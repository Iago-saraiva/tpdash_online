"""TP DASH ADMIN: site separado, só da Tecnoplan, para cadastrar empresas, chaves dos agentes e usuários.

Usa o mesmo banco do site TP DASH online (site\\dados\\painel.sqlite), mas roda em outro processo,
em outra porta (ou outro endereço) e com login próprio: só entra o administrador da Tecnoplan.
O site TP DASH online grava no banco o estado de cada agente e as filiais da empresa, e este site só lê.
"""
import configparser
import datetime as dt
import functools
import ipaddress
import os
import secrets
import sys
import time

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_from_directory, session

import mimetypes

# no Windows o tipo do .js às vezes vem errado do registro e o navegador recusa o script do React
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(AQUI, "admin.ini")


NUVEM = os.environ.get("TPDASH_NUVEM", "").strip() == "1"


def _carregar():
    if NUVEM:
        return _da_nuvem()
    if not os.path.exists(CONFIG_PATH):
        with open(os.path.join(AQUI, "admin.ini.exemplo"), encoding="utf-8") as f:
            txt = f.read().replace("GERAR-AUTOMATICO", secrets.token_hex(32))
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(txt)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG_PATH, encoding="utf-8")
    s = cp["admin"] if cp.has_section("admin") else {}
    sim = lambda v: str(v).strip().lower() in ("sim", "s", "1", "true", "yes")  # noqa: E731
    return {
        "host": s.get("host", "0.0.0.0").strip(),
        "porta": int(s.get("porta", "8071")),
        "pasta_site": os.path.abspath(os.path.join(AQUI, s.get("pasta_site", "../site").strip())),
        "chave_secreta": s.get("chave_secreta", "").strip() or secrets.token_hex(32),
        "sessao_minutos": int(s.get("sessao_minutos", "60")),
        "cookie_seguro": sim(s.get("cookie_seguro", "nao")),
        "atras_de_proxy": sim(s.get("atras_de_proxy", "nao")),
        "permitir": [x.strip() for x in s.get("permitir", "").replace(";", ",").split(",") if x.strip()],
    }


def _da_nuvem():
    """Hospedado (Render): sem admin.ini, tudo pelas variáveis de ambiente. Roda junto do site (servidor_nuvem.py)."""
    e = os.environ.get
    sim = lambda v: str(v).strip().lower() in ("sim", "s", "1", "true", "yes")  # noqa: E731
    chave = e("TPDASH_ADMIN_CHAVE_SECRETA", "").strip()
    if len(chave) < 32:
        raise SystemExit("Defina a variável de ambiente TPDASH_ADMIN_CHAVE_SECRETA (32 caracteres ou mais).")
    return {
        "host": "0.0.0.0", "porta": int(e("PORT", "10000")),
        "pasta_site": os.path.abspath(os.path.join(AQUI, "..", "site")),
        "chave_secreta": chave,
        "sessao_minutos": int(e("TPDASH_ADMIN_SESSAO_MINUTOS", "60")),
        "cookie_seguro": sim(e("TPDASH_COOKIE_SEGURO", "sim")),
        "atras_de_proxy": sim(e("TPDASH_ATRAS_DE_PROXY", "sim")),
        "permitir": [x.strip() for x in e("TPDASH_ADMIN_PERMITIR", "").replace(";", ",").split(",") if x.strip()],
    }


CFG = _carregar()
sys.path.insert(0, CFG["pasta_site"])
import usuarios  # noqa: E402  (módulo do site: mesmo banco de usuários e empresas)

usuarios.iniciar(site=True)
ONLINE_SEGUNDOS = 75          # o site grava o "visto" do agente a cada ~20-45 s

app = Flask(__name__, static_folder=None)
if CFG["atras_de_proxy"]:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = CFG["chave_secreta"]
app.json.sort_keys = False
app.config.update(
    SESSION_COOKIE_NAME="tpadmin_sessao", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=CFG["cookie_seguro"], MAX_CONTENT_LENGTH=256 * 1024,
    PERMANENT_SESSION_LIFETIME=dt.timedelta(minutes=CFG["sessao_minutos"]),
)

_REDES = [ipaddress.ip_network(r, strict=False) for r in CFG["permitir"]]
_FALHAS = {}                  # ip -> [tentativas, bloqueado_ate]


# ------------------------------------------------------------------ segurança
@app.before_request
def filtrar_ip():
    if not _REDES:
        return None
    try:
        ip = ipaddress.ip_address(request.remote_addr or "")
    except ValueError:
        abort(403)
    if ip.is_loopback or any(ip in r for r in _REDES):
        return None
    return Response("Acesso não permitido a partir deste computador.", 403, mimetype="text/plain")


