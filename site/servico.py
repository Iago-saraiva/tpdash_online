"""Supervisor do TP DASH: mantém o painel sempre no ar.

- Inicia o app.py e, se ele parar por qualquer motivo, inicia de novo (em poucos segundos).
- A cada 30 s confere se o painel responde em /saude; se travar (4 falhas seguidas), reinicia.
- Grava tudo em dados\\servidor.log (troca de arquivo ao passar de 5 MB).
- Só roda um supervisor por vez (os demais saem sozinhos).

Uso: pythonw servico.py   (a tarefa "TP DASH" criada pelo proteger_instalacao.bat faz isso)
"""
import datetime as dt
import os
import ssl
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(BASE, "dados")
LOG = os.path.join(DADOS, "servidor.log")
TRAVA = os.path.join(DADOS, "servico.trava")
INTERVALO = 30
FALHAS_MAX = 4
TOLERANCIA_INICIO = 120


def registrar(txt):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 5 * 1024 * 1024:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} [supervisor] {txt}\n")
    except OSError:
        pass


def _trava():
    """Trava exclusiva do arquivo: garante um supervisor só. Devolve o arquivo aberto ou None."""
    os.makedirs(DADOS, exist_ok=True)
    f = open(TRAVA, "a+")
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


def _config():
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(BASE, "config.ini"), encoding="utf-8")
    s = cp["servidor"] if cp.has_section("servidor") else {}
    https = s.get("https", "nao").strip().lower() in ("sim", "s", "1", "true", "yes")
    host = s.get("host", "0.0.0.0").strip()
    if host in ("0.0.0.0", "", "::"):
        host = "127.0.0.1"
    return f"{'https' if https else 'http'}://{host}:{int(s.get('porta', '8050'))}/saude"


def _python():
    """python.exe (com console oculto) em vez de pythonw.exe: assim a saída vai para o log."""
    exe = sys.executable
    pasta, nome = os.path.split(exe)
    if nome.lower() == "pythonw.exe" and os.path.exists(os.path.join(pasta, "python.exe")):
        exe = os.path.join(pasta, "python.exe")
    return exe


def _responde(url):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE        # só confere se responde (é o próprio servidor, 127.0.0.1)
    try:
        with urllib.request.urlopen(url, timeout=20, context=ctx) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _iniciar(log):
    env = dict(os.environ, PAINEL_SUPERVISOR="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    return subprocess.Popen([_python(), os.path.join(BASE, "app.py")], cwd=BASE, env=env,
                            stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def _parar(p):
    try:
        p.stdin.close()                     # o app.py termina sozinho ao perceber
        p.wait(10)
    except Exception:  # noqa: BLE001
        pass
    if p.poll() is None:
        p.kill()
        p.wait(10)


def main():
    trava = _trava()
    if trava is None:
        print("O supervisor do painel já está rodando.")
        return
    url = _config()
    espera = 3
    registrar(f"iniciado (pid {os.getpid()}); vigiando {url}")
    while True:
        log = open(LOG, "a", encoding="utf-8")
        inicio = time.monotonic()
        try:
            p = _iniciar(log)
        except OSError as e:
            registrar(f"não consegui iniciar o app.py: {e}")
            log.close()
            time.sleep(30)
            continue
        registrar(f"painel iniciado (pid {p.pid})")
        falhas = 0
        while p.poll() is None:
            try:
                p.wait(INTERVALO)            # volta na hora se o painel parar
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() - inicio < TOLERANCIA_INICIO:
                continue
            if _responde(url):
                falhas, espera = 0, 3
            else:
                falhas += 1
                registrar(f"painel não respondeu ({falhas}/{FALHAS_MAX})")
                if falhas >= FALHAS_MAX:
                    registrar("painel travado: reiniciando")
                    _parar(p)
        codigo = p.returncode
        log.close()
        vida = time.monotonic() - inicio
        if vida > 300:
            espera = 3                       # rodou um bom tempo: volta logo
        registrar(f"painel parou (código {codigo}, rodou {int(vida)} s); iniciando de novo em {espera} s")
        time.sleep(espera)
        espera = min(espera * 2, 60)         # se cair em sequência (ex.: config errado), espera mais entre tentativas


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
