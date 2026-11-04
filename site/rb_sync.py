"""Sincroniza os relatórios do ReportBuilder direto do banco conectado (tabelas RB_ITEM e RB_FOLDER).

- Lê só os metadados (id, pasta, nome, data de alteração) a cada verificação: é rápido.
- Baixa e converte o modelo (TEMPLATE) apenas dos relatórios novos ou alterados.
- Relatórios excluídos no ReportBuilder somem do painel; pastas renomeadas/movidas são atualizadas.
- Os ajustes feitos no painel (rb_ajustes.json) são reaplicados depois de cada conversão.

Resultado: dados/relatorios_rb.json (catálogo usado pelo painel) e dados/rb_fonte.json (cache por relatório).
"""
import datetime as dt
import json
import os
import re
import struct
import threading
import time
import unicodedata

import rb_where as W
from config import BASE_DIR, DADOS_DIR

DADOS = DADOS_DIR
CATALOGO = os.path.join(DADOS, "relatorios_rb.json")
FONTE = os.path.join(DADOS, "rb_fonte.json")
ESTADO = os.path.join(DADOS, "rb_sync.json")
AJUSTES = os.path.join(BASE_DIR, "rb_ajustes.json")

_travas = {}


def _caminhos(bid):
    """(catálogo, fonte, estado) do banco. O principal usa dados\\ (como antes); os outros dados\\bancos\\<id>."""
    import bancos
    d = bancos.pasta(bid)
    return (os.path.join(d, "relatorios_rb.json"), os.path.join(d, "rb_fonte.json"), os.path.join(d, "rb_sync.json"),
            os.path.join(d, "rb_desenhos.json"))


def desenhos(bid="principal"):
    """Layouts de impressão lidos dos modelos do ReportBuilder: {id do relatório: desenho}."""
    return _ler(_caminhos(bid)[3], {})


def _ajustes(bid):
    """rb_ajustes.json: as entradas soltas valem para o banco principal; "_bancos": {"id": {...}} para os outros."""
    import bancos
    tudo = _ler(AJUSTES, {})
    if bid == bancos.PRINCIPAL:
        return tudo
    return (tudo.get("_bancos") or {}).get(bid) or {}

# módulo do painel exigido para ver o relatório, pela pasta de primeiro nível
MODULO_PASTA = {
    "Clientes/Fornecedores (F)": "cadastros", "Agenda/Contatos": "cadastros",
    "Contas à Pagar/Receber (F)": "financeiro", "Caixa/Contas Correntes (F)": "financeiro", "Contas à Receber (F)": "financeiro",
    "Contas à Pagar (F)": "financeiro", "Desconto de Duplicatas": "financeiro", "Comissao": "financeiro", "ImpressaoSistema": "financeiro",
    "Produtos (E)": "estoque", "Tabelas do Estoque (E)": "estoque", "Movimentação de Produtos(E)": "estoque", "Funcionários (E)": "estoque",
    "Ferramentas (E)": "estoque", "Compras (E)": "estoque", "Serviços de Corte/religação  (E)": "estoque", "Obras Terceiros (E)": "estoque",
    "Gestao de Frota (E)": "estoque", "Material(E)": "estoque",
    "Movimento (G)": "movimentos", "Ordem de Serviço": "movimentos", "Impressos": "movimentos", "Gerenciais (G)": "movimentos",
    "Obras Particulares (G)": "movimentos", "Teste": "movimentos",
}
RE_ANTIGO = re.compile(r"\b(old\d*|bkp\w*|backup|teste|test|c[oó]pia|nao usar|não usar|antig[oa]|erro av|mais antigo|duplicand)\b", re.I)


def _modulo(topo):
    if topo in MODULO_PASTA:
        return MODULO_PASTA[topo]
    t = topo.upper()
    if "(F)" in t or "FINANC" in t or "PAGAR" in t or "RECEBER" in t:
        return "financeiro"
    if "(E)" in t or "ESTOQUE" in t or "PRODUTO" in t:
        return "estoque"
    if "CLIENTE" in t or "FORNECEDOR" in t:
        return "cadastros"
    return "movimentos"


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# ------------------------------------------------------------------ leitura do modelo binário (DFM do Delphi)
def _lestr(b, i):
    t = b[i]
    i += 1
    if t in (0x06, 0x07):
        n = b[i]
        return b[i + 1:i + 1 + n].decode("cp1252", "replace"), i + 1 + n
    if t == 0x0C:
        n = struct.unpack("<I", b[i:i + 4])[0]
        return b[i + 4:i + 4 + n].decode("cp1252", "replace"), i + 4 + n
    if t == 0x12:
        n = struct.unpack("<I", b[i:i + 4])[0]
        return b[i + 4:i + 4 + 2 * n].decode("utf-16-le", "replace"), i + 4 + 2 * n
    if t == 0x14:
        n = struct.unpack("<I", b[i:i + 4])[0]
        return b[i + 4:i + 4 + n].decode("utf-8", "replace"), i + 4 + n
    raise ValueError(t)


