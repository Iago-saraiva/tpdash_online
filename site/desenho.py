"""Layout de impressão no estilo ReportBuilder: bandas (título, cabeçalho, grupos, detalhe, sumário, rodapé)
com textos, campos, totais, variáveis, linhas e retângulos posicionados em milímetros, e sub-relatórios.

- importar(template)  lê o modelo do ReportBuilder (DFM binário do RB_ITEM.TEMPLATE) e devolve o "desenho"
- padrao(r, campos)   desenho simples (tabela) para relatórios sem modelo
- validar(d)          limpa um desenho vindo da tela (tipos, limites)
- gerar_pdf(...)      imprime o desenho com os dados das visões (reportlab)

As variáveis do ReportBuilder (TppVariable) têm o cálculo em RAP (Pascal); aqui há um interpretador
pequeno e seguro (não executa nada do sistema) para o subconjunto usado nos relatórios: atribuições,
if/then/else, contas, textos, campos das visões (Visao['Campo']), outras variáveis (Variable1.Value)
e funções comuns (FormatFloat, Copy, Trim...).
"""
import datetime as dt
import io
import math
import re
import struct

VERSAO = 1
VERSAO_IMPORTADOR = 2      # sobe quando o leitor do modelo do ReportBuilder melhora (o painel converte de novo)
TIPOS_BANDA = ("titulo", "cabecalho", "detalhe", "sumario", "rodape")
TIPOS_ITEM = ("texto", "campo", "memo", "total", "variavel", "sistema", "linha", "retangulo", "sub", "grade")
SISTEMA = ("data", "hora", "datahora", "pagina", "paginas", "pagina_desc", "pagina_de", "pagina_x_de_y")
CALCS = ("soma", "contagem", "media", "maximo", "minimo")


# =====================================================================================================
# importação do modelo do ReportBuilder
# =====================================================================================================
def _mm(v):
    try:
        return round(float(v or 0) / 1000.0, 3)
    except (TypeError, ValueError):
        return 0.0


_CORES = {"clBlack": "#000000", "clWhite": "#ffffff", "clRed": "#ff0000", "clMaroon": "#800000",
          "clGreen": "#008000", "clNavy": "#000080", "clBlue": "#0000ff", "clGray": "#808080",
          "clSilver": "#c0c0c0", "clOlive": "#808000", "clPurple": "#800080", "clTeal": "#008080",
          "clLime": "#00ff00", "clYellow": "#ffff00", "clFuchsia": "#ff00ff", "clAqua": "#00ffff",
          "clWindowText": "#000000", "clWindow": "#ffffff", "clBtnFace": "#f0f0f0", "clNone": None}


def _cor(v, padrao="#000000"):
    if v is None:
        return padrao
    if isinstance(v, int):
        v &= 0xFFFFFF
        return "#%02x%02x%02x" % (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)   # Delphi: $00BBGGRR
    return _CORES.get(str(v), padrao)


def _fonte(p):
    est = p.get("Font.Style") or []
    return {"nome": str(p.get("Font.Name") or "Arial")[:40], "tam": float(p.get("Font.Size") or 10),
            "n": "fsBold" in est, "i": "fsItalic" in est, "s": "fsUnderline" in est,
            "cor": _cor(p.get("Font.Color"))}


_ALIN = {"taLeftJustified": "e", "taCentered": "c", "taRightJustified": "d"}
_SISVAR = {"vtDate": "data", "vtTime": "hora", "vtDateTime": "datahora", "vtPrintDateTime": "datahora",
           "vtPageNo": "pagina", "vtPageNoDesc": "pagina_desc", "vtPageCount": "paginas",
           "vtPageSet": "pagina_de", "vtPageSetDesc": "pagina_x_de_y"}
_DBCALC = {"dcSum": "soma", "dcCount": "contagem", "dcAverage": "media", "dcMaximum": "maximo", "dcMinimum": "minimo"}
_CALCTIPO = {"veTraversal": "percurso", "veGroupBeforeFooter": "antes_rodape_grupo", "veGroupBeforeHeader": "antes_cab_grupo",
             "veGroupStart": "inicio_grupo", "veGroupEnd": "fim_grupo", "vePageStart": "inicio_pagina",
             "vePageEnd": "fim_pagina", "veReportStart": "inicio", "veReportEnd": "fim"}
_TIPODADO = {"dtString": "texto", "dtDouble": "numero", "dtInteger": "numero", "dtCurrency": "numero",
             "dtExtended": "numero", "dtSingle": "numero", "dtLongint": "numero", "dtBoolean": "logico",
             "dtDate": "data", "dtDateTime": "data", "dtTime": "data"}


def _codigos(arvore):
    """Fontes RAP dos eventos OnCalc: {nome do componente: código}."""
    from rb_sync import _prop
    saida = {}

    def andar(o):
        if o["classe"] == "TraProgramInfo":
            # ReportBuilder novo: cada evento é um objeto filho do módulo de código
            p = o["props"]
            comp, ev, src = p.get("raProgram.ComponentName"), p.get("raProgram.EventName"), p.get("raProgram.Source")
            if comp and isinstance(src, str) and src.strip() and (ev or "OnCalc") == "OnCalc":
                saida.setdefault(comp, src)
        if o["classe"] == "TraCodeModule":
            ps = o["props"].get("ProgramStream")
            if isinstance(ps, (bytes, bytearray)):
                for seg in bytes(ps).split(b"TraEventHandler")[1:]:
                    comp, ev, src = _prop(seg, "ComponentName"), _prop(seg, "EventName"), _prop(seg, "Source")
                    if comp and src and (ev or "OnCalc") == "OnCalc":
                        saida[comp] = src
        for f in o["filhos"]:
            andar(f)
    andar(arvore)
    return saida


def _aliases(arvore):
    """Pipeline -> {APELIDO DO CAMPO (FieldAlias): nome do campo (FieldName)} - usado nos cálculos RAP."""
    saida = {}

    def andar(o):
        if o["classe"] in ("TppChildDBPipeline", "TppDBPipeline", "TppBDEPipeline"):
            nome = o["props"].get("UserName") or o["nome"]
            m = saida.setdefault(nome, {})
            for f in o["filhos"]:
                if f["classe"] == "TppField":
                    al, fn = f["props"].get("FieldAlias"), f["props"].get("FieldName")
                    if fn:
                        m[(al or fn).upper()] = fn.upper()
                        m.setdefault(fn.upper(), fn.upper())
        for f in o["filhos"]:
            andar(f)
    andar(arvore)
    return saida


def _item(o, codigos, grupos):
    c, p = o["classe"], o["props"]
    if p.get("Visible") is False:
        return None
    base = {"x": _mm(p.get("mmLeft")), "y": _mm(p.get("mmTop")), "w": _mm(p.get("mmWidth")), "h": _mm(p.get("mmHeight")),
            "nome": str(p.get("UserName") or o["nome"])[:40]}
    txt = {"fonte": _fonte(p), "alin": _ALIN.get(p.get("TextAlignment"), "e"),
           "auto": bool(p.get("AutoSize", c in ("TppLabel", "TppVariable", "TppSystemVariable"))),   # padrões do RB
           "quebra": bool(p.get("WordWrap", False)),
           "fundo": None if p.get("Transparent", True) else _cor(p.get("Color"), "#ffffff")}
    if c == "TppLabel":
        return {**base, **txt, "tipo": "texto", "texto": str(p.get("Caption") or "")}
    if c in ("TppMemo",):
        linhas = p.get("Lines.Strings") or p.get("Lines") or []
        return {**base, **txt, "tipo": "texto", "quebra": True,
                "texto": "\n".join(linhas) if isinstance(linhas, list) else str(linhas)}
    if c in ("TppDBText", "TppDBMemo", "TppDBRichText"):
        return {**base, **txt, "tipo": "memo" if c != "TppDBText" else "campo",
                "quebra": c != "TppDBText" or txt["quebra"], "esticar": c != "TppDBText" or bool(p.get("Stretch")),
                "visao": p.get("DataPipelineName"), "campo": str(p.get("DataField") or "").upper(),
                "formato": str(p.get("DisplayFormat") or ""), "branco_zero": bool(p.get("BlankWhenZero", False))}
    if c == "TppDBCalc":
        return {**base, **txt, "tipo": "total", "visao": p.get("DataPipelineName"),
                "campo": str(p.get("DataField") or "").upper(), "calc": _DBCALC.get(p.get("DBCalcType"), "soma"),
                "formato": str(p.get("DisplayFormat") or ""), "grupo_reset": grupos.get(p.get("ResetGroup")),
                "branco_zero": bool(p.get("BlankWhenZero", False))}
    if c == "TppVariable":
        return {**base, **txt, "tipo": "variavel", "codigo": codigos.get(o["nome"]) or codigos.get(p.get("UserName")) or "",
                "formato": str(p.get("DisplayFormat") or ""), "tipo_dado": _TIPODADO.get(p.get("DataType"), "texto"),
                "calc_tipo": _CALCTIPO.get(p.get("CalcType"), "percurso"), "calc_grupo": grupos.get(p.get("CalcComponent")),
                "reset_tipo": _CALCTIPO.get(p.get("ResetType"), "fim"), "reset_grupo": grupos.get(p.get("ResetComponent")),
                "ordem": int(p.get("CalcOrder") or 0), "branco_zero": bool(p.get("BlankWhenZero", False))}
    if c == "TppSystemVariable":
        return {**base, **txt, "tipo": "sistema", "sistema": _SISVAR.get(p.get("VarType"), "data"),
                "formato": str(p.get("DisplayFormat") or "")}
    if c == "TppLine":
        pos = {"lpTop": "topo", "lpBottom": "base", "lpLeft": "esq", "lpRight": "dir"}.get(p.get("Position"), "topo")
        return {**base, "tipo": "linha", "posicao": pos, "espessura": float(p.get("Weight") or 0.75) or 0.75,
                "cor": _cor(p.get("Pen.Color")), "dupla": p.get("Style") == "lsDouble"}
    if c in ("TppShape", "TppRegion"):
        forma = {"stRoundRect": "arredondado", "stRoundSquare": "arredondado", "stEllipse": "elipse",
                 "stCircle": "elipse"}.get(p.get("Shape"), "retangulo")
        if c == "TppRegion" and p.get("Pen.Style") == "psClear":
            return None
        return {**base, "tipo": "retangulo", "forma": forma, "cor": _cor(p.get("Pen.Color")),
                "fundo": None if p.get("Brush.Style") in (None, "bsClear") and c == "TppRegion" else
                (None if p.get("Brush.Style") == "bsClear" else _cor(p.get("Brush.Color"), "#ffffff")),
                "espessura": float(p.get("Pen.Width") or 1) * 0.75}
    return None


