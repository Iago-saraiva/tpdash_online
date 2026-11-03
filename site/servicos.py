"""Consultas do painel. O SQL é escrito de forma portável (Firebird e SQLite de demonstração):
sem FIRST/ROWS (o limite é aplicado no fetch) e agregações por mês feitas no pandas."""
import datetime as dt

import pandas as pd

from db import ErroBanco

HOJE = dt.date.today


def _df(banco, sql, params=(), limite=None):
    cols, linhas, mais = banco.consultar(sql, params, limite)
    df = pd.DataFrame(linhas, columns=cols)
    df.attrs["mais"] = mais
    return df


def _data(txt, padrao):
    if not txt:
        return padrao
    try:
        return dt.date.fromisoformat(txt[:10])
    except ValueError:
        raise ErroBanco(f"Data inválida: {txt}")


def _lista(txt):
    return [x.strip() for x in (txt or "").split(",") if x.strip()]


def _num(df, *cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _registros(df):
    df = df.astype(object).where(pd.notna(df), None)
    return {"colunas": list(df.columns), "linhas": df.values.tolist()}


def _agrupar(df, chave, valor, n=None, contagem=False, ordem_valor=True, outros=True):
    if df.empty:
        return []
    g = df.groupby(chave, dropna=False)
    s = g.size() if contagem else g[valor].sum()
    s = s.sort_values(ascending=False) if ordem_valor else s.sort_index()
    if n and len(s) > n:
        resto = s.iloc[n:].sum()
        s = s.iloc[:n]
        if outros:
            s.loc["Outros"] = resto
    return [{"rotulo": str(k if k is not None else "(vazio)"), "valor": float(v)} for k, v in s.items()]


def _por_mes(df, col_data, col_valor, ini=None, fim=None, contagem=False):
    if df.empty:
        return []
    d = pd.to_datetime(df[col_data], errors="coerce")
    tmp = pd.DataFrame({"mes": d.dt.strftime("%Y-%m"), "v": 1 if contagem else df[col_valor]})
    s = tmp.groupby("mes")["v"].sum()
    if ini and fim:
        meses = pd.period_range(ini, fim, freq="M").strftime("%Y-%m")
        s = s.reindex(meses, fill_value=0)
    return [{"rotulo": k, "valor": float(v)} for k, v in s.items()]


# ======================================================================== opções
def opcoes(banco, cfg):
    emp = cfg["empresa"]
    tipos = _df(banco, "SELECT CODTIPOMOV AS COD, NOME FROM TTIPOMOV WHERE CODEMPRESA = ? ORDER BY CODTIPOMOV", (emp,))
    vend = _df(banco, "SELECT CODVEN AS COD, NOME FROM TVENDEDOR WHERE CODEMPRESA = ? ORDER BY NOME", (emp,))
    locais = _df(banco, "SELECT CODLOC AS COD, NOME FROM TLOCALEST WHERE CODEMPRESA = ? ORDER BY CODLOC", (emp,))
    grupos = _df(banco, "SELECT CODGRUPO AS COD, DESCRICAO AS NOME FROM TGRUPO WHERE CODEMPRESA = ? ORDER BY DESCRICAO", (emp,))
    filiais = _df(banco, "SELECT CODFILIAL AS COD, NOMEFANTASIA AS NOME FROM GFILIAL WHERE CODEMPRESA = ? ORDER BY CODFILIAL", (emp,))
    tipos_doc = _df(banco, "SELECT CODTIPODOC AS COD, DESCRICAO AS NOME FROM FTIPODOC WHERE CODEMPRESA = ? ORDER BY CODTIPODOC", (emp,))
    ccustos = _df(banco, "SELECT COD, DESCRICAO AS NOME FROM FCCUSTO WHERE CODEMPRESA = ? ORDER BY COD", (emp,))
    deptos = _df(banco, "SELECT CODDEPARTAMENTO AS COD, NOME FROM GDEPARTAMENTO WHERE CODEMPRESA = ? ORDER BY CODDEPARTAMENTO", (emp,))
    f = lambda d: [{"cod": str(r.COD).strip(), "nome": (r.NOME or "").strip()} for r in d.itertuples()]
    return {
        "tipos": f(tipos), "vendedores": f(vend), "locais": f(locais), "grupos": f(grupos), "filiais": f(filiais), "tipos_doc": f(tipos_doc),
        "ccustos": f(ccustos), "departamentos": f(deptos),
        "status_movimento": cfg["status_movimento"], "status_lancamento": cfg["status_lancamento"],
    }


# ======================================================================== movimentos
SQL_MOV = """
SELECT M.IDMOV, M.NUMEROMOV AS DOCUMENTO, M.CODTMV, T.NOME AS TIPO, M.DATAEMISSAO AS EMISSAO,
       M.STATUS, M.CODCFO, C.NOME AS CLIENTE, M.CODVEN1 AS CODVEN, V.NOME AS VENDEDOR,
       M.CODFILIAL AS FILIAL, M.VALORLIQUIDO AS VALOR, M.VALORBRUTO AS VALOR_BRUTO,
       M.CODCCUSTO AS CCUSTO, CC.DESCRICAO AS NOME_CCUSTO, M.CODDEPARTAMENTO, DP.NOME AS NOME_DEPARTAMENTO
FROM TMOV M
LEFT JOIN TTIPOMOV T ON T.CODTIPOMOV = M.CODTMV AND T.CODEMPRESA = M.CODEMPRESA
LEFT JOIN FCFO C ON C.CODCFO = M.CODCFO AND C.CODEMPRESA = M.CODEMPRESA
LEFT JOIN TVENDEDOR V ON V.CODVEN = M.CODVEN1 AND V.CODEMPRESA = M.CODEMPRESA
LEFT JOIN FCCUSTO CC ON CC.COD = M.CODCCUSTO AND CC.CODEMPRESA = M.CODEMPRESA
LEFT JOIN GDEPARTAMENTO DP ON DP.CODDEPARTAMENTO = M.CODDEPARTAMENTO AND DP.CODEMPRESA = M.CODEMPRESA
WHERE M.CODEMPRESA = ? AND M.DATAEMISSAO BETWEEN ? AND ?
"""


def _cod_nome(c, n):
    c = c.strip() if isinstance(c, str) else ""
    n = n.strip() if isinstance(n, str) else ""
    return f"{c} - {n}" if c and n else c or n


def _cc_depto(df, col_cc="CCUSTO", col_dep="CODDEPARTAMENTO"):
    """Colunas legíveis 'código - nome' do centro de custo e do departamento."""
    df["CENTRO_CUSTO"] = [_cod_nome(c, n) for c, n in zip(df[col_cc], df["NOME_CCUSTO"])]
    df["DEPARTAMENTO"] = [_cod_nome(c, n) for c, n in zip(df[col_dep], df["NOME_DEPARTAMENTO"])]
    return df


def filtro_tipos(perm, col="M.CODTMV"):
    """Restrição de tipos de movimento do usuário: lista de códigos exatos e prefixos ("2.2.*").
    Lista vazia = sem restrição. Devolve (trecho SQL, parâmetros)."""
    if not perm:
        return "", []
    exatos = [t for t in perm if not t.endswith("*")]
    prefixos = [t[:-1] for t in perm if t.endswith("*")]
    partes, params = [], []
    if exatos:
        partes.append(f"{col} IN ({','.join('?' * len(exatos))})")
        params += exatos
    for p in prefixos:
        partes.append(f"{col} STARTING WITH ?")
        params.append(p)
    return " AND (" + " OR ".join(partes) + ")", params


def tipo_permitido(perm, codtmv):
    if not perm:
        return True
    c = (codtmv or "").strip()
    return any(c == t or (t.endswith("*") and c.startswith(t[:-1])) for t in perm)


def _filial(a):
    """Código da filial escolhida no filtro (None = todas)."""
    try:
        return int(str((a or {}).get("filial") or "").strip())
    except ValueError:
        return None


PERIODO_PADRAO_DIAS = 60      # período padrão das telas Movimentos e Financeiro (últimos 60 dias)


def _filtros_mov(a, cfg):
    hoje = HOJE()
    ini = _data(a.get("ini"), hoje - dt.timedelta(days=PERIODO_PADRAO_DIAS - 1))
    fim = _data(a.get("fim"), hoje)
    where, params = "", [cfg["empresa"], ini, fim]
    tipos = _lista(a.get("tipos"))
    if tipos:
        where += f" AND M.CODTMV IN ({','.join('?' * len(tipos))})"
        params += tipos
    if a.get("prefixo"):
        where += " AND M.CODTMV STARTING WITH ?"
        params.append(a["prefixo"].strip())
    if a.get("vendedor"):
        where += " AND (M.CODVEN1 = ? OR M.CODVEN2 = ?)"
        params += [a["vendedor"], a["vendedor"]]
    if a.get("cliente"):
        txt = a["cliente"].strip()
        where += " AND (M.CODCFO = ? OR UPPER(C.NOME) LIKE ?)"
        params += [txt, f"%{txt.upper()}%"]
    if a.get("status"):
        st = _lista(a["status"])
        where += f" AND M.STATUS IN ({','.join('?' * len(st))})"
        params += st
    elif a.get("cancelados") == "so":          # apenas cancelados
        where += " AND M.STATUS = 'C'"
    elif a.get("cancelados") != "1":
        where += " AND (M.STATUS IS NULL OR M.STATUS <> 'C')"
    if _filial(a) is not None:
        where += " AND M.CODFILIAL = ?"
        params.append(_filial(a))
    if a.get("doc"):
        where += " AND M.IDMOV = ?"
        params.append(int(a["doc"]))
    if a.get("codcfo"):                       # código exato (ficha do cliente)
        where += " AND M.CODCFO = ?"
        params.append(a["codcfo"])
    ccustos = _lista(a.get("ccusto"))[:100]   # centros de custo, com os subcentros
    if ccustos:
        w, p = _filtro_rateado("CCUSTO", ccustos, True, "M", "CODCCUSTO", "IDMOV", "M")
        where += w
        params += p
    deptos = _lista(a.get("depto"))[:100]
    if deptos:
        w, p = _filtro_rateado("CODDEPARTAMENTO", deptos, False, "M", "CODDEPARTAMENTO", "IDMOV", "M")
        where += w
        params += p
    w, p = filtro_tipos(a.get("_tipos_perm"))
    return ini, fim, where + w, params + p


def movimentos(banco, cfg, a, limite):
    ini, fim, where, params = _filtros_mov(a, cfg)
    df = _df(banco, SQL_MOV + where + " ORDER BY M.DATAEMISSAO DESC, M.IDMOV DESC", params, limite)
    _num(df, "VALOR", "VALOR_BRUTO")
    st = cfg["status_movimento"]
    df["STATUS"] = df["STATUS"].map(lambda s: st.get(s, s) if s else "")
    df["TIPO_ROT"] = df["CODTMV"].fillna("") + " " + df["TIPO"].fillna("")
    df["CLIENTE_ROT"] = df["CLIENTE"].fillna(df["CODCFO"]).fillna("(sem cliente)")
    df["VENDEDOR_ROT"] = df["VENDEDOR"].fillna(df["CODVEN"]).fillna("(sem vendedor)")
    kpis = {
        "qtd": int(len(df)),
        "valor": float(df["VALOR"].sum()),
        "bruto": float(df["VALOR_BRUTO"].sum()),           # soma do valor bruto dos movimentos do filtro
        "clientes": int(df["CODCFO"].nunique()),
    }
    _cc_depto(df)
    tabela = df[["IDMOV", "DOCUMENTO", "EMISSAO", "CODTMV", "TIPO", "STATUS", "CODCFO", "CLIENTE", "VENDEDOR", "CENTRO_CUSTO",
                 "DEPARTAMENTO", "VALOR"]]
    return {
        "periodo": [ini.isoformat(), fim.isoformat()],
        "kpis": kpis,
        "por_mes": _por_mes(df, "EMISSAO", "VALOR", ini, fim),
        "qtd_mes": _por_mes(df, "EMISSAO", "VALOR", ini, fim, contagem=True),
        "por_tipo": _agrupar(df, "TIPO_ROT", "VALOR", 10, contagem=True),
        "por_categoria": _agrupar_categoria(df, "CODTMV", categorias(banco, cfg), 10),
        "top_clientes": _agrupar(df, "CLIENTE_ROT", "VALOR", 10, outros=False),
        "top_vendedores": _agrupar(df, "VENDEDOR_ROT", "VALOR", 10, outros=False),
        "tabela": _registros(tabela),
        "truncado": df.attrs["mais"],
    }


SQL_ITENS = """
SELECT I.IDMOV, I.NSEQ AS SEQ, P.NUMNOFABRIC AS COD_FABRICANTE, P.NOMEFANTASIA AS MATERIAL, I.CODUND AS UND,
       I.QUANTIDADE AS QTD, I.PRECOUNITARIO AS VLR_UNIT, I.VALORTOTALITEM AS TOTAL
FROM TMOVITENS I
LEFT JOIN TPRODUTO P ON P.CODPRD = I.CODPRD AND P.CODEMPRESA = I.CODEMPRESA
WHERE I.CODEMPRESA = ? AND I.IDMOV = ?
ORDER BY I.NSEQ
"""


def itens_movimento(banco, cfg, idmov, perm=None):
    cab = _df(banco, SQL_MOV.replace("AND M.DATAEMISSAO BETWEEN ? AND ?", "") + " AND M.IDMOV = ?", (cfg["empresa"], int(idmov)))
    if cab.empty or not tipo_permitido(perm, cab["CODTMV"].iloc[0]):
        return {"cabecalho": {"colunas": [], "linhas": []}, "itens": {"colunas": [], "linhas": []}}
    df = _df(banco, SQL_ITENS, (cfg["empresa"], int(idmov)))
    _num(df, "QTD", "VLR_UNIT", "TOTAL")
    st = cfg["status_movimento"]
    if not cab.empty:
        cab["STATUS"] = cab["STATUS"].map(lambda s: st.get(s, s) if s else "")
        _cc_depto(cab)
    return {"cabecalho": _registros(cab), "itens": _registros(df.drop(columns=["IDMOV"]))}


def movimentos_com_itens(banco, cfg, a, limite):
    """Para o relatório 'documento por documento': cabeçalhos + itens."""
    ini, fim, where, params = _filtros_mov(a, cfg)
    sql = f"""
    SELECT M.IDMOV, M.NUMEROMOV AS DOCUMENTO, M.DATAEMISSAO AS EMISSAO, M.CODTMV, T.NOME AS TIPO,
           M.CODCFO, C.NOME AS CLIENTE, V.NOME AS VENDEDOR, M.STATUS, M.VALORLIQUIDO AS VALOR_DOC,
           I.NSEQ AS SEQ, P.NUMNOFABRIC AS COD_FABRICANTE, I.CODPRD AS CODPRD_INT, P.NOMEFANTASIA AS MATERIAL, I.CODUND AS UND,
           I.QUANTIDADE AS QTD, I.PRECOUNITARIO AS VLR_UNIT, I.VALORTOTALITEM AS TOTAL
    FROM TMOV M
    LEFT JOIN TTIPOMOV T ON T.CODTIPOMOV = M.CODTMV AND T.CODEMPRESA = M.CODEMPRESA
    LEFT JOIN FCFO C ON C.CODCFO = M.CODCFO AND C.CODEMPRESA = M.CODEMPRESA
    LEFT JOIN TVENDEDOR V ON V.CODVEN = M.CODVEN1 AND V.CODEMPRESA = M.CODEMPRESA
    LEFT JOIN TMOVITENS I ON I.IDMOV = M.IDMOV AND I.CODEMPRESA = M.CODEMPRESA
    LEFT JOIN TPRODUTO P ON P.CODPRD = I.CODPRD AND P.CODEMPRESA = I.CODEMPRESA
    WHERE M.CODEMPRESA = ? AND M.DATAEMISSAO BETWEEN ? AND ? {where}
    ORDER BY M.DATAEMISSAO, M.NUMEROMOV, I.NSEQ
    """
    df = _df(banco, sql, params, limite)
    _num(df, "VALOR_DOC", "QTD", "VLR_UNIT", "TOTAL")
    st = cfg["status_movimento"]
    df["STATUS"] = df["STATUS"].map(lambda s: st.get(s, s) if s else "")
    return ini, fim, df


# ======================================================================== estoque
SQL_ESTOQUE = """
SELECT S.CODLOC, L.NOME AS NOME_LOCAL, P.NUMNOFABRIC AS COD_FABRICANTE, P.CODPRD AS CODPRD_INT, P.NOMEFANTASIA AS PRODUTO, P.CODUNDVENDA AS UND,
       G.DESCRICAO AS GRUPO, S.SALDOFISICO1 AS SALDO,
       COALESCE(NULLIF(S.CUSTOMEDIO, 0), P.CUSTOMEDIO, 0) AS CUSTO_MEDIO, P.PRECO1 AS PRECO,
       P.CODCLASSFISCAL AS NCM, P.CODCEST AS CEST, P.CODSIT AS SIT_D, S1.DESCRICAO AS DESC_D,
       P.CODSIT2 AS SIT_F, S2.DESCRICAO AS DESC_F, P.ORIGEMMERCADORIA AS ORIG, P.CST_PISCOFINS
FROM TPRODSALDO S
JOIN TPRODUTO P ON P.CODPRD = S.CODPRD AND P.CODEMPRESA = S.CODEMPRESA
LEFT JOIN TLOCALEST L ON L.CODLOC = S.CODLOC AND L.CODEMPRESA = S.CODEMPRESA
LEFT JOIN TGRUPO G ON G.CODGRUPO = P.CODGRUPO AND G.CODEMPRESA = P.CODEMPRESA
LEFT JOIN TSTRIBUTARIA S1 ON S1.CODSIT = P.CODSIT AND S1.CODEMPRESA = P.CODEMPRESA
LEFT JOIN TSTRIBUTARIA S2 ON S2.CODSIT = P.CODSIT2 AND S2.CODEMPRESA = P.CODEMPRESA
WHERE S.CODEMPRESA = ? AND S.SALDOFISICO1 <> 0
"""


ORIGENS = {
    0: "Nacional", 1: "Estrangeira - importação direta", 2: "Estrangeira - adquirida no mercado interno",
    3: "Nacional - conteúdo importado > 40% e <= 70%", 4: "Nacional - processos produtivos básicos",
    5: "Nacional - conteúdo importado <= 40%", 6: "Estrangeira - importação direta, sem similar nacional",
    7: "Estrangeira - mercado interno, sem similar nacional", 8: "Nacional - conteúdo importado > 70%",
}


def _fiscal(df):
    """Monta as colunas de tributação: situação dentro/fora do estado (código - descrição) e origem."""
    def sit(cod, desc):
        cod = cod.strip() if isinstance(cod, str) else cod
        if not cod:
            return ""
        return f"{cod} - {desc.strip()}" if isinstance(desc, str) and desc.strip() else cod
    df["SIT_DENTRO"] = [sit(c, d) for c, d in zip(df["SIT_D"], df["DESC_D"])]
    df["SIT_FORA"] = [sit(c, d) for c, d in zip(df["SIT_F"], df["DESC_F"])]

    def orig(v):
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            return ""
        return f"{v} - {ORIGENS.get(v, '')}".rstrip(" -")
    df["ORIGEM"] = df["ORIG"].map(orig)
    for c in ("NCM", "CEST", "CST_PISCOFINS"):
        df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)


