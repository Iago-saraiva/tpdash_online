"""Relatórios importados do ReportBuilder do Puma (arquivo relatorios_rb.json).

Cada relatório tem uma ou mais "visões" (as Data Views do ReportBuilder). Visões de detalhe
(ex.: itens do movimento) são filtradas pelas linhas da visão mestre, como no ReportBuilder.
Os critérios que no ReportBuilder eram de "AutoSearch" viraram parâmetros :NOME.
"""
import datetime as dt
import json
import os
import re

from config import BASE_DIR, DADOS_DIR
from db import ErroBanco

CAMINHO = os.path.join(BASE_DIR, "relatorios_rb.json")                  # catálogo que vem com o painel (banco principal)
SINCRONIZADO = os.path.join(DADOS_DIR, "relatorios_rb.json")   # catálogo lido do banco principal (rb_sync)
_cache = {}
PADRAO = os.path.join(BASE_DIR, "relatorios_padrao.json")              # relatórios padrão do painel
_padroes = None


def padroes():
    """Relatórios criados no painel (pasta "Relatórios padrões"), iguais para todas as empresas."""
    global _padroes
    if _padroes is None:
        try:
            with open(PADRAO, encoding="utf-8") as f:
                _padroes = json.load(f).get("relatorios") or []
        except (OSError, ValueError):
            _padroes = []
    return _padroes


def _arquivos(bid):
    import bancos
    if bid == bancos.PRINCIPAL:
        return (SINCRONIZADO, CAMINHO)
    return (os.path.join(bancos.pasta(bid), "relatorios_rb.json"),)   # outros bancos: só o que foi lido deles


def todos(bid=None):
    """Relatórios do banco `bid` (padrão: o banco em uso pelo usuário)."""
    import bancos
    bid = bid or bancos.atual()
    if bid not in _cache:
        lista = None
        for c in _arquivos(bid):
            if os.path.exists(c):
                try:
                    with open(c, encoding="utf-8") as f:
                        lista = json.load(f)
                    break
                except (OSError, ValueError):
                    continue
        lista = list(lista or [])
        ids = {r["id"] for r in lista}
        lista += [r for r in padroes() if r["id"] not in ids]
        _cache[bid] = lista
    return _cache[bid]


def recarregar(bid=None):
    if bid is None:
        _cache.clear()
    else:
        _cache.pop(bid, None)


def obter(rid, bid=None):
    return next((r for r in todos(bid) if r["id"] == rid), None)


def valor_padrao(p):
    """Padrão do parâmetro; aceita 'hoje', 'inicio_mes', 'inicio_ano', 'mes_anterior_ini', 'mes_anterior_fim'."""
    v = p.get("padrao")
    if p.get("tipo") == "data" and isinstance(v, str):
        hoje = dt.date.today()
        ini_mes = hoje.replace(day=1)
        fim_ant = ini_mes - dt.timedelta(days=1)
        v = {"hoje": hoje, "inicio_mes": ini_mes, "inicio_ano": hoje.replace(month=1, day=1),
             "mes_anterior_ini": fim_ant.replace(day=1), "mes_anterior_fim": fim_ant}.get(v, v)
        if isinstance(v, dt.date):
            v = v.isoformat()
    return v


def resumo(r):
    params = [dict(p, padrao=valor_padrao(p)) for p in r["parametros"]]
    return {"id": r["id"], "nome": r["nome"], "pasta": r["pasta"], "modulo": r["modulo"], "alterado": r["alterado"],
            "antigo": r["antigo"], "visoes": [v["nome"] for v in r["visoes"]], "parametros": params,
            "padrao_painel": bool(r.get("padrao_painel")),
            "valido": r.get("valido", True), "erro": r.get("erro")}