def _banda(o, codigos, grupos, aliases):
    p = o["props"]
    itens = []

    def coletar(obj):
        for f in obj["filhos"]:
            if f["classe"] == "TppSubReport":
                ch = next((x for x in f["filhos"] if x["classe"] == "TppChildReport"), None)
                if ch is not None and f["props"].get("Visible", True) is not False:
                    it = {"tipo": "sub", "x": _mm(f["props"].get("mmLeft")), "y": _mm(f["props"].get("mmTop")),
                          "w": _mm(f["props"].get("mmWidth")), "h": _mm(f["props"].get("mmHeight")),
                          "nome": str(f["props"].get("UserName") or f["nome"])[:40],
                          "secao": _secao(ch, codigos, aliases)}
                    itens.append(it)
                continue
            if f["classe"] == "TppRegion":
                r = _item(f, codigos, grupos)
                if r:
                    itens.append(r)
                coletar(f)
                continue
            it = _item(f, codigos, grupos)
            if it:
                itens.append(it)
    coletar(o)
    return {"altura": _mm(p.get("mmHeight")), "visivel": p.get("Visible", True) is not False,
            "dinamica": p.get("PrintHeight") != "phStatic", "itens": itens}


_BANDAS = {"TppTitleBand": "titulo", "TppHeaderBand": "cabecalho", "TppDetailBand": "detalhe",
           "TppSummaryBand": "sumario", "TppFooterBand": "rodape"}


def _secao(rep, codigos, aliases):
    """TppReport / TppChildReport -> seção do desenho."""
    grupos_obj = [f for f in rep["filhos"] if f["classe"] == "TppGroup"]
    grupos = {}
    for i, g in enumerate(grupos_obj):
        grupos[g["nome"]] = i
        if g["props"].get("UserName"):
            grupos[g["props"]["UserName"]] = i
    sec = {"visao": rep["props"].get("DataPipelineName"), "bandas": {}, "grupos": [],
           "titulo_antes": bool(rep["props"].get("TitleBeforeHeader", True))}
    for f in rep["filhos"]:
        t = _BANDAS.get(f["classe"])
        if t:
            sec["bandas"][t] = _banda(f, codigos, grupos, aliases)
    for g in grupos_obj:
        cab = next((x for x in g["filhos"] if x["classe"] == "TppGroupHeaderBand"), None)
        rod = next((x for x in g["filhos"] if x["classe"] == "TppGroupFooterBand"), None)
        sec["grupos"].append({
            "campo": str(g["props"].get("BreakName") or "").upper(), "visao": g["props"].get("DataPipelineName"),
            "nova_pagina": bool(g["props"].get("NewPage", False)),
            "cab": _banda(cab, codigos, grupos, aliases) if cab else {"altura": 0, "itens": []},
            "rod": _banda(rod, codigos, grupos, aliases) if rod else {"altura": 0, "itens": []},
        })
    return sec


def importar(template):
    """Modelo binário do ReportBuilder -> desenho (ou None se não der para ler)."""
    from rb_sync import _Leitor
    if not template or not bytes(template[:4]) == b"TPF0":
        return None
    try:
        arv = _Leitor(bytes(template), 4).objeto()
    except Exception:  # noqa: BLE001 - modelo diferente / corrompido
        return None
    return importar_arvore(arv)


def importar_arvore(arv):
    """Árvore do modelo (objetos e propriedades, binário ou texto) -> desenho."""
    if not arv or arv.get("classe") != "TppReport":
        return None
    p = arv["props"]
    larg, alt = _mm(p.get("PrinterSetup.mmPaperWidth")) or 210.0, _mm(p.get("PrinterSetup.mmPaperHeight")) or 297.0
    if p.get("PrinterSetup.Orientation") == "poLandscape" and larg < alt:
        larg, alt = alt, larg
    marg = {k: _mm(p.get(f"PrinterSetup.mmMargin{n}")) if p.get(f"PrinterSetup.mmMargin{n}") is not None else 6.35
            for k, n in (("sup", "Top"), ("inf", "Bottom"), ("esq", "Left"), ("dir", "Right"))}
    codigos, aliases = _codigos(arv), _aliases(arv)
    d = {"versao": VERSAO, "origem": "reportbuilder",
         "pagina": {"largura": larg, "altura": alt, "margens": marg},
         "relatorio": _secao(arv, codigos, aliases), "aliases": aliases}
    return validar(d)


# =====================================================================================================
# desenho padrão (relatórios sem modelo) e validação
# =====================================================================================================
def _largura_util(d):
    pg = d["pagina"]
    return pg["largura"] - pg["margens"]["esq"] - pg["margens"]["dir"]


def _colunas_auto(cols, largura, numeros, y_rot, y_val, fonte):
    pesos = [2.2 if c in numeros else (3.2 if any(k in c for k in ("NOME", "DESCR", "HISTOR", "OBS", "RAZAO")) else 1.6)
             for c in cols]
    total = sum(pesos) or 1
    rot, det, x = [], [], 0.0
    for c, p in zip(cols, pesos):
        w = max(10.0, largura * p / total)
        al = "d" if c in numeros else "e"
        rot.append({"tipo": "texto", "texto": c.replace("_", " ").title(), "x": x, "y": y_rot, "w": w - 1, "h": 4,
                    "alin": al, "fonte": {**fonte, "n": True}})
        det.append({"tipo": "campo", "campo": c, "x": x, "y": y_val, "w": w - 1, "h": 4, "alin": al,
                    "formato": "#,0.00;-#,0.00" if c in numeros else "", "fonte": dict(fonte)})
        x += w
    return rot, det


def padrao(r, campos, numeros=None):
    """Desenho em tabela para um relatório (visão principal + visões de detalhe como sub-relatórios).
    campos: {visao: [colunas]}; numeros: {visao: {colunas numéricas}}."""
    numeros = numeros or {}
    d = {"versao": VERSAO, "origem": "padrao",
         "pagina": {"largura": 210.0, "altura": 297.0, "margens": {"sup": 10.0, "inf": 10.0, "esq": 10.0, "dir": 10.0}}}
    larg = _largura_util(d)
    fonte = {"nome": "Arial", "tam": 7.0, "n": False, "i": False, "s": False, "cor": "#000000"}
    visoes = r.get("visoes") or []
    princ = next((v for v in visoes if not v.get("mestre")), visoes[0] if visoes else {"nome": None})
    cols = list(campos.get(princ["nome"]) or [])[:12]
    rot, det = _colunas_auto(cols, larg, numeros.get(princ["nome"], set()), 14.5, 0.5, fonte)
    cab = [{"tipo": "texto", "texto": r.get("nome") or "Relatório", "x": 0, "y": 0, "w": larg * 0.7, "h": 6,
            "alin": "e", "fonte": {**fonte, "tam": 12.0, "n": True}},
           {"tipo": "sistema", "sistema": "pagina_x_de_y", "x": larg - 40, "y": 0.5, "w": 40, "h": 4, "alin": "d",
            "fonte": dict(fonte)},
           {"tipo": "sistema", "sistema": "datahora", "x": larg - 40, "y": 5, "w": 40, "h": 4, "alin": "d", "fonte": dict(fonte)},
           {"tipo": "linha", "posicao": "base", "x": 0, "y": 18.5, "w": larg, "h": 1, "espessura": 0.75, "cor": "#000000"}] + rot
    detalhe = {"altura": 5.0, "itens": det}
    y_sub = 5.0
    for v in visoes:
        if v.get("mestre") != princ["nome"] or v is princ:
            continue
        sc = list(campos.get(v["nome"]) or [])[:12]
        r2, d2 = _colunas_auto(sc, larg - 8, numeros.get(v["nome"], set()), 0.5, 0.5, fonte)
        for it in r2 + d2:
            it["x"] += 8
        sub = {"visao": v["nome"], "grupos": [], "bandas": {
            "titulo": {"altura": 5.0, "itens": [{**i, "fonte": {**i["fonte"], "i": True}} for i in r2]},
            "detalhe": {"altura": 4.5, "itens": d2}, "sumario": {"altura": 2.0, "itens": []}}}
        detalhe["itens"].append({"tipo": "sub", "nome": v["nome"], "x": 0, "y": y_sub, "w": larg, "h": 10.0, "secao": sub})
        y_sub += 10.0
    detalhe["altura"] = max(detalhe["altura"], y_sub)
    d["relatorio"] = {"visao": princ["nome"], "grupos": [], "titulo_antes": True, "bandas": {
        "cabecalho": {"altura": 20.0, "itens": cab},
        "detalhe": detalhe,
        "rodape": {"altura": 0.0, "itens": []},
        "sumario": {"altura": 0.0, "itens": []}}}
    return validar(d)


