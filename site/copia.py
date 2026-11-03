"""Cópia, no banco do site, das tabelas que o agente de cada empresa sincroniza.

Cada (empresa, tabela) vira uma tabela própria no banco do site: c_<empresa>__<tabela> (ex.: c_alfa__tmov),
com as mesmas colunas do Puma e a coluna _k (chave da linha, montada pelo agente).
O banco é o mesmo do site: SQLite no servidor próprio, PostgreSQL (Neon) no Render.
A lista de tabelas copiadas e o tamanho de cada uma ficam em copia_tabelas.
"""
import json
import re
import threading
import time

import banco_site
import usuarios

_TIPOS_PG = {"inteiro": "BIGINT", "numero": "DOUBLE PRECISION", "data": "DATE", "hora": "TIME",
             "datahora": "TIMESTAMP", "texto": "TEXT", "logico": "BOOLEAN"}
_TIPOS_SQLITE = {"inteiro": "INTEGER", "numero": "REAL", "texto": "TEXT", "logico": "INTEGER"}
_NOME = re.compile(r"^[A-Z][A-Z0-9_$]{0,62}$")
_TRAVA = threading.Lock()


class ErroCopia(Exception):
    pass


def nome_sql(eid, tabela):
    e = re.sub(r"[^a-z0-9_]", "_", eid.lower())
    return f"c_{e}__{tabela.lower()}"


def _meta(con):
    con.execute("""CREATE TABLE IF NOT EXISTS copia_tabelas (
        empresa_id TEXT NOT NULL, tabela TEXT NOT NULL, colunas TEXT, chave TEXT, linhas INTEGER DEFAULT 0,
        atualizada REAL, PRIMARY KEY (empresa_id, tabela))""")


def _criar(con, eid, tabela, colunas):
    nome = nome_sql(eid, tabela)
    tipos = _TIPOS_PG if banco_site.POSTGRES else _TIPOS_SQLITE
    defs = ", ".join(f'"{c}" {tipos.get(t, "TEXT")}' for c, t in colunas)
    con.execute(f'DROP TABLE IF EXISTS "{nome}"')
    con.execute(f'CREATE TABLE "{nome}" (_k TEXT PRIMARY KEY, {defs})')


def receber(eid, d):
    """Um pacote do agente. Devolve a resposta para ele: {"ok", "linhas_tabela"} ou {"recarregar": True}."""
    tabela = str(d.get("tabela") or "").upper()
    if not _NOME.match(tabela):
        raise ErroCopia("Tabela inválida.")
    colunas = [(str(c).upper(), str(t)) for c, t in d.get("colunas") or []]
    if not colunas or any(not _NOME.match(c) for c, _ in colunas) or len(colunas) > 400:
        raise ErroCopia("Colunas inválidas.")
    nome = nome_sql(eid, tabela)
    linhas = d.get("linhas") or []
    apagadas = [str(k) for k in d.get("apagadas") or []]
    assinatura = json.dumps(colunas)
    with _TRAVA, usuarios._con() as con:
        _meta(con)
        r = con.execute("SELECT colunas FROM copia_tabelas WHERE empresa_id = ? AND tabela = ?", (eid, tabela)).fetchone()
        if d.get("recomecar") or not r or r["colunas"] != assinatura:
            if not d.get("recomecar"):
                # o site não tem esta tabela (ou ela mudou): o agente precisa mandar tudo de novo
                return {"ok": False, "recarregar": True}
            _criar(con, eid, tabela, colunas)
            con.execute("INSERT OR IGNORE INTO copia_tabelas (empresa_id, tabela) VALUES (?, ?)", (eid, tabela))
            con.execute("UPDATE copia_tabelas SET colunas = ?, chave = ?, linhas = 0 WHERE empresa_id = ? AND tabela = ?",
                        (assinatura, json.dumps(d.get("chave") or []), eid, tabela))
        nomes = ["_k"] + [c for c, _ in colunas]
        if linhas:
            valores = []
            for item in linhas:
                k, vals = item[0], item[1]
                if len(vals) != len(colunas):
                    raise ErroCopia("Linha com número de colunas diferente.")
                valores.append([str(k)] + [_valor(v, t) for v, (_, t) in zip(vals, colunas)])
            _gravar(con, nome, nomes, valores)
        if apagadas:
            _apagar(con, nome, apagadas)
        if not d.get("fim"):        # contagem só no último pacote da tabela (contar a cada pacote fica caro)
            con.execute("UPDATE copia_tabelas SET atualizada = ? WHERE empresa_id = ? AND tabela = ?",
                        (time.time(), eid, tabela))
            return {"ok": True, "linhas_tabela": None}
        n = con.execute(f'SELECT COUNT(*) FROM "{nome}"').fetchone()[0]
        con.execute("UPDATE copia_tabelas SET linhas = ?, atualizada = ? WHERE empresa_id = ? AND tabela = ?",
                    (n, time.time(), eid, tabela))
    return {"ok": True, "linhas_tabela": n}


def _valor(v, tipo):
    if v is None:
        return None
    if tipo == "logico":
        return bool(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    if tipo in ("data", "datahora", "hora") and isinstance(v, str) and not v.strip():
        return None
    return v


def _gravar(con, nome, nomes, valores):
    cols = ", ".join(f'"{c}"' for c in nomes)
    if banco_site.POSTGRES:
        # COPY para uma tabela temporária e um INSERT só: é o jeito mais rápido com o banco em outro servidor (Neon)
        con.copiar_e_mesclar(nome, nomes, valores)
    else:
        con.executemany(f'INSERT OR REPLACE INTO "{nome}" ({cols}) VALUES ({", ".join(["?"] * len(nomes))})', valores)


def _apagar(con, nome, chaves):
    if banco_site.POSTGRES:
        for i in range(0, len(chaves), 5000):
            con.executemany_cru(f'DELETE FROM "{nome}" WHERE _k = ANY(%s)', [(chaves[i:i + 5000],)])
    else:
        con.executemany(f'DELETE FROM "{nome}" WHERE _k = ?', [(k,) for k in chaves])


def tabelas(eid=None):
    """[{empresa_id, tabela, linhas, atualizada}] das cópias guardadas."""
    with usuarios._con() as con:
        _meta(con)
        sql = "SELECT empresa_id, tabela, linhas, atualizada FROM copia_tabelas"
        rs = con.execute(sql + (" WHERE empresa_id = ?" if eid else "") + " ORDER BY tabela", (eid,) if eid else ())
        return [dict(r) for r in rs]


def tamanho(eid):
    """Espaço que a cópia da empresa ocupa no banco do site, em bytes (None se não der para medir)."""
    if not banco_site.POSTGRES:
        return None
    with usuarios._con() as con:
        total = 0
        for t in tabelas(eid):
            r = con.execute(f"SELECT pg_total_relation_size('\"{nome_sql(eid, t['tabela'])}\"')").fetchone()
            total += int(r[0] or 0)
        return total