# ------------------------------------------------------------------ montagem do SQL
def _itens_select(sql):
    """Mapa NOME_DA_COLUNA -> expressão, a partir da lista do SELECT gerada pelo ReportBuilder."""
    m = re.search(r"^\s*SELECT\b(.*?)\bFROM\b", sql, re.S | re.I)
    if not m:
        return {}
    itens, prof, atual = [], 0, ""
    for ch in m.group(1):
        if ch == "(":
            prof += 1
        elif ch == ")":
            prof -= 1
        if ch == "," and prof == 0:
            itens.append(atual)
            atual = ""
        else:
            atual += ch
    itens.append(atual)
    mapa = {}
    for it in itens:
        it = " ".join(it.split())
        if not it:
            continue
        mm = re.match(r"^(.*?)\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_$]*)$", it, re.I)
        if mm and not re.match(r"^[\w$]+\.[\w$]+$|^[\w$]+$", it):
            mapa[mm.group(2).upper()] = mm.group(1)
        else:
            mapa[it.split(".")[-1].upper().strip('"')] = it
    return mapa


_WHERE = re.compile(r"\bWHERE\b(.*?)(?=\bGROUP\s+BY\b|\bHAVING\b|\bORDER\s+BY\b|\Z)", re.S | re.I)


def _acrescentar_condicao(sql, cond):
    """Acrescenta uma condição ao WHERE do SELECT principal (consultas geradas pelo ReportBuilder)."""
    if re.search(r"\bUNION\b", sql, re.I) or sql.upper().count("SELECT") > 1:
        return None
    m = _WHERE.search(sql)
    if m:
        return sql[:m.start(1)] + f" ({m.group(1).strip()}) AND ({cond})\n" + sql[m.end(1):]
    for kw in (r"\bGROUP\s+BY\b", r"\bHAVING\b", r"\bORDER\s+BY\b"):
        k = re.search(kw, sql, re.I)
        if k:
            return sql[:k.start()] + f"WHERE {cond}\n" + sql[k.start():]
    return sql + f"\nWHERE {cond}"


def _restringir(v, mestre_res):
    """SQL da visão de detalhe limitada às linhas da visão mestre (como o vínculo mestre-detalhe do RB).
    Devolve (sql, params_extra) ou (None, None) se não for possível restringir."""
    if not mestre_res or mestre_res.get("erro"):
        return None, None
    mapa = _itens_select(v["sql"])
    exprs, idx = [], []
    for m, d in v["ligacoes"]:
        if d.upper() not in mapa or m.upper() not in [c.upper() for c in mestre_res["colunas"]]:
            return None, None
        exprs.append(mapa[d.upper()])
        idx.append([c.upper() for c in mestre_res["colunas"]].index(m.upper()))
    chaves = []
    vistos = set()
    for linha in mestre_res["linhas"]:
        k = tuple(linha[i] for i in idx)
        if None in k or k in vistos:
            continue
        vistos.add(k)
        chaves.append(k)
    if not chaves:
        return "VAZIO", []
    if len(chaves) > 5000:
        return None, None
    params = []
    if len(exprs) == 1:
        blocos = []
        for i in range(0, len(chaves), 1000):
            parte = chaves[i:i + 1000]
            blocos.append(f"{exprs[0]} IN ({','.join('?' * len(parte))})")
            params += [k[0] for k in parte]
        cond = " OR ".join(blocos)
    else:
        if len(chaves) > 500:
            return None, None
        cond = " OR ".join("(" + " AND ".join(f"{e} = ?" for e in exprs) + ")" for _ in chaves)
        for k in chaves:
            params += list(k)
    novo = _acrescentar_condicao(v["sql"], cond)
    if novo is None:
        return None, None
    return novo, params


_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|:([A-Za-z_][A-Za-z0-9_]*)")


def nomes_parametros(sql):
    vistos = []
    for m in _TOKEN.finditer(sql):
        if m.group(1) and m.group(1).upper() not in vistos:
            vistos.append(m.group(1).upper())
    return vistos


def ligar(sql, valores):
    """Troca :NOME por ? (fora de textos entre aspas) e devolve a lista de valores na ordem."""
    params = []

    def troca(m):
        if m.group(1) is None:
            return m.group(0)
        params.append(valores.get(m.group(1).upper()))
        return "?"

    return _TOKEN.sub(troca, sql), params


