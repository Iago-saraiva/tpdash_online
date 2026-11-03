"""Exportação de tabelas para Excel e PDF."""
import datetime as dt
import io
from collections import OrderedDict
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL = "1F4E78"
_DINHEIRO = ("VALOR", "TOTAL", "PRECO", "CUSTO", "LIMITE", "VLR_UNIT", "VALOR_ESTOQUE", "VALOR_BAIXADO", "VALOR_DOC")
_DATAS = ("EMISSAO", "VENCIMENTO", "BAIXA", "CADASTRO", "ULTIMA_VENDA", "DATA")


def _salvar(wb, buf):
    """Salva a planilha tratando como TEXTO qualquer valor que começaria uma fórmula (=, +, -, @).
    Evita "injeção de fórmula": um nome de cliente como =HYPERLINK(...) vindo do banco não vira fórmula no Excel."""
    for ws in wb.worksheets:
        for linha in ws.iter_rows():
            for c in linha:
                if c.data_type == "f":
                    c.data_type = "s"
    wb.save(buf)


def _eh_dinheiro(col):
    c = col.upper()
    return any(c == d or c.startswith(d + "_") or c.endswith("_" + d) for d in _DINHEIRO) or c in _DINHEIRO


def _eh_data(col):
    return any(col.upper() == d or col.upper().startswith(d) for d in _DATAS)


def _para_data(v):
    if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-":
        try:
            if len(v) > 10:
                return dt.datetime.fromisoformat(v[:19])
            return dt.date.fromisoformat(v)
        except ValueError:
            return v
    return v


def _titulo_col(c):
    return c.replace("_", " ").title().replace("Cpf Cnpj", "CPF/CNPJ").replace("Ncm", "NCM").replace("Cest", "CEST")


def excel(titulo, subtitulo, colunas, linhas, totais=None):
    wb = Workbook()
    ws = wb.active
    ws.title = (titulo or "Dados")[:31].replace("/", "-")
    ws["A1"] = titulo
    ws["A1"].font = Font(name="Arial", bold=True, size=14)
    ws["A2"] = subtitulo or ""
    ws["A2"].font = Font(name="Arial", size=9, color="666666")
    ws.append([])
    ws.append([_titulo_col(c) for c in colunas])
    cab = 4
    for c in ws[cab]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=AZUL)
        c.alignment = Alignment(vertical="center", wrap_text=True)
    fina = Side(style="thin", color="D9DEE5")
    larguras = [len(_titulo_col(c)) for c in colunas]
    for r in linhas:
        linha = []
        for i, v in enumerate(r):
            if _eh_data(colunas[i]):
                v = _para_data(v)
            linha.append(v)
            larguras[i] = max(larguras[i], min(len(str(v)) if v is not None else 0, 60))
        ws.append(linha)
    for row in ws.iter_rows(min_row=cab + 1):
        for i, c in enumerate(row):
            c.font = Font(name="Arial", size=10)
            c.border = Border(bottom=fina)
            col = colunas[i]
            if _eh_dinheiro(col):
                c.number_format = '#,##0.00;[Red]-#,##0.00;"-"'
            elif isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                c.number_format = "#,##0.###"
            elif isinstance(c.value, dt.datetime):
                c.number_format = "dd/mm/yyyy hh:mm"
            elif isinstance(c.value, dt.date):
                c.number_format = "dd/mm/yyyy"
    for i, w in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, min(w + 2, 62))
    ws.freeze_panes = ws.cell(cab + 1, 1)
    if linhas:
        ws.auto_filter.ref = f"A{cab}:{get_column_letter(len(colunas))}{cab + len(linhas)}"
    if totais:                                   # bloco de totais no fim da planilha
        ws.append([])
        for rotulo, valor, formato in totais:
            ws.append([rotulo, valor])
            a, b = ws.cell(ws.max_row, 1), ws.cell(ws.max_row, 2)
            a.font = Font(name="Arial", bold=True, size=10)
            b.font = Font(name="Arial", bold=formato != "texto", size=10, italic=formato == "texto")
            b.alignment = Alignment(horizontal="left")
            if formato == "moeda":
                b.number_format = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
            elif formato == "qtd":
                b.number_format = "#,##0.###;[Red]-#,##0.###"
    buf = io.BytesIO()
    _salvar(wb, buf)
    return buf.getvalue()


