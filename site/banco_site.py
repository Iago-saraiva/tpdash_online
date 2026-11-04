"""Banco do site (usuários, empresas, chaves, consultas salvas, layouts).

Padrão: arquivo SQLite em dados\\painel.sqlite (painel local e TP DASH online no seu servidor).
Com a variável de ambiente DATABASE_URL (postgresql://...), usa PostgreSQL: é o caso da hospedagem
grátis (Render free + Neon), em que o disco do servidor é apagado a cada reinício.
O resto do código continua escrevendo o SQL do SQLite; aqui ele é adaptado para o PostgreSQL.
"""
import os
import queue
import re
import sqlite3

URL = os.environ.get("DATABASE_URL", "").strip()
POSTGRES = URL.startswith(("postgres://", "postgresql://"))

IntegrityError = sqlite3.IntegrityError       # o código captura este erro nos dois bancos


def conectar(caminho_sqlite):
    if POSTGRES:
        return _ConexaoPG()
    os.makedirs(os.path.dirname(caminho_sqlite), exist_ok=True)
    con = sqlite3.connect(caminho_sqlite)
    con.row_factory = sqlite3.Row
    return con


# ------------------------------------------------------------------ PostgreSQL
_POOL = queue.LifoQueue(maxsize=8)       # conexões reaproveitadas (abrir uma no Neon leva ~100 ms)


class Linha(dict):
    """Linha que aceita r["coluna"] e r[0], como o sqlite3.Row."""

    def __init__(self, colunas, valores):
        super().__init__(zip(colunas, valores))
        self._v = valores

    def __getitem__(self, k):
        return self._v[k] if isinstance(k, int) else super().__getitem__(k)


class _Resultado:
    def __init__(self, cur, lastrowid=None):
        self.rowcount = cur.rowcount
        self.lastrowid = lastrowid
        cols = [c.name for c in cur.description] if cur.description else []
        self._linhas = [Linha(cols, tuple(v)) for v in cur.fetchall()] if cols and lastrowid is None else []

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return list(self._linhas)

    def __iter__(self):
        return iter(self._linhas)


def _traduzir(sql):
    """SQL do SQLite -> PostgreSQL (só as construções usadas pelo site)."""
    s = sql
    retorna_id = False
    m = re.match(r"\s*INSERT OR REPLACE INTO layouts\b", s, re.I)
    if m:
        s = re.sub(r"INSERT OR REPLACE INTO", "INSERT INTO", s, count=1, flags=re.I)
        s += (" ON CONFLICT (chave) DO UPDATE SET json = EXCLUDED.json, atualizado = EXCLUDED.atualizado,"
              " por = EXCLUDED.por")
    elif re.match(r"\s*INSERT OR IGNORE INTO", s, re.I):
        s = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", s, count=1, flags=re.I) + " ON CONFLICT DO NOTHING"
    elif re.match(r"\s*INSERT INTO (consultas|usuarios|acessos)\b", s, re.I):
        s += " RETURNING id"
        retorna_id = True
    s = re.sub(r"\blogin\s*=\s*\?", "lower(login) = lower(?)", s)    # login sem diferenciar maiúsculas (COLLATE NOCASE)
    s = s.replace("%", "%%").replace("?", "%s")
    return s, retorna_id


