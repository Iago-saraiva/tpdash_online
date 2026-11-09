"""TP DASH - dashboard web com conexão direta (somente leitura) ao banco Firebird do Puma."""
import datetime as dt
import functools
import json
import os
import re
import secrets
import threading
import time

from flask import (Flask, Response, abort, g, jsonify, redirect, render_template, request, session,
                   url_for)

import assistente
import bancos
import config
import copia
import copia_leitura
import db
import exportar
import layout
import servicos
import rb_sync
import relatorios_rb
import usuarios

CFG = config.carregar()
SITE = CFG["site"]              # TP DASH online: cada empresa (cliente) tem seu agente; ver nuvem.py
usuarios.iniciar(site=SITE)

app = Flask(__name__)
if SITE and CFG["atras_de_proxy"]:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = CFG["chave_secreta"]
app.json.sort_keys = False
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=CFG["https"] or (SITE and CFG["cookie_seguro"]),
    SESSION_COOKIE_NAME="painel_sessao",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=dt.timedelta(minutes=CFG["timeout_minutos"]),
    JSON_AS_ASCII=False,
)

# Sessão: "Manter conectado neste aparelho" vale [servidor] lembrar_dias (padrão 30);
# sem marcar, a sessão expira após sessao_minutos sem uso.
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature


class _Sessao(SecureCookieSessionInterface):
    def open_session(self, app_, req):
        s = self.get_signing_serializer(app_)
        if s is None:
            return None
        valor = req.cookies.get(self.get_cookie_name(app_))
        if not valor:
            return self.session_class()
        try:
            return self.session_class(s.loads(valor, max_age=max(CFG["lembrar_dias"], 1) * 86400))
        except BadSignature:
            return self.session_class()

    def get_expiration_time(self, app_, sess):
        if sess.get("lembrar"):
            return dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=CFG["lembrar_dias"])
        return super().get_expiration_time(app_, sess)


app.session_interface = _Sessao()

# ------------------------------------------------------------------ vários bancos (uma empresa por banco)
# Configuração de cada banco = config geral + o que é próprio dele ([banco] ou [banco:ID] no config.ini)
_conexoes = {}
if SITE:
    from collections.abc import Mapping

    import nuvem

    class _EmpresasDoSite(Mapping):
        """No site, cada "banco" é uma empresa cliente cadastrada (ativa); o resto vem do agente dela."""

        def __getitem__(self, bid):
            e = usuarios.empresa(bid) if bid else None
            if not e or not e["ativa"]:
                raise KeyError(bid)
            i = nuvem.info(bid)
            return {**CFG, "id": bid, "nome": e["nome"], "nome_empresa": e["nome"],
                    "modo": i.get("modo") or "firebird", "empresa": int(i.get("empresa") or 1),
                    "status_movimento": i.get("status_movimento") or CFG["status_movimento"],
                    "status_lancamento": i.get("status_lancamento") or CFG["status_lancamento"]}

        def __iter__(self):
            return iter([e["id"] for e in usuarios.listar_empresas(so_ativas=True)])

        def __len__(self):
            return len(usuarios.listar_empresas(so_ativas=True))

    _CFGS = _EmpresasDoSite()
else:
    _CFGS = {bid: {**CFG, **b, "nome_empresa": b["nome"]} for bid, b in CFG["bancos"].items()}


def _bid():
    """Banco escolhido pelo usuário (fora de uma requisição: o principal)."""
    try:
        return g.get("banco_id") or bancos.PRINCIPAL
    except RuntimeError:
        return bancos.PRINCIPAL


bancos.atual = _bid


def C(bid=None):
    """Configuração do banco em uso (empresa, modo, status...)."""
    if SITE:
        c = _CFGS.get(bid or _bid())
        if not c:
            raise db.ErroBanco("Empresa não encontrada ou desativada.")
        return c
    return _CFGS.get(bid or _bid()) or _CFGS[bancos.PRINCIPAL]


def banco(bid=None):
    bid = bid or _bid()
    if SITE:
        C(bid)                                   # confere se a empresa existe e está ativa
        return copia_leitura.BancoHibrido(bid, ao_usar=_marcar_fonte)   # cópia no Neon quando dá; senão, o agente
    if bid not in _conexoes:
        _conexoes[bid] = db.abrir(C(bid))
    return _conexoes[bid]


def _marcar_fonte(fonte, recebido=None):
    """Guarda de onde vieram os dados desta requisição (cópia ou agente), para o cabeçalho X-Dados."""
    f = g.setdefault("fontes", {})
    f[fonte] = True
    if fonte == "copia" and recebido:
        g.dados_de = min(g.get("dados_de") or recebido, recebido)


def _banco_vivo():
    """Banco direto no servidor da empresa (Consulta SQL: o usuário escreve o SQL, roda sempre no Firebird)."""
    b = banco()
    return getattr(b, "remoto", b)


def _bancos_usuario(u):
    """Bancos que o usuário pode escolher, na ordem do config.ini."""
    if not u:
        return []
    if SITE:
        # TP DASH online: o usuário só enxerga a empresa dele; só o super administrador (Tecnoplan) vê todas
        if u.get("super"):
            return list(_CFGS)
        e = u.get("empresa_id")
        return [e] if e and e in _CFGS else []
    lib = u.get("bancos")
    return [b for b in _CFGS if u.get("admin") or lib is None or b in lib]


def _empresa_da_requisicao():
    try:
        return g.get("banco_id") or "-"          # "-" não casa com nenhuma empresa
    except RuntimeError:
        return None                               # fora de requisição (tarefas em segundo plano)


if SITE:
    usuarios.empresa_atual = _empresa_da_requisicao


def _lista_bancos(ids):
    return [{"id": b, "nome": _CFGS[b]["nome_empresa"]} for b in ids]


# ------------------------------------------------------------------ segurança
import ipaddress

_REDES = []
for _r in CFG["permitir"]:
    try:
        _REDES.append(ipaddress.ip_network(_r, strict=False))
    except ValueError:
        print(f"[config] faixa de IP inválida em [servidor] permitir: {_r}")


@app.before_request
def filtrar_ip():
    """Só atende os IPs/faixas de [servidor] permitir (vazio = todos). O próprio servidor sempre pode."""
    if not _REDES:
        return None
    try:
        ip = ipaddress.ip_address(request.remote_addr or "")
    except ValueError:
        abort(403)
    if ip.is_loopback or any(ip in r for r in _REDES):
        return None
    return Response("Acesso não permitido a partir deste computador.", 403, mimetype="text/plain")


_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; worker-src 'self'; manifest-src 'self'")


@app.after_request
def cabecalhos_seguranca(resp):
    h = resp.headers
    fontes = g.get("fontes") or {}
    if fontes:
        # de onde vieram os dados: "copia:<hora da última sincronização>", "agente" ou "misto:<hora>"
        de = int(g.get("dados_de") or 0)
        h["X-Dados"] = (f"misto:{de}" if fontes.get("agente") else f"copia:{de}") if fontes.get("copia") else "agente"
    h.setdefault("Content-Security-Policy", _CSP)
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    if CFG["https"]:
        h["Strict-Transport-Security"] = "max-age=31536000"
    if request.path.startswith("/api/") or resp.mimetype in ("text/html",):
        h["Cache-Control"] = "no-store"     # dados da empresa não ficam no cache do navegador
    h.pop("Server", None)
    return resp


# ------------------------------------------------------------------ autenticação
@app.before_request
def carregar_usuario():
    g.usuario = None
    uid = session.get("uid")
    if uid and not session.get("lembrar"):
        agora = time.time()
        if agora - session.get("visto", agora) > CFG["timeout_minutos"] * 60:
            session.clear()
            uid = None
        elif agora - session.get("visto", 0) > 60:
            session["visto"] = agora          # renova (no máximo 1x por minuto)
    g.banco_id = None
    if uid:
        g.usuario = usuarios.obter(uid)
        if g.usuario and SITE and not g.usuario.get("admin"):
            # TP DASH online: Consulta SQL e assistente só para administradores
            g.usuario["modulos"] = [m for m in g.usuario["modulos"] if m not in ("sql", "chat")]
        if not g.usuario:
            session.clear()
        else:
            _marcar_ativo(g.usuario)
            perm = _bancos_usuario(g.usuario)
            bid = session.get("banco")
            g.banco_id = bid if bid in perm else (perm[0] if perm else None)


# ------------------------------------------------------------------ conexões (para o ícone da bandeja do servidor)
_ATIVOS = {}                 # (login, ip) -> dados da última requisição
_ATIVOS_TRAVA = threading.Lock()
_INICIO_PAINEL = dt.datetime.now()
_ARQ_TOKEN_LOCAL = os.path.join(config.DADOS_DIR, "bandeja.token")


def _navegador(ua):
    ua = ua or ""
    so = ("Android" if "Android" in ua else "iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua
          else "Windows" if "Windows" in ua else "Mac" if "Mac OS" in ua else "Linux" if "Linux" in ua else "")
    nav = ("App TP DASH" if ("TPDash" in ua or "PainelPuma" in ua) else "Edge" if "Edg/" in ua else "Chrome" if "Chrome/" in ua
           else "Firefox" if "Firefox/" in ua else "Safari" if "Safari/" in ua else "")
    return " · ".join(x for x in (nav, so) if x) or "navegador"


def _marcar_ativo(u):
    agora = time.time()
    chave = (u["login"], request.remote_addr or "?")
    with _ATIVOS_TRAVA:
        a = _ATIVOS.get(chave)
        if not a:
            a = _ATIVOS[chave] = {"login": u["login"], "nome": u.get("nome") or u["login"], "ip": chave[1],
                                  "inicio": agora, "requisicoes": 0}
        a["ultimo"] = agora
        a["requisicoes"] += 1
        a["navegador"] = _navegador(request.headers.get("User-Agent"))
        if not request.path.startswith(("/api/", "/static/")) and "." not in request.path.rsplit("/", 1)[-1]:
            a["pagina"] = request.path
        if len(_ATIVOS) > 500:                       # esquece quem sumiu há mais de 1 dia
            for k in [k for k, v in _ATIVOS.items() if agora - v["ultimo"] > 86400]:
                _ATIVOS.pop(k, None)


def _token_local():
    """Senha só da bandeja: gravada em dados\\bandeja.token (pasta que só administradores e o serviço leem)."""
    try:
        with open(_ARQ_TOKEN_LOCAL, encoding="utf-8") as f:
            t = f.read().strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    try:
        os.makedirs(os.path.dirname(_ARQ_TOKEN_LOCAL), exist_ok=True)
        with open(_ARQ_TOKEN_LOCAL, "w", encoding="utf-8") as f:
            f.write(t)
    except OSError:
        return None
    return t


_TOKEN_LOCAL = _token_local()