def _prop(b, nome, ate=None):
    k = b.rfind(bytes([len(nome)]) + nome.encode(), 0, ate if ate is not None else len(b))
    if k < 0:
        return None
    try:
        return _lestr(b, k + 1 + len(nome))[0]
    except (ValueError, IndexError, struct.error):
        return None


class _Fim(Exception):
    pass


class _Leitor:
    def __init__(self, b, i=0):
        self.b, self.i = b, i

    def byte(self):
        if self.i >= len(self.b):
            raise _Fim()
        v = self.b[self.i]
        self.i += 1
        return v

    def bytes_(self, n):
        if self.i + n > len(self.b):
            raise _Fim()
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def sstr(self):
        n = self.byte()
        return self.bytes_(n).decode("cp1252", "replace")

    def valor(self, t=None):
        if t is None:
            t = self.byte()
        if t == 0:
            return None
        if t == 1:
            lst = []
            while True:
                if self.i >= len(self.b):
                    raise _Fim()
                if self.b[self.i] == 0:
                    self.i += 1
                    return lst
                lst.append(self.valor())
        if t == 2:
            return struct.unpack("<b", self.bytes_(1))[0]
        if t == 3:
            return struct.unpack("<h", self.bytes_(2))[0]
        if t == 4:
            return struct.unpack("<i", self.bytes_(4))[0]
        if t == 5:
            self.bytes_(10)
            return 0.0
        if t in (6, 7):
            return self.sstr()
        if t == 8:
            return False
        if t == 9:
            return True
        if t == 10:
            n = struct.unpack("<I", self.bytes_(4))[0]
            return self.bytes_(n)
        if t == 11:
            s = []
            while True:
                x = self.sstr()
                if not x:
                    return s
                s.append(x)
        if t == 12:
            n = struct.unpack("<I", self.bytes_(4))[0]
            return self.bytes_(n).decode("cp1252", "replace")
        if t == 13:
            return None
        if t == 14:
            itens = []
            while True:
                c = self.byte()
                if c == 0:
                    return itens
                if c in (2, 3, 4):
                    self.valor(c)
                    c = self.byte()
                self.i -= 1
                props = {}
                while True:
                    nome = self.sstr()
                    if not nome:
                        break
                    props[nome] = self.valor()
                itens.append(props)
        if t == 15:
            self.bytes_(4)
            return 0.0
        if t in (16, 17, 21):
            return struct.unpack("<d", self.bytes_(8))[0]
        if t == 18:
            n = struct.unpack("<I", self.bytes_(4))[0]
            return self.bytes_(2 * n).decode("utf-16-le", "replace")
        if t == 19:
            return struct.unpack("<q", self.bytes_(8))[0]
        if t == 20:
            n = struct.unpack("<I", self.bytes_(4))[0]
            return self.bytes_(n).decode("utf-8", "replace")
        raise ValueError(f"tipo {t} em {self.i}")

    def objeto(self):
        f = self.b[self.i]
        if f & 0xF0 == 0xF0:
            self.i += 1
            if f & 2:
                self.valor()
        classe = self.sstr()
        nome = self.sstr()
        props = {}
        while True:
            p = self.sstr()
            if not p:
                break
            props[p] = self.valor()
        filhos = []
        while self.i < len(self.b) and self.b[self.i] != 0:
            filhos.append(self.objeto())
        self.i += 1
        return {"classe": classe, "nome": nome, "props": props, "filhos": filhos}


def _criterios(seg):
    """seg começa em 'SQLType' (logo após o SQL de uma visão)."""
    r = _Leitor(seg, len("SQLType"))
    crits = []
    try:
        r.valor()
        if r.byte() != 0:
            return []
        while r.i < len(seg) and seg[r.i] != 0:
            o = r.objeto()
            if o["classe"] != "TdaCriteria":
                return crits
            campo = next((f["props"] for f in o["filhos"] if f["classe"] == "TdaField"), {})
            crits.append({**o["props"], "campo": campo})
        return crits
    except (_Fim, ValueError, IndexError, struct.error):
        return crits


