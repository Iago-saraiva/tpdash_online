"""Assistente (chat) do TP DASH, sem IA e sem internet: entende perguntas de uma lista de assuntos
(movimentos, financeiro, estoque, produtos, clientes) e responde com consultas prontas ao banco.

Cada resposta pode trazer uma tabela; a tabela inteira fica guardada em memória por 2 horas para o
usuário baixar em PDF ou Excel. Respeita as permissões do usuário (módulos e tipos de movimento).
"""
import datetime as dt
import difflib
import re
import secrets
import threading
import time
import unicodedata

import pandas as pd

import servicos

MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
LINHAS_NA_TELA = 15
ARQUIVO_VALIDADE = 2 * 3600

MODULO_NOME = {"movimentos": "Movimentos", "financeiro": "Financeiro", "estoque": "Estoque",
               "cadastros": "Cadastros", "inicio": "Início"}


class Resposta(dict):
    pass


# ------------------------------------------------------------------ utilidades de texto
def norm(txt):
    """minúsculas e sem acentos (para comparar o que o usuário escreveu com os nomes do banco)."""
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt.lower()).strip()


def tem(t, *padroes):
    return any(re.search(p, t) for p in padroes)


def moeda(v):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return str(v)
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def inteiro(v):
    return f"{int(v or 0):,}".replace(",", ".")


def data_br(d):
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    return d.strftime("%d/%m/%Y")


def _lista_br(itens):
    itens = [i for i in itens if i]
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1] if itens else ""


# ------------------------------------------------------------------ entender melhor a frase
# abreviações e jeitos comuns de escrever -> forma que o assistente entende
_ABREVIACOES = {
    "vc": "voce", "vcs": "voces", "qto": "quanto", "qnto": "quanto", "qt": "quanto", "qtos": "quantos", "qtd": "quantidade",
    "hj": "hoje", "amanha": "amanha", "mov": "movimentos", "movs": "movimentos", "movto": "movimento", "movtos": "movimentos",
    "vlr": "valor", "vl": "valor", "pgto": "pagamento", "pagto": "pagamento", "pgtos": "pagamentos", "fin": "financeiro",
    "estq": "estoque", "prod": "produto", "prods": "produtos", "cli": "cliente", "clis": "clientes", "forn": "fornecedor",
    "fornec": "fornecedor", "vend": "vendedor", "func": "funcionario", "tit": "titulos", "dup": "duplicata", "nf": "notas",
    "nfs": "notas", "nfe": "notas", "rel": "relatorio", "q": "que", "pq": "porque", "tb": "tambem", "tbm": "tambem",
    "prox": "proximos", "ult": "ultimos", "jan.": "jan", "xls": "excel",
}
# frases com o mesmo sentido -> frase que as regras já conhecem (aplicadas em ordem)
_SINONIMOS = [
    (r"\b(quem (me|nos) deve|quem (esta|estao|ta|tao) devendo|clientes devedores|inadimplentes?)\b", "maiores devedores"),
    (r"\b(o que|quanto) (eu )?(tenho|temos) (pra|para|a) receber\b", "contas a receber em aberto"),
    (r"\b(o que|quanto) (eu )?(tenho|temos) (pra|para|a) pagar\b", "contas a pagar em aberto"),
    (r"\b(quanto|o que) (eu )?(devo|devemos)\b", "contas a pagar em aberto"),
    (r"\b(minhas|nossas)? ?dividas?\b", "contas a pagar"),
    (r"\b(boletos?|duplicatas?|titulos?) (atrasad[oa]s|vencid[oa]s)\b", "contas a receber vencidas"),
    (r"\b(contas|titulos) (atrasad[oa]s|em atraso)\b", "contas vencidas"),
    (r"\bquem (mais )?(vendeu|vende|movimentou)\b", "movimentos por vendedor"),
    (r"\b(vendemos|vendeu|vendi|vendido|vendidos|vendida|vendidas|faturamos|faturou|faturei|faturado)\b", "vendas"),
    (r"\b(compramos|comprou|comprei|comprado|comprados)\b", "compras"),
    (r"\b(recebi|recebeu|recebido|recebidos|entrou de dinheiro|entrou no caixa)\b", "recebemos"),
    (r"\b(paguei|pagou|pago|pagos|saiu de dinheiro|saiu do caixa)\b", "pagamos"),
    (r"\b(o que|quanto) (tem|tenho|temos|ha) (no|em) estoque\b", "valor do estoque"),
    (r"\bestoque (zerado|negativo|furado)\b", "saldos negativos"),
    (r"\b(itens|produtos) (com saldo )?negativos?\b", "saldos negativos"),
    (r"\bmelhores clientes\b", "maiores clientes"),
    (r"\bmaiores fornecedores\b", "compras por fornecedor"),
    (r"\bfluxo de caixa\b", "resumo do mes"),
    (r"\bproxima semana\b", "proximos 7 dias"),
    (r"\bsemana que vem\b", "proximos 7 dias"),
    (r"\bmes que vem\b", "proximos 30 dias"),
]
_NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
            "nove": 9, "dez": 10, "quinze": 15, "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "cem": 100}
# palavras que as regras usam (para corrigir erros de digitação, ex.: "movimetos" -> "movimentos")
_VOCABULARIO = sorted(set("""movimentos movimento movimentacao vendedor vendedores vendedora funcionario funcionarios cliente clientes
fornecedor fornecedores contas conta receber pagar vencidas vencidos vencida vencido vencer vencendo vencem estoque produto
produtos saldo saldos negativos negativo financeiro resumo listar lista compras vendas cancelados canceladas recebidas
recebemos pagamos pagas devedores atrasadas atrasados grupo grupos local locais janeiro fevereiro marco abril maio junho
julho agosto setembro outubro novembro dezembro hoje ontem amanha semana passado passada proximos proximas dias mes meses
ano anos faturamento documentos pedidos tipo tipos mensal maiores menores total inadimplentes titulos boletos duplicatas
almoxarifado inventario dados ficha telefone endereco cadastro quanto quantos quais excel planilha ajuda filial trimestre
semestre aberto valor material materiais preco custo diario semanal ultimos ultimas indicadores visao geral
ultima ultimo proxima proximo passados atual atuais esta este essa esse nesta neste semanas quanta quantas qual mostrar
mostre todos todas tudo sobre entre desde dentro maior menor primeiro primeiros principais melhores contato email cnpj
cidade venda compra pedido nota notas entrada entradas saida saidas cancelado cancelada receita despesa despesas pagamento
pagamentos recebimento recebimentos devendo devem tenho temos vencimento emissao baixa baixados quitados previsao tempo
obrigado obrigada valeu tarde noite retrasado anterior relatorio quantidade movimentaram movimentamos geral
entrou saiu entrar sair dinheiro caixa fluxo ranking parado parados mostra quero queria preciso saber gostaria pode
poderia fazer custa comprar vender ganhar ganhamos lucro dentro fora""".split()))


def _corrigir(palavra, protegidas):
    if len(palavra) < 4 or palavra in _VOCABULARIO or palavra in protegidas or not palavra.isalpha():
        return palavra
    m = difflib.get_close_matches(palavra, _VOCABULARIO, n=1, cutoff=0.85 if len(palavra) > 4 else 0.88)
    return m[0] if m else palavra


