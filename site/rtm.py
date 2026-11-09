"""Arquivos .rtm do ReportBuilder (modelo de relatório do Delphi).

- exportar(desenho, original)  gera o .rtm com o layout do painel. Com o modelo original do ReportBuilder
  (RB_ITEM.TEMPLATE), mantém tudo o que o painel não edita (consultas, parâmetros, configurações) e troca
  só as bandas, os itens e o código dos cálculos.
- ler(arquivo)                 lê um .rtm (binário ou texto) e devolve a árvore de objetos do modelo.

O formato é o DFM do Delphi: "TPF0" + objeto (classe, nome, propriedades, filhos).
"""
import re
import struct

from rb_sync import _Leitor

# ---------------------------------------------------------------------------------------------- valores
class Ident(str):
    """Identificador do Delphi (ex.: taCentered, clBlack, referência a outro componente)."""


class Conj(list):
    """Conjunto do Delphi (ex.: [fsBold, fsItalic])."""


class Ext(float):
    """Número com ponto flutuante gravado como Extended (10 bytes)."""


class Lista(list):
    """Lista do Delphi (ex.: Lines.Strings)."""


def _sstr(s):
    b = s.encode("cp1252", "replace")[:255]
    return bytes([len(b)]) + b


def _extended(x):
    """float -> Extended de 80 bits (little endian)."""
    if x == 0:
        return b"\x00" * 10
    sinal = 0x8000 if x < 0 else 0
    x = abs(x)
    import math
    m, e = math.frexp(x)                       # x = m * 2**e, 0.5 <= m < 1
    mant = int(m * (1 << 64)) & 0xFFFFFFFFFFFFFFFF
    exp = e - 1 + 16383
    return struct.pack("<QH", mant, sinal | exp)


def valor(v):
    """Valor Python -> bytes no formato binário do DFM."""
    if v is None:
        return b"\x0d"
    if isinstance(v, bool):
        return b"\x09" if v else b"\x08"
    if isinstance(v, Ident):
        return b"\x07" + _sstr(v)
    if isinstance(v, Conj):
        return b"\x0b" + b"".join(_sstr(x) for x in v) + b"\x00"
    if isinstance(v, Lista):
        return b"\x01" + b"".join(valor(x) for x in v) + b"\x00"
    if isinstance(v, Ext):
        return b"\x05" + _extended(float(v))
    if isinstance(v, int):
        if -128 <= v <= 127:
            return b"\x02" + struct.pack("<b", v)
        if -32768 <= v <= 32767:
            return b"\x03" + struct.pack("<h", v)
        return b"\x04" + struct.pack("<i", v)
    if isinstance(v, float):
        return b"\x05" + _extended(v)
    if isinstance(v, (bytes, bytearray)):
        return b"\x0a" + struct.pack("<I", len(v)) + bytes(v)
    s = str(v)
    try:
        b = s.encode("ascii")
        if len(b) <= 255:
            return b"\x06" + bytes([len(b)]) + b
        return b"\x0c" + struct.pack("<I", len(b)) + b
    except UnicodeEncodeError:
        b = s.encode("utf-8")
        return b"\x14" + struct.pack("<I", len(b)) + b


# ---------------------------------------------------------------------------------------------- árvore sem perdas
def _no(classe, nome, props=None, filhos=None):
    """props: lista de (nome, valor Python)."""
    return {"classe": classe, "nome": nome, "pre": b"",
            "props": [(k, valor(v), v) for k, v in (props or []) if v is not None or k == "_"],
            "filhos": filhos or []}


def _ler_no(L):
    ini = L.i
    f = L.b[L.i]
    pre = b""
    if f & 0xF0 == 0xF0:
        L.i += 1
        if f & 2:
            L.valor()
        pre = L.b[ini:L.i]
    classe, nome = L.sstr(), L.sstr()
    props = []
    while True:
        p = L.sstr()
        if not p:
            break
        a = L.i
        v = L.valor()
        props.append((p, L.b[a:L.i], v))
    filhos = []
    while L.i < len(L.b) and L.b[L.i] != 0:
        filhos.append(_ler_no(L))
    L.i += 1
    return {"classe": classe, "nome": nome, "pre": pre, "props": props, "filhos": filhos}


