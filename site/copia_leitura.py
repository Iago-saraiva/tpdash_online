"""Relatórios lidos da cópia do banco no PostgreSQL (Neon), sem ir ao servidor da empresa.

BancoHibrido é usado no lugar do nuvem.BancoRemoto: cada consulta (SQL do Firebird) é traduzida para o
PostgreSQL e roda no schema copia_<empresa>. Se não der (tabela fora da cópia, carga ainda não terminou,
cópia atrasada com o agente ligado, função do Firebird sem tradução, erro), a consulta vai ao agente,
como antes. Assim nada para de funcionar; só fica mais rápido onde a cópia serve.

Segurança: a consulta roda numa transação só de leitura, com o search_path só no schema da empresa e
tempo máximo. Nomes de outros schemas, do catálogo do PostgreSQL e funções que leem fora da cópia são recusados.
"""
import datetime as dt
import decimal
import logging
import os
import re
import threading
import time

import banco_site
import copia
import nuvem
import usuarios

log = logging.getLogger("copia")
ATIVA = banco_site.POSTGRES and os.environ.get("TPDASH_LER_COPIA", "1").strip().lower() not in ("0", "nao", "não", "false")
TEMPO_MAX_MS = 25000


class NaoDa(Exception):
    """A consulta não pode rodar na cópia (vai ao agente)."""


# ------------------------------------------------------------------ tradução Firebird -> PostgreSQL
_TOKENS = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/|\"(?:[^\"]|\"\")*\"", re.S)
_PROIBIDOS = re.compile(r"^(pg_|information_schema|public$|copia_|lo_|dblink|query_to|table_to|cursor_to|schema_to|"
                        r"database_to|current_setting|set_config|txid|rdb\$|mon\$|sec\$)", re.I)
_PALAVRAS_FIM = re.compile(r"\b(LIMIT|ROWS|OFFSET|FOR|UNION|PLAN)\b", re.I)


def _mascarar(sql):
    """Tira comentários e troca textos entre aspas por marcadores (para as trocas não mexerem neles)."""
    textos = []

    def troca(m):
        t = m.group(0)
        if t.startswith("--") or t.startswith("/*"):
            return " "
        if t.startswith('"'):
            nome = t[1:-1]
            if not re.fullmatch(r"[A-Z][A-Z0-9_$]*", nome):
                raise NaoDa("nome entre aspas")
            return nome
        if re.fullmatch(r"'\d{1,2}\.\d{1,2}\.\d{4}'", t):          # '31.12.2025' (dia.mês.ano no Firebird)
            d, m_, a = t[1:-1].split(".")
            t = f"'{a}-{int(m_):02d}-{int(d):02d}'"
        textos.append(t)
        return f"\x00{len(textos) - 1}\x00"
    return _TOKENS.sub(troca, sql), textos


def _fecha(s, i):
    """Índice do parêntese que fecha o aberto em s[i]."""
    n = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            n += 1
        elif s[j] == ")":
            n -= 1
            if n == 0:
                return j
    raise NaoDa("parênteses")


def _args(dentro):
    partes, n, ini = [], 0, 0
    for j, ch in enumerate(dentro):
        if ch == "(":
            n += 1
        elif ch == ")":
            n -= 1
        elif ch == "," and n == 0:
            partes.append(dentro[ini:j].strip())
            ini = j + 1
    partes.append(dentro[ini:].strip())
    return partes


def _funcao(s, nome, fn):
    """Troca cada chamada nome(...) por fn(texto de dentro), de dentro para fora."""
    rx = re.compile(r"\b" + nome + r"\s*\(", re.I)
    antes = len(s) + 1          # só as chamadas antes da última trocada (a troca pode repetir o nome, ex.: EXTRACT)
    while True:
        ms = [m for m in rx.finditer(s) if m.start() < antes]
        if not ms:
            return s
        m = ms[-1]
        antes = m.start()
        a = m.end() - 1
        b = _fecha(s, a)
        s = s[:m.start()] + fn(s[a + 1:b]) + s[b + 1:]


def _iif(d):
    a = _args(d)
    if len(a) != 3:
        raise NaoDa("IIF")
    return f"(CASE WHEN {a[0]} THEN {a[1]} ELSE {a[2]} END)"


def _list(d):
    a = _args(d)
    sep = a[1] if len(a) > 1 else "','"
    x = a[0]
    dist = ""
    m = re.match(r"(?i)DISTINCT\s+(.*)", x, re.S)
    if m:
        dist, x = "DISTINCT ", m.group(1)
    return f"STRING_AGG({dist}CAST({x} AS TEXT), {sep})"


