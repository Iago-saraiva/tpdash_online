"""Anuncia o painel na rede local com um nome fixo (ex.: painel.local), sem depender do IP.

Usa mDNS (o mesmo "Bonjour" de impressoras e Apple TV), só com a biblioteca padrão do Python.
Responde apenas perguntas do tipo "qual é o IP de <nome>.local?" - não aceita nem executa nada.
Funciona em: Windows 10/11, macOS, iPhone/iPad, Linux e Android 12 ou mais novo (na maioria dos aparelhos).
"""
import ipaddress
import socket
import struct
import threading
import time

GRUPO = "224.0.0.251"
PORTA = 5353
TTL = 120
estado = {"ativo": False, "nome": "", "erro": "", "respostas": 0}


def _nome_valido(n):
    n = (n or "").strip().lower()
    return n if n and len(n) <= 63 and all(c.isalnum() or c == "-" for c in n) and not n.startswith("-") else ""


def _ler_nome(pacote, pos, profundidade=0):
    partes = []
    while True:
        if pos >= len(pacote) or profundidade > 10:
            raise ValueError("nome inválido")
        t = pacote[pos]
        if t == 0:
            return ".".join(partes), pos + 1
        if t & 0xC0 == 0xC0:                       # ponteiro (compressão)
            alvo = ((t & 0x3F) << 8) | pacote[pos + 1]
            resto, _ = _ler_nome(pacote, alvo, profundidade + 1)
            if resto:
                partes.append(resto)
            return ".".join(partes), pos + 2
        partes.append(pacote[pos + 1:pos + 1 + t].decode("utf-8", "replace"))
        pos += 1 + t


def _codificar(nome):
    return b"".join(bytes([len(p)]) + p.encode() for p in nome.split(".")) + b"\x00"


def _perguntas(pacote):
    _id, flags, qd = struct.unpack("!HHH", pacote[:6])
    if flags & 0x8000:                             # é resposta, não pergunta
        return _id, []
    pos, saida = 12, []
    for _ in range(min(qd, 32)):
        nome, pos = _ler_nome(pacote, pos)
        tipo, classe = struct.unpack("!HH", pacote[pos:pos + 4])
        pos += 4
        saida.append((nome.lower(), tipo, classe))
    return _id, saida


def _ips_v4():
    import certificado
    return [ip for ip in certificado.ips_locais() if ip.version == 4 and not ip.is_loopback]


def _ips_para(origem):
    """IPs do servidor na mesma rede de quem perguntou (evita mandar IP de placa virtual/VPN)."""
    ips = _ips_v4()
    try:
        o = ipaddress.ip_address(origem)
        mesma = [ip for ip in ips if ipaddress.ip_network(f"{ip}/24", strict=False) == ipaddress.ip_network(f"{o}/24", strict=False)]
        if mesma:
            return mesma
    except ValueError:
        pass
    return ips[:1] if ips else []


def _resposta(nome, ips, _id=0, pergunta=None, ttl=TTL):
    qd = 1 if pergunta else 0
    cab = struct.pack("!HHHHHH", _id, 0x8400, qd, len(ips), 0, 0)
    corpo = b""
    if pergunta:
        corpo += _codificar(nome) + struct.pack("!HH", 1, 1)
    for ip in ips:
        corpo += _codificar(nome) + struct.pack("!HHIH", 1, 0x8001 if not pergunta else 1, ttl, 4) + socket.inet_aton(str(ip))
    return cab + corpo


class _Anunciante(threading.Thread):
    def __init__(self, nome, registrar):
        super().__init__(daemon=True, name="mdns")
        self.fqdn = nome + ".local"
        self.registrar = registrar or (lambda txt: None)
        self.grupos = set()

    def _socket(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("", PORTA))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.settimeout(30)
        return s

    def _entrar_grupos(self, s):
        novos = []
        for ip in _ips_v4():
            if ip in self.grupos:
                continue
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(GRUPO) + socket.inet_aton(str(ip)))
            except OSError:
                pass                     # já estava no grupo nessa placa
            self.grupos.add(ip)
            novos.append(ip)
        return novos

    def _anunciar(self, s, ips):
        for ip in ips:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(str(ip)))
                s.sendto(_resposta(self.fqdn, [ip]), (GRUPO, PORTA))
            except OSError:
                pass

    def run(self):
        espera = 5
        while True:
            try:
                s = self._socket()
            except OSError as e:
                estado.update(ativo=False, erro=f"porta 5353 indisponível: {e}")
                time.sleep(min(espera, 300))
                espera *= 2
                continue
            estado.update(ativo=True, erro="")
            self.grupos.clear()
            self._anunciar(s, self._entrar_grupos(s))
            ultimo = time.monotonic()
            try:
                while True:
                    if time.monotonic() - ultimo > 60:          # IP novo (ex.: trocou de rede): entra e anuncia
                        self._anunciar(s, self._entrar_grupos(s))
                        ultimo = time.monotonic()
                    try:
                        pacote, (origem, porta) = s.recvfrom(9000)
                    except socket.timeout:
                        continue
                    try:
                        _id, perguntas = _perguntas(pacote)
                    except (ValueError, struct.error, IndexError):
                        continue
                    for nome, tipo, classe in perguntas:
                        if nome != self.fqdn or tipo not in (1, 255):
                            continue
                        ips = _ips_para(origem)
                        if not ips:
                            continue
                        estado["respostas"] += 1
                        if porta != PORTA:                         # pergunta "simples" (nslookup, etc.): responde direto
                            s.sendto(_resposta(self.fqdn, ips, _id, pergunta=True, ttl=10), (origem, porta))
                        elif classe & 0x8000:                      # pediu resposta direta
                            s.sendto(_resposta(self.fqdn, ips), (origem, porta))
                        else:
                            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(str(ips[0])))
                            s.sendto(_resposta(self.fqdn, ips), (GRUPO, PORTA))
            except OSError as e:
                estado.update(ativo=False, erro=str(e))
                try:
                    s.close()
                except OSError:
                    pass
                time.sleep(5)


def iniciar(nome, registrar=None):
    """Começa a responder por <nome>.local. Devolve o nome completo ou '' se o nome for inválido."""
    nome = _nome_valido(nome)
    if not nome:
        return ""
    estado["nome"] = nome + ".local"
    _Anunciante(nome, registrar).start()
    return nome + ".local"
