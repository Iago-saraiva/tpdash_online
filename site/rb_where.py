"""Reconstrói o WHERE de cada visão do ReportBuilder a partir dos critérios (TdaCriteria), com parâmetros para os de AutoSearch."""
import re
import unicodedata

OPS = {"dacoEqual": "=", "dacoNotEqual": "<>", "dacoLessThan": "<", "dacoLessThanOrEqualTo": "<=",
       "dacoGreaterThan": ">", "dacoGreaterThanOrEqualTo": ">="}
NUMERICOS = {"dtInteger", "dtLargeInt", "dtDouble", "dtCurrency", "dtBCD", "dtSingle", "dtExtended", "dtSmallInt", "dtWord"}
DATAS = {"dtDate", "dtDateTime", "dtTime"}


def _tipo(c):
    dt = c["campo"].get("DataType") or "dtString"
    if dt in DATAS:
        return "data"
    if dt in NUMERICOS:
        return "numero"
    return "texto"


def _campo(c):
    f = c["campo"]
    if f.get("Expression"):
        return f["Expression"]
    return f"{f.get('TableSQLAlias')}.{f.get('SQLFieldName') or f.get('FieldName')}"


def _data_mdY(v):
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})(.*)$", v)
    if m:
        return f"{m.group(2).zfill(2)}/{m.group(1).zfill(2)}/{m.group(3)}{m.group(4)}"
    return v


def _data_iso(v):
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", v or "")
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return None


def _lit(c, v):
    t = _tipo(c)
    if t == "numero":
        return v.strip()
    if t == "data":
        return "'" + _data_mdY(v).strip() + "'"
    return "'" + v.replace("'", "''") + "'"


def _split(v):
    return [x for x in v.split(",")]


def cond_literal(c):
    op = c.get("Operator", "dacoEqual")
    f = _campo(c)
    v = c.get("Value")
    if op == "dacoBlank":
        return f"{f} IS NULL"
    if op == "dacoNotBlank":
        return f"{f} IS NOT NULL"
    if v is None or (v == "" and c["campo"].get("AutoSearch") and c["campo"].get("ShowAllValues")):
        return None
    if op in OPS:
        return f"{f} {OPS[op]} {_lit(c, v)}"
    if op in ("dacoBetween", "dacoNotBetween"):
        a, _, b = v.partition(",")
        return f"{f} {'NOT ' if op == 'dacoNotBetween' else ''}BETWEEN {_lit(c, a)} AND {_lit(c, b)}"
    if op in ("dacoInList", "dacoNotInList"):
        return f"{f} {'NOT ' if op == 'dacoNotInList' else ''}IN ({','.join(_lit(c, x) for x in _split(v))})"
    if op in ("dacoLike", "dacoNotLike"):
        val = v if _tipo(c) == "numero" else v + "%"
        return f"{f} {'NOT ' if op == 'dacoNotLike' else ''}LIKE {_lit(c, val)}"
    raise ValueError(op)


def montar(criterios, literal=True, params=None, empresa_fixa=True):
    """Monta o texto do WHERE. Com literal=False, critérios de AutoSearch viram parâmetros."""
    partes = []
    prox_conector = None
    for c in criterios:
        tipo = c.get("CriteriaType", "dacrField")
        if tipo == "dacrBegin":
            if partes and prox_conector is None:
                partes.append("AND")
            prox_conector = None
            partes.append("(")
            prox_conector = "INICIO"
            continue
        if tipo == "dacrEnd":
            partes.append(")")
            prox_conector = None
            continue
        if tipo == "dacrOR":
            prox_conector = "OR"
            continue
        if tipo == "dacrNOT":
            partes.append("NOT")
            continue
        if literal or not c["campo"].get("AutoSearch") or (empresa_fixa and (c["campo"].get("SQLFieldName") or "").upper() == "CODEMPRESA"):
            cond = cond_literal(c)
        else:
            cond = cond_param(c, params)
        if cond is None:
            continue
        if partes and partes[-1] != "(" and prox_conector != "INICIO":
            partes.append(prox_conector or "AND")
        partes.append(f"( {cond} )")
        prox_conector = None
    # remove parênteses vazios "( )"
    txt = " ".join(partes)
    txt = re.sub(r"\(\s*\)", "", txt)
    txt = re.sub(r"\b(AND|OR)\s+(AND|OR)\b", r"\2", txt)
    txt = re.sub(r"^\s*(AND|OR)\s+|\s+(AND|OR)\s*$", "", txt.strip())
    txt = re.sub(r"\(\s*(AND|OR)\s+", "(", txt)
    txt = re.sub(r"\s+(AND|OR)\s*\)", ")", txt)
    return txt.strip()


def _nome_param(c, sufixo=""):
    base = c["campo"].get("Alias") or c["campo"].get("FieldAlias") or c["campo"].get("SQLFieldName") or "PARAM"
    base = "".join(ch for ch in unicodedata.normalize("NFD", base) if unicodedata.category(ch) != "Mn")
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").upper() or "PARAM"
    if base[0].isdigit():
        base = "P_" + base
    return (base + sufixo)[:60]


