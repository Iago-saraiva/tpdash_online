"""Certificados HTTPS do TP DASH.

Funciona como uma pequena "autoridade certificadora" local:
  dados\\ca.pem / ca_chave.pem     autoridade do painel (criada uma vez, vale 10 anos; a chave nunca sai do servidor)
  dados\\certificado.cer           cópia da autoridade para instalar UMA VEZ nos computadores e celulares
  dados\\certificado.pem / chave.pem  certificado do servidor, assinado pela autoridade

O certificado do servidor é refeito sozinho quando muda o IP, o nome do computador ou os nomes do config.ini
([servidor] nome_local / nomes) e quando está perto de vencer. Como os aparelhos confiam na autoridade
(e não no certificado do servidor), eles NÃO precisam instalar nada de novo nessas trocas.
"""
import datetime as dt
import ipaddress
import os
import socket

from config import BASE_DIR, DADOS_DIR

DADOS = DADOS_DIR
CERT = os.path.join(DADOS, "certificado.pem")      # servidor + autoridade (cadeia)
CHAVE = os.path.join(DADOS, "chave.pem")
CA = os.path.join(DADOS, "ca.pem")
CA_CHAVE = os.path.join(DADOS, "ca_chave.pem")
CER = os.path.join(DADOS, "certificado.cer")       # autoridade em DER (para instalar nos aparelhos)


def ips_locais():
    ips = {ipaddress.ip_address("127.0.0.1")}
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ipaddress.ip_address(ip))
    except OSError:
        pass
    try:   # IP usado para sair para a rede
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(ipaddress.ip_address(s.getsockname()[0]))
        s.close()
    except OSError:
        pass
    return ips


def _nomes(extras=()):
    dns = {"localhost"}
    try:
        h = socket.gethostname()
        if h:
            dns.add(h.lower())
            dns.add(h.lower() + ".local")
        fq = socket.getfqdn()
        if fq:
            dns.add(fq.lower())
    except OSError:
        pass
    ips = ips_locais()
    for n in extras:
        n = (n or "").strip().lower().rstrip(".")
        if not n:
            continue
        try:
            ips.add(ipaddress.ip_address(n))
        except ValueError:
            if all(c.isalnum() or c in "-." for c in n):
                dns.add(n)
    return dns, ips


def _carregar(caminho):
    from cryptography import x509
    with open(caminho, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def _fim(c):
    return c.not_valid_after_utc if hasattr(c, "not_valid_after_utc") else c.not_valid_after.replace(tzinfo=dt.timezone.utc)


def _salvar_chave(caminho, chave):
    from cryptography.hazmat.primitives import serialization
    with open(caminho, "wb") as f:
        f.write(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))