def estoque(banco, cfg, a, limite):
    sql, params = SQL_ESTOQUE, [cfg["empresa"]]
    locais = _lista(a.get("local"))
    if locais:
        sql += f" AND S.CODLOC IN ({','.join('?' * len(locais))})"
        params += locais
    if a.get("grupo"):
        sql += " AND P.CODGRUPO = ?"
        params.append(a["grupo"])
    if a.get("busca"):
        txt = a["busca"].strip()
        sql += " AND (P.NUMNOFABRIC = ? OR P.CODPRD = ? OR UPPER(P.NOMEFANTASIA) LIKE ?)"
        params += [txt, txt, f"%{txt.upper()}%"]
    if a.get("negativos") == "1":
        sql += " AND S.SALDOFISICO1 < 0"
    if _filial(a) is not None:
        sql += " AND S.CODFILIAL = ?"
        params.append(_filial(a))
    df = _df(banco, sql + " ORDER BY P.NOMEFANTASIA, S.CODLOC", params, max(limite, 20000))
    _num(df, "SALDO", "CUSTO_MEDIO", "PRECO")
    df["VALOR_ESTOQUE"] = (df["SALDO"] * df["CUSTO_MEDIO"]).round(2)
    _fiscal(df)
    df["LOCAL_ROT"] = df["CODLOC"].fillna("") + " " + df["NOME_LOCAL"].fillna("")
    df["GRUPO"] = df["GRUPO"].fillna("(sem grupo)")
    pos = df[df["SALDO"] > 0]
    kpis = {
        "valor": float(pos["VALOR_ESTOQUE"].sum()),
        "itens": int(df["CODPRD_INT"].nunique()),
        "negativos": int((df["SALDO"] < 0).sum()),
        "sem_custo": int(((df["SALDO"] > 0) & (df["CUSTO_MEDIO"] <= 0)).sum()),
    }
    agg = (pos.groupby(["CODPRD_INT", "COD_FABRICANTE", "PRODUTO"], dropna=False)
           .agg(valor=("VALOR_ESTOQUE", "sum"), qtd=("SALDO", "sum"), und=("UND", "first"), preco=("PRECO", "max")))
    top = agg.sort_values("valor", ascending=False).head(10)
    top_q = agg.sort_values("qtd", ascending=False).head(10)

    def _lista_top(tb, campo):
        return [{"rotulo": f"{c or ''} {(p or '')[:40]}".strip() + (f" ({x.und})" if campo == "qtd" and x.und else ""),
                 "codigo": c or "", "produto": p or "",
                 "valor": float(x.valor) if campo == "valor" else float(x.qtd),
                 "valor_estoque": float(x.valor), "qtd": float(x.qtd), "und": x.und or "",
                 "unitario": float(x.valor / x.qtd) if x.qtd else 0.0,
                 "preco": float(x.preco) if x.preco == x.preco else 0.0}
                for (_, c, p), x in tb.iterrows()]
    tabela = df[["CODLOC", "NOME_LOCAL", "COD_FABRICANTE", "PRODUTO", "UND", "GRUPO", "SALDO", "CUSTO_MEDIO", "VALOR_ESTOQUE", "PRECO",
                 "NCM", "CEST", "SIT_DENTRO", "SIT_FORA", "ORIGEM", "CST_PISCOFINS"]]
    return {
        "kpis": kpis,
        "por_local": _agrupar(pos, "LOCAL_ROT", "VALOR_ESTOQUE", 12),
        "por_grupo": _agrupar(pos, "GRUPO", "VALOR_ESTOQUE", 10),
        # mesmas visões pela quantidade (soma dos saldos)
        "por_local_qtd": _agrupar(pos, "LOCAL_ROT", "SALDO", 12),
        "por_grupo_qtd": _agrupar(pos, "GRUPO", "SALDO", 10),
        "top_produtos": _lista_top(top, "valor"),
        "top_produtos_qtd": _lista_top(top_q, "qtd"),
        "tabela": _registros(tabela.head(limite)),
        "truncado": len(tabela) > limite,
    }


