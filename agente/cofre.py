"""Configuração do TP DASH Agente guardada cifrada (sem config.ini).

O arquivo dados\\agente.dat é cifrado pelo próprio Windows (DPAPI, escopo da máquina):
- copiado para outro computador, não abre;
- neste computador só abre quem consegue ler a pasta dados (administradores e o serviço do agente).
Dentro dele ficam: o login do app (senha só como hash), o endereço do site e, para cada empresa,
a chave do site e os dados do banco (inclusive a senha do Firebird).
"""
import base64
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sys

import config

ARQUIVO = os.path.join(config.BASE_DIR, "dados", "agente.dat")
_ENTROPIA = b"TPDashAgente/cofre/v1"
_CABECALHO = b"TPDA1"
ITERACOES = 240_000

BANCO_PADRAO = {"modo": "firebird", "host": "localhost", "porta": 3050, "arquivo": "", "usuario": "SYSDBA",
                "senha": "", "charset": "WIN1252", "fbclient": "", "empresa": 1}


class ErroCofre(Exception):
    pass


# ------------------------------------------------------------------ cifragem (Windows DPAPI)
if sys.platform == "win32":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(dados):
        buf = ctypes.create_string_buffer(dados, len(dados))
        return _Blob(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _CRYPTPROTECT_LOCAL_MACHINE = 0x4

    def _dpapi(dados, proteger):
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        entrada, _b1 = _blob(dados)
        entropia, _b2 = _blob(_ENTROPIA)
        saida = _Blob()
        if proteger:
            ok = crypt32.CryptProtectData(ctypes.byref(entrada), "TP DASH Agente", ctypes.byref(entropia), None, None,
                                          _CRYPTPROTECT_UI_FORBIDDEN | _CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(saida))
        else:
            ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
                                            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
        if not ok:
            raise ErroCofre("O Windows não conseguiu " + ("cifrar" if proteger else "abrir") +
                            " a configuração do agente (arquivo de outro computador ou corrompido).")
        try:
            return ctypes.string_at(saida.pbData, saida.cbData)
        finally:
            kernel32.LocalFree(saida.pbData)
else:  # só para os testes fora do Windows: NÃO é cifragem de verdade
    def _dpapi(dados, proteger):
        return base64.b64encode(dados) if proteger else base64.b64decode(dados)


# ------------------------------------------------------------------ arquivo
def existe():
    return os.path.exists(ARQUIVO)


def novo():
    return {"versao": 1, "usuario": None, "site": "", "empresas": []}


def carregar():
    if not existe():
        return None
    with open(ARQUIVO, "rb") as f:
        bruto = f.read()
    if not bruto.startswith(_CABECALHO):
        raise ErroCofre("Arquivo de configuração do agente inválido.")
    try:
        return json.loads(_dpapi(bruto[len(_CABECALHO):], False).decode("utf-8"))
    except ErroCofre:
        raise
    except Exception as e:  # noqa: BLE001
        raise ErroCofre(f"Arquivo de configuração do agente corrompido ({e}).") from e


def salvar(d):
    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    bruto = _CABECALHO + _dpapi(json.dumps(d, ensure_ascii=False).encode("utf-8"), True)
    tmp = ARQUIVO + ".novo"
    with open(tmp, "wb") as f:
        f.write(bruto)
    os.replace(tmp, ARQUIVO)


# ------------------------------------------------------------------ login do app
def _hash(senha, sal):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, ITERACOES).hex()


def definir_usuario(d, login, senha):
    sal = secrets.token_bytes(16)
    d["usuario"] = {"login": login.strip(), "sal": sal.hex(), "hash": _hash(senha, sal)}


def conferir(d, login, senha):
    u = (d or {}).get("usuario") or {}
    if not u:
        return False
    esperado = _hash(senha or "", bytes.fromhex(u["sal"]))
    return hmac.compare_digest(esperado, u["hash"]) and login.strip().lower() == u["login"].lower()


def senha_fraca(senha):
    if len(senha or "") < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if senha.isdigit() or senha.isalpha():
        return "Use letras e números na senha."
    return None


# ------------------------------------------------------------------ empresas
def id_empresa(chave):
    """O id vem da própria chave do site (<empresa>.<segredo>)."""
    return (chave or "").strip().split(".", 1)[0].lower()


def banco_completo(b):
    d = dict(BANCO_PADRAO)
    d.update({k: v for k, v in (b or {}).items() if v not in (None, "")})
    d["porta"] = int(d["porta"])
    d["empresa"] = int(d["empresa"])
    return d