class _ConexaoPG:
    def __init__(self):
        try:
            self.con = _POOL.get_nowait()
            if self.con.closed or self.con.broken:
                raise queue.Empty
        except queue.Empty:
            import psycopg
            self.con = psycopg.connect(URL, cursor_factory=psycopg.ClientCursor, connect_timeout=15)

    def execute(self, sql, params=()):
        import psycopg
        s, retorna_id = _traduzir(sql)
        cur = self.con.cursor()
        try:
            cur.execute(s, tuple(params))
        except psycopg.errors.UniqueViolation as e:
            raise IntegrityError(str(e)) from e
        if retorna_id:
            r = cur.fetchone()
            return _Resultado(cur, r[0] if r else None)
        return _Resultado(cur)

    def executemany_cru(self, sql, seq):
        """SQL já escrito para o PostgreSQL (com %s), muitas linhas de uma vez. Usado pela cópia das tabelas."""
        with self.con.cursor() as cur:
            cur.executemany(sql, seq)

    def copiar_e_mesclar(self, tabela, colunas, linhas):
        """Grava muitas linhas (inclui ou substitui pela coluna _k) com COPY: rápido mesmo com o banco longe."""
        cols = ", ".join(f'"{c}"' for c in colunas)
        sets = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in colunas[1:])
        with self.con.cursor() as cur:
            cur.execute(f'CREATE TEMP TABLE IF NOT EXISTS _carga (LIKE "{tabela}" INCLUDING DEFAULTS) ON COMMIT DROP')
            with cur.copy(f'COPY _carga ({cols}) FROM STDIN') as cp:
                for linha in linhas:
                    cp.write_row(linha)
            cur.execute(f'INSERT INTO "{tabela}" ({cols}) SELECT DISTINCT ON (_k) {cols} FROM _carga '
                        f'ON CONFLICT (_k) DO UPDATE SET {sets}')
            cur.execute("DROP TABLE _carga")

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, tb):
        try:
            if tipo is None:
                self.con.commit()
            else:
                self.con.rollback()
        finally:
            try:
                if self.con.closed or self.con.broken:
                    raise queue.Full
                _POOL.put_nowait(self.con)
            except queue.Full:
                self.con.close()
        return False


ESQUEMA_PG = """
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY, login TEXT NOT NULL, nome TEXT NOT NULL, senha_hash TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0, modulos TEXT NOT NULL DEFAULT 'inicio', ativo INTEGER NOT NULL DEFAULT 1,
    trocar_senha INTEGER NOT NULL DEFAULT 1, ultimo_acesso TEXT, relatorios TEXT, tipos_mov TEXT,
    falhas_login INTEGER DEFAULT 0, bloqueado_ate TEXT, bancos TEXT, empresa_id TEXT, super INTEGER DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS usuarios_login ON usuarios (lower(login));
CREATE TABLE IF NOT EXISTS consultas (
    id SERIAL PRIMARY KEY, nome TEXT NOT NULL, descricao TEXT, sql TEXT NOT NULL, grafico TEXT,
    dono_id INTEGER NOT NULL, compartilhada INTEGER NOT NULL DEFAULT 0, atualizada TEXT, empresa_id TEXT);
CREATE TABLE IF NOT EXISTS layouts (chave TEXT PRIMARY KEY, json TEXT NOT NULL, atualizado TEXT, por TEXT);
CREATE TABLE IF NOT EXISTS acessos (
    id SERIAL PRIMARY KEY, usuario TEXT, acao TEXT, detalhe TEXT, quando TEXT, empresa_id TEXT);
CREATE INDEX IF NOT EXISTS acessos_empresa ON acessos (empresa_id, id);
CREATE TABLE IF NOT EXISTS empresas (
    id TEXT PRIMARY KEY, nome TEXT NOT NULL, chave_hash TEXT, ativa INTEGER NOT NULL DEFAULT 1, criada TEXT);
CREATE TABLE IF NOT EXISTS agentes_estado (
    empresa_id TEXT PRIMARY KEY, visto DOUBLE PRECISION, versao TEXT, descricao TEXT, ip TEXT,
    filiais TEXT, filiais_quando DOUBLE PRECISION, filiais_erro TEXT);
CREATE TABLE IF NOT EXISTS agentes_info (empresa_id TEXT PRIMARY KEY, dados TEXT);
CREATE TABLE IF NOT EXISTS arquivos_site (caminho TEXT PRIMARY KEY, conteudo TEXT, atualizado DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS agentes_consultas (
    empresa_id TEXT NOT NULL, dia TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, erros INTEGER NOT NULL DEFAULT 0,
    segundos DOUBLE PRECISION NOT NULL DEFAULT 0, PRIMARY KEY (empresa_id, dia));
"""


def criar_esquema_pg():
    import psycopg
    with psycopg.connect(URL, connect_timeout=15) as con:
        con.execute("SELECT pg_advisory_lock(7310)")          # dois processos subindo juntos não brigam
        try:
            for comando in [c.strip() for c in ESQUEMA_PG.split(";") if c.strip()]:
                con.execute(comando)
        finally:
            con.execute("SELECT pg_advisory_unlock(7310)")
