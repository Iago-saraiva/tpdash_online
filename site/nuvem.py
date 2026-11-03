"""TP DASH online: ponte entre o site e os agentes instalados nos servidores dos clientes.

O agente abre a conexão (de dentro para fora) e busca os pedidos por "long polling":
  POST /agente/ola        ao conectar: informa o banco (modo, código da empresa, status...)
  GET  /agente/pedidos    espera até ~25 s por pedidos de consulta da empresa dele
  POST /agente/resposta   devolve o resultado de um pedido
Toda chamada leva a chave do agente (Authorization: Bearer <empresa>.<segredo>). A empresa vem
SEMPRE da chave conferida no site, nunca de algo enviado pelo agente ou pelo navegador.
Os pedidos ficam em memória: o site deve rodar em UM processo (vários threads).
"""
import base64
import datetime as dt
import decimal
import queue
import secrets
import threading
import time

import db

ESPERA_PEDIDOS = 25          # segundos que o GET /agente/pedidos fica aberto esperando
ONLINE_SEGUNDOS = ESPERA_PEDIDOS + 20   # sem buscar pedidos há mais que isso = agente fora do ar
RETIRADA_SEGUNDOS = ESPERA_PEDIDOS + 10 # pedido não buscado pelo agente nesse tempo = agente caiu
TEMPO_RESPOSTA = 180         # tempo máximo de uma consulta


class _Agente:
    def __init__(self, empresa_id):
        self.empresa_id = empresa_id
        self.fila = queue.Queue()
        self.pendentes = {}               # id -> [Event, resposta]
        self.trava = threading.Lock()
        self.visto = 0.0
        self.info = {}                    # o que o agente mandou no /ola (sem senhas)
        self.versao = ""
        self.ip = ""

    @property
    def online(self):
        return time.time() - self.visto <= ONLINE_SEGUNDOS

    def pedir(self, op, **dados):
        if not self.online:
            raise db.ErroBanco("O servidor da empresa está desligado ou sem internet (agente desconectado). "
                               "Confira se o serviço TP DASH Agente está rodando no servidor.")
        rid = secrets.token_hex(12)
        ev = threading.Event()
        with self.trava:
            self.pendentes[rid] = [ev, None, time.time()]
        pedido = {"id": rid, "op": op, **dados}
        self.fila.put(pedido)
        # se o agente caiu sem avisar, ninguém busca o pedido: desiste logo com um aviso claro
        if not ev.wait(RETIRADA_SEGUNDOS) and not pedido.get("_retirado"):
            pedido["_cancelado"] = True
            with self.trava:
                self.pendentes.pop(rid, None)
            self.visto = 0.0
            raise db.ErroBanco("O servidor da empresa está desligado ou sem internet (agente desconectado). "
                               "Confira se o serviço TP DASH Agente está rodando no servidor.")
        if not ev.is_set() and not ev.wait(TEMPO_RESPOSTA - RETIRADA_SEGUNDOS):
            with self.trava:
                self.pendentes.pop(rid, None)
            raise db.ErroBanco("O servidor da empresa demorou demais para responder. Tente um período menor.")
        resp = self.pendentes.pop(rid, [None, None, 0])[1] or {}
        if not resp.get("ok"):
            raise db.ErroBanco(resp.get("erro") or "Erro no servidor da empresa.")
        return resp

    def responder(self, resp):
        """Entrega a resposta a quem pediu. Devolve quantos segundos o pedido levou (None = pedido desconhecido)."""
        with self.trava:
            p = self.pendentes.get(str(resp.get("id")))
        if not p:                          # pedido desconhecido (expirou ou é de outro agente): ignora
            return None
        p[1] = resp
        p[0].set()
        return time.time() - p[2]

    def proximos(self, espera, maximo=8):
        """Pedidos para o agente: espera o primeiro até `espera` segundos e junta os que já estiverem na fila."""
        self.visto = time.time()
        lista, fim = [], time.time() + espera
        try:
            while not lista and time.time() < fim:
                p = self.fila.get(timeout=max(fim - time.time(), 0.01))
                if not p.get("_cancelado"):
                    lista.append(p)
            while len(lista) < maximo:
                p = self.fila.get_nowait()
                if not p.get("_cancelado"):
                    lista.append(p)
        except queue.Empty:
            pass
        for p in lista:
            p["_retirado"] = True
        return [{k: v for k, v in p.items() if not k.startswith("_")} for p in lista]


_AGENTES = {}
_TRAVA = threading.Lock()


def agente(empresa_id):
    with _TRAVA:
        if empresa_id not in _AGENTES:
            _AGENTES[empresa_id] = _Agente(empresa_id)
        return _AGENTES[empresa_id]


def estado(empresa_id):
    a = _AGENTES.get(empresa_id)
    if not a or not a.visto:
        return {"online": False, "visto": None, "versao": "", "banco": ""}
    return {"online": a.online, "visto": dt.datetime.fromtimestamp(a.visto).strftime("%d/%m/%Y %H:%M:%S"),
            "versao": a.versao, "banco": a.info.get("descricao", "")}


def info(empresa_id):
    a = _AGENTES.get(empresa_id)
    return dict(a.info) if a else {}


# ------------------------------------------------------------------ valores que atravessam o JSON
def codificar(v):
    if isinstance(v, dt.datetime):
        return {"$dt": v.isoformat()}
    if isinstance(v, dt.date):
        return {"$d": v.isoformat()}
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(v)).decode("ascii")}
    return v


def decodificar(v):
    if isinstance(v, dict) and len(v) == 1:
        k, x = next(iter(v.items()))
        if k == "$dt":
            return dt.datetime.fromisoformat(x)
        if k == "$d":
            return dt.date.fromisoformat(x)
        if k == "$b":
            return base64.b64decode(x)
    return v


class BancoRemoto:
    """Mesmo jeito de usar do db.BancoFirebird, mas a consulta roda no agente da empresa."""

    def __init__(self, empresa_id):
        self.empresa_id = empresa_id

    @property
    def descricao(self):
        return info(self.empresa_id).get("descricao") or "servidor da empresa"

    def _ag(self):
        return agente(self.empresa_id)

    def consultar(self, sql, params=(), limite=None):
        r = self._ag().pedir("consultar", sql=sql, params=[codificar(p) for p in params], limite=limite)
        return r["colunas"], r["linhas"], bool(r.get("mais"))

    def consultar_blob(self, sql, params=()):
        r = self._ag().pedir("consultar_blob", sql=sql, params=[codificar(p) for p in params])
        return r["colunas"], [[decodificar(v) for v in linha] for linha in r["linhas"]], False

    def colunas(self, sql, params=()):
        return self._ag().pedir("colunas", sql=sql, params=[codificar(p) for p in params])["colunas"]

    def testar(self):
        return self._ag().pedir("testar")["texto"]

    def fechar_tudo(self):
        pass