def _num(v, padrao=0.0, mn=-2000.0, mx=2000.0):
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return padrao
        return max(mn, min(mx, round(x, 3)))
    except (TypeError, ValueError):
        return padrao


def _txt(v, n=200):
    return "" if v is None else str(v)[:n]


_COR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _vcor(v, padrao=None):
    return v if isinstance(v, str) and _COR_RE.match(v) else padrao


def _vitem(it, prof, contador):
    if not isinstance(it, dict) or it.get("tipo") not in TIPOS_ITEM:
        return None
    contador[0] += 1
    if contador[0] > 3000:
        raise ValueError("Desenho grande demais (máximo de 3000 itens).")
    t = it["tipo"]
    s = {"tipo": t, "x": _num(it.get("x")), "y": _num(it.get("y")), "w": _num(it.get("w"), 10, 0.2, 2000),
         "h": _num(it.get("h"), 4, 0.1, 2000), "nome": _txt(it.get("nome"), 40)}
    if t in ("texto", "campo", "memo", "total", "variavel", "sistema", "grade"):
        f = it.get("fonte") or {}
        s["fonte"] = {"nome": _txt(f.get("nome") or "Arial", 40), "tam": _num(f.get("tam"), 10, 3, 96),
                      "n": bool(f.get("n")), "i": bool(f.get("i")), "s": bool(f.get("s")),
                      "cor": _vcor(f.get("cor"), "#000000")}
        s["alin"] = it.get("alin") if it.get("alin") in ("e", "c", "d") else "e"
        s["auto"] = bool(it.get("auto"))
        s["quebra"] = bool(it.get("quebra"))
        s["fundo"] = _vcor(it.get("fundo"))
        s["formato"] = _txt(it.get("formato"), 60)
        s["branco_zero"] = bool(it.get("branco_zero"))
    if t == "texto":
        s["texto"] = _txt(it.get("texto"), 4000)
    if t in ("campo", "memo", "total"):
        s["campo"] = re.sub(r"[^\w$]", "", _txt(it.get("campo"), 80)).upper()
        s["visao"] = _txt(it.get("visao"), 80) or None
        s["esticar"] = bool(it.get("esticar", t == "memo"))
    if t == "total":
        s["calc"] = it.get("calc") if it.get("calc") in CALCS else "soma"
        g = it.get("grupo_reset")
        s["grupo_reset"] = int(g) if isinstance(g, (int, float)) and 0 <= g < 20 else None
    if t == "variavel":
        s["codigo"] = _txt(it.get("codigo"), 8000)
        s["tipo_dado"] = it.get("tipo_dado") if it.get("tipo_dado") in ("texto", "numero", "logico", "data") else "texto"
        s["calc_tipo"] = it.get("calc_tipo") if it.get("calc_tipo") in _CALCTIPO.values() else "percurso"
        s["reset_tipo"] = it.get("reset_tipo") if it.get("reset_tipo") in _CALCTIPO.values() else "fim"
        for k in ("calc_grupo", "reset_grupo"):
            g = it.get(k)
            s[k] = int(g) if isinstance(g, (int, float)) and 0 <= g < 20 else None
        s["ordem"] = int(_num(it.get("ordem"), 0, 0, 999))
    if t == "sistema":
        s["sistema"] = it.get("sistema") if it.get("sistema") in SISTEMA else "data"
    if t == "linha":
        s["posicao"] = it.get("posicao") if it.get("posicao") in ("topo", "base", "esq", "dir") else "topo"
        s["espessura"] = _num(it.get("espessura"), 0.75, 0.1, 10)
        s["cor"] = _vcor(it.get("cor"), "#000000")
        s["dupla"] = bool(it.get("dupla"))
    if t == "retangulo":
        s["forma"] = it.get("forma") if it.get("forma") in ("retangulo", "arredondado", "elipse") else "retangulo"
        s["cor"] = _vcor(it.get("cor"), "#000000")
        s["fundo"] = _vcor(it.get("fundo"))
        s["espessura"] = _num(it.get("espessura"), 0.75, 0, 10)
    if t == "sub":
        if prof >= 3:
            return None
        s["secao"] = _vsecao(it.get("secao") or {}, prof + 1, contador)
    if t == "grade":
        s["visao"] = _txt(it.get("visao"), 80) or None
        cols = []
        for c in (it.get("colunas") or [])[:40]:
            if isinstance(c, dict) and c.get("campo"):
                cols.append({"campo": re.sub(r"[^\w$]", "", _txt(c.get("campo"), 80)).upper(),
                             "titulo": _txt(c.get("titulo"), 80), "largura": _num(c.get("largura"), 20, 1, 2000),
                             "alin": c.get("alin") if c.get("alin") in ("e", "c", "d") else "e",
                             "formato": _txt(c.get("formato"), 60)})
        s["colunas"] = cols
        s["alt_linha"] = _num(it.get("alt_linha"), 5, 2, 100)
        s["cabecalho"] = it.get("cabecalho", True) is not False
        s["cab_fundo"] = _vcor(it.get("cab_fundo"))
        s["bordas"] = it.get("bordas", True) is not False
        s["cor_borda"] = _vcor(it.get("cor_borda"), "#999999")
    return s


def _vbanda(b, prof, contador):
    b = b if isinstance(b, dict) else {}
    itens = [x for x in (_vitem(i, prof, contador) for i in (b.get("itens") or [])[:1500]) if x]
    return {"altura": _num(b.get("altura"), 0, 0, 1000), "visivel": b.get("visivel", True) is not False,
            "dinamica": b.get("dinamica", True) is not False, "itens": itens}


def _vsecao(s, prof, contador):
    bandas = {}
    for t in TIPOS_BANDA:
        if isinstance((s.get("bandas") or {}).get(t), dict):
            bandas[t] = _vbanda(s["bandas"][t], prof, contador)
    bandas.setdefault("detalhe", {"altura": 5.0, "visivel": True, "dinamica": True, "itens": []})
    grupos = []
    for g in (s.get("grupos") or [])[:10]:
        if isinstance(g, dict):
            grupos.append({"campo": re.sub(r"[^\w$]", "", _txt(g.get("campo"), 80)).upper(),
                           "visao": _txt(g.get("visao"), 80) or None, "nova_pagina": bool(g.get("nova_pagina")),
                           "cab": _vbanda(g.get("cab"), prof, contador), "rod": _vbanda(g.get("rod"), prof, contador)})
    return {"visao": _txt(s.get("visao"), 80) or None, "bandas": bandas, "grupos": grupos,
            "titulo_antes": s.get("titulo_antes", True) is not False}


def _ident(v):
    """Nome de tabela ou campo do banco: só letras, números, _ e $ (vai direto no SQL)."""
    return re.sub(r"[^A-Za-z0-9_$]", "", str(v or ""))[:63].upper()


def _vtabelas(lista):
    """Tabelas do banco acrescentadas no editor: nome da visão, tabela, campos e ligação com outra visão."""
    saida, nomes = [], set()
    for t in (lista or [])[:20]:
        if not isinstance(t, dict):
            continue
        tabela = _ident(t.get("tabela"))
        nome = re.sub(r"[^\w ]", "", _txt(t.get("nome"), 40)).strip() or tabela
        campos = []
        for c in (t.get("campos") or [])[:150]:
            c = _ident(c)
            if c and c not in campos:
                campos.append(c)
        if not tabela or not campos or nome.upper() in nomes:
            continue
        nomes.add(nome.upper())
        ligacoes = []
        for par in (t.get("ligacoes") or [])[:5]:
            if isinstance(par, (list, tuple)) and len(par) == 2 and _ident(par[0]) and _ident(par[1]):
                ligacoes.append([_ident(par[0]), _ident(par[1])])
        mestre = _txt(t.get("mestre"), 80) or None
        saida.append({"nome": nome, "tabela": tabela, "campos": campos, "mestre": mestre if ligacoes else None,
                      "ligacoes": ligacoes if mestre else []})
    return saida


def visoes_tabelas(d):
    """Visões (SQL) das tabelas acrescentadas no editor, no formato das visões do ReportBuilder.
    Ligadas a outra visão: só as linhas da tabela que batem com as linhas dela (vínculo mestre-detalhe)."""
    vs = []
    for t in _vtabelas((d or {}).get("tabelas")):
        campos = list(t["campos"]) + [b for _, b in t["ligacoes"] if b not in t["campos"]]
        sql = "SELECT " + ", ".join("T." + c for c in campos) + "\nFROM " + t["tabela"] + " T"
        vs.append({"nome": t["nome"], "sql": sql, "mestre": t["mestre"], "ligacoes": t["ligacoes"],
                   "tabela": t["tabela"], "limite": None if t["mestre"] else 500})
    return vs


def validar(d):
    if not isinstance(d, dict):
        raise ValueError("Desenho inválido.")
    pg = d.get("pagina") or {}
    mg = pg.get("margens") or {}
    pagina = {"largura": _num(pg.get("largura"), 210, 50, 1500), "altura": _num(pg.get("altura"), 297, 50, 1500),
              "margens": {k: _num(mg.get(k), 10, 0, 100) for k in ("sup", "inf", "esq", "dir")}}
    aliases = {}
    for k, m in (d.get("aliases") or {}).items():
        if isinstance(m, dict):
            aliases[_txt(k, 80)] = {_txt(a, 80).upper(): _txt(b, 80).upper() for a, b in list(m.items())[:500]}
    return {"versao": VERSAO, "origem": _txt(d.get("origem"), 20) or "editado", "pagina": pagina,
            "relatorio": _vsecao(d.get("relatorio") or {}, 0, [0]), "aliases": aliases,
            "tabelas": _vtabelas(d.get("tabelas"))}