@app.route("/api/local/conexoes")
def api_local_conexoes():
    """Usado só pelo ícone da bandeja no próprio servidor (endereço local + senha do arquivo bandeja.token)."""
    try:
        local = ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        local = False
    if not local or not _TOKEN_LOCAL or not secrets.compare_digest(request.headers.get("X-Painel-Local", ""), _TOKEN_LOCAL):
        abort(404)
    agora = time.time()
    with _ATIVOS_TRAVA:
        lista = [dict(v) for v in _ATIVOS.values()]
    hoje = dt.date.today().isoformat()
    ativos = sorted((v for v in lista if agora - v["ultimo"] <= 10 * 60), key=lambda v: -v["ultimo"])
    hoje_lista = sorted((v for v in lista if dt.date.fromtimestamp(v["ultimo"]).isoformat() == hoje),
                        key=lambda v: -v["ultimo"])
    fmt = lambda ts: dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")
    for v in ativos + hoje_lista:
        v["ha_segundos"] = int(agora - v["ultimo"])
        v["ultimo_txt"], v["inicio_txt"] = fmt(v["ultimo"]), fmt(v["inicio"])
    logins = [a for a in usuarios.ultimos_acessos(400) if a["acao"] in ("login", "login recusado")][:50]
    return jsonify(inicio=_INICIO_PAINEL.strftime("%d/%m/%Y %H:%M"), agora=dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                   empresa=CFG["nome_empresa"], ativos=ativos, hoje=hoje_lista, logins=logins)


def _token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = _token


# rotas que o super administrador usa mesmo sem nenhuma empresa cadastrada ainda
_SEM_EMPRESA = {"trocar_senha", "sem_empresa"}


def exige(modulo=None, admin=False):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **kw):
            api = request.path.startswith("/api/")
            u = g.usuario
            if not u:
                if api:
                    return jsonify(erro="Sessão expirada. Entre novamente."), 401
                return redirect(url_for("login", proximo=request.path))
            if u.get("trocar_senha") and request.endpoint not in ("trocar_senha", "sair"):
                if api:
                    return jsonify(erro="Troque sua senha antes de continuar."), 403
                return redirect(url_for("trocar_senha"))
            if not g.banco_id and not (SITE and u.get("super") and request.endpoint in _SEM_EMPRESA):
                if SITE and u.get("super") and not api:
                    return redirect("/sem-empresa")
                if api:
                    return jsonify(erro="Nenhuma empresa (banco) liberada para você. Fale com o administrador."), 403
                abort(403)
            if admin and not u.get("admin"):
                abort(403)
            if modulo and modulo not in u["modulos"]:
                if api:
                    return jsonify(erro="Você não tem permissão para este módulo."), 403
                telas = [m for m in u["modulos"] if m in PAGINAS]
                if modulo == "inicio" and telas:
                    return redirect(PAGINAS[telas[0]][0])
                abort(403)
            if request.method == "POST" and api and request.headers.get("X-Painel") != _token():
                return jsonify(erro="Requisição inválida (token)."), 400
            return fn(*a, **kw)
        return wrap
    return deco


@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    r = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    r.headers["Service-Worker-Allowed"] = "/"
    return r


@app.route("/manifest.webmanifest")
def manifesto():
    from flask import send_from_directory
    return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/certificado.cer")
def baixar_certificado():
    """Certificado público do painel (sem a chave), para instalar em celulares e PCs."""
    import certificado
    from flask import send_file
    if SITE or not CFG["https"] or not __import__("os").path.exists(certificado.CER):
        abort(404)
    return send_file(certificado.CER, mimetype="application/x-x509-ca-cert", as_attachment=True,
                     download_name="tp-dash.cer")


@app.route("/instalar")
def pagina_instalar():
    """Guia para instalar o TP DASH como app (aberta sem login, para facilitar no celular)."""
    return render_template("instalar.html", empresa=CFG["nome_empresa"], https=CFG["https"])


@app.route("/qr.svg")
def qr_instalar():
    """QR Code com o endereço da página /instalar deste servidor (como o computador o acessou)."""
    import qr
    base = f"{'https' if CFG['https'] else 'http'}://{request.host}"
    if request.host.split(":")[0].lower() in ("localhost", "127.0.0.1", "[::1]"):
        # aberto no próprio servidor: o celular precisa de um endereço da rede (usa o IP, que todo celular entende)
        ips = [e for e in _enderecos() if e.split("://")[1][:1].isdigit()]
        base = ips[0] if ips else base
    destino = base + "/instalar"
    r = Response(qr.svg(destino), mimetype="image/svg+xml")
    r.headers["Cache-Control"] = "no-store"
    return r


@app.route("/app-windows.zip")
@exige()
def baixar_app_windows():
    """Pacote do app para Windows já configurado com o endereço deste servidor (e o certificado, com HTTPS)."""
    if SITE:
        abort(404)
    import io
    import os
    import zipfile
    from config import BASE_DIR
    import certificado
    pasta = os.path.join(BASE_DIR, "app_cliente")
    endereco = f"{'https' if CFG['https'] else 'http'}://{request.host}"
    local = request.host.split(":")[0].lower() in ("localhost", "127.0.0.1", "[::1]")
    lista = [] if local else [endereco]
    for e in _enderecos():
        if e.lower() != endereco.lower() and len(lista) < 5:
            lista.append(e)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ("TPDash.exe", "criar_atalho.bat", "LEIA-ME.txt", "HASHES.txt"):
            caminho = os.path.join(pasta, nome)
            if os.path.exists(caminho):
                z.write(caminho, f"TPDash/{nome}")
        z.writestr("TPDash/TPDash.ini",
                   "; TP DASH - configuração do aplicativo (TPDash.exe)\r\n[app]\r\n"
                   "; vários endereços: o app usa o primeiro que responder\r\n"
                   f"servidor = {', '.join(lista)}\r\n")
        if CFG["https"] and os.path.exists(certificado.CER):
            z.write(certificado.CER, "TPDash/painel.cer")
    usuarios.registrar(g.usuario["login"], "baixou app Windows", endereco)
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="TPDash-Windows.zip"'})


@app.route("/favicon.ico")
def favicon():
    from flask import send_from_directory
    return send_from_directory(app.static_folder, "icone.ico", mimetype="image/x-icon")


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            erro = "Formulário expirado, tente de novo."
        else:
            ip = request.remote_addr or "?"
            login_txt = request.form.get("login", "")[:60]
            try:
                u = usuarios.autenticar(login_txt, request.form.get("senha", ""))
            except usuarios.Bloqueado as e:
                u, erro = None, str(e)
            if SITE:
                lib = _bancos_usuario(u) if u else []
                pref = request.cookies.get("painel_banco")
                escolhido = pref if pref in lib else (lib[0] if lib else None)
                if u and not escolhido and not u.get("super"):     # o super entra mesmo sem empresa cadastrada
                    usuarios.registrar(u["login"], "login recusado", "sem empresa ativa")
                    u, erro = None, "Seu usuário não está ligado a nenhuma empresa ativa. Fale com o administrador."
            else:
                escolhido = request.form.get("banco") or bancos.PRINCIPAL
                if escolhido not in _CFGS:
                    escolhido = bancos.PRINCIPAL
            if u and not SITE and escolhido not in _bancos_usuario(u):
                usuarios.registrar(u["login"], "login recusado", f"sem acesso à empresa {_CFGS[escolhido]['nome_empresa']}")
                u, erro = None, f"Você não tem acesso à empresa {_CFGS[escolhido]['nome_empresa']}."
            if u:
                session.clear()
                session.permanent = True
                session["uid"] = u["id"]
                session["banco"] = escolhido
                session["visto"] = time.time()
                if request.form.get("lembrar") and CFG["lembrar_dias"] > 0:
                    session["lembrar"] = True
                g.banco_id = escolhido
                usuarios.registrar(u["login"], "login", " · ".join(x for x in (
                    f"IP {ip}", _CFGS[escolhido]["nome_empresa"] if escolhido and len(_CFGS) > 1 else "") if x))
                destino = request.args.get("proximo") or "/"
                seguro = destino.startswith("/") and not destino.startswith("//") and "\\" not in destino
                r = redirect(destino if seguro else "/")
                if escolhido:
                    r.set_cookie("painel_banco", escolhido, max_age=365 * 86400, samesite="Strict",
                                 secure=CFG["https"] or (SITE and CFG["cookie_seguro"]), httponly=True)
                return r
            usuarios.registrar(login_txt or "?", "login recusado", f"IP {ip}")
            time.sleep(0.8)
            erro = erro or "Login ou senha incorretos."
    sel = request.form.get("banco") or request.cookies.get("painel_banco")
    lista = _lista_bancos(list(_CFGS)) if (not SITE and len(_CFGS) > 1) else []
    banco_sel = sel if (not SITE and sel in _CFGS) else bancos.PRINCIPAL
    if _react():
        return _spa("login", "Entrar", erro=erro, empresa=CFG["nome_empresa"], lembrar=CFG["lembrar_dias"] > 0,
                    bancos_login=lista, banco_sel=banco_sel)
    return render_template("login.html", erro=erro, empresa=CFG["nome_empresa"], lembrar=CFG["lembrar_dias"] > 0,
                           bancos=lista, banco_sel=banco_sel)


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/trocar-senha", methods=["GET", "POST"])
@exige()
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
                return redirect("/")
            except ValueError as e:
                erro = str(e)
    empresa = C()["nome_empresa"] if g.banco_id else CFG["nome_empresa"]
    if _react():
        return _spa("trocar_senha", "Trocar senha", erro=erro, empresa=empresa)
    return render_template("trocar_senha.html", erro=erro, empresa=empresa)


# ------------------------------------------------------------------ páginas
PAGINAS = {
    "inicio": ("/", "Início"),
    "movimentos": ("/movimentos", "Movimentos"),
    "movimentacoes": ("/movimentacoes", "Movimentações"),
    "estoque": ("/estoque", "Estoque"),
    "financeiro": ("/financeiro", "Financeiro"),
    "cadastros": ("/cadastros", "Cadastros"),
    "frotas": ("/frotas", "Frotas"),
    "relatorios": ("/relatorios", "Relatórios"),
    "sql": ("/sql", "Consulta SQL"),
}


# ------------------------------------------------------------------ telas em React (site/frontend -> static/app)
# As telas desta lista já foram migradas para React; as outras continuam nos templates antigos.
# TPDASH_REACT=0 volta tudo para as telas antigas (sem precisar de outro build).
TELAS_REACT = {"inicio", "movimentos", "movimentacoes", "financeiro", "estoque", "cadastros", "frotas", "relatorios", "sql", "admin"}


def _arquivo_react():
    """Arquivo .js gerado pelo build do React (lido do manifest do Vite). None se o build não existir."""
    try:
        with open(os.path.join(app.static_folder, "app", ".vite", "manifest.json"), encoding="utf-8") as f:
            return "app/" + json.load(f)["src/main.tsx"]["file"]
    except (OSError, ValueError, KeyError):
        return None


def _react():
    return os.environ.get("TPDASH_REACT", "1") != "0" and _arquivo_react() is not None


def _spa(tela, titulo, **dados):
    """Página do React: os dados iniciais vão num <script type="application/json"> e o React monta a tela."""
    u = g.get("usuario")
    d = {"tela": tela, "titulo": titulo, "csrf": _token(), "modo": "", "empresa": CFG["nome_empresa"]}
    if u and tela not in ("login", "trocar_senha"):
        d.update(
            empresa=C()["nome_empresa"], modo=C()["modo"],
            usuario={"nome": u["nome"], "admin": bool(u.get("admin")), "modulos": list(u["modulos"])},
            paginas=[{"chave": k, "url": v[0], "titulo": v[1]} for k, v in PAGINAS.items() if k in u["modulos"]],
            react=sorted(TELAS_REACT), admin_link=bool(u.get("admin") and _bid()),
            bancos=_lista_bancos(_bancos_usuario(u)), banco_atual=_bid(),
        )
    d.update(dados)
    chat = bool(u and "chat" in u["modulos"] and tela not in ("login", "trocar_senha"))
    return render_template("spa.html", dados=d, js=_arquivo_react(), chat=chat)