# ======================================================================== movimentações por produto
# O Puma grava em cada item (TMOVITENS.FLAGEFEITOSALDO) o efeito do movimento nos saldos do produto.
# A 1ª letra é o saldo físico: A = aumenta (entrada), D = diminui (saída), N = não mexe no estoque.
_ENTRADA = "I.FLAGEFEITOSALDO LIKE 'A%'"
_SAIDA = "I.FLAGEFEITOSALDO LIKE 'D%'"
_MEXE = f"({_ENTRADA} OR {_SAIDA})"
_NAO_MEXE = f"(I.FLAGEFEITOSALDO IS NULL OR NOT {_MEXE})"


def _aba_estoque(a):
    return (a or {}).get("aba") != "sem"


def _where_itens(cfg, a, com_periodo=True):
    """WHERE comum dos itens: empresa, efeito no estoque, sem cancelados, filial, período e tipos liberados."""
    where = f" WHERE I.CODEMPRESA = ? AND (M.STATUS IS NULL OR M.STATUS <> 'C') AND {_MEXE if _aba_estoque(a) else _NAO_MEXE}"
    params = [cfg["empresa"]]
    if _filial(a) is not None:
        where += " AND M.CODFILIAL = ?"
        params.append(_filial(a))
    if com_periodo and a.get("ini"):
        where += " AND M.DATAEMISSAO >= ?"
        params.append(_data(a["ini"], None))
    if com_periodo and a.get("fim"):
        where += " AND M.DATAEMISSAO < ?"
        params.append(_data(a["fim"], None) + dt.timedelta(days=1))
    w, p = filtro_tipos(a.get("_tipos_perm"))
    return where + w, params + p


SQL_MOV_PRODUTOS = """
SELECT P.CODPRD AS CODPRD_INT, P.NUMNOFABRIC AS COD_FABRICANTE, P.NOMEFANTASIA AS PRODUTO, P.CODUNDVENDA AS UND,
       G.DESCRICAO AS GRUPO, P.SALDOGERALFISICO AS SALDO
FROM TPRODUTO P
LEFT JOIN TGRUPO G ON G.CODGRUPO = P.CODGRUPO AND G.CODEMPRESA = P.CODEMPRESA
WHERE P.CODEMPRESA = ?
"""


def movimentacoes(banco, cfg, a, limite):
    """Lista de produtos com o resumo dos movimentos que mexem (ou não) no estoque."""
    estoque_ = _aba_estoque(a)
    sql, params = SQL_MOV_PRODUTOS, [cfg["empresa"]]
    if a.get("inativos") != "1":
        sql += " AND (P.INATIVO IS NULL OR P.INATIVO <> 'T')"
    if a.get("grupo"):
        sql += " AND P.CODGRUPO = ?"
        params.append(a["grupo"])
    if a.get("busca"):
        t = a["busca"].strip()
        sql += " AND (P.NUMNOFABRIC = ? OR P.CODPRD = ? OR UPPER(P.NOMEFANTASIA) LIKE ?)"
        params += [t, t, f"%{t.upper()}%"]
    prod = _df(banco, sql + " ORDER BY P.NOMEFANTASIA", params, max(limite, 50000))
    _num(prod, "SALDO")
    if _filial(a) is not None:                  # saldo só da filial escolhida
        s = _df(banco, "SELECT S.CODPRD, SUM(S.SALDOFISICO1) AS SALDO FROM TPRODSALDO S WHERE S.CODEMPRESA = ? AND S.CODFILIAL = ? "
                       "GROUP BY S.CODPRD", (cfg["empresa"], _filial(a)))
        _num(s, "SALDO")
        prod["SALDO"] = prod["CODPRD_INT"].map(dict(zip(s["CODPRD"], s["SALDO"]))).fillna(0.0)

    where, p2 = _where_itens(cfg, a)
    if estoque_:
        cols = (f"SUM(CASE WHEN {_ENTRADA} THEN 1 ELSE 0 END) AS N_ENT, SUM(CASE WHEN {_SAIDA} THEN 1 ELSE 0 END) AS N_SAI, "
                f"SUM(CASE WHEN {_ENTRADA} THEN I.QUANTIDADE ELSE 0 END) AS ENTRADAS, "
                f"SUM(CASE WHEN {_SAIDA} THEN I.QUANTIDADE ELSE 0 END) AS SAIDAS")
    else:
        cols = "SUM(I.QUANTIDADE) AS QTD_TOTAL, SUM(I.VALORTOTALITEM) AS VALOR"
    agg = _df(banco, f"""SELECT I.CODPRD, COUNT(*) AS MOVIMENTOS, {cols}, MAX(M.DATAEMISSAO) AS ULTIMO
        FROM TMOVITENS I JOIN TMOV M ON M.IDMOV = I.IDMOV AND M.CODEMPRESA = I.CODEMPRESA {where}
        GROUP BY I.CODPRD""", p2)
    num = ["MOVIMENTOS", "N_ENT", "N_SAI", "ENTRADAS", "SAIDAS"] if estoque_ else ["MOVIMENTOS", "QTD_TOTAL", "VALOR"]
    _num(agg, *num)
    df = prod.merge(agg.rename(columns={"CODPRD": "CODPRD_INT"}), on="CODPRD_INT", how="left")
    for c in num:
        df[c] = df[c].fillna(0.0)
    df["MOVIMENTOS"] = df["MOVIMENTOS"].astype(int)
    df["GRUPO"] = df["GRUPO"].fillna("(sem grupo)")
    if a.get("com_mov") == "1":
        df = df[df["MOVIMENTOS"] > 0]
    kpis = {"produtos": int(len(df)), "com_mov": int((df["MOVIMENTOS"] > 0).sum()), "lancamentos": int(df["MOVIMENTOS"].sum())}
    if estoque_:
        df["N_ENT"] = df["N_ENT"].astype(int)
        df["N_SAI"] = df["N_SAI"].astype(int)
        kpis.update(entradas=int(df["N_ENT"].sum()), saidas=int(df["N_SAI"].sum()))
        tabela = df[["CODPRD_INT", "COD_FABRICANTE", "PRODUTO", "UND", "GRUPO", "SALDO", "ENTRADAS", "SAIDAS", "MOVIMENTOS", "ULTIMO"]]
        totais = [["Total de entradas", float(df["ENTRADAS"].sum()), "qtd"], ["Total de saídas", float(df["SAIDAS"].sum()), "qtd"]]
    else:
        kpis.update(valor=float(df["VALOR"].sum()))
        tabela = df[["CODPRD_INT", "COD_FABRICANTE", "PRODUTO", "UND", "GRUPO", "SALDO", "MOVIMENTOS", "QTD_TOTAL", "VALOR", "ULTIMO"]]
        totais = [["Quantidade total", float(df["QTD_TOTAL"].sum()), "qtd"], ["Valor total", float(df["VALOR"].sum()), "moeda"]]
    totais.append(["Saldo atual do estoque", float(df["SALDO"].sum()), "qtd"])
    if df["UND"].nunique() > 1:
        totais.append(["Obs.", "as quantidades somam produtos de unidades diferentes (UN, M, PC...)", "texto"])
    return {"aba": "estoque" if estoque_ else "sem", "kpis": kpis, "totais": totais,
            "tabela": _registros(tabela.head(max(limite, 50000))), "truncado": len(tabela) > max(limite, 50000)}


def movimentacoes_produto(banco, cfg, codprd, a, limite):
    """Movimentos de um produto. Na aba de estoque calcula o saldo depois de cada movimento."""
    estoque_ = _aba_estoque(a)
    p = _df(banco, "SELECT P.CODPRD, P.NUMNOFABRIC, P.NOMEFANTASIA, P.CODUNDVENDA, P.SALDOGERALFISICO FROM TPRODUTO P "
                   "WHERE P.CODEMPRESA = ? AND P.CODPRD = ?", (cfg["empresa"], codprd))
    if p.empty:
        raise ErroBanco("Produto não encontrado.")
    # na aba de estoque busca tudo (sem período) para o saldo acumulado começar do primeiro movimento
    where, params = _where_itens(cfg, a, com_periodo=not estoque_)
    sql = f"""
    SELECT M.IDMOV, M.DATAEMISSAO AS EMISSAO, M.NUMEROMOV AS DOCUMENTO, M.CODTMV, T.NOME AS TIPO, M.STATUS,
           M.CODCFO, C.NOME AS CLIENTE, M.CODFILIAL AS FILIAL, I.NSEQ, I.CODUND AS UND, I.QUANTIDADE AS QTD,
           I.PRECOUNITARIO AS VLR_UNIT, I.VALORTOTALITEM AS TOTAL, I.FLAGEFEITOSALDO AS FLAG
    FROM TMOVITENS I
    JOIN TMOV M ON M.IDMOV = I.IDMOV AND M.CODEMPRESA = I.CODEMPRESA
    LEFT JOIN TTIPOMOV T ON T.CODTIPOMOV = M.CODTMV AND T.CODEMPRESA = M.CODEMPRESA
    LEFT JOIN FCFO C ON C.CODCFO = M.CODCFO AND C.CODEMPRESA = M.CODEMPRESA
    {where} AND I.CODPRD = ?
    ORDER BY M.DATAEMISSAO, M.IDMOV, I.NSEQ
    """
    df = _df(banco, sql, params + [codprd], max(limite, 50000))
    mais = df.attrs["mais"]
    _num(df, "QTD", "VLR_UNIT", "TOTAL")
    st = cfg["status_movimento"]
    df["STATUS"] = df["STATUS"].map(lambda s: st.get(s, s) if s else "")
    df["TIPO"] = (df["CODTMV"].fillna("") + " " + df["TIPO"].fillna("")).str.strip()
    df["CLIENTE"] = df["CLIENTE"].fillna(df["CODCFO"]).fillna("")
    info = {"codprd": str(p["CODPRD"].iloc[0]).strip(), "fabricante": p["NUMNOFABRIC"].iloc[0] or "",
            "nome": (p["NOMEFANTASIA"].iloc[0] or "").strip(), "und": p["CODUNDVENDA"].iloc[0] or ""}
    resumo = {"lancamentos": 0}
    # saldo físico atual do produto (só da filial, se escolhida)
    if _filial(a) is not None:
        s = _df(banco, "SELECT SUM(S.SALDOFISICO1) AS SALDO FROM TPRODSALDO S WHERE S.CODEMPRESA = ? AND S.CODPRD = ? AND S.CODFILIAL = ?",
                (cfg["empresa"], codprd, _filial(a)))
    else:
        s = p.rename(columns={"SALDOGERALFISICO": "SALDO"})
    _num(s, "SALDO")
    atual = float(s["SALDO"].iloc[0]) if len(s) else 0.0
    if estoque_:
        ent = df["FLAG"].fillna("").str.startswith("A")
        df["MOVIMENTO"] = ent.map({True: "Entrada", False: "Saída"})
        df["ENTRADA"] = df["QTD"].where(ent, 0.0)
        df["SAIDA"] = df["QTD"].where(~ent, 0.0)
        acum = (df["ENTRADA"] - df["SAIDA"]).cumsum()
        # o saldo de cada linha parte do saldo atual do produto (ou da filial) e volta no tempo; assim a última
        # linha bate com o Estoque, e o que veio de fora dos movimentos (implantação/ajuste) fica como saldo inicial
        ajuste = 0.0
        if not a.get("_tipos_perm"):
            ajuste = round(atual - (float(acum.iloc[-1]) if len(acum) else 0.0), 6)
        df["SALDO"] = (acum + ajuste).round(6)
        d_emissao = pd.to_datetime(df["EMISSAO"], errors="coerce")
        antes = pd.Series(False, index=df.index)
        if a.get("ini"):
            antes = d_emissao < pd.Timestamp(_data(a["ini"], None))
        depois = pd.Series(False, index=df.index)
        if a.get("fim"):
            depois = d_emissao >= pd.Timestamp(_data(a["fim"], None) + dt.timedelta(days=1))
        anterior = float(df.loc[antes, "SALDO"].iloc[-1]) if antes.any() else ajuste
        df = df[~antes & ~depois]
        resumo.update(saldo_anterior=anterior, entradas=float(df["ENTRADA"].sum()), saidas=float(df["SAIDA"].sum()),
                      saldo_final=float(df["SALDO"].iloc[-1]) if len(df) else anterior, lancamentos=int(len(df)))
        cols = ["IDMOV", "EMISSAO", "DOCUMENTO", "TIPO", "CLIENTE", "FILIAL", "MOVIMENTO", "UND", "ENTRADA", "SAIDA", "SALDO"]
        totais = [["Saldo antes do período" if a.get("ini") else "Saldo inicial", resumo["saldo_anterior"], "qtd"],
                  ["Total de entradas", resumo["entradas"], "qtd"], ["Total de saídas", resumo["saidas"], "qtd"]]
        if a.get("fim"):
            totais.append(["Saldo no fim do período", resumo["saldo_final"], "qtd"])
    else:
        resumo.update(qtd=float(df["QTD"].sum()), valor=float(df["TOTAL"].sum()), lancamentos=int(len(df)))
        cols = ["IDMOV", "EMISSAO", "DOCUMENTO", "TIPO", "STATUS", "CLIENTE", "FILIAL", "UND", "QTD", "VLR_UNIT", "TOTAL"]
        totais = [["Quantidade total", resumo["qtd"], "qtd"], ["Valor total", resumo["valor"], "moeda"]]
    resumo["saldo_atual"] = atual
    totais.append(["Saldo atual do estoque", atual, "qtd"])
    tabela = df[cols].iloc[::-1]                 # mais recente primeiro
    return {"aba": "estoque" if estoque_ else "sem", "produto": info, "resumo": resumo, "totais": totais,
            "tabela": _registros(tabela), "truncado": mais}