def extrair_visoes(b):
    """Cada Data View do modelo: nome do pipeline, SQL, mestre, ligações e critérios."""
    blocos = []
    k = b.find(b"SQLText.Strings")
    while k >= 0:
        i = k + len("SQLText.Strings")
        linhas = []
        if b[i] == 1:
            i += 1
            while i < len(b) and b[i] != 0:
                s, i = _lestr(b, i)
                linhas.append(s)
        tq = b.rfind(b"TdaSQL", 0, k)
        cab = b[:tq] if tq > 0 else b[:k]
        ini = max(cab.rfind(b"TppChildDBPipeline"), cab.rfind(b"TppDBPipeline"), 0)
        cab = cab[ini:]
        master = _prop(cab, "MasterDataPipelineName") if b"MasterDataPipelineName" in cab else None
        links = []
        for m in re.finditer(rb"\x12TppMasterFieldLink", cab):
            try:
                o = _Leitor(cab, m.start()).objeto()      # lê o objeto inteiro (propriedades na ordem certa)
                links.append((o["props"].get("MasterFieldName"), o["props"].get("DetailFieldName")))
            except (_Fim, ValueError, IndexError, struct.error):
                seg = cab[m.end():m.end() + 200]
                links.append((_prop(seg, "MasterFieldName"), _prop(seg, "DetailFieldName")))
        crits = []
        s = b.find(b"SQLType", k)
        if s >= 0:
            fins = [b.find(x, s) for x in (b"TdaCalculation", b"TdaField\x08", b"TdaField\x09", b"TdaTable")]
            e = min([x for x in fins if x >= 0] or [len(b)])
            if b.find(b"TdaCriteria", s, e) >= 0:
                crits = _criterios(b[s:e])
        blocos.append({"pipeline": _prop(b, "DataPipelineName", k), "master": master, "links": links,
                       "sql": "\n".join(linhas), "criterios": crits})
        k = b.find(b"SQLText.Strings", k + 15)
    return blocos


# ------------------------------------------------------------------ conversão para o formato do painel
def _colunas_select(sql):
    m = re.search(r"\bSELECT\b(.*?)\bFROM\b", sql, re.S | re.I)
    if not m:
        return set()
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
    nomes = set()
    for c in itens:
        c = " ".join(c.split())
        if c:
            p = c.split(" ")
            nomes.add((p[-1] if len(p) > 1 else p[0].split(".")[-1]).upper().strip('"'))
    return nomes


def _trocar_codprd(sql, protegidos):
    """Mostra o código do fabricante (NUMNOFABRIC) no lugar do CODPRD; o vínculo continua pelo CODPRD."""
    m = re.match(r"(\s*SELECT\s+)(.*?)(\bFROM\b.*)$", sql, re.S | re.I)
    if not m:
        return sql
    itens, prof, atual = [], 0, ""
    for ch in m.group(2):
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
    novos = []
    for it in itens:
        mm = re.match(r"^(\s*)(\w+)\.CODPRD(?:\s+(?:AS\s+)?(\w+))?(\s*)$", it, re.I)
        if not mm:
            novos.append(it)
            continue
        nome = (mm.group(3) or "CODPRD").upper()
        sub = f"(SELECT FIRST 1 PNF.NUMNOFABRIC FROM TPRODUTO PNF WHERE PNF.CODPRD = {mm.group(2)}.CODPRD)"
        if nome in protegidos:
            novos.append(it.rstrip() + f", {sub} {nome}_FABRIC" + mm.group(4))
        else:
            novos.append(f"{mm.group(1)}{sub} {nome}{mm.group(4)}")
    return m.group(1) + ",".join(novos) + m.group(3)


def converter(blocos):
    """Lista de visões (do modelo) -> (parametros, visoes) no formato do painel."""
    params, visoes = {}, []
    nomes = [b["pipeline"] for b in blocos]
    for b in blocos:
        sql = b["sql"].strip()
        if b["criterios"]:
            try:
                lit = W.montar(b["criterios"])
                if W.norm(lit) == W.norm(W.where_atual("\n" + sql)):
                    novo_params = dict(params)
                    novo = W.montar(b["criterios"], literal=False, params=novo_params)
                    sql = W.substituir_where(sql, novo)
                    params.clear()
                    params.update(novo_params)
            except (ValueError, KeyError, TypeError):
                pass       # mantém o SQL original do ReportBuilder
        cols = _colunas_select(sql)
        master = b["master"]
        links = [tuple(l) for l in b["links"] if l[0] and l[1]]
        if links and not master:
            for v in visoes:
                if all(l[0].upper() in v["_cols"] for l in links):
                    master = v["nome"]
                    break
        if master and master not in nomes:
            master = None
        if master:
            mv = next((v for v in visoes if v["nome"] == master), None)
            # mantém só as ligações cujos campos existem nas duas visões
            links = [l for l in links if mv is not None and l[0].upper() in mv["_cols"] and l[1].upper() in cols]
        visoes.append({"nome": b["pipeline"], "sql": sql, "mestre": master if links else None,
                       "ligacoes": [list(l) for l in links] if master and links else [], "_cols": cols})
    for v in visoes:
        prot = {d.upper() for _, d in v["ligacoes"]}
        for w in visoes:
            if w.get("mestre") == v["nome"]:
                prot |= {m_.upper() for m_, _ in w["ligacoes"]}
        v["sql"] = _trocar_codprd(v["sql"], prot)
    for v in visoes:
        v.pop("_cols")
    return list(params.values()), visoes


