"""Leitura do arquivo config.ini do TP DASH."""
import configparser
import os
import secrets
import sys

# no executável (TPDashAgente.exe) a pasta é a do .exe, não a pasta temporária onde ele se abre
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")
EXEMPLO_PATH = os.path.join(BASE_DIR, "config.ini.exemplo")

SO_LEITURA = False   # agente usando o config.ini do painel: nunca grava nele

_PADRAO_STATUS_MOV = {"C": "Cancelado"}
_PADRAO_STATUS_LAN = {"A": "Em aberto", "B": "Baixado", "C": "Cancelado"}



def _sem_sufixo(texto, sufixo):
    """Igual a str.removesuffix (que só existe a partir do Python 3.9; o agente também roda no 3.8)."""
    return texto[:-len(sufixo)] if sufixo and texto.endswith(sufixo) else texto

def _garantir_config():
    """Cria config.ini a partir do exemplo na primeira execução, com chave secreta própria."""
    if os.path.exists(CONFIG_PATH):
        return
    if SO_LEITURA:
        raise SystemExit(f"Arquivo não encontrado: {CONFIG_PATH}")
    with open(EXEMPLO_PATH, encoding="utf-8") as f:
        texto = f.read()
    texto = texto.replace("TROQUE-ESTA-CHAVE", secrets.token_hex(24))
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(texto)


def _chave_secreta(atual):
    """Chave que assina as sessões. Se estiver vazia, curta ou com o texto de exemplo, gera uma aleatória
    e grava no config.ini (assim continua a mesma depois de reiniciar)."""
    atual = (atual or "").strip()
    if len(atual) >= 32 and atual != "TROQUE-ESTA-CHAVE":
        return atual
    nova = secrets.token_hex(32)
    if SO_LEITURA:
        return nova
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            texto = f.read()
        import re
        if re.search(r"(?m)^\s*chave_secreta\s*=.*$", texto):
            texto = re.sub(r"(?m)^\s*chave_secreta\s*=.*$", "chave_secreta = " + nova, texto, count=1)
        else:
            texto = re.sub(r"(?m)^\[servidor\]\s*$", "[servidor]\nchave_secreta = " + nova, texto, count=1)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(texto)
    except OSError:
        pass
    return nova


def carregar():
    _garantir_config()
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # preserva maiúsculas nas chaves de status
    lidos = cp.read(CONFIG_PATH, encoding="utf-8")
    if not lidos:
        # o configparser ignora em silêncio arquivo sem permissão de leitura: avisa claramente
        import getpass
        raise SystemExit(f"Não consegui ler o {CONFIG_PATH} (sem permissão?). Usuário do Windows atual: "
                         f"{getpass.getuser()}. Rode proteger_instalacao.bat como administrador ou dê permissão "
                         f"de leitura do config.ini para este usuário.")

    b = cp["banco"] if cp.has_section("banco") else {}
    s = cp["servidor"] if cp.has_section("servidor") else {}

    cfg = {
        "modo": b.get("modo", "firebird").strip().lower(),
        "host": b.get("host", "localhost").strip(),
        "porta": int(b.get("porta", "3050")),
        "arquivo": b.get("arquivo", "").strip(),
        "usuario": b.get("usuario", "SYSDBA").strip(),
        "senha": b.get("senha", "masterkey"),
        "charset": b.get("charset", "WIN1252").strip(),
        "fbclient": b.get("fbclient", "").strip(),
        "empresa": int(b.get("empresa", "1")),
        "servidor_porta": int(s.get("porta", "8050")),
        "servidor_host": s.get("host", "0.0.0.0").strip(),
        "chave_secreta": _chave_secreta(s.get("chave_secreta", "")),
        "limite_linhas": int(s.get("limite_linhas", "5000")),
        "timeout_minutos": int(s.get("sessao_minutos", "480")),
        "lembrar_dias": int(s.get("lembrar_dias", "30")),
        "nome_empresa": s.get("nome_empresa", "TP DASH").strip(),
        "https": s.get("https", "nao").strip().lower() in ("sim", "s", "1", "true", "yes"),
        "nome_local": _sem_sufixo(s.get("nome_local", "painel").strip().lower(), ".local"),
        "nomes": [x.strip() for x in s.get("nomes", "").replace(";", ",").split(",") if x.strip()],
        "permitir": [x.strip() for x in s.get("permitir", "").replace(";", ",").split(",") if x.strip()],
        "rb_sync_minutos": int((cp["relatorios"] if cp.has_section("relatorios") else {}).get("sincronizar_minutos", "10")),
        "status_movimento": dict(_PADRAO_STATUS_MOV),
        "status_lancamento": dict(_PADRAO_STATUS_LAN),
    }
    # Vários bancos (uma empresa/Puma por banco): [banco] é o principal; [banco:ID] são os outros.
    # O que não for informado num [banco:ID] é herdado do [banco] (servidor, usuário, senha...).
    import re as _re
    bancos = {}

    def _banco(sec, bid, nome_padrao):
        d = {
            "id": bid,
            "nome": sec.get("nome", nome_padrao).strip() or nome_padrao,
            "modo": sec.get("modo", cfg["modo"]).strip().lower(),
            "host": sec.get("host", cfg["host"]).strip(),
            "porta": int(sec.get("porta", str(cfg["porta"]))),
            "arquivo": sec.get("arquivo", cfg["arquivo"] if bid == "principal" else "").strip(),
            "usuario": sec.get("usuario", cfg["usuario"]).strip(),
            "senha": sec.get("senha", cfg["senha"]),
            "charset": sec.get("charset", cfg["charset"]).strip(),
            "fbclient": sec.get("fbclient", cfg["fbclient"]).strip(),
            "empresa": int(sec.get("empresa", str(cfg["empresa"]))),
        }
        bancos[bid] = d

    _banco(b, "principal", cfg["nome_empresa"])
    for sec in cp.sections():
        m = _re.fullmatch(r"\s*banco\s*:\s*([A-Za-z0-9_-]{1,30})\s*", sec)
        if m:
            bid = m.group(1).lower()
            if bid != "principal" and bid not in bancos:
                _banco(cp[sec], bid, m.group(1))
    cfg["bancos"] = bancos
    # TP DASH online: [nuvem] site = sim -> este painel é o site (os dados vêm dos agentes dos clientes)
    nv = cp["nuvem"] if cp.has_section("nuvem") else {}
    cfg["site"] = nv.get("site", "nao").strip().lower() in ("sim", "s", "1", "true", "yes")
    cfg["atras_de_proxy"] = nv.get("atras_de_proxy", "sim").strip().lower() in ("sim", "s", "1", "true", "yes")
    cfg["cookie_seguro"] = nv.get("cookie_seguro", "sim").strip().lower() in ("sim", "s", "1", "true", "yes")
    if cp.has_section("status_movimento"):
        cfg["status_movimento"].update({k.strip(): v.strip() for k, v in cp["status_movimento"].items()})
    if cp.has_section("status_lancamento"):
        cfg["status_lancamento"].update({k.strip(): v.strip() for k, v in cp["status_lancamento"].items()})
    return cfg