def _pagina(modulo):
    if modulo in TELAS_REACT and _react():
        return _spa(modulo, PAGINAS.get(modulo, ("", "Administração"))[1])
    return render_template(
        f"{modulo}.html", pagina=modulo, paginas=PAGINAS, usuario=g.usuario,
        empresa=C()["nome_empresa"], modo=C()["modo"], titulo=PAGINAS.get(modulo, ("", "Administração"))[1],
        bancos_usuario=_lista_bancos(_bancos_usuario(g.usuario)), banco_atual=_bid(),
    )


def _rota(modulo):
    caminho = PAGINAS[modulo][0]
    view = exige(modulo)(lambda: _pagina(modulo))
    view.__name__ = f"pagina_{modulo}"
    app.add_url_rule(caminho, view.__name__, view)


for _m in PAGINAS:
    _rota(_m)


@app.route("/sem-empresa")
@exige()
def sem_empresa():
    """O administrador da Tecnoplan entrou no TP DASH sem nenhuma empresa ativa cadastrada."""
    return render_template("erro.html", msg="Nenhuma empresa ativa cadastrada. Cadastre as empresas no TP DASH ADMIN."), 200


@app.route("/admin")
@exige(admin=True)
def pagina_admin():
    return _pagina("admin")


@app.errorhandler(403)
def proibido(_e):
    return render_template("erro.html", msg="Você não tem permissão para acessar esta página.",
                           empresa=C()["nome_empresa"] if g.get("banco_id") else CFG["nome_empresa"]), 403


# ------------------------------------------------------------------ API: dados
def _args():
    a = request.args.to_dict()
    a.pop("_tipos_perm", None)
    a.pop("_frota", None)
    a["_tipos_perm"] = _tipos()
    return a


def _tipos():
    """Tipos de movimento liberados para o usuário ([] = todos)."""
    return (g.usuario or {}).get("tipos_mov") or []


def _rel_ok(chave, pasta=None):
    """Relatório liberado na lista do usuário? (None = todos os dos módulos que ele tem)."""
    u = g.usuario
    sel = u.get("relatorios")
    if u.get("admin") or sel is None:
        return True
    return chave in sel.get("ids", []) or (pasta is not None and pasta in sel.get("pastas", []))


def _resposta(nome, titulo, dados, subtitulo=""):
    """Devolve JSON ou, com ?formato=xlsx|pdf, o arquivo da tabela (com os "totais" no fim, se houver)."""
    fmt = request.args.get("formato")
    if fmt in ("xlsx", "pdf"):
        t = dados["tabela"]
        cols = [c for c in t["colunas"] if c not in ("IDMOV", "IDLAN")]
        idx = [t["colunas"].index(c) for c in cols]
        linhas = [[r[i] for i in idx] for r in t["linhas"]]
        usuarios.registrar(g.usuario["login"], f"exportou {fmt}", titulo)
        totais = dados.get("totais")
        if totais:
            conteudo = (exportar.excel(titulo, subtitulo, cols, linhas, totais) if fmt == "xlsx"
                        else exportar.pdf(titulo, subtitulo, cols, linhas, totais))
            return _arquivo(nome, fmt, titulo, subtitulo, cols, linhas, conteudo)
        return _arquivo(nome, fmt, titulo, subtitulo, cols, linhas)
    return jsonify(dados)


def _arquivo(nome, fmt, titulo, subtitulo, cols, linhas, conteudo=None):
    if conteudo is None:
        conteudo = exportar.excel(titulo, subtitulo, cols, linhas) if fmt == "xlsx" else exportar.pdf(titulo, subtitulo, cols, linhas)
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "application/pdf"
    arq = f"{nome}_{dt.date.today():%Y%m%d}.{fmt}"
    disp = "attachment" if fmt == "xlsx" or request.args.get("baixar") else "inline"
    return Response(conteudo, mimetype=mime, headers={"Content-Disposition": f'{disp}; filename="{arq}"'})


def _sub_filtros():
    partes = []
    a = request.args
    rot = {"ini": "De", "fim": "Até", "tipos": "Tipos", "prefixo": "Tipo inicia com", "vendedor": "Vendedor",
           "cliente": "Cliente", "status": "Status", "local": "Local", "grupo": "Grupo", "busca": "Busca",
           "tipo": "Tipo", "base": "Data base", "uf": "UF", "alerta": "Alerta", "tipodoc": "Tipo de documento",
           "filial": "Filial", "situacao": "Situação",
           "ccusto": "Centro de custo", "depto": "Departamento", "maquina": "Máquina"}
    for k, nome in rot.items():
        v = a.get(k)
        if v:
            if k in ("ini", "fim") and len(v) == 10:
                v = f"{v[8:10]}/{v[5:7]}/{v[:4]}"
            partes.append(f"{nome}: {v}")
    if a.get("cancelados") == "so":
        partes.append("Apenas cancelados")
    elif a.get("cancelados") == "1":
        partes.append("Incluindo cancelados")
    return " · ".join(partes)


@app.route("/saude")
def saude():
    """Usado pelo supervisor (servico.py) para saber se o painel está respondendo. Não consulta o banco."""
    r = Response("ok", mimetype="text/plain")
    r.headers["Cache-Control"] = "no-store"
    return r


def _enderecos():
    """Endereços pelos quais os aparelhos podem acessar este servidor (para mostrar em Administração)."""
    import socket
    import certificado
    esq, porta = ("https" if CFG["https"] else "http"), CFG["servidor_porta"]
    nomes = []
    if CFG["nome_local"]:
        nomes.append(CFG["nome_local"] + ".local")
    nomes += [n for n in CFG["nomes"]]
    try:
        nomes.append(socket.gethostname())
    except OSError:
        pass
    nomes += [str(ip) for ip in sorted(certificado.ips_locais(), key=str) if not ip.is_loopback]
    vistos, saida = set(), []
    for n in nomes:
        if n.lower() not in vistos:
            vistos.add(n.lower())
            saida.append(f"{esq}://{n}:{porta}")
    return saida


@app.errorhandler(db.ErroBanco)
def erro_banco(e):
    if SITE:
        return jsonify(erro=str(e)), 500
    return jsonify(erro=f"Erro no banco de dados: {e}"), 500


@app.route("/api/status")
@exige()
def api_status():
    try:
        # no Render o HTTPS é feito pelo próprio Render (o painel recebe a conexão já decifrada)
        seg = {"https": request.is_secure if SITE else CFG["https"], "ip_restrito": bool(CFG["permitir"]), "site": bool(SITE)}
        if g.usuario.get("admin") and not SITE:
            import mdns
            seg["enderecos"] = _enderecos()
            seg["nome_local"] = mdns.estado.get("nome") or ""
            seg["nome_local_ativo"] = bool(mdns.estado.get("ativo"))
            seg["nome_local_erro"] = mdns.estado.get("erro") or ""
            if CFG["https"]:
                import certificado
                seg["certificado_sha256"] = certificado.impressao_digital()
                seg["certificado_nomes"] = certificado.nomes_do_certificado()
        return jsonify(ok=True, banco=banco().testar(), modo=C()["modo"], seguranca=seg,
                       empresa=C()["nome_empresa"], bancos=_lista_bancos(_bancos_usuario(g.usuario)))
    except db.ErroBanco as e:
        return jsonify(ok=False, erro=str(e)), 500


_cache = {}


def _em_cache(chave, segundos, fn):
    """Cache curto para telas pesadas acessadas por vários usuários ao mesmo tempo."""
    agora = time.time()
    chave = f"{_bid()}:{chave}"
    if chave in _cache and agora - _cache[chave][0] < segundos:
        return _cache[chave][1]
    valor = fn()
    if len(_cache) > 300:                     # limpa entradas antigas (períodos diferentes geram chaves novas)
        for k in [k for k, (t, _) in list(_cache.items()) if agora - t > 900]:
            _cache.pop(k, None)
    _cache[chave] = (agora, valor)
    return valor


@app.route("/api/opcoes")
@exige()
def api_opcoes():
    d = dict(_em_cache("opcoes", 300, lambda: servicos.opcoes(banco(), C())))
    if _tipos():
        d["tipos"] = [t for t in d["tipos"] if servicos.tipo_permitido(_tipos(), t["cod"])]
    return jsonify(d)


@app.route("/api/inicio")
@exige("inicio")
def api_inicio():
    parte = request.args.get("parte") if request.args.get("parte") in ("resumo", "graficos") else None
    a = {"ini": request.args.get("ini", "")[:10], "fim": request.args.get("fim", "")[:10],
         "filial": request.args.get("filial", "")[:6]}
    chave = f"inicio:{parte}:{a['ini']}:{a['fim']}:{a['filial']}:" + ",".join(_tipos())
    if request.args.get("atualizar"):
        _cache.pop(f"{_bid()}:{chave}", None)
    return jsonify(_em_cache(chave, 120, lambda: servicos.inicio(banco(), C(), _tipos(), parte, a)))


@app.route("/api/movimentos")
@exige("movimentos")
def api_movimentos():
    d = servicos.movimentos(banco(), C(), _args(), CFG["limite_linhas"])
    return _resposta("movimentos", "Movimentos", d, _sub_filtros())


@app.route("/api/movimentos/<int:idmov>")
@exige("movimentos")
def api_movimento_itens(idmov):
    return jsonify(servicos.itens_movimento(banco(), C(), idmov, _tipos()))


@app.route("/api/movimentacoes")
@exige("movimentacoes")
def api_movimentacoes():
    a = _args()
    chave = "movimentacoes:" + ":".join(f"{k}={a.get(k, '')}" for k in ("aba", "ini", "fim", "filial", "grupo", "busca", "inativos", "com_mov")) + ":" + ",".join(_tipos())
    if request.args.get("atualizar"):
        _cache.pop(f"{_bid()}:{chave}", None)
    d = _em_cache(chave, 120, lambda: servicos.movimentacoes(banco(), C(), a, CFG["limite_linhas"]))
    tit = "Movimentações que mexem no estoque" if d["aba"] == "estoque" else "Movimentações que não mexem no estoque"
    return _resposta("movimentacoes", tit, d, _sub_filtros())


@app.route("/api/movimentacoes/produto")
@exige("movimentacoes")
def api_movimentacoes_produto():
    cod = request.args.get("codprd", "")[:30]
    d = servicos.movimentacoes_produto(banco(), C(), cod, _args(), CFG["limite_linhas"])
    p = d["produto"]
    tit = ("Movimentos que mexem no estoque" if d["aba"] == "estoque" else "Movimentos que não mexem no estoque") + \
        f" - {p['fabricante'] or p['codprd']} {p['nome']}"
    return _resposta("movimentacoes_produto", tit, d, _sub_filtros())


@app.route("/api/estoque")
@exige("estoque")
def api_estoque():
    d = servicos.estoque(banco(), C(), _args(), CFG["limite_linhas"])
    return _resposta("estoque", "Saldo de estoque", d, _sub_filtros())


