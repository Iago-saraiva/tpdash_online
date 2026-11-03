"""Servidor HTTPS do painel usando só a biblioteca padrão do Python (TLS 1.2+, várias conexões ao mesmo tempo).

- Cada conexão é atendida numa thread própria; o aperto de mão TLS acontece nessa thread, com tempo limite,
  para que um cliente lento não trave os outros.
- Quem acessar por http:// na mesma porta é redirecionado para https://.
"""
import socket
import socketserver
import ssl
import sys
import wsgiref.simple_server as _ws
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

TEMPO_LIMITE = 60   # segundos sem dados numa conexão
_ws.ServerHandler.server_software = "painel"   # não anuncia versão do Python no cabeçalho Server


class _Handler(WSGIRequestHandler):
    def setup(self):
        bruto = self.request
        bruto.settimeout(15)
        try:
            primeiro = bruto.recv(1, socket.MSG_PEEK)
        except OSError:
            primeiro = b""
        if primeiro and primeiro != b"\x16":           # não é TLS: provavelmente http://
            self._redirecionar(bruto)
            raise ConnectionAbortedError()
        tls = self.server.contexto.wrap_socket(bruto, server_side=True, do_handshake_on_connect=False)
        tls.settimeout(TEMPO_LIMITE)
        tls.do_handshake()
        self.request = tls
        super().setup()

    def _redirecionar(self, s):
        try:
            dados = s.recv(4096).decode("latin-1", "replace")
            host = next((l.split(":", 1)[1].strip() for l in dados.split("\r\n") if l.lower().startswith("host:")), "")
            caminho = dados.split(" ", 2)[1] if dados.count(" ") >= 2 else "/"
            if not caminho.startswith("/") or "\r" in caminho or "\n" in caminho:
                caminho = "/"
            if not host or any(c in host for c in "\r\n /\\"):
                host = f"localhost:{self.server.server_address[1]}"
            destino = f"https://{host}{caminho}"
            s.sendall(("HTTP/1.1 301 Moved Permanently\r\nLocation: " + destino +
                       "\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").encode("latin-1", "replace"))
        except OSError:
            pass
        finally:
            try:
                s.close()
            except OSError:
                pass

    def get_environ(self):
        env = super().get_environ()
        env["HTTPS"] = "on"
        env["wsgi.url_scheme"] = "https"
        return env

    def log_message(self, fmt, *args):   # sem log de cada requisição no console
        pass

    def handle(self):
        try:
            super().handle()
        except (ssl.SSLError, ConnectionError, socket.timeout):
            pass

    def finish(self):
        try:
            super().finish()
        except OSError:
            pass
        try:
            self.request.close()     # fecha o socket TLS (o socket original foi desanexado no wrap)
        except OSError:
            pass


class _Servidor(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, endereco, contexto):
        self.contexto = contexto
        super().__init__(endereco, _Handler)

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if isinstance(e, (ssl.SSLError, ConnectionError, socket.timeout, OSError)):
            return
        super().handle_error(request, client_address)

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        except OSError:
            pass


def _contexto(cert, chave):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, chave)
    ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:!aNULL:!MD5:!RC4")
    return ctx


def servir(app, host, porta, cert, chave, renovar=None, minutos=5):
    """renovar(): devolve (cert, chave, mudou?) - chamado de tempos em tempos; se o certificado foi refeito
    (ex.: o IP do servidor mudou), as próximas conexões já usam o novo, sem reiniciar o painel."""
    srv = _Servidor((host, porta), _contexto(cert, chave))
    srv.set_app(app)
    if renovar:
        import threading
        import time

        def laco():
            while True:
                time.sleep(minutos * 60)
                try:
                    c, k, mudou = renovar()
                    if mudou:
                        srv.contexto = _contexto(c, k)
                        print("Certificado do servidor atualizado (nomes/IPs novos).", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"Aviso: não consegui renovar o certificado: {e}", flush=True)
        threading.Thread(target=laco, daemon=True, name="renovar-certificado").start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()