# ======================================================================== financeiro
SQL_FIN = """
SELECT L.IDLAN, L.PAGREC, L.STATUSLAN AS STATUS, L.NUMERODOCUMENTO AS DOCUMENTO, L.PARCELA,
       L.CODCFO, C.NOME AS NOME, L.CODTDO, D.DESCRICAO AS TIPO_DOC, L.DATAEMISSAO AS EMISSAO,
       L.DATAVENCIMENTO AS VENCIMENTO, L.DATABAIXA AS BAIXA, L.VALORORIGINAL AS VALOR,
       L.VALORBAIXADO AS VALOR_BAIXADO, L.HISTORICO
FROM FLAN L
LEFT JOIN FCFO C ON C.CODCFO = L.CODCFO AND C.CODEMPRESA = L.CODEMPRESA
LEFT JOIN FTIPODOC D ON D.CODTIPODOC = L.CODTDO AND D.CODEMPRESA = L.CODEMPRESA
WHERE L.CODEMPRESA = ?
"""
_BASES = {"vencimento": "L.DATAVENCIMENTO", "emissao": "L.DATAEMISSAO", "baixa": "L.DATABAIXA"}

# tela Financeiro: os mesmos títulos com o centro de custo e o departamento de cada um
SQL_FIN_CC = SQL_FIN.replace("       L.VALORBAIXADO AS VALOR_BAIXADO, L.HISTORICO\n", """       L.VALORBAIXADO AS VALOR_BAIXADO, L.HISTORICO, L.CCUSTO, CC.DESCRICAO AS NOME_CCUSTO,
       L.CODDEPARTAMENTO, DP.NOME AS NOME_DEPARTAMENTO
""").replace("WHERE L.CODEMPRESA = ?", """LEFT JOIN FCCUSTO CC ON CC.COD = L.CCUSTO AND CC.CODEMPRESA = L.CODEMPRESA
LEFT JOIN GDEPARTAMENTO DP ON DP.CODDEPARTAMENTO = L.CODDEPARTAMENTO AND DP.CODEMPRESA = L.CODEMPRESA
WHERE L.CODEMPRESA = ?""")
assert "CC.DESCRICAO" in SQL_FIN_CC and "LEFT JOIN FCCUSTO" in SQL_FIN_CC


def _filtro_rateado(col, codigos, hierarquia, alias="L", col_principal=None, col_id="IDLAN", origem="L"):
    """Registro entra se o centro de custo/departamento dele ou do rateio (FLANRATCCUSTO; origem L = título do
    financeiro, M = movimento) for um dos escolhidos. Com hierarquia, escolher 2.02 também traz 2.02.001 etc."""
    def cond(c):
        partes, params = [], []
        for cod in codigos:
            if hierarquia:
                partes.append(f"({c} = ? OR {c} STARTING WITH ?)")
                params += [cod, cod + "."]
            else:
                partes.append(f"{c} = ?")
                params.append(cod)
        return "(" + " OR ".join(partes) + ")", params
    c1, p1 = cond(f"{alias}.{col_principal or col}")
    c2, p2 = cond(f"R.{col}")
    sql = (f" AND ({c1} OR EXISTS (SELECT 1 FROM FLANRATCCUSTO R WHERE R.CODEMPRESA = {alias}.CODEMPRESA"
           f" AND R.IDLAN = {alias}.{col_id} AND R.ORIGEM = '{origem}' AND {c2}))")
    return sql, p1 + p2


def financeiro(banco, cfg, a, limite):
    hoje = HOJE()
    base = a.get("base", "vencimento")
    col = _BASES.get(base, "L.DATAVENCIMENTO")
    ini = _data(a.get("ini"), hoje - dt.timedelta(days=PERIODO_PADRAO_DIAS - 1))
    fim = _data(a.get("fim"), hoje)
    sql, params = SQL_FIN_CC + f" AND {col} BETWEEN ? AND ?", [cfg["empresa"], ini, fim]
    tipo = a.get("tipo", "R")
    if tipo in ("P", "R"):
        sql += " AND L.PAGREC = ?"
        params.append(tipo)
    status = _lista(a.get("status")) or ["A"]
    if status != ["*"]:
        sql += f" AND L.STATUSLAN IN ({','.join('?' * len(status))})"
        params += status
    tipos_doc = _lista(a.get("tipodoc"))[:100]          # um ou mais tipos de documento (FTIPODOC)
    if tipos_doc:
        sql += f" AND L.CODTDO IN ({','.join('?' * len(tipos_doc))})"
        params += tipos_doc
    ccustos = _lista(a.get("ccusto"))[:100]             # centros de custo (FCCUSTO), com os subcentros
    if ccustos:
        w, p = _filtro_rateado("CCUSTO", ccustos, True)
        sql += w
        params += p
    deptos = _lista(a.get("depto"))[:100]               # departamentos (GDEPARTAMENTO)
    if deptos:
        w, p = _filtro_rateado("CODDEPARTAMENTO", deptos, False)
        sql += w
        params += p
    if a.get("cliente"):
        txt = a["cliente"].strip()
        sql += " AND (L.CODCFO = ? OR UPPER(C.NOME) LIKE ?)"
        params += [txt, f"%{txt.upper()}%"]
    if _filial(a) is not None:
        sql += " AND L.CODFILIAL = ?"
        params.append(_filial(a))
    df = _df(banco, sql + f" ORDER BY {col}, L.IDLAN", params, max(limite, 20000))
    _num(df, "VALOR", "VALOR_BAIXADO")
    venc = pd.to_datetime(df["VENCIMENTO"], errors="coerce")
    aberto = df["STATUS"] == "A"
    dias = (pd.Timestamp(hoje) - venc).dt.days
    df["DIAS_ATRASO"] = dias.where(aberto & (dias > 0), 0).fillna(0).astype(int)
    stl = cfg["status_lancamento"]
    df["SITUACAO"] = df["STATUS"].map(lambda s: stl.get(s, s) if s else "")
    df["TIPO"] = df["PAGREC"].map({"P": "A pagar", "R": "A receber"}).fillna("")

    def faixa(d, ab):
        if not ab:
            return None
        if d <= 0:
            return "A vencer"
        if d <= 30:
            return "1-30 dias"
        if d <= 60:
            return "31-60 dias"
        if d <= 90:
            return "61-90 dias"
        return "Mais de 90"

    df["FAIXA"] = [faixa(d, ab) for d, ab in zip(df["DIAS_ATRASO"], aberto)]
    ordem = ["A vencer", "1-30 dias", "31-60 dias", "61-90 dias", "Mais de 90"]
    ab = df[aberto]
    aging = ab.groupby("FAIXA")["VALOR"].sum().reindex(ordem, fill_value=0)
    ab_valor = ab["VALOR"]
    kpis = {
        "total": float(df["VALOR"].sum()),
        "qtd": int(len(df)),
        "aberto": float(ab_valor.sum()),
        "vencido": float(ab.loc[ab["DIAS_ATRASO"] > 0, "VALOR"].sum()),
        "a_vencer_30": float(ab.loc[(venc[aberto] >= pd.Timestamp(hoje)) & (venc[aberto] <= pd.Timestamp(hoje + dt.timedelta(days=30))), "VALOR"].sum()),
        "baixado": float(df["VALOR_BAIXADO"].sum()),
    }
    por_mes_col = {"vencimento": "VENCIMENTO", "emissao": "EMISSAO", "baixa": "BAIXA"}[base if base in _BASES else "vencimento"]
    serie = []
    for pr, rot in (("R", "A receber"), ("P", "A pagar")):
        sub = df[df["PAGREC"] == pr]
        if tipo in ("P", "R") and pr != tipo:
            continue
        serie.append({"nome": rot, "pontos": _por_mes(sub, por_mes_col, "VALOR", ini, fim)})
    df["NOME_ROT"] = df["NOME"].fillna(df["CODCFO"])
    _cc_depto(df)
    tabela = df[["IDLAN", "TIPO", "SITUACAO", "DOCUMENTO", "PARCELA", "CODCFO", "NOME", "TIPO_DOC", "CENTRO_CUSTO", "DEPARTAMENTO",
                 "EMISSAO", "VENCIMENTO", "BAIXA", "VALOR", "VALOR_BAIXADO", "DIAS_ATRASO", "HISTORICO"]]
    return {
        "periodo": [ini.isoformat(), fim.isoformat()],
        "kpis": kpis,
        "aging": [{"rotulo": k, "valor": float(v)} for k, v in aging.items()],
        "por_mes": serie,
        "top_nomes": _agrupar(df, "NOME_ROT", "VALOR", 10, outros=False),
        "tabela": _registros(tabela.head(limite)),
        "truncado": len(tabela) > limite,
    }


