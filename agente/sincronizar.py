"""Sincronização: o agente manda para o site uma cópia das tabelas que o TP DASH usa.

Primeira vez (carga inicial): lê cada tabela inteira e envia tudo, em pacotes.
Depois, a cada intervalo configurado: lê de novo e envia só o que mudou (linhas novas, alteradas e as
chaves das apagadas). Para saber o que mudou, o agente guarda aqui, em dados\\sinc_<empresa>.sqlite, uma
"foto" de cada linha: a chave e um resumo (hash) do conteúdo. Nada é gravado no banco do Puma.

A foto só é atualizada depois que o site confirma o pacote: se a internet cair no meio, a rodada
seguinte reenvia o que faltou. Se o site perder a cópia (ex.: banco do site apagado), ele avisa pela
contagem de linhas e o agente refaz a carga daquela tabela.
"""
import datetime as dt
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time

import config
import db

log = logging.getLogger("agente")

# Tabelas que os relatórios do TP DASH usam (a lista pode vir do site no futuro).
TABELAS_PADRAO = [
    "TMOV", "TMOVITENS", "TTRBMOV", "TPRODUTO", "TPRODSALDO", "FCFO", "FLAN", "FLANRATCCUSTO", "GFILIAL",
    "TTIPOMOV", "TVENDEDOR", "TGRUPO", "FCCUSTO", "AMAQUINAS", "AMAQUINASGRUPO", "TLOCALEST", "TNATUREZA",
    "TMOVNFE", "TMOVNFSE", "TCONDPGTO", "GDEPARTAMENTO", "TSTRIBUTARIA", "FTIPODOC",
]
# chaves primárias das tabelas do Puma (usadas quando o banco não informa, como no modo demonstração)
CHAVES_CONHECIDAS = {
    "AMAQUINAS": ["CODIGO", "CODEMPRESA"], "AMAQUINASGRUPO": ["CODIGO", "CODEMPRESA"], "FCCUSTO": ["COD", "CODEMPRESA"],
    "FCFO": ["CODCFO", "CODEMPRESA"], "FLAN": ["IDLAN", "CODEMPRESA"], "FTIPODOC": ["CODTIPODOC", "CODEMPRESA"],
    "GDEPARTAMENTO": ["CODDEPARTAMENTO", "CODEMPRESA"], "GFILIAL": ["CODFILIAL", "CODEMPRESA"],
    "TCONDPGTO": ["CODCONDPGTO", "CODEMPRESA"], "TGRUPO": ["CODGRUPO", "CODEMPRESA"], "TLOCALEST": ["CODLOC", "CODEMPRESA"],
    "TMOV": ["IDMOV", "CODEMPRESA"], "TMOVITENS": ["IDMOV", "NSEQ", "CODEMPRESA"], "TMOVNFE": ["IDMOV", "CODEMPRESA"],
    "TMOVNFSE": ["IDMOV", "CODEMPRESA"], "TNATUREZA": ["CODNAT", "CODEMPRESA"],
    "TPRODSALDO": ["CODPRD", "CODLOC", "CODFILIAL", "CODEMPRESA"], "TPRODUTO": ["CODPRD", "CODEMPRESA"],
    "TSTRIBUTARIA": ["CODSIT", "CODEMPRESA"], "TTIPOMOV": ["CODTIPOMOV", "CODEMPRESA"],
    "TTRBMOV": ["IDMOV", "NSEQITMMOV", "CODTRB", "CODEMPRESA"], "TVENDEDOR": ["CODVEN", "CODEMPRESA"],
}
# colunas que nunca saem do servidor do cliente (senhas, certificados, tokens de acesso)
SENSIVEIS = re.compile(r"SENHA|PASSWORD|TOKEN|CERTIFICADO|CSRT|SISDEVHASH|INTEGRATIONKEY|USUARIOSPC", re.I)
PACOTE = 2000                 # linhas por envio
INTERVALOS = (5, 10, 15, 30, 60, 120, 240)