@app.route("/api/financeiro")
@exige("financeiro")
def api_financeiro():
    d = servicos.financeiro(banco(), C(), _args(), CFG["limite_linhas"])
    tit = {"R": "Contas a receber", "P": "Contas a pagar"}.get(request.args.get("tipo", "R"), "Contas a pagar e receber")
    return _resposta("financeiro", tit, d, _sub_filtros())


@app.route("/api/clientes")
@exige("cadastros")
def api_clientes():
    d = servicos.clientes(banco(), C(), _args(), CFG["limite_linhas"])
    return _resposta("clientes", "Clientes e fornecedores", d, _sub_filtros())


def _frota():
    """Movimentos do Frotas desta empresa: {codtmv: "abastecimento"|"manutencao"}, ou {} se ainda não escolhidos.
    Empresa que já usa o padrão antigo (1.2.40 / 1.2.39 com máquina) começa com ele, sem precisar escolher."""
    bid = _bid()
    t = usuarios.config_empresa(bid, "frota_tipos")
    if t is None:
        t = dict(servicos.FROTA_PADRAO) if servicos.frota_padrao_em_uso(banco(), C()) else {}
        if t:
            usuarios.gravar_config_empresa(bid, "frota_tipos", t, "automático (padrão antigo)")
    return t or {}


def _sem_config_frota():
    return jsonify(configurar=True, pode_configurar=bool(g.usuario.get("admin")),
                   erro="Os movimentos do Frotas ainda não foram escolhidos para esta empresa."), 409


@app.route("/api/frotas/tipos", methods=["GET", "POST"])
@exige("frotas")
def api_frota_tipos():
    if request.method == "POST":
        if not g.usuario.get("admin"):
            return jsonify(erro="Só o administrador da empresa escolhe os movimentos do Frotas."), 403
        d = request.get_json(silent=True) or {}
        validos = {t["cod"] for t in servicos.frota_tipos_disponiveis(banco(), C())}
        escolha = {}
        for cod, cat in (d.get("tipos") or {}).items():
            cod = str(cod).strip()[:20]
            if cat in servicos.ROTULO_FROTA and cod in validos:
                escolha[cod] = cat
        if not escolha:
            return jsonify(erro="Marque pelo menos um movimento."), 400
        usuarios.gravar_config_empresa(_bid(), "frota_tipos", escolha, g.usuario["login"])
        usuarios.registrar(g.usuario["login"], "movimentos do Frotas", ", ".join(f"{c}={v}" for c, v in sorted(escolha.items())))
        for k in [k for k in _cache if k.startswith(f"{_bid()}:frotas:")]:
            _cache.pop(k, None)
        return jsonify(ok=True, tipos=escolha)
    return jsonify(tipos=servicos.frota_tipos_disponiveis(banco(), C()), escolha=_frota(),
                   pode_configurar=bool(g.usuario.get("admin")))


@app.route("/api/frotas")
@exige("frotas")
def api_frotas():
    a = _args()
    a["_frota"] = _frota()
    if not a["_frota"]:
        return _sem_config_frota()
    chave = "frotas:" + ":".join(f"{k}={a.get(k, '')}" for k in ("ini", "fim", "maquina", "grupo", "filial", "busca", "ver")) + ":" + ",".join(_tipos()) \
        + ":" + ",".join(f"{c}={v}" for c, v in sorted(a["_frota"].items()))
    d = _em_cache(chave, 120, lambda: servicos.frotas(banco(), C(), a, CFG["limite_linhas"]))
    tit = "Frotas - lançamentos de abastecimento e manutenção" if a.get("ver") == "lancamentos" else "Frotas - gasto por máquina"
    return _resposta("frotas", tit, d, _sub_filtros())


@app.route("/api/frotas/maquina")
@exige("frotas")
def api_frota_maquina():
    cod = request.args.get("codigo", "")[:10]
    a = _args()
    a["_frota"] = _frota()
    if not a["_frota"]:
        return _sem_config_frota()
    d = servicos.frota_maquina(banco(), C(), cod, a, CFG["limite_linhas"])
    m = d["maquina"]
    tit = f"Frotas - {m.get('placa') or m.get('codigo') or cod} {m.get('nome') or ''}".strip()
    return _resposta("frota_maquina", tit, d, _sub_filtros())


@app.route("/api/maquinas")
@exige("cadastros")
def api_maquinas():
    d = servicos.maquinas(banco(), C(), _args(), CFG["limite_linhas"])
    return _resposta("maquinas", "Máquinas e veículos", d, _sub_filtros())


@app.route("/api/produtos")
@exige("cadastros")
def api_produtos():
    d = servicos.produtos(banco(), C(), _args(), CFG["limite_linhas"])
    return _resposta("produtos", "Produtos - cadastro e tributação", d, _sub_filtros())


# ------------------------------------------------------------------ relatórios prontos
RELATORIOS = {
    "documentos": {"titulo": "Movimentos documento por documento (com materiais)", "modulo": "movimentos"},
    "titulos": {"titulo": "Títulos financeiros", "modulo": "financeiro"},
    "estoque": {"titulo": "Saldo de estoque por local", "modulo": "estoque"},
    "produtos": {"titulo": "Produtos - cadastro e tributação", "modulo": "cadastros"},
    "clientes": {"titulo": "Clientes e fornecedores", "modulo": "cadastros"},
}


@app.route("/api/relatorio/<nome>")
@exige("relatorios")
def api_relatorio(nome):
    rel = RELATORIOS.get(nome)
    if not rel:
        abort(404)
    if rel["modulo"] not in g.usuario["modulos"] or not _rel_ok("pronto:" + nome):
        return jsonify(erro="Você não tem permissão para os dados deste relatório."), 403
    fmt = request.args.get("formato", "pdf")
    limite = max(CFG["limite_linhas"], 20000)
    a = _args()
    sub = _sub_filtros()
    usuarios.registrar(g.usuario["login"], f"relatório {nome} ({fmt})", sub)
    if nome == "documentos":
        ini, fim, df = servicos.movimentos_com_itens(banco(), C(), a, limite)
        sub = sub or f"Período {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
        if fmt == "pdf":
            return _arquivo(nome, "pdf", rel["titulo"], sub, None, None, exportar.pdf_documentos(rel["titulo"], sub, df))
        df = df.drop(columns=["IDMOV", "CODPRD_INT"], errors="ignore")
        return _arquivo(nome, "xlsx", rel["titulo"], sub, list(df.columns), df.astype(object).where(df.notna(), None).values.tolist())
    fn = {"titulos": servicos.financeiro, "estoque": servicos.estoque, "produtos": servicos.produtos,
          "clientes": servicos.clientes}[nome]
    t = fn(banco(), C(), a, limite)["tabela"]
    cols = [c for c in t["colunas"] if c not in ("IDLAN",)]
    idx = [t["colunas"].index(c) for c in cols]
    return _arquivo(nome, fmt, rel["titulo"], sub, cols, [[r[i] for i in idx] for r in t["linhas"]])


# ------------------------------------------------------------------ ficha do cliente/fornecedor
@app.route("/api/cadastro/<path:codcfo>")
@exige("cadastros")
def api_ficha(codcfo):
    """Cadastro + abas permitidas. ?aba=financeiro|movimentos traz os dados (e ?formato=xlsx|pdf o arquivo)."""
    u = g.usuario
    cad = servicos.ficha_cadastro(banco(), C(), codcfo)
    if not cad["linhas"]:
        abort(404)
    abas = [a for a in ("financeiro", "movimentos") if a in u["modulos"]]
    aba = request.args.get("aba")
    if not aba:
        return jsonify(cadastro=cad, abas=abas)
    if aba not in abas:
        return jsonify(erro="Você não tem permissão para esta aba."), 403
    limite = max(CFG["limite_linhas"], 20000)
    nome = cad["linhas"][0][cad["colunas"].index("NOME")] or codcfo
    if aba == "financeiro":
        d = servicos.ficha_financeiro(banco(), C(), codcfo, limite)
        titulo = f"Financeiro - {codcfo} {nome}"
    else:
        d = servicos.ficha_movimentos(banco(), C(), codcfo, limite, _tipos())
        titulo = f"Movimentos - {codcfo} {nome}"
    usuarios.registrar(u["login"], f"ficha {aba}", codcfo)
    return _resposta("ficha", titulo, d, "Todos os registros")


# ------------------------------------------------------------------ SQL livre e consultas salvas
def _executar_sql(sql, limite=None, valores=None):
    """Executa um SELECT livre. Aceita parâmetros :NOME (valores vazios viram NULL)."""
    sql = db.validar_select(sql)
    valores = {k.upper(): (v if v not in ("", None) else None) for k, v in (valores or {}).items()}
    q, params = relatorios_rb.ligar(sql, valores)
    ini = time.perf_counter()
    cols, linhas, mais = _banco_vivo().consultar(q, params, limite or CFG["limite_linhas"])
    return {"colunas": cols, "linhas": linhas, "truncado": mais, "ms": int((time.perf_counter() - ini) * 1000),
            "parametros": relatorios_rb.nomes_parametros(sql)}


def _valores_args():
    return {k[2:]: v for k, v in request.args.items() if k.startswith("p_")}


def _pode_consulta(c):
    u = g.usuario
    if not c:
        return False
    if c["dono_id"] == u["id"] or u.get("admin"):
        return True
    return bool(c["compartilhada"]) and _rel_ok(f"sq:{c['id']}")


@app.route("/api/sql", methods=["POST"])
@exige("sql")
def api_sql():
    dados = request.get_json(silent=True) or {}
    sql = dados.get("sql", "")
    try:
        r = _executar_sql(sql, valores=dados.get("valores"))
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    usuarios.registrar(g.usuario["login"], "sql", sql)
    return jsonify(r)


@app.route("/api/sql/exportar", methods=["POST"])
@exige("sql")
def api_sql_exportar():
    dados = request.get_json(silent=True) or {}
    fmt = dados.get("formato", "xlsx")
    try:
        r = _executar_sql(dados.get("sql", ""), max(CFG["limite_linhas"], 50000), dados.get("valores"))
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    titulo = dados.get("titulo") or "Consulta SQL"
    return _arquivo("consulta", fmt, titulo, f"Gerado por {g.usuario['nome']}", r["colunas"], r["linhas"])


# ------------------------------------------------------------------ assistente (chat com perguntas programadas)
@app.route("/api/chat/inicio")
@exige("chat")
def api_chat_inicio():
    return jsonify(sugestoes=assistente.exemplos(g.usuario["modulos"], 6), topicos=assistente.topicos(g.usuario["modulos"]))


@app.route("/api/chat", methods=["POST"])
@exige("chat")
def api_chat():
    pergunta = str((request.get_json(silent=True) or {}).get("pergunta") or "")[:500]
    ctx = {"banco": banco(), "cfg": C(), "bid": _bid(), "uid": g.usuario["id"], "modulos": g.usuario["modulos"],
           "tipos": _tipos(), "limite": CFG["limite_linhas"]}
    usuarios.registrar(g.usuario["login"], "assistente", pergunta)
    try:
        r = assistente.responder(pergunta, ctx)
    except db.ErroBanco as e:
        return jsonify(erro=f"Erro no banco de dados: {e}"), 500
    return jsonify(r)