def _garantir_ca():
    """Devolve (certificado, chave) da autoridade; cria se não existir."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    if os.path.exists(CA) and os.path.exists(CA_CHAVE):
        try:
            c = _carregar(CA)
            with open(CA_CHAVE, "rb") as f:
                k = serialization.load_pem_private_key(f.read(), None)
            if _fim(c) - dt.datetime.now(dt.timezone.utc) > dt.timedelta(days=60):
                if not os.path.exists(CER):
                    with open(CER, "wb") as f:
                        f.write(c.public_bytes(serialization.Encoding.DER))
                return c, k
        except Exception:  # noqa: BLE001 - arquivo corrompido: cria outra
            pass
    os.makedirs(DADOS, exist_ok=True)
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    try:
        h = socket.gethostname()
    except OSError:
        h = "servidor"
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"TP DASH - autoridade local ({h})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TP DASH")])
    agora = dt.datetime.now(dt.timezone.utc)
    ski = x509.SubjectKeyIdentifier.from_public_key(k.public_key())
    c = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(k.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(agora - dt.timedelta(days=1)).not_valid_after(agora + dt.timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
         .add_extension(x509.KeyUsage(digital_signature=False, key_encipherment=False, key_cert_sign=True,
                                      content_commitment=False, data_encipherment=False, key_agreement=False,
                                      crl_sign=True, encipher_only=False, decipher_only=False), True)
         .add_extension(ski, False)
         .sign(k, hashes.SHA256()))
    _salvar_chave(CA_CHAVE, k)
    with open(CA, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.PEM))
    with open(CER, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.DER))
    for p in (CERT, CHAVE):          # certificado antigo (de outra autoridade ou autoassinado) não serve mais
        if os.path.exists(p):
            os.remove(p)
    return c, k


def _cobre(cert, ca, dns, ips):
    """O certificado do servidor atual serve? (assinado pela autoridade, cobre os nomes/IPs, longe de vencer)"""
    from cryptography import x509
    try:
        if cert.issuer != ca.subject:
            return False
        from cryptography.x509.oid import NameOID
        org = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        if not org or org[0].value != "TP DASH":     # certificado do nome antigo: refaz (aparelhos não reinstalam)
            return False
        cert.verify_directly_issued_by(ca)
        if _fim(cert) - dt.datetime.now(dt.timezone.utc) < dt.timedelta(days=30):
            return False
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        tem_dns = {d.lower() for d in san.get_values_for_type(x509.DNSName)}
        tem_ip = set(san.get_values_for_type(x509.IPAddress))
        return dns <= tem_dns and ips <= tem_ip
    except Exception:  # noqa: BLE001
        return False


def garantir(nomes_extras=()):
    """Garante autoridade + certificado do servidor válidos para os nomes/IPs atuais.
    Devolve (cert, chave, refeito?)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca, ca_k = _garantir_ca()
    dns, ips = _nomes(nomes_extras)
    if os.path.exists(CERT) and os.path.exists(CHAVE):
        try:
            atual = _carregar(CERT)
            if _cobre(atual, ca, dns, ips):
                return CERT, CHAVE, False
            # junta os nomes antigos: um IP que mudou continua aceito até o certificado vencer
            san = atual.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            if atual.issuer == ca.subject:
                dns |= {d.lower() for d in san.get_values_for_type(x509.DNSName)}
                ips |= set(san.get_values_for_type(x509.IPAddress))
        except Exception:  # noqa: BLE001
            pass
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    agora = dt.datetime.now(dt.timezone.utc)
    principal = sorted(d for d in dns if d != "localhost")[:1] or ["servidor"]
    c = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, principal[0]),
                                  x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TP DASH")]))
         .issuer_name(ca.subject).public_key(k.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(agora - dt.timedelta(days=1)).not_valid_after(agora + dt.timedelta(days=397))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName(d) for d in sorted(dns)] +
                                                    [x509.IPAddress(i) for i in sorted(ips, key=str)]), False)
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
         .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=False,
                                      content_commitment=False, data_encipherment=False, key_agreement=False,
                                      crl_sign=False, encipher_only=False, decipher_only=False), True)
         .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_k.public_key()), False)
         .sign(ca_k, hashes.SHA256()))
    tmp_k, tmp_c = CHAVE + ".novo", CERT + ".novo"
    _salvar_chave(tmp_k, k)
    with open(tmp_c, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    os.replace(tmp_k, CHAVE)
    os.replace(tmp_c, CERT)
    return CERT, CHAVE, True


def nomes_do_certificado():
    """Nomes e IPs aceitos pelo certificado atual do servidor (para mostrar em Administração)."""
    try:
        from cryptography import x509
        san = _carregar(CERT).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return [str(x) for x in san.get_values_for_type(x509.DNSName)] + \
               [str(x) for x in san.get_values_for_type(x509.IPAddress)]
    except Exception:  # noqa: BLE001
        return []


def impressao_digital():
    """SHA-256 do certificado que os aparelhos instalam (a autoridade do painel)."""
    import hashlib
    try:
        with open(CER, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()
        return ":".join(h[i:i + 2] for i in range(0, len(h), 2))
    except OSError:
        return None


if __name__ == "__main__":
    import sys
    try:
        import config
        cfg = config.carregar()
        extras = list(cfg.get("nomes", [])) + ([cfg["nome_local"] + ".local"] if cfg.get("nome_local") else [])
    except BaseException:  # noqa: BLE001
        extras = []
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--nova-autoridade" in sys.argv:          # só se a chave da autoridade vazou: todos reinstalam
        for p in (CA, CA_CHAVE, CER, CERT, CHAVE):
            if os.path.exists(p):
                os.remove(p)
    elif "--novo" in sys.argv:                   # refaz só o certificado do servidor (aparelhos não reinstalam)
        for p in (CERT, CHAVE):
            if os.path.exists(p):
                os.remove(p)
    garantir(extras + args)
    print("Certificado para instalar nos aparelhos:", CER)
    print("SHA-256:", impressao_digital())
    print("Nomes/IPs aceitos:", ", ".join(nomes_do_certificado()))
