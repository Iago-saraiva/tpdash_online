"""Layout de apresentação dos relatórios: colunas (ordem, nome, formato, visibilidade), ordenação,
agrupamento com subtotais, totais, indicadores e gráfico. Aplicado igual na tela, no Excel e no PDF.

Formato salvo (por relatório):
{
  "visoes": {
    "<nome da visão>": {
      "oculta": false, "titulo": "Itens",
      "colunas": [{"campo": "VALOR", "rotulo": "Valor", "visivel": true, "formato": "moeda", "total": "soma"}],
      "ordenar": [{"campo": "DATAEMISSAO", "dir": "asc"}],
      "agrupar": ["CLIENTE"],               # até 2 níveis, com subtotais
      "grafico": {"tipo": "barras", "x": "CLIENTE", "y": "VALOR", "agregacao": "soma"},
      "indicadores": [{"rotulo": "Total", "campo": "VALOR", "agregacao": "soma", "formato": "moeda"}]
    }
  },
  "pdf": {"orientacao": "auto"}
}
"""
import datetime as dt
import re

FORMATOS = ("auto", "texto", "inteiro", "numero", "moeda", "percentual", "data", "datahora")
AGREGACOES = ("nenhum", "soma", "media", "contagem", "minimo", "maximo")

_MOEDA = re.compile(r"(VALOR|PRECO|PREÇO|TOTAL|CUSTO|SALDO_FIN|LIMITE|VLR|BRUTO|LIQUIDO|DESC|FRETE|SEGURO|DESP|JUROS|MULTA)", re.I)
_DATA = re.compile(r"(^DATA|DATA$|^DT|EMISSAO|VENCIMENTO|BAIXA|CADASTRO|ULTIMA_VENDA)", re.I)


def rotulo_padrao(campo):
    m = {"CPF_CNPJ": "CPF/CNPJ", "CGCCFO": "CPF/CNPJ", "NCM": "NCM", "CEST": "CEST", "CODCFO": "Cód. cliente",
         "CODTMV": "Tipo mov.", "NUMEROMOV": "Documento", "NOMEFANTASIA": "Nome fantasia", "CODPRD": "Cód. fabricante",
         "NUMNOFABRIC": "Cód. fabricante", "COD_FABRICANTE": "Cód. fabricante", "DATAEMISSAO": "Emissão",
         "DATAVENCIMENTO": "Vencimento", "DATABAIXA": "Baixa", "VALORLIQUIDO": "Valor líquido", "VALORBRUTO": "Valor bruto",
         "VALORORIGINAL": "Valor original", "VALORBAIXADO": "Valor baixado", "QUANTIDADE": "Quantidade",
         "PRECOUNITARIO": "Preço unitário", "VALORTOTALITEM": "Total do item", "CODUND": "Und", "UNIDADE": "Und",
         "CODLOC": "Local", "CODVEN1": "Vendedor", "NSEQ": "Seq"}
    c = campo.upper()
    if c in m:
        return m[c]
    t = re.sub(r"_\d+$", "", campo).replace("_", " ").lower()
    return t[:1].upper() + t[1:]


def _numerico(linhas, i):
    tem = False
    for r in linhas[:500]:
        v = r[i]
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        tem = True
    return tem


def formato_auto(campo, linhas, i):
    amostra = next((r[i] for r in linhas[:200] if r[i] is not None), None)
    if isinstance(amostra, str) and re.match(r"^\d{4}-\d{2}-\d{2}", amostra):
        return "datahora" if len(amostra) > 10 and amostra[11:16] != "00:00" else "data"
    if _numerico(linhas, i):
        if _MOEDA.search(campo):
            return "moeda"
        if all(float(r[i]).is_integer() for r in linhas[:300] if r[i] is not None):
            return "inteiro"
        return "numero"
    return "texto"


