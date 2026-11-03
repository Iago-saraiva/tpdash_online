"""Usuários, permissões por módulo e consultas salvas (SQLite local do painel)."""
import datetime as dt
import json
import os
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

import banco_site
from config import BASE_DIR, DADOS_DIR

CAMINHO = os.path.join(DADOS_DIR, "painel.sqlite")

MODULOS = {
    "inicio": "Início",
    "movimentos": "Movimentos",
    "movimentacoes": "Movimentações",
    "estoque": "Estoque",
    "financeiro": "Financeiro",
    "cadastros": "Cadastros",
    "frotas": "Frotas",
    "relatorios": "Relatórios",
    "sql": "Consulta SQL",
    "chat": "Assistente (chat)",
}


# TP DASH online: devolve a empresa em uso na requisição (o app.py troca esta função).
# None = painel local de uma empresa só (sem separação por empresa).
empresa_atual = lambda: None   # noqa: E731


def _con():
    """SQLite (dados\\painel.sqlite) ou, com DATABASE_URL, PostgreSQL (hospedagem sem disco). Ver banco_site.py."""
    return banco_site.conectar(CAMINHO)


def iniciar(site=False):
    if banco_site.POSTGRES:
        banco_site.criar_esquema_pg()
        _admin_inicial(site)
        return
    with _con() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL COLLATE NOCASE,
            nome TEXT NOT NULL,
            senha_hash TEXT NOT NULL,
            admin INTEGER NOT NULL DEFAULT 0,
            modulos TEXT NOT NULL DEFAULT 'inicio',
            ativo INTEGER NOT NULL DEFAULT 1,
            trocar_senha INTEGER NOT NULL DEFAULT 1,
            ultimo_acesso TEXT
        );
        CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            sql TEXT NOT NULL,
            grafico TEXT,
            dono_id INTEGER NOT NULL,
            compartilhada INTEGER NOT NULL DEFAULT 0,
            atualizada TEXT
        );
        CREATE TABLE IF NOT EXISTS layouts (
            chave TEXT PRIMARY KEY, json TEXT NOT NULL, atualizado TEXT, por TEXT
        );
        CREATE TABLE IF NOT EXISTS acessos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT, acao TEXT, detalhe TEXT, quando TEXT
        );
        """)
        cols = {r[1] for r in con.execute("PRAGMA table_info(usuarios)")}
        # permissões finas (versões novas): relatórios escolhidos e tipos de movimento liberados (JSON; vazio = todos)
        for c in ("relatorios", "tipos_mov", "falhas_login", "bloqueado_ate", "bancos"):
            if c not in cols:
                con.execute(f"ALTER TABLE usuarios ADD COLUMN {c} " + ("INTEGER DEFAULT 0" if c == "falhas_login" else "TEXT"))
        # TP DASH online: empresas (clientes), a empresa de cada usuário e o super administrador (Tecnoplan)
        con.execute("""CREATE TABLE IF NOT EXISTS empresas (
            id TEXT PRIMARY KEY, nome TEXT NOT NULL, chave_hash TEXT, ativa INTEGER NOT NULL DEFAULT 1, criada TEXT)""")
        for tabela, c, tipo in (("usuarios", "empresa_id", "TEXT"), ("usuarios", "super", "INTEGER DEFAULT 0"),
                                ("consultas", "empresa_id", "TEXT"), ("acessos", "empresa_id", "TEXT")):
            if c not in {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {c} {tipo}")
    _admin_inicial(site)


def _admin_inicial(site):
    with _con() as con:
        if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
            con.execute(
                "INSERT INTO usuarios (login, nome, senha_hash, admin, modulos, trocar_senha, super) VALUES (?,?,?,?,?,1,?)",
                ("admin", "Administrador", generate_password_hash("admin"), 1, ",".join(MODULOS), 1 if site else 0),
            )


def _dict(r):
    if r is None:
        return None
    d = dict(r)
    d.pop("senha_hash", None)
    d["modulos"] = [m for m in (d.get("modulos") or "").split(",") if m]
    d["relatorios"] = _json(d.get("relatorios"))
    d["tipos_mov"] = _json(d.get("tipos_mov")) or []
    d["bancos"] = _json(d.get("bancos"))          # None = todos os bancos
    d["super"] = bool(d.get("super"))
    d.pop("falhas_login", None)
    d.pop("bloqueado_ate", None)
    if d.get("admin"):
        d["modulos"] = list(MODULOS)
        d["relatorios"] = None
        d["tipos_mov"] = []
        d["bancos"] = None
    return d


def _json(txt):
    try:
        return json.loads(txt) if txt else None
    except ValueError:
        return None


def _limpar_relatorios(v):
    """None = todos os relatórios dos módulos liberados; senão {"pastas": [...], "ids": [...]}."""
    if not isinstance(v, dict):
        return None
    return {"pastas": sorted({str(x)[:200] for x in v.get("pastas") or []}),
            "ids": sorted({str(x)[:100] for x in v.get("ids") or []})}


def _limpar_tipos(v):
    """Lista de códigos de tipo de movimento (ex.: 2.2.21) ou prefixos terminados em * (ex.: 2.2.*)."""
    import re
    return sorted({x.strip() for x in v or [] if isinstance(x, str) and re.fullmatch(r"[\w.\-]{1,20}\*?", x.strip())})


class Bloqueado(Exception):
    pass


def autenticar(login, senha):
    agora = dt.datetime.now()
    with _con() as con:
        r = con.execute("SELECT * FROM usuarios WHERE login = ? AND ativo = 1", (login.strip(),)).fetchone()
        if not r:
            check_password_hash(generate_password_hash("x"), senha or "")   # mesmo tempo de resposta
            return None
        if check_password_hash(r["senha_hash"], senha or ""):
            con.execute("UPDATE usuarios SET ultimo_acesso = ?, falhas_login = 0, bloqueado_ate = NULL WHERE id = ?",
                        (agora.isoformat(" ", "seconds"), r["id"]))
            return _dict(r)
    return None


def obter(uid):
    with _con() as con:
        return _dict(con.execute("SELECT * FROM usuarios WHERE id = ? AND ativo = 1", (uid,)).fetchone())


def listar(empresa=None):
    """empresa=None: todos (painel local). Com empresa: só os usuários dela (o super administrador não aparece)."""
    with _con() as con:
        if empresa is None:
            return [_dict(r) for r in con.execute("SELECT * FROM usuarios ORDER BY nome")]
        return [_dict(r) for r in con.execute("SELECT * FROM usuarios WHERE empresa_id = ? ORDER BY nome", (empresa,))]


def salvar(dados, uid=None, empresa=None):
    """empresa: no TP DASH online, a empresa em uso. O usuário novo fica nela e só se altera usuário dela."""
    login = (dados.get("login") or "").strip()
    nome = (dados.get("nome") or "").strip()
    if not login or not nome:
        raise ValueError("Informe login e nome.")
    modulos = ",".join(m for m in dados.get("modulos", []) if m in MODULOS) or "inicio"
    admin = 1 if dados.get("admin") else 0
    ativo = 0 if dados.get("ativo") is False else 1
    rel = _limpar_relatorios(dados.get("relatorios"))
    tipos = _limpar_tipos(dados.get("tipos_mov"))
    if not admin and tipos and "sql" in modulos.split(","):
        raise ValueError("Quem tem tipos de movimento limitados não pode ter o módulo Consulta SQL "
                         "(no SQL livre dá para consultar qualquer tipo). Desmarque um dos dois.")
    rel_txt = json.dumps(rel, ensure_ascii=False) if rel is not None else None
    tipos_txt = json.dumps(tipos) if tipos else None
    bancos_v = dados.get("bancos")
    if isinstance(bancos_v, list):
        bancos_v = sorted({str(x)[:30] for x in bancos_v})
        if not bancos_v and not admin:
            raise ValueError("Escolha pelo menos uma empresa (banco) para o usuário.")
    else:
        bancos_v = None
    bancos_txt = json.dumps(bancos_v) if bancos_v and not admin else None
    with _con() as con:
        if uid and empresa is not None:
            dono = con.execute("SELECT empresa_id FROM usuarios WHERE id=?", (uid,)).fetchone()
            if not dono or dono["empresa_id"] != empresa:
                raise ValueError("Usuário não encontrado nesta empresa.")
        if uid:
            con.execute("UPDATE usuarios SET login=?, nome=?, admin=?, modulos=?, ativo=?, relatorios=?, tipos_mov=?, bancos=? WHERE id=?",
                        (login, nome, admin, modulos, ativo, rel_txt, tipos_txt, bancos_txt, uid))
            if dados.get("senha"):
                con.execute("UPDATE usuarios SET senha_hash=?, trocar_senha=1 WHERE id=?",
                            (generate_password_hash(dados["senha"]), uid))
        else:
            if not dados.get("senha"):
                raise ValueError("Informe uma senha inicial.")
            try:
                con.execute(
                    "INSERT INTO usuarios (login, nome, senha_hash, admin, modulos, ativo, trocar_senha, relatorios, tipos_mov, bancos, empresa_id) "
                    "VALUES (?,?,?,?,?,?,1,?,?,?,?)",
                    (login, nome, generate_password_hash(dados["senha"]), admin, modulos, ativo, rel_txt, tipos_txt, bancos_txt, empresa))
            except sqlite3.IntegrityError:
                raise ValueError("Já existe um usuário com esse login.")
        admins = con.execute("SELECT COUNT(*) FROM usuarios WHERE admin=1 AND ativo=1").fetchone()[0]
        if admins == 0:
            raise ValueError("É preciso manter pelo menos um administrador ativo.")


def trocar_senha(uid, atual, nova):
    import re
    if len(nova or "") < 6:
        raise ValueError("A nova senha precisa ter pelo menos 6 caracteres.")
    if nova == atual:
        raise ValueError("A nova senha precisa ser diferente da atual.")
    with _con() as con:
        r = con.execute("SELECT senha_hash FROM usuarios WHERE id=?", (uid,)).fetchone()
        if not r or not check_password_hash(r["senha_hash"], atual):
            raise ValueError("Senha atual incorreta.")
        con.execute("UPDATE usuarios SET senha_hash=?, trocar_senha=0 WHERE id=?", (generate_password_hash(nova), uid))


def registrar(usuario, acao, detalhe=""):
    with _con() as con:
        con.execute("INSERT INTO acessos (usuario, acao, detalhe, quando, empresa_id) VALUES (?,?,?,?,?)",
                    (usuario, acao, (detalhe or "")[:2000], dt.datetime.now().isoformat(" ", "seconds"), _empresa()))


def ultimos_acessos(n=200):
    with _con() as con:
        e = _empresa()
        if e is None:
            return [dict(r) for r in con.execute("SELECT usuario, acao, detalhe, quando FROM acessos ORDER BY id DESC LIMIT ?", (n,))]
        return [dict(r) for r in con.execute("SELECT usuario, acao, detalhe, quando FROM acessos WHERE empresa_id = ? "
                                             "ORDER BY id DESC LIMIT ?", (e, n))]


# ------------------------------------------------------------ consultas salvas
def consultas_visiveis(uid, admin=False):
    with _con() as con:
        rows = con.execute("""
            SELECT c.*, u.nome AS dono FROM consultas c LEFT JOIN usuarios u ON u.id = c.dono_id
            WHERE (c.dono_id = ? OR c.compartilhada = 1 OR ? = 1) AND (? IS NULL OR c.empresa_id = ?)
            ORDER BY c.nome""", (uid, 1 if admin else 0, _empresa(), _empresa()))
        return [dict(r) for r in rows]


def consulta(cid):
    with _con() as con:
        r = con.execute("SELECT * FROM consultas WHERE id = ? AND (? IS NULL OR empresa_id = ?)",
                        (cid, _empresa(), _empresa())).fetchone()
        return dict(r) if r else None


def salvar_consulta(uid, dados, cid=None, admin=False):
    nome = (dados.get("nome") or "").strip()
    if not nome or not (dados.get("sql") or "").strip():
        raise ValueError("Informe nome e SQL.")
    agora = dt.datetime.now().isoformat(" ", "seconds")
    with _con() as con:
        if cid:
            atual = con.execute("SELECT dono_id FROM consultas WHERE id=? AND (? IS NULL OR empresa_id = ?)",
                                (cid, _empresa(), _empresa())).fetchone()
            if not atual or (atual["dono_id"] != uid and not admin):
                raise ValueError("Você só pode alterar suas próprias consultas.")
            con.execute("UPDATE consultas SET nome=?, descricao=?, sql=?, grafico=?, compartilhada=?, atualizada=? WHERE id=?",
                        (nome, dados.get("descricao", ""), dados["sql"], dados.get("grafico"), 1 if dados.get("compartilhada") else 0, agora, cid))
            return cid
        cur = con.execute("INSERT INTO consultas (nome, descricao, sql, grafico, dono_id, compartilhada, atualizada, empresa_id) "
                          "VALUES (?,?,?,?,?,?,?,?)",
                          (nome, dados.get("descricao", ""), dados["sql"], dados.get("grafico"), uid,
                           1 if dados.get("compartilhada") else 0, agora, _empresa()))
        return cur.lastrowid


def excluir_consulta(uid, cid, admin=False):
    with _con() as con:
        atual = con.execute("SELECT dono_id FROM consultas WHERE id=? AND (? IS NULL OR empresa_id = ?)",
                            (cid, _empresa(), _empresa())).fetchone()
        if not atual or (atual["dono_id"] != uid and not admin):
            raise ValueError("Você só pode excluir suas próprias consultas.")
        con.execute("DELETE FROM consultas WHERE id=?", (cid,))


# ------------------------------------------------------------ teste dos relatórios importados
_TESTE = os.path.join(os.path.dirname(CAMINHO), "teste_relatorios_rb.json")


def _teste_arq(bid):
    import bancos
    return _TESTE if not bid or bid == bancos.PRINCIPAL else os.path.join(bancos.pasta(bid), "teste_relatorios_rb.json")


def teste_rb(bid=None):
    try:
        import json
        with open(_teste_arq(bid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def salvar_teste_rb(dados, bid=None):
    import json
    arq = _teste_arq(bid)
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, arq)


# ------------------------------------------------------------------ layouts dos relatórios (valem para todos)
def _lay(chave):
    """No TP DASH online cada empresa tem seus próprios layouts."""
    e = _empresa()
    return chave if e is None else f"{e}\u00a7{chave}"


def obter_layout(chave):
    chave = _lay(chave)
    with _con() as con:
        r = con.execute("SELECT json, atualizado, por FROM layouts WHERE chave = ?", (chave,)).fetchone()
    if not r:
        return None
    d = json.loads(r["json"])
    d["_info"] = {"atualizado": r["atualizado"], "por": r["por"]}
    return d


def salvar_layout(chave, dados, usuario):
    chave = _lay(chave)
    dados = {k: v for k, v in dados.items() if not k.startswith("_")}
    with _con() as con:
        con.execute("INSERT OR REPLACE INTO layouts (chave, json, atualizado, por) VALUES (?,?,?,?)",
                    (chave, json.dumps(dados, ensure_ascii=False),
                     dt.datetime.now().strftime("%d/%m/%Y %H:%M"), usuario))


def chaves_layout(prefixo):
    pre = _lay("")
    prefixo = pre + prefixo
    with _con() as con:
        return [r[0][len(pre):] for r in con.execute("SELECT chave FROM layouts WHERE chave LIKE ? ESCAPE '\\'",
                                          (prefixo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",))]


def excluir_layout(chave):
    chave = _lay(chave)
    with _con() as con:
        con.execute("DELETE FROM layouts WHERE chave = ?", (chave,))


def _empresa():
    try:
        return empresa_atual()
    except Exception:  # noqa: BLE001 - fora de uma requisição
        return None


# ------------------------------------------------------------ TP DASH online: empresas e chaves dos agentes
def _hash_chave(segredo):
    import hashlib
    return hashlib.sha256(segredo.encode("utf-8")).hexdigest()


def listar_empresas(so_ativas=False):
    with _con() as con:
        sql = "SELECT id, nome, ativa, criada, chave_hash IS NOT NULL AS tem_chave FROM empresas"
        sql += " WHERE ativa = 1" if so_ativas else ""
        return [dict(r) for r in con.execute(sql + " ORDER BY nome")]


def empresa(eid):
    with _con() as con:
        r = con.execute("SELECT id, nome, ativa, criada FROM empresas WHERE id = ?", (eid,)).fetchone()
        return dict(r) if r else None


def salvar_empresa(eid, nome, ativa=True):
    """Cria ou altera uma empresa. eid: identificador curto (letras, números, - e _)."""
    import re
    eid = (eid or "").strip().lower()
    nome = (nome or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,29}", eid):
        raise ValueError("Identificador inválido: use de 2 a 30 letras minúsculas, números, - ou _.")
    if not nome:
        raise ValueError("Informe o nome da empresa.")
    with _con() as con:
        if con.execute("SELECT 1 FROM empresas WHERE id = ?", (eid,)).fetchone():
            con.execute("UPDATE empresas SET nome = ?, ativa = ? WHERE id = ?", (nome, 1 if ativa else 0, eid))
        else:
            con.execute("INSERT INTO empresas (id, nome, ativa, criada) VALUES (?,?,?,?)",
                        (eid, nome, 1 if ativa else 0, dt.datetime.now().isoformat(" ", "seconds")))
    return eid


def gerar_chave(eid):
    """Gera uma chave nova para o agente da empresa (a anterior deixa de valer). Mostrada uma única vez."""
    import secrets
    segredo = secrets.token_urlsafe(32)
    with _con() as con:
        n = con.execute("UPDATE empresas SET chave_hash = ? WHERE id = ?", (_hash_chave(segredo), eid)).rowcount
    if not n:
        raise ValueError("Empresa não encontrada.")
    return f"{eid}.{segredo}"


def bloquear_chave(eid):
    with _con() as con:
        con.execute("UPDATE empresas SET chave_hash = NULL WHERE id = ?", (eid,))


def empresa_por_chave(chave):
    """Confere a chave de um agente. Devolve o id da empresa (ativa) ou None."""
    import hmac
    if not chave or "." not in chave or len(chave) > 200:
        return None
    eid, segredo = chave.split(".", 1)
    with _con() as con:
        r = con.execute("SELECT chave_hash FROM empresas WHERE id = ? AND ativa = 1", (eid,)).fetchone()
    if not r or not r["chave_hash"]:
        _hash_chave(segredo)            # mesmo tempo de resposta
        return None
    return eid if hmac.compare_digest(r["chave_hash"], _hash_chave(segredo)) else None


# ------------------------------------------------------------ TP DASH ADMIN (só Tecnoplan): usuários de todas as empresas
def listar_usuarios_empresas():
    """Usuários de todas as empresas clientes (o super administrador não aparece)."""
    with _con() as con:
        return [_dict(r) for r in con.execute(
            "SELECT * FROM usuarios WHERE COALESCE(super, 0) = 0 ORDER BY empresa_id, nome")]


def salvar_usuario_admin(dados, uid=None):
    """Cria ou altera um usuário pela página TP DASH ADMIN, na empresa escolhida no cadastro.
    Mudar o usuário de empresa limpa os relatórios e tipos de movimento escolhidos (eram da empresa anterior)."""
    eid = str(dados.get("empresa") or "").strip()
    if not empresa(eid):
        raise ValueError("Escolha a empresa do usuário.")
    login = (dados.get("login") or "").strip()
    nome = (dados.get("nome") or "").strip()
    if not login or not nome:
        raise ValueError("Informe login e nome.")
    admin = 1 if dados.get("admin") else 0
    ativo = 0 if dados.get("ativo") is False else 1
    modulos = ",".join(m for m in dados.get("modulos") or [] if m in MODULOS) or "inicio"
    with _con() as con:
        if uid:
            r = con.execute("SELECT empresa_id, COALESCE(super, 0) AS super FROM usuarios WHERE id = ?", (uid,)).fetchone()
            if not r or r["super"]:
                raise ValueError("Usuário não encontrado.")
            try:
                con.execute("UPDATE usuarios SET login=?, nome=?, admin=?, modulos=?, ativo=?, empresa_id=? WHERE id=?",
                            (login, nome, admin, modulos, ativo, eid, uid))
            except sqlite3.IntegrityError:
                raise ValueError("Já existe um usuário com esse login.")
            if r["empresa_id"] != eid:
                con.execute("UPDATE usuarios SET relatorios=NULL, tipos_mov=NULL, bancos=NULL WHERE id=?", (uid,))
            if dados.get("senha"):
                con.execute("UPDATE usuarios SET senha_hash=?, trocar_senha=1, falhas_login=0, bloqueado_ate=NULL WHERE id=?",
                            (generate_password_hash(dados["senha"]), uid))
        else:
            if not dados.get("senha"):
                raise ValueError("Informe uma senha inicial.")
            try:
                con.execute("INSERT INTO usuarios (login, nome, senha_hash, admin, modulos, ativo, trocar_senha, empresa_id) "
                            "VALUES (?,?,?,?,?,?,1,?)",
                            (login, nome, generate_password_hash(dados["senha"]), admin, modulos, ativo, eid))
            except sqlite3.IntegrityError:
                raise ValueError("Já existe um usuário com esse login.")
    return eid


# ------------------------------------------------------------ estado dos agentes (gravado pelo site, lido pelo TP DASH ADMIN)
def _tabela_agentes(con):
    con.execute("""CREATE TABLE IF NOT EXISTS agentes_estado (
        empresa_id TEXT PRIMARY KEY, visto REAL, versao TEXT, descricao TEXT, ip TEXT,
        filiais TEXT, filiais_quando REAL, filiais_erro TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS agentes_info (empresa_id TEXT PRIMARY KEY, dados TEXT)")
    con.execute("""CREATE TABLE IF NOT EXISTS agentes_consultas (
        empresa_id TEXT NOT NULL, dia TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, erros INTEGER NOT NULL DEFAULT 0,
        segundos REAL NOT NULL DEFAULT 0, PRIMARY KEY (empresa_id, dia))""")


def gravar_info_agente(eid, dados):
    """O que o agente informa ao conectar (modo, código da empresa, computador, sincronização). Sem senhas."""
    with _con() as con:
        _tabela_agentes(con)
        con.execute("INSERT OR IGNORE INTO agentes_info (empresa_id, dados) VALUES (?, '{}')", (eid,))
        con.execute("UPDATE agentes_info SET dados = ? WHERE empresa_id = ?", (json.dumps(dados, ensure_ascii=False), eid))


def contar_consulta(eid, ok, segundos):
    """Uma consulta feita ao banco da empresa pelo agente: conta por dia, para o TP DASH ADMIN."""
    import datetime as _dt
    dia = _dt.date.today().isoformat()
    with _con() as con:
        _tabela_agentes(con)
        con.execute("INSERT OR IGNORE INTO agentes_consultas (empresa_id, dia) VALUES (?, ?)", (eid, dia))
        con.execute("UPDATE agentes_consultas SET n = n + 1, erros = erros + ?, segundos = segundos + ? "
                    "WHERE empresa_id = ? AND dia = ?", (0 if ok else 1, float(segundos), eid, dia))


def consultas_agentes(dias=7):
    """{empresa: [{dia, n, erros, segundos}, ...]} dos últimos `dias` dias (o mais novo primeiro)."""
    import datetime as _dt
    desde = (_dt.date.today() - _dt.timedelta(days=dias - 1)).isoformat()
    saida = {}
    with _con() as con:
        _tabela_agentes(con)
        for r in con.execute("SELECT empresa_id, dia, n, erros, segundos FROM agentes_consultas WHERE dia >= ? "
                             "ORDER BY dia DESC", (desde,)):
            saida.setdefault(r["empresa_id"], []).append(
                {"dia": r["dia"], "n": r["n"], "erros": r["erros"], "segundos": round(float(r["segundos"]), 1)})
    return saida


def info_agentes():
    with _con() as con:
        _tabela_agentes(con)
        return {r["empresa_id"]: _json(r["dados"]) or {} for r in con.execute("SELECT empresa_id, dados FROM agentes_info")}


def gravar_estado_agente(eid, visto, versao=None, descricao=None, ip=None):
    with _con() as con:
        _tabela_agentes(con)
        con.execute("INSERT OR IGNORE INTO agentes_estado (empresa_id) VALUES (?)", (eid,))
        con.execute("UPDATE agentes_estado SET visto = ? WHERE empresa_id = ?", (visto, eid))
        if versao is not None:
            con.execute("UPDATE agentes_estado SET versao = ?, descricao = ?, ip = ? WHERE empresa_id = ?",
                        (versao, descricao or "", ip or "", eid))


def gravar_filiais(eid, lista, erro=""):
    import time
    with _con() as con:
        _tabela_agentes(con)
        con.execute("INSERT OR IGNORE INTO agentes_estado (empresa_id) VALUES (?)", (eid,))
        if lista is None:
            con.execute("UPDATE agentes_estado SET filiais_erro = ?, filiais_quando = ? WHERE empresa_id = ?",
                        (erro[:300], time.time(), eid))
        else:
            con.execute("UPDATE agentes_estado SET filiais = ?, filiais_quando = ?, filiais_erro = '' WHERE empresa_id = ?",
                        (json.dumps(lista, ensure_ascii=False), time.time(), eid))


def pedir_filiais(eid):
    """O TP DASH ADMIN pede uma leitura nova das filiais: o site lê na próxima vez que o agente falar com ele."""
    with _con() as con:
        _tabela_agentes(con)
        con.execute("INSERT OR IGNORE INTO agentes_estado (empresa_id) VALUES (?)", (eid,))
        con.execute("UPDATE agentes_estado SET filiais_quando = 0 WHERE empresa_id = ?", (eid,))


def filiais_vencidas(eid, segundos):
    import time
    with _con() as con:
        _tabela_agentes(con)
        r = con.execute("SELECT filiais_quando FROM agentes_estado WHERE empresa_id = ?", (eid,)).fetchone()
    return not r or not r["filiais_quando"] or time.time() - r["filiais_quando"] > segundos


def estado_agentes():
    with _con() as con:
        _tabela_agentes(con)
        return {r["empresa_id"]: dict(r) for r in con.execute("SELECT * FROM agentes_estado")}