def converter_valores(r, entrada):
    """Converte os valores digitados (texto) para o tipo de cada parâmetro."""
    saida = {}
    faltando = []
    for p in r["parametros"]:
        bruto = (entrada.get(p["nome"]) if p["nome"] in entrada else valor_padrao(p))
        bruto = None if bruto is None else str(bruto).strip()
        if bruto in ("", None):
            if p.get("obrigatorio"):
                faltando.append(p["rotulo"])
            saida[p["nome"]] = None
            continue
        try:
            if p["tipo"] == "data":
                if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", bruto):
                    d, m, a = bruto.split("/")
                    saida[p["nome"]] = dt.date(int(a), int(m), int(d))
                else:
                    saida[p["nome"]] = dt.date.fromisoformat(bruto[:10])
            elif p["tipo"] == "opcao":
                ops = [o[0] for o in p.get("opcoes") or []]
                saida[p["nome"]] = bruto if bruto in ops else valor_padrao(p)
            elif p["tipo"] == "numero":
                n = float(bruto.replace(".", "").replace(",", ".")) if "," in bruto else float(bruto)
                saida[p["nome"]] = int(n) if n == int(n) else n
            else:
                saida[p["nome"]] = bruto
        except ValueError:
            raise ErroBanco(f"Valor inválido para '{p['rotulo']}': {bruto}")
    if faltando:
        raise ErroBanco("Preencha: " + ", ".join(faltando))
    return saida


def executar(banco, r, entrada, limite, pular=()):
    """pular: visões ocultas pelo layout - não são executadas (só os nomes das colunas), a não ser que
    sejam mestre de outra visão que vai rodar."""
    valores = converter_valores(r, entrada)
    pular = set(pular or ())
    mestres = {v.get("mestre") for v in r["visoes"] if v["nome"] not in pular and v.get("mestre")}
    resultado = {}
    for v in r["visoes"]:
        info = {"nome": v["nome"], "colunas": [], "linhas": [], "truncado": False, "aviso": None}
        sql, extra = v["sql"], []
        if v["nome"] in pular and v["nome"] not in mestres:
            info["aviso"] = "Visão oculta pelo layout (não executada)"
            info["colunas"] = list(_itens_select(v["sql"]))   # nomes lidos do SQL, sem consultar o banco
            resultado[v["nome"]] = info
            continue
        if v.get("mestre") and v.get("ligacoes"):
            mestre = resultado.get(v["mestre"]) or {}
            restrito, extra_r = _restringir(v, resultado.get(v["mestre"]))
            if restrito == "VAZIO":
                info["aviso"] = (f"Não executada porque a visão {v['mestre']} deu erro" if mestre.get("erro")
                                 else f"Sem linhas em {v['mestre']}")
                # mesmo sem linhas, busca os nomes das colunas (para o editor de layout)
                info["colunas"] = list(_itens_select(v["sql"]))
                resultado[v["nome"]] = info
                continue
            if restrito:
                sql, extra = restrito, extra_r
            else:
                info["aviso"] = f"Não foi possível vincular a {v['mestre']}; mostrando sem o vínculo"
        q, params = ligar(sql, valores)
        try:
            cols, linhas, mais = banco.consultar(q, params + extra, min(limite, v.get("limite") or limite))
            info.update(colunas=cols, linhas=linhas, truncado=mais)
        except ErroBanco as e:
            info["erro"] = str(e)
        resultado[v["nome"]] = info
    return list(resultado.values())


def testar(banco, r):
    """Executa cada visão com os parâmetros vazios/padrão e no máximo 1 linha. Devolve lista de erros."""
    erros = []
    valores = {p["nome"]: None for p in r["parametros"]}
    for v in r["visoes"]:
        q, params = ligar(v["sql"], valores)
        try:
            banco.consultar(q, params, 1)
        except ErroBanco as e:
            erros.append(f"{v['nome']}: {str(e)[:300]}")
    return erros


def params_tipo_movimento(r):
    """Nomes dos filtros que comparam o tipo de movimento (CODTMV) - usados para limitar por usuário."""
    nomes = []
    for p in r["parametros"]:
        n = re.escape(p["nome"])
        for v in r["visoes"]:
            if re.search(r"CODTMV[^()]*:%s\b|:%s\b[^()]*CODTMV|TRIM\([\w.]*CODTMV\)[^:]*:%s\b" % (n, n, n), v["sql"]):
                nomes.append(p["nome"])
                break
    return nomes