def _agregar(valores, ag):
    vs = [v for v in valores if v is not None]
    if ag == "contagem":
        return len(vs)
    nums = [float(v) for v in vs if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if ag == "soma":
        return sum(nums) if nums else None
    if ag == "media":
        return sum(nums) / len(nums) if nums else None
    if ag == "minimo":
        return min(vs) if vs else None
    if ag == "maximo":
        return max(vs) if vs else None
    return None


def _chave_ordem(v):
    if v is None:
        return (1, "")
    if isinstance(v, (int, float)):
        return (0, v)
    return (0, str(v))


def colunas_efetivas(visao, cfg):
    """Lista de colunas a exibir (ordem/rótulo/formato/total) combinando a consulta com o layout salvo."""
    originais = visao.get("colunas") or []
    linhas = visao.get("linhas") or []
    idx = {c.upper(): i for i, c in enumerate(originais)}
    salvas = {c["campo"].upper(): c for c in (cfg or {}).get("colunas") or []}
    ordem = [c["campo"] for c in (cfg or {}).get("colunas") or [] if c["campo"].upper() in idx]
    ordem += [c for c in originais if c.upper() not in {o.upper() for o in ordem}]
    cols = []
    for campo in ordem:
        i = idx[campo.upper()]
        s = salvas.get(campo.upper(), {})
        fmt = s.get("formato") or "auto"
        if fmt == "auto":
            fmt = formato_auto(campo, linhas, i)
        total = s.get("total")
        if total is None:
            total = "soma" if fmt == "moeda" and not re.search(r"PRECO|UNIT|CUSTO|LIMITE", campo, re.I) else "nenhum"
        cols.append({"campo": originais[i], "i": i, "rotulo": s.get("rotulo") or rotulo_padrao(originais[i]),
                     "visivel": s.get("visivel", True), "formato": fmt, "total": total, "abaixo": bool(s.get("abaixo")),
                     "formato_salvo": s.get("formato") or "auto"})
    return cols


def aplicar(visao, cfg):
    """Devolve a visão pronta para exibir: colunas visíveis, linhas ordenadas, blocos agrupados,
    totais, indicadores e dados do gráfico."""
    cfg = cfg or {}
    out = {k: visao.get(k) for k in ("nome", "erro", "aviso", "truncado")}
    out["titulo"] = cfg.get("titulo") or visao.get("nome")
    out["oculta"] = bool(cfg.get("oculta"))
    out["colunas_originais"] = visao.get("colunas") or []
    if visao.get("erro") or not visao.get("colunas"):
        out.update(colunas=[], linhas=[], blocos=None, totais=None, indicadores=[], grafico=None)
        return out
    todas = colunas_efetivas(visao, cfg)
    out["config_colunas"] = [{k: c[k] for k in ("campo", "rotulo", "visivel", "formato_salvo", "total", "abaixo")} for c in todas]
    vis = [c for c in todas if c["visivel"]]
    linhas = list(visao.get("linhas") or [])
    idx = {c.upper(): i for i, c in enumerate(visao["colunas"])}

    # ordenação (agrupamento primeiro, depois a ordenação escolhida)
    ordens = [{"campo": g, "dir": "asc"} for g in cfg.get("agrupar") or [] if g and g.upper() in idx]
    ordens += [o for o in cfg.get("ordenar") or [] if o.get("campo") and o["campo"].upper() in idx]
    for o in reversed(ordens):
        i = idx[o["campo"].upper()]
        linhas.sort(key=lambda r: _chave_ordem(r[i]), reverse=o.get("dir") == "desc")

    def projetar(r):
        return [r[c["i"]] for c in vis]

    def totais_de(rs):
        return [(_agregar([r[c["i"]] for r in rs], c["total"]) if c["total"] != "nenhum" else None) for c in vis]

    tem_total = any(c["total"] != "nenhum" for c in vis)
    # "abaixo": a coluna aparece embaixo da anterior, na mesma célula (como no ReportBuilder); a 1ª nunca fica abaixo
    out["colunas"] = [{"campo": c["campo"], "rotulo": c["rotulo"], "formato": c["formato"], "total": c["total"],
                       "abaixo": bool(c["abaixo"]) and k > 0} for k, c in enumerate(vis)]
    out["linhas"] = [projetar(r) for r in linhas]
    out["totais"] = totais_de(linhas) if tem_total and linhas else None

    # agrupamento com subtotais (até 2 níveis)
    grupos = [g for g in (cfg.get("agrupar") or [])[:2] if g and g.upper() in idx]
    out["agrupar"] = grupos
    if grupos and linhas:
        blocos = []

        def montar(rs, nivel):
            gi = idx[grupos[nivel].upper()]
            rot = next((c["rotulo"] for c in todas if c["campo"].upper() == grupos[nivel].upper()), grupos[nivel])
            atual, buf = object(), []

            def fechar():
                if not buf:
                    return
                blocos.append({"t": "grupo", "nivel": nivel, "rotulo": rot, "valor": buf[0][gi], "qtd": len(buf)})
                if nivel + 1 < len(grupos):
                    montar(buf, nivel + 1)
                else:
                    blocos.extend({"t": "linha", "v": projetar(r)} for r in buf)
                if tem_total:
                    blocos.append({"t": "subtotal", "nivel": nivel, "valor": buf[0][gi], "v": totais_de(buf), "qtd": len(buf)})

            for r in rs:
                if r[gi] != atual and buf:
                    fechar()
                    buf = []
                atual = r[gi]
                buf.append(r)
            fechar()

        montar(linhas, 0)
        out["blocos"] = blocos
    else:
        out["blocos"] = None

    # indicadores
    ind = []
    for k in cfg.get("indicadores") or []:
        campo = (k.get("campo") or "").upper()
        ag = k.get("agregacao") or "soma"
        if ag == "contagem" and not campo:
            valor = len(linhas)
        elif campo in idx:
            valor = _agregar([r[idx[campo]] for r in linhas], ag)
        else:
            continue
        fmt = k.get("formato") or "auto"
        if fmt == "auto":
            fmt = "inteiro" if ag == "contagem" else next((c["formato"] for c in todas if c["campo"].upper() == campo), "numero")
        ind.append({"rotulo": k.get("rotulo") or f"{ag} de {rotulo_padrao(campo)}", "valor": valor, "formato": fmt})
    out["indicadores"] = ind

    # gráfico
    g = cfg.get("grafico") or {}
    out["grafico"] = None
    if g.get("tipo") not in (None, "", "nenhum") and (g.get("x") or "").upper() in idx:
        xi = idx[g["x"].upper()]
        yi = idx.get((g.get("y") or "").upper())
        ag = g.get("agregacao") or ("soma" if yi is not None else "contagem")
        acc = {}
        for r in linhas:
            k = r[xi]
            if isinstance(k, str) and re.match(r"^\d{4}-\d{2}-\d{2}", k) and g.get("por_mes"):
                k = k[:7]
            acc.setdefault(k, []).append(r[yi] if yi is not None else 1)
        pontos = [{"rotulo": "(vazio)" if k is None else str(k), "valor": float(_agregar(v, ag if yi is not None else "contagem") or 0)}
                  for k, v in acc.items()]
        if g["tipo"] in ("barras", "rosca"):
            pontos.sort(key=lambda p: -p["valor"])
        else:
            pontos.sort(key=lambda p: p["rotulo"])
        fmt_y = next((c["formato"] for c in todas if yi is not None and c["i"] == yi), "inteiro")
        out["grafico"] = {"tipo": g["tipo"], "pontos": pontos, "formato": "inteiro" if ag == "contagem" else fmt_y,
                          "titulo": g.get("titulo") or (f"{rotulo_padrao(g.get('y') or '') or 'Quantidade'} por {rotulo_padrao(g['x'])}")}
    return out


def aplicar_todas(visoes, layout):
    layout = layout or {}
    cfgs = layout.get("visoes") or {}
    return [aplicar(v, cfgs.get(v["nome"])) for v in visoes]


def validar(layout):
    """Limpa o layout recebido do navegador (só chaves e valores conhecidos)."""
    if not isinstance(layout, dict):
        raise ValueError("Layout inválido.")
    limpo = {"visoes": {}, "pdf": {"orientacao": (layout.get("pdf") or {}).get("orientacao", "auto")}}
    if limpo["pdf"]["orientacao"] not in ("auto", "retrato", "paisagem"):
        limpo["pdf"]["orientacao"] = "auto"
    for nome, v in (layout.get("visoes") or {}).items():
        if not isinstance(v, dict):
            continue
        cols = []
        for c in v.get("colunas") or []:
            if not c.get("campo"):
                continue
            cols.append({"campo": str(c["campo"])[:100], "rotulo": str(c.get("rotulo") or "")[:100],
                         "visivel": bool(c.get("visivel", True)),
                         "formato": c.get("formato") if c.get("formato") in FORMATOS else "auto",
                         "total": c.get("total") if c.get("total") in AGREGACOES else "nenhum",
                         "abaixo": bool(c.get("abaixo"))})
        g = v.get("grafico") or {}
        limpo["visoes"][str(nome)[:100]] = {
            "oculta": bool(v.get("oculta")), "titulo": str(v.get("titulo") or "")[:150],
            "colunas": cols,
            "ordenar": [{"campo": str(o["campo"])[:100], "dir": "desc" if o.get("dir") == "desc" else "asc"}
                        for o in v.get("ordenar") or [] if o.get("campo")][:3],
            "agrupar": [str(x)[:100] for x in v.get("agrupar") or [] if x][:2],
            "grafico": {"tipo": g.get("tipo") if g.get("tipo") in ("nenhum", "barras", "colunas", "linhas", "rosca") else "nenhum",
                        "x": str(g.get("x") or "")[:100], "y": str(g.get("y") or "")[:100],
                        "agregacao": g.get("agregacao") if g.get("agregacao") in AGREGACOES else "soma",
                        "por_mes": bool(g.get("por_mes")), "titulo": str(g.get("titulo") or "")[:150]},
            "indicadores": [{"rotulo": str(k.get("rotulo") or "")[:80], "campo": str(k.get("campo") or "")[:100],
                             "agregacao": k.get("agregacao") if k.get("agregacao") in AGREGACOES else "soma",
                             "formato": k.get("formato") if k.get("formato") in FORMATOS else "auto"}
                            for k in v.get("indicadores") or []][:6],
        }
    return limpo


def formatar(v, fmt):
    """Texto para PDF."""
    if v is None:
        return ""
    def br(x, casas):
        return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    try:
        if fmt == "moeda":
            return br(float(v), 2)
        if fmt == "inteiro":
            return br(float(v), 0)
        if fmt == "numero":
            x = float(v)
            return br(x, 0) if x.is_integer() else br(x, 3).rstrip("0").rstrip(",")
        if fmt == "percentual":
            return br(float(v), 2) + "%"
        if fmt in ("data", "datahora") and isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
            d = f"{v[8:10]}/{v[5:7]}/{v[:4]}"
            return d + (" " + v[11:16] if fmt == "datahora" and len(v) >= 16 else "")
    except (TypeError, ValueError):
        pass
    return str(v)


def valor_excel(v, fmt):
    if fmt in ("data", "datahora") and isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
        try:
            return dt.datetime.fromisoformat(v[:19]) if fmt == "datahora" and len(v) > 10 else dt.date.fromisoformat(v[:10])
        except ValueError:
            return v
    return v


FMT_EXCEL = {"moeda": '#,##0.00;[Red]-#,##0.00', "inteiro": "#,##0", "numero": "#,##0.###",
             "percentual": '0.00"%"', "data": "dd/mm/yyyy", "datahora": "dd/mm/yyyy hh:mm"}


def grupos_visuais(colunas):
    """Junta as colunas marcadas como "abaixo" com a anterior: devolve listas de índices por coluna visual."""
    g = []
    for i, c in enumerate(colunas):
        if c.get("abaixo") and g:
            g[-1].append(i)
        else:
            g.append([i])
    return g