def preparar(t, protegidas=frozenset()):
    """Arruma a frase (já normalizada) antes das regras: abreviações, erros de digitação, números por extenso e
    jeitos diferentes de perguntar a mesma coisa. 'protegidas' = palavras de nomes do banco (não são corrigidas)."""
    t = re.sub(r"[?!;,]+", " ", t)
    t = " ".join(_ABREVIACOES.get(p, p) for p in t.split())
    for padrao, troca in _SINONIMOS:          # antes e depois da correção (a frase pode já estar certa)
        t = re.sub(padrao, troca, t)
    t = " ".join(_corrigir(p, protegidas) for p in t.split())
    t = re.sub(r"\b(" + "|".join(_NUMEROS) + r")\s+(maiores|melhores|primeiros|principais|mais|ultimos|ultimas|proximos|proximas|dias|meses|semanas)\b",
               lambda m: f"{_NUMEROS[m.group(1)]} {m.group(2)}", t)
    for padrao, troca in _SINONIMOS:
        t = re.sub(padrao, troca, t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ tabelas guardadas para PDF/Excel
_tabelas = {}
_trava = threading.Lock()


def _guardar(uid, titulo, subtitulo, colunas, linhas):
    agora = time.time()
    with _trava:
        for k in [k for k, v in _tabelas.items() if agora - v["t"] > ARQUIVO_VALIDADE]:
            _tabelas.pop(k, None)
        while len(_tabelas) >= 300:
            _tabelas.pop(min(_tabelas, key=lambda k: _tabelas[k]["t"]), None)
        tid = secrets.token_urlsafe(16)
        _tabelas[tid] = {"uid": uid, "titulo": titulo, "subtitulo": subtitulo, "colunas": colunas,
                         "linhas": linhas, "t": agora}
    return tid


def obter_tabela(tid, uid):
    with _trava:
        t = _tabelas.get(tid)
    if not t or t["uid"] != uid or time.time() - t["t"] > ARQUIVO_VALIDADE:
        return None
    return t


# ------------------------------------------------------------------ cadastros em cache (busca por nome sem acento)
_cache = {}


def _em_cache(chave, segundos, fn):
    agora = time.time()
    if chave in _cache and agora - _cache[chave][0] < segundos:
        return _cache[chave][1]
    v = fn()
    _cache[chave] = (agora, v)
    return v


def _vendedores(ctx):
    def ler():
        _, linhas, _ = ctx["banco"].consultar("SELECT CODVEN, NOME FROM TVENDEDOR WHERE CODEMPRESA = ?", (ctx["cfg"]["empresa"],))
        return [(str(c).strip(), (n or "").strip(), norm(n)) for c, n in linhas if n]
    return _em_cache(f"{ctx['bid']}:vend", 300, ler)


def _cfos(ctx):
    def ler():
        _, linhas, _ = ctx["banco"].consultar(
            "SELECT CODCFO, NOME, NOMEFANTASIA FROM FCFO WHERE CODEMPRESA = ?", (ctx["cfg"]["empresa"],))
        return [(str(c).strip(), (n or "").strip(), norm(f"{n or ''} {f or ''}")) for c, n, f in linhas]
    return _em_cache(f"{ctx['bid']}:cfo", 300, ler)


def _produtos(ctx):
    def ler():
        _, linhas, _ = ctx["banco"].consultar(
            "SELECT CODPRD, NUMNOFABRIC, NOMEFANTASIA FROM TPRODUTO WHERE CODEMPRESA = ? "
            "AND (INATIVO IS NULL OR INATIVO <> 'T')", (ctx["cfg"]["empresa"],))
        return [(c, str(f or "").strip(), (n or "").strip(), norm(n)) for c, f, n in linhas]
    return _em_cache(f"{ctx['bid']}:prd", 300, ler)


_PALAVRAS_VAZIAS = set("""a o as os de do da dos das e em no na nos nas para por com sem que qual quais quanto quantos
quanta quantas me mostre mostrar mostra ver veja lista listar liste traga trazer gere gerar gera um uma uns umas
este esta esse essa neste nesta nesse nessa isso isto mes ano semana dia dias hoje ontem ultimo ultima ultimos
ultimas passado passada atual pdf excel planilha relatorio arquivo xlsx top maiores menores melhores total valor
valores ate desde entre ao aos pelo pela pelos pelas tudo todos todas cliente clientes fornecedor fornecedores
vendedor vendedores vendedora funcionario funcionarios funcionaria produto produtos material materiais item itens
saldo saldos preco precos estoque codigo dados ficha contato telefone email do""".split()) | set(MESES) | set(MESES_CURTOS)


def _termos(txt):
    return [p for p in re.findall(r"[a-z0-9./-]+", txt) if p not in _PALAVRAS_VAZIAS and not re.fullmatch(r"\d{1,2}", p)]


def _achar(lista, termos, chave_txt=2):
    """Itens cujo texto normalizado contém todos os termos (em qualquer ordem)."""
    if not termos:
        return []
    return [x for x in lista if all(t in x[chave_txt] for t in termos)]


# ------------------------------------------------------------------ período
def _fim_mes(d):
    return (pd.Timestamp(d) + pd.offsets.MonthEnd(0)).date()


def periodo(t, hoje=None, padrao="mes"):
    """Devolve (ini, fim, rótulo, informado). t já normalizado."""
    hoje = hoje or dt.date.today()
    ini_mes = hoje.replace(day=1)
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*(?:a|ate|-)\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        def d(dd, mm, aa):
            aa = int(aa) if aa else hoje.year
            aa = aa + 2000 if aa < 100 else aa
            return dt.date(aa, int(mm), int(dd))
        try:
            i, f = d(*m.group(1, 2, 3)), d(*m.group(4, 5, 6))
            return i, f, f"de {data_br(i)} a {data_br(f)}", True
        except ValueError:
            pass
    m = re.search(r"ultim[oa]s?\s+(\d+)\s+(dias|dia|meses|mes|semanas|semana)", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        if u.startswith("dia"):
            i = hoje - dt.timedelta(days=n - 1)
        elif u.startswith("semana"):
            i = hoje - dt.timedelta(days=7 * n - 1)
        else:
            i = (pd.Timestamp(ini_mes) - pd.DateOffset(months=n - 1)).date()
        u = {"dias": "dias", "dia": "dias", "mes": "meses", "meses": "meses", "semana": "semanas", "semanas": "semanas"}[u]
        return i, hoje, f"nos últimos {n} {u}" if n > 1 else f"no último {u[:-1] if u != 'meses' else 'mês'}", True
    if tem(t, r"\bhoje\b"):
        return hoje, hoje, "hoje", True
    if tem(t, r"\bontem\b"):
        o = hoje - dt.timedelta(days=1)
        return o, o, "ontem", True
    if tem(t, r"semana passada", r"ultima semana"):
        i = hoje - dt.timedelta(days=hoje.weekday() + 7)
        return i, i + dt.timedelta(days=6), "na semana passada", True
    if tem(t, r"(esta|essa|nesta|nessa) semana", r"semana atual"):
        i = hoje - dt.timedelta(days=hoje.weekday())
        return i, hoje, "nesta semana", True
    if tem(t, r"mes retrasado"):
        f = (ini_mes - pd.DateOffset(months=1)).date() - dt.timedelta(days=1)
        return f.replace(day=1), f, f"em {MESES[f.month - 1]}/{f.year}", True
    if tem(t, r"trimestre (passado|anterior)", r"ultimo trimestre"):
        q0 = dt.date(hoje.year, 3 * ((hoje.month - 1) // 3) + 1, 1)
        i = (pd.Timestamp(q0) - pd.DateOffset(months=3)).date()
        return i, q0 - dt.timedelta(days=1), f"no trimestre de {data_br(i)} a {data_br(q0 - dt.timedelta(days=1))}", True
    if tem(t, r"(este|esse|neste|nesse) trimestre", r"trimestre atual", r"\bno trimestre\b"):
        q0 = dt.date(hoje.year, 3 * ((hoje.month - 1) // 3) + 1, 1)
        return q0, hoje, "neste trimestre", True
    if tem(t, r"(este|esse|neste|nesse) semestre", r"semestre atual", r"\bno semestre\b"):
        s0 = dt.date(hoje.year, 1 if hoje.month <= 6 else 7, 1)
        return s0, hoje, "neste semestre", True
    if tem(t, r"semestre (passado|anterior)", r"ultimo semestre"):
        s0 = dt.date(hoje.year, 1 if hoje.month <= 6 else 7, 1)
        i = (pd.Timestamp(s0) - pd.DateOffset(months=6)).date()
        return i, s0 - dt.timedelta(days=1), f"no semestre de {data_br(i)} a {data_br(s0 - dt.timedelta(days=1))}", True
    if tem(t, r"mes passado", r"ultimo mes", r"mes anterior"):
        f = ini_mes - dt.timedelta(days=1)
        return f.replace(day=1), f, f"em {MESES[f.month - 1]}/{f.year}", True
    m = re.search(r"\b(" + "|".join(MESES + MESES_CURTOS) + r")\b(?:\s*(?:de|/)?\s*(\d{4}))?", t)
    if m:
        nome = m.group(1)
        mes = (MESES.index(nome) if nome in MESES else MESES_CURTOS.index(nome)) + 1
        ano = int(m.group(2)) if m.group(2) else (hoje.year if mes <= hoje.month else hoje.year - 1)
        i = dt.date(ano, mes, 1)
        return i, _fim_mes(i), f"em {MESES[mes - 1]}/{ano}", True
    if tem(t, r"ano passado", r"ultimo ano", r"ano anterior"):
        a = hoje.year - 1
        return dt.date(a, 1, 1), dt.date(a, 12, 31), f"em {a}", True
    m = re.search(r"\b(20\d{2})\b", t)
    if m:
        a = int(m.group(1))
        return dt.date(a, 1, 1), dt.date(a, 12, 31), f"em {a}", True
    if tem(t, r"(este|esse|neste|nesse) ano", r"ano atual", r"\bno ano\b", r"do ano"):
        return dt.date(hoje.year, 1, 1), hoje, f"em {hoje.year} (até hoje)", True
    if tem(t, r"(este|esse|neste|nesse) mes", r"mes atual", r"\bno mes\b", r"do mes"):
        return ini_mes, _fim_mes(hoje), f"em {MESES[hoje.month - 1]}/{hoje.year}", True
    if padrao == "mes":
        return ini_mes, _fim_mes(hoje), f"em {MESES[hoje.month - 1]}/{hoje.year}", False
    return None, None, "", False


def _top(t, padrao=10):
    m = re.search(r"\btop\s*(\d+)|\b(\d+)\s+(?:maiores|melhores|primeiros|principais|mais)", t)
    n = int(m.group(1) or m.group(2)) if m else padrao
    return max(1, min(n, 500))


def _formato(t):
    if tem(t, r"\bpdf\b"):
        return "pdf"
    if tem(t, r"excel|planilha|xlsx|\bxls\b"):
        return "xlsx"
    return None


# ------------------------------------------------------------------ montagem das respostas
def _resp(texto, ctx, tabela=None, sugestoes=None):
    r = Resposta(texto=texto, sugestoes=sugestoes or [])
    if tabela:
        titulo, sub, cols, linhas = tabela
        linhas = [[round(v, 4) if isinstance(v, float) else v for v in l] for l in linhas]
        r["tabela"] = {"titulo": titulo, "colunas": cols, "linhas": linhas[:LINHAS_NA_TELA], "total": len(linhas)}
        if linhas:
            r["tabela"]["id"] = _guardar(ctx["uid"], titulo, sub, cols, linhas)
            r["formato"] = ctx.get("formato")
    return r


def _sem_permissao(modulo):
    return Resposta(texto=f"Você não tem acesso ao módulo {MODULO_NOME.get(modulo, modulo)}, então não posso "
                          "responder sobre isso. Fale com o administrador.", sugestoes=[])


# ------------------------------------------------------------------ movimentos
def _filtro_mov(ctx, t, ini, fim):
    """WHERE dos movimentos: empresa, período, cancelados, tipo, vendedor, cliente e permissão de tipos."""
    where = " WHERE M.CODEMPRESA = ? AND M.DATAEMISSAO BETWEEN ? AND ?"
    params = [ctx["cfg"]["empresa"], ini, fim]
    descr, frase = [], []
    if tem(t, r"cancelad"):
        where += " AND M.STATUS = 'C'"
        descr.append("só cancelados")
        frase.append("cancelados")
    else:
        where += " AND (M.STATUS IS NULL OR M.STATUS <> 'C')"
    m = re.search(r"\b(\d\.\d(?:\.\d{1,3})*)\b", t)
    if m:
        where += " AND M.CODTMV STARTING WITH ?"
        params.append(m.group(1))
        descr.append(f"tipo {m.group(1)}")
        frase.append(m.group(1))
    if tem(t, r"\bcompras?\b") and not m:
        where += " AND M.CODTMV STARTING WITH ?"
        params.append("1.")
        descr.append("tipos 1.x (compras/entradas)")
        frase.append("compras")
    vend = _vendedor_citado(ctx, t)
    if vend:
        w, p = _in("M.CODVEN1", vend[0])
        where += w
        params += p
        descr.append(f"vendedor {vend[1]}")
        frase.append(f"do vendedor {vend[2]}")
    cli = _cfo_citado(ctx, t)
    if cli:
        w, p = _in("M.CODCFO", cli[0])
        where += w
        params += p
        descr.append(f"cliente {cli[1]}")
        frase.append(f"do cliente {cli[2]}")
    fil = _filial(t)
    if fil is not None:
        where += " AND M.CODFILIAL = ?"
        params.append(fil)
        descr.append(f"filial {fil}")
        frase.append(f"filial {fil}")
    w, p = servicos.filtro_tipos(ctx["tipos"])
    ctx["frase"] = " ".join(frase)
    return where + w, params + p, descr


def _citado(lista, termos, rotulo_plural):
    """Procura pelo código ou pelo nome. Devolve (códigos, rótulo, termos) ou None.
    Nome ambíguo: filtra por todos os cadastros parecidos (até 50)."""
    cod = [x for x in lista if norm(x[0]) in termos]
    if cod:
        return [cod[0][0]], cod[0][1], cod[0][0]
    while termos:
        achados = _achar(lista, termos)
        if achados:
            exatos = [a for a in achados if norm(a[1]) == " ".join(termos)]
            if len(exatos) == 1 or len(achados) == 1:
                a = (exatos or achados)[0]
                return [a[0]], a[1], " ".join(termos)
            return ([a[0] for a in achados[:50]], f"\"{' '.join(termos).upper()}\" ({len(achados)} {rotulo_plural})",
                    " ".join(termos))
        termos = termos[:-1]
    return None


def _vendedor_citado(ctx, t):
    m = re.search(r"\b(?:vendedor|vendedora|funcionario|funcionaria)\s+([a-z0-9 ]{2,60})", t)
    return _citado(_vendedores(ctx), _termos(m.group(1))[:3], "vendedores") if m else None


def _cfo_citado(ctx, t):
    m = re.search(r"(?<!por )\b(?:cliente|fornecedor)\s+(.{2,80})", t)
    return _citado(_cfos(ctx), _termos(m.group(1))[:4], "cadastros") if m else None


def _filial(t):
    """'filial 2' na frase -> 2 (None = todas)."""
    m = re.search(r"\bfilial\s*(\d{1,3})\b", t)
    return int(m.group(1)) if m else None


def _in(col, codigos):
    return f" AND {col} IN ({','.join('?' * len(codigos))})", list(codigos)


_FROM_MOV = """
FROM TMOV M
LEFT JOIN TTIPOMOV T ON T.CODTIPOMOV = M.CODTMV AND T.CODEMPRESA = M.CODEMPRESA
LEFT JOIN FCFO C ON C.CODCFO = M.CODCFO AND C.CODEMPRESA = M.CODEMPRESA
LEFT JOIN TVENDEDOR V ON V.CODVEN = M.CODVEN1 AND V.CODEMPRESA = M.CODEMPRESA"""


def movimentos(ctx, t):
    if "movimentos" not in ctx["modulos"]:
        return _sem_permissao("movimentos")
    ini, fim, rot, informado = periodo(t)
    where, params, descr = _filtro_mov(ctx, t, ini, fim)
    filtros = f" ({_lista_br(descr)})" if descr else ""
    sub = f"Período: {data_br(ini)} a {data_br(fim)}" + (f" · {_lista_br(descr)}" if descr else "") + " · sem cancelados" * (not tem(t, r"cancelad"))
    banco = ctx["banco"]
    n = _top(t)
    filtrou_vend = any(d.startswith("vendedor ") for d in descr)
    filtrou_cli = any(d.startswith("cliente ") for d in descr)

    def sug(*dims):
        per = f"de {data_br(ini)} a {data_br(fim)}"
        nomes = {"listar": "Listar movimentos"}
        return [{"rotulo": nomes.get(d, d[0].upper() + d[1:]),
                 "pergunta": re.sub(r"\s+", " ", f"{'Listar movimentos' if d == 'listar' else 'Movimentos ' + d} {ctx['frase']} {per}")}
                for d in dims if not (d == "por vendedor" and filtrou_vend or d == "por cliente" and filtrou_cli)]

    if tem(t, r"por vendedor", r"vendedores", r"por funcionari", r"funcionarios") or (
            tem(t, r"vendedor", r"funcionari") and not filtrou_vend):
        dim, col_sql, col_nome, titulo = "vendedor", "COALESCE(V.NOME, M.CODVEN1)", "VENDEDOR", "Movimentos por vendedor"
    elif tem(t, r"\bclientes\b", r"por cliente", r"maiores client", r"fornecedores", r"por fornecedor") and not (
            filtrou_cli and not tem(t, r"por cliente", r"por fornecedor")):
        dim, col_sql, col_nome, titulo = "cliente", "COALESCE(C.NOME, M.CODCFO)", "CLIENTE", "Movimentos por cliente"
        if tem(t, r"fornecedor", r"\bcompras?\b"):
            col_nome, titulo = "FORNECEDOR", "Movimentos por fornecedor"
    elif tem(t, r"por tipo", r"\btipos\b"):
        dim, col_sql, col_nome, titulo = "tipo", "M.CODTMV || ' ' || COALESCE(T.NOME, '')", "TIPO", "Movimentos por tipo"
    elif tem(t, r"por mes", r"mensal", r"cada mes", r"mes a mes", r"evolucao", r"por dia", r"diari"):
        dim = "dia" if tem(t, r"por dia", r"diari") else "mes"
        if not informado and dim == "mes":
            ini = (pd.Timestamp(ini) - pd.DateOffset(months=11)).date()
            where, params, descr = _filtro_mov(ctx, t, ini, fim)
            rot = "nos últimos 12 meses"
            sub = f"Período: {data_br(ini)} a {data_br(fim)} · sem cancelados"
        cols, linhas, _ = banco.consultar("SELECT M.DATAEMISSAO AS EMISSAO, M.VALORLIQUIDO AS VALOR" + _FROM_MOV + where, params)
        df = pd.DataFrame(linhas, columns=cols)
        if df.empty:
            return _resp(f"Não encontrei movimentos {rot}{filtros}.", ctx)
        df["VALOR"] = pd.to_numeric(df["VALOR"], errors="coerce").fillna(0)
        d = pd.to_datetime(df["EMISSAO"], errors="coerce")
        df["P"] = d.dt.strftime("%Y-%m" if dim == "mes" else "%Y-%m-%d")
        g = df.groupby("P").agg(QTD=("VALOR", "size"), VALOR=("VALOR", "sum")).reset_index()
        rotulo = (lambda p: f"{MESES_CURTOS[int(p[5:7]) - 1]}/{p[:4]}") if dim == "mes" else (lambda p: data_br(p))
        lin = [[rotulo(p), int(q), float(v)] for p, q, v in g.itertuples(index=False)]
        maior = max(lin, key=lambda x: x[2])
        texto = (f"Movimentos **{'por mês' if dim == 'mes' else 'por dia'}** {rot}{filtros}: total de "
                 f"**{moeda(df['VALOR'].sum())}** em {inteiro(len(df))} movimentos. O maior foi **{maior[0]}**, "
                 f"com {moeda(maior[2])}.")
        return _resp(texto, ctx, (f"Movimentos por {'mês' if dim == 'mes' else 'dia'}", sub,
                                   ["MES" if dim == "mes" else "DATA", "QTD", "VALOR"], lin),
                     sug("por vendedor", "por tipo"))
    elif tem(t, r"\blist", r"documentos", r"notas", r"quais (os )?movimentos", r"ultimos movimentos", r"detalh"):
        cols, linhas, mais = banco.consultar(
            "SELECT M.NUMEROMOV AS DOCUMENTO, M.DATAEMISSAO AS EMISSAO, M.CODTMV AS TIPO, C.NOME AS CLIENTE, "
            "V.NOME AS VENDEDOR, M.VALORLIQUIDO AS VALOR" + _FROM_MOV + where + " ORDER BY M.DATAEMISSAO DESC, M.IDMOV DESC",
            params, ctx["limite"])
        if not linhas:
            return _resp(f"Não encontrei movimentos {rot}{filtros}.", ctx)
        tot = sum(float(r[5] or 0) for r in linhas)
        texto = (f"Encontrei **{inteiro(len(linhas))} movimentos** {rot}{filtros}, somando **{moeda(tot)}**."
                 + (" (limite de linhas atingido; refine o período)" if mais else ""))
        return _resp(texto, ctx, ("Lista de movimentos", sub, cols, linhas))
    else:
        dim = None

    if dim:
        cols, linhas, _ = banco.consultar(
            f"SELECT {col_sql} AS {col_nome}, COUNT(*) AS QTD, SUM(M.VALORLIQUIDO) AS VALOR" + _FROM_MOV + where
            + f" GROUP BY {col_sql}", params)
        linhas = sorted(([r[0] or "(vazio)", int(r[1] or 0), float(r[2] or 0)] for r in linhas), key=lambda r: -r[2])
        if not linhas:
            return _resp(f"Não encontrei movimentos {rot}{filtros}.", ctx)
        tot = sum(r[2] for r in linhas)
        top = linhas[:n]
        partes = [f"{i + 1}. **{r[0]}**: {moeda(r[2])} ({inteiro(r[1])} mov.)" for i, r in enumerate(top[:5])]
        texto = (f"{titulo} **{rot}**{filtros}. Total: **{moeda(tot)}** em {inteiro(sum(r[1] for r in linhas))} "
                 f"movimentos.\n\n" + "\n".join(partes))
        outras = {"vendedor": ("por cliente", "por tipo"), "cliente": ("por vendedor", "por tipo"),
                  "tipo": ("por vendedor", "por cliente")}[dim]
        return _resp(texto, ctx, (titulo, sub, [col_nome, "QTD", "VALOR"], top), sug(*outras, "listar"))

    # total simples
    cols, linhas, _ = banco.consultar(
        "SELECT COUNT(*) AS QTD, SUM(M.VALORLIQUIDO) AS VALOR, COUNT(DISTINCT M.CODCFO) AS CLIENTES" + _FROM_MOV + where, params)
    qtd, valor, clientes = linhas[0] if linhas else (0, 0, 0)
    if not qtd:
        return _resp(f"Não encontrei movimentos {rot}{filtros}.", ctx,
                     sugestoes=["Movimentos do mês passado", "Movimentos deste ano por mês"])
    texto = (f"**{rot[0].upper() + rot[1:]}**{filtros} foram **{inteiro(qtd)} movimentos**, somando **{moeda(valor)}** "
             f"(valor líquido), para {inteiro(clientes)} clientes/fornecedores diferentes.")
    if not informado:
        texto += " Considerei o mês atual; você pode citar outro período (ex.: \"em setembro\", \"este ano\")."
    return _resp(texto, ctx, sugestoes=sug("por vendedor", "por cliente", "por tipo", "listar"))


# ------------------------------------------------------------------ financeiro
def financeiro(ctx, t):
    if "financeiro" not in ctx["modulos"]:
        return _sem_permissao("financeiro")
    receber = not tem(t, r"\bpagar\b", r"\bpagamento", r"fornecedor", r"\bdevo\b", r"\bdevemos\b", r"despesa",
                      r"\bpag[oa]s\b", r"\bpagamos\b")
    pr, nome_tipo = ("R", "a receber") if receber else ("P", "a pagar")
    hoje = dt.date.today()
    so_vencidos = tem(t, r"vencid", r"atrasad", r"inadimpl", r"em atraso", r"devendo")
    a_vencer = tem(t, r"a vencer", r"vence(m|r)? (hoje|amanha|esta|essa|nest|ness|no|na|em|ate|os|as)", r"proxim", r"vencendo")
    baixados = tem(t, r"recebid", r"\bpag[oa]s\b", r"baixad", r"quitad", r"recebemos", r"pagamos", r"recebimentos?\b",
                   r"pagamentos (feitos|realizados)")
    ini, fim, rot, informado = periodo(t, padrao=None)
    if a_vencer and not informado:
        dias = 30
        m = re.search(r"(\d+)\s+dias", t)
        if m:
            dias = int(m.group(1))
        if tem(t, r"\bhoje\b"):
            dias = 0
        if tem(t, r"\bamanha\b"):
            ini_a = hoje + dt.timedelta(days=1)
            ini, fim, rot, informado = ini_a, ini_a, "amanhã", True
        if not informado:
            ini, fim, rot, informado = hoje, hoje + dt.timedelta(days=dias), (
                "hoje" if dias == 0 else f"nos próximos {dias} dias"), True

    sql = (servicos.SQL_FIN.replace("SELECT L.IDLAN,", "SELECT") + " AND L.PAGREC = ?")
    params = [ctx["cfg"]["empresa"], pr]
    descr = []
    col_data = "L.DATABAIXA" if baixados else "L.DATAVENCIMENTO"
    if baixados:
        sql += " AND L.STATUSLAN = 'B'"
        if not informado:
            ini, fim, rot, informado = periodo(t)
    else:
        sql += " AND L.STATUSLAN = 'A'"
    if so_vencidos and not baixados:
        sql += " AND L.DATAVENCIMENTO < ?"
        params.append(hoje)
    if informado:
        sql += f" AND {col_data} BETWEEN ? AND ?"
        params += [ini, fim]
    cli = _cfo_citado(ctx, t)
    if cli:
        w, p = _in("L.CODCFO", cli[0])
        sql += w
        params += p
        descr.append(cli[1])
    fil = _filial(t)
    if fil is not None:
        sql += " AND L.CODFILIAL = ?"
        params.append(fil)
    cols, linhas, mais = ctx["banco"].consultar(sql + f" ORDER BY {col_data}", params, max(ctx["limite"], 20000))
    df = pd.DataFrame(linhas, columns=cols)
    situacao = "recebidas" if baixados and receber else "pagas" if baixados else "vencidas" if so_vencidos else "em aberto"
    quando = f" {rot}" if informado else ""
    de_quem = f" de {descr[0]}" if descr else ""
    titulo = f"Contas {nome_tipo} {situacao}{quando}{de_quem}" + (f" (filial {fil})" if fil is not None else "")
    if df.empty:
        return _resp(f"Não há contas {nome_tipo} {situacao}{quando}{de_quem}.", ctx,
                     sugestoes=["Contas a receber vencidas", "Contas a pagar a vencer nos próximos 7 dias"])
    df["VALOR"] = pd.to_numeric(df["VALOR"], errors="coerce").fillna(0)
    df["VALOR_BAIXADO"] = pd.to_numeric(df["VALOR_BAIXADO"], errors="coerce").fillna(0)
    venc = pd.to_datetime(df["VENCIMENTO"], errors="coerce")
    atraso = (pd.Timestamp(hoje) - venc).dt.days
    df["DIAS_ATRASO"] = atraso.where(atraso > 0, 0).fillna(0).astype(int)
    df["NOME"] = df["NOME"].fillna(df["CODCFO"]).fillna("(sem nome)")
    total = float(df["VALOR_BAIXADO" if baixados else "VALOR"].sum())
    sub = (f"{titulo} · {len(df)} títulos" + (f" · vencimento de {data_br(ini)} a {data_br(fim)}" if informado and not baixados else ""))

    if tem(t, r"por cliente", r"por fornecedor", r"maiores", r"\bquem\b", r"top", r"devedor", r"agrupad", r"por nome"):
        g = df.groupby("NOME").agg(QTD=("VALOR", "size"), VALOR=("VALOR_BAIXADO" if baixados else "VALOR", "sum"),
                                   MAIOR_ATRASO=("DIAS_ATRASO", "max")).reset_index().sort_values("VALOR", ascending=False)
        n = _top(t)
        lin = [[r.NOME, int(r.QTD), float(r.VALOR), int(r.MAIOR_ATRASO)] for r in g.head(n).itertuples()]
        partes = [f"{i + 1}. **{r[0]}**: {moeda(r[2])} ({r[1]} título{'s' if r[1] > 1 else ''})" for i, r in enumerate(lin[:5])]
        texto = f"{titulo}: **{moeda(total)}** no total, de {inteiro(g.shape[0])} {'clientes' if receber else 'fornecedores'}.\n\n" + "\n".join(partes)
        return _resp(texto, ctx, (titulo + " por " + ("cliente" if receber else "fornecedor"), sub,
                                  ["NOME", "QTD", "VALOR", "MAIOR_ATRASO"], lin))

    tab = df[["DOCUMENTO", "PARCELA", "NOME", "TIPO_DOC", "EMISSAO", "VENCIMENTO", "BAIXA", "VALOR", "VALOR_BAIXADO",
              "DIAS_ATRASO"]]
    if not baixados:
        tab = tab.drop(columns=["BAIXA", "VALOR_BAIXADO"])
    else:
        tab = tab.drop(columns=["DIAS_ATRASO"])
    tab = tab.astype(object).where(pd.notna(tab), None)
    texto = f"{titulo}: **{inteiro(len(df))} títulos**, total de **{moeda(total)}**."
    if not baixados:
        vencido = float(df.loc[df["DIAS_ATRASO"] > 0, "VALOR"].sum())
        if vencido and not so_vencidos:
            texto += f" Desse total, **{moeda(vencido)}** já está vencido."
        if so_vencidos:
            texto += f" O atraso médio é de {int(round((df['DIAS_ATRASO'] * df['VALOR']).sum() / max(df['VALOR'].sum(), 0.01)))} dias (ponderado pelo valor)."
    if mais:
        texto += " (limite de linhas atingido)"
    base = f"Contas {nome_tipo}" + (f" do cliente {cli[2]}" if cli else "")
    sug = [{"rotulo": "Por cliente" if receber else "Por fornecedor",
            "pergunta": f"{base} {'vencidas' if so_vencidos else 'recebidas' if baixados and receber else 'pagas' if baixados else 'em aberto'}"
                        + (f" de {data_br(ini)} a {data_br(fim)}" if informado else "") + (" por cliente" if receber else " por fornecedor")},
           {"rotulo": "Só as vencidas", "pergunta": f"{base} vencidas"} if not so_vencidos else
           {"rotulo": "A vencer em 30 dias", "pergunta": f"{base} a vencer nos próximos 30 dias"}]
    return _resp(texto, ctx, (titulo, sub, list(tab.columns), tab.values.tolist()), sug)


# ------------------------------------------------------------------ estoque e produtos
_VALOR_EST = "S.SALDOFISICO1 * COALESCE(NULLIF(S.CUSTOMEDIO, 0), P.CUSTOMEDIO, 0)"
_FROM_EST = """
FROM TPRODSALDO S
JOIN TPRODUTO P ON P.CODPRD = S.CODPRD AND P.CODEMPRESA = S.CODEMPRESA
LEFT JOIN TLOCALEST L ON L.CODLOC = S.CODLOC AND L.CODEMPRESA = S.CODEMPRESA
LEFT JOIN TGRUPO G ON G.CODGRUPO = P.CODGRUPO AND G.CODEMPRESA = P.CODEMPRESA
WHERE S.CODEMPRESA = ?"""


def estoque(ctx, t):
    if "estoque" not in ctx["modulos"]:
        return _sem_permissao("estoque")
    b, emp = ctx["banco"], ctx["cfg"]["empresa"]
    hoje = data_br(dt.date.today())
    fil = _filial(t)
    if fil is not None:                       # filtro de filial: entra logo depois de "S.CODEMPRESA = ?"
        emp_txt = f" (filial {fil})"
        b0 = b

        class _ComFilial:
            @staticmethod
            def consultar(sql, params=(), limite=None):
                return b0.consultar(sql.replace("WHERE S.CODEMPRESA = ?", "WHERE S.CODEMPRESA = ? AND S.CODFILIAL = ?"),
                                    [params[0], fil] + list(params[1:]), limite)
        b = _ComFilial()
        hoje += emp_txt
    if tem(t, r"negativ"):
        cols, linhas, _ = b.consultar(
            "SELECT L.NOME AS NOME_LOCAL, P.NUMNOFABRIC AS COD_FABRICANTE, P.NOMEFANTASIA AS PRODUTO, "
            "S.SALDOFISICO1 AS SALDO" + _FROM_EST + " AND S.SALDOFISICO1 < 0 ORDER BY S.SALDOFISICO1", (emp,))
        if not linhas:
            return _resp("Nenhum produto com saldo negativo. 👍", ctx)
        return _resp(f"Há **{inteiro(len(linhas))} saldos negativos** no estoque.", ctx,
                     ("Saldos negativos", f"Posição de {hoje}", cols, linhas))
    if tem(t, r"por local", r"locais", r"almoxarifado", r"deposito"):
        dim, col, nome, titulo = "local", "COALESCE(L.NOME, S.CODLOC)", "LOCAL", "Estoque por local"
    elif tem(t, r"por grupo", r"grupos", r"categoria"):
        dim, col, nome, titulo = "grupo", "COALESCE(G.DESCRICAO, '(sem grupo)')", "GRUPO", "Estoque por grupo"
    elif tem(t, r"\blist", r"produtos", r"itens", r"maiores", r"top", r"materiais"):
        n = _top(t, 20)
        cols, linhas, _ = b.consultar(
            "SELECT P.NUMNOFABRIC AS COD_FABRICANTE, P.NOMEFANTASIA AS PRODUTO, P.CODUNDVENDA AS UND, "
            f"SUM(S.SALDOFISICO1) AS SALDO, SUM({_VALOR_EST}) AS VALOR_ESTOQUE" + _FROM_EST
            + " AND S.SALDOFISICO1 > 0 GROUP BY P.NUMNOFABRIC, P.NOMEFANTASIA, P.CODUNDVENDA", (emp,))
        linhas = sorted(linhas, key=lambda r: -(r[4] or 0))
        tot = sum(float(r[4] or 0) for r in linhas)
        texto = (f"Estoque em {hoje}: **{inteiro(len(linhas))} produtos** com saldo, valor total de **{moeda(tot)}** "
                 f"(saldo × custo médio). Abaixo, os {min(n, len(linhas))} de maior valor.")
        return _resp(texto, ctx, ("Produtos em estoque por valor", f"Posição de {hoje}", cols,
                                  linhas if tem(t, r"pdf|excel|planilha|xlsx|todos|completo") else linhas[:n]))
    else:
        dim = None
    if dim:
        cols, linhas, _ = b.consultar(
            f"SELECT {col} AS {nome}, COUNT(DISTINCT S.CODPRD) AS QTD, SUM({_VALOR_EST}) AS VALOR_ESTOQUE" + _FROM_EST
            + f" AND S.SALDOFISICO1 > 0 GROUP BY {col}", (emp,))
        linhas = sorted(([r[0] or "(vazio)", int(r[1] or 0), float(r[2] or 0)] for r in linhas), key=lambda r: -r[2])
        tot = sum(r[2] for r in linhas)
        partes = [f"{i + 1}. **{r[0]}**: {moeda(r[2])} ({inteiro(r[1])} produtos)" for i, r in enumerate(linhas[:5])]
        return _resp(f"{titulo} em {hoje}: total de **{moeda(tot)}**.\n\n" + "\n".join(partes), ctx,
                     (titulo, f"Posição de {hoje} · saldo × custo médio", [nome, "QTD", "VALOR_ESTOQUE"], linhas),
                     ["Estoque por " + ("grupo" if dim == "local" else "local"), "Saldos negativos"])
    cols, linhas, _ = b.consultar(
        f"SELECT COUNT(DISTINCT S.CODPRD), SUM({_VALOR_EST})" + _FROM_EST + " AND S.SALDOFISICO1 > 0", (emp,))
    qtd, valor = linhas[0]
    return _resp(f"O estoque em {hoje} vale **{moeda(valor)}** (saldo × custo médio), com **{inteiro(qtd)} produtos** "
                 "com saldo positivo.", ctx, sugestoes=["Estoque por local", "Estoque por grupo", "Saldos negativos",
                                                        "Produtos de maior valor em estoque"])


def produto(ctx, t, termos):
    if not ({"estoque", "cadastros"} & set(ctx["modulos"])):
        return _sem_permissao("estoque")
    lista = _produtos(ctx)
    cod = [x for x in lista if x[1] and norm(x[1]) in termos]
    achados = cod or _achar(lista, termos, 3)
    if not achados:
        return _resp(f"Não encontrei produto com \"{' '.join(termos)}\". Tente o código do fabricante ou outra "
                     "parte da descrição.", ctx)
    b, emp = ctx["banco"], ctx["cfg"]["empresa"]
    if len(achados) > 1:
        ids = [a[0] for a in achados[:300]]
        cols, linhas, _ = b.consultar(
            "SELECT P.NUMNOFABRIC AS COD_FABRICANTE, P.NOMEFANTASIA AS PRODUTO, P.CODUNDVENDA AS UND, "
            "P.SALDOGERALFISICO AS SALDO, P.PRECO1 AS PRECO, P.CUSTOMEDIO AS CUSTO_MEDIO FROM TPRODUTO P "
            f"WHERE P.CODEMPRESA = ? AND P.CODPRD IN ({','.join('?' * len(ids))}) ORDER BY P.NOMEFANTASIA", [emp] + ids)
        texto = f"Encontrei **{inteiro(len(achados))} produtos** com \"{' '.join(termos)}\"."
        if len(achados) > 300:
            texto += " Mostrando os 300 primeiros; seja mais específico."
        return _resp(texto, ctx, (f"Produtos: {' '.join(termos)}", "", cols, linhas),
                     [{"rotulo": f"{r[0]} {r[1]}"[:40], "pergunta": f"Saldo do produto {r[0]}"} for r in linhas[:5] if r[0]])
    codprd = achados[0][0]
    cols, linhas, _ = b.consultar(
        "SELECT P.NUMNOFABRIC, P.NOMEFANTASIA, P.CODUNDVENDA, P.PRECO1, P.CUSTOMEDIO, P.SALDOGERALFISICO, "
        "G.DESCRICAO, P.CODCLASSFISCAL FROM TPRODUTO P LEFT JOIN TGRUPO G ON G.CODGRUPO = P.CODGRUPO "
        "AND G.CODEMPRESA = P.CODEMPRESA WHERE P.CODEMPRESA = ? AND P.CODPRD = ?", (emp, codprd))
    fab, desc, und, preco, custo, saldo, grupo, ncm = linhas[0]
    cols, locais, _ = b.consultar(
        "SELECT COALESCE(L.NOME, S.CODLOC) AS NOME_LOCAL, S.SALDOFISICO1 AS SALDO FROM TPRODSALDO S "
        "LEFT JOIN TLOCALEST L ON L.CODLOC = S.CODLOC AND L.CODEMPRESA = S.CODEMPRESA "
        "WHERE S.CODEMPRESA = ? AND S.CODPRD = ? AND S.SALDOFISICO1 <> 0 ORDER BY 2 DESC", (emp, codprd))
    num = lambda v: f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")
    texto = (f"**{fab} · {desc}** ({und or 'sem unidade'})\n\n"
             f"- Saldo geral: **{num(saldo)} {und or ''}**\n- Preço: {moeda(preco)} · Custo médio: {moeda(custo)}\n"
             f"- Grupo: {grupo or '-'} · NCM: {ncm or '-'}")
    if locais:
        texto += "\n\nSaldo por local de estoque:"
        return _resp(texto, ctx, (f"Saldo por local: {fab} {desc}", "", cols, locais))
    return _resp(texto + "\n\nSem saldo em nenhum local.", ctx)


# ------------------------------------------------------------------ clientes / fornecedores
def ficha(ctx, t, termos):
    if "cadastros" not in ctx["modulos"]:
        return _sem_permissao("cadastros")
    achados = _achar(_cfos(ctx), termos)
    cod = [x for x in _cfos(ctx) if norm(x[0]) in termos]
    achados = cod or achados
    if not achados:
        return _resp(f"Não encontrei cliente/fornecedor com \"{' '.join(termos)}\".", ctx)
    b, emp = ctx["banco"], ctx["cfg"]["empresa"]
    if len(achados) > 1:
        lin = [[a[0], a[1]] for a in achados[:100]]
        return _resp(f"Encontrei **{len(achados)}** cadastros com \"{' '.join(termos)}\". Qual deles? "
                     "Pergunte de novo com o nome mais completo ou o código.", ctx,
                     (f"Clientes/fornecedores: {' '.join(termos)}", "", ["CODIGO", "NOME"], lin),
                     [{"rotulo": a[1][:40], "pergunta": f"Dados do cliente {a[0]}"} for a in achados[:6]])
    codcfo = achados[0][0]
    cols, linhas, _ = b.consultar(servicos.SQL_CLI + " AND C.CODCFO = ?", (emp, codcfo))
    d = dict(zip(cols, linhas[0]))
    tipo = {"C": "Cliente", "F": "Fornecedor", "A": "Cliente e fornecedor"}.get((d.get("TIPO") or "").strip(), d.get("TIPO") or "")
    texto = (f"**{d['NOME']}** (código {d['CODIGO']}) · {tipo}\n\n"
             f"- CPF/CNPJ: {d.get('CPF_CNPJ') or '-'}\n- Cidade: {d.get('CIDADE') or '-'}/{d.get('UF') or '-'}\n"
             f"- Telefone: {d.get('TELEFONE') or '-'} · E-mail: {d.get('EMAIL') or '-'}")
    if d.get("ULTIMA_VENDA"):
        texto += f"\n- Última venda: {data_br(d['ULTIMA_VENDA'])}"
    if "financeiro" in ctx["modulos"]:
        _, fin, _ = b.consultar(
            "SELECT L.PAGREC, SUM(L.VALORORIGINAL), SUM(CASE WHEN L.DATAVENCIMENTO < ? THEN L.VALORORIGINAL ELSE 0 END) "
            "FROM FLAN L WHERE L.CODEMPRESA = ? AND L.CODCFO = ? AND L.STATUSLAN = 'A' GROUP BY L.PAGREC",
            (dt.date.today(), emp, codcfo))
        for pr, aberto, vencido in fin:
            texto += (f"\n- {'A receber' if pr == 'R' else 'A pagar'} em aberto: **{moeda(aberto)}**"
                      + (f" ({moeda(vencido)} vencido)" if vencido else ""))
    sug = [{"rotulo": "Movimentos no ano", "pergunta": f"Movimentos do cliente {codcfo} este ano por tipo"}] \
        if "movimentos" in ctx["modulos"] else []
    if "financeiro" in ctx["modulos"]:
        sug += [{"rotulo": "Contas a receber", "pergunta": f"Contas a receber do cliente {codcfo}"},
                {"rotulo": "Contas a pagar", "pergunta": f"Contas a pagar do cliente {codcfo}"}]
    return _resp(texto, ctx, sugestoes=sug)


# ------------------------------------------------------------------ resumo e ajuda
def resumo(ctx):
    if "inicio" not in ctx["modulos"]:
        return _sem_permissao("inicio")
    d = servicos.inicio(ctx["banco"], ctx["cfg"], ctx["tipos"], "resumo")
    k = d["kpis"]
    ini = dt.date.fromisoformat(d["periodo"][0])
    texto = (f"Resumo de **{MESES[ini.month - 1]}/{ini.year}**:\n\n"
             f"- A receber em aberto no mês: **{moeda(k['receber_aberto'])}** ({moeda(k['receber_vencido'])} vencido)\n"
             f"- A pagar em aberto no mês: **{moeda(k['pagar_aberto'])}** ({moeda(k['pagar_vencido'])} vencido)\n"
             f"- Movimentos no mês: **{inteiro(k['mov_mes'])}**, somando {moeda(k['mov_mes_valor'])}\n"
             f"- Valor em estoque hoje: **{moeda(k['estoque_valor'])}**")
    return _resp(texto, ctx, sugestoes=["Contas a receber vencidas", "Movimentos por vendedor", "Estoque por local"])


EXEMPLOS = [
    ("inicio", "Resumo do mês"),
    ("movimentos", "Movimentos deste mês por vendedor"),
    ("movimentos", "Top 10 clientes do ano"),
    ("movimentos", "Movimentos por mês"),
    ("movimentos", "Movimentos por tipo em setembro"),
    ("movimentos", "Listar movimentos de ontem"),
    ("financeiro", "Contas a receber vencidas"),
    ("financeiro", "Contas a pagar dos próximos 7 dias"),
    ("financeiro", "Maiores devedores"),
    ("estoque", "Estoque por local"),
    ("estoque", "Saldos negativos"),
    ("estoque", "Saldo do produto cabo flex 6mm"),
    ("cadastros", "Dados do cliente Construtora Horizonte"),
]


def exemplos(modulos, n=None):
    ex = [e for m, e in EXEMPLOS if m in modulos]
    return ex[:n] if n else ex


# tópicos da tela do chat: perguntas prontas por assunto. Terminando em "…" o texto vai para a caixa de
# digitação para o usuário completar (nome do cliente, do produto etc.).
TOPICOS = [
    ("inicio", "Resumo", [
        "Resumo do mês", "Como estamos?",
    ]),
    ("movimentos", "Movimentos", [
        "Movimentos de hoje", "Movimentos deste mês", "Movimentos do mês passado", "Movimentos deste ano por mês",
        "Movimentos por vendedor este mês", "Movimentos por tipo este mês", "Movimentos por dia nesta semana",
        "Top 10 clientes do ano", "Listar movimentos de ontem", "Movimentos cancelados este mês",
        "Compras deste mês por fornecedor", "Movimentos dos últimos 30 dias por cliente",
        "Movimentos do vendedor …", "Movimentos deste ano do cliente …",
    ]),
    ("financeiro", "Financeiro", [
        "Contas a receber em aberto", "Contas a receber vencidas", "Contas a pagar em aberto", "Contas a pagar vencidas",
        "Contas a pagar que vencem hoje", "Contas a pagar dos próximos 7 dias", "Contas a receber dos próximos 30 dias",
        "Maiores devedores", "Contas a pagar em aberto por fornecedor", "Contas recebidas este mês",
        "Contas pagas no mês passado", "Contas a receber do cliente …",
    ]),
    ("estoque", "Estoque", [
        "Valor total do estoque", "Estoque por local", "Estoque por grupo", "Saldos negativos",
        "Top 20 produtos de maior valor em estoque", "Estoque por local em Excel",
    ]),
    ("estoque", "Produtos", [
        "Saldo do produto …", "Preço do produto …", "Produto …",
    ]),
    ("cadastros", "Clientes", [
        "Dados do cliente …", "Telefone do cliente …", "Dados do fornecedor …",
    ]),
]


def topicos(modulos):
    vistos = []
    for mod, nome, perguntas in TOPICOS:
        if mod in modulos or (nome == "Produtos" and "cadastros" in modulos):
            if not any(v["nome"] == nome for v in vistos):
                vistos.append({"nome": nome, "perguntas": [{"texto": p.rstrip("…").strip() + (" " if p.endswith("…") else ""),
                                                            "rotulo": p, "completar": p.endswith("…")} for p in perguntas]})
    return vistos


def parecidas(t, modulos, n=4):
    """Perguntas prontas mais parecidas com o que o usuário escreveu (para "você quis dizer")."""
    palavras = set(_termos_simples(t))
    if not palavras:
        return []
    notas = []
    for tp in topicos(modulos):
        for q in tp["perguntas"]:
            if q["completar"]:
                continue
            alvo = set(_termos_simples(norm(q["texto"])))
            comum = len(palavras & alvo)
            if comum:
                notas.append((comum / len(alvo | palavras) + difflib.SequenceMatcher(None, t, norm(q["texto"])).ratio() * .3,
                              q["texto"]))
    notas.sort(reverse=True)
    return [x for _, x in notas[:n]]


_LIGACAO = {"a", "o", "as", "os", "de", "do", "da", "dos", "das", "e", "em", "no", "na", "por", "para", "com", "que", "me", "eu"}


def _termos_simples(t):
    return [p for p in re.findall(r"[a-z0-9]+", t) if p not in _LIGACAO and len(p) > 1]


def ajuda(ctx, entendeu=True, entendeu_t=""):
    ex = exemplos(ctx["modulos"])
    texto = ("Sou o assistente do painel. Respondo perguntas prontas sobre os dados do Puma e gero PDF/Excel "
             "das tabelas (é só pedir \"em PDF\" ou \"em Excel\", ou usar os botões abaixo de cada tabela).\n\n"
             "**Posso responder sobre:**\n"
             "- Movimentos: total, por vendedor, por cliente, por tipo, por mês ou lista, em qualquer período "
             "(hoje, ontem, esta semana, mês passado, setembro, 2025, últimos 30 dias, 01/09 a 15/09)\n"
             "- Financeiro: contas a receber e a pagar em aberto, vencidas, a vencer, recebidas/pagas, por cliente\n"
             "- Estoque: valor total, por local, por grupo, saldos negativos, produtos de maior valor\n"
             "- Produto: saldo, preço e locais de um produto (pelo código ou pela descrição)\n"
             "- Cliente/fornecedor: dados de contato e valores em aberto\n\n"
             "Dá para filtrar por filial (ex.: \"contas a receber vencidas da filial 2\").\n\n"
             "Escolha um assunto abaixo para ver as perguntas prontas.")
    if not entendeu:
        perto = parecidas(entendeu_t, ctx["modulos"]) if entendeu_t else []
        texto = ("Não entendi bem a pergunta. " + ("Você quis dizer uma destas?" if perto else
                 "Tente usar palavras como **movimentos**, **vendedor**, **cliente**, **contas a receber/pagar**, "
                 "**vencidas**, **estoque**, **produto** e um período (ex.: \"este mês\", \"em setembro\").")
                 + "\n\nVocê também pode tocar em **Tópicos**, no alto do chat, para ver as perguntas prontas por assunto.")
        return Resposta(texto=texto, sugestoes=(perto or ex[:6]) + [{"rotulo": "Ver tópicos", "pergunta": "topicos"}])
    r = Resposta(texto=texto, sugestoes=ex[:8])
    r["topicos"] = topicos(ctx["modulos"])
    return r


# ------------------------------------------------------------------ roteador
def responder(pergunta, ctx):
    """ctx: banco, cfg, bid, uid, modulos, tipos (restrição de tipos de movimento), limite."""
    t = norm(pergunta)[:500]
    if not t:
        return ajuda(ctx)
    if tem(t, r"^(topicos?|assuntos?|menu|perguntas prontas|o que posso perguntar)$"):
        return ajuda(ctx)
    t = preparar(t, _protegidas(ctx))
    ctx = {**ctx, "formato": _formato(t)}
    if tem(t, r"^(oi|ola|bom dia|boa tarde|boa noite|ajuda|help|menu|\?)\b", r"o que (voce|vc) (faz|sabe)",
           r"como (funciona|usar|uso)", r"^ajud"):
        return ajuda(ctx)
    if tem(t, r"\bresumo\b", r"visao geral", r"como (estamos|esta|estao)", r"indicadores", r"\bkpis?\b"):
        return resumo(ctx)
    if tem(t, r"^(obrigad[oa]|valeu|ok|certo|beleza|blz|show)\b"):
        return Resposta(texto="Por nada! Se precisar, é só perguntar. 🙂", sugestoes=exemplos(ctx["modulos"], 4))
    if tem(t, r"receber", r"\bpagar\b", r"\bcontas?\b", r"financeiro", r"titulos?", r"vencid", r"inadimpl", r"devedor", r"atrasad",
           r"boleto", r"duplicata", r"a vencer", r"vencendo", r"\bdevendo\b", r"recebid", r"lancamento", r"recebemos",
           r"pagamos", r"recebimento", r"\bpagos?\b", r"\bpagas?\b"):
        return financeiro(ctx, t)
    if tem(t, r"saldos? negativ", r"\bestoque\b", r"inventario", r"almoxarifado") and not tem(t, r"produto\s+\S", r"saldo d[oa]s?\s+(?!estoque)\S"):
        return estoque(ctx, t)
    m = re.search(r"(?:produto|material|item|codigo|saldo|preco|estoque)\s+(?:d[oa]s?\s+)?(?:produto\s+|material\s+)?(.{2,80})", t)
    if m and not tem(t, r"movimento", r"vendedor", r"por cliente"):
        termos = _termos(m.group(1))
        if termos:
            return produto(ctx, t, termos)
    m = re.search(r"(?:dados|ficha|contato|telefone|e-?mail|endereco|cnpj|cpf|cadastro)\s+(?:d[oa]s?\s+)?(?:cliente|fornecedor)?\s*(.{2,80})", t) \
        or re.search(r"^(?:quem e (?:o|a)\s+)?(?:cliente|fornecedor)\s+(.{2,80})$", t)
    if m and not tem(t, r"moviment", r"vend[ai]", r"\bpor\b"):
        termos = _termos(m.group(1))
        if termos:
            return ficha(ctx, t, termos)
    if tem(t, r"moviment", r"vend[ai]", r"faturament", r"\bcompras?\b", r"notas?\b", r"documentos?", r"pedidos?",
           r"vendedor", r"funcionari", r"\bclientes\b", r"por tipo", r"por mes", r"mensal", r"saida", r"entrada",
           r"cancelad", r"\d\.\d", r"movimentaram", r"movimentamos"):
        return movimentos(ctx, t)
    return ajuda(ctx, entendeu=False, entendeu_t=t)


def _protegidas(ctx):
    """Palavras dos nomes do banco (clientes, vendedores, produtos): não são 'corrigidas' como erro de digitação."""
    def ler():
        pal = set()
        for fn in (_vendedores, _cfos, _produtos):
            try:
                for x in fn(ctx):
                    pal.update(re.findall(r"[a-z]{4,}", x[-1]))
            except Exception:              # sem acesso ou tabela diferente: segue sem proteger
                pass
        return frozenset(pal - set(_VOCABULARIO))
    return _em_cache(f"{ctx['bid']}:protegidas", 300, ler)