# ---------------------------------------------------------------- PDF
def _br(v, casas=2):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt(col, v):
    if v is None:
        return ""
    if _eh_dinheiro(col) and isinstance(v, (int, float)):
        return _br(v)
    if isinstance(v, float):
        return _br(v, 3).rstrip("0").rstrip(",") if v != int(v) else _br(v, 0)
    if _eh_data(col) and isinstance(v, str) and len(v) >= 10 and v[4] == "-":
        return f"{v[8:10]}/{v[5:7]}/{v[:4]}"
    return str(v)


def _doc(buf, titulo, retrato=False):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    tam = A4 if retrato else landscape(A4)
    gerado = dt.datetime.now().strftime("%d/%m/%Y %H:%M")

    def rodape(c, doc):
        from reportlab.lib import colors

        c.setFont("Helvetica", 7)
        c.setFillColor(colors.grey)
        c.drawString(10 * mm, 6 * mm, f"{titulo} - gerado em {gerado} pelo TP DASH")
        c.drawRightString(tam[0] - 10 * mm, 6 * mm, f"Página {doc.page}")

    doc = SimpleDocTemplate(buf, pagesize=tam, leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=12 * mm, title=titulo)
    return doc, rodape, tam[0] - 20 * mm


def _estilos():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    return {
        "cel": ParagraphStyle("c", fontName="Helvetica", fontSize=7, leading=8.5),
        "num": ParagraphStyle("n", fontName="Helvetica", fontSize=7, leading=8.5, alignment=2),
        "cab": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=7, leading=8.5, textColor=colors.white),
        "cabn": ParagraphStyle("hn", fontName="Helvetica-Bold", fontSize=7, leading=8.5, textColor=colors.white, alignment=2),
        "tit": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, spaceAfter=2),
        "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#555555"), spaceAfter=8),
        "grp": ParagraphStyle("g", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#" + AZUL)),
    }


def _estilo_tabela(n):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    st = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + AZUL)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(2, n, 2):
        st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F2F6FA")))
    return TableStyle(st)


def _larguras(colunas, linhas, total):
    pesos = []
    for i, c in enumerate(colunas):
        amostra = [len(str(r[i] or "")) for r in linhas[:300]]
        media = sum(amostra) / len(amostra) if amostra else 6
        pesos.append(max(5, min(max(len(c), media), 45)))
    s = sum(pesos)
    return [total * p / s for p in pesos]


def _fmt_total(valor, formato):
    if formato == "moeda":
        return "R$ " + _br(valor)
    if formato == "qtd" and isinstance(valor, (int, float)):
        return _fmt("", float(valor))
    return str(valor)