@app.route("/api/chat/arquivo/<tid>")
@exige("chat")
def api_chat_arquivo(tid):
    t = assistente.obter_tabela(tid, g.usuario["id"])
    if not t:
        return jsonify(erro="Essa tabela expirou. Faça a pergunta de novo."), 404
    fmt = "xlsx" if request.args.get("formato") == "xlsx" else "pdf"
    usuarios.registrar(g.usuario["login"], f"assistente {fmt}", t["titulo"])
    sub = " · ".join(x for x in (t["subtitulo"], f"Gerado por {g.usuario['nome']}") if x)
    nome = "".join(ch if ch.isalnum() else "_" for ch in assistente.norm(t["titulo"])).strip("_")[:50] or "assistente"
    return _arquivo(nome, fmt, t["titulo"], sub, t["colunas"], t["linhas"])


@app.route("/api/esquema")
@exige("sql")
def api_esquema():
    tabela = request.args.get("tabela")
    if tabela:
        if C()["modo"] == "demo":
            cols, linhas, _ = banco().consultar(f"SELECT name AS CAMPO, type AS TIPO FROM pragma_table_info('{tabela.replace(chr(39), '')}')")
        else:
            cols, linhas, _ = banco().consultar("""
                SELECT TRIM(RF.RDB$FIELD_NAME) AS CAMPO, F.RDB$FIELD_TYPE AS T, F.RDB$FIELD_LENGTH AS L
                FROM RDB$RELATION_FIELDS RF JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME = RF.RDB$FIELD_SOURCE
                WHERE RF.RDB$RELATION_NAME = ? ORDER BY RF.RDB$FIELD_POSITION""", (tabela.upper(),))
            tipos = {7: "SMALLINT", 8: "INTEGER", 10: "FLOAT", 12: "DATE", 13: "TIME", 14: "CHAR", 16: "BIGINT/NUMERIC",
                     27: "DOUBLE", 35: "TIMESTAMP", 37: "VARCHAR", 261: "BLOB", 23: "BOOLEAN", 26: "INT128"}
            linhas = [[c, tipos.get(t, str(t)) + (f"({l})" if t in (14, 37) else "")] for c, t, l in linhas]
        return jsonify(campos=[{"campo": c, "tipo": t} for c, t in linhas])
    if C()["modo"] == "demo":
        _, linhas, _ = banco().consultar("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
    else:
        _, linhas, _ = banco().consultar(
            "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 ORDER BY 1")
    return jsonify(tabelas=[r[0] for r in linhas])


@app.route("/api/consultas", methods=["GET", "POST"])
@exige()
def api_consultas():
    u = g.usuario
    if request.method == "GET" and "relatorios" in u["modulos"] and "sql" not in u["modulos"]:
        return jsonify(consultas=[c for c in usuarios.consultas_visiveis(u["id"], u.get("admin")) if _pode_consulta(c)])
    if "sql" not in u["modulos"]:
        return jsonify(erro="Você não tem permissão para este módulo."), 403
    if request.method == "POST":
        dados = request.get_json(silent=True) or {}
        try:
            cid = usuarios.salvar_consulta(u["id"], dados, dados.get("id"), u.get("admin"))
        except ValueError as e:
            return jsonify(erro=str(e)), 400
        return jsonify(id=cid)
    return jsonify(consultas=usuarios.consultas_visiveis(u["id"], u.get("admin")))


@app.route("/api/consultas/<int:cid>/excluir", methods=["POST"])
@exige("sql")
def api_consulta_excluir(cid):
    try:
        usuarios.excluir_consulta(g.usuario["id"], cid, g.usuario.get("admin"))
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    return jsonify(ok=True)


def _layout_consulta(c):
    lay = usuarios.obter_layout(f"sq:{c['id']}")
    if lay is None and c.get("grafico"):
        g0 = json.loads(c["grafico"]) or {}
        if g0.get("x"):
            lay = {"visoes": {"Resultado": {"grafico": {"tipo": g0.get("tipo") or "barras", "x": g0["x"], "y": g0.get("y") or "",
                                                        "agregacao": "soma" if g0.get("y") else "contagem"}}}}
    return lay


def _visao_consulta(r):
    return {"nome": "Resultado", "colunas": r["colunas"], "linhas": r["linhas"], "truncado": r["truncado"],
            "aviso": "Limite de linhas atingido; refine os filtros para ver tudo." if r["truncado"] else None, "erro": None}


@app.route("/api/consultas/<int:cid>/arquivo")
@exige("relatorios")
def api_consulta_arquivo(cid):
    c = usuarios.consulta(cid)
    if not _pode_consulta(c):
        abort(404)
    try:
        r = _executar_sql(c["sql"], max(CFG["limite_linhas"], 50000), _valores_args())
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    fmt = request.args.get("formato", "xlsx")
    usuarios.registrar(g.usuario["login"], f"consulta salva {fmt}", c["nome"])
    lay = _layout_consulta(c)
    visoes = layout.aplicar_todas([_visao_consulta(r)], lay)
    conteudo = exportar.com_layout(c["nome"], c.get("descricao") or "", visoes, fmt, ((lay or {}).get("pdf") or {}).get("orientacao", "auto"))
    return _arquivo("consulta", fmt, c["nome"], "", None, None, conteudo)


@app.route("/api/consultas/<int:cid>/dados")
@exige("relatorios")
def api_consulta_dados(cid):
    c = usuarios.consulta(cid)
    if not _pode_consulta(c):
        abort(404)
    try:
        r = _executar_sql(c["sql"], valores=_valores_args())
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    lay = _layout_consulta(c)
    return jsonify(nome=c["nome"], ms=r["ms"], visoes=layout.aplicar_todas([_visao_consulta(r)], lay),
                   layout=lay or {}, pode_editar=_pode_editar_layout())


# ------------------------------------------------------------------ layout dos relatórios (vale para todos os usuários)
def _pode_editar_layout():
    u = g.usuario
    return bool(u.get("admin") or "sql" in u["modulos"])


def _checar_chave(chave):
    tipo, _, ident = chave.partition(":")
    if tipo == "rb" and _rb_permitido(relatorios_rb.obter(ident)):
        return
    if tipo == "sq" and ident.isdigit() and _pode_consulta(usuarios.consulta(int(ident))):
        return
    abort(404)


@app.route("/api/layout/<path:chave>", methods=["GET", "POST"])
@exige("relatorios")
def api_layout(chave):
    _checar_chave(chave)
    if request.method == "POST":
        if not _pode_editar_layout():
            abort(403)
        try:
            lay = layout.validar(request.get_json(silent=True) or {})
        except ValueError as e:
            return jsonify(erro=str(e)), 400
        usuarios.salvar_layout(_chave_layout(chave), lay, g.usuario["login"])
        usuarios.registrar(g.usuario["login"], "layout salvo", _chave_layout(chave))
        return jsonify(ok=True)
    lay = usuarios.obter_layout(_chave_layout(chave))
    if lay is None and chave.startswith("rb:"):
        lay = relatorios_rb.obter(chave[3:]).get("layout_padrao")
    return jsonify(layout=lay or {}, pode_editar=_pode_editar_layout())


@app.route("/api/layout/<path:chave>/excluir", methods=["POST"])
@exige("relatorios")
def api_layout_excluir(chave):
    _checar_chave(chave)
    if not _pode_editar_layout():
        abort(403)
    usuarios.excluir_layout(_chave_layout(chave))
    usuarios.registrar(g.usuario["login"], "layout restaurado", _chave_layout(chave))
    return jsonify(ok=True)


# ------------------------------------------------------------------ relatórios importados do ReportBuilder
def _chave_rb(rid, bid=None):
    """Chave de um relatório do ReportBuilder (permissões e layout). Os ids do RB se repetem entre bancos
    diferentes, então nos bancos que não são o principal a chave leva o banco na frente: 'poligonal|rb:12-3'."""
    bid = bid or _bid()
    return f"rb:{rid}" if bid == bancos.PRINCIPAL else f"{bid}|rb:{rid}"


def _chave_layout(chave):
    return _chave_rb(chave[3:]) if chave.startswith("rb:") else chave


def _rb_permitido(r):
    return bool(r) and r["modulo"] in g.usuario["modulos"] and _rel_ok(_chave_rb(r["id"]), r["pasta"])


@app.route("/api/rb")
@exige("relatorios")
def api_rb_lista():
    teste = usuarios.teste_rb(_bid())
    desenhos_rb = {k for k, v in rb_sync.desenhos(_bid()).items() if v}
    pref = _chave_rb("")
    salvos = {k[len("desenho|" + pref):] for k in usuarios.chaves_layout("desenho|" + pref)}
    lista = []
    for r in relatorios_rb.todos():
        if not _rb_permitido(r):
            continue
        x = relatorios_rb.resumo(r)
        x["impressao"] = r["id"] in desenhos_rb or (r["id"] in salvos) or bool(r.get("desenho"))
        t = teste.get("resultados", {}).get(r["id"])
        if t is not None:
            x["erro"] = "; ".join(t) if t else None
        lista.append(x)
    prontos = [k for k, v in RELATORIOS.items() if v["modulo"] in g.usuario["modulos"] and _rel_ok("pronto:" + k)]
    return jsonify(relatorios=lista, teste={k: v for k, v in teste.items() if k != "resultados"},
                   pode_sql="sql" in g.usuario["modulos"], prontos=prontos)


def _rb_valores(r=None):
    dados = request.get_json(silent=True) or {}
    valores = {k.upper(): v for k, v in (dados.get("valores") or {}).items()}
    perm = _tipos()
    if perm and r:
        # filtros de tipo de movimento ficam limitados aos tipos liberados para o usuário
        tipos = _em_cache("opcoes", 300, lambda: servicos.opcoes(banco(), C()))["tipos"]
        liberados = [t["cod"] for t in tipos if servicos.tipo_permitido(perm, t["cod"])]
        for nome in relatorios_rb.params_tipo_movimento(r):
            pedidos = [x.strip() for x in str(valores.get(nome) or "").split(",") if x.strip()]
            ok = [x for x in pedidos if servicos.tipo_permitido(perm, x)] if pedidos else liberados
            valores[nome] = ",".join(ok) or "__NENHUM__"
    return valores, dados


def _rb_filtrar_tipos(res):
    """Remove linhas de tipos de movimento não liberados quando a visão traz a coluna CODTMV."""
    perm = _tipos()
    if not perm:
        return res
    for v in res:
        cols = [c.upper() for c in v.get("colunas") or []]
        if "CODTMV" in cols:
            i = cols.index("CODTMV")
            antes = len(v["linhas"])
            v["linhas"] = [r for r in v["linhas"] if servicos.tipo_permitido(perm, r[i])]
            if len(v["linhas"]) < antes:
                v["aviso"] = ((v.get("aviso") or "") + " Mostrando só os tipos de movimento liberados para você.").strip()
    return res


def _layout_rb(r):
    """Layout salvo pelos usuários ou, se não houver, o layout padrão que vem com o relatório."""
    return usuarios.obter_layout(_chave_rb(r["id"])) or r.get("layout_padrao")


def _ocultas(lay):
    return {n for n, c in ((lay or {}).get("visoes") or {}).items() if (c or {}).get("oculta")}


@app.route("/api/rb/<rid>/executar", methods=["POST"])
@exige("relatorios")
def api_rb_executar(rid):
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    valores, _ = _rb_valores(r)
    lay = _layout_rb(r)
    try:
        res = _rb_filtrar_tipos(relatorios_rb.executar(banco(), r, valores, CFG["limite_linhas"], _ocultas(lay)))
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    usuarios.registrar(g.usuario["login"], "relatório RB", r["nome"])
    return jsonify(visoes=layout.aplicar_todas(res, lay), layout=lay or {}, pode_editar=_pode_editar_layout())


# ------------------------------------------------------------------ layout de impressão (estilo ReportBuilder)
import desenho as desenho_mod


def _chave_desenho(r):
    return "desenho|" + _chave_rb(r["id"])


def _desenho_original(r):
    if r.get("desenho"):                 # relatórios padrão do painel trazem o próprio layout de impressão
        return r["desenho"]
    return rb_sync.desenhos(_bid()).get(r["id"]) or None


def _layout_salvo(r):
    """Layout salvo no painel, com os cálculos vazios completados pelo original do ReportBuilder."""
    salvo = usuarios.obter_layout(_chave_desenho(r))
    return desenho_mod.completar_codigos(salvo, _desenho_original(r)) if salvo else None


def _desenho_efetivo(r):
    """Layout de impressão salvo no painel ou, se não houver, o original do ReportBuilder."""
    return _layout_salvo(r) or _desenho_original(r)


def _com_tabelas(r, d):
    """Relatório com as tabelas do banco que o layout de impressão acrescentou (viram visões extras)."""
    extras = desenho_mod.visoes_tabelas(d)
    nomes = {v["nome"].upper() for v in r["visoes"]}
    extras = [v for v in extras if v["nome"].upper() not in nomes]
    return dict(r, visoes=list(r["visoes"]) + extras) if extras else r


def _pdf_desenho(r, d, valores):
    r = _com_tabelas(r, d)
    res = _rb_filtrar_tipos(relatorios_rb.executar(banco(), r, valores, max(CFG["limite_linhas"], 50000)))
    erros = [f"{v['nome']}: {v['erro']}" for v in res if v.get("erro")]
    if erros and all(v.get("erro") for v in res):
        raise db.ErroBanco("; ".join(erros)[:500])
    pdf, avisos = desenho_mod.gerar_pdf(d, res, r["nome"], valores,
                                        [{"nome": v["nome"], "mestre": v.get("mestre"), "ligacoes": v.get("ligacoes")}
                                         for v in r["visoes"]])
    return pdf, avisos + erros


@app.route("/api/rb/<rid>/desenho/abrir", methods=["POST"])
@exige("relatorios")
def api_desenho_abrir(rid):
    """Abre o editor: desenho (salvo, original do RB ou padrão) + campos de cada visão."""
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    valores, _ = _rb_valores(r)
    base = (request.get_json(silent=True) or {}).get("base")
    salvo = None if base in ("original", "padrao") else _layout_salvo(r)
    original = None if base == "padrao" else _desenho_original(r)
    rt = _com_tabelas(r, salvo or original or {})        # tabelas do banco acrescentadas no editor
    campos, numeros = {}, {}
    try:
        res = relatorios_rb.executar(banco(), rt, valores, 30)
    except db.ErroBanco:
        res = []
    import decimal
    for v in rt["visoes"]:
        x = next((y for y in res if y["nome"] == v["nome"]), None)
        cols = (x or {}).get("colunas") or list(relatorios_rb._itens_select(v["sql"]))
        campos[v["nome"]] = [c.upper() for c in cols]
        nums = set()
        for i, c in enumerate(cols):
            vals = [l[i] for l in (x or {}).get("linhas", [])[:30] if l[i] is not None]
            if vals and all(isinstance(z, (float, decimal.Decimal)) for z in vals):
                nums.add(c.upper())
        numeros[v["nome"]] = nums
    if salvo:
        d, origem = salvo, "salvo"
    elif original:
        d, origem = original, "reportbuilder"
    else:
        d, origem = desenho_mod.padrao(r, campos, numeros), "padrao"
    return jsonify(desenho=d, origem=origem, tem_original=bool(_desenho_original(r)), campos=campos,
                   tem_salvo=bool(usuarios.obter_layout(_chave_desenho(r))),
                   numeros={k: sorted(v) for k, v in numeros.items()},
                   visoes=[{"nome": v["nome"], "mestre": v.get("mestre"), "tabela": v.get("tabela")} for v in rt["visoes"]],
                   pode_editar=_pode_editar_layout(), pode_tabelas=_pode_editar_layout(), nome=r["nome"])


@app.route("/api/rb/<rid>/desenho", methods=["POST"])
@exige("relatorios")
def api_desenho_salvar(rid):
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    if not _pode_editar_layout():
        abort(403)
    try:
        d = desenho_mod.validar((request.get_json(silent=True) or {}).get("desenho"))
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    d["origem"] = "salvo"
    usuarios.salvar_layout(_chave_desenho(r), d, g.usuario["login"])
    usuarios.registrar(g.usuario["login"], "layout de impressão salvo", r["nome"])
    return jsonify(ok=True)


@app.route("/api/rb/<rid>/desenho/excluir", methods=["POST"])
@exige("relatorios")
def api_desenho_excluir(rid):
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    if not _pode_editar_layout():
        abort(403)
    usuarios.excluir_layout(_chave_desenho(r))
    usuarios.registrar(g.usuario["login"], "layout de impressão restaurado", r["nome"])
    return jsonify(ok=True, tem_original=bool(_desenho_original(r)))


def _modelo_rb(r):
    """Modelo original do ReportBuilder (RB_ITEM.TEMPLATE) do relatório, ou None (relatórios padrão do painel)."""
    if r.get("desenho"):
        return None
    m = re.match(r"^(\d+)-(\d+|x)$", str(r["id"]))
    if not m:
        return None
    iid = int(m.group(1))
    if m.group(2) == "x":
        sql, par = ("SELECT TEMPLATE FROM RB_ITEM WHERE ITEM_ID = ? AND FOLDER_ID < 0 "
                    "AND (DELETED IS NULL OR DELETED = 0) ORDER BY MODIFIED DESC"), (iid,)
    else:
        sql, par = ("SELECT TEMPLATE FROM RB_ITEM WHERE ITEM_ID = ? AND FOLDER_ID = ? "
                    "AND (DELETED IS NULL OR DELETED = 0) ORDER BY MODIFIED DESC"), (iid, int(m.group(2)))
    _, t, _ = banco().consultar_blob(sql, par)
    return t[0][0] if t and t[0][0] else None


@app.route("/api/rb/<rid>/desenho/rtm", methods=["POST"])
@exige("relatorios")
def api_desenho_rtm(rid):
    """Baixa o layout (o enviado pela tela ou o efetivo) como arquivo .rtm do ReportBuilder.
    Parte do modelo original do ERP (consultas, parâmetros e configurações ficam) e troca só o layout."""
    import rtm
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    if not _pode_editar_layout():
        abort(403)
    d = (request.get_json(silent=True) or {}).get("desenho") or _desenho_efetivo(r)
    if not d:
        return jsonify(erro="Este relatório não tem layout de impressão."), 400
    try:
        original = _modelo_rb(r)
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    try:
        conteudo = rtm.exportar(d, original)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    usuarios.registrar(g.usuario["login"], "layout exportado (.rtm)", r["nome"])
    import unicodedata
    arq = unicodedata.normalize("NFKD", r["nome"]).encode("ascii", "ignore").decode()
    arq = re.sub(r'[\\/:*?"<>|;]+', "_", arq).strip(" ._") or "relatorio"
    return Response(conteudo, mimetype="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{arq}.rtm"',
        "X-Content-Type-Options": "nosniff",
        "X-Rtm-Modelo": "original" if original else "layout"})