# ======================================================================== cadastros
SQL_CLI = """
SELECT C.CODCFO AS CODIGO, C.NOME, C.NOMEFANTASIA AS FANTASIA, C.TIPO, C.PESSOAFISJUR AS PESSOA,
       C.CGCCFO AS CPF_CNPJ, C.CIDADE, C.CODETD AS UF, C.TELEFONE, C.EMAIL, C.ATIVO,
       C.DATACRIACAO AS CADASTRO, C.DATAULTVENDA AS ULTIMA_VENDA, C.LIMITECREDITO AS LIMITE
FROM FCFO C WHERE C.CODEMPRESA = ?
"""


# ======================================================================== frotas (abastecimento e manutenção)
TMV_MANUTENCAO = "1.2.39"     # Rateio Manutenção de Veículos e Máquinas
TMV_COMBUSTIVEL = "1.2.40"    # Rateio Combustível / Lubrificante


def _where_frota(cfg, a):
    hoje = HOJE()
    ini = _data(a.get("ini"), dt.date(hoje.year, hoje.month, 1) - dt.timedelta(days=334))
    fim = _data(a.get("fim"), hoje)
    where = (" WHERE M.CODEMPRESA = ? AND M.CODTMV IN (?, ?) AND (M.STATUS IS NULL OR M.STATUS <> 'C')"
             " AND M.DATAEMISSAO BETWEEN ? AND ?")
    params = [cfg["empresa"], TMV_MANUTENCAO, TMV_COMBUSTIVEL, ini, fim]
    if a.get("maquina"):
        where += " AND M.CODMAQUINA = ?"
        params.append(a["maquina"])
    if a.get("grupo"):
        where += " AND A.CODGRUPO = ?"
        params.append(a["grupo"])
    if _filial(a) is not None:
        where += " AND M.CODFILIAL = ?"
        params.append(_filial(a))
    if a.get("busca"):
        t = a["busca"].strip().upper()
        where += " AND (UPPER(M.CODMAQUINA) LIKE ? OR UPPER(A.PLACA) LIKE ? OR UPPER(A.NOME) LIKE ?)"
        params += [f"%{t}%"] * 3
    w, p = filtro_tipos(a.get("_tipos_perm"))
    return ini, fim, where + w, params + p


_FROM_FROTA = """
FROM TMOV M
LEFT JOIN AMAQUINAS A ON A.CODIGO = M.CODMAQUINA AND A.CODEMPRESA = M.CODEMPRESA
LEFT JOIN AMAQUINASGRUPO G ON G.CODIGO = A.CODGRUPO AND G.CODEMPRESA = A.CODEMPRESA
LEFT JOIN FCFO C ON C.CODCFO = M.CODCFO AND C.CODEMPRESA = M.CODEMPRESA
"""


def _frota_dados(banco, cfg, a, limite):
    ini, fim, where, params = _where_frota(cfg, a)
    docs = _df(banco, "SELECT M.IDMOV, M.CODTMV, M.NUMEROMOV AS DOCUMENTO, M.DATAEMISSAO AS EMISSAO, M.CODMAQUINA, "
                      "A.PLACA, A.NOME AS DESCRICAO, A.CODGRUPO, G.NOME AS GRUPO, M.KM, M.VALORLIQUIDO AS VALOR, "
                      "M.CODCFO, C.NOME AS FORNECEDOR" + _FROM_FROTA + where, params, max(limite, 50000))
    itens = _df(banco, "SELECT I.IDMOV, P.NOMEFANTASIA AS PRODUTO, I.CODUND AS UND, I.QUANTIDADE AS QTD, I.VALORTOTALITEM AS TOTAL"
                       + _FROM_FROTA.replace("FROM TMOV M", "FROM TMOVITENS I\nJOIN TMOV M ON M.IDMOV = I.IDMOV AND M.CODEMPRESA = I.CODEMPRESA")
                       + LEFT_PROD + where, params, max(limite, 100000))
    _num(docs, "KM", "VALOR")
    _num(itens, "QTD", "TOTAL")
    docs["TIPO"] = docs["CODTMV"].map({TMV_MANUTENCAO: "Manutenção", TMV_COMBUSTIVEL: "Abastecimento"}).fillna(docs["CODTMV"])
    # litros de combustível: itens em litro do movimento de combustível, fora ARLA (aditivo)
    prod = itens["PRODUTO"].fillna("").str.upper()
    und = itens["UND"].fillna("").str.upper().str.strip()
    itens["LITROS"] = itens["QTD"].where(und.isin(["L", "LT", "LTS", "LITRO", "LITROS"]) & ~prod.str.contains("ARLA"), 0.0)
    comb = set(docs.loc[docs["CODTMV"] == TMV_COMBUSTIVEL, "IDMOV"])
    itens.loc[~itens["IDMOV"].isin(comb), "LITROS"] = 0.0
    itens["VALOR_LITROS"] = itens["TOTAL"].where(itens["LITROS"] > 0, 0.0)

    itens["DESC"] = [f"{_t(p)} {_fmt_qtd(q)} {_t(u)}".strip()
                     for p, q, u in zip(itens["PRODUTO"], itens["QTD"], itens["UND"])]
    por_doc = itens.groupby("IDMOV").agg(LITROS=("LITROS", "sum"), VALOR_LITROS=("VALOR_LITROS", "sum"), ITENS=("DESC", "; ".join))
    docs = docs.merge(por_doc, left_on="IDMOV", right_index=True, how="left")
    docs["LITROS"] = pd.to_numeric(docs["LITROS"], errors="coerce").fillna(0.0)
    docs["VALOR_LITROS"] = pd.to_numeric(docs["VALOR_LITROS"], errors="coerce").fillna(0.0)
    docs["ITENS"] = docs["ITENS"].fillna("")
    docs["MAQUINA"] = [f"{_t(p) or _t(c)} - {_t(n)}".strip(" -") for c, p, n in
                       zip(docs["CODMAQUINA"], docs["PLACA"], docs["DESCRICAO"])]
    docs.attrs["mais"] = docs.attrs.get("mais", False)
    return ini, fim, docs, itens


LEFT_PROD = "LEFT JOIN TPRODUTO P ON P.CODPRD = I.CODPRD AND P.CODEMPRESA = I.CODEMPRESA\n"


def _t(v):
    """Texto limpo; None/NaN viram ''."""
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()


def _fmt_qtd(q):
    try:
        q = float(q)
    except (TypeError, ValueError):
        return ""
    s = f"{q:,.3f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def frotas(banco, cfg, a, limite):
    ini, fim, docs, itens = _frota_dados(banco, cfg, a, limite)
    ab = docs[docs["CODTMV"] == TMV_COMBUSTIVEL]
    mt = docs[docs["CODTMV"] == TMV_MANUTENCAO]
    litros = float(ab["LITROS"].sum())
    kpis = {"total": float(docs["VALOR"].sum()), "combustivel": float(ab["VALOR"].sum()), "litros": litros,
            "preco_litro": float(ab["VALOR_LITROS"].sum() / litros) if litros else 0.0,
            "manutencao": float(mt["VALOR"].sum()), "maquinas": int(docs["CODMAQUINA"].nunique()),
            "abastecimentos": int(len(ab)), "manutencoes": int(len(mt))}

    # por máquina
    linhas = []
    for cod, g in docs.groupby("CODMAQUINA", dropna=False):
        gab, gmt = g[g["CODTMV"] == TMV_COMBUSTIVEL], g[g["CODTMV"] == TMV_MANUTENCAO]
        lit = float(gab["LITROS"].sum())
        km = g.loc[g["KM"] > 0, "KM"]
        km_ini, km_fim = (float(km.min()), float(km.max())) if len(km) else (None, None)
        rodado = (km_fim - km_ini) if km_ini is not None else None
        # média: km rodados ÷ litros, sem o 1º abastecimento (ele cobre o trecho anterior ao período)
        gk = gab[gab["KM"] > 0].sort_values(["EMISSAO", "KM"])
        lit_media = float(gk["LITROS"].iloc[1:].sum()) if len(gk) > 1 else 0.0
        km_l = round(rodado / lit_media, 2) if rodado and lit_media else None
        if km_l is not None and not (0.3 <= km_l <= 40):
            km_l = None                       # KM digitado errado: não mostra média
        r0 = g.iloc[0]
        linhas.append({
            "CODMAQUINA": cod, "PLACA": r0["PLACA"], "DESCRICAO": r0["DESCRICAO"], "GRUPO": r0["GRUPO"],
            "ABASTECIMENTOS": int(len(gab)), "LITROS": lit, "VALOR_COMBUSTIVEL": float(gab["VALOR"].sum()),
            "PRECO_LITRO": round(float(gab["VALOR_LITROS"].sum()) / lit, 3) if lit else None,
            "MANUTENCOES": int(len(gmt)), "VALOR_MANUTENCAO": float(gmt["VALOR"].sum()),
            "VALOR_TOTAL": float(g["VALOR"].sum()), "KM_INICIAL": km_ini, "KM_FINAL": km_fim, "KM_RODADO": rodado,
            "KM_POR_LITRO": km_l, "ULTIMO": g["EMISSAO"].max(),
        })
    por_maq = pd.DataFrame(linhas, columns=["CODMAQUINA", "PLACA", "DESCRICAO", "GRUPO", "ABASTECIMENTOS", "LITROS", "VALOR_COMBUSTIVEL",
                                            "PRECO_LITRO", "MANUTENCOES", "VALOR_MANUTENCAO", "VALOR_TOTAL", "KM_INICIAL", "KM_FINAL",
                                            "KM_RODADO", "KM_POR_LITRO", "ULTIMO"])
    por_maq = por_maq.sort_values("VALOR_TOTAL", ascending=False)
    por_maq["ROT"] = [f"{_t(p) or _t(c)} {_t(d)[:28]}".strip() for c, p, d in zip(por_maq["CODMAQUINA"], por_maq["PLACA"], por_maq["DESCRICAO"])]
    top = por_maq.head(10)
    # combustível por produto
    it_ab = itens[itens["IDMOV"].isin(set(ab["IDMOV"]))]
    serie = [{"nome": "Abastecimento", "pontos": _por_mes(ab, "EMISSAO", "VALOR", ini, fim)},
             {"nome": "Manutenção", "pontos": _por_mes(mt, "EMISSAO", "VALOR", ini, fim)}]
    if ab.empty:
        serie[0]["pontos"] = [{"rotulo": p["rotulo"], "valor": 0.0} for p in serie[1]["pontos"]]
    if mt.empty:
        serie[1]["pontos"] = [{"rotulo": p["rotulo"], "valor": 0.0} for p in serie[0]["pontos"]]
    lanc = docs.sort_values(["EMISSAO", "IDMOV"], ascending=False)[
        ["IDMOV", "EMISSAO", "TIPO", "DOCUMENTO", "CODMAQUINA", "PLACA", "DESCRICAO", "KM", "FORNECEDOR", "ITENS", "LITROS", "VALOR"]]
    tabela = por_maq.drop(columns=["ROT"])
    if a.get("ver") == "lancamentos":            # exportação da lista de lançamentos
        tabela = lanc
    maqs = _df(banco, "SELECT CODIGO AS COD, PLACA, NOME FROM AMAQUINAS WHERE CODEMPRESA = ? ORDER BY NOME", (cfg["empresa"],))
    grupos = _df(banco, "SELECT CODIGO AS COD, NOME FROM AMAQUINASGRUPO WHERE CODEMPRESA = ? ORDER BY NOME", (cfg["empresa"],))
    return {
        "periodo": [ini.isoformat(), fim.isoformat()],
        "maquinas": [{"cod": str(r.COD).strip(), "nome": " ".join(x for x in [_t(r.PLACA), _t(r.NOME)] if x)}
                     for r in maqs.itertuples()],
        "grupos": [{"cod": str(r.COD).strip(), "nome": _t(r.NOME)} for r in grupos.itertuples()],
        "kpis": kpis,
        "por_mes": serie if (len(ab) or len(mt)) else [],
        "top_maquinas": [{"rotulo": r, "valor": float(v), "codigo": c} for r, v, c in zip(top["ROT"], top["VALOR_TOTAL"], top["CODMAQUINA"])],
        "por_produto": _agrupar(it_ab.assign(PRODUTO=it_ab["PRODUTO"].fillna("(sem produto)")), "PRODUTO", "TOTAL", 8),
        "tabela": _registros(tabela),
        "totais": [["Abastecimentos", kpis["abastecimentos"], "qtd"], ["Litros", litros, "qtd"],
                   ["Valor de combustível", kpis["combustivel"], "moeda"], ["Manutenções", kpis["manutencoes"], "qtd"],
                   ["Valor de manutenção", kpis["manutencao"], "moeda"], ["Total", kpis["total"], "moeda"]],
        "lancamentos": _registros(lanc.head(limite)),
        "truncado": bool(docs.attrs.get("mais")) or len(lanc) > limite,
    }