def pdf(titulo, subtitulo, colunas, linhas, totais=None):
    from reportlab.platypus import Paragraph, Table

    buf = io.BytesIO()
    doc, rodape, largura = _doc(buf, titulo, retrato=len(colunas) <= 6)
    e = _estilos()
    dados = [[Paragraph(escape(_titulo_col(c)), e["cab"]) for c in colunas]]
    for r in linhas:
        dados.append([
            Paragraph(escape(_fmt(colunas[i], v)), e["num"] if isinstance(v, (int, float)) else e["cel"])
            for i, v in enumerate(r)
        ])
    t = Table(dados, colWidths=_larguras(colunas, linhas, largura), repeatRows=1)
    t.setStyle(_estilo_tabela(len(dados)))
    partes = [Paragraph(escape(titulo), e["tit"]), Paragraph(escape(subtitulo or ""), e["sub"]), t]
    if totais:                                   # bloco de totais no fim do relatório
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import KeepTogether, Spacer, TableStyle

        rot = ParagraphStyle("tr", fontName="Helvetica-Bold", fontSize=8.5, leading=11)
        val = ParagraphStyle("tv", fontName="Helvetica-Bold", fontSize=8.5, leading=11, alignment=2)
        obs = ParagraphStyle("to", fontName="Helvetica-Oblique", fontSize=7.5, leading=10, textColor=colors.HexColor("#555555"))
        linhas_t = []
        for rotulo, valor, formato in totais:
            if formato == "texto":
                linhas_t.append([Paragraph(escape(f"{rotulo} {valor}"), obs), ""])
            else:
                linhas_t.append([Paragraph(escape(rotulo), rot), Paragraph(escape(_fmt_total(valor, formato)), val)])
        tt = Table(linhas_t, colWidths=[60 * 2.835, 45 * 2.835], hAlign="RIGHT")
        st = [("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#" + AZUL)),
              ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#CCCCCC")),
              ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6FA")),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        st += [("SPAN", (0, i), (1, i)) for i, x in enumerate(totais) if x[2] == "texto"]
        tt.setStyle(TableStyle(st))
        partes += [Spacer(1, 8), KeepTogether([tt])]
    doc.build(partes, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()


def pdf_documentos(titulo, subtitulo, df):
    """Relatório agrupado: DOCUMENTO + cabeçalho, itens embaixo, resumo por material no fim."""
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer, Table
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    doc, rodape, largura = _doc(buf, titulo, retrato=True)
    e = _estilos()
    cw = [largura * x for x in (.07, .11, .46, .07, .09, .10, .10)]
    docs = OrderedDict()
    for r in df.itertuples(index=False):
        docs.setdefault(r.IDMOV, {"r": r, "itens": []})
        if r.SEQ is not None and r.SEQ == r.SEQ:
            docs[r.IDMOV]["itens"].append(r)
    total_docs = sum(d["r"].VALOR_DOC for d in docs.values())
    story = [Paragraph(escape(titulo), e["tit"]),
             Paragraph(escape(f"{subtitulo} · {len(docs)} documentos, {sum(len(d['itens']) for d in docs.values())} itens · "
                              f"Total R$ {_br(total_docs)}"), e["sub"])]
    resumo = OrderedDict()
    for d in docs.values():
        r = d["r"]
        dados = [[Paragraph(h, e["cab"]) for h in ("Seq", "Cód. fabricante", "Material", "Und", "Qtd", "Vlr Unit.", "Total")]]
        for i in d["itens"]:
            dados.append([Paragraph(escape(_fmt("SEQ", i.SEQ)), e["cel"]), Paragraph(escape(str(i.COD_FABRICANTE or "")), e["cel"]),
                          Paragraph(escape(str(i.MATERIAL or "")), e["cel"]), Paragraph(escape(str(i.UND or "")), e["cel"]),
                          Paragraph(_fmt("QTD", i.QTD), e["num"]), Paragraph(_br(i.VLR_UNIT), e["num"]),
                          Paragraph(_br(i.TOTAL), e["num"])])
            k = getattr(i, "CODPRD_INT", None) or i.COD_FABRICANTE
            if k not in resumo:
                resumo[k] = [i.MATERIAL, i.UND, 0.0, 0.0, i.COD_FABRICANTE]
            resumo[k][2] += i.QTD or 0
            resumo[k][3] += i.TOTAL or 0
        t = Table(dados, colWidths=cw)
        t.setStyle(_estilo_tabela(len(dados)))
        cliente = f"{r.CODCFO or ''} - {r.CLIENTE or ''}".strip(" -")
        status = f" · {r.STATUS}" if r.STATUS else ""
        cab = (f"DOCUMENTO {r.DOCUMENTO}  ·  {_fmt('EMISSAO', r.EMISSAO)}  ·  {r.CODTMV}  ·  {cliente}"
               f"{status}  ·  Valor: R$ {_br(r.VALOR_DOC)}")
        story.append(KeepTogether([Paragraph(escape(cab), e["grp"]), Spacer(1, 1.5 * mm), t, Spacer(1, 5 * mm)]))
    if resumo:
        story += [PageBreak(), Paragraph("Resumo por material (soma do período)", e["tit"]), Spacer(1, 3 * mm)]
        dados = [[Paragraph(h, e["cab"]) for h in ("Cód. fabricante", "Material", "Und", "Qtd total", "Valor total")]]
        for k, (n, u, q, v, cf) in sorted(resumo.items(), key=lambda x: str(x[1][0] or "")):
            dados.append([Paragraph(escape(str(cf or "")), e["cel"]), Paragraph(escape(str(n or "")), e["cel"]),
                          Paragraph(escape(str(u or "")), e["cel"]), Paragraph(_fmt("QTD", q), e["num"]),
                          Paragraph(_br(v), e["num"])])
        t = Table(dados, colWidths=[largura * x for x in (.11, .55, .08, .12, .14)], repeatRows=1)
        t.setStyle(_estilo_tabela(len(dados)))
        story.append(t)
    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()


def multi(titulo, subtitulo, visoes, fmt):
    """Exporta um relatório com várias visões: Excel com uma aba por visão, PDF com uma seção por visão."""
    if fmt == "xlsx":
        from openpyxl import load_workbook

        wb = None
        usados = set()
        for v in visoes:
            if v.get("erro"):
                cols, linhas = ["ERRO"], [[v["erro"]]]
            else:
                cols, linhas = v["colunas"] or ["(sem colunas)"], v["linhas"]
            parcial = load_workbook(io.BytesIO(excel(f"{titulo} - {v['nome']}", subtitulo, cols, linhas)))
            origem = parcial.active
            nome = (v["nome"] or "Dados")[:28].replace("/", "-")
            base, k = nome, 2
            while nome in usados:
                nome = f"{base[:25]}_{k}"
                k += 1
            usados.add(nome)
            if wb is None:
                wb = parcial
                origem.title = nome
                continue
            destino = wb.create_sheet(nome)
            for row in origem.iter_rows():
                for c in row:
                    n = destino.cell(row=c.row, column=c.column, value=c.value)
                    if c.has_style:
                        n.font, n.fill, n.border = c.font.copy(), c.fill.copy(), c.border.copy()
                        n.number_format, n.alignment = c.number_format, c.alignment.copy()
            for letra, dim in origem.column_dimensions.items():
                destino.column_dimensions[letra].width = dim.width
            destino.freeze_panes = origem.freeze_panes
            if origem.auto_filter.ref:
                destino.auto_filter.ref = origem.auto_filter.ref
        buf = io.BytesIO()
        _salvar(wb or Workbook(), buf)
        return buf.getvalue()

    from reportlab.platypus import PageBreak, Paragraph, Spacer, Table
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    maxcols = min(14, max([len(v["colunas"]) for v in visoes if v.get("colunas")] or [1]))
    doc, rodape, largura = _doc(buf, titulo, retrato=maxcols <= 6)
    e = _estilos()
    story = [Paragraph(escape(titulo), e["tit"]), Paragraph(escape(subtitulo or ""), e["sub"])]
    for i, v in enumerate(visoes):
        if i and len(v.get("linhas") or []) > 25:
            story.append(PageBreak())
        n = len(v.get("linhas") or [])
        story.append(Paragraph(escape(f"{v['nome']} · {n} linha(s)" + (" · limite atingido" if v.get("truncado") else "")), e["grp"]))
        story.append(Spacer(1, 2 * mm))
        if v.get("erro"):
            story.append(Paragraph(escape("Erro: " + v["erro"]), e["cel"]))
        elif v.get("aviso") and not n:
            story.append(Paragraph(escape(v["aviso"]), e["cel"]))
        elif n:
            cols = v["colunas"][:14]
            if len(v["colunas"]) > 14:
                story.append(Paragraph(escape(f"Mostrando 14 de {len(v['colunas'])} colunas - exporte em Excel para ver todas."), e["sub"]))
            dados = [[Paragraph(escape(_titulo_col(c)), e["cab"]) for c in cols]]
            for r in (x[:14] for x in v["linhas"]):
                dados.append([Paragraph(escape(_fmt(cols[j], x)), e["num"] if isinstance(x, (int, float)) else e["cel"])
                              for j, x in enumerate(r)])
            t = Table(dados, colWidths=_larguras(cols, v["linhas"], largura), repeatRows=1)
            t.setStyle(_estilo_tabela(len(dados)))
            story.append(t)
        else:
            story.append(Paragraph("Sem linhas para os parâmetros informados.", e["cel"]))
        story.append(Spacer(1, 6 * mm))
    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()


# ---------------------------------------------------------------- relatórios com layout
def com_layout(titulo, subtitulo, visoes, fmt, orientacao="auto"):
    """Exporta visões já processadas por layout.aplicar (colunas, blocos agrupados, totais, indicadores)."""
    import layout as L

    visoes = [v for v in visoes if not v.get("oculta")]
    if fmt == "xlsx":
        wb = Workbook()
        wb.remove(wb.active)
        usados = set()
        fina = Side(style="thin", color="D9DEE5")
        for v in visoes:
            nome = (v.get("titulo") or v["nome"] or "Dados")[:28].replace("/", "-").replace(":", " ")
            base, k = nome, 2
            while nome in usados:
                nome = f"{base[:25]}_{k}"
                k += 1
            usados.add(nome)
            ws = wb.create_sheet(nome)
            ws["A1"] = f"{titulo} - {v.get('titulo') or v['nome']}"
            ws["A1"].font = Font(name="Arial", bold=True, size=13)
            ws["A2"] = subtitulo or ""
            ws["A2"].font = Font(name="Arial", size=9, color="666666")
            lin = 3
            if v.get("erro"):
                ws.cell(lin + 1, 1, "Erro: " + v["erro"]).font = Font(name="Arial", color="C00000")
                continue
            for ind in v.get("indicadores") or []:
                ws.cell(lin, 1, ind["rotulo"]).font = Font(name="Arial", bold=True)
                c = ws.cell(lin, 2, ind["valor"])
                c.font = Font(name="Arial")
                c.number_format = L.FMT_EXCEL.get(ind["formato"], "General")
                lin += 1
            lin += 1
            cols = v["colunas"]
            for j, c in enumerate(cols, 1):
                cel = ws.cell(lin, j, c["rotulo"])
                cel.font = Font(name="Arial", bold=True, color="FFFFFF")
                cel.fill = PatternFill("solid", start_color=AZUL)
                cel.alignment = Alignment(vertical="center", wrap_text=True)
            cab = lin
            larg = [len(c["rotulo"]) for c in cols]

            def escrever(valores, estilo=None, rotulo=None):
                nonlocal lin
                lin += 1
                for j, (c, x) in enumerate(zip(cols, valores), 1):
                    cel = ws.cell(lin, j, L.valor_excel(x, c["formato"]))
                    cel.font = Font(name="Arial", size=10, bold=estilo in ("grupo", "subtotal", "total"))
                    cel.border = Border(bottom=fina)
                    if c["formato"] in L.FMT_EXCEL and x is not None:
                        cel.number_format = L.FMT_EXCEL[c["formato"]]
                    if estilo in ("subtotal", "total"):
                        cel.fill = PatternFill("solid", start_color="EEF2F7")
                    larg[j - 1] = max(larg[j - 1], min(len(L.formatar(x, c["formato"])), 60))
                if rotulo and (not valores or valores[0] is None):
                    ws.cell(lin, 1, rotulo).font = Font(name="Arial", size=10, bold=True)

            if v.get("blocos"):
                for b in v["blocos"]:
                    if b["t"] == "grupo":
                        lin += 1
                        cel = ws.cell(lin, 1, f"{'   ' * b['nivel']}{b['rotulo']}: {L.formatar(b['valor'], 'texto') or '(vazio)'}  ({b['qtd']})")
                        cel.font = Font(name="Arial", bold=True, color=AZUL)
                    elif b["t"] == "linha":
                        escrever(b["v"])
                    else:
                        escrever(b["v"], "subtotal", f"Subtotal {L.formatar(b['valor'], 'texto')}")
            else:
                for r in v["linhas"]:
                    escrever(r)
            if v.get("totais"):
                escrever(v["totais"], "total", "Total geral")
            for j, w in enumerate(larg, 1):
                ws.column_dimensions[get_column_letter(j)].width = max(8, min(w + 2, 62))
            ws.freeze_panes = ws.cell(cab + 1, 1)
        if not wb.sheetnames:
            wb.create_sheet("Vazio")
        buf = io.BytesIO()
        _salvar(wb, buf)
        return buf.getvalue()

    # PDF
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    maxcols = max([len(L.grupos_visuais(v["colunas"])) for v in visoes if v.get("colunas")] or [1])
    retrato = orientacao == "retrato" or (orientacao == "auto" and maxcols <= 6)
    doc, rodape, largura = _doc(buf, titulo, retrato=retrato)
    e = _estilos()
    story = [Paragraph(escape(titulo), e["tit"]), Paragraph(escape(subtitulo or ""), e["sub"])]
    for v in visoes:
        n = len(v.get("linhas") or [])
        story.append(Paragraph(escape(f"{v.get('titulo') or v['nome']} · {n} linha(s)" + (" · limite atingido" if v.get("truncado") else "")), e["grp"]))
        story.append(Spacer(1, 2 * mm))
        if v.get("erro"):
            story.append(Paragraph(escape("Erro: " + v["erro"]), e["cel"]))
            continue
        if v.get("indicadores"):
            txt = "   ·   ".join(f"<b>{escape(i['rotulo'])}:</b> {escape(L.formatar(i['valor'], i['formato']))}" for i in v["indicadores"])
            story += [Paragraph(txt, e["cel"]), Spacer(1, 2 * mm)]
        if not n:
            story += [Paragraph(escape(v.get("aviso") or "Sem linhas para os parâmetros informados."), e["cel"]), Spacer(1, 5 * mm)]
            continue
        grupos = L.grupos_visuais(v["colunas"])
        if len(grupos) > 16:
            story.append(Paragraph(escape(f"Mostrando 16 de {len(grupos)} colunas - use o editor de layout para escolher as colunas ou exporte em Excel."), e["sub"]))
            grupos = grupos[:16]
        cols = v["colunas"]
        num = [all(cols[i]["formato"] in ("moeda", "inteiro", "numero", "percentual") for i in gr) for gr in grupos]
        dados = [[Paragraph("<br/>".join(escape(cols[i]["rotulo"]) for i in gr), e["cabn"] if num[j] else e["cab"]) for j, gr in enumerate(grupos)]]
        estilos = []

        def linha(valores, negrito=False):
            celulas = []
            for j, gr in enumerate(grupos):
                txt = "<br/>".join(escape(L.formatar(valores[i], cols[i]["formato"])) or "&nbsp;" for i in gr)
                celulas.append(Paragraph(("<b>%s</b>" if negrito else "%s") % txt, e["num"] if num[j] else e["cel"]))
            dados.append(celulas)

        def rotulo_primeira(texto):
            if all(cols[i]["formato"] not in ("moeda", "inteiro", "numero", "percentual") for i in grupos[0]):
                dados[-1][0] = Paragraph("<b>%s</b>" % escape(texto), e["cel"])

        if v.get("blocos"):
            for b in v["blocos"]:
                if b["t"] == "grupo":
                    dados.append([Paragraph(f"<b>{'&nbsp;' * 4 * b['nivel']}{escape(b['rotulo'])}: {escape(L.formatar(b['valor'], 'texto') or '(vazio)')}</b> ({b['qtd']})", e["cel"])] + [""] * (len(grupos) - 1))
                    estilos += [("SPAN", (0, len(dados) - 1), (-1, len(dados) - 1)),
                                ("BACKGROUND", (0, len(dados) - 1), (-1, len(dados) - 1), colors.HexColor("#E3EEFB"))]
                elif b["t"] == "linha":
                    linha(b["v"])
                else:
                    linha(b["v"], True)
                    rotulo_primeira("Subtotal " + L.formatar(b["valor"], "texto"))
                    estilos.append(("BACKGROUND", (0, len(dados) - 1), (-1, len(dados) - 1), colors.HexColor("#F2F4F7")))
        else:
            for r in v["linhas"]:
                linha(r)
        if v.get("totais"):
            linha(v["totais"], True)
            rotulo_primeira("Total geral")
            estilos.append(("BACKGROUND", (0, len(dados) - 1), (-1, len(dados) - 1), colors.HexColor("#DCE3EC")))
        rot_vis = [max((cols[i]["rotulo"] for i in gr), key=len) for gr in grupos]
        amostra = v["linhas"][:300] + ([v["totais"]] * 3 if v.get("totais") else [])
        linhas_txt = [[max((L.formatar(r[i], cols[i]["formato"]) for i in gr), key=len) for gr in grupos] for r in amostra]
        t = Table(dados, colWidths=_larguras(rot_vis, linhas_txt, largura), repeatRows=1)
        st = _estilo_tabela(0)
        t.setStyle(st)
        t.setStyle(TableStyle(estilos))
        story += [t, Spacer(1, 6 * mm)]
    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