@app.route("/api/rb/<rid>/desenho/rtm/importar", methods=["POST"])
@exige("relatorios")
def api_desenho_rtm_importar(rid):
    """Lê um arquivo .rtm enviado (corpo da requisição) e devolve o desenho para o editor (não salva)."""
    import rtm
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    if not _pode_editar_layout():
        abort(403)
    arq = request.files.get("arquivo")
    conteudo = arq.read() if arq else request.get_data()
    if not conteudo:
        return jsonify(erro="Nenhum arquivo enviado."), 400
    try:
        d, pipes = rtm.importar(conteudo)
        d = desenho_mod.validar(d)
    except Exception as e:  # noqa: BLE001 - arquivo de outro formato / corrompido
        return jsonify(erro=str(e) if isinstance(e, ValueError) else "Não foi possível ler este arquivo .rtm."), 400
    atual = _desenho_efetivo(r) or {}
    if not d["relatorio"].get("visao") and atual.get("relatorio", {}).get("visao"):
        d["relatorio"]["visao"] = atual["relatorio"]["visao"]
    if not d.get("aliases") and atual.get("aliases"):
        d["aliases"] = atual["aliases"]
    if atual.get("tabelas") and not d.get("tabelas"):
        d["tabelas"] = atual["tabelas"]
    nomes = {v["nome"].upper() for v in _com_tabelas(r, d)["visoes"]}
    faltam = sorted(x for x in rtm.visoes_usadas(d) if x.upper() not in nomes)
    usuarios.registrar(g.usuario["login"], "layout importado (.rtm)", r["nome"])
    return jsonify(desenho=d, faltam=faltam)


@app.route("/api/rb/<rid>/desenho/pdf", methods=["POST"])
@exige("relatorios")
def api_desenho_pdf(rid):
    """PDF com o desenho enviado (pré-visualização no editor, sem salvar) ou com o efetivo."""
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    valores, dados = _rb_valores(r)
    d = dados.get("desenho") or _desenho_efetivo(r)
    if not d:
        return jsonify(erro="Este relatório não tem layout de impressão."), 400
    try:
        d = desenho_mod.validar(d)
        if dados.get("desenho") and not _pode_editar_layout():
            # quem não edita layouts não escolhe tabelas do banco: valem só as do layout salvo
            d["tabelas"] = desenho_mod.validar(_desenho_efetivo(r) or {"relatorio": {}})["tabelas"]
        pdf, avisos = _pdf_desenho(r, d, valores)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    usuarios.registrar(g.usuario["login"], "relatório RB pdf (layout)", r["nome"])
    resp = _arquivo("relatorio", "pdf", r["nome"], "", None, None, pdf)
    if avisos:
        resp.headers["X-Avisos"] = str(len(avisos))
    return resp


@app.route("/api/rb/<rid>/arquivo", methods=["POST"])
@exige("relatorios")
def api_rb_arquivo(rid):
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    valores, dados = _rb_valores(r)
    fmt = dados.get("formato", "xlsx")
    if fmt == "pdf" and not dados.get("tabela"):
        d = _desenho_efetivo(r)
        if d:
            try:
                pdf, _ = _pdf_desenho(r, desenho_mod.validar(d), valores)
            except (ValueError, db.ErroBanco) as e:
                return jsonify(erro=str(e)), 400
            usuarios.registrar(g.usuario["login"], "relatório RB pdf (layout)", r["nome"])
            return _arquivo("relatorio", "pdf", r["nome"], "", None, None, pdf)
    lay = _layout_rb(r) or {}
    try:
        res = _rb_filtrar_tipos(relatorios_rb.executar(banco(), r, valores, max(CFG["limite_linhas"], 50000), _ocultas(lay)))
    except db.ErroBanco as e:
        return jsonify(erro=str(e)), 400
    usados = relatorios_rb.converter_valores(r, valores)
    sub = " · ".join(f"{p['rotulo']}: {usados[p['nome']]:%d/%m/%Y}" if hasattr(usados[p["nome"]], "strftime")
                     else f"{p['rotulo']}: {usados[p['nome']]}" for p in r["parametros"] if usados.get(p["nome"]) is not None)
    usuarios.registrar(g.usuario["login"], f"relatório RB {fmt}", r["nome"])
    conteudo = exportar.com_layout(r["nome"], sub or r["pasta"], layout.aplicar_todas(res, lay), fmt,
                                   (lay.get("pdf") or {}).get("orientacao", "auto"))
    return _arquivo("relatorio", fmt, r["nome"], sub, None, None, conteudo)