def _data_delphi(x):
    try:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(x))).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


# ------------------------------------------------------------------ ajustes feitos no painel
def aplicar_ajustes(rel, aj):
    """Reaplica, sobre a conversão do ReportBuilder, as mudanças feitas no painel para este relatório."""
    if not aj:
        return rel
    rel = json.loads(json.dumps(rel))
    for nome, trechos in (aj.get("remover_trechos") or {}).items():
        for v in rel["visoes"]:
            if v["nome"] == nome:
                for t in trechos:
                    v["sql"] = v["sql"].replace(t, "")
    if aj.get("manter_visoes"):
        rel["visoes"] = [v for v in rel["visoes"] if v["nome"] in aj["manter_visoes"]]
    for ins in aj.get("inserir_visoes") or []:
        rel["visoes"] = [v for v in rel["visoes"] if v["nome"] != ins["visao"]["nome"]]
        rel["visoes"].insert(ins.get("posicao", len(rel["visoes"])), ins["visao"])
    if aj.get("remover_parametros"):
        rel["parametros"] = [p for p in rel["parametros"] if p["nome"] not in aj["remover_parametros"]]
    if aj.get("layout_padrao"):
        rel["layout_padrao"] = aj["layout_padrao"]
    rel["ajustado"] = True
    return rel