# =====================================================================================================
# formatos (DisplayFormat do Delphi -> texto pt-BR)
# =====================================================================================================
def _fmt_numero(v, fmt):
    secs = fmt.split(";")
    neg = v < 0
    f = secs[1] if neg and len(secs) > 1 and secs[1] else secs[0]
    if neg and len(secs) > 1 and secs[1]:
        v = -v
    if len(secs) > 2 and secs[2] and v == 0:
        f = secs[2]
    m = re.search(r"[#0][#0,.]*", f)
    if not m:
        return f.replace('"', "")
    mascara = m.group(0)
    pre, suf = f[:m.start()], f[m.end():]
    inteiro, _, dec = mascara.partition(".")
    casas = len(dec.replace(",", ""))
    milhar = "," in inteiro
    zeros = inteiro.replace(",", "").count("0")
    if "%" in suf and "%" not in pre:
        pass   # no Delphi o % é só um caractere (não multiplica)
    s = f"{abs(v) if not neg or len(secs) > 1 else abs(v):,.{casas}f}" if milhar else f"{abs(v):.{casas}f}"
    ip, _, dp = s.partition(".")
    ip = ip.replace(",", ".")
    if zeros > 1:
        ip = ip.replace(".", "").zfill(zeros)
        if milhar:
            ip = f"{int(ip):,}".replace(",", ".").rjust(zeros, "0")
    if zeros == 0 and ip == "0":
        ip = ""
    txt = ip + ("," + dp if casas else "")
    if neg and not (len(secs) > 1 and secs[1]):
        txt = "-" + txt
    pre = pre.replace('"', "").replace("'", "")
    suf = suf.replace('"', "").replace("'", "")
    return pre + txt + suf


_TOK_DATA = [("yyyy", "%Y"), ("yy", "%y"), ("mmmm", "%B"), ("mmm", "%b"), ("mm", "%m"), ("m", "%-m"),
             ("dddd", "%A"), ("ddd", "%a"), ("dd", "%d"), ("d", "%-d"), ("hh", "%H"), ("h", "%-H"),
             ("nn", "%M"), ("n", "%-M"), ("ss", "%S"), ("s", "%-S")]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]
_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _fmt_data(v, fmt):
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        v = dt.datetime(v.year, v.month, v.day)
    out, i, f = [], 0, fmt
    ultimo_h = False
    while i < len(f):
        ch = f[i]
        if ch in "\"'":
            j = f.find(ch, i + 1)
            j = len(f) if j < 0 else j
            out.append(f[i + 1:j])
            i = j + 1
            continue
        low = f[i:].lower()
        for tok, _ in _TOK_DATA:
            if low.startswith(tok):
                if tok in ("mm", "m") and ultimo_h:
                    out.append(f"{v.minute:02d}" if tok == "mm" else str(v.minute))
                elif tok == "yyyy":
                    out.append(f"{v.year:04d}")
                elif tok == "yy":
                    out.append(f"{v.year % 100:02d}")
                elif tok == "mmmm":
                    out.append(_MESES[v.month - 1])
                elif tok == "mmm":
                    out.append(_MESES[v.month - 1][:3])
                elif tok == "mm":
                    out.append(f"{v.month:02d}")
                elif tok == "m":
                    out.append(str(v.month))
                elif tok == "dddd":
                    out.append(_DIAS[v.weekday()])
                elif tok == "ddd":
                    out.append(_DIAS[v.weekday()][:3])
                elif tok == "dd":
                    out.append(f"{v.day:02d}")
                elif tok == "d":
                    out.append(str(v.day))
                elif tok in ("hh", "h"):
                    out.append(f"{v.hour:02d}" if tok == "hh" else str(v.hour))
                elif tok in ("nn", "n"):
                    out.append(f"{v.minute:02d}" if tok == "nn" else str(v.minute))
                elif tok in ("ss", "s"):
                    out.append(f"{v.second:02d}" if tok == "ss" else str(v.second))
                ultimo_h = tok in ("hh", "h")
                i += len(tok)
                break
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def formatar(v, fmt="", branco_zero=False):
    import decimal
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, (int, float)):
        if branco_zero and v == 0:
            return ""
        if fmt and re.search(r"[#0]", fmt):
            try:
                return _fmt_numero(float(v), fmt)
            except (ValueError, OverflowError):
                pass
        if isinstance(v, float):
            if v == int(v) and abs(v) < 1e15:
                return str(int(v))
            return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return str(v)
    if isinstance(v, (dt.date, dt.datetime)):
        if fmt and re.search(r"[dmyhn]", fmt, re.I):
            return _fmt_data(v, fmt)
        if isinstance(v, dt.datetime):
            return v.strftime("%d/%m/%Y %H:%M") if (v.hour or v.minute) else v.strftime("%d/%m/%Y")
        return v.strftime("%d/%m/%Y")
    if isinstance(v, dt.time):
        return v.strftime("%H:%M")
    if isinstance(v, (bytes, bytearray)):
        return ""
    return str(v)


# =====================================================================================================
# interpretador RAP (subconjunto do Pascal usado nas variáveis do ReportBuilder)
# =====================================================================================================
class ErroRAP(Exception):
    pass


_TOKEN = re.compile(r"""
    (?P<esp>\s+) | (?P<com>//[^\n]*|\{[^}]*\}|\(\*.*?\*\)) |
    (?P<num>\d+\.\d+(?:[eE][+-]?\d+)?|\d+) | (?P<str>'(?:[^']|'')*') | (?P<chr>\#\d+) |
    (?P<op>:=|<>|<=|>=|[-+*/=<>()\[\],;.:]) | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
""", re.S | re.X)
_PALAVRAS = {"begin", "end", "if", "then", "else", "var", "and", "or", "not", "div", "mod", "true", "false",
             "nil", "procedure", "function", "exit", "while", "do", "for", "to", "downto"}


def _tokens(src):
    out, i = [], 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise ErroRAP(f"caractere inesperado: {src[i]!r}")
        i = m.end()
        k = m.lastgroup
        if k in ("esp", "com"):
            continue
        v = m.group(k)
        if k == "str":
            out.append(("str", v[1:-1].replace("''", "'")))
        elif k == "chr":
            out.append(("str", chr(int(v[1:]))))
        elif k == "num":
            out.append(("num", float(v) if "." in v or "e" in v.lower() else int(v)))
        elif k == "id":
            out.append(("kw", v.lower()) if v.lower() in _PALAVRAS else ("id", v))
        else:
            out.append(("op", v))
    out.append(("fim", None))
    return out


class _Parser:
    """Gera uma árvore simples (tuplas) a partir do código."""

    def __init__(self, src):
        self.t = _tokens(src)
        self.i = 0

    def ver(self, k=None, v=None):
        tk = self.t[self.i]
        return (k is None or tk[0] == k) and (v is None or tk[1] == v)

    def pegar(self, k=None, v=None):
        tk = self.t[self.i]
        if (k and tk[0] != k) or (v is not None and tk[1] != v):
            raise ErroRAP(f"esperado {v or k}, veio {tk[1]!r}")
        self.i += 1
        return tk

    def programa(self):
        if self.ver("kw", "procedure") or self.ver("kw", "function"):
            while not self.ver("op", ";"):
                if self.ver("fim"):
                    raise ErroRAP("cabeçalho incompleto")
                if self.ver("op", "("):        # pula parâmetros
                    nivel = 0
                    while True:
                        tk = self.pegar()
                        if tk == ("op", "("):
                            nivel += 1
                        elif tk == ("op", ")"):
                            nivel -= 1
                            if nivel == 0:
                                break
                    continue
                self.pegar()
            self.pegar("op", ";")
        while self.ver("kw", "var"):
            self.pegar()
            while self.ver("id"):
                while not self.ver("op", ";"):
                    self.pegar()
                self.pegar("op", ";")
        return self.bloco()

    def bloco(self):
        self.pegar("kw", "begin")
        lista = []
        while not self.ver("kw", "end"):
            if self.ver("op", ";"):
                self.pegar()
                continue
            lista.append(self.comando())
        self.pegar("kw", "end")
        return ("bloco", lista)

    def comando(self):
        if self.ver("kw", "begin"):
            return self.bloco()
        if self.ver("kw", "if"):
            self.pegar()
            cond = self.expr()
            self.pegar("kw", "then")
            entao = ("bloco", []) if self.ver("kw", "else") or self.ver("op", ";") else self.comando()
            senao = None
            if self.ver("kw", "else"):
                self.pegar()
                senao = self.comando()
            return ("se", cond, entao, senao)
        if self.ver("kw", "exit"):
            self.pegar()
            return ("sair",)
        alvo = self.primario(atribuir=True)
        if self.ver("op", ":="):
            self.pegar()
            return ("atrib", alvo, self.expr())
        return ("expr", alvo)

    def expr(self):
        e = self.simples()
        while self.ver("op") and self.t[self.i][1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.pegar()[1]
            e = ("bin", op, e, self.simples())
        return e

    def simples(self):
        if self.ver("op", "-"):
            self.pegar()
            e = ("neg", self.termo())
        elif self.ver("op", "+"):
            self.pegar()
            e = self.termo()
        else:
            e = self.termo()
        while (self.ver("op") and self.t[self.i][1] in ("+", "-")) or self.ver("kw", "or"):
            op = self.pegar()[1]
            e = ("bin", op, e, self.termo())
        return e

    def termo(self):
        e = self.fator()
        while (self.ver("op") and self.t[self.i][1] in ("*", "/")) or self.ver("kw", "div") or self.ver("kw", "mod") \
                or self.ver("kw", "and"):
            op = self.pegar()[1]
            e = ("bin", op, e, self.fator())
        return e

    def fator(self):
        if self.ver("kw", "not"):
            self.pegar()
            return ("nao", self.fator())
        if self.ver("op", "-"):
            self.pegar()
            return ("neg", self.fator())
        return self.primario()

    def primario(self, atribuir=False):
        tk = self.t[self.i]
        if tk[0] == "num" or tk[0] == "str":
            self.pegar()
            e = ("lit", tk[1])
            while self.ver("str"):          # 'abc'#13#10 juntos
                e = ("bin", "+", e, ("lit", self.pegar()[1]))
            return e
        if tk == ("kw", "true") or tk == ("kw", "false"):
            self.pegar()
            return ("lit", tk[1] == "true")
        if tk == ("kw", "nil"):
            self.pegar()
            return ("lit", None)
        if tk == ("op", "("):
            self.pegar()
            e = self.expr()
            self.pegar("op", ")")
            return e
        if tk[0] == "id":
            self.pegar()
            e = ("nome", tk[1])
            while True:
                if self.ver("op", "["):
                    self.pegar()
                    idx = self.expr()
                    self.pegar("op", "]")
                    e = ("indice", e, idx)
                elif self.ver("op", "."):
                    self.pegar()
                    e = ("membro", e, self.pegar("id")[1])
                elif self.ver("op", "("):
                    self.pegar()
                    args = []
                    while not self.ver("op", ")"):
                        args.append(self.expr())
                        if self.ver("op", ","):
                            self.pegar()
                    self.pegar("op", ")")
                    e = ("chamar", e, args)
                else:
                    return e
        raise ErroRAP(f"não entendi {tk[1]!r}")


def compilar(src):
    """Código RAP -> árvore (ou ErroRAP)."""
    return _Parser(src or "begin end;").programa()


def _n(v):
    import decimal
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (dt.date, dt.datetime)):
        return v.toordinal()
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if "," in str(v) else float(v)
    except ValueError:
        return 0