def frota_maquina(banco, cfg, codigo, a, limite):
    """Lançamentos de abastecimento e manutenção de uma máquina."""
    b = dict(a)
    b["maquina"] = codigo
    ini, fim, docs, itens = _frota_dados(banco, cfg, b, limite)
    maq = _df(banco, "SELECT A.CODIGO, A.PLACA, A.NOME, A.MARCA, A.ANO, A.MODELO, G.NOME AS GRUPO, A.KM FROM AMAQUINAS A "
                     "LEFT JOIN AMAQUINASGRUPO G ON G.CODIGO = A.CODGRUPO AND G.CODEMPRESA = A.CODEMPRESA "
                     "WHERE A.CODEMPRESA = ? AND A.CODIGO = ?", (cfg["empresa"], codigo))
    info = {k.lower(): (None if v != v else v) for k, v in (maq.iloc[0].to_dict().items() if len(maq) else {"CODIGO": codigo}.items())}
    lanc = docs.sort_values(["EMISSAO", "IDMOV"], ascending=False)[
        ["IDMOV", "EMISSAO", "TIPO", "DOCUMENTO", "KM", "FORNECEDOR", "ITENS", "LITROS", "VALOR"]]
    ab, mt = docs[docs["CODTMV"] == TMV_COMBUSTIVEL], docs[docs["CODTMV"] == TMV_MANUTENCAO]
    resumo = {"combustivel": float(ab["VALOR"].sum()), "litros": float(ab["LITROS"].sum()), "manutencao": float(mt["VALOR"].sum()),
              "total": float(docs["VALOR"].sum()), "abastecimentos": int(len(ab)), "manutencoes": int(len(mt))}
    totais = [["Abastecimentos", resumo["abastecimentos"], "qtd"], ["Litros", resumo["litros"], "qtd"],
              ["Valor de combustível", resumo["combustivel"], "moeda"], ["Manutenções", resumo["manutencoes"], "qtd"],
              ["Valor de manutenção", resumo["manutencao"], "moeda"], ["Total", resumo["total"], "moeda"]]
    return {"periodo": [ini.isoformat(), fim.isoformat()], "maquina": info, "resumo": resumo, "totais": totais,
            "tabela": _registros(lanc), "truncado": bool(docs.attrs.get("mais"))}


# ======================================================================== máquinas (AMAQUINAS)
SQL_MAQ = """
SELECT A.CODIGO, A.PLACA, A.NOME AS DESCRICAO, A.MARCA, A.MODELO, A.ANO, A.CODGRUPO, G.NOME AS NOME_GRUPO,
       A.TIPO, A.CHASSI, A.NUMMOTOR, A.NUMSERIE, A.KM, A.TIPOCONTROLE, A.TIPOVERIFICACAO,
       A.CODFILIAL, F.NOMEFANTASIA AS NOME_FILIAL, A.INATIVO, A.OBSERVACAO
FROM AMAQUINAS A
LEFT JOIN AMAQUINASGRUPO G ON G.CODIGO = A.CODGRUPO AND G.CODEMPRESA = A.CODEMPRESA
LEFT JOIN GFILIAL F ON F.CODFILIAL = A.CODFILIAL AND F.CODEMPRESA = A.CODEMPRESA
WHERE A.CODEMPRESA = ?
"""


def maquinas(banco, cfg, a, limite):
    """Cadastro de máquinas e veículos com todas as colunas da tabela AMAQUINAS."""
    sql, params = SQL_MAQ, [cfg["empresa"]]
    if a.get("situacao") == "ativas":
        sql += " AND (A.INATIVO IS NULL OR A.INATIVO <> 'T')"
    elif a.get("situacao") == "inativas":
        sql += " AND A.INATIVO = 'T'"
    if a.get("grupo"):
        sql += " AND A.CODGRUPO = ?"
        params.append(a["grupo"])
    if _filial(a) is not None:
        sql += " AND A.CODFILIAL = ?"
        params.append(_filial(a))
    if a.get("busca"):
        t = a["busca"].strip().upper()
        sql += (" AND (UPPER(A.CODIGO) LIKE ? OR UPPER(A.PLACA) LIKE ? OR UPPER(A.NOME) LIKE ? OR UPPER(A.MARCA) LIKE ?"
                " OR UPPER(A.CHASSI) LIKE ? OR UPPER(A.NUMMOTOR) LIKE ? OR UPPER(A.NUMSERIE) LIKE ?)")
        params += [f"%{t}%"] * 7
    df = _df(banco, sql + " ORDER BY G.NOME, A.NOME", params, max(limite, 20000))
    _num(df, "KM")

    def txt(v):
        if isinstance(v, str):
            return "\n".join(" ".join(l.split()) for l in v.splitlines() if l.strip())
        return "" if v is None or v != v else str(v)
    df["OBSERVACAO"] = df["OBSERVACAO"].map(txt)
    df["GRUPO"] = [f"{c} - {n}".strip(" -") if (c or n) else "(sem grupo)" for c, n in zip(df["CODGRUPO"].fillna(""), df["NOME_GRUPO"].fillna(""))]
    df["FILIAL"] = [f"{int(c)} - {n}".strip(" -") if c == c and c is not None else "" for c, n in zip(df["CODFILIAL"], df["NOME_FILIAL"].fillna(""))]
    df["SITUACAO"] = df["INATIVO"].map(lambda v: "Inativa" if v == "T" else "Ativa")
    grupos = _df(banco, "SELECT CODIGO AS COD, NOME FROM AMAQUINASGRUPO WHERE CODEMPRESA = ? ORDER BY NOME", (cfg["empresa"],))
    kpis = {"qtd": int(len(df)), "ativas": int((df["SITUACAO"] == "Ativa").sum()),
            "grupos": int(df["GRUPO"].nunique()), "marcas": int(df["MARCA"].dropna().nunique())}
    tabela = df[["CODIGO", "PLACA", "DESCRICAO", "MARCA", "MODELO", "ANO", "GRUPO", "TIPO", "CHASSI", "NUMMOTOR", "NUMSERIE",
                 "KM", "TIPOCONTROLE", "TIPOVERIFICACAO", "FILIAL", "SITUACAO", "OBSERVACAO"]]
    return {
        "kpis": kpis,
        "grupos": [{"cod": str(r.COD).strip(), "nome": (r.NOME or "").strip()} for r in grupos.itertuples()],
        "por_grupo": _agrupar(df, "GRUPO", "CODIGO", 12, contagem=True),
        "por_marca": _agrupar(df.assign(MARCA=df["MARCA"].fillna("(sem marca)")), "MARCA", "CODIGO", 10, contagem=True),
        "tabela": _registros(tabela.head(limite)),
        "truncado": len(tabela) > limite,
    }


def clientes(banco, cfg, a, limite):
    sql, params = SQL_CLI, [cfg["empresa"]]
    tipo = a.get("tipo", "clientes")
    if tipo == "clientes":
        sql += " AND C.TIPO IN ('C','A')"
    elif tipo == "fornecedores":
        sql += " AND C.TIPO IN ('F','A')"
    if a.get("ativo") in ("T", "F"):
        sql += " AND C.ATIVO = ?"
        params.append(a["ativo"])
    if a.get("uf"):
        sql += " AND C.CODETD = ?"
        params.append(a["uf"].upper())
    if a.get("acima_limite") == "1":       # devendo (a receber em aberto) mais que o limite de crédito
        sql += (" AND C.LIMITECREDITO > 0 AND C.LIMITECREDITO < (SELECT COALESCE(SUM(L.VALORORIGINAL), 0) FROM FLAN L"
                " WHERE L.CODEMPRESA = C.CODEMPRESA AND L.CODCFO = C.CODCFO AND L.PAGREC = 'R' AND L.STATUSLAN = 'A')")
    if a.get("busca"):
        t = a["busca"].strip()
        sql += " AND (C.CODCFO = ? OR C.CGCCFO = ? OR UPPER(C.NOME) LIKE ? OR UPPER(C.NOMEFANTASIA) LIKE ? OR UPPER(C.CIDADE) LIKE ?)"
        params += [t, t, f"%{t.upper()}%", f"%{t.upper()}%", f"%{t.upper()}%"]
    df = _df(banco, sql + " ORDER BY C.NOME", params, max(limite, 20000))
    _num(df, "LIMITE")
    df["TIPO"] = df["TIPO"].map({"C": "Cliente", "F": "Fornecedor", "A": "Cliente/Fornecedor"}).fillna(df["TIPO"])
    df["PESSOA"] = df["PESSOA"].map({"F": "Física", "J": "Jurídica"}).fillna(df["PESSOA"])
    df["ATIVO"] = df["ATIVO"].map({"T": "Ativo", "F": "Inativo"}).fillna(df["ATIVO"])
    df["CIDADE_UF"] = df["CIDADE"].fillna("").str.upper().str.strip() + df["UF"].fillna("").map(lambda u: f" - {u}" if u else "")
    df.loc[df["CIDADE_UF"].str.strip() == "", "CIDADE_UF"] = "(sem cidade)"
    email = df["EMAIL"].fillna("").str.upper()
    kpis = {
        "qtd": int(len(df)),
        "ativos": int((df["ATIVO"] == "Ativo").sum()),
        "sem_uf": int(df["UF"].isna().sum() + (df["UF"] == "").sum()),
        "email_generico": int(email.str.contains("NAOTEM|NAO TEM|NAOCONTEM", regex=True).sum() + (email == "").sum()),
    }
    return {
        "kpis": kpis,
        "por_cidade": _agrupar(df, "CIDADE_UF", "CODIGO", 12, contagem=True, outros=False),
        "por_pessoa": _agrupar(df, "PESSOA", "CODIGO", contagem=True),
        "tabela": _registros(df.drop(columns=["CIDADE_UF"]).head(limite)),
        "truncado": len(df) > limite,
    }


