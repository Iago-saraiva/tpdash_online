"""Acesso ao banco do Puma (Firebird) somente leitura, com modo demonstração em SQLite."""
import atexit
import contextlib
import datetime as dt
import decimal
import os
import re
import sqlite3
import threading
import time

from config import BASE_DIR, DADOS_DIR


class ErroBanco(Exception):
    pass


def _normalizar(v):
    if v is None:
        return None
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return v.isoformat(timespec="seconds")
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("cp1252")
        except Exception:
            return "<binário>"
    if isinstance(v, str):
        return v.rstrip()
    if hasattr(v, "read"):  # BlobReader do firebird-driver
        try:
            conteudo = v.read()
            return _normalizar(conteudo)
        finally:
            try:
                v.close()
            except Exception:
                pass
    return v


# --------------------------------------------------------------------- SQL livre
_PROIBIDAS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|DROP|ALTER|CREATE|RECREATE|GRANT|REVOKE|EXECUTE|EXEC|"
    r"COMMIT|ROLLBACK|SET|DECLARE|TRUNCATE|REPLACE)\b(?<!REPLACE)|\b(REPLACE)\b(?!\s*\()",
    re.IGNORECASE,
)


def _sem_comentarios_e_textos(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def validar_select(sql):
    """Garante que o texto é uma única consulta SELECT/WITH. A proteção real é a transação
    somente leitura; esta validação só evita mensagens confusas."""
    if not sql or not sql.strip():
        raise ErroBanco("Digite uma consulta SQL.")
    limpo = _sem_comentarios_e_textos(sql).strip().rstrip(";").strip()
    if ";" in limpo:
        raise ErroBanco("Envie apenas uma consulta por vez (sem ';' no meio).")
    if not re.match(r"^(SELECT|WITH)\b", limpo, re.IGNORECASE):
        raise ErroBanco("Somente consultas SELECT (ou WITH ... SELECT) são permitidas.")
    # REPLACE(...) é a função de texto do Firebird e CHARACTER SET faz parte do CAST: não são comandos
    m = _PROIBIDAS.search(re.sub(r"\bCHARACTER\s+SET\b", " ", limpo, flags=re.IGNORECASE))
    if m:
        raise ErroBanco(f"Comando não permitido em consulta: {(m.group(1) or m.group(2)).upper()}")
    return sql.strip().rstrip(";")


# --------------------------------------------------------------------- Firebird
class BancoFirebird:
    def __init__(self, cfg):
        self.cfg = cfg
        # Conexões reaproveitadas entre pedidos. Antes cada thread (uma por pedido no servidor HTTPS)
        # abria a sua e a deixava para o coletor de lixo fechar, o que gerava "access violation" no log.
        self._livres = []                 # [(conexao, momento em que foi devolvida)]
        self._trava = threading.Lock()
        atexit.register(self.fechar_tudo)
        try:
            from firebird.driver import driver_config  # noqa
        except ImportError as e:
            raise ErroBanco(
                "Biblioteca 'firebird-driver' não instalada. Rode instalar.bat novamente."
            ) from e
        from firebird.driver import driver_config

        if cfg.get("fbclient"):
            driver_config.fb_client_library.value = cfg["fbclient"]

    @property
    def descricao(self):
        c = self.cfg
        return f"{c['host']}/{c['porta']}:{c['arquivo']}"

    def _conectar(self):
        from firebird.driver import connect

        c = self.cfg
        if not c["arquivo"]:
            raise ErroBanco("Caminho do banco vazio. No config.ini, na seção [banco], preencha a linha "
                            "arquivo = (ex.: arquivo = D:\\PUMA\\DADOS\\METODO\\DADOS\\PUMA.FDB)")
        dsn = f"{c['host']}/{c['porta']}:{c['arquivo']}"
        return connect(dsn, user=c["usuario"], password=c["senha"], charset=c["charset"])

    MAX_LIVRES = 4          # conexões ociosas guardadas
    OCIOSA_SEG = 300        # fecha conexões paradas há mais de 5 minutos

    @staticmethod
    def _fechar(con):
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass

    def _pegar(self):
        agora = time.monotonic()
        velhas = []
        con = None
        with self._trava:
            while self._livres:
                c, ts = self._livres.pop()
                if agora - ts < self.OCIOSA_SEG:
                    con = c
                    break
                velhas.append(c)
            velhas += [c for c, ts in self._livres if agora - ts >= self.OCIOSA_SEG]
            self._livres = [(c, ts) for c, ts in self._livres if agora - ts < self.OCIOSA_SEG]
        for c in velhas:
            self._fechar(c)
        if con is not None:
            try:
                if not con.is_closed():
                    return con
            except Exception:  # noqa: BLE001
                pass
            self._fechar(con)
        return self._conectar()

    def _devolver(self, con):
        with self._trava:
            if len(self._livres) < self.MAX_LIVRES:
                self._livres.append((con, time.monotonic()))
                return
        self._fechar(con)

    @contextlib.contextmanager
    def _usar(self):
        """Empresta uma conexão; devolve se deu certo, fecha (explicitamente) se deu erro."""
        con = self._pegar()
        try:
            yield con
        except BaseException:
            self._fechar(con)
            raise
        else:
            self._devolver(con)

    def fechar_tudo(self):
        with self._trava:
            livres, self._livres = self._livres, []
        for c, _ in livres:
            self._fechar(c)

    def consultar(self, sql, params=(), limite=None):
        from firebird.driver import Isolation, TraAccessMode, tpb

        leitura = tpb(Isolation.READ_COMMITTED_RECORD_VERSION, access_mode=TraAccessMode.READ)
        for tentativa in (1, 2):
            try:
                with self._usar() as con:
                    tm = con.transaction_manager(leitura)
                    tm.begin()
                    try:
                        cur = tm.cursor()
                        cur.execute(sql, tuple(params))
                        colunas = [d[0].strip() for d in cur.description]
                        linhas = cur.fetchmany(limite) if limite else cur.fetchall()
                        linhas = [[_normalizar(v) for v in r] for r in linhas]
                        mais = bool(limite) and cur.fetchone() is not None
                        cur.close()
                    finally:
                        tm.rollback()  # nunca grava nada
                        tm.close()
                return colunas, linhas, mais
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                conexao_caiu = any(t in msg.lower() for t in ("connection", "network", "shutdown", "closed"))
                if conexao_caiu:
                    self.fechar_tudo()      # as outras guardadas provavelmente caíram também
                if tentativa == 1 and conexao_caiu:
                    continue
                raise ErroBanco(msg) from e

    def consultar_blob(self, sql, params=()):
        """Como consultar(), mas devolve BLOBs binários como bytes (usado para ler os modelos do ReportBuilder)."""
        from firebird.driver import Isolation, TraAccessMode, tpb

        try:
            with self._usar() as con:
                tm = con.transaction_manager(tpb(Isolation.READ_COMMITTED_RECORD_VERSION, access_mode=TraAccessMode.READ))
                tm.begin()
                try:
                    cur = tm.cursor()
                    try:
                        cur.stream_blob_threshold = 64 * 1024 * 1024   # BLOBs até 64 MB vêm inteiros
                    except Exception:  # noqa: BLE001 - versões antigas do driver
                        pass
                    cur.execute(sql, tuple(params))
                    colunas = [d[0].strip() for d in cur.description]
                    linhas = []
                    for r in cur.fetchall():
                        linha = []
                        for v in r:
                            if hasattr(v, "read"):          # BLOB em modo stream
                                dado = v.read()
                                v.close()
                                v = dado
                            linha.append(bytes(v) if isinstance(v, (bytes, bytearray, memoryview)) else v)
                        linhas.append(linha)
                    cur.close()
                finally:
                    tm.rollback()
                    tm.close()
            return colunas, linhas, False
        except Exception as e:  # noqa: BLE001
            raise ErroBanco(str(e)) from e

    def colunas(self, sql, params=()):
        """Só os nomes das colunas (executa sem buscar linhas)."""
        from firebird.driver import Isolation, TraAccessMode, tpb

        try:
            with self._usar() as con:
                tm = con.transaction_manager(tpb(Isolation.READ_COMMITTED_RECORD_VERSION, access_mode=TraAccessMode.READ))
                tm.begin()
                try:
                    cur = tm.cursor()
                    cur.execute(sql, tuple(params))
                    cols = [d[0].strip() for d in cur.description]
                    cur.close()
                finally:
                    tm.rollback()
                    tm.close()
            return cols
        except Exception as e:  # noqa: BLE001
            raise ErroBanco(str(e)) from e

    def testar(self):
        cols, linhas, _ = self.consultar(
            "SELECT rdb$get_context('SYSTEM','ENGINE_VERSION') AS VERSAO FROM RDB$DATABASE"
        )
        return f"Firebird {linhas[0][0]} em {self.descricao}"


# --------------------------------------------------------------------- Demonstração
_TRAVA_DEMO = threading.Lock()


class BancoDemo:
    """SQLite com tabelas no mesmo formato do Puma e dados fictícios."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.caminho = os.path.join(DADOS_DIR, "demo.sqlite")
        with _TRAVA_DEMO:                         # várias requisições ao mesmo tempo: só uma cria o arquivo
            if os.path.exists(self.caminho) and not self._tem_filial():
                os.remove(self.caminho)          # banco de demonstração antigo (sem filial): recria
            if not os.path.exists(self.caminho):
                import demo_data

                demo_data.criar(self.caminho)

    descricao = "modo demonstração (dados fictícios)"

    def _tem_filial(self):
        try:
            con = sqlite3.connect(f"file:{self.caminho}?mode=ro", uri=True)
            try:
                # bancos de demonstração antigos (sem filial ou sem o efeito no estoque) são recriados
                return (any(c[1] == "CODFILIAL" for c in con.execute("PRAGMA table_info(FLAN)"))
                        and any(c[1] == "FLAGEFEITOSALDO" for c in con.execute("PRAGMA table_info(TMOVITENS)"))
                        and any(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'AMAQUINAS'"))
                        and any(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'FLANRATCCUSTO'"))
                        and any(c[1] == "CODCCUSTO" for c in con.execute("PRAGMA table_info(TMOV)"))
                        and any(c[1] == "CODMAQUINA" for c in con.execute("PRAGMA table_info(TMOV)")))
            finally:
                con.close()
        except sqlite3.Error:
            return False

    def consultar(self, sql, params=(), limite=None):
        sql = re.sub(r"\bSTARTING\s+WITH\s+\?", "LIKE ? || '%'", sql, flags=re.I)
        conv = [p.isoformat() if isinstance(p, (dt.date, dt.datetime)) else p for p in params]
        try:
            con = sqlite3.connect(f"file:{self.caminho}?mode=ro", uri=True)
            try:
                cur = con.execute(sql, conv)
                colunas = [d[0].upper() for d in cur.description]
                linhas = cur.fetchmany(limite) if limite else cur.fetchall()
                mais = bool(limite) and cur.fetchone() is not None
                return colunas, [[_normalizar(v) for v in r] for r in linhas], mais
            finally:
                con.close()
        except sqlite3.Error as e:
            raise ErroBanco(str(e)) from e

    def colunas(self, sql, params=()):
        sql = re.sub(r"\bSTARTING\s+WITH\s+\?", "LIKE ? || '%'", sql, flags=re.I)
        conv = [p.isoformat() if isinstance(p, (dt.date, dt.datetime)) else p for p in params]
        try:
            con = sqlite3.connect(f"file:{self.caminho}?mode=ro", uri=True)
            try:
                return [d[0].upper() for d in con.execute(sql, conv).description]
            finally:
                con.close()
        except sqlite3.Error as e:
            raise ErroBanco(str(e)) from e

    def consultar_blob(self, sql, params=()):
        raise ErroBanco("O banco de demonstração não tem os relatórios do ReportBuilder.")

    def testar(self):
        return "Banco de demonstração (SQLite) com dados fictícios"


def abrir(cfg):
    if cfg["modo"] == "demo":
        return BancoDemo(cfg)
    return BancoFirebird(cfg)