@app.after_request
def cabecalhos(resp):
    h = resp.headers
    h["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Cache-Control"] = "no-store"
    h["X-Robots-Tag"] = "noindex, nofollow"
    if CFG["cookie_seguro"]:
        h["Strict-Transport-Security"] = "max-age=31536000"
    h.pop("Server", None)
    return resp


def _token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = _token


def _base():
    """Início do endereço do ADMIN: vazio no endereço próprio, ou o caminho quando roda em /algum-caminho."""
    return request.script_root or ""


app.jinja_env.globals["base"] = _base


@app.before_request
def carregar_usuario():
    g.usuario = None
    uid = session.get("uid")
    if uid:
        u = usuarios.obter(uid)
        if u and u.get("super"):
            g.usuario = u
        else:
            session.clear()


def exige(fn):
    @functools.wraps(fn)
    def wrap(*a, **kw):
        api = request.path.startswith("/api/")
        if not g.usuario:
            return (jsonify(erro="Sessão expirada. Entre novamente."), 401) if api else redirect(_base() + "/login")
        if g.usuario.get("trocar_senha") and request.endpoint != "trocar_senha":
            return (jsonify(erro="Troque sua senha antes de continuar."), 403) if api else redirect(_base() + "/trocar-senha")
        if request.method == "POST" and api and request.headers.get("X-Admin") != session.get("csrf"):
            return jsonify(erro="Requisição inválida (token)."), 400
        return fn(*a, **kw)
    return wrap


# ------------------------------------------------------------------ arquivos (os do ADMIN e, se faltar, os do site)
@app.route("/static/<path:arquivo>")
def estaticos(arquivo):
    if os.path.exists(os.path.join(AQUI, "static", arquivo)):
        return send_from_directory(os.path.join(AQUI, "static"), arquivo)
    if arquivo in ("app.css", "logo-tpdash-preto.svg", "logo-tpdash.svg", "icone.ico", "cabeca.js"):
        return send_from_directory(os.path.join(CFG["pasta_site"], "static"), arquivo)
    abort(404)


@app.route("/favicon.ico")
def favicon():
    return estaticos("icone.ico")


# ------------------------------------------------------------------ login
@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    ip = request.remote_addr or "?"
    if request.method == "POST":
        tent, ate = _FALHAS.get(ip, [0, 0])
        if ate > time.time():
            erro = f"Muitas tentativas erradas. Tente de novo em {int(ate - time.time()) // 60 + 1} minuto(s)."
        elif request.form.get("csrf") != session.get("csrf"):
            erro = "Formulário expirado, tente de novo."
        else:
            login_txt = request.form.get("login", "")[:60]
            try:
                u = usuarios.autenticar(login_txt, request.form.get("senha", ""))
            except usuarios.Bloqueado as e:
                u, erro = None, str(e)
            if u and not u.get("super"):
                u = None                                      # usuário de empresa cliente não entra aqui
            if u:
                _FALHAS.pop(ip, None)
                session.clear()
                session.permanent = True
                session["uid"] = u["id"]
                usuarios.registrar(u["login"], "login no TP DASH ADMIN", f"IP {ip}")
                return redirect(_base() + "/")
            tent += 1
            _FALHAS[ip] = [0, time.time() + 300] if tent >= 5 else [tent, 0]
            usuarios.registrar(login_txt or "?", "login recusado no TP DASH ADMIN", f"IP {ip}")
            time.sleep(0.8)
            erro = erro or "Login ou senha incorretos."
    return render_template("login.html", erro=erro)


@app.route("/sair")
def sair():
    session.clear()
    return redirect(_base() + "/login")


@app.route("/trocar-senha", methods=["GET", "POST"])
@exige
def trocar_senha():
    erro = None
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            erro = "Formulário expirado, tente de novo."
        elif request.form.get("nova") != request.form.get("confirma"):
            erro = "A confirmação não confere com a nova senha."
        else:
            try:
                usuarios.trocar_senha(g.usuario["id"], request.form.get("atual", ""), request.form.get("nova", ""))
                return redirect(_base() + "/")
            except ValueError as e:
                erro = str(e)
    return render_template("trocar_senha.html", erro=erro)


# ------------------------------------------------------------------ página
def _arquivos_react():
    """Arquivos gerados pelo build do React (admin/frontend -> admin/static/app). Lidos do manifest do Vite."""
    import json
    with open(os.path.join(AQUI, "static", "app", ".vite", "manifest.json"), encoding="utf-8") as f:
        entrada = json.load(f)["src/main.tsx"]
    return "app/" + entrada["file"], ["app/" + c for c in entrada.get("css", [])]