@app.route("/api/rb/<rid>/sql")
@exige("sql")
def api_rb_sql(rid):
    r = relatorios_rb.obter(rid)
    if not _rb_permitido(r):
        abort(404)
    return jsonify(visoes=[{"nome": v["nome"], "sql": v["sql"]} for v in r["visoes"]], parametros=r["parametros"])


@app.route("/api/rb/testar", methods=["POST"])
@exige(admin=True)
def api_rb_testar():
    import threading

    bid = _bid()
    if usuarios.teste_rb(bid).get("andamento"):
        return jsonify(ok=True)

    def rodar():
        res, inicio = {}, dt.datetime.now().isoformat(" ", "seconds")
        lista = relatorios_rb.todos(bid)
        for i, r in enumerate(lista, 1):
            res[r["id"]] = relatorios_rb.testar(banco(bid), r)
            if i % 10 == 0 or i == len(lista):
                usuarios.salvar_teste_rb({"andamento": i < len(lista), "feitos": i, "total": len(lista),
                                          "inicio": inicio, "resultados": res,
                                          "com_erro": sum(1 for e in res.values() if e)}, bid)

    usuarios.salvar_teste_rb({"andamento": True, "feitos": 0, "total": len(relatorios_rb.todos(bid)), "resultados": {}}, bid)
    threading.Thread(target=rodar, daemon=True).start()
    return jsonify(ok=True)

# ------------------------------------------------------------------ sincronização com o ReportBuilder
def _rb_mudou(bid=None):
    relatorios_rb.recarregar(bid)


# No site (Render), os arquivos do ReportBuilder de cada empresa (dados\bancos\<empresa>\rb_*.json) somem a cada
# reinício. Por isso cada gravação vai também para o banco do site, e ao iniciar o site eles são recriados de lá.
if SITE:
    import os as _os

    def _espelhar_rb(caminho, texto):
        try:
            rel = _os.path.relpath(caminho, config.DADOS_DIR).replace("\\", "/")
            if not rel.startswith(".."):
                usuarios.guardar_arquivo_site(rel, texto)
        except Exception:  # noqa: BLE001 - o arquivo local já foi gravado; o espelho é uma segurança a mais
            app.logger.exception("Não consegui guardar %s no banco do site", caminho)

    def _restaurar_rb():
        n = 0
        for rel, texto in usuarios.arquivos_site():
            destino = _os.path.normpath(_os.path.join(config.DADOS_DIR, rel))
            if not destino.startswith(_os.path.normpath(config.DADOS_DIR) + _os.sep) or _os.path.exists(destino):
                continue
            if rel.endswith("rb_sync.json"):      # uma leitura que estava em andamento parou com o reinício
                try:
                    st = json.loads(texto)
                    if st.get("andamento"):
                        st["andamento"] = False
                        texto = json.dumps(st, ensure_ascii=False)
                except ValueError:
                    pass
            _os.makedirs(_os.path.dirname(destino), exist_ok=True)
            with open(destino, "w", encoding="utf-8") as f:
                f.write(texto)
            n += 1
        if n:
            print(f"ReportBuilder: {n} arquivo(s) recuperado(s) do banco do site.", flush=True)

    try:
        _restaurar_rb()
    except Exception:  # noqa: BLE001
        app.logger.exception("Não consegui recuperar os arquivos do ReportBuilder do banco do site")
    rb_sync.espelho = _espelhar_rb

_RB_AUTO = {}             # empresa -> quando a leitura automática do ReportBuilder foi tentada


def _rb_auto(eid):
    """Site: se a empresa ainda não tem os relatórios do ReportBuilder lidos, lê assim que o agente conectar."""
    import os
    if not SITE or time.time() - _RB_AUTO.get(eid, 0) < 1800:
        return
    _RB_AUTO[eid] = time.time()
    if os.path.exists(rb_sync._caminhos(eid)[0]):
        return

    def rodar():
        try:
            r = rb_sync.sincronizar(banco(eid), False, eid)
            if not r.get("ocupado"):
                _rb_mudou(eid)
                usuarios.registrar("sistema", "ReportBuilder sincronizado",
                                   f"{eid}: leitura automática, {r.get('total', 0)} relatório(s)")
        except Exception:  # noqa: BLE001 - o erro fica gravado no estado da sincronização
            pass
    import threading
    threading.Thread(target=rodar, daemon=True, name=f"rb-auto-{eid}").start()


@app.route("/api/rb/sync", methods=["GET", "POST"])
@exige(admin=True)
def api_rb_sync():
    if request.method == "POST":
        import threading
        forcar = bool((request.get_json(silent=True) or {}).get("forcar"))
        bid = _bid()

        def rodar():
            try:
                r = rb_sync.sincronizar(banco(bid), forcar, bid)
                if not r.get("ocupado"):
                    _rb_mudou(bid)
            except Exception:  # noqa: BLE001 - o erro fica gravado no estado da sincronização
                pass
        threading.Thread(target=rodar, daemon=True).start()
        usuarios.registrar(g.usuario["login"], "sincronizar ReportBuilder", C()["nome_empresa"] + (" (completa)" if forcar else ""))
        time.sleep(0.3)
    return jsonify(estado=rb_sync.estado(_bid()), automatico=CFG["rb_sync_minutos"], total=len(relatorios_rb.todos()),
                   empresa=C()["nome_empresa"], varios=len(_bancos_usuario(g.usuario)) > 1)


# ------------------------------------------------------------------ administração
@app.route("/api/admin/catalogo")
@exige(admin=True)
def api_admin_catalogo():
    """Listas usadas no cadastro de usuários: relatórios (para escolher quais cada um vê) e tipos de movimento."""
    rb = [{"chave": _chave_rb(r["id"]), "nome": r["nome"], "pasta": r["pasta"], "modulo": r["modulo"], "antigo": r.get("antigo", False)}
          for r in relatorios_rb.todos()]
    prontos = [{"chave": "pronto:" + k, "nome": v["titulo"], "pasta": "Relatórios prontos", "modulo": v["modulo"]}
               for k, v in RELATORIOS.items()]
    consultas = [{"chave": f"sq:{c['id']}", "nome": c["nome"], "pasta": "Consultas salvas", "modulo": "relatorios"}
                 for c in usuarios.consultas_visiveis(0, True) if c["compartilhada"]]
    try:
        tipos = _em_cache("opcoes", 300, lambda: servicos.opcoes(banco(), C()))["tipos"]
    except db.ErroBanco:
        tipos = []
    return jsonify(relatorios=prontos + consultas + rb, tipos=tipos, bancos=_lista_bancos(_bancos_usuario(g.usuario)),
                   empresa=C()["nome_empresa"], empresa_id=_bid(), site=SITE)

def _banco_da_chave(chave):
    """Banco a que pertence a chave de um relatório do RB (None para relatórios prontos / consultas)."""
    if "|rb:" in chave:
        return chave.split("|", 1)[0]
    return bancos.PRINCIPAL if chave.startswith("rb:") else None


def _mesclar_relatorios(uid, novo):
    """A tela de usuários mostra só os relatórios do ReportBuilder da empresa em uso; os escolhidos nas
    outras empresas (e as pastas que só existem nelas) são mantidos."""
    antigo = next((u for u in usuarios.listar() if u["id"] == uid), {}).get("relatorios")
    if not antigo:
        return novo
    bid = _bid()
    pastas_aqui = {r["pasta"] for r in relatorios_rb.todos(bid)} | {"Relatórios prontos", "Consultas salvas"}
    ids = set(novo.get("ids") or []) | {i for i in antigo.get("ids", []) if _banco_da_chave(i) not in (None, bid)}
    pastas = set(novo.get("pastas") or []) | {p for p in antigo.get("pastas", []) if p not in pastas_aqui}
    return {"pastas": sorted(pastas), "ids": sorted(ids)}


@app.route("/api/banco", methods=["POST"])
@exige()
def api_trocar_banco():
    """Troca a empresa (banco) em uso, sem sair do painel."""
    bid = str((request.get_json(silent=True) or {}).get("id") or "")
    if bid not in _bancos_usuario(g.usuario):
        return jsonify(erro="Empresa não liberada para você."), 403
    session["banco"] = bid
    usuarios.registrar(g.usuario["login"], "trocou de empresa", _CFGS[bid]["nome_empresa"])
    r = jsonify(ok=True, nome=_CFGS[bid]["nome_empresa"])
    r.set_cookie("painel_banco", bid, max_age=365 * 86400, samesite="Strict",
                 secure=CFG["https"] or (SITE and CFG["cookie_seguro"]), httponly=True)
    return r


@app.route("/api/usuarios", methods=["GET", "POST"])
@exige(admin=True)
def api_usuarios():
    if request.method == "POST":
        dados = request.get_json(silent=True) or {}
        if SITE:
            dados.pop("bancos", None)
            dados.pop("super", None)
            destino = _bid()
            escolhida = str(dados.pop("empresa", "") or "")
            if g.usuario.get("super") and not dados.get("id") and escolhida and escolhida != destino:
                # Tecnoplan cadastrando usuário para outra empresa: ele fica na empresa escolhida no cadastro.
                # Relatórios e tipos de movimento da tela são os da empresa em uso, então ficam "todos".
                if escolhida not in _CFGS:
                    return jsonify(erro="Empresa escolhida não encontrada ou desativada."), 400
                destino = escolhida
                dados["relatorios"], dados["tipos_mov"] = None, []
            try:
                usuarios.salvar(dados, dados.get("id"), empresa=destino)
            except ValueError as e:
                return jsonify(erro=str(e)), 400
            usuarios.registrar(g.usuario["login"], "salvou usuário", f'{dados.get("login", "")} ({destino})')
            return jsonify(ok=True, empresa=destino, nome_empresa=_CFGS[destino]["nome_empresa"])
        if "bancos" in dados and isinstance(dados["bancos"], list):
            dados["bancos"] = [b for b in dados["bancos"] if b in _CFGS]
        if dados.get("id") and isinstance(dados.get("relatorios"), dict):
            dados["relatorios"] = _mesclar_relatorios(dados["id"], dados["relatorios"])
        try:
            usuarios.salvar(dados, dados.get("id"))
        except ValueError as e:
            return jsonify(erro=str(e)), 400
        usuarios.registrar(g.usuario["login"], "salvou usuário", dados.get("login", ""))
        return jsonify(ok=True)
    lista = usuarios.listar(empresa=_bid()) if SITE else usuarios.listar()
    return jsonify(usuarios=lista, modulos=usuarios.MODULOS, acessos=usuarios.ultimos_acessos(),
                   site=SITE, empresa=C()["nome_empresa"])


