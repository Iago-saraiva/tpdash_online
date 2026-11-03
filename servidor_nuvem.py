"""TP DASH online hospedado (Render): o site e o TP DASH ADMIN no mesmo serviço, com endereços separados.

Variáveis de ambiente (painel do Render > Environment):
  TPDASH_NUVEM=1                     liga o modo hospedado (sem config.ini / admin.ini)
  TPDASH_DADOS=/var/data             pasta do disco persistente (usuários, empresas, chaves)
  TPDASH_CHAVE_SECRETA=...           chave do login do site (32+ caracteres)
  TPDASH_ADMIN_CHAVE_SECRETA=...     chave do login do ADMIN (32+ caracteres, diferente da do site)
  TPDASH_ADMIN_HOST=admin.seudominio.com.br    endereço próprio do ADMIN (recomendado), ou
  TPDASH_ADMIN_CAMINHO=/adm-xxxxxxxx           caminho do ADMIN no mesmo endereço do site (enquanto não há domínio)
  TPDASH_ADMIN_PERMITIR=200.1.2.3    (opcional) IPs que podem abrir o ADMIN
  TPDASH_NOME=TP DASH                (opcional) nome mostrado no login do site
O site fica num processo só (os pedidos aos agentes ficam em memória): use 1 instância no Render.
"""
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("TPDASH_NUVEM", "1")
sys.path.insert(0, os.path.join(AQUI, "site"))
sys.path.insert(1, os.path.join(AQUI, "admin"))

from app import app as site            # noqa: E402  (site TP DASH online)

ADMIN_HOSTS = {h.strip().lower() for h in os.environ.get("TPDASH_ADMIN_HOST", "").split(",") if h.strip()}
ADMIN_CAMINHO = "/" + os.environ.get("TPDASH_ADMIN_CAMINHO", "").strip().strip("/")
if ADMIN_CAMINHO == "/":
    ADMIN_CAMINHO = ""
if ADMIN_CAMINHO and len(ADMIN_CAMINHO) < 8:
    raise SystemExit("TPDASH_ADMIN_CAMINHO muito curto: use algo difícil de adivinhar, ex.: /adm-7f3k9q2m")

admin = None
if ADMIN_HOSTS or ADMIN_CAMINHO:
    from admin_app import app as admin  # noqa: E402  (TP DASH ADMIN: mesmo banco de empresas e usuários)


def _host(environ):
    h = environ.get("HTTP_HOST") or ""
    return h.split(",")[0].strip().split(":")[0].lower()


def aplicacao(environ, start_response):
    if admin is not None:
        if ADMIN_HOSTS and _host(environ) in ADMIN_HOSTS:
            return admin(environ, start_response)
        caminho = environ.get("PATH_INFO", "")
        if ADMIN_CAMINHO and (caminho == ADMIN_CAMINHO or caminho.startswith(ADMIN_CAMINHO + "/")):
            environ = dict(environ)
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + ADMIN_CAMINHO
            environ["PATH_INFO"] = caminho[len(ADMIN_CAMINHO):] or "/"
            return admin(environ, start_response)
    return site(environ, start_response)


if __name__ == "__main__":
    from waitress import serve
    porta = int(os.environ.get("PORT", "10000"))
    print(f"TP DASH online na porta {porta}", flush=True)
    if admin is None:
        print("TP DASH ADMIN desligado: defina TPDASH_ADMIN_HOST ou TPDASH_ADMIN_CAMINHO.", flush=True)
    else:
        print("TP DASH ADMIN em: " + ", ".join(sorted(ADMIN_HOSTS) + ([ADMIN_CAMINHO] if ADMIN_CAMINHO else [])), flush=True)
    # cada agente conectado segura um thread esperando pedidos: threads de sobra
    serve(aplicacao, host="0.0.0.0", port=porta, threads=int(os.environ.get("TPDASH_THREADS", "120")),
          ident="tpdash", channel_timeout=300)