@app.route("/")
@exige
def inicio():
    js, css = _arquivos_react()
    return render_template("painel.html", usuario=g.usuario, js=js, css=css)


# ------------------------------------------------------------------ API
def _empresas_com_estado():
    est = usuarios.estado_agentes()
    infos = usuarios.info_agentes()
    consultas = usuarios.consultas_agentes(7)
    hoje = dt.date.today().isoformat()
    agora = time.time()
    lista = usuarios.listar_empresas()
    for e in lista:
        a = est.get(e["id"]) or {}
        visto = a.get("visto") or 0
        e["online"] = bool(e["ativa"] and e["tem_chave"] and agora - visto <= ONLINE_SEGUNDOS)
        e["visto"] = dt.datetime.fromtimestamp(visto).strftime("%d/%m/%Y %H:%M:%S") if visto else None
        e["versao"] = a.get("versao") or ""
        e["banco"] = a.get("descricao") or ""
        e["filiais"] = usuarios._json(a.get("filiais"))
        e["filiais_erro"] = a.get("filiais_erro") or ""
        e["filiais_pedidas"] = a.get("filiais_quando") == 0
        e["filiais_lidas"] = (dt.datetime.fromtimestamp(a["filiais_quando"]).strftime("%d/%m/%Y %H:%M")
                              if a.get("filiais_quando") else None)
        i = infos.get(e["id"]) or {}
        e["ip"] = a.get("ip") or ""
        e["agente"] = {
            "modo": i.get("modo") or "", "codempresa": i.get("codempresa"), "maquina": i.get("maquina") or "",
            "sistema": i.get("sistema") or "", "sincronizacao": i.get("sincronizacao"),
            "conectado": dt.datetime.fromtimestamp(i["conectado"]).strftime("%d/%m/%Y %H:%M:%S") if i.get("conectado") else None}
        dias = consultas.get(e["id"]) or []
        e["consultas"] = {"hoje": next((d for d in dias if d["dia"] == hoje), None), "dias": dias,
                          "semana": sum(d["n"] for d in dias)}
    return lista


@app.route("/api/empresas", methods=["GET", "POST"])
@exige
def api_empresas():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        try:
            eid = usuarios.salvar_empresa(d.get("id"), d.get("nome"), d.get("ativa", True) is not False)
        except ValueError as e:
            return jsonify(erro=str(e)), 400
        usuarios.registrar(g.usuario["login"], "salvou empresa (TP DASH ADMIN)", eid)
        return jsonify(ok=True, id=eid)
    return jsonify(empresas=_empresas_com_estado())


@app.route("/api/empresas/<eid>/chave", methods=["POST"])
@exige
def api_empresa_chave(eid):
    """Gera uma chave nova para o agente (a anterior para de funcionar). Mostrada só nesta resposta."""
    acao = (request.get_json(silent=True) or {}).get("acao")
    try:
        if acao == "bloquear":
            usuarios.bloquear_chave(eid)
            usuarios.registrar(g.usuario["login"], "bloqueou chave do agente", eid)
            return jsonify(ok=True)
        chave = usuarios.gerar_chave(eid)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    usuarios.registrar(g.usuario["login"], "gerou chave do agente", eid)
    return jsonify(ok=True, chave=chave)


@app.route("/api/empresas/<eid>/filiais", methods=["POST"])
@exige
def api_empresa_filiais(eid):
    """Pede ao site uma leitura nova das filiais (feita assim que o agente da empresa falar com o site)."""
    if not usuarios.empresa(eid):
        return jsonify(erro="Empresa não encontrada."), 404
    usuarios.pedir_filiais(eid)
    return jsonify(ok=True)


@app.route("/api/usuarios", methods=["GET", "POST"])
@exige
def api_usuarios():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        try:
            eid = usuarios.salvar_usuario_admin(d, d.get("id"))
        except ValueError as e:
            return jsonify(erro=str(e)), 400
        usuarios.registrar(g.usuario["login"], "salvou usuário (TP DASH ADMIN)", f"{d.get('login', '')} ({eid})")
        return jsonify(ok=True)
    return jsonify(usuarios=usuarios.listar_usuarios_empresas(), modulos=usuarios.MODULOS)


if __name__ == "__main__":
    from waitress import serve
    print(f"TP DASH ADMIN em http://{'localhost' if CFG['host'] in ('0.0.0.0', '') else CFG['host']}:{CFG['porta']}")
    serve(app, host=CFG["host"], port=CFG["porta"], threads=8)
