"""Gerador de QR Code (sem bibliotecas externas) - modo byte, correção de erro nível M, versões 1 a 10.
Usado para mostrar no PC um QR com o endereço do painel, para abrir/instalar no celular."""

# versão: (total de codewords, codewords de correção por bloco, [(qtd blocos, codewords de dados por bloco), ...])
_TAB_M = {
    1: (26, 10, [(1, 16)]), 2: (44, 16, [(1, 28)]), 3: (70, 26, [(1, 44)]), 4: (100, 18, [(2, 32)]),
    5: (134, 24, [(2, 43)]), 6: (172, 16, [(4, 27)]), 7: (196, 18, [(4, 31)]), 8: (242, 22, [(2, 38), (2, 39)]),
    9: (292, 22, [(3, 36), (2, 37)]), 10: (346, 26, [(4, 43), (1, 44)]),
}
_ALINHAMENTO = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
                8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
_RESTO = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

# ---------------------------------------------------------------- Reed-Solomon (GF(256), polinômio 0x11D)
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _gerador(n):
    g = [1]
    for i in range(n):
        novo = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            novo[j] ^= c
            novo[j + 1] ^= _mul(c, _EXP[i])
        g = novo
    return g


def _ec(dados, n):
    g = _gerador(n)
    resto = list(dados) + [0] * n
    for i in range(len(dados)):
        c = resto[i]
        if c:
            for j in range(1, len(g)):
                resto[i + j] ^= _mul(g[j], c)
    return resto[len(dados):]


# ---------------------------------------------------------------- montagem
def _bits_dados(texto, versao):
    dados = texto.encode("utf-8")
    total, ecb, grupos = _TAB_M[versao]
    capacidade = sum(q * n for q, n in grupos)
    bits = [0, 1, 0, 0]                                       # modo byte
    largura = 8 if versao < 10 else 16
    bits += [(len(dados) >> i) & 1 for i in range(largura - 1, -1, -1)]
    for b in dados:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    if len(bits) > capacidade * 8:
        return None
    bits += [0] * min(4, capacidade * 8 - len(bits))          # terminador
    bits += [0] * (-len(bits) % 8)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(cw) < capacidade:
        cw.append(pad[(len(cw) - len(bits) // 8) % 2])
    # blocos + correção, intercalados
    blocos, ecs, k = [], [], 0
    for q, n in grupos:
        for _ in range(q):
            blocos.append(cw[k:k + n])
            ecs.append(_ec(cw[k:k + n], ecb))
            k += n
    final = []
    for i in range(max(len(b) for b in blocos)):
        for b in blocos:
            if i < len(b):
                final.append(b[i])
    for i in range(ecb):
        for e in ecs:
            final.append(e[i])
    saida = []
    for c in final:
        saida += [(c >> i) & 1 for i in range(7, -1, -1)]
    return saida + [0] * _RESTO[versao]


def _bch(valor, gerador, bits_gerador):
    v = valor << (bits_gerador - 1)
    while v.bit_length() >= bits_gerador:
        v ^= gerador << (v.bit_length() - bits_gerador)
    return v


def _matriz(versao, bits, mascara):
    n = 17 + 4 * versao
    m = [[0] * n for _ in range(n)]
    funcao = [[False] * n for _ in range(n)]

    def pos(r, c, v):
        m[r][c] = 1 if v else 0
        funcao[r][c] = True

    for i in range(n):                                           # timing
        pos(6, i, i % 2 == 0)
        pos(i, 6, i % 2 == 0)
    for (r0, c0) in ((3, 3), (3, n - 4), (n - 4, 3)):           # finders + separadores
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < n and 0 <= c < n:
                    d = max(abs(dr), abs(dc))
                    pos(r, c, d not in (2, 4))
    cs = _ALINHAMENTO[versao]
    ult = len(cs) - 1
    for a, r0 in enumerate(cs):                                  # alinhamento
        for b, c0 in enumerate(cs):
            if (a == 0 and b == 0) or (a == 0 and b == ult) or (a == ult and b == 0):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    pos(r0 + dr, c0 + dc, max(abs(dr), abs(dc)) != 1)

    def formato(msk):
        dado = (0 << 3) | msk                                    # nível M = 00
        bitsf = ((dado << 10) | _bch(dado, 0x537, 11)) ^ 0x5412
        g = lambda i: (bitsf >> i) & 1
        for i in range(6):
            pos(i, 8, g(i))
        pos(7, 8, g(6))
        pos(8, 8, g(7))
        pos(8, 7, g(8))
        for i in range(9, 15):
            pos(8, 14 - i, g(i))
        for i in range(8):
            pos(8, n - 1 - i, g(i))
        for i in range(8, 15):
            pos(n - 15 + i, 8, g(i))
        pos(n - 8, 8, 1)                                         # módulo escuro

    formato(mascara)
    if versao >= 7:
        vi = (versao << 12) | _bch(versao, 0x1F25, 13)
        for i in range(18):
            b = (vi >> i) & 1
            a, c = n - 11 + i % 3, i // 3
            pos(c, a, b)
            pos(a, c, b)

    k = 0
    direita = n - 1
    while direita >= 1:
        if direita == 6:
            direita = 5
        for vert in range(n):
            for j in range(2):
                c = direita - j
                subindo = ((direita + 1) & 2) == 0
                r = n - 1 - vert if subindo else vert
                if not funcao[r][c]:
                    b = bits[k] if k < len(bits) else 0
                    k += 1
                    m[r][c] = b ^ (1 if _mascara(mascara, r, c) else 0)
        direita -= 2
    return m


def _mascara(k, r, c):
    return [
        (r + c) % 2 == 0, r % 2 == 0, c % 3 == 0, (r + c) % 3 == 0,
        (r // 2 + c // 3) % 2 == 0, (r * c) % 2 + (r * c) % 3 == 0,
        ((r * c) % 2 + (r * c) % 3) % 2 == 0, ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    ][k]


def _penalidade(m):
    n = len(m)
    p = 0
    for linhas in (m, [list(x) for x in zip(*m)]):
        for linha in linhas:
            seq, ant = 0, None
            for v in linha:
                if v == ant:
                    seq += 1
                else:
                    if seq >= 5:
                        p += seq - 2
                    seq, ant = 1, v
            if seq >= 5:
                p += seq - 2
            s = "".join(map(str, linha))
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r + 1][c] == m[r][c + 1] == m[r + 1][c + 1]:
                p += 3
    escuros = sum(map(sum, m))
    p += 10 * (abs(escuros * 100 // (n * n) - 50) // 5)
    return p


def gerar(texto):
    """Matriz (lista de listas 0/1) do QR Code para o texto."""
    for versao in range(1, 11):
        bits = _bits_dados(texto, versao)
        if bits is not None:
            break
    else:
        raise ValueError("Texto grande demais para o QR Code")
    melhor = min((_matriz(versao, bits, k) for k in range(8)), key=_penalidade)
    return melhor


def svg(texto, tamanho_modulo=6, margem=4):
    m = gerar(texto)
    n = len(m)
    lado = (n + 2 * margem) * tamanho_modulo
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n + 2 * margem} {n + 2 * margem}" '
              f'width="{lado}" height="{lado}" shape-rendering="crispEdges">'
              f'<rect width="100%" height="100%" fill="#fff"/><path fill="#000" d="']
    for r in range(n):
        for c in range(n):
            if m[r][c]:
                partes.append(f"M{c + margem} {r + margem}h1v1h-1z")
    partes.append('"/></svg>')
    return "".join(partes)
