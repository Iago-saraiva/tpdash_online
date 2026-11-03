"""Ícone do TP DASH na bandeja do Windows (perto do relógio), para o SERVIDOR.

- Verde: painel rodando · Amarelo: iniciando / sem resposta · Vermelho: parado.
- Clique com o botão direito: quem está conectado agora, lista completa de conexões, abrir o painel,
  reiniciar o painel, abrir o log.
- Avisa (balão do Windows) quando alguém entra no painel.
- Fechar o ícone NÃO para o painel.

Uso: .venv\\Scripts\\pythonw.exe bandeja.py      (o iniciar.bat e o reiniciar_painel.bat já fazem isso)
     .venv\\Scripts\\python.exe bandeja.py --verificar   -> sai com código 0 se o painel está respondendo
"""
import configparser
import datetime as dt
import html
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(BASE, "dados")
INTERVALO = 5                     # segundos entre as conferências
PAGINA = os.path.join(tempfile.gettempdir(), "tp_dash_conexoes.html")


# ------------------------------------------------------------------ configuração e consultas ao painel
def _config():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(BASE, "config.ini"), encoding="utf-8")
    s = cp["servidor"] if cp.has_section("servidor") else {}
    https = s.get("https", "nao").strip().lower() in ("sim", "s", "1", "true", "yes")
    porta = int(s.get("porta", "8050") or 8050)
    return ("https" if https else "http"), porta


ESQUEMA, PORTA = _config()
URL = f"{ESQUEMA}://127.0.0.1:{PORTA}"
URL_ABRIR = f"{ESQUEMA}://localhost:{PORTA}"
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE          # é o próprio servidor (127.0.0.1)


def _get(caminho, cabecalhos=None, tempo=6):
    req = urllib.request.Request(URL + caminho, headers=cabecalhos or {})
    with urllib.request.urlopen(req, timeout=tempo, context=_SSL) as r:
        return r.status, r.read()


def responde():
    global URL, URL_ABRIR
    try:
        return _get("/saude", tempo=4)[0] == 200
    except Exception:  # noqa: BLE001
        pass
    # não deu: tenta o outro esquema (http/https), caso o config.ini não tenha sido lido
    outro = "http" if URL.startswith("https") else "https"
    antigo = URL, URL_ABRIR
    URL, URL_ABRIR = f"{outro}://127.0.0.1:{PORTA}", f"{outro}://localhost:{PORTA}"
    try:
        if _get("/saude", tempo=4)[0] == 200:
            return True
    except Exception:  # noqa: BLE001
        pass
    URL, URL_ABRIR = antigo
    return False


def _token():
    try:
        with open(os.path.join(DADOS, "bandeja.token"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def conexoes():
    """Dados de conexões do painel, ou None (painel antigo, sem permissão para ler o token etc.)."""
    t = _token()
    if not t:
        return None
    try:
        st, corpo = _get("/api/local/conexoes", {"X-Painel-Local": t})
        return json.loads(corpo.decode("utf-8")) if st == 200 else None
    except Exception:  # noqa: BLE001
        return None


def _tela(caminho):
    nomes = {"/": "Início", "/movimentos": "Movimentos", "/estoque": "Estoque", "/financeiro": "Financeiro",
             "/cadastros": "Cadastros", "/relatorios": "Relatórios", "/sql": "Consulta SQL", "/admin": "Administração",
             "/trocar-senha": "Trocar senha"}
    return nomes.get(caminho or "", caminho or "")


def _ha(seg):
    seg = int(seg or 0)
    if seg < 60:
        return "agora"
    if seg < 3600:
        return f"há {seg // 60} min"
    return f"há {seg // 3600} h"


# ------------------------------------------------------------------ desenho do ícone
def _icone(cor):
    from PIL import Image, ImageDraw
    n = 64
    try:                                                                                    # logotipo do TP DASH
        img = Image.open(os.path.join(BASE, "static", "icone-192.png")).convert("RGBA").resize((n, n), Image.LANCZOS)
    except OSError:
        img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((2, 2, n - 3, n - 3), radius=14, fill=(0, 165, 144, 255))
    d = ImageDraw.Draw(img)
    cores = {"verde": (47, 158, 68, 255), "amarelo": (242, 183, 5, 255), "vermelho": (224, 49, 49, 255)}
    d.ellipse((38, 38, 62, 62), fill=cores[cor], outline=(255, 255, 255, 255), width=3)   # bolinha de situação
    return img


# ------------------------------------------------------------------ página com a lista completa
def _tabela(titulo, colunas, linhas, vazio):
    if not linhas:
        return f"<h2>{html.escape(titulo)}</h2><p class='vazio'>{html.escape(vazio)}</p>"
    cab = "".join(f"<th>{html.escape(c)}</th>" for c in colunas)
    corpo = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in l) + "</tr>" for l in linhas)
    return f"<h2>{html.escape(titulo)} <span>({len(linhas)})</span></h2><table><thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table>"