def _rotulo(c, extra=""):
    r = c["campo"].get("Alias") or c["campo"].get("FieldAlias") or c["campo"].get("SQLFieldName")
    return f"{r}{extra}"


def _add(params, nome, tipo, rotulo, padrao, obrig, ajuda=""):
    if nome in params:
        return nome
    params[nome] = {"nome": nome, "tipo": tipo, "rotulo": rotulo, "padrao": padrao, "obrigatorio": obrig, "ajuda": ajuda}
    return nome


def _padrao(c, v):
    if v in (None, ""):
        return None
    if _tipo(c) == "data":
        return _data_iso(v)
    return v.strip() if _tipo(c) == "numero" else v


PNF = "(SELECT FIRST 1 PNF.NUMNOFABRIC FROM TPRODUTO PNF WHERE PNF.CODPRD = {})"


def cond_param(c, params):
    op = c.get("Operator", "dacoEqual")
    f = _campo(c)
    if (c["campo"].get("SQLFieldName") or "").upper() == "CODPRD" and not c["campo"].get("Expression"):
        # o usuário digita o código do fabricante (NUMNOFABRIC) no lugar do CODPRD
        f = PNF.format(f)
        c = {**c, "Value": None, "campo": {**c["campo"], "DataType": "dtString",
                            "Alias": (c["campo"].get("Alias") or "Codigo") + " (cód. fabricante)"}}
    v = c.get("Value")
    t = _tipo(c)
    sql_t = {"data": "DATE", "numero": "DOUBLE PRECISION", "texto": "VARCHAR(250)"}[t]
    obrig = bool(c["campo"].get("Mandatory"))
    if op == "dacoBlank":
        return f"{f} IS NULL"
    if op == "dacoNotBlank":
        return f"{f} IS NOT NULL"
    if op in OPS:
        p = _add(params, _nome_param(c), t, _rotulo(c), _padrao(c, v), obrig)
        cond = f"{f} {OPS[op]} CAST(:{p} AS {sql_t})"
        return cond if obrig else f"(CAST(:{p} AS {sql_t}) IS NULL OR {cond})"
    if op in ("dacoBetween", "dacoNotBetween"):
        a, _, b = (v or "").partition(",")
        p1 = _add(params, _nome_param(c, "_DE"), t, _rotulo(c, " (de)"), _padrao(c, a), obrig)
        p2 = _add(params, _nome_param(c, "_ATE"), t, _rotulo(c, " (até)"), _padrao(c, b), obrig)
        sup = f"{f} < CAST(:{p2} AS DATE) + 1" if t == "data" else f"{f} <= CAST(:{p2} AS {sql_t})"
        inf = f"{f} >= CAST(:{p1} AS {sql_t})"
        if op == "dacoNotBetween":
            return f"NOT ({inf} AND {sup})"
        return f"(CAST(:{p1} AS {sql_t}) IS NULL OR {inf}) AND (CAST(:{p2} AS {sql_t}) IS NULL OR {sup})"
    if op in ("dacoInList", "dacoNotInList"):
        p = _add(params, _nome_param(c), "lista", _rotulo(c, " (separe por vírgula)"), v or None, obrig)
        cmp_ = "= 0" if op == "dacoNotInList" else "> 0"
        return (f"(CAST(:{p} AS VARCHAR(2000)) IS NULL OR POSITION(',' || TRIM({f}) || ',' IN "
                f"',' || REPLACE(CAST(:{p} AS VARCHAR(2000)), ' ', '') || ',') {cmp_})")
    if op in ("dacoLike", "dacoNotLike"):
        p = _add(params, _nome_param(c), "texto", _rotulo(c, " (começa com; use % como coringa)"), v or None, obrig)
        neg = "NOT " if op == "dacoNotLike" else ""
        return f"(CAST(:{p} AS VARCHAR(250)) IS NULL OR {f} {neg}LIKE CAST(:{p} AS VARCHAR(250)) || '%')"
    raise ValueError(op)


_PADRAO_WHERE = re.compile(r"\nWHERE\b(.*?)(?=\nGROUP BY\b|\nHAVING\b|\nORDER BY\b|\Z)", re.S)


def where_atual(sql):
    m = _PADRAO_WHERE.search(sql)
    return m.group(1) if m else ""


def norm(s):
    return " ".join(s.replace("(", " ( ").replace(")", " ) ").split()).upper()


def substituir_where(sql, novo):
    m = _PADRAO_WHERE.search(sql)
    if m:
        return sql[:m.start()] + ("\nWHERE " + novo if novo else "") + sql[m.end():]
    if not novo:
        return sql
    for kw in ("\nGROUP BY", "\nHAVING", "\nORDER BY"):
        k = sql.find(kw)
        if k >= 0:
            return sql[:k] + "\nWHERE " + novo + sql[k:]
    return sql + "\nWHERE " + novo