def _gravar_no(n):
    out = [n.get("pre") or b"", _sstr(n["classe"]), _sstr(n["nome"])]
    for k, raw, _v in n["props"]:
        out.append(_sstr(k))
        out.append(raw)
    out.append(b"\x00")
    for f in n["filhos"]:
        out.append(_gravar_no(f))
    out.append(b"\x00")
    return b"".join(out)


def ler_binario(b):
    """Modelo binário -> árvore sem perdas (as propriedades guardam os bytes originais)."""
    if bytes(b[:4]) != b"TPF0":
        raise ValueError("Não é um modelo binário do ReportBuilder.")
    L = _Leitor(bytes(b), 4)
    arv = _ler_no(L)
    arv["cauda"] = bytes(b[L.i:])          # alguns modelos terminam com bytes extras (zeros)
    return arv


def gravar(arv):
    return b"TPF0" + _gravar_no(arv) + (arv.get("cauda") or b"")


def para_desenho(n):
    """Árvore sem perdas -> árvore simples (props como dicionário) usada pelo desenho.importar_arvore."""
    return {"classe": n["classe"], "nome": n["nome"], "props": {k: v for k, _r, v in n["props"]},
            "filhos": [para_desenho(f) for f in n["filhos"]]}


def _prop(n, nome, padrao=None):
    for k, _r, v in n["props"]:
        if k == nome:
            return v
    return padrao


def _por(n, nome, v):
    raw = valor(v)
    for i, (k, _r, _v) in enumerate(n["props"]):
        if k == nome:
            n["props"][i] = (k, raw, v)
            return
    n["props"].append((nome, raw, v))


def _todos(n):
    yield n
    for f in n["filhos"]:
        yield from _todos(f)


# ---------------------------------------------------------------------------------------------- .rtm em texto
_TOK = re.compile(r"""\s*(?:
    (?P<str>(?:'(?:[^']|'')*'|\#\d+)+) |
    (?P<num>[-+]?\d+\.\d+(?:[eE][-+]?\d+)?|[-+]?\$[0-9A-Fa-f]+|[-+]?\d+) |
    (?P<id>[A-Za-z_][\w.]*) |
    (?P<sym>[=\[\](){}<>,:+])
)""", re.X)