def gravar_pagina(situacao, dados):
    d = dados or {}
    ativos = [[a["nome"], a["login"], a["ip"], a.get("navegador", ""), _tela(a.get("pagina")), _ha(a.get("ha_segundos")),
               a.get("inicio_txt", "")[11:16], a.get("requisicoes", 0)] for a in d.get("ativos", [])]
    hoje = [[a["nome"], a["ip"], a.get("navegador", ""), a.get("inicio_txt", "")[11:16], a.get("ultimo_txt", "")[11:16],
             a.get("requisicoes", 0)] for a in d.get("hoje", [])]
    br = lambda q: f"{q[8:10]}/{q[5:7]}/{q[:4]} {q[11:16]}" if len(q or "") >= 16 else (q or "")
    logins = [[br(l["quando"]), l["usuario"], "Entrou" if l["acao"] == "login" else "Senha errada / recusado", l.get("detalhe", "")]
              for l in d.get("logins", [])]
    cor = {"rodando": "#2f9e44", "iniciando": "#e0a800", "parado": "#e03131"}[situacao]
    txt = {"rodando": "Painel rodando", "iniciando": "Painel iniciando / sem resposta", "parado": "Painel parado"}[situacao]
    aviso = "" if dados is not None or situacao != "rodando" else (
        "<p class='vazio'>Não consegui ler as conexões. Reinicie o painel (reiniciar_painel.bat) para ativar esta lista.</p>")
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{INTERVALO}"><title>TP DASH - conexões</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f7fa;color:#1d2733}}
 header{{background:#13253d;color:#fff;padding:14px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
 header h1{{font-size:18px;margin:0;flex:1}} .sit{{display:inline-flex;align-items:center;gap:8px;font-weight:600}}
 .bola{{width:12px;height:12px;border-radius:50%;background:{cor};box-shadow:0 0 0 3px #fff3}}
 main{{padding:8px 22px 30px;max-width:1200px}} h2{{font-size:15px;margin:22px 0 8px}} h2 span{{color:#6b7785;font-weight:400}}
 table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid #dde3ea;border-radius:8px;overflow:hidden;font-size:13px}}
 th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid #edf0f4;white-space:nowrap}} th{{background:#eef2f6;font-weight:600}}
 .vazio{{color:#6b7785;background:#fff;border:1px dashed #cdd5de;border-radius:8px;padding:12px}}
 .nota{{color:#6b7785;font-size:12px;margin-top:20px}}
</style></head><body>
<header><h1>TP DASH · conexões{(' · ' + html.escape(d['empresa'])) if d.get('empresa') else ''}</h1>
<span class="sit"><span class="bola"></span>{txt}</span>
<span>{html.escape(URL_ABRIR)}</span></header><main>{aviso}
{_tabela("Conectados agora (últimos 10 minutos)", ["Usuário", "Login", "IP", "Aparelho", "Tela", "Última ação", "Desde", "Ações"], ativos, "Ninguém usando o painel neste momento.")}
{_tabela("Quem usou hoje", ["Usuário", "IP", "Aparelho", "Primeiro acesso", "Último acesso", "Ações"], hoje, "Ninguém usou o painel hoje (desde que ele foi iniciado).")}
{_tabela("Últimas entradas (login)", ["Quando", "Usuário", "Resultado", "Detalhe"], logins, "Nenhuma entrada registrada.")}
<p class="nota">Atualiza sozinha a cada {INTERVALO} segundos · painel no ar desde {html.escape(d.get('inicio', '-'))} ·
última leitura {dt.datetime.now():%d/%m/%Y %H:%M:%S}</p></main></body></html>"""
    tmp = PAGINA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(pagina)
    os.replace(tmp, PAGINA)


# ------------------------------------------------------------------ uma instância só
def _trava():
    f = open(os.path.join(tempfile.gettempdir(), "tp_dash_bandeja.trava"), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


# ------------------------------------------------------------------ ícone
class Bandeja:
    def __init__(self):
        import pystray
        self.pystray = pystray
        self.situacao = "iniciando"
        self.dados = None
        self.vistos = None              # (login, ip) já conhecidos, para avisar só de quem entrou agora
        self.avisar = True
        self.parado_desde = None
        self.imagens = {k: _icone(c) for k, c in (("rodando", "verde"), ("iniciando", "amarelo"), ("parado", "vermelho"))}
        self.icone = pystray.Icon("TPDash", self.imagens["iniciando"], "TP DASH: conferindo...", self._menu())

    # ---- menu (montado de novo a cada atualização)
    def _menu(self):
        P = self.pystray
        ativos = (self.dados or {}).get("ativos", [])
        sit = {"rodando": f"● Painel rodando (porta {PORTA})", "iniciando": "● Painel iniciando / sem resposta",
               "parado": "● Painel PARADO"}[self.situacao]
        itens = [P.MenuItem(sit, None, enabled=False)]
        if self.situacao == "rodando" and self.dados is not None:
            if ativos:
                sub = [P.MenuItem(f"{a['nome']} · {a['ip']} · {_ha(a.get('ha_segundos'))}", None, enabled=False)
                       for a in ativos[:20]]
                if len(ativos) > 20:
                    sub.append(P.MenuItem(f"... e mais {len(ativos) - 20}", None, enabled=False))
                itens.append(P.MenuItem(f"Conectados agora: {len(ativos)}", P.Menu(*sub)))
            else:
                itens.append(P.MenuItem("Ninguém conectado agora", None, enabled=False))
        itens += [
            P.Menu.SEPARATOR,
            P.MenuItem("Ver conexões (lista completa)", self.ver_conexoes, default=True),
            P.MenuItem("Abrir o painel", lambda *_: webbrowser.open(URL_ABRIR)),
            P.MenuItem("Avisar quando alguém entrar", self._alternar_aviso, checked=lambda _: self.avisar),
            P.Menu.SEPARATOR,
            P.MenuItem("Reiniciar o painel", self.reiniciar),
            P.MenuItem("Abrir o log do servidor", self.abrir_log),
            P.Menu.SEPARATOR,
            P.MenuItem("Fechar este ícone (o painel continua)", self.sair),
        ]
        return P.Menu(*itens)

    def _alternar_aviso(self, *_):
        self.avisar = not self.avisar

    # ---- ações
    def ver_conexoes(self, *_):
        gravar_pagina(self.situacao, self.dados)
        webbrowser.open("file:///" + PAGINA.replace("\\", "/"))

    def reiniciar(self, *_):
        bat = os.path.join(BASE, "reiniciar_painel.bat")
        if os.name == "nt":
            import ctypes
            ctypes.windll.shell32.ShellExecuteW(None, "runas", bat, None, BASE, 1)    # pede permissão de administrador
        else:
            subprocess.Popen([bat], cwd=BASE)

    def abrir_log(self, *_):
        log = os.path.join(DADOS, "servidor.log")
        if os.name == "nt":
            subprocess.Popen(["notepad.exe", log])
        else:
            webbrowser.open("file://" + log)

    def sair(self, *_):
        self.icone.stop()

    # ---- conferência periódica
    def _atualizar(self):
        ok = responde()
        if ok:
            self.situacao, self.parado_desde = "rodando", None
            self.dados = conexoes()
        else:
            self.dados = None
            if self.parado_desde is None:
                self.parado_desde = time.monotonic()
            # sem resposta por pouco tempo = iniciando/reiniciando; depois de 30 s = parado
            self.situacao = "iniciando" if time.monotonic() - self.parado_desde < 30 else "parado"
        ativos = (self.dados or {}).get("ativos", [])
        if self.dados is not None:
            agora = {(a["login"], a["ip"]) for a in ativos}
            if self.vistos is not None and self.avisar:
                novos = [a for a in ativos if (a["login"], a["ip"]) not in self.vistos]
                if novos:
                    txt = "\n".join(f"{a['nome']} ({a['ip']} · {a.get('navegador', '')})" for a in novos[:4])
                    try:
                        self.icone.notify(txt, "Entrou no painel" if len(novos) == 1 else f"{len(novos)} entraram no painel")
                    except Exception:  # noqa: BLE001
                        pass
            self.vistos = agora          # quem some por mais de 10 min sai da lista: se voltar, avisa de novo
        titulo = {"rodando": f"TP DASH: rodando · {len(ativos)} conectado{'s' if len(ativos) != 1 else ''}",
                  "iniciando": "TP DASH: iniciando / sem resposta", "parado": "TP DASH: PARADO"}[self.situacao]
        self.icone.icon = self.imagens[self.situacao]
        self.icone.title = titulo[:127]
        self.icone.menu = self._menu()
        try:
            self.icone.update_menu()
        except Exception:  # noqa: BLE001
            pass
        if os.path.exists(PAGINA):                     # mantém a página aberta atualizada
            try:
                gravar_pagina(self.situacao, self.dados)
            except OSError:
                pass

    def _laco(self, icone):
        # chamado pelo próprio pystray (setup) numa thread separada, depois que o ícone foi criado
        try:
            icone.visible = True
        except Exception:  # noqa: BLE001
            pass
        while True:
            try:
                self._atualizar()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(INTERVALO)

    def rodar(self):
        self.icone.run(setup=self._laco)


def main():
    if "--verificar" in sys.argv:
        sys.exit(0 if responde() else 1)
    trava = _trava()
    if trava is None:
        return                                          # o ícone já está aberto
    try:
        if os.path.exists(PAGINA):
            os.remove(PAGINA)
    except OSError:
        pass
    Bandeja().rodar()


if __name__ == "__main__":
    main()
