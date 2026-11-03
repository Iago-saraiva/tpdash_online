"""TP DASH Agente: roda no servidor do cliente e responde às consultas do site TP DASH online.

- Lê o banco do Puma (Firebird) em transação SOMENTE LEITURA, com a senha que fica só no config.ini daqui.
- Quem abre a conexão é o agente (HTTPS de dentro para fora): não precisa abrir porta nem VPN.
- O site identifica a empresa pela chave do agente ([nuvem] chave no config.ini).

Uso: python agente.py            (roda até ser parado; reconecta sozinho se a internet cair)
     python agente.py --testar   (confere o banco e o site e sai)
"""
import base64
import configparser
import datetime as dt
import decimal
import gzip
import http.client
import json
import logging
import os
import re
import sys
import threading
import time
import ssl
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler

import config
import cofre
import db

VERSAO = "2.0.0"
CONSULTAS_AO_MESMO_TEMPO = 8
PASTA = config.BASE_DIR

LOG = os.path.join(PASTA, "dados", "agente.log")
log = logging.getLogger("agente")
log.setLevel(logging.INFO)
if sys.stdout is not None:            # no app com janela não existe console
    log.addHandler(logging.StreamHandler(sys.stdout))


def iniciar_log():
    """Só o agente em funcionamento grava o agente.log (a janela de configuração só lê)."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    h = RotatingFileHandler(LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)


PROPRIO_INI = config.CONFIG_PATH     # config.ini do agente ([nuvem] e, se quiser, [banco])


def _ler_proprio():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(PROPRIO_INI, encoding="utf-8")
    return cp


def usar_config_do_painel():
    """[banco] usar_config_do_painel = caminho do config.ini do TP DASH já instalado neste servidor:
    o agente lê o banco de lá (somente leitura) e a senha não precisa ser copiada."""
    cp = _ler_proprio()
    caminho = (cp["banco"].get("usar_config_do_painel", "") if cp.has_section("banco") else "").strip()
    if caminho:
        config.CONFIG_PATH = caminho
        config.SO_LEITURA = True
        return caminho
    return None


def ler_nuvem():
    """Endereço do site e a lista de empresas deste agente: [(banco, chave), ...].
    [nuvem] chave = empresa do banco principal; [nuvem:ID] chave = empresa do [banco:ID]
    (ou de outro banco, com "banco = ..."). Cada empresa tem a sua chave, gerada no site."""
    cp = _ler_proprio()
    nv = cp["nuvem"] if cp.has_section("nuvem") else {}
    endereco = (nv.get("endereco") or "").strip().rstrip("/")
    empresas = []
    chave = (nv.get("chave") or "").strip()
    if chave:
        empresas.append(((nv.get("banco") or "principal").strip().lower(), chave))
    for sec in cp.sections():
        m = re.fullmatch(r"\s*nuvem\s*:\s*([A-Za-z0-9_-]{1,30})\s*", sec)
        if m:
            ch = (cp[sec].get("chave") or "").strip()
            if ch:
                empresas.append(((cp[sec].get("banco") or m.group(1)).strip().lower(), ch))
    if not endereco or not empresas:
        raise SystemExit("Preencha [nuvem] endereco e chave no config.ini (a chave é gerada no site, em Empresas).")
    erro = erro_endereco(endereco)
    if erro:
        raise SystemExit(erro)
    return endereco, empresas


def erro_endereco(endereco):
    endereco = (endereco or "").strip()
    if not endereco:
        return "Informe o endereço do site."
    if endereco.startswith("https://"):
        return None
    if endereco.startswith("http://") and rede_interna(urllib.parse.urlsplit(endereco).hostname or ""):
        return None
    return ("O endereço do site precisa começar com https://. Sem https, só para testes na rede interna "
            "(localhost, IP 192.168.x.x / 10.x.x.x / 172.16-31.x.x ou nome do computador).")


def rede_interna(host):
    """http (sem cifragem) só é aceito dentro da rede interna, para testes."""
    import ipaddress
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".local") or host.endswith(".lan"):
        return True
    return "." not in host and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", host) is not None


class ErroHTTP(Exception):
    def __init__(self, code, texto=""):
        super().__init__(f"HTTP {code} {texto}".strip())
        self.code = code


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


def so_leitura(sql):
    """Só aceita uma única consulta SELECT/WITH. A garantia principal é a transação somente leitura do banco."""
    limpo = db._sem_comentarios_e_textos(sql or "").strip().rstrip(";").strip()
    if ";" in limpo or not re.match(r"^(SELECT|WITH)\b", limpo, re.IGNORECASE):
        raise db.ErroBanco("O agente só executa consultas SELECT.")
    return sql


class BancoComErro:
    """Banco que não abriu: a empresa conecta no site mesmo assim e cada consulta devolve o erro."""

    def __init__(self, erro):
        self.erro = f"Não consegui abrir o banco no servidor da empresa: {erro}"

    def _falha(self, *a, **k):
        raise db.ErroBanco(self.erro)

    consultar = consultar_blob = colunas = testar = _falha


class Agente:
    """Uma ligação com o site para UMA empresa (um banco + a chave dessa empresa)."""

    def __init__(self, cfg, banco_id, endereco, chave):
        self.cfg = cfg
        self.rotulo = banco_id
        self.cfg_banco = {**cfg, **cfg["bancos"][banco_id]}
        try:
            self.banco = db.abrir(self.cfg_banco)
        except Exception as e:  # noqa: BLE001 - um banco com problema não derruba as outras empresas
            log.error("[%s] Não consegui abrir o banco: %s", banco_id, e)
            self.banco = BancoComErro(e)
        self.endereco, self.chave = endereco, chave
        u = urllib.parse.urlsplit(self.endereco)
        self._https = u.scheme == "https"
        # no Windows "localhost" tenta IPv6 primeiro e perde ~2 s a cada conexão: vai direto no IPv4
        self._host = "127.0.0.1" if u.hostname == "localhost" else u.hostname
        self._porta = u.port or (443 if self._https else 80)
        self._base = u.path.rstrip("/")
        self._ssl = ssl.create_default_context() if self._https else None
        self._local = threading.local()      # uma conexão aberta (keep-alive) por thread
        self.pool = ThreadPoolExecutor(max_workers=CONSULTAS_AO_MESMO_TEMPO, thread_name_prefix="consulta")
        self.parar = threading.Event()

    # -------------------------------------------------------------- HTTP
    def _conexao(self, timeout):
        c = getattr(self._local, "con", None)
        if c is None:
            if self._https:
                c = http.client.HTTPSConnection(self._host, self._porta, timeout=timeout, context=self._ssl)
            else:
                c = http.client.HTTPConnection(self._host, self._porta, timeout=timeout)
            self._local.con = c
        c.timeout = timeout
        if c.sock is not None:
            c.sock.settimeout(timeout)
        return c

    def _fechar_conexao(self):
        c = getattr(self._local, "con", None)
        self._local.con = None
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    def _chamar(self, metodo, caminho, dados=None, timeout=30):
        corpo, cab = None, {"Authorization": f"Bearer {self.chave}", "User-Agent": f"TPDashAgente/{VERSAO}"}
        if dados is not None:
            corpo = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            cab["Content-Type"] = "application/json"
            if len(corpo) > 4096:
                corpo = gzip.compress(corpo, 6)
                cab["Content-Encoding"] = "gzip"
        for tentativa in (1, 2):
            c = self._conexao(timeout)
            try:
                c.request(metodo, self._base + caminho, body=corpo, headers=cab)
                r = c.getresponse()
                conteudo = r.read()
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError,
                    http.client.CannotSendRequest, http.client.ResponseNotReady):
                # a conexão guardada foi fechada pelo site (ociosa): abre outra e tenta uma vez mais
                self._fechar_conexao()
                if tentativa == 2:
                    raise
                continue
            except Exception:
                self._fechar_conexao()
                raise
            if r.will_close:
                self._fechar_conexao()
            if r.status >= 400:
                raise ErroHTTP(r.status, r.reason)
            return json.loads(conteudo or b"{}")

    def ola(self):
        try:
            descricao = self.banco.testar()
        except Exception as e:  # noqa: BLE001 - avisa o site que o banco está com problema, mas conecta
            descricao = f"ERRO NO BANCO: {e}"
            log.warning("[%s] %s", self.rotulo, descricao)
        r = self._chamar("POST", "/agente/ola", {
            "versao": VERSAO, "modo": self.cfg_banco["modo"], "empresa": self.cfg_banco["empresa"], "descricao": descricao,
            "status_movimento": self.cfg["status_movimento"], "status_lancamento": self.cfg["status_lancamento"]})
        self.nome_no_site = r.get("empresa")
        log.info("[%s] Conectado ao site como %s (%s)", self.rotulo, r.get("empresa"), descricao)
        return r.get("espera", 25)

    # -------------------------------------------------------------- execução dos pedidos
    def executar(self, p):
        resp = {"id": p.get("id")}
        inicio = time.monotonic()
        try:
            op = p.get("op")
            params = [decodificar(x) for x in p.get("params") or []]
            if op == "consultar":
                limite = p.get("limite")
                cols, linhas, mais = self.banco.consultar(so_leitura(p["sql"]), params, int(limite) if limite else None)
                resp.update(ok=True, colunas=cols, linhas=[[codificar(v) for v in r] for r in linhas], mais=mais)
            elif op == "consultar_blob":
                cols, linhas, _ = self.banco.consultar_blob(so_leitura(p["sql"]), params)
                resp.update(ok=True, colunas=cols, linhas=[[codificar(v) for v in r] for r in linhas])
            elif op == "colunas":
                resp.update(ok=True, colunas=self.banco.colunas(so_leitura(p["sql"]), params))
            elif op == "testar":
                resp.update(ok=True, texto=self.banco.testar())
            else:
                resp.update(ok=False, erro=f"Operação desconhecida: {op}")
        except db.ErroBanco as e:
            resp.update(ok=False, erro=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] Erro no pedido %s", self.rotulo, p.get("op"))
            resp.update(ok=False, erro=f"Erro no agente: {e}")
        no_banco = time.monotonic() - inicio
        for tentativa in range(3):
            try:
                self._chamar("POST", "/agente/resposta", resp, timeout=120)
                total = time.monotonic() - inicio
                linhas = len(resp.get("linhas") or [])
                log.info("[%s] Consulta %s: %.1f s no banco, %.1f s no total, %s linhas%s", self.rotulo, p.get("op"), no_banco,
                        total, linhas, "" if resp.get("ok") else " (erro)")
                return
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] Falha ao devolver resposta (tentativa %s): %s", self.rotulo, tentativa + 1, e)
                time.sleep(2 * (tentativa + 1))

    # -------------------------------------------------------------- laço principal
    def rodar(self):
        espera_erro = 5
        while not self.parar.is_set():
            try:
                espera = self.ola()
                espera_erro = 5
                while not self.parar.is_set():
                    r = self._chamar("GET", "/agente/pedidos", timeout=espera + 20)
                    for p in r.get("pedidos", []):
                        self.pool.submit(self.executar, p)
            except ErroHTTP as e:
                if e.code == 401:
                    log.error("[%s] O site recusou a chave (chave errada, bloqueada ou empresa desativada). Nova tentativa em 5 min.", self.rotulo)
                    self.parar.wait(300)
                    continue
                log.warning("[%s] Site respondeu %s. Nova tentativa em %s s.", self.rotulo, e.code, espera_erro)
            except Exception as e:  # noqa: BLE001 - internet caiu, site fora do ar...
                log.warning("[%s] Sem conexão com o site (%s). Nova tentativa em %s s.", self.rotulo, e, espera_erro)
            self.parar.wait(espera_erro)
            espera_erro = min(espera_erro * 2, 60)


def cfg_base():
    return {"status_movimento": dict(config._PADRAO_STATUS_MOV), "status_lancamento": dict(config._PADRAO_STATUS_LAN),
            "limite_linhas": 5000, "bancos": {}}


def agente_da_empresa(endereco, emp):
    """Agente de uma empresa guardada no cofre: {"id", "nome", "chave", "banco": {...}}."""
    cfg = cfg_base()
    cfg["bancos"][emp["id"]] = {"id": emp["id"], "nome": emp.get("nome") or emp["id"], **cofre.banco_completo(emp.get("banco"))}
    return Agente(cfg, emp["id"], endereco.strip().rstrip("/"), emp["chave"])


def testar_empresa(endereco, emp):
    """Usado pela janela: confere o banco e a chave no site. Devolve (ok, texto)."""
    erro = erro_endereco(endereco)
    if erro:
        return False, erro
    a = agente_da_empresa(endereco, emp)
    try:
        banco = a.banco.testar()
    except Exception as e:  # noqa: BLE001
        return False, f"Banco: {e}"
    try:
        a.ola()
    except ErroHTTP as e:
        if e.code == 401:
            return False, f"Banco ok ({banco}). Site recusou a chave (chave errada, bloqueada ou empresa desativada)."
        return False, f"Banco ok ({banco}). Site respondeu {e.code}."
    except Exception as e:  # noqa: BLE001
        return False, f"Banco ok ({banco}). Sem conexão com o site: {e}"
    finally:
        a._fechar_conexao()
        try:
            a.banco.fechar_tudo()
        except Exception:  # noqa: BLE001
            pass
    return True, f"Banco ok ({banco}). Site ok: conectado como {a.nome_no_site}."


def importar_config_ini():
    """Lê o config.ini antigo (e o do painel, se ele aponta para lá) e devolve (site, empresas) para o cofre."""
    usar_config_do_painel()
    cfg = config.carregar()
    endereco, empresas = ler_nuvem()
    lista = []
    for banco_id, chave in empresas:
        b = cfg["bancos"].get(banco_id)
        if not b:
            continue
        lista.append({"id": cofre.id_empresa(chave), "nome": b.get("nome") or banco_id, "chave": chave,
                      "banco": {k: b[k] for k in cofre.BANCO_PADRAO}})
    return endereco, lista


def criar_agentes():
    if cofre.existe():
        d = cofre.carregar()
        endereco = (d.get("site") or "").strip().rstrip("/")
        erro = erro_endereco(endereco)
        if erro:
            raise SystemExit(erro + " Abra o TP DASH Agente e confira a configuração.")
        agentes = [agente_da_empresa(endereco, e) for e in d.get("empresas", []) if e.get("ativa", True)]
        if not agentes:
            raise SystemExit("Nenhuma empresa configurada. Abra o TP DASH Agente e cadastre a empresa.")
        return endereco, agentes
    origem = usar_config_do_painel()
    if origem:
        log.info("Usando os bancos configurados em %s", origem)
    cfg = config.carregar()
    endereco, empresas = ler_nuvem()
    agentes, vistos = [], set()
    for banco_id, chave in empresas:
        if banco_id not in cfg["bancos"]:
            log.error("[%s] Não existe [banco:%s] no config.ini. Essa empresa ficou de fora.", banco_id, banco_id)
            continue
        if banco_id in vistos:
            log.error("[%s] Banco repetido em mais de uma seção [nuvem]. Só a primeira vale.", banco_id)
            continue
        vistos.add(banco_id)
        agentes.append(Agente(cfg, banco_id, endereco, chave))
    if not agentes:
        raise SystemExit("Nenhuma empresa ficou configurada. Confira as seções [nuvem] e [banco] do config.ini.")
    return endereco, agentes


def main():
    iniciar_log()
    endereco, agentes = criar_agentes()
    if "--testar" in sys.argv:
        for a in agentes:
            print(f"[{a.rotulo}] Banco:", a.banco.testar())
            print(f"[{a.rotulo}] Site:", a.endereco, "->", "ok" if a.ola() else "?")
        return
    log.info("TP DASH Agente %s iniciado. Site: %s. Empresas: %s", VERSAO, endereco, ", ".join(a.rotulo for a in agentes))
    threads = [threading.Thread(target=a.rodar, name=f"empresa-{a.rotulo}", daemon=True) for a in agentes]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        for a in agentes:
            a.parar.set()


if __name__ == "__main__":
    main()