def _ler(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


espelho = None      # site: função (caminho, texto) que guarda uma cópia do arquivo no banco do site


def _gravar(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    texto = json.dumps(dados, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(tmp, caminho)
    if espelho:
        espelho(caminho, texto)


def estado(bid="principal"):
    return _ler(_caminhos(bid)[2], {})


# ------------------------------------------------------------------ sincronização
def sincronizar(banco, forcar=False, bid="principal"):
    """Compara o ReportBuilder do banco com o catálogo do painel e atualiza o que mudou.
    Devolve um resumo {novos, alterados, removidos, erros, total}."""
    CATALOGO, FONTE, ESTADO, DESENHOS = _caminhos(bid)
    import desenho as _desenho
    _trava = _travas.setdefault(bid, threading.Lock())
    if not _trava.acquire(blocking=False):
        return {"ocupado": True}
    inicio = time.time()
    st = estado(bid)
    try:
        st.update(andamento=True, inicio=dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        _gravar(ESTADO, st)
        _, pastas_l, _ = banco.consultar("SELECT FOLDER_ID, NAME, PARENT_ID FROM RB_FOLDER")
        pastas = {int(f): ((n or "").strip(), int(p) if p is not None else 0) for f, n, p in pastas_l}
        _, itens_l, _ = banco.consultar(
            "SELECT ITEM_ID, FOLDER_ID, NAME, MODIFIED FROM RB_ITEM "
            "WHERE ITEM_TYPE = 1 AND (DELETED IS NULL OR DELETED = 0)")

        def caminho(fid):
            partes, vistos = [], set()
            while fid in pastas and fid not in vistos and len(partes) < 8:
                vistos.add(fid)
                nome, pai = pastas[fid]
                partes.insert(0, nome)
                fid = pai
            return " / ".join(partes) if partes else "(sem pasta)"

        def topo(fid):
            ult, vistos = fid, set()
            while fid in pastas and fid not in vistos:
                vistos.add(fid)
                ult = fid
                fid = pastas[fid][1]
            return pastas.get(ult, ("(sem pasta)", 0))[0]

        fonte = {} if forcar else _ler(FONTE, {})
        desenhos_rb = {} if forcar else _ler(DESENHOS, {})
        atuais, novos, alterados, erros = {}, [], [], []
        for iid, fid, nome, mod in itens_l:
            rid = f"{iid}-{fid if fid >= 0 else 'x'}"
            atuais[rid] = (iid, fid, (nome or "").strip(), float(mod))
            ant = fonte.get(rid)
            mesmo = bool(ant) and abs(ant.get("modified", 0) - float(mod)) < 1e-9
            if mesmo and rid in desenhos_rb:
                continue
            try:
                _, t, _ = banco.consultar_blob("SELECT TEMPLATE FROM RB_ITEM WHERE ITEM_ID = ? AND FOLDER_ID = ? AND MODIFIED = ?",
                                               (iid, fid, mod))
                if not t:   # MODIFIED com arredondamento diferente: busca pela chave do item
                    _, t, _ = banco.consultar_blob("SELECT TEMPLATE FROM RB_ITEM WHERE ITEM_ID = ? AND FOLDER_ID = ? "
                                                   "AND (DELETED IS NULL OR DELETED = 0) ORDER BY MODIFIED DESC", (iid, fid))
                b = t[0][0] if t else None
                try:      # layout de impressão (bandas, posições) - também para os já convertidos antes
                    desenhos_rb[rid] = (_desenho.importar(b) if b else None) or False
                except Exception:  # noqa: BLE001
                    desenhos_rb[rid] = False
                if mesmo:
                    continue
                blocos = extrair_visoes(b) if b else []
                if not blocos:
                    fonte.pop(rid, None)
                    continue
                parametros, visoes = converter(blocos)
                fonte[rid] = {"modified": float(mod), "parametros": parametros, "visoes": visoes}
                (alterados if ant else novos).append(rid)
            except Exception as e:  # noqa: BLE001 - um relatório com problema não para os outros
                erros.append(f"{nome}: {e}")
        removidos = [r for r in list(fonte) if r not in atuais]
        for r in removidos:
            fonte.pop(r)
        for r in [r for r in desenhos_rb if r not in atuais]:
            desenhos_rb.pop(r)
        _gravar(FONTE, fonte)
        _gravar(DESENHOS, desenhos_rb)

        ajustes = _ajustes(bid)
        catalogo = []
        for rid, (iid, fid, nome, mod) in atuais.items():
            f = fonte.get(rid)
            if not f:
                continue
            pasta, top = caminho(fid), topo(fid)
            rel = {
                "id": rid, "nome": nome, "pasta": pasta, "modulo": _modulo(top), "alterado": _data_delphi(mod),
                "antigo": bool(RE_ANTIGO.search(_sem_acento(nome))) or top == "Teste" or "BKP" in pasta or fid in (-2, 0),
                "lixeira": fid == -2, "parametros": f["parametros"], "visoes": f["visoes"],
            }
            catalogo.append(aplicar_ajustes(rel, ajustes.get(rid)))
        catalogo.sort(key=lambda r: (r["pasta"], r["nome"]))
        _gravar(CATALOGO, catalogo)
        res = {"novos": len(novos), "alterados": len(alterados), "removidos": len(removidos), "erros": erros[:50],
               "total": len(catalogo), "segundos": round(time.time() - inicio, 1),
               "nomes_novos": [atuais[r][2] for r in novos][:30], "nomes_alterados": [atuais[r][2] for r in alterados][:30]}
        st = {"andamento": False, "ultima": dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "resultado": res}
        if novos or alterados or removidos:
            st["ultima_mudanca"] = st["ultima"]
            st["resultado_mudanca"] = res
        else:
            ant_st = estado(bid)
            for k in ("ultima_mudanca", "resultado_mudanca"):
                if k in ant_st:
                    st[k] = ant_st[k]
        _gravar(ESTADO, st)
        return res
    except Exception as e:  # noqa: BLE001
        st.update(andamento=False, erro=str(e)[:500], ultima=dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        _gravar(ESTADO, st)
        raise
    finally:
        _trava.release()


def iniciar_automatico(banco_fn, minutos, ao_mudar=None, registrar=None, bid="principal"):
    """Thread que sincroniza ao iniciar o painel e depois a cada `minutos`."""
    if minutos <= 0:
        return

    def laco():
        time.sleep(5)
        while True:
            try:
                r = sincronizar(banco_fn(), bid=bid)
                if not r.get("ocupado") and (r["novos"] or r["alterados"] or r["removidos"]):
                    if ao_mudar:
                        ao_mudar()
                    if registrar:
                        registrar(f"{r['novos']} novo(s), {r['alterados']} alterado(s), {r['removidos']} removido(s)")
            except Exception:  # noqa: BLE001 - banco fora do ar etc.: tenta de novo no próximo ciclo
                pass
            time.sleep(max(1, minutos) * 60)

    threading.Thread(target=laco, daemon=True, name=f"rb-sync-{bid}").start()