# ------------------------------------------------------------------ TP DASH online: agentes e empresas
def _agente_autenticado():
    """Empresa dona da chave enviada pelo agente (Authorization: Bearer <chave>) ou None."""
    if not SITE:
        return None
    auth = request.headers.get("Authorization", "")
    eid = usuarios.empresa_por_chave(auth[7:].strip() if auth.startswith("Bearer ") else "")
    if not eid:
        time.sleep(0.5)                     # atrasa quem tenta adivinhar chaves
    return eid


def _corpo_json():
    dados = request.get_data(cache=False)
    if request.headers.get("Content-Encoding", "").lower() == "gzip":
        import gzip
        dados = gzip.decompress(dados)
    return json.loads(dados or b"{}")


@app.route("/agente/ola", methods=["POST"])
def agente_ola():
    eid = _agente_autenticado()
    if not eid:
        return jsonify(erro="Chave do agente inválida ou empresa desativada."), 401
    d = _corpo_json()
    ag = nuvem.agente(eid)
    ag.info = {k: d.get(k) for k in ("modo", "empresa", "descricao", "status_movimento", "status_lancamento")}
    # dados do agente para o TP DASH ADMIN (os agentes mais novos mandam também o computador e a sincronização)
    usuarios.gravar_info_agente(eid, {
        "modo": d.get("modo"), "codempresa": d.get("empresa"), "maquina": str(d.get("maquina") or "")[:80],
        "sistema": str(d.get("sistema") or "")[:80], "sincronizacao": d.get("sincronizacao") if isinstance(d.get("sincronizacao"), dict) else None,
        "conectado": time.time()})
    ag.versao = str(d.get("versao") or "")[:20]
    ag.ip = request.remote_addr or ""
    ag.visto = time.time()
    usuarios.registrar("agente", "agente conectado", f"{eid} · IP {ag.ip} · {ag.info.get('descricao') or ''}")
    usuarios.gravar_estado_agente(eid, ag.visto, ag.versao, ag.info.get("descricao"), ag.ip)
    _GRAVADO[eid] = ag.visto
    usuarios.pedir_filiais(eid)                      # lê as filiais logo que o agente começar a buscar pedidos
    _rb_auto(eid)                                    # relatórios do ReportBuilder ainda não lidos (ex.: site reiniciou)
    return jsonify(ok=True, empresa=usuarios.empresa(eid)["nome"], espera=nuvem.ESPERA_PEDIDOS)


# Estado dos agentes gravado no banco do site, para o TP DASH ADMIN (outro site) mostrar.
_GRAVADO = {}             # empresa -> última vez que o "visto" foi gravado
_LENDO_FILIAIS = set()


_CAMPOS_FILIAL_NOMES = {
    "NOME": "razao", "CGC": "cnpj", "INSCRICAOESTADUAL": "ie", "INSCRICAOMUNICIPAL": "im", "TELEFONE": "telefone",
    "EMAIL": "email", "RUA": "rua", "NUMERO": "numero", "COMPLEMENTO": "complemento", "BAIRRO": "bairro",
    "CIDADE": "cidade", "ESTADO": "uf", "CEP": "cep", "CONTATO": "contato", "INATIVO": "inativo"}
_CAMPOS_FILIAL = ["CODFILIAL", "NOMEFANTASIA"] + list(_CAMPOS_FILIAL_NOMES)
_FILIAL_SIMPLES = set()   # empresas cuja GFILIAL não tem esses campos (lidas só com código e nome)


def _ler_filiais(eid):
    try:
        try:
            if eid in _FILIAL_SIMPLES:
                raise db.ErroBanco("GFILIAL sem os campos de cadastro")
            # só os campos de cadastro: a GFILIAL também guarda senhas e certificados, que nunca saem do cliente
            cols, linhas, _ = banco(eid).consultar(
                "SELECT " + ", ".join(_CAMPOS_FILIAL) + " FROM GFILIAL WHERE CODEMPRESA = ? ORDER BY CODFILIAL",
                (C(eid)["empresa"],))
        except db.ErroBanco:      # banco com outra versão da GFILIAL: lê só o básico (e não tenta de novo)
            _FILIAL_SIMPLES.add(eid)
            cols, linhas, _ = banco(eid).consultar(
                "SELECT CODFILIAL, NOMEFANTASIA FROM GFILIAL WHERE CODEMPRESA = ? ORDER BY CODFILIAL", (C(eid)["empresa"],))
        lista = []
        for l in linhas:
            r = {str(c).upper(): ("" if v is None else str(v).strip()) for c, v in zip(cols, l)}
            f = {"codigo": r.get("CODFILIAL"), "nome": r.get("NOMEFANTASIA") or r.get("NOME") or ""}
            f.update({k: r[c] for c, k in _CAMPOS_FILIAL_NOMES.items() if c in r})
            lista.append(f)
        usuarios.gravar_filiais(eid, lista)
    except (db.ErroBanco, KeyError) as e:
        usuarios.gravar_filiais(eid, None, str(e))
    finally:
        _LENDO_FILIAIS.discard(eid)


def _atualizar_estado(eid, ag):
    agora = time.time()
    if agora - _GRAVADO.get(eid, 0) < 20:
        return
    _GRAVADO[eid] = agora
    usuarios.gravar_estado_agente(eid, agora)
    if eid not in _LENDO_FILIAIS and usuarios.filiais_vencidas(eid, 1800):
        _LENDO_FILIAIS.add(eid)
        threading.Thread(target=_ler_filiais, args=(eid,), daemon=True).start()


@app.route("/agente/pedidos")
def agente_pedidos():
    eid = _agente_autenticado()
    if not eid:
        return jsonify(erro="Chave do agente inválida ou empresa desativada."), 401
    ag = nuvem.agente(eid)
    if not ag.info:
        return jsonify(erro="Envie /agente/ola primeiro."), 409
    _atualizar_estado(eid, ag)
    return jsonify(pedidos=ag.proximos(nuvem.ESPERA_PEDIDOS))


@app.route("/agente/sinc", methods=["POST"])
def agente_sinc():
    """Sincronização: pacotes de linhas (novas/alteradas/apagadas) de uma tabela, ou o resumo da rodada."""
    eid = _agente_autenticado()
    if not eid:
        return jsonify(erro="Chave do agente inválida ou empresa desativada."), 401
    try:
        d = _corpo_json()
    except (ValueError, OSError):
        return jsonify(erro="Pacote inválido."), 400
    if "resumo" in d:
        resumo = d.get("resumo") if isinstance(d.get("resumo"), dict) else None
        if resumo is not None:
            resumo["recebido"] = time.time()          # hora do site: diz se a cópia está em dia
        usuarios.gravar_sinc_agente(eid, resumo)
        copia_leitura.esquecer(eid)
        return jsonify(ok=True)
    try:
        return jsonify(copia.receber(eid, d))
    except copia.ErroCopia as e:
        return jsonify(erro=str(e)), 400


@app.route("/agente/resposta", methods=["POST"])
def agente_resposta():
    eid = _agente_autenticado()
    if not eid:
        return jsonify(erro="Chave do agente inválida ou empresa desativada."), 401
    try:
        resp = _corpo_json()
    except (ValueError, OSError):
        return jsonify(erro="Resposta inválida."), 400
    segundos = nuvem.agente(eid).responder(resp)          # só os pedidos desta empresa estão na lista dela
    if segundos is not None:
        try:
            usuarios.contar_consulta(eid, bool(resp.get("ok")), segundos)
        except Exception:  # noqa: BLE001 - a contagem é só informativa: nunca atrapalha a resposta
            app.logger.exception("Falha ao contar a consulta do agente")
    return jsonify(ok=True)


def iniciar_servicos():
    """Tarefas em segundo plano: sincronização automática dos relatórios do ReportBuilder."""
    if SITE:
        return            # no site, a sincronização do ReportBuilder é feita pelo botão em Administração
    for bid, c in _CFGS.items():
        if c["modo"] == "demo":
            continue
        rb_sync.iniciar_automatico(
            lambda b=bid: banco(b), CFG["rb_sync_minutos"], ao_mudar=lambda b=bid: _rb_mudou(b), bid=bid,
            registrar=lambda txt, n=c["nome_empresa"]: usuarios.registrar("sistema", "ReportBuilder sincronizado", f"{n}: {txt}"))


def _vigiar_supervisor():
    """Quando iniciado pelo servico.py: se o supervisor terminar (ex.: tarefa parada), o painel termina junto."""
    import os
    import sys
    if os.environ.get("PAINEL_SUPERVISOR") != "1" or sys.stdin is None:
        return

    def esperar():
        try:
            while sys.stdin.buffer.read(1):
                pass
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)
    threading.Thread(target=esperar, daemon=True, name="supervisor").start()


def _nomes_extras():
    return list(CFG["nomes"]) + ([CFG["nome_local"] + ".local"] if CFG["nome_local"] else [])


if __name__ == "__main__":
    _vigiar_supervisor()
    iniciar_servicos()
    host, porta = CFG["servidor_host"], CFG["servidor_porta"]
    print(f"TP DASH em {'https' if CFG['https'] else 'http'}://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{porta}", flush=True)
    if SITE:
        from waitress import serve
        print(f"TP DASH online (site) em http://{host}:{porta} - coloque atrás do nginx com HTTPS", flush=True)
        # cada agente conectado segura um thread na espera de pedidos: threads de sobra
        serve(app, host=host, port=porta, threads=CFG.get("threads_site", 120), ident="tpdash", channel_timeout=300)
        raise SystemExit(0)
    try:
        print(f"Banco: {banco().testar()}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"ATENÇÃO - não foi possível conectar ao banco: {e}", flush=True)
    for _b in list(_CFGS)[1:]:
        try:
            print(f"Banco {_CFGS[_b]['nome_empresa']}: {banco(_b).testar()}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"ATENÇÃO - banco {_CFGS[_b]['nome_empresa']}: {e}", flush=True)
    if CFG["nome_local"] and host != "127.0.0.1":
        import mdns
        n = mdns.iniciar(CFG["nome_local"])
        if n:
            print(f"Nome na rede: {'https' if CFG['https'] else 'http'}://{n}:{porta}", flush=True)
    if CFG["https"]:
        import certificado
        import servidor_https
        try:
            cert, chave, _ = certificado.garantir(_nomes_extras())
        except ImportError:
            print("\nERRO: falta a biblioteca 'cryptography' (usada para o HTTPS).\n"
                  "Feche esta janela e rode o instalar.bat de novo (precisa de internet), ou execute:\n"
                  "   .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n", flush=True)
            raise SystemExit(1)
        print(f"HTTPS ativo. Certificado para os outros PCs: dados\\certificado.cer  SHA-256 {certificado.impressao_digital()}", flush=True)
        print("Nomes/IPs aceitos: " + ", ".join(certificado.nomes_do_certificado()), flush=True)
        servidor_https.servir(app, host, porta, cert, chave, renovar=lambda: certificado.garantir(_nomes_extras()))
    else:
        try:
            from waitress import serve
            serve(app, host=host, port=porta, threads=16, ident="painel", channel_timeout=300)
        except ImportError:
            print("Aviso: biblioteca 'waitress' não instalada; usando o servidor simples do Flask.", flush=True)
            app.run(host=host, port=porta, threaded=True)