def _texto_str(t):
    out, i = [], 0
    while i < len(t):
        if t[i] == "'":
            j = i + 1
            buf = []
            while j < len(t):
                if t[j] == "'":
                    if j + 1 < len(t) and t[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(t[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
        elif t[i] == "#":
            j = i + 1
            while j < len(t) and t[j].isdigit():
                j += 1
            out.append(chr(int(t[i + 1:j])))
            i = j
        else:
            i += 1
    return "".join(out)


class _Texto:
    def __init__(self, s):
        self.s, self.i = s, 0

    def _pular(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def tok(self, olhar=False):
        self._pular()
        m = _TOK.match(self.s, self.i)
        if not m:
            if self.i >= len(self.s):
                return None, None
            raise ValueError(f"Arquivo .rtm inválido perto de: {self.s[self.i:self.i + 30]!r}")
        k = m.lastgroup
        v = m.group(k)
        if not olhar:
            self.i = m.end()
        return k, v

    def esperar(self, sym):
        k, v = self.tok()
        if v != sym:
            raise ValueError(f"Arquivo .rtm inválido: esperava {sym!r}, veio {v!r}")

    def valor(self):
        k, v = self.tok()
        if k == "str":
            s = _texto_str(v)
            while self.tok(True)[1] == "+":
                self.tok()
                k2, v2 = self.tok()
                s += _texto_str(v2)
            return s
        if k == "num":
            if "." in v or "e" in v.lower() and not v.lstrip("+-").startswith("$"):
                return float(v)
            neg = v.startswith("-")
            v = v.lstrip("+-")
            n = int(v[1:], 16) if v.startswith("$") else int(v)
            return -n if neg else n
        if k == "id":
            if v.lower() == "true":
                return True
            if v.lower() == "false":
                return False
            if v.lower() == "nil":
                return None
            return Ident(v)
        if v == "[":
            itens = Conj()
            while self.tok(True)[1] != "]":
                kk, vv = self.tok()
                if vv != ",":
                    itens.append(vv)
            self.tok()
            return itens
        if v == "(":
            itens = Lista()
            while self.tok(True)[1] != ")":
                itens.append(self.valor())
            self.tok()
            return itens
        if v == "{":
            fim = self.s.index("}", self.i)
            hexa = re.sub(r"\s+", "", self.s[self.i:fim])
            self.i = fim + 1
            return bytes.fromhex(hexa)
        if v == "<":                        # coleção: < item ... end item ... end >
            itens = []
            while True:
                k2, v2 = self.tok()
                if v2 == ">":
                    return itens
                if v2 and v2.lower() == "item":
                    props = {}
                    while True:
                        k3, v3 = self.tok(True)
                        if v3 and v3.lower() == "end":
                            self.tok()
                            break
                        nome = self.tok()[1]
                        self.esperar("=")
                        props[nome] = self.valor()
                    itens.append(props)
        raise ValueError(f"Valor inesperado no .rtm: {v!r}")

    def objeto(self):
        k, v = self.tok()
        if not v or v.lower() not in ("object", "inherited", "inline"):
            raise ValueError("Arquivo .rtm em texto inválido (esperava 'object').")
        nome = self.tok()[1]
        classe = ""
        if self.tok(True)[1] == ":":
            self.tok()
            classe = self.tok()[1]
        else:
            nome, classe = "", nome
        if self.tok(True)[1] == "[":         # índice de herança
            while self.tok()[1] != "]":
                pass
        props, filhos = [], []
        while True:
            k, v = self.tok(True)
            if v is None:
                raise ValueError("Arquivo .rtm em texto incompleto.")
            lv = v.lower()
            if lv == "end":
                self.tok()
                break
            if lv in ("object", "inherited", "inline"):
                filhos.append(self.objeto())
                continue
            self.tok()
            self.esperar("=")
            val = self.valor()
            props.append((v, val))
        return {"classe": classe, "nome": nome, "pre": b"",
                "props": [(k2, valor(v2) if not isinstance(v2, list) or isinstance(v2, (Conj, Lista)) else b"\x0e\x00", v2)
                          for k2, v2 in props],
                "filhos": filhos}


def ler(arquivo):
    """Arquivo .rtm (binário ou texto) -> árvore sem perdas."""
    b = bytes(arquivo or b"")
    if b[:4] == b"TPF0":
        return ler_binario(b)
    for cod in ("utf-8-sig", "cp1252"):
        try:
            txt = b.decode(cod)
            break
        except UnicodeDecodeError:
            continue
    if not re.match(r"\s*(object|inherited|inline)\s", txt, re.I):
        raise ValueError("Este arquivo não é um modelo do ReportBuilder (.rtm).")
    arv = _Texto(txt).objeto()
    if arv["classe"] != "TppReport":
        raise ValueError(f"O arquivo tem um {arv['classe'] or 'objeto'} e não um relatório (TppReport).")
    return arv


# ---------------------------------------------------------------------------------------------- desenho -> objetos
_BANDA_RB = {"titulo": ("TppTitleBand", 1), "cabecalho": ("TppHeaderBand", 2), "detalhe": ("TppDetailBand", 4),
             "rodape": ("TppFooterBand", 6), "sumario": ("TppSummaryBand", 7)}
_ORDEM_BANDAS = ("titulo", "cabecalho", "detalhe", "rodape", "sumario")
_CLASSES_BANDA = {"TppTitleBand", "TppHeaderBand", "TppDetailBand", "TppFooterBand", "TppSummaryBand", "TppGroup"}
_ALIN = {"e": "taLeftJustified", "c": "taCentered", "d": "taRightJustified"}
_SIS = {"data": "vtDate", "hora": "vtTime", "datahora": "vtDateTime", "pagina": "vtPageNo", "pagina_desc": "vtPageNoDesc",
        "paginas": "vtPageCount", "pagina_de": "vtPageSet", "pagina_x_de_y": "vtPageSetDesc"}
_CALC = {"soma": "dcSum", "contagem": "dcCount", "media": "dcAverage", "maximo": "dcMaximum", "minimo": "dcMinimum"}
_EVENTO = {"percurso": "veTraversal", "antes_rodape_grupo": "veGroupBeforeFooter", "antes_cab_grupo": "veGroupBeforeHeader",
           "inicio_grupo": "veGroupStart", "fim_grupo": "veGroupEnd", "inicio_pagina": "vePageStart",
           "fim_pagina": "vePageEnd", "inicio": "veReportStart", "fim": "veReportEnd"}
_TIPO = {"texto": "dtString", "numero": "dtDouble", "logico": "dtBoolean", "data": "dtDateTime"}
_CORES = {"#000000": "clBlack", "#ffffff": "clWhite"}


def _um(v):
    return int(round(float(v or 0) * 1000))


def _cor(c, padrao="#000000"):
    c = (c or padrao).lower()
    if c in _CORES:
        return Ident(_CORES[c])
    try:
        r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    except (ValueError, IndexError):
        return Ident("clBlack")
    return (b << 16) | (g << 8) | r                  # Delphi: $00BBGGRR


class _Montador:
    def __init__(self, arv, d):
        self.arv, self.d = arv, d
        self.nomes = {n["nome"].lower() for n in _todos(arv) if n["nome"]}
        self.contador = {}
        # pipelines: nome que aparece no layout -> referência "dataview.pipeline"
        self.pipes = {}
        for dv in _todos(arv):
            for pl in dv["filhos"]:
                if pl["classe"] in ("TppChildDBPipeline", "TppDBPipeline", "TppBDEPipeline", "TppJITPipeline"):
                    ref = f"{dv['nome']}.{pl['nome']}" if dv["classe"] != "TppReport" else pl["nome"]
                    for k in (pl["nome"], _prop(pl, "UserName")):
                        if k:
                            self.pipes[str(k).upper()] = ref
        camada = next((n for n in _todos(arv) if n["classe"] == "TppDesignLayer"), None)
        self.camada = camada["nome"] if camada else None
        self.grupos_nome = {}
        self.codigos = []                            # (nome do componente, código)

    def nome(self, base):
        n = self.contador.get(base, 0)
        while True:
            n += 1
            nm = f"{base}{n}"
            if nm.lower() not in self.nomes:
                self.nomes.add(nm.lower())
                self.contador[base] = n
                return nm

    def _pipe(self, visao, padrao):
        v = (visao or padrao or "")
        return self.pipes.get(v.upper()), v

    def _comuns(self, it, banda_tipo, grupo):
        p = []
        if self.camada:
            p.append(("DesignLayer", Ident(self.camada)))
        return p, [("mmHeight", _um(it["h"])), ("mmLeft", _um(it["x"])), ("mmTop", _um(it["y"])), ("mmWidth", _um(it["w"])),
                   ("BandType", banda_tipo)] + ([("GroupNo", grupo)] if grupo is not None else []) + \
            ([("LayerName", Ident("Foreground"))] if self.camada else [])

    def _fonte(self, it):
        f = it.get("fonte") or {}
        est = Conj([x for k, x in (("n", "fsBold"), ("i", "fsItalic"), ("s", "fsUnderline")) if f.get(k)])
        p = [("Font.Charset", Ident("DEFAULT_CHARSET")), ("Font.Color", _cor(f.get("cor"))),
             ("Font.Name", f.get("nome") or "Arial"), ("Font.Size", int(round(float(f.get("tam") or 10)))), ("Font.Style", est)]
        if it.get("alin") in ("c", "d"):
            p.append(("TextAlignment", Ident(_ALIN[it["alin"]])))
        if it.get("fundo"):
            p += [("Color", _cor(it["fundo"])), ("Transparent", False)]
        else:
            p.append(("Transparent", True))
        if it.get("quebra"):
            p.append(("WordWrap", True))
        return p

    def item(self, it, sec, banda_tipo, grupo):
        t = it["tipo"]
        antes, fim = self._comuns(it, banda_tipo, grupo)
        un = lambda base: [("UserName", (it.get("nome") or "")[:40] or base)]  # noqa: E731
        if t == "texto":
            txt = it.get("texto") or ""
            if "\n" in txt:
                nm = self.nome("ppMemo")
                return _no("TppMemo", nm, antes + un(nm[2:]) + [("Caption", "Memo")] + self._fonte(it) +
                           [("Lines.Strings", Lista(txt.split("\n"))), ("Stretch", True)] + fim)
            nm = self.nome("ppLabel")
            return _no("TppLabel", nm, antes + un(nm[2:]) + [("AutoSize", bool(it.get("auto"))), ("Caption", txt)] +
                       self._fonte(it) + fim)
        if t in ("campo", "memo", "total"):
            ref, vis = self._pipe(it.get("visao"), sec.get("visao"))
            dados = [("DataField", it.get("campo") or "")] + ([("DataPipeline", Ident(ref))] if ref else [])
            extra = [("DisplayFormat", it["formato"])] if it.get("formato") else []
            if it.get("branco_zero"):
                extra.append(("BlankWhenZero", True))
            if t == "campo":
                nm = self.nome("ppDBText")
                return _no("TppDBText", nm, antes + un(nm[2:]) + dados + extra + self._fonte(it) +
                           ([("AutoSize", True)] if it.get("auto") else []) + [("DataPipelineName", vis)] + fim)
            if t == "memo":
                nm = self.nome("ppDBMemo")
                return _no("TppDBMemo", nm, antes + un(nm[2:]) + [("CharWrap", False)] + dados + extra + self._fonte(it) +
                           [("Stretch", bool(it.get("esticar", True))), ("DataPipelineName", vis)] + fim)
            nm = self.nome("ppDBCalc")
            g = it.get("grupo_reset")
            return _no("TppDBCalc", nm, antes + un(nm[2:]) + dados + extra +
                       [("DBCalcType", Ident(_CALC.get(it.get("calc"), "dcSum")))] + self._fonte(it) +
                       ([("ResetGroup", Ident(self.grupos_nome[g]))] if g in self.grupos_nome else []) +
                       [("DataPipelineName", vis)] + fim)
        if t == "variavel":
            nm = self.nome("ppVariable")
            usuario = (it.get("nome") or "")[:40] or nm[2:]
            if (it.get("codigo") or "").strip():
                self.codigos.append((usuario, it["codigo"]))
            ref = [("CalcComponent", Ident(self.grupos_nome[it["calc_grupo"]]))] if it.get("calc_grupo") in self.grupos_nome else []
            rst = [("ResetComponent", Ident(self.grupos_nome[it["reset_grupo"]]))] if it.get("reset_grupo") in self.grupos_nome else []
            return _no("TppVariable", nm, antes + [("UserName", usuario), ("AutoSize", bool(it.get("auto"))),
                                                  ("BlankWhenZero", bool(it.get("branco_zero"))),
                                                  ("CalcOrder", int(it.get("ordem") or 0))] + ref +
                       [("CalcType", Ident(_EVENTO.get(it.get("calc_tipo"), "veTraversal"))),
                        ("DataType", Ident(_TIPO.get(it.get("tipo_dado"), "dtString")))] +
                       ([("DisplayFormat", it["formato"])] if it.get("formato") else []) + self._fonte(it) + rst +
                       [("ResetType", Ident(_EVENTO.get(it.get("reset_tipo"), "veReportEnd")))] + fim)
        if t == "sistema":
            nm = self.nome("ppSystemVariable")
            return _no("TppSystemVariable", nm, antes + un(nm[2:]) + [("AutoSize", bool(it.get("auto"))), ("VarType", Ident(_SIS.get(it.get("sistema"), "vtDate")))] +
                       ([("DisplayFormat", it["formato"])] if it.get("formato") else []) + self._fonte(it) + fim)
        if t == "linha":
            nm = self.nome("ppLine")
            pos = {"topo": "lpTop", "base": "lpBottom", "esq": "lpLeft", "dir": "lpRight"}.get(it.get("posicao"), "lpTop")
            return _no("TppLine", nm, antes + un(nm[2:]) + [("Pen.Color", _cor(it.get("cor"))), ("Position", Ident(pos))] +
                       ([("Style", Ident("lsDouble"))] if it.get("dupla") else []) +
                       [("Weight", Ext(float(it.get("espessura") or 0.75)))] + fim)
        if t == "retangulo":
            nm = self.nome("ppShape")
            forma = {"arredondado": "stRoundRect", "elipse": "stEllipse"}.get(it.get("forma"), "stRectangle")
            pincel = [("Brush.Color", _cor(it["fundo"]))] if it.get("fundo") else [("Brush.Style", Ident("bsClear"))]
            return _no("TppShape", nm, antes + un(nm[2:]) + pincel +
                       [("Pen.Color", _cor(it.get("cor"))), ("Pen.Width", max(1, int(round(float(it.get("espessura") or 0.75) / 0.75)))),
                        ("Shape", Ident(forma))] + fim)
        if t == "sub":
            nm = self.nome("ppSubReport")
            filho = self.nome("ppChildReport")
            sc = it.get("secao") or {}
            ref, vis = self._pipe(sc.get("visao"), None)
            ch = _no("TppChildReport", filho, [("AutoStop", False)] + ([("DataPipeline", Ident(ref))] if ref else []) +
                     self._papel() + [("Version", str(_prop(self.arv, "Version") or "6.02")), ("mmColumnWidth", 0),
                                      ("DataPipelineName", vis or "")])
            salvo_grupos = self.grupos_nome
            self.grupos_nome = {}
            ch["filhos"] = self.secao(sc)
            self.grupos_nome = salvo_grupos
            return _no("TppSubReport", nm, antes + un(nm[2:]) + [("ExpandAll", False), ("NewPrintJob", False),
                                                               ("TraverseAllData", False), ("DataPipelineName", vis or "")] + fim,
                       [ch])
        return None

    def _papel(self):
        pg = self.d["pagina"]
        mg = pg["margens"]
        deitado = pg["largura"] > pg["altura"]
        return [("PrinterSetup.mmMarginBottom", _um(mg["inf"])), ("PrinterSetup.mmMarginLeft", _um(mg["esq"])),
                ("PrinterSetup.mmMarginRight", _um(mg["dir"])), ("PrinterSetup.mmMarginTop", _um(mg["sup"])),
                ("PrinterSetup.mmPaperHeight", _um(max(pg["largura"], pg["altura"]) if deitado else pg["altura"])),
                ("PrinterSetup.mmPaperWidth", _um(min(pg["largura"], pg["altura"]) if deitado else pg["largura"])),
                ("PrinterSetup.Orientation", Ident("poLandscape" if deitado else "poPortrait"))]

    def banda(self, classe, b, sec, banda_tipo, grupo=None, extra=()):
        nm = self.nome("pp" + classe[3:])
        props = [("mmBottomOffset", 0), ("mmHeight", _um(b.get("altura"))), ("mmPrintPosition", 0)]
        if classe == "TppDetailBand" and b.get("dinamica") is False:
            props.insert(0, ("PrintHeight", Ident("phStatic")))
        if b.get("visivel") is False:
            props.append(("Visible", False))
        n = _no(classe, nm, list(extra) + props)
        for it in b.get("itens") or []:
            x = self.item(it, sec, banda_tipo, grupo)
            if x:
                n["filhos"].append(x)
        return n

    def secao(self, sc):
        """Bandas e grupos de uma seção (relatório ou sub-relatório), na ordem do ReportBuilder."""
        filhos = []
        bandas = sc.get("bandas") or {}
        grupos = sc.get("grupos") or []
        nomes_g = [self.nome("ppGroup") for _ in grupos]
        self.grupos_nome = {i: n for i, n in enumerate(nomes_g)}
        for t in _ORDEM_BANDAS:
            b = bandas.get(t)
            if b is None and t != "detalhe":
                continue
            classe, bt = _BANDA_RB[t]
            filhos.append(self.banda(classe, b or {"altura": 5, "itens": []}, sc, bt))
        for i, g in enumerate(grupos):
            ref, vis = self._pipe(g.get("visao"), sc.get("visao"))
            gn = _no("TppGroup", nomes_g[i], [("BreakName", g.get("campo") or "")] + ([("DataPipeline", Ident(ref))] if ref else []) +
                     [("KeepTogether", True), ("NewPage", bool(g.get("nova_pagina"))), ("UserName", f"Group{i + 1}"),
                      ("DataPipelineName", vis or "")])
            gn["filhos"] = [self.banda("TppGroupHeaderBand", g.get("cab") or {"altura": 0, "itens": []}, sc, 8, i),
                            self.banda("TppGroupFooterBand", g.get("rod") or {"altura": 0, "itens": []}, sc, 9, i,
                                       extra=[("HideWhenOneDetail", False)])]
            filhos.append(gn)
        return filhos


def _codigo_rb(nome, codigo):
    """O ReportBuilder guarda o evento inteiro: procedure NomeOnCalc(var Value: Variant); begin ... end;"""
    c = (codigo or "").strip()
    if re.match(r"(?is)^procedure\s", c):
        return (codigo or "").lstrip().replace("\r\n", "\n").replace("\n", "\r\n")
    if True:
        corpo = c if re.match(r"(?is)^begin\b", c) else "begin\r\n  " + c.replace("\n", "\r\n  ") + "\r\nend;"
        c = f"procedure {nome}OnCalc(var Value: Variant);\r\n{corpo}"
    return c.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n"


def exportar(d, original=None):
    """Desenho (validado) -> bytes do .rtm. original: modelo do ReportBuilder (RB_ITEM.TEMPLATE) para manter
    consultas, parâmetros e configurações; sem ele não há consultas no arquivo (só o layout)."""
    import desenho as dz
    d = dz.expandir_grades(dz.validar(d))
    if original:
        arv = ler(original)
    else:
        arv = _no("TppReport", "ppReport1", [("AutoStop", False), ("PrinterSetup.BinName", "Default"),
                                             ("PrinterSetup.DocumentName", "Report"), ("PrinterSetup.PrinterName", "Default"),
                                             ("Units", Ident("utMillimeters")), ("Version", "6.02"), ("mmColumnWidth", 0)])
    m = _Montador(arv, d)
    rel = d["relatorio"]
    for k, v in m._papel():
        _por(arv, k, v)
    ref, vis = m._pipe(rel.get("visao"), None)
    if ref:
        _por(arv, "DataPipeline", Ident(ref))
        _por(arv, "DataPipelineName", vis)
    elif vis and not original:
        _por(arv, "DataPipelineName", vis)          # sem o modelo do ERP: guarda o nome da visão principal
    novos = m.secao(rel)
    pos = next((i for i, f in enumerate(arv["filhos"]) if f["classe"] in _CLASSES_BANDA), None)
    resto = [f for f in arv["filhos"] if f["classe"] not in _CLASSES_BANDA]
    if pos is None:
        pos = next((i for i, f in enumerate(resto) if f["classe"] in ("TraCodeModule", "TdaDataModule")), len(resto))
    else:
        pos = sum(1 for f in arv["filhos"][:pos] if f["classe"] not in _CLASSES_BANDA)
    arv["filhos"] = resto[:pos] + novos + resto[pos:]
    # código dos cálculos (eventos OnCalc)
    mod = next((f for f in arv["filhos"] if f["classe"] == "TraCodeModule"), None)
    if mod is not None and _prop(mod, "ProgramStream") is not None:
        pass                       # ReportBuilder antigo: mantém o código original guardado no modelo
    elif m.codigos:
        if mod is None:
            mod = _no("TraCodeModule", m.nome("raCodeModule"))
            arv["filhos"].insert(len(arv["filhos"]) - sum(1 for f in arv["filhos"] if f["classe"] in ("TdaDataModule", "TppDesignLayers", "TppParameterList")), mod)
        mod["filhos"] = [f for f in mod["filhos"]
                         if not (f["classe"] == "TraProgramInfo" and (_prop(f, "raProgram.EventName") or "OnCalc") == "OnCalc")]
        for usuario, cod in m.codigos:
            mod["filhos"].append(_no("TraProgramInfo", m.nome("raProgramInfo"), [
                ("raClassName", "TraEventHandler"), ("raProgram.ProgramName", f"{usuario}OnCalc"),
                ("raProgram.ProgramType", Ident("ttProcedure")), ("raProgram.Source", _codigo_rb(usuario, cod)),
                ("raProgram.ComponentName", usuario), ("raProgram.EventName", "OnCalc"), ("raProgram.EventID", 33)]))
    return gravar(arv)


def importar(arquivo):
    """Arquivo .rtm -> desenho do painel."""
    import desenho as dz
    arv = ler(arquivo)
    d = dz.importar_arvore(para_desenho(arv))
    if not d:
        raise ValueError("Não foi possível ler o layout deste arquivo .rtm.")
    return d, pipelines(arv)


def pipelines(arv):
    """Nomes das fontes de dados (pipelines) que o modelo usa."""
    return sorted({str(_prop(n, "UserName") or n["nome"]) for n in _todos(arv)
                   if n["classe"] in ("TppChildDBPipeline", "TppDBPipeline", "TppBDEPipeline", "TppJITPipeline")})


def visoes_usadas(d):
    """Visões (fontes de dados) que os itens do desenho usam."""
    saida = set()

    def sec(s):
        if s.get("visao"):
            saida.add(s["visao"])
        bandas = list((s.get("bandas") or {}).values())
        for g in s.get("grupos") or []:
            if g.get("visao"):
                saida.add(g["visao"])
            bandas += [g.get("cab") or {}, g.get("rod") or {}]
        for b in bandas:
            for it in b.get("itens") or []:
                if it.get("visao"):
                    saida.add(it["visao"])
                if it.get("tipo") == "sub" and it.get("secao"):
                    sec(it["secao"])
    sec(d.get("relatorio") or {})
    return sorted(saida)