SQL_PROD = """
SELECT P.NUMNOFABRIC AS COD_FABRICANTE, P.NOMEFANTASIA AS PRODUTO, P.CODUNDVENDA AS UND, G.DESCRICAO AS GRUPO,
       P.PRECO1 AS PRECO, P.CUSTOMEDIO AS CUSTO_MEDIO, P.SALDOGERALFISICO AS SALDO,
       P.CODCLASSFISCAL AS NCM, P.CODCEST AS CEST, P.CODSIT AS SIT_DENTRO, S1.DESCRICAO AS DESC_DENTRO,
       P.CODSIT2 AS SIT_FORA, S2.DESCRICAO AS DESC_FORA, P.CST_PISCOFINS, P.ORIGEMMERCADORIA AS ORIG, P.INATIVO
FROM TPRODUTO P
LEFT JOIN TGRUPO G ON G.CODGRUPO = P.CODGRUPO AND G.CODEMPRESA = P.CODEMPRESA
LEFT JOIN TSTRIBUTARIA S1 ON S1.CODSIT = P.CODSIT AND S1.CODEMPRESA = P.CODEMPRESA
LEFT JOIN TSTRIBUTARIA S2 ON S2.CODSIT = P.CODSIT2 AND S2.CODEMPRESA = P.CODEMPRESA
WHERE P.CODEMPRESA = ?
"""


def produtos(banco, cfg, a, limite):
    sql, params = SQL_PROD, [cfg["empresa"]]
    so_inativos = a.get("alerta") == "Inativos"
    if so_inativos:
        sql += " AND P.INATIVO = 'T'"
    elif a.get("inativos") != "1":
        sql += " AND (P.INATIVO IS NULL OR P.INATIVO <> 'T')"
    if a.get("grupo"):
        sql += " AND P.CODGRUPO = ?"
        params.append(a["grupo"])
    if a.get("busca"):
        t = a["busca"].strip()
        sql += " AND (P.NUMNOFABRIC = ? OR P.CODPRD = ? OR P.CODCLASSFISCAL = ? OR UPPER(P.NOMEFANTASIA) LIKE ?)"
        params += [t, t, t, f"%{t.upper()}%"]
    df = _df(banco, sql + " ORDER BY P.CODPRD DESC", params, max(limite, 50000))
    _num(df, "PRECO", "CUSTO_MEDIO", "SALDO")
    for c in ("SIT_DENTRO", "SIT_FORA", "CEST", "NCM"):
        df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    st_dentro = df["SIT_DENTRO"].fillna("")
    sem_cest_st = (st_dentro == "FF") & (df["CEST"].isna() | df["CEST"].isin(["", "0000000"]))
    df["ALERTA"] = ""
    df.loc[df["SIT_DENTRO"].isna() | (st_dentro == ""), "ALERTA"] += "Sem situação tributária; "
    df.loc[df["NCM"].isna() | (df["NCM"] == ""), "ALERTA"] += "Sem NCM; "
    df.loc[sem_cest_st, "ALERTA"] += "ST sem CEST; "
    df.loc[df["PRECO"] <= 0, "ALERTA"] += "Sem preço; "
    df.loc[df["SALDO"] < 0, "ALERTA"] += "Saldo negativo; "
    df["ALERTA"] = df["ALERTA"].str.rstrip("; ")
    filtro = a.get("alerta")
    if filtro and not so_inativos:
        df = df[df["ALERTA"].str.contains(filtro, regex=False)]
    df["ORIGEM"] = df.pop("ORIG").map(lambda v: f"{int(v)} - {ORIGENS.get(int(v), '')}".rstrip(" -") if v is not None and v == v else "")
    df["SIT_ROT"] = df["SIT_DENTRO"].fillna("--") + " " + df["DESC_DENTRO"].fillna("Sem situação")
    alertas = {}
    for nome in ("Sem situação tributária", "Sem NCM", "ST sem CEST", "Sem preço", "Saldo negativo"):
        alertas[nome] = int(df["ALERTA"].str.contains(nome, regex=False).sum())
    kpis = {"qtd": int(len(df)), "com_alerta": int((df["ALERTA"] != "").sum()), **{"alerta_" + k: v for k, v in alertas.items()}}
    return {
        "kpis": kpis,
        "por_situacao": _agrupar(df, "SIT_ROT", "COD_FABRICANTE", contagem=True),
        "alertas": [{"rotulo": k, "valor": float(v)} for k, v in alertas.items()],
        "tabela": _registros(df.drop(columns=["SIT_ROT"]).head(limite)),
        "truncado": len(df) > limite,
    }


# ======================================================================== início
def _por_dia(df, col_data, col_valor, ini, fim):
    """Soma por dia (rótulo dd/mm) de ini a fim, com zero nos dias sem valor."""
    dias = pd.date_range(ini, fim, freq="D")
    if df.empty:
        s = pd.Series(0.0, index=dias.strftime("%Y-%m-%d"))
    else:
        d = pd.to_datetime(df[col_data], errors="coerce").dt.strftime("%Y-%m-%d")
        s = pd.DataFrame({"d": d, "v": df[col_valor]}).groupby("d")["v"].sum().reindex(dias.strftime("%Y-%m-%d"), fill_value=0)
    return [{"rotulo": f"{k[8:10]}/{k[5:7]}", "valor": float(v)} for k, v in s.items()]


def categorias(banco, cfg):
    """Categorias de negócio dos tipos de movimento, tiradas do próprio Puma: os grupos de 2 níveis
    do TTIPOMOV (ex.: 1.2 = Movimentos de Compra, 2.3 = Devoluções de Venda)."""
    df = _df(banco, "SELECT CODTIPOMOV AS COD, NOME FROM TTIPOMOV WHERE CODEMPRESA = ?", (cfg["empresa"],))
    cats = {}
    for r in df.itertuples():
        c = str(r.COD or "").strip()
        if c and c.count(".") <= 1:
            cats[c] = (r.NOME or "").strip()
    return cats


def categoria_de(cod, cats):
    """'1.2.06' -> ('1.2', '1.2 Movimentos de Compra')."""
    partes = str(cod or "").strip().split(".")
    for n in (2, 1):
        pre = ".".join(partes[:n])
        if pre in cats:
            return pre, f"{pre} {cats[pre]}"
    pre = ".".join(partes[:2]) or "(sem tipo)"
    return pre, pre


def _agrupar_categoria(df, col_cod, cats, n=10):
    if df.empty:
        return []
    rot = df[col_cod].map(lambda c: categoria_de(c, cats)[1])
    s = rot.value_counts()
    if len(s) > n:
        resto = s.iloc[n:].sum()
        s = s.iloc[:n]
        s.loc["Outros"] = resto
    return [{"rotulo": str(k), "valor": float(v), "prefixo": (str(k).split(" ")[0] if k != "Outros" else "")} for k, v in s.items()]


def _periodo_inicio(a):
    """Período da Início: o escolhido no topo da tela (ini/fim) ou o mês atual."""
    hoje = HOJE()
    ini_mes = hoje.replace(day=1)
    fim_mes = (pd.Timestamp(ini_mes) + pd.offsets.MonthEnd(0)).date()
    ini = _data((a or {}).get("ini"), ini_mes)
    fim = _data((a or {}).get("fim"), fim_mes)
    if fim < ini:
        ini, fim = fim, ini
    return ini, fim


def _periodo_anterior(ini, fim, hoje):
    """Mesmo trecho no período anterior, para comparar de forma justa (ex.: 01 a 21/10 x 01 a 21/09)."""
    fim_c = min(fim, max(hoje, ini))
    fim_mes = (pd.Timestamp(fim) + pd.offsets.MonthEnd(0)).date()
    if ini.day == 1 and fim == fim_mes:                       # meses inteiros: volta o mesmo nº de meses
        meses = (fim.year - ini.year) * 12 + fim.month - ini.month + 1
        volta = pd.DateOffset(months=meses)
        return (pd.Timestamp(ini) - volta).date(), (pd.Timestamp(fim_c) - volta).date()
    dias = dt.timedelta(days=(fim - ini).days + 1)
    return ini - dias, fim_c - dias