PADRAO = {"ativa": True, "intervalo_min": 15, "pausa_inicio": "", "pausa_fim": ""}


def ler_config():
    """Configuração da sincronização: do cofre (app com janela) ou da seção [sincronizacao] do config.ini."""
    import cofre
    cfg = dict(PADRAO)
    try:
        if cofre.existe():
            cfg.update((cofre.carregar() or {}).get("sincronizacao") or {})
            return _validar(cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("Não consegui ler a configuração da sincronização: %s", e)
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(config.CONFIG_PATH, encoding="utf-8")
    if cp.has_section("sincronizacao"):
        s = cp["sincronizacao"]
        cfg["ativa"] = s.get("ativa", "sim").strip().lower() in ("sim", "1", "true", "s")
        cfg["intervalo_min"] = s.get("intervalo_min", cfg["intervalo_min"])
        cfg["pausa_inicio"] = s.get("pausa_inicio", "")
        cfg["pausa_fim"] = s.get("pausa_fim", "")
    return _validar(cfg)


def _validar(cfg):
    try:
        cfg["intervalo_min"] = max(1, int(float(cfg.get("intervalo_min") or 15)))
    except (TypeError, ValueError):
        cfg["intervalo_min"] = 15
    for k in ("pausa_inicio", "pausa_fim"):
        v = str(cfg.get(k) or "").strip()
        cfg[k] = v if re.match(r"^\d{1,2}:\d{2}$", v) else ""
    cfg["ativa"] = bool(cfg.get("ativa", True))
    return cfg


def em_pausa(cfg, agora=None):
    """Horário em que a sincronização não roda (ex.: backup da noite). Aceita faixa que passa da meia-noite."""
    if not cfg["pausa_inicio"] or not cfg["pausa_fim"]:
        return False
    agora = agora or dt.datetime.now()
    m = agora.hour * 60 + agora.minute
    h1, m1 = map(int, cfg["pausa_inicio"].split(":"))
    h2, m2 = map(int, cfg["pausa_fim"].split(":"))
    a, b = h1 * 60 + m1, h2 * 60 + m2
    return a <= m < b if a <= b else (m >= a or m < b)


def arquivo_estado(eid):
    return os.path.join(config.BASE_DIR, "dados", f"sinc_{eid}.json")


def ler_estado(eid):
    try:
        with open(arquivo_estado(eid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pedir_carga_completa(eid):
    """Chamado pela janela: a próxima rodada desta empresa refaz a carga inicial de todas as tabelas."""
    est = ler_estado(eid)
    est["refazer"] = True
    _gravar_estado(eid, est)


def _gravar_estado(eid, est):
    os.makedirs(os.path.dirname(arquivo_estado(eid)), exist_ok=True)
    tmp = arquivo_estado(eid) + ".novo"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False, indent=1)
    os.replace(tmp, arquivo_estado(eid))


# ------------------------------------------------------------------ estrutura das tabelas
_TIPOS_FB = {7: "inteiro", 8: "inteiro", 16: "inteiro", 10: "numero", 27: "numero", 12: "data", 13: "hora",
             35: "datahora", 14: "texto", 37: "texto", 23: "logico", 24: "numero", 25: "numero", 26: "numero",
             28: "hora", 29: "datahora"}


def estrutura(banco, tabela):
    """[(coluna, tipo)], [colunas da chave]. Tipos: inteiro, numero, data, hora, datahora, texto, logico."""
    if isinstance(banco, db.BancoDemo):
        _, linhas, _ = banco.consultar(f"PRAGMA table_info({tabela})")
        if not linhas:
            raise db.ErroBanco(f"Tabela {tabela} não existe")
        cols, chave = [], []
        for _cid, nome, tipo, _nn, _pad, pk in linhas:
            t = (tipo or "").upper()
            n = nome.upper()
            tipo_c = "inteiro" if "INT" in t else "numero" if t in ("REAL", "NUMERIC", "FLOAT") else "texto"
            if tipo_c == "texto" and n.startswith(("DATA", "DT")):     # demonstração: datas guardadas como texto
                _, ex, _ = banco.consultar(f"SELECT {nome} FROM {tabela} WHERE {nome} IS NOT NULL", (), 1)
                tipo_c = "datahora" if ex and len(str(ex[0][0])) > 10 else "data"
            cols.append((n, tipo_c))
            if pk:
                chave.append(nome.upper())
        return [c for c in cols if not SENSIVEIS.search(c[0])], chave or _chave_conhecida(tabela, cols)
    _, linhas, _ = banco.consultar(
        "SELECT TRIM(RF.RDB$FIELD_NAME), F.RDB$FIELD_TYPE, F.RDB$FIELD_SCALE FROM RDB$RELATION_FIELDS RF "
        "JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME = RF.RDB$FIELD_SOURCE WHERE RF.RDB$RELATION_NAME = ? "
        "ORDER BY RF.RDB$FIELD_POSITION", (tabela,))
    if not linhas:
        raise db.ErroBanco(f"Tabela {tabela} não existe")
    cols = []
    for nome, tipo, escala in linhas:
        if tipo == 261:            # BLOB (textos longos, imagens): fica fora da cópia
            continue
        t = _TIPOS_FB.get(tipo, "texto")
        if t == "inteiro" and (escala or 0) < 0:
            t = "numero"
        if not SENSIVEIS.search(nome):
            cols.append((nome, t))
    _, pk, _ = banco.consultar(
        "SELECT TRIM(S.RDB$FIELD_NAME) FROM RDB$RELATION_CONSTRAINTS RC JOIN RDB$INDEX_SEGMENTS S "
        "ON S.RDB$INDEX_NAME = RC.RDB$INDEX_NAME WHERE RC.RDB$RELATION_NAME = ? "
        "AND RC.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' ORDER BY S.RDB$FIELD_POSITION", (tabela,))
    return cols, [r[0] for r in pk] or _chave_conhecida(tabela, cols)


def _chave_conhecida(tabela, cols):
    nomes = {c[0] for c in cols}
    k = CHAVES_CONHECIDAS.get(tabela.upper()) or []
    return k if all(c in nomes for c in k) else []


# ------------------------------------------------------------------ foto local
class Foto:
    def __init__(self, eid):
        self.caminho = os.path.join(config.BASE_DIR, "dados", f"sinc_{eid}.sqlite")
        os.makedirs(os.path.dirname(self.caminho), exist_ok=True)
        self.con = sqlite3.connect(self.caminho, check_same_thread=False)
        self.con.execute("CREATE TABLE IF NOT EXISTS foto (tabela TEXT, k TEXT, h TEXT, PRIMARY KEY (tabela, k))")
        self.con.execute("CREATE TABLE IF NOT EXISTS tabelas (tabela TEXT PRIMARY KEY, assinatura TEXT)")
        self.con.commit()

    def carregar(self, tabela):
        return dict(self.con.execute("SELECT k, h FROM foto WHERE tabela = ?", (tabela,)))

    def assinatura(self, tabela):
        r = self.con.execute("SELECT assinatura FROM tabelas WHERE tabela = ?", (tabela,)).fetchone()
        return r[0] if r else None

    def aplicar(self, tabela, novas, apagadas, assinatura):
        with self.con:
            self.con.executemany("INSERT OR REPLACE INTO foto (tabela, k, h) VALUES (?, ?, ?)",
                                 [(tabela, k, h) for k, h in novas])
            self.con.executemany("DELETE FROM foto WHERE tabela = ? AND k = ?", [(tabela, k) for k in apagadas])
            self.con.execute("INSERT OR REPLACE INTO tabelas (tabela, assinatura) VALUES (?, ?)", (tabela, assinatura))

    def esquecer(self, tabela=None):
        with self.con:
            if tabela:
                self.con.execute("DELETE FROM foto WHERE tabela = ?", (tabela,))
                self.con.execute("DELETE FROM tabelas WHERE tabela = ?", (tabela,))
            else:
                self.con.execute("DELETE FROM foto")
                self.con.execute("DELETE FROM tabelas")

    def fechar(self):
        self.con.close()


def _hash(linha):
    return hashlib.md5(json.dumps(linha, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:20]


# ------------------------------------------------------------------ uma rodada
class Sincronizador:
    """Roda em segundo plano dentro do agente de uma empresa."""

    def __init__(self, agente):
        self.ag = agente
        self.eid = agente.rotulo
        self.trava = threading.Lock()
        self.tabelas = list(TABELAS_PADRAO)

    def resumo(self):
        est = ler_estado(self.eid)
        cfg = ler_config()
        return {k: est.get(k) for k in ("ultima", "proxima", "duracao_s", "inseridas", "alteradas", "apagadas",
                                        "carga_inicial", "erro", "tabelas", "linhas")} | {
            "intervalo_min": cfg["intervalo_min"] if cfg["ativa"] else None, "ativa": cfg["ativa"],
            "pausa": f"{cfg['pausa_inicio']} às {cfg['pausa_fim']}" if cfg["pausa_inicio"] else ""}

    def laco(self):
        """Espera o intervalo, roda, repete. A primeira rodada começa logo depois de o agente conectar."""
        espera = 20
        while not self.ag.parar.wait(espera):
            cfg = ler_config()
            est = ler_estado(self.eid)
            if not cfg["ativa"]:
                espera = 60
                continue
            ultima = est.get("ultima_ts") or 0
            falta = ultima + cfg["intervalo_min"] * 60 - time.time()
            if est.get("refazer") or not est.get("carga_completa"):
                falta = min(falta, 0)
            if falta > 0:
                espera = min(falta, 60)
                continue
            if em_pausa(cfg):
                espera = 60
                continue
            try:
                self.rodada()
            except Exception as e:  # noqa: BLE001 - nunca derruba o agente
                if getattr(e, "code", None) == 404:
                    msg = "O site ainda não tem a sincronização: atualize o TP DASH online."
                    log.warning("[%s] %s", self.eid, msg)
                else:
                    msg = str(e)
                    log.exception("[%s] Erro na sincronização", self.eid)
                est = ler_estado(self.eid)
                est.update(erro=msg[:300], ultima_ts=time.time())
                _gravar_estado(self.eid, est)
            espera = 20

    def _enviar(self, dados):
        return self.ag._chamar("POST", "/agente/sinc", dados, timeout=180)

    def rodada(self):
        with self.trava:
            return self._rodada()

    def _rodada(self):
        inicio = time.time()
        est = ler_estado(self.eid)
        foto = Foto(self.eid)
        try:
            if est.get("refazer"):
                foto.esquecer()
                est.pop("refazer", None)
                est["carga_completa"] = False
                est["carga_inicial"] = "em andamento"
                _gravar_estado(self.eid, est)
            tot = {"inseridas": 0, "alteradas": 0, "apagadas": 0}
            completa, linhas_total, erros = True, 0, []
            log.info("[%s] Sincronização: começando a rodada", self.eid)
            for tabela in self.tabelas:
                if self.ag.parar.is_set():
                    completa = False
                    break
                try:
                    r = self._tabela(foto, tabela)
                except db.ErroBanco as e:
                    if "não existe" in str(e) or "Table unknown" in str(e) or "no such table" in str(e):
                        continue          # este banco não tem a tabela: segue sem ela
                    erros.append(f"{tabela}: {e}")
                    completa = False
                    continue
                for k in tot:
                    tot[k] += r[k]
                linhas_total += r["linhas"]
            dur = round(time.time() - inicio, 1)
            fim = dt.datetime.now()
            proxima = fim + dt.timedelta(minutes=ler_config()["intervalo_min"])
            est.update(
                ultima=fim.strftime("%d/%m/%Y %H:%M:%S"), ultima_ts=time.time(), duracao_s=dur,
                proxima=proxima.strftime("%d/%m/%Y %H:%M"), linhas=linhas_total, tabelas=len(self.tabelas),
                erro="; ".join(erros)[:300], **tot)
            if completa and not est.get("carga_completa"):
                est["carga_completa"] = True
                est["carga_inicial"] = f"concluída {fim.strftime('%d/%m %H:%M')} ({dur:.0f} s)"
            elif not est.get("carga_completa"):
                est["carga_inicial"] = "em andamento"
            if ler_estado(self.eid).get("refazer"):      # pedido na janela durante a rodada: vale para a próxima
                est["refazer"] = True
            _gravar_estado(self.eid, est)
            log.info("[%s] Sincronização: %s novas, %s alteradas, %s apagadas em %.1f s (%s linhas no total)",
                     self.eid, tot["inseridas"], tot["alteradas"], tot["apagadas"], dur, linhas_total)
            try:
                self._enviar({"resumo": self.resumo()})
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] Não consegui mandar o resumo da sincronização: %s", self.eid, e)
            return est
        finally:
            foto.fechar()

    def _tabela(self, foto, tabela):
        banco = self.ag.banco
        cols, chave = estrutura(banco, tabela)
        nomes = [c[0] for c in cols]
        assinatura = json.dumps([cols, chave])
        if foto.assinatura(tabela) not in (None, assinatura):
            log.info("[%s] %s mudou de estrutura: refazendo a carga dela", self.eid, tabela)
            foto.esquecer(tabela)
        antes = foto.carregar(tabela)
        recomecar = not antes
        pos_chave = [nomes.index(c) for c in chave if c in nomes] if chave else []
        if len(pos_chave) != len(chave):
            pos_chave = []
        filtro, params = "", ()
        if "CODEMPRESA" in nomes:
            filtro, params = " WHERE CODEMPRESA = ?", (self.ag.cfg_banco["empresa"],)
        sql = "SELECT " + ", ".join(nomes) + f" FROM {tabela}{filtro}"
        r = {"inseridas": 0, "alteradas": 0, "apagadas": 0, "linhas": 0}
        vistas = set()
        buf, buf_foto = [], []
        base = {"tabela": tabela, "colunas": cols, "chave": chave if pos_chave else []}

        def enviar(apagadas=(), fim=False):
            nonlocal recomecar
            resp = self._enviar({**base, "linhas": buf, "apagadas": list(apagadas), "recomecar": recomecar,
                                 "fim": fim})
            if resp.get("recarregar"):
                raise _Recarregar()
            foto.aplicar(tabela, buf_foto, list(apagadas), assinatura)
            recomecar = False
            buf.clear()
            buf_foto.clear()
            return resp

        try:
            for _, linhas in banco.percorrer(sql, params, PACOTE):
                for linha in linhas:
                    h = _hash(linha)
                    k = json.dumps([linha[i] for i in pos_chave] if pos_chave else h, default=str,
                                   ensure_ascii=False, separators=(",", ":"))
                    if k in vistas:          # chave repetida (tabela sem chave primária com linhas iguais)
                        continue
                    vistas.add(k)
                    if antes.get(k) == h:
                        continue
                    r["alteradas" if k in antes else "inseridas"] += 1
                    buf.append([k, linha])
                    buf_foto.append((k, h))
                    if len(buf) >= PACOTE:
                        enviar()
            r["linhas"] = len(vistas)
            sumidas = [k for k in antes if k not in vistas]
            r["apagadas"] = len(sumidas)
            for i in range(0, max(len(sumidas), 1), PACOTE * 5):
                ultimo = i + PACOTE * 5 >= len(sumidas)
                resp = enviar(sumidas[i:i + PACOTE * 5], fim=ultimo)
            if resp.get("linhas_tabela") is not None and resp["linhas_tabela"] != len(vistas):
                log.warning("[%s] %s: o site tem %s linhas e o banco %s. Refazendo a carga desta tabela.",
                            self.eid, tabela, resp["linhas_tabela"], len(vistas))
                foto.esquecer(tabela)
        except _Recarregar:
            log.info("[%s] O site pediu a carga completa de %s", self.eid, tabela)
            foto.esquecer(tabela)
        return r


class _Recarregar(Exception):
    pass