def _s(v):
    import decimal
    if v is None:
        return ""
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, float):
        return (str(int(v)) if v == int(v) else repr(v).replace(".", ",")) if abs(v) < 1e15 else str(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return formatar(v)
    return str(v)


def _func(nome, a):
    n = nome.lower()
    try:
        if n == "formatfloat":
            return _fmt_numero(float(_n(a[1])), _s(a[0]))
        if n in ("formatdatetime",):
            return _fmt_data(a[1], _s(a[0])) if isinstance(a[1], (dt.date, dt.datetime)) else ""
        if n in ("inttostr", "floattostr", "vartostr", "currtostr"):
            return _s(a[0])
        if n in ("datetostr", "datetimetostr"):
            return formatar(a[0])
        if n in ("strtofloat", "strtocurr", "strtofloatdef"):
            return float(_n(a[0]))
        if n in ("strtoint", "strtointdef"):
            return int(_n(a[0]))
        if n == "trim":
            return _s(a[0]).strip()
        if n == "trimleft":
            return _s(a[0]).lstrip()
        if n == "trimright":
            return _s(a[0]).rstrip()
        if n == "uppercase":
            return _s(a[0]).upper()
        if n == "lowercase":
            return _s(a[0]).lower()
        if n == "copy":
            s, i, c = _s(a[0]), int(_n(a[1])), int(_n(a[2]))
            return s[max(i - 1, 0):max(i - 1, 0) + c]
        if n == "length":
            return len(_s(a[0]))
        if n == "pos":
            return _s(a[1]).find(_s(a[0])) + 1
        if n == "round":
            return int(math.floor(_n(a[0]) + 0.5)) if _n(a[0]) >= 0 else -int(math.floor(-_n(a[0]) + 0.5))
        if n == "trunc":
            return int(_n(a[0]))
        if n == "abs":
            return abs(_n(a[0]))
        if n in ("now", "date"):
            return dt.datetime.now() if n == "now" else dt.date.today()
        if n == "stringofchar":
            return _s(a[0]) * int(_n(a[1]))
        if n in ("varisnull", "varisempty"):
            return a[0] is None or a[0] == ""
        if n == "iif":
            return a[1] if a[0] else a[2]
        if n == "power":
            return _n(a[0]) ** _n(a[1])
        if n == "sqrt":
            return math.sqrt(_n(a[0]))
        if n == "yearof":
            return a[0].year
        if n == "monthof":
            return a[0].month
        if n == "dayof":
            return a[0].day
    except (IndexError, ValueError, TypeError, AttributeError, OverflowError):
        return None
    raise ErroRAP(f"função não suportada: {nome}")


class _Sair(Exception):
    pass


class Contexto:
    """O que um cálculo enxerga: campos das visões, outras variáveis e parâmetros."""

    def __init__(self, campo_fn, variaveis, aliases, parametros=None):
        self.campo_fn = campo_fn          # (visao, nome_ou_apelido) -> valor
        self.variaveis = variaveis        # nome -> estado {"valor"}
        self.aliases = aliases
        self.parametros = parametros or {}


def executar(arvore, valor, ctx, passos=20000):
    locais = {"value": valor}
    cont = [0]

    def ava(e):
        cont[0] += 1
        if cont[0] > passos:
            raise ErroRAP("cálculo longo demais")
        k = e[0]
        if k == "lit":
            return e[1]
        if k == "nome":
            n = e[1].lower()
            if n in locais:
                return locais[n]
            if n in ("now", "date"):
                return _func(n, [])
            v = ctx.variaveis.get(n)
            if v is not None:
                return v["valor"]
            return None
        if k == "indice":
            base = e[1]
            if base[0] == "nome":
                return ctx.campo_fn(base[1], _s(ava(e[2])))
            return None
        if k == "membro":
            alvo, m = e[1], e[2].lower()
            if alvo[0] == "nome":
                v = ctx.variaveis.get(alvo[1].lower())
                if v is not None and m in ("value", "text", "caption"):
                    return v["valor"]
            if m in ("searchexpression", "value", "text"):
                return ""                # Report.AutoSearchCriteriaByName(...).SearchExpression etc.
            return None
        if k == "chamar":
            alvo = e[1]
            args = [ava(x) for x in e[2]]
            if alvo[0] == "nome":
                return _func(alvo[1], args)
            if alvo[0] == "membro":
                return ""                # métodos de objetos do relatório: sem efeito aqui
            return None
        if k == "neg":
            return -_n(ava(e[1]))
        if k == "nao":
            return not ava(e[1])
        if k == "bin":
            op = e[1]
            a = ava(e[2])
            if op == "and":
                return bool(a) and bool(ava(e[3]))
            if op == "or":
                return bool(a) or bool(ava(e[3]))
            b = ava(e[3])
            if op == "+":
                if isinstance(a, str) or isinstance(b, str):
                    return _s(a) + _s(b)
                return _n(a) + _n(b)
            if op == "-":
                return _n(a) - _n(b)
            if op == "*":
                return _n(a) * _n(b)
            if op == "/":
                d = _n(b)
                return _n(a) / d if d else 0.0
            if op == "div":
                d = int(_n(b))
                return int(_n(a)) // d if d else 0
            if op == "mod":
                d = int(_n(b))
                return int(_n(a)) % d if d else 0
            if isinstance(a, str) or isinstance(b, str):
                a, b = _s(a).rstrip(), _s(b).rstrip()
            else:
                if isinstance(a, (dt.date, dt.datetime)) or isinstance(b, (dt.date, dt.datetime)):
                    a, b = _n(a), _n(b)
                else:
                    a, b = (_n(a), _n(b))
            return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        raise ErroRAP("expressão")

    def run(c):
        k = c[0]
        if k == "bloco":
            for x in c[1]:
                run(x)
        elif k == "se":
            if ava(c[1]):
                run(c[2])
            elif c[3] is not None:
                run(c[3])
        elif k == "atrib":
            alvo, v = c[1], ava(c[2])
            if alvo[0] == "nome":
                locais[alvo[1].lower()] = v
            elif alvo[0] == "membro" and alvo[1][0] == "nome":
                var = ctx.variaveis.get(alvo[1][1].lower())
                if var is not None:
                    var["valor"] = v
        elif k == "sair":
            raise _Sair()
        elif k == "expr":
            ava(c[1])

    try:
        run(arvore)
    except _Sair:
        pass
    return locais.get("value")


# =====================================================================================================
# geração do PDF
# =====================================================================================================
MM = 72.0 / 25.4


def _fonte_pdf(f):
    nome = (f.get("nome") or "Arial").lower()
    n, i = f.get("n"), f.get("i")
    if "courier" in nome or "draft" in nome or "console" in nome or "mono" in nome:
        base = ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique")
    elif "times" in nome or "roman" in nome or "georgia" in nome or "serif" == nome:
        base = ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic")
    else:
        base = ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique")
    return base[(1 if n else 0) + (2 if i else 0)], (88 if "17cpi" in nome else 100)


def _hex(c):
    from reportlab.lib import colors
    try:
        return colors.HexColor(c) if c else None
    except (ValueError, TypeError):
        return colors.black


class _Fonte:
    """Dados de uma visão: linhas como dicionários e ligação com a visão mestre."""

    def __init__(self, nome, colunas, linhas, mestre=None, ligacoes=None):
        self.nome = nome
        self.colunas = [c.upper() for c in colunas]
        self.linhas = [dict(zip(self.colunas, l)) for l in linhas]
        self.mestre = mestre
        self.ligacoes = [(a.upper(), b.upper()) for a, b in (ligacoes or [])]
        self._indice = None

    def filhas(self, linha_mestre):
        if not self.ligacoes or linha_mestre is None:
            return self.linhas
        if self._indice is None:
            self._indice = {}
            for l in self.linhas:
                self._indice.setdefault(tuple(_chave(l.get(d)) for _, d in self.ligacoes), []).append(l)
        return self._indice.get(tuple(_chave(linha_mestre.get(m)) for m, _ in self.ligacoes), [])


def _chave(v):
    import decimal
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


class _Render:
    def __init__(self, d, fontes, titulo, parametros):
        self.d = d
        self.fontes = {k.upper(): v for k, v in fontes.items()} if fontes else {}
        self.titulo = titulo
        self.parametros = parametros or {}
        pg = d["pagina"]
        self.larg, self.alt, self.mg = pg["largura"], pg["altura"], pg["margens"]
        self.aliases = {k.upper(): v for k, v in (d.get("aliases") or {}).items()}
        self.atual = {}            # visão -> linha atual
        self.vars = {}             # nome da variável (minúsculo) -> estado
        self.avisos = set()
        self.agora = dt.datetime.now()

    # ---------------------------------------------------------------- dados
    def fonte(self, visao):
        return self.fontes.get((visao or "").upper())

    def linha(self, visao):
        v = (visao or "").upper()
        if v in self.atual:
            return self.atual[v]
        f = self.fontes.get(v)
        if f is None:
            return None
        if f.mestre:                      # visão de consulta ligada à mestre: primeira linha ligada à atual
            lm = self.linha(f.mestre)
            ls = f.filhas(lm)
            return ls[0] if ls else None
        return f.linhas[0] if f.linhas else None

    def valor_campo(self, visao, campo, padrao_visao=None):
        campo = (campo or "").upper()
        vis = visao or padrao_visao
        l = self.linha(vis)
        if l is None or campo not in l:
            # campo de outra visão (o ReportBuilder às vezes guarda só o nome do campo)
            for nome, f in self.fontes.items():
                if campo in f.colunas:
                    l2 = self.linha(nome)
                    if l2 is not None:
                        return l2.get(campo)
            return None
        return l.get(campo)

    def campo_rap(self, visao, nome):
        al = self.aliases.get((visao or "").upper()) or next((m for k, m in self.aliases.items()
                                                              if k.upper() == (visao or "").upper()), {})
        campo = al.get(nome.upper(), nome.upper())
        return self.valor_campo(visao, campo)

    # ---------------------------------------------------------------- variáveis (cálculos RAP)
    def preparar_vars(self, sec):
        cont = [0]

        def andar(s):
            cont[0] += 1
            s["_id"] = cont[0]
            for b in self._todas_bandas(s):
                for it in b["itens"]:
                    if it["tipo"] == "variavel":
                        nome = (it.get("nome") or "").lower()
                        try:
                            arv = compilar(it.get("codigo") or "")
                            erro = None
                        except ErroRAP as e:
                            arv, erro = None, str(e)
                            self.avisos.add(f"{it.get('nome')}: {e}")
                        est = {"it": it, "arv": arv, "erro": erro, "valor": self._zero(it), "sec": s["_id"]}
                        it["_est"] = est
                        self.ests.append(est)            # todas calculam, mesmo com nome repetido
                        if nome and nome not in self.vars:
                            self.vars[nome] = est
                    elif it["tipo"] == "sub":
                        andar(it["secao"])
        andar(sec)

    @staticmethod
    def _zero(it):
        return {"numero": 0, "logico": False, "data": None}.get(it.get("tipo_dado"), "")

    @staticmethod
    def _todas_bandas(s):
        for b in s["bandas"].values():
            yield b
        for g in s["grupos"]:
            yield g["cab"]
            yield g["rod"]

    def calcular(self, sec, evento, grupo=None, linha=None):
        """linha: no percurso, a linha atual; cada cálculo roda uma vez por linha (o 1º cabeçalho já calcula a 1ª)."""
        ests = [e for e in self.ests if e["sec"] == sec.get("_id") and e["it"]["calc_tipo"] == evento
                and (grupo is None or e["it"].get("calc_grupo") in (grupo, None))]
        if linha is not None:
            ests = [e for e in ests if e.get("_ult") is not linha]
            for e in ests:
                e["_ult"] = linha
        ests.sort(key=lambda e: e["it"].get("ordem", 0))
        ctx = Contexto(self.campo_rap, self.vars, self.aliases, self.parametros)
        for e in ests:
            if e["arv"] is None:
                continue
            try:
                e["valor"] = executar(e["arv"], e["valor"], ctx)
            except (ErroRAP, RecursionError, TypeError, ValueError, AttributeError, OverflowError) as ex:
                self.avisos.add(f"{e['it'].get('nome')}: {ex}")

    def zerar(self, sec, evento, grupo=None):
        for e in self.ests:
            if e["sec"] == sec.get("_id") and e["it"]["reset_tipo"] == evento and \
                    (grupo is None or e["it"].get("reset_grupo") in (grupo, None)):
                e["valor"] = self._zero(e["it"])

    # ---------------------------------------------------------------- páginas
    def nova_pagina(self, primeira=False):
        if not primeira:
            self.fechar_pagina()
            self.c.showPage()
        self.pagina += 1
        self.y = 0.0
        self.limite = self.alt - self.mg["sup"] - self.mg["inf"] - self._altura_rodape()
        if not (primeira and self._titulo_antes and self._titulo_pendente):
            self._cabecalho()

    def _altura_rodape(self):
        b = self.d["relatorio"]["bandas"].get("rodape")
        return b["altura"] if b and b.get("visivel", True) else 0.0

    def _cabecalho(self):
        b = self.d["relatorio"]["bandas"].get("cabecalho")
        if b and b.get("visivel", True) and b["altura"] > 0:
            self.desenhar_banda(b, self.d["relatorio"], escopo=None, forcar=True)

    def fechar_pagina(self):
        b = self.d["relatorio"]["bandas"].get("rodape")
        if b and b.get("visivel", True) and b["altura"] > 0:
            y_antes = self.y
            self.y = self.alt - self.mg["sup"] - self.mg["inf"] - b["altura"]
            self._desenhar_itens(b["itens"], self.d["relatorio"], self.y, None)
            self.y = y_antes

    def espaco(self, h):
        if self.y + h > self.limite + 0.01 and self.y > 0.5:
            self.nova_pagina()
            return True
        return False

    # ---------------------------------------------------------------- desenho
    def _Y(self, y_mm):
        return (self.alt - self.mg["sup"] - y_mm) * MM

    def _X(self, x_mm):
        return (self.mg["esq"] + x_mm) * MM

    def texto_item(self, it, sec, escopo):
        t = it["tipo"]
        if t == "texto":
            return it.get("texto") or ""
        if t in ("campo", "memo"):
            v = self.valor_campo(it.get("visao"), it.get("campo"), sec.get("visao"))
            return formatar(v, it.get("formato") or "", it.get("branco_zero"))
        if t == "total":
            linhas = escopo.get(it.get("grupo_reset")) if escopo and it.get("grupo_reset") is not None else None
            if linhas is None and escopo:
                linhas = escopo.get("_banda")
            if linhas is None:
                linhas = escopo.get("_tudo") if escopo else []
            vals = []
            for l in linhas or []:
                if isinstance(l, dict):
                    vals.append(l.get(it.get("campo")))
            nums = [_n(v) for v in vals if v is not None]
            calc = it.get("calc", "soma")
            if calc == "contagem":
                r = len(vals)
            elif not nums:
                r = 0
            elif calc == "media":
                r = sum(nums) / len(nums)
            elif calc == "maximo":
                r = max(nums)
            elif calc == "minimo":
                r = min(nums)
            else:
                r = sum(nums)
            return formatar(r, it.get("formato") or "", it.get("branco_zero"))
        if t == "variavel":
            est = it.get("_est") or {}
            v = est.get("valor")
            return formatar(v, it.get("formato") or "", it.get("branco_zero"))
        if t == "sistema":
            s = it.get("sistema")
            tot = self.total_paginas or "?"
            if s == "pagina":
                return str(self.pagina)
            if s == "paginas":
                return str(tot)
            if s == "pagina_desc":
                return f"Página {self.pagina}"
            if s == "pagina_de":
                return f"{self.pagina} de {tot}"
            if s == "pagina_x_de_y":
                return f"Página {self.pagina} de {tot}"
            if s == "hora":
                return formatar(self.agora, it.get("formato") or "hh:nn")
            if s == "datahora":
                return formatar(self.agora, it.get("formato") or "dd/mm/yyyy hh:nn")
            return formatar(self.agora.date(), it.get("formato") or "dd/mm/yyyy")
        return ""

    def _linhas_quebradas(self, txt, fonte, tam, largura_pt):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        saida = []
        for par in (txt or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            palavras, atual = par.split(" "), ""
            for p in palavras:
                tent = (atual + " " + p) if atual else p
                if stringWidth(tent, fonte, tam) <= largura_pt or not atual:
                    atual = tent
                    while stringWidth(atual, fonte, tam) > largura_pt and len(atual) > 1:   # palavra maior que a caixa
                        k = len(atual)
                        while k > 1 and stringWidth(atual[:k], fonte, tam) > largura_pt:
                            k -= 1
                        saida.append(atual[:k])
                        atual = atual[k:]
                else:
                    saida.append(atual)
                    atual = p
            saida.append(atual)
        return saida

    def altura_item(self, it, sec, escopo):
        """Altura necessária (mm) para itens que esticam (memo / quebra de linha)."""
        if it["tipo"] not in ("memo", "texto", "campo") or not (it.get("quebra") and it.get("esticar", it["tipo"] == "memo")):
            return it["h"]
        f = it["fonte"]
        nome, _ = _fonte_pdf(f)
        linhas = self._linhas_quebradas(self.texto_item(it, sec, escopo), nome, f["tam"], max(it["w"] * MM - 1, 5))
        return max(it["h"] if it["tipo"] != "memo" else 0, len(linhas) * f["tam"] * 1.18 / MM + 0.5)

    def desenhar_texto(self, it, y0, txt):
        c = self.c
        f = it["fonte"]
        nome, escala = _fonte_pdf(f)
        tam = f["tam"]
        x, y, w, h = self._X(it["x"]), self._Y(y0 + it["y"]), it["w"] * MM, it["h"] * MM
        if it.get("fundo"):
            c.setFillColor(_hex(it["fundo"]))
            c.rect(x, y - h, w, h, stroke=0, fill=1)
        c.setFillColor(_hex(f.get("cor") or "#000000"))
        from reportlab.pdfbase.pdfmetrics import stringWidth
        largura = lambda s: stringWidth(s, nome, tam) * escala / 100.0
        if it.get("quebra"):
            linhas = self._linhas_quebradas(txt, nome, tam, max(w / (escala / 100.0) - 1, 5))
        else:
            linhas = [txt.replace("\r", "").split("\n")[0]] if txt else []
            if linhas and not it.get("auto") and largura(linhas[0]) > w + 0.5:      # corta como o ReportBuilder
                s = linhas[0]
                if it.get("alin") == "d":
                    while s and largura(s) > w:
                        s = s[1:]
                else:
                    while s and largura(s) > w:
                        s = s[:-1]
                linhas = [s]
        lead = tam * 1.18
        base = y - tam * 0.86
        for k, ln in enumerate(linhas):
            yy = base - k * lead
            to = c.beginText()
            to.setFont(nome, tam)
            to.setHorizScale(escala)
            lw = largura(ln)
            if it.get("alin") == "d":
                xx = x + w - lw
            elif it.get("alin") == "c":
                xx = x + (w - lw) / 2
            else:
                xx = x
            to.setTextOrigin(xx, yy)
            to.textOut(ln)
            c.drawText(to)
            if f.get("s") and ln:
                c.setLineWidth(max(tam / 18.0, 0.4))
                c.setStrokeColor(_hex(f.get("cor") or "#000000"))
                c.line(xx, yy - tam * 0.12, xx + lw, yy - tam * 0.12)

    def desenhar_forma(self, it, y0):
        c = self.c
        x, y, w, h = self._X(it["x"]), self._Y(y0 + it["y"]), it["w"] * MM, it["h"] * MM
        c.setStrokeColor(_hex(it.get("cor") or "#000000"))
        c.setLineWidth(max(it.get("espessura") or 0.75, 0.1))
        if it["tipo"] == "linha":
            pos = it.get("posicao", "topo")
            pts = {"topo": (x, y, x + w, y), "base": (x, y - h, x + w, y - h),
                   "esq": (x, y, x, y - h), "dir": (x + w, y, x + w, y - h)}[pos]
            c.line(*pts)
            if it.get("dupla"):
                d = 1.5
                if pos in ("topo", "base"):
                    c.line(pts[0], pts[1] - d, pts[2], pts[3] - d)
                else:
                    c.line(pts[0] + d, pts[1], pts[2] + d, pts[3])
            return
        fundo = it.get("fundo")
        if fundo:
            c.setFillColor(_hex(fundo))
        borda = 1 if (it.get("espessura") or 0) > 0 else 0
        if it.get("forma") == "arredondado":
            c.roundRect(x, y - h, w, h, min(w, h) * 0.12, stroke=borda, fill=1 if fundo else 0)
        elif it.get("forma") == "elipse":
            c.ellipse(x, y - h, x + w, y, stroke=borda, fill=1 if fundo else 0)
        else:
            c.rect(x, y - h, w, h, stroke=borda, fill=1 if fundo else 0)

    def _desenhar_itens(self, itens, sec, y0, escopo, pular_sub=True, deslocar=None):
        # formas primeiro (atrás), depois textos
        for it in sorted(itens, key=lambda i: 0 if i["tipo"] in ("retangulo",) else 1):
            if it["tipo"] == "sub" and pular_sub:
                continue
            yy = y0 + (deslocar(it) if deslocar else 0)
            if it["tipo"] in ("linha", "retangulo"):
                self.desenhar_forma(it, yy)
            elif it["tipo"] != "sub":
                self.desenhar_texto(it, yy, self.texto_item(it, sec, escopo))

    def desenhar_banda(self, b, sec, escopo, forcar=False):
        """Desenha uma banda na posição atual (quebrando página se não couber) e avança o cursor."""
        if not b or not b.get("visivel", True):
            return
        subs = sorted([i for i in b["itens"] if i["tipo"] == "sub"], key=lambda i: i["y"])
        alt = b["altura"]
        for it in b["itens"]:
            if b.get("dinamica", True) and it["tipo"] in ("memo", "texto", "campo") and it.get("quebra") and \
                    it.get("esticar", it["tipo"] == "memo"):
                alt = max(alt, it["y"] + self.altura_item(it, sec, escopo))
        if not subs:
            if not forcar:
                self.espaco(alt)
            self._desenhar_itens(b["itens"], sec, self.y, escopo)
            self.y += alt
            return
        # banda com sub-relatório(s): o que está acima do 1º sub, depois os subs (que podem crescer/quebrar
        # página), depois o que está abaixo, deslocado pelo quanto os subs cresceram
        primeiro = subs[0]
        acima = [i for i in b["itens"] if i["tipo"] != "sub" and i["y"] < primeiro["y"] + primeiro["h"]]
        abaixo = [i for i in b["itens"] if i["tipo"] != "sub" and i not in acima]
        self.espaco(max(primeiro["y"], 0.1) + 3)
        y_banda = self.y
        self._desenhar_itens(acima, sec, y_banda, escopo)
        self.y = y_banda + primeiro["y"]
        ultimo_fim = primeiro["y"] + primeiro["h"]
        for s in subs:
            alvo = y_banda + s["y"] if self.y < y_banda + s["y"] else self.y
            self.y = alvo
            self.secao(s["secao"], sub=True, x0=s["x"])
            ultimo_fim = s["y"] + s["h"]
        resto_alt = max(b["altura"] - ultimo_fim, 0)
        if abaixo:
            # o que estava abaixo dos sub-relatórios desce junto com o quanto eles cresceram
            self.espaco(resto_alt)
            self._desenhar_itens(abaixo, sec, self.y - ultimo_fim, escopo)
        self.y += resto_alt

    # ---------------------------------------------------------------- seção (relatório ou sub-relatório)
    def _pre_percurso(self, sec, vis, linhas):
        """Como no ReportBuilder: o título e os cabeçalhos já saem com os cálculos da 1ª linha."""
        if linhas and linhas[0]:
            antes = self.atual.get(vis)
            self.atual[vis] = linhas[0]
            self.calcular(sec, "percurso", linha=linhas[0])
            if antes is None:
                self.atual.pop(vis, None)
            else:
                self.atual[vis] = antes

    def secao(self, sec, sub=False, x0=0.0, principal=False):
        if x0:
            sec = self._deslocar_x(sec, x0)
        f = self.fonte(sec.get("visao"))
        if f is not None:
            mestre_linha = self.linha(f.mestre) if f.mestre else None
            linhas = f.filhas(mestre_linha) if f.mestre else f.linhas
        else:
            linhas = [{}]
        vis = (sec.get("visao") or "").upper()
        bandas = sec["bandas"]
        if sub:
            self.zerar(sec, "fim")           # o sub-relatório recomeça para cada linha da mestre
            if not linhas:
                return
        escopo = {"_tudo": linhas}
        if not principal:
            for e in self.ests:              # o sub-relatório recomeça: as linhas podem se repetir
                if e["sec"] == sec.get("_id"):
                    e.pop("_ult", None)
            self.zerar(sec, "inicio")
            self.calcular(sec, "inicio")
        self._pre_percurso(sec, vis, linhas)
        if sub:
            for t in ("titulo", "cabecalho"):
                if bandas.get(t):
                    self._com_linha(vis, linhas[0] if linhas else None,
                                    lambda bt=t: self.desenhar_banda(bandas[bt], sec, escopo))
        elif self._titulo_pendente:
            self._titulo_pendente = False
            if self._titulo_antes:
                self._com_linha(vis, linhas[0] if linhas else None,
                                lambda: self.desenhar_banda(bandas.get("titulo"), sec, escopo))
                self._cabecalho()
            else:
                self._com_linha(vis, linhas[0] if linhas else None,
                                lambda: self.desenhar_banda(bandas.get("titulo"), sec, escopo))
        grupos = sec["grupos"]
        chaves = [None] * len(grupos)
        inicio_grupo = [0] * len(grupos)
        detalhe = bandas.get("detalhe")
        for idx, l in enumerate(linhas):
            novas = [_chave(l.get(g["campo"])) for g in grupos]
            mudou = next((k for k in range(len(grupos)) if idx == 0 or novas[k] != chaves[k]), None)
            if mudou is not None:
                if idx > 0:
                    self._rodapes(sec, grupos, mudou, linhas, inicio_grupo, idx, escopo, vis)
                for k in range(mudou, len(grupos)):
                    inicio_grupo[k] = idx
                    self.zerar(sec, "inicio_grupo", k)
            # a linha entra no cálculo antes dos cabeçalhos de grupo (no RB o cabeçalho já mostra os valores dela)
            self.atual[vis] = l
            self.calcular(sec, "percurso", linha=l)
            if mudou is not None:
                for k in range(mudou, len(grupos)):
                    if grupos[k].get("nova_pagina") and idx > 0 and not sub:
                        self.nova_pagina()
                    self.atual[vis] = l
                    self.calcular(sec, "antes_cab_grupo", k)
                    fim = self._fim_grupo(linhas, idx, grupos, k)
                    escopo[k] = linhas[idx:fim]
                    escopo["_banda"] = linhas[idx:fim]
                    self.desenhar_banda(grupos[k]["cab"], sec, escopo)
                    self.calcular(sec, "inicio_grupo", k)
                chaves = novas
            self.atual[vis] = l
            escopo["_banda"] = [l]
            self.desenhar_banda(detalhe, sec, escopo)
        if linhas and grupos:
            self._rodapes(sec, grupos, 0, linhas, inicio_grupo, len(linhas), escopo, vis)
        self.calcular(sec, "fim")
        escopo["_banda"] = None
        if linhas:
            self.atual[vis] = linhas[-1]
        self.desenhar_banda(bandas.get("sumario"), sec, escopo)
        self.atual.pop(vis, None)

    @staticmethod
    def _fim_grupo(linhas, ini, grupos, k):
        chave = [_chave(linhas[ini].get(grupos[j]["campo"])) for j in range(k + 1)]
        fim = ini
        while fim < len(linhas) and [_chave(linhas[fim].get(grupos[j]["campo"])) for j in range(k + 1)] == chave:
            fim += 1
        return fim

    def _rodapes(self, sec, grupos, ate, linhas, inicio_grupo, idx, escopo, vis):
        for k in range(len(grupos) - 1, ate - 1, -1):
            self.atual[vis] = linhas[idx - 1]
            escopo[k] = linhas[inicio_grupo[k]:idx]
            escopo["_banda"] = escopo[k]
            self.calcular(sec, "antes_rodape_grupo", k)
            self.desenhar_banda(grupos[k]["rod"], sec, escopo)
            self.calcular(sec, "fim_grupo", k)
            self.zerar(sec, "fim_grupo", k)

    def _com_linha(self, vis, linha, fn):
        if linha is not None:
            self.atual[vis] = linha
        fn()

    @staticmethod
    def _deslocar_x(sec, x0):
        import copy
        s = copy.copy(sec)
        s["bandas"] = {k: {**b, "itens": [{**i, "x": i["x"] + x0} for i in b["itens"]]} for k, b in sec["bandas"].items()}
        s["grupos"] = [{**g, "cab": {**g["cab"], "itens": [{**i, "x": i["x"] + x0} for i in g["cab"]["itens"]]},
                        "rod": {**g["rod"], "itens": [{**i, "x": i["x"] + x0} for i in g["rod"]["itens"]]}}
                       for g in sec["grupos"]]
        return s          # as cópias levam junto o "_est" (estado das variáveis)

    # ---------------------------------------------------------------- tudo
    def gerar(self, total_paginas=None):
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        self.c = canvas.Canvas(buf, pagesize=(self.larg * MM, self.alt * MM))
        self.c.setTitle(self.titulo or "Relatório")
        self.total_paginas = total_paginas
        self.pagina = 0
        self.vars = {}
        self.ests = []
        self.atual = {}
        rel = self.d["relatorio"]
        self.preparar_vars(rel)
        self._titulo_antes = rel.get("titulo_antes", True)
        tb = rel["bandas"].get("titulo")
        self._titulo_pendente = bool(tb and tb.get("visivel", True) and (tb["altura"] > 0 or tb["itens"]))
        self.zerar(rel, "inicio")
        self.calcular(rel, "inicio")       # cálculos "no início" já valem para o 1º cabeçalho
        f = self.fonte(rel.get("visao"))
        self._pre_percurso(rel, (rel.get("visao") or "").upper(), f.linhas if f is not None else [])
        self.nova_pagina(primeira=True)
        self.secao(rel, principal=True)
        self.fechar_pagina()
        self.c.showPage()
        self.c.save()
        return buf.getvalue()


def _variaveis(d):
    """Todas as variáveis (cálculos) do desenho, inclusive dos sub-relatórios."""
    saida = []

    def secao(sc):
        for b in list((sc.get("bandas") or {}).values()) + [g.get(k) for g in sc.get("grupos") or [] for k in ("cab", "rod")]:
            for i in (b or {}).get("itens") or []:
                if i.get("tipo") == "variavel":
                    saida.append(i)
                elif i.get("tipo") == "sub" and i.get("secao"):
                    secao(i["secao"])
    secao((d or {}).get("relatorio") or {})
    return saida


def completar_codigos(salvo, original):
    """Layouts salvos antes de o painel ler o código de todas as versões do ReportBuilder ficaram com
    cálculos vazios: completa com o código do original (mesmo nome de variável). Devolve o desenho."""
    if not salvo or not original:
        return salvo
    cods = {}
    for v in _variaveis(original):
        if (v.get("codigo") or "").strip():
            cods.setdefault((v.get("nome") or "").lower(), v["codigo"])
    for v in _variaveis(salvo):
        if not (v.get("codigo") or "").strip() and (v.get("nome") or "").lower() in cods:
            v["codigo"] = cods[(v.get("nome") or "").lower()]
    return salvo


def _grade_para_sub(it):
    """Componente Tabela (grade): vira um sub-relatório com uma linha de títulos e uma linha por registro."""
    cols = it.get("colunas") or []
    total = sum(c["largura"] for c in cols) or 1
    fator = it["w"] / total
    f = it.get("fonte") or {"nome": "Arial", "tam": 8.0, "n": False, "i": False, "s": False, "cor": "#000000"}
    alt = it.get("alt_linha") or 5.0
    pad = 0.8
    ty = max((alt - (f.get("tam") or 8) * 0.3528 * 1.2) / 2, 0)    # texto centralizado na altura da linha
    cab, det, x = [], [], 0.0
    for c in cols:
        w = c["largura"] * fator
        base = {"y": ty, "h": alt - ty, "nome": "", "auto": False, "quebra": False, "branco_zero": False, "alin": c["alin"]}
        if it.get("bordas", True):
            borda = {"tipo": "retangulo", "x": x, "y": 0.0, "w": w, "h": alt, "nome": "", "forma": "retangulo",
                     "cor": it.get("cor_borda") or "#999999", "espessura": 0.5}
            cab.append({**borda, "fundo": it.get("cab_fundo")})
            det.append({**borda, "fundo": None})
        elif it.get("cab_fundo"):
            cab.append({"tipo": "retangulo", "x": x, "y": 0.0, "w": w, "h": alt, "nome": "", "forma": "retangulo",
                        "cor": it["cab_fundo"], "espessura": 0, "fundo": it["cab_fundo"]})
        cab.append({**base, "tipo": "texto", "x": x + pad, "w": max(w - 2 * pad, 0.5), "texto": c["titulo"] or c["campo"],
                    "fonte": {**f, "n": True}, "fundo": None, "formato": ""})
        det.append({**base, "tipo": "campo", "x": x + pad, "w": max(w - 2 * pad, 0.5), "campo": c["campo"],
                    "visao": it.get("visao"), "esticar": False, "fonte": dict(f), "fundo": None, "formato": c["formato"]})
        x += w
    bandas = {"detalhe": {"altura": alt, "visivel": True, "dinamica": True, "itens": det}}
    if it.get("cabecalho", True):
        bandas["titulo"] = {"altura": alt, "visivel": True, "dinamica": True, "itens": cab}
    return {"tipo": "sub", "x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"], "nome": it.get("nome") or "",
            "secao": {"visao": it.get("visao"), "bandas": bandas, "grupos": [], "titulo_antes": True}}


def expandir_grades(d):
    """Troca cada componente Tabela por um sub-relatório equivalente (o desenho já validado)."""
    def banda(b):
        if b:
            b["itens"] = [(_grade_para_sub(i) if i["tipo"] == "grade" else i) for i in b["itens"]]
            for i in b["itens"]:
                if i["tipo"] == "sub":
                    secao(i["secao"])

    def secao(sc):
        for b in sc["bandas"].values():
            banda(b)
        for g in sc.get("grupos") or []:
            banda(g.get("cab"))
            banda(g.get("rod"))
    secao(d["relatorio"])
    return d


def gerar_pdf(desenho, visoes, titulo="", parametros=None, info_visoes=None):
    """visoes: lista [{nome, colunas, linhas}] (resultado do relatorios_rb.executar);
    info_visoes: [{nome, mestre, ligacoes}] (do catálogo) para ligar mestre/detalhe."""
    info = {v["nome"].upper(): v for v in (info_visoes or [])}
    fontes = {}
    for v in visoes:
        i = info.get(v["nome"].upper(), {})
        fontes[v["nome"]] = _Fonte(v["nome"], v.get("colunas") or [], v.get("linhas") or [],
                                   (i.get("mestre") or "").upper() or None, i.get("ligacoes"))
    d = expandir_grades(validar(desenho))
    r1 = _Render(expandir_grades(validar(desenho)), fontes, titulo, parametros)
    r1.gerar()
    r2 = _Render(d, fontes, titulo, parametros)
    pdf = r2.gerar(total_paginas=r1.pagina)
    return pdf, sorted(r2.avisos)[:20]