def inicio(banco, cfg, perm=None, parte=None, a=None):
    """Tela Início, em duas partes para aparecer mais rápido:
    parte 'resumo' (cards, comparação, histórico, alertas, atraso) e 'graficos' (funcionário, tipo, semanas)."""
    hoje = HOJE()
    emp = cfg["empresa"]
    ini, fim = _periodo_inicio(a)
    ft_sql, ft_par = filtro_tipos(perm)
    fil = _filial(a)
    r = {"periodo": [ini.isoformat(), fim.isoformat()], "filial": fil}
    # filtro de filial (vazio = todas)
    fl_sql, fl_par = (" AND L.CODFILIAL = ?", [fil]) if fil is not None else ("", [])
    fm_sql, fm_par = (" AND M.CODFILIAL = ?", [fil]) if fil is not None else ("", [])
    fs_sql, fs_par = (" AND S.CODFILIAL = ?", [fil]) if fil is not None else ("", [])
    fq = f"&filial={fil}" if fil is not None else ""

    fin = _df(banco, """
        SELECT L.PAGREC, L.DATAVENCIMENTO AS VENCIMENTO, L.VALORORIGINAL AS VALOR
        FROM FLAN L WHERE L.CODEMPRESA = ? AND L.STATUSLAN = 'A'
          AND L.DATAVENCIMENTO BETWEEN ? AND ?""" + fl_sql, [emp, ini, fim] + fl_par)
    _num(fin, "VALOR")
    venc = pd.to_datetime(fin["VENCIMENTO"], errors="coerce")
    rec, pag = fin["PAGREC"] == "R", fin["PAGREC"] == "P"

    if parte in (None, "resumo"):
        vencido = venc < pd.Timestamp(hoje)
        # ---- movimentos: período atual + 6 meses de histórico + período anterior, numa consulta só
        ini_ant, fim_ant = _periodo_anterior(ini, fim, hoje)
        ini_6 = (pd.Timestamp(fim.replace(day=1)) - pd.DateOffset(months=5)).date()
        desde = min(ini, ini_6, ini_ant)
        hist = _df(banco, """
            SELECT M.DATAEMISSAO AS EMISSAO, M.VALORLIQUIDO AS VALOR
            FROM TMOV M WHERE M.CODEMPRESA = ? AND M.DATAEMISSAO BETWEEN ? AND ? AND (M.STATUS IS NULL OR M.STATUS <> 'C')""" + ft_sql + fm_sql,
            [emp, desde, fim] + ft_par + fm_par)
        _num(hist, "VALOR")
        he = pd.to_datetime(hist["EMISSAO"], errors="coerce")
        no = lambda i, f: hist[(he >= pd.Timestamp(i)) & (he <= pd.Timestamp(f))]
        atual, ant = no(ini, fim), no(ini_ant, fim_ant)
        hist6 = no(ini_6, fim).copy()
        hist6["MES"] = pd.to_datetime(hist6["EMISSAO"], errors="coerce").dt.strftime("%Y-%m")
        meses = pd.period_range(ini_6, fim, freq="M").strftime("%Y-%m")
        h_qtd = hist6.groupby("MES").size().reindex(meses, fill_value=0)
        h_val = hist6.groupby("MES")["VALOR"].sum().reindex(meses, fill_value=0)

        est = _df(banco, """
            SELECT S.SALDOFISICO1 AS SALDO, COALESCE(NULLIF(S.CUSTOMEDIO, 0), P.CUSTOMEDIO, 0) AS CUSTO
            FROM TPRODSALDO S JOIN TPRODUTO P ON P.CODPRD = S.CODPRD AND P.CODEMPRESA = S.CODEMPRESA
            WHERE S.CODEMPRESA = ? AND S.SALDOFISICO1 > 0""" + fs_sql, [emp] + fs_par)
        _num(est, "SALDO", "CUSTO")
        valor_est = float((est["SALDO"] * est["CUSTO"]).sum()) if not est.empty else 0.0

        # ---- atraso (aging) de todos os títulos em aberto
        ab = _df(banco, """
            SELECT L.PAGREC, L.CODCFO, L.DATAVENCIMENTO AS VENCIMENTO, L.VALORORIGINAL AS VALOR
            FROM FLAN L WHERE L.CODEMPRESA = ? AND L.STATUSLAN = 'A'""" + fl_sql, [emp] + fl_par)
        _num(ab, "VALOR")
        atraso = (pd.Timestamp(hoje) - pd.to_datetime(ab["VENCIMENTO"], errors="coerce")).dt.days.fillna(0)
        ontem = (hoje - dt.timedelta(days=1)).isoformat()
        faixas = [("A vencer", atraso <= 0, hoje.isoformat(), "2100-12-31"),
                  ("1–30 dias", (atraso >= 1) & (atraso <= 30), (hoje - dt.timedelta(days=30)).isoformat(), ontem),
                  ("31–60 dias", (atraso >= 31) & (atraso <= 60), (hoje - dt.timedelta(days=60)).isoformat(), (hoje - dt.timedelta(days=31)).isoformat()),
                  ("61–90 dias", (atraso >= 61) & (atraso <= 90), (hoje - dt.timedelta(days=90)).isoformat(), (hoje - dt.timedelta(days=61)).isoformat()),
                  ("+90 dias", atraso > 90, "2000-01-01", (hoje - dt.timedelta(days=91)).isoformat())]
        aging = {pr: [{"rotulo": rot, "valor": float(ab.loc[(ab["PAGREC"] == pr) & m, "VALOR"].sum()),
                       "qtd": int(((ab["PAGREC"] == pr) & m).sum()), "ini": i, "fim": f} for rot, m, i, f in faixas]
                 for pr in ("R", "P")}

        # ---- alertas
        venc_r = (ab["PAGREC"] == "R") & (atraso > 0)
        venc_p = (ab["PAGREC"] == "P") & (atraso > 0)
        vence_hoje = (ab["PAGREC"] == "P") & (atraso == 0)
        neg = _df(banco, "SELECT COUNT(*) AS N FROM TPRODSALDO S WHERE S.CODEMPRESA = ? AND S.SALDOFISICO1 < 0" + fs_sql, [emp] + fs_par)
        n_neg = int(neg["N"].iloc[0] or 0) if not neg.empty else 0
        lim = _df(banco, "SELECT C.CODCFO, C.LIMITECREDITO AS LIMITE FROM FCFO C WHERE C.CODEMPRESA = ? AND C.LIMITECREDITO > 0", (emp,))
        _num(lim, "LIMITE")
        deve = ab[ab["PAGREC"] == "R"].groupby("CODCFO")["VALOR"].sum()
        acima = int((lim["LIMITE"].values < deve.reindex(lim["CODCFO"]).fillna(0).values).sum()) if not lim.empty else 0
        alertas = [
            {"nivel": "critico", "qtd": int(venc_r.sum()), "valor": float(ab.loc[venc_r, "VALOR"].sum()), "texto": "títulos a receber vencidos",
             "link": f"/financeiro?tipo=R&status=A&base=vencimento&ini=2000-01-01&fim={ontem}{fq}"},
            {"nivel": "critico", "qtd": int(venc_p.sum()), "valor": float(ab.loc[venc_p, "VALOR"].sum()), "texto": "contas a pagar vencidas",
             "link": f"/financeiro?tipo=P&status=A&base=vencimento&ini=2000-01-01&fim={ontem}{fq}"},
            {"nivel": "aviso", "qtd": int(vence_hoje.sum()), "valor": float(ab.loc[vence_hoje, "VALOR"].sum()), "texto": "contas a pagar vencem hoje",
             "link": f"/financeiro?tipo=P&status=A&base=vencimento&ini={hoje.isoformat()}&fim={hoje.isoformat()}{fq}"},
            {"nivel": "aviso", "qtd": n_neg, "texto": "saldos negativos no estoque", "link": f"/estoque?negativos=1{fq}"},
            {"nivel": "aviso", "qtd": acima, "texto": "clientes acima do limite de crédito", "link": "/cadastros?acima_limite=1"},
        ]
        r.update({
            "kpis": {
                "receber_aberto": float(fin.loc[rec, "VALOR"].sum()),
                "receber_vencido": float(fin.loc[rec & vencido, "VALOR"].sum()),
                "pagar_aberto": float(fin.loc[pag, "VALOR"].sum()),
                "pagar_vencido": float(fin.loc[pag & vencido, "VALOR"].sum()),
                "mov_mes": int(len(atual)),
                "mov_mes_valor": float(atual["VALOR"].sum()),
                "estoque_valor": valor_est,
            },
            "comparacao": {"mov_mes": int(len(ant)), "mov_mes_valor": float(ant["VALOR"].sum()),
                           "rotulo": f"{ini_ant.strftime('%d/%m')} a {fim_ant.strftime('%d/%m')}" if ini_ant.year == fim_ant.year == hoje.year
                           else f"{ini_ant.strftime('%d/%m/%y')} a {fim_ant.strftime('%d/%m/%y')}"},
            "historico": {"meses": list(meses), "qtd": [int(v) for v in h_qtd], "valor": [float(v) for v in h_val]},
            "aging": aging,
            "alertas": [x for x in alertas if x["qtd"]],
        })

    if parte in (None, "graficos"):
        mov = _df(banco, """
            SELECT M.CODTMV, T.NOME AS TIPO, M.CODVEN1 AS CODVEN, V.NOME AS VENDEDOR
            FROM TMOV M LEFT JOIN TTIPOMOV T ON T.CODTIPOMOV = M.CODTMV AND T.CODEMPRESA = M.CODEMPRESA
            LEFT JOIN TVENDEDOR V ON V.CODVEN = M.CODVEN1 AND V.CODEMPRESA = M.CODEMPRESA
            WHERE M.CODEMPRESA = ? AND M.DATAEMISSAO BETWEEN ? AND ? AND (M.STATUS IS NULL OR M.STATUS <> 'C')""" + ft_sql + fm_sql,
            [emp, ini, fim] + ft_par + fm_par)
        mov["VALOR"] = 0.0
        mov["TIPO_ROT"] = mov["CODTMV"].fillna("") + " " + mov["TIPO"].fillna("")
        mov["FUNC_ROT"] = (mov["CODVEN"].fillna("").astype(str).str.strip() + " " + mov["VENDEDOR"].fillna("")).str.strip()
        mov.loc[mov["FUNC_ROT"] == "", "FUNC_ROT"] = "(sem funcionário)"
        # ---- contas por semana (até 2 meses) ou por mês (períodos maiores)
        blocos = []
        if (fim - ini).days <= 62:
            d0 = ini
            while d0 <= fim:
                d1 = min(d0 + dt.timedelta(days=6), fim)
                blocos.append((f"{d0.day:02d}–{d1.day:02d}/{d1.month:02d}", d0, d1))
                d0 = d1 + dt.timedelta(days=1)
        else:
            for m in pd.period_range(ini, fim, freq="M"):
                d0 = max(m.start_time.date(), ini)
                d1 = min(m.end_time.date(), fim)
                blocos.append((m.strftime("%Y-%m"), d0, d1))
        sem = []
        for rot, d0, d1 in blocos:
            f = (venc >= pd.Timestamp(d0)) & (venc <= pd.Timestamp(d1))
            sem.append({"rotulo": rot, "ini": d0.isoformat(), "fim": d1.isoformat(),
                        "receber": float(fin.loc[rec & f, "VALOR"].sum()), "pagar": float(fin.loc[pag & f, "VALOR"].sum())})
        r.update({
            "semanas": sem,
            "por_semana": (fim - ini).days <= 62,
            "mov_tipo": _agrupar(mov, "TIPO_ROT", "VALOR", 8, contagem=True),
            "mov_cat": _agrupar_categoria(mov, "CODTMV", categorias(banco, cfg), 8),
            "mov_func": _agrupar(mov, "FUNC_ROT", "VALOR", 12, contagem=True),
        })
    return r


# ======================================================================== ficha do cliente/fornecedor
def ficha_cadastro(banco, cfg, codcfo):
    df = _df(banco, SQL_CLI + " AND C.CODCFO = ?", (cfg["empresa"], codcfo))
    _num(df, "LIMITE")
    return _registros(df)


def ficha_financeiro(banco, cfg, codcfo, limite):
    """Todos os lançamentos (a pagar e a receber, qualquer situação) do cliente/fornecedor."""
    df = _df(banco, SQL_FIN + " AND L.CODCFO = ? ORDER BY L.DATAVENCIMENTO DESC, L.IDLAN DESC",
             (cfg["empresa"], codcfo), limite)
    _num(df, "VALOR", "VALOR_BAIXADO")
    hoje = HOJE()
    venc = pd.to_datetime(df["VENCIMENTO"], errors="coerce")
    aberto = df["STATUS"] == "A"
    dias = (pd.Timestamp(hoje) - venc).dt.days
    df["DIAS_ATRASO"] = dias.where(aberto & (dias > 0), 0).fillna(0).astype(int)
    stl = cfg["status_lancamento"]
    df["SITUACAO"] = df["STATUS"].map(lambda x: stl.get(x, x) if x else "")
    df["TIPO"] = df["PAGREC"].map({"P": "A pagar", "R": "A receber"}).fillna("")
    rec, pag = df["PAGREC"] == "R", df["PAGREC"] == "P"
    vencido = aberto & (df["DIAS_ATRASO"] > 0)
    kpis = {
        "qtd": int(len(df)),
        "receber_aberto": float(df.loc[rec & aberto, "VALOR"].sum()),
        "receber_vencido": float(df.loc[rec & vencido, "VALOR"].sum()),
        "pagar_aberto": float(df.loc[pag & aberto, "VALOR"].sum()),
        "pagar_vencido": float(df.loc[pag & vencido, "VALOR"].sum()),
        "recebido": float(df.loc[rec & (df["STATUS"] == "B"), "VALOR_BAIXADO"].sum()),
        "pago": float(df.loc[pag & (df["STATUS"] == "B"), "VALOR_BAIXADO"].sum()),
    }
    tabela = df[["TIPO", "SITUACAO", "DOCUMENTO", "PARCELA", "TIPO_DOC", "EMISSAO", "VENCIMENTO", "BAIXA",
                 "VALOR", "VALOR_BAIXADO", "DIAS_ATRASO", "HISTORICO"]]
    return {"kpis": kpis, "tabela": _registros(tabela), "truncado": df.attrs["mais"]}


def ficha_movimentos(banco, cfg, codcfo, limite, perm=None):
    """Todos os movimentos do cliente/fornecedor (todas as datas, inclusive cancelados)."""
    d = movimentos(banco, cfg, {"ini": "1900-01-01", "fim": "2999-12-31", "codcfo": codcfo, "cancelados": "1",
                                "_tipos_perm": perm}, limite)
    t = d["tabela"]
    i_st, i_v = t["colunas"].index("STATUS"), t["colunas"].index("VALOR")
    canc = cfg["status_movimento"].get("C", "C")
    validos = [r for r in t["linhas"] if r[i_st] != canc]
    datas = [r[t["colunas"].index("EMISSAO")] for r in validos if r[t["colunas"].index("EMISSAO")]]
    return {
        "kpis": {"qtd": len(validos), "cancelados": len(t["linhas"]) - len(validos),
                 "valor": float(sum(r[i_v] or 0 for r in validos)),
                 "primeiro": min(datas) if datas else None, "ultimo": max(datas) if datas else None},
        "por_tipo": d["por_tipo"],
        "tabela": t, "truncado": d["truncado"],
    }