def _extract(d):
    m = re.match(r"(?is)\s*(\w+)\s+FROM\s+(.*)", d)
    if not m:
        raise NaoDa("EXTRACT")
    parte, x = m.group(1).upper(), m.group(2)
    if parte == "WEEKDAY":
        return f"CAST(EXTRACT(DOW FROM {x}) AS INTEGER)"
    if parte == "YEARDAY":
        return f"(CAST(EXTRACT(DOY FROM {x}) AS INTEGER) - 1)"
    if parte in ("YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "WEEK", "QUARTER"):
        return f"CAST(EXTRACT({parte} FROM {x}) AS INTEGER)"
    if parte == "SECOND":
        return f"CAST(EXTRACT(SECOND FROM {x}) AS NUMERIC(9,4))"
    raise NaoDa("EXTRACT " + parte)


def _datediff(d):
    m = re.match(r"(?is)\s*DAY\s+FROM\s+(.*)\s+TO\s+(.*)", d)
    if m:
        a, b = m.group(1), m.group(2)
    else:
        p = _args(d)
        if len(p) != 3 or p[0].upper() != "DAY":
            raise NaoDa("DATEDIFF")
        a, b = p[1], p[2]
    return f"(CAST({b} AS DATE) - CAST({a} AS DATE))"


def _nao(nome):
    def f(_d):
        raise NaoDa(nome)
    return f


def _ordenacao(s):
    """Firebird põe os nulos primeiro em ORDER BY crescente; o PostgreSQL, por último. Deixa como no Firebird."""
    saida, pos = [], 0
    for m in re.finditer(r"\bORDER\s+BY\b", s, re.I):
        if m.start() < pos:
            continue
        ini = m.end()
        n, fim = 0, len(s)
        for j in range(ini, len(s)):
            ch = s[j]
            if ch == "(":
                n += 1
            elif ch == ")":
                if n == 0:
                    fim = j
                    break
                n -= 1
            elif n == 0 and _PALAVRAS_FIM.match(s, j) and (j == 0 or not (s[j - 1].isalnum() or s[j - 1] == "_")):
                fim = j
                break
        itens = []
        for it in _args(s[ini:fim]):
            if re.search(r"(?i)\bNULLS\s+(FIRST|LAST)\b", it):
                itens.append(it)
            elif re.search(r"(?i)\bDESC(ENDING)?$", it):
                itens.append(it + " NULLS LAST")
            else:
                itens.append(it + " NULLS FIRST")
        saida.append(s[pos:ini] + " " + ", ".join(itens) + " ")
        pos = fim
    saida.append(s[pos:])
    return "".join(saida)


def _limites(s):
    """SELECT FIRST n SKIP m ... e ... ROWS n [TO m] viram LIMIT/OFFSET no fim do mesmo SELECT."""
    rx = re.compile(r"\bSELECT\s+(?:FIRST\s+(\S+)\s+)?(?:SKIP\s+(\S+)\s+)?", re.I)
    i = 0
    while True:
        m = rx.search(s, i)
        if not m:
            break
        first, skip = m.group(1), m.group(2)
        if not first and not skip:
            i = m.end()
            continue
        for v in (first, skip):
            if v and not v.isdigit():
                raise NaoDa("FIRST/SKIP com parâmetro")
        # fim deste SELECT: onde fecha o parêntese que o contém (ou o fim do texto)
        n, fim = 0, len(s)
        for j in range(m.end(), len(s)):
            if s[j] == "(":
                n += 1
            elif s[j] == ")":
                if n == 0:
                    fim = j
                    break
                n -= 1
        extra = (f" LIMIT {first}" if first else "") + (f" OFFSET {skip}" if skip else "")
        s = s[:m.start()] + "SELECT " + s[m.end():fim] + extra + s[fim:]
        i = m.start() + 7
    m = re.search(r"\bROWS\s+(\S+)(?:\s+TO\s+(\S+))?\s*$", s, re.I)
    if m:
        a, b = m.group(1), m.group(2)
        if not a.isdigit() or (b and not b.isdigit()):
            raise NaoDa("ROWS com parâmetro")
        a = int(a)
        s = s[:m.start()] + (f" LIMIT {int(b) - a + 1} OFFSET {a - 1}" if b else f" LIMIT {a}")
    return s


def traduzir(sql):
    """(SQL do PostgreSQL com %s, [nomes usados]) ou NaoDa."""
    s, textos = _mascarar(sql)
    s = s.strip().rstrip(";").strip()
    if ";" in s or not re.match(r"(?i)(SELECT|WITH)\b", s):
        raise NaoDa("não é um SELECT só")
    s = re.sub(r"(?i)\bFROM\s+RDB\$DATABASE\b", " ", s)
    s = re.sub(r"(?i)\bCHARACTER\s+SET\s+\w+", " ", s)
    s = re.sub(r"(?i)\bCOLLATE\s+\w+", " ", s)
    for nome, fn in (("IIF", _iif), ("LIST", _list), ("EXTRACT", _extract), ("DATEDIFF", _datediff),
                     ("DATEADD", _nao("DATEADD")), ("DECODE", _nao("DECODE")), ("GEN_ID", _nao("GEN_ID"))):
        s = _funcao(s, nome, fn)
    alvo = r"(\?|\x00\d+\x00|[\w.$]+(?:\s*\([^()]*\))?)"
    s = re.sub(r"(?i)\bCONTAINING\s+" + alvo, lambda m: f"ILIKE ('%' || {m.group(1)} || '%')", s)
    s = re.sub(r"(?i)\bSTARTING\s+(?:WITH\s+)?" + alvo, lambda m: f"LIKE ({m.group(1)} || '%')", s)
    if re.search(r"(?i)\bBLOB\b|\bSIMILAR\s+TO\b|\bMATCHING\b", s):
        raise NaoDa("construção sem tradução")
    s = _ordenacao(s)
    s = _limites(s)
    nomes = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", s)
    for n in nomes:
        if _PROIBIDOS.match(n):
            raise NaoDa("nome proibido: " + n)
    s = s.replace("%", "%%").replace("?", "%s")
    s = re.sub(r"\x00(\d+)\x00", lambda m: textos[int(m.group(1))].replace("%", "%%"), s)
    return s, {n.upper() for n in nomes}


# ------------------------------------------------------------------ estado da cópia de cada empresa
_ESTADO, _TRAVA = {}, threading.Lock()


def estado(eid):
    """{"tabelas": {TABELA: completa}, "recebido": epoch da última rodada, "fresca": bool} (guardado 15 s)."""
    agora = time.time()
    with _TRAVA:
        e = _ESTADO.get(eid)
        if e and agora - e["lido"] < 15:
            return e
    tabs = {t["tabela"].upper(): bool(t.get("completa")) for t in copia.tabelas(eid)}
    sinc = (usuarios.info_agentes().get(eid) or {}).get("sincronizacao") or {}
    recebido = float(sinc.get("recebido") or 0)
    intervalo = float(sinc.get("intervalo_min") or 15)
    fresca = bool(recebido) and agora - recebido <= (2 * intervalo + 10) * 60 and not sinc.get("erro")
    e = {"tabelas": tabs, "recebido": recebido, "fresca": fresca, "lido": agora}
    with _TRAVA:
        _ESTADO[eid] = e
    return e


def esquecer(eid):
    with _TRAVA:
        _ESTADO.pop(eid, None)


def _normalizar(v):
    """Igual ao agente (db._normalizar): os relatórios recebem os mesmos tipos de valor."""
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return v.isoformat(timespec="seconds")
    if isinstance(v, str):
        return v.rstrip()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<binário>"
    return v


def ler(eid, sql, params=(), limite=None):
    """(colunas, linhas, mais) lidos da cópia, ou NaoDa."""
    e = estado(eid)
    if not any(e["tabelas"].values()):
        raise NaoDa("empresa sem cópia")
    pg, nomes = traduzir(sql)
    usadas = nomes & set(e["tabelas"])
    if not usadas:
        raise NaoDa("nenhuma tabela da cópia")
    if not all(e["tabelas"][t] for t in usadas):
        raise NaoDa("carga da cópia ainda não terminou")
    with usuarios._con() as c:
        cur = c.con.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(f'SET LOCAL search_path TO "{copia.schema(eid)}"')
        cur.execute(f"SET LOCAL statement_timeout = {TEMPO_MAX_MS}")
        cur.execute(pg, tuple(params))
        colunas = [d.name.upper() for d in cur.description]
        linhas = cur.fetchmany(limite) if limite else cur.fetchall()
        mais = bool(limite) and cur.fetchone() is not None
    return colunas, [[_normalizar(v) for v in r] for r in linhas], mais


class BancoHibrido:
    """Lê da cópia quando dá; senão, do agente (nuvem.BancoRemoto). `fontes` registra o que foi usado."""

    def __init__(self, empresa_id, ao_usar=None):
        self.empresa_id = empresa_id
        self.remoto = nuvem.BancoRemoto(empresa_id)
        self.ao_usar = ao_usar            # função (fonte, recebido) chamada a cada consulta: "copia" ou "agente"

    @property
    def descricao(self):
        return self.remoto.descricao

    def _avisar(self, fonte, recebido=None):
        if self.ao_usar:
            try:
                self.ao_usar(fonte, recebido)
            except Exception:  # noqa: BLE001
                pass

    def consultar(self, sql, params=(), limite=None):
        if ATIVA:
            e = estado(self.empresa_id)
            online = nuvem.estado(self.empresa_id).get("online")
            if e["fresca"] or not online:
                try:
                    r = ler(self.empresa_id, sql, params, limite)
                    self._avisar("copia", e["recebido"])
                    return r
                except NaoDa as x:
                    log.debug("cópia não serve (%s): %s", x, sql[:120])
                except Exception as x:  # noqa: BLE001 - erro na cópia: vai ao agente
                    log.info("cópia deu erro, indo ao agente: %s | %s", str(x)[:200], sql[:160])
        self._avisar("agente")
        return self.remoto.consultar(sql, params, limite)

    def consultar_blob(self, sql, params=()):
        return self.remoto.consultar_blob(sql, params)

    def colunas(self, sql, params=()):
        return self.remoto.colunas(sql, params)

    def testar(self):
        return self.remoto.testar()

    def fechar_tudo(self):
        pass
