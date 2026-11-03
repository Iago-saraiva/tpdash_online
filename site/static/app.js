/* TP DASH - lógica das telas */
(function () {
  "use strict";
  const G = window.Graficos;
  const F = G.F;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const TOKEN = document.querySelector('meta[name="csrf"]')?.content || "";

  /* ------------------------------------------------------------- utilidades */
  /* fetch com novas tentativas: se o servidor estiver reiniciando ou a rede oscilar
     (conexão recusada / sem resposta), tenta de novo algumas vezes antes de mostrar erro. */
  const ESPERAS = [800, 2000, 4000, 7000, 10000];
  function avisoConexao(mostrar) {
    let a = document.getElementById("sem-conexao");
    if (!mostrar) { if (a) a.remove(); return; }
    if (!a) {
      a = document.createElement("div");
      a.id = "sem-conexao"; a.className = "sem-conexao"; a.setAttribute("role", "status");
      a.textContent = "Sem resposta do servidor. Tentando de novo...";
      document.body.appendChild(a);
    }
  }
  async function buscar(url, op) {
    for (let i = 0; ; i++) {
      try {
        const resp = await fetch(url, op);
        if ((resp.status === 502 || resp.status === 503 || resp.status === 504) && i < 2) throw new TypeError("indisponível");
        if (i) avisoConexao(false);
        return resp;
      } catch (e) {
        if (!(e instanceof TypeError) || i >= ESPERAS.length) {
          avisoConexao(false);
          if (e instanceof TypeError) {
            throw new Error("Não foi possível falar com o servidor (conexão recusada ou sem rede). " +
              "Ele pode estar reiniciando: aguarde alguns segundos e tente de novo. Se continuar, confira se o servidor está ligado.");
          }
          throw e;
        }
        avisoConexao(true);
        await new Promise((ok) => setTimeout(ok, ESPERAS[i]));
      }
    }
  }

  async function api(url, opcoes = {}) {
    const op = { headers: { "X-Painel": TOKEN }, ...opcoes };
    if (op.json !== undefined) {
      op.method = op.method || "POST";
      op.headers["Content-Type"] = "application/json";
      op.body = JSON.stringify(op.json);
      delete op.json;
    }
    const r = await buscar(url, op);
    let d = null;
    try { d = await r.json(); } catch (e) { /* sem JSON */ }
    if (r.status === 401) { location.href = "/login?proximo=" + encodeURIComponent(location.pathname + location.search); throw new Error("Sessão expirada"); }
    if (!r.ok) throw new Error((d && d.erro) || `Erro ${r.status}`);
    return d;
  }

  async function baixar(url, opcoes) {
    const op = { headers: { "X-Painel": TOKEN }, ...opcoes };
    if (op.json !== undefined) {
      op.method = "POST";
      op.headers["Content-Type"] = "application/json";
      op.body = JSON.stringify(op.json);
      delete op.json;
    }
    const r = await buscar(url, op);
    if (!r.ok) {
      let msg = `Erro ${r.status}`;
      try { msg = (await r.json()).erro || msg; } catch (e) { /* */ }
      throw new Error(msg);
    }
    const blob = await r.blob();
    const nome = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "arquivo";
    if (window.PainelApp && window.PainelApp.salvar) {
      // dentro do app Android: o arquivo é salvo em Downloads e aberto pelo próprio celular
      const leitor = new FileReader();
      leitor.onload = () => window.PainelApp.salvar(String(leitor.result).split(",")[1], blob.type, nome);
      leitor.readAsDataURL(blob);
      return;
    }
    const href = URL.createObjectURL(blob);
    if (blob.type === "application/pdf") {
      window.open(href, "_blank");
    } else {
      const a = document.createElement("a");
      a.href = href; a.download = nome; document.body.appendChild(a); a.click(); a.remove();
    }
    setTimeout(() => URL.revokeObjectURL(href), 60000);
  }

  const MOEDA = /^(VALOR|TOTAL|PRECO|CUSTO|LIMITE|VLR_UNIT|VALOR_.*|CUSTO_.*|.*_VALOR)$/i;
  const SOMAVEL = /^(VALOR|TOTAL|VALOR_ESTOQUE|VALOR_BAIXADO|VALOR_DOC|.*_VALOR)$/i;
  const DATA = /^(EMISSAO|VENCIMENTO|BAIXA|CADASTRO|ULTIMA_VENDA|DATA.*|DT.*)$/i;
  function fmtData(v) {
    if (typeof v !== "string" || v.length < 10 || v[4] !== "-") return v ?? "";
    const d = `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}`;
    return v.length > 10 && v.slice(11, 16) !== "00:00" ? d + " " + v.slice(11, 16) : d;
  }
  function fmtCel(col, v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return MOEDA.test(col) ? F.moeda(v).replace("R$ ", "") : F.numero(v);
    if (DATA.test(col) || /^\d{4}-\d{2}-\d{2}/.test(v)) return fmtData(v);
    return String(v);
  }
  const NUMFMT = new Set(["moeda", "inteiro", "numero", "percentual"]);
  function fmtValor(fmt, v) {
    if (v === null || v === undefined || v === "") return "";
    if (fmt === "moeda" && typeof v === "number") return F.moeda(v).replace("R$ ", "");
    if (fmt === "inteiro" && typeof v === "number") return F.inteiro(v);
    if (fmt === "numero" && typeof v === "number") return F.numero(v);
    if (fmt === "percentual" && typeof v === "number") return F.numero(v) + "%";
    if ((fmt === "data" || fmt === "datahora") && typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) {
      const d = `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}`;
      return fmt === "datahora" && v.length >= 16 ? d + " " + v.slice(11, 16) : d;
    }
    if (typeof v === "number") return F.numero(v);
    return String(v);
  }
  function agregarJS(vals, ag) {
    const vs = vals.filter((v) => v !== null && v !== undefined);
    if (ag === "contagem") return vs.length;
    const ns = vs.filter((v) => typeof v === "number");
    if (ag === "soma") return ns.length ? ns.reduce((a, b) => a + b, 0) : null;
    if (ag === "media") return ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : null;
    if (ag === "minimo" || ag === "maximo") {
      if (!vs.length) return null;
      const ord = vs.slice().sort((a, b) => (typeof a === "number" ? a - b : String(a).localeCompare(String(b))));
      return ag === "minimo" ? ord[0] : ord[ord.length - 1];
    }
    return null;
  }
  function rotuloCol(c) {
    const m = { CPF_CNPJ: "CPF/CNPJ", NCM: "NCM", CEST: "CEST", CODCFO: "Cód. cliente", CODTMV: "Tipo mov.", CODLOC: "Local", UND: "Und",
      VLR_UNIT: "Vlr unit.", SIT_DENTRO: "Sit. dentro UF", SIT_FORA: "Sit. fora UF", DESC_DENTRO: "Descr. dentro", DESC_FORA: "Descr. fora",
      CST_PISCOFINS: "CST PIS/COFINS", DIAS_ATRASO: "Dias atraso", VALOR_BAIXADO: "Valor baixado", VALOR_ESTOQUE: "Valor estoque",
      CUSTO_MEDIO: "Custo médio", modulos: "Módulos", usuario: "Usuário", acao: "Ação", ultimo_acesso: "Último acesso", CODIGO: "Código", CENTRO_CUSTO: "Centro de custo", COD_FABRICANTE: "Cód. fabricante", CODPRD_INT: "Cód. interno", SITUACAO: "Situação", DOCUMENTO: "Documento", NOME_LOCAL: "Nome do local", TIPO_DOC: "Tipo doc.", ULTIMA_VENDA: "Última venda", EMISSAO: "Emissão", PRECO: "Preço", ORIGEM: "Origem", CEST: "CEST", LANCAMENTOS: "Lançamentos", PAGREC: "Pagar/Receber" };
    if (m[c]) return m[c];
    const t = c.replace(/_/g, " ").toLowerCase();
    return t.charAt(0).toUpperCase() + t.slice(1);
  }
  function aviso(cont, msg, tipo = "erro") {
    const d = document.createElement("div");
    d.className = "aviso " + tipo;
    d.textContent = msg;
    cont.prepend(d);
    setTimeout(() => d.remove(), 9000);
    return d;
  }

  /* ------------------------------------------------------------- tabela */
  class Tabela {
    constructor(cont, op = {}) {
      this.cont = cont;
      this.op = op;
      this.pagina = 0;
      this.porPagina = op.porPagina || 100;
      this.ordem = null;
      this.busca = "";
      cont.replaceChildren();
      const barra = document.createElement("div");
      barra.className = "tabela-barra";
      this.info = document.createElement("span");
      this.info.className = "info";
      const busca = document.createElement("input");
      busca.className = "campo busca";
      busca.placeholder = "Filtrar nesta tabela…";
      busca.addEventListener("input", () => { this.busca = busca.value.toLowerCase(); this.pagina = 0; this.render(); });
      barra.append(this.info, busca);
      (op.botoes || []).forEach((b) => barra.appendChild(b));
      this.wrap = document.createElement("div");
      this.wrap.className = "tabela-wrap";
      this.pag = document.createElement("div");
      this.pag.className = "paginacao";
      cont.append(barra, this.wrap, this.pag);
    }
    definir(dados, truncado) {
      this.dados = dados;
      this.truncado = truncado;
      const ocultar = new Set(this.op.ocultar || []);
      this.cols = dados.colunas.map((c, i) => ({ c, i })).filter((x) => !ocultar.has(x.c));
      this.defs = this.op.defs || null;   // layout: [{rotulo, formato, total}] na mesma ordem das colunas
      this.numericas = new Set(this.defs ? this.cols.filter((x) => NUMFMT.has(this.defs[x.i].formato)).map((x) => x.i)
        : this.cols.filter((x) => dados.linhas.some((r) => typeof r[x.i] === "number")).map((x) => x.i));
      this.pagina = 0;
      this.render();
    }
    filtradas() {
      let ls = this.dados.linhas;
      if (this.busca) ls = ls.filter((r) => r.some((v) => v !== null && String(v).toLowerCase().includes(this.busca) || (typeof v === "string" && fmtData(v).includes(this.busca))));
      if (this.ordem) {
        const { i, dir } = this.ordem;
        ls = ls.slice().sort((a, b) => {
          const x = a[i], y = b[i];
          if (x === y) return 0;
          if (x === null || x === undefined) return 1;
          if (y === null || y === undefined) return -1;
          return (typeof x === "number" ? x - y : String(x).localeCompare(String(y), "pt-BR", { numeric: true })) * dir;
        });
      }
      return ls;
    }
    render() {
      const ls = this.filtradas();
      const total = ls.length;
      const ini = this.pagina * this.porPagina;
      const pag = ls.slice(ini, ini + this.porPagina);
      if (this.defs && this.defs.some((d) => d.abaixo)) {
        this.wrap.replaceChildren(this.empilhada(ls, pag));
        this.rodape(total);
        return;
      }
      const tb = document.createElement("table");
      tb.className = "dados";
      const th = tb.createTHead().insertRow();
      this.cols.forEach(({ c, i }) => {
        const h = document.createElement("th");
        h.textContent = this.defs ? this.defs[i].rotulo : (this.op.rotulos && this.op.rotulos[c]) || rotuloCol(c);
        if (this.numericas.has(i)) h.className = "num";
        if (this.ordem && this.ordem.i === i) {
          const s = document.createElement("span");
          s.className = "seta";
          s.textContent = this.ordem.dir > 0 ? "▲" : "▼";
          h.appendChild(s);
        }
        h.addEventListener("click", () => {
          this.ordem = this.ordem && this.ordem.i === i ? { i, dir: -this.ordem.dir } : { i, dir: this.numericas.has(i) ? -1 : 1 };
          this.render();
        });
        th.appendChild(h);
      });
      const body = tb.createTBody();
      pag.forEach((r) => {
        const tr = body.insertRow();
        if (this.op.onClick) {
          tr.className = "clicavel";
          tr.addEventListener("click", () => this.op.onClick(r, this.dados.colunas));
        }
        this.cols.forEach(({ c, i }) => {
          const td = tr.insertCell();
          const v = r[i];
          if (this.op.celula && this.op.celula(c, v, td, r)) return;
          td.textContent = this.defs ? fmtValor(this.defs[i].formato, v) : fmtCel(c, v);
          if (typeof v === "string" && v.length > 40) td.title = v;
          if (this.numericas.has(i)) { td.className = "num"; if (v < 0) td.classList.add("neg"); }
        });
      });
      // totais das colunas de valor
      if (this.defs && total && this.cols.some(({ i }) => this.defs[i].total !== "nenhum")) {
        const tr = tb.createTFoot().insertRow();
        this.cols.forEach(({ i }, k) => {
          const td = tr.insertCell();
          const d = this.defs[i];
          if (d.total !== "nenhum") {
            const x = agregarJS(ls.map((r) => r[i]), d.total);
            td.textContent = fmtValor(d.total === "contagem" ? "inteiro" : d.formato, x);
            if (this.numericas.has(i) || d.total === "contagem") td.className = "num";
          } else if (k === 0) td.textContent = "Total";
        });
      }
      const somar = this.defs ? [] : this.cols.filter(({ c, i }) => this.numericas.has(i) && SOMAVEL.test(c));
      if (somar.length && total) {
        const tr = tb.createTFoot().insertRow();
        this.cols.forEach(({ c, i }, k) => {
          const td = tr.insertCell();
          if (k === 0) td.textContent = "Total";
          if (somar.some((s) => s.i === i)) {
            td.className = "num";
            td.textContent = F.moeda(ls.reduce((a, r) => a + (r[i] || 0), 0)).replace("R$ ", "");
          }
        });
      }
      this.wrap.replaceChildren(tb);
      this.rodape(total);
    }
    /* colunas marcadas "abaixo" no layout aparecem embaixo da anterior, na mesma célula */
    empilhada(ls, pag) {
      const grupos = [];
      this.cols.forEach((x) => { if (this.defs[x.i].abaixo && grupos.length) grupos[grupos.length - 1].push(x); else grupos.push([x]); });
      const tb = el("table", "dados empilhada");
      const th = tb.createTHead().insertRow();
      grupos.forEach((gr) => {
        const h = el("th", gr.every((x) => this.numericas.has(x.i)) ? "num" : "");
        gr.forEach((x) => h.appendChild(el("div", "", this.defs[x.i].rotulo)));
        const i = gr[0].i;
        if (this.ordem && this.ordem.i === i) h.firstChild.appendChild(el("span", "seta", this.ordem.dir > 0 ? "▲" : "▼"));
        h.addEventListener("click", () => {
          this.ordem = this.ordem && this.ordem.i === i ? { i, dir: -this.ordem.dir } : { i, dir: this.numericas.has(i) ? -1 : 1 };
          this.render();
        });
        th.appendChild(h);
      });
      const celula = (tr, gr, vals, negrito) => {
        const td = tr.insertCell();
        if (gr.every((x) => this.numericas.has(x.i))) td.className = "num";
        gr.forEach((x) => {
          const v = vals(x);
          const d = el("div", v.neg ? "neg" : "", v.t || "\u00a0");
          if (negrito) d.style.fontWeight = "600";
          td.appendChild(d);
        });
        return td;
      };
      const body = tb.createTBody();
      pag.forEach((r) => {
        const tr = body.insertRow();
        grupos.forEach((gr) => celula(tr, gr, (x) => ({ t: fmtValor(this.defs[x.i].formato, r[x.i]), neg: typeof r[x.i] === "number" && r[x.i] < 0 })));
      });
      if (ls.length && this.cols.some(({ i }) => this.defs[i].total !== "nenhum")) {
        const tr = tb.createTFoot().insertRow();
        grupos.forEach((gr, k) => {
          const td = celula(tr, gr, (x) => {
            const d = this.defs[x.i];
            if (d.total === "nenhum") return { t: "" };
            return { t: fmtValor(d.total === "contagem" ? "inteiro" : d.formato, agregarJS(ls.map((r) => r[x.i]), d.total)) };
          });
          if (k === 0 && !td.textContent.trim()) td.firstChild.textContent = "Total";
        });
      }
      return tb;
    }
    rodape(total) {
      this.info.textContent = `${F.inteiro(total)} ${total === 1 ? "linha" : "linhas"}` +
        (this.truncado ? " · limite atingido, refine os filtros para ver tudo" : "");
      this.pag.replaceChildren();
      const paginas = Math.ceil(total / this.porPagina);
      if (paginas > 1) {
        const ant = document.createElement("button"); ant.className = "btn pequeno"; ant.textContent = "‹ Anterior";
        ant.disabled = this.pagina === 0; ant.onclick = () => { this.pagina--; this.render(); };
        const prox = document.createElement("button"); prox.className = "btn pequeno"; prox.textContent = "Próxima ›";
        prox.disabled = this.pagina >= paginas - 1; prox.onclick = () => { this.pagina++; this.render(); };
        const s = document.createElement("span"); s.textContent = `Página ${this.pagina + 1} de ${paginas}`;
        this.pag.append(ant, s, prox);
      }
    }
  }

  /* ------------------------------------------------------------- KPIs */
  function kpis(cont, lista) {
    cont.replaceChildren();
    lista.forEach((k) => {
      const d = document.createElement("div");
      d.className = "kpi" + (k.classe ? " " + k.classe : "");
      const r = document.createElement("div"); r.className = "rot"; r.textContent = k.rotulo;
      const v = document.createElement("div"); v.className = "val"; v.textContent = k.valor;
      d.append(r, v);
      if (k.detalhe) { const t = document.createElement("div"); t.className = "det"; t.textContent = k.detalhe; d.appendChild(t); }
      if (k.variacao !== undefined && k.variacao !== null) {
        const t = document.createElement("div");
        const v = k.variacao;
        t.className = "var " + (Math.abs(v) < 0.5 ? "igual" : v > 0 ? "sobe" : "desce");
        t.textContent = (Math.abs(v) < 0.5 ? "● " : v > 0 ? "▲ " : "▼ ") + Math.abs(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 }) + "% " + (k.varTexto || "");
        d.appendChild(t);
      }
      if (k.spark && k.spark.length > 1) d.appendChild(sparkline(k.spark, k.sparkRot || []));
      cont.appendChild(d);
    });
  }

  function sparkline(vals, rots) {
    const NS = "http://www.w3.org/2000/svg", W = 120, H = 30, n = vals.length;
    const max = Math.max(...vals), min = Math.min(...vals, 0);
    const x = (i) => 3 + (i / (n - 1)) * (W - 6), y = (v) => 3 + (H - 6) * (1 - (v - min) / ((max - min) || 1));
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none");
    const pts = vals.map((v, i) => `${x(i)},${y(v)}`);
    const area = document.createElementNS(NS, "path");
    area.setAttribute("d", `M${x(0)},${H} L${pts.join(" L")} L${x(n - 1)},${H} Z`); area.setAttribute("class", "spark-area");
    const lin = document.createElementNS(NS, "polyline");
    lin.setAttribute("points", pts.join(" ")); lin.setAttribute("class", "spark-linha");
    const pto = document.createElementNS(NS, "circle");
    pto.setAttribute("cx", x(n - 1)); pto.setAttribute("cy", y(vals[n - 1])); pto.setAttribute("r", 2.6); pto.setAttribute("class", "spark-ponto");
    svg.append(area, lin, pto);
    const box = document.createElement("div"); box.className = "spark-box";
    box.title = "Últimos 6 meses: " + vals.map((v, i) => `${G.F.mes(rots[i] || "")} ${G.F.compacto(v)}`).join(" · ");
    const leg = document.createElement("span"); leg.className = "spark-leg"; leg.textContent = "6 meses";
    box.append(svg, leg);
    return box;
  }

  /* ------------------------------------------------------------- filtros ligados à URL */
  function lerFiltros(form) {
    const p = new URLSearchParams();
    new FormData(form).forEach((v, k) => {
      if (v === "" || v === null) return;
      if (p.has(k)) p.set(k, p.get(k) + "," + v); else p.set(k, v);
    });
    $$("select[multiple]", form).forEach((s) => {
      const vals = Array.from(s.selectedOptions).map((o) => o.value).filter(Boolean);
      p.delete(s.name);
      if (vals.length) p.set(s.name, vals.join(","));
    });
    $$("input[type=checkbox]", form).forEach((c) => { if (!c.checked) p.delete(c.name); });
    return p;
  }
  function preencherFiltros(form, params) {
    params.forEach((v, k) => {
      const campo = form.elements[k];
      if (!campo) return;
      if (campo.type === "checkbox") campo.checked = v === campo.value;
      else if (campo.multiple) Array.from(campo.options).forEach((o) => (o.selected = v.split(",").includes(o.value)));
      else campo.value = v;
      if (campo._sincronizar) campo._sincronizar();
    });
  }
  function iso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
  function presets(form, alvo) {
    const cont = $(".presets", form);
    if (!cont) return;
    const hoje = new Date();
    const ops = [
      ["Mês", () => [new Date(hoje.getFullYear(), hoje.getMonth(), 1), hoje]],
      ["60 dias", () => [new Date(hoje.getTime() - 59 * 864e5), hoje]],
      ["90 dias", () => [new Date(hoje.getTime() - 89 * 864e5), hoje]],
      ["Ano", () => [new Date(hoje.getFullYear(), 0, 1), hoje]],
      ["12 meses", () => [new Date(hoje.getFullYear(), hoje.getMonth() - 11, 1), hoje]],
    ];
    ops.forEach(([rot, fn]) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn pequeno"; b.textContent = rot;
      b.onclick = () => { const [a, z] = fn(); form.elements.ini.value = iso(a); form.elements.fim.value = iso(z); alvo(); };
      cont.appendChild(b);
    });
  }
  function opcoesSelect(sel, lista, vazio) {
    if (!sel) return;
    const atual = sel.value;
    sel.replaceChildren();
    if (vazio !== undefined) { const o = document.createElement("option"); o.value = ""; o.textContent = vazio; sel.appendChild(o); }
    lista.forEach((x) => {
      const o = document.createElement("option");
      o.value = x.cod; o.textContent = x.nome ? `${x.cod} - ${x.nome}` : x.cod;
      sel.appendChild(o);
    });
    sel.value = atual;
  }

  /* Escolha múltipla com caixas de seleção (ex.: tipos de documento). Guarda os códigos separados por
     vírgula num <input type="hidden">, então funciona com os filtros na URL, Limpar e exportação. */
  function multiEscolha(input, lista, vazio, aoMudar, unidade = "tipos selecionados") {
    if (!input) return;
    let caixa = input._multi;
    if (!caixa) {
      caixa = el("div", "multi");
      const botao = el("button", "multi-botao campo"); botao.type = "button";
      botao.setAttribute("aria-haspopup", "listbox");
      const painel = el("div", "multi-painel"); painel.hidden = true;
      const busca = el("input", "campo"); busca.placeholder = "Buscar…";
      const acoes = el("div", "multi-acoes");
      const todos = el("button", "btn pequeno", "Marcar todos"); todos.type = "button";
      const nenhum = el("button", "btn pequeno", "Limpar"); nenhum.type = "button";
      acoes.append(todos, nenhum);
      const itens = el("div", "multi-itens");
      painel.append(busca, acoes, itens);
      caixa.append(botao, painel);
      input.after(caixa);
      input._multi = caixa;
      caixa._botao = botao; caixa._itens = itens; caixa._painel = painel;
      let antes = "";
      const abrir = (s) => {
        if (s === !painel.hidden) return;
        painel.hidden = !s;
        botao.classList.toggle("aberto", s);
        if (s) { antes = input.value; busca.value = ""; filtrar(); busca.focus(); }
        else if (input.value !== antes && caixa._aoMudar) caixa._aoMudar();     // aplica ao fechar
      };
      const filtrar = () => {
        const q = busca.value.trim().toLowerCase();
        itens.querySelectorAll("label").forEach((l) => { l.hidden = q && !l.textContent.toLowerCase().includes(q); });
      };
      botao.onclick = (e) => { e.stopPropagation(); abrir(painel.hidden); };
      busca.oninput = filtrar;
      painel.addEventListener("click", (e) => e.stopPropagation());
      document.addEventListener("click", () => abrir(false));
      caixa.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); abrir(false); botao.focus(); } });
      const marcar = (v) => { itens.querySelectorAll("label:not([hidden]) input").forEach((c) => (c.checked = v)); caixa._ler(); };
      todos.onclick = () => marcar(true);
      nenhum.onclick = () => marcar(false);
      caixa._ler = () => {
        input.value = Array.from(itens.querySelectorAll("input:checked")).map((c) => c.value).join(",");
        caixa._sync();
      };
      caixa._sync = () => {
        const sel = (input.value || "").split(",").filter(Boolean);
        itens.querySelectorAll("input").forEach((c) => (c.checked = sel.includes(c.value)));
        const nomes = sel.map((v) => { const c = itens.querySelector(`input[value="${CSS.escape(v)}"]`); return c ? c.dataset.rot : v; });
        botao.textContent = !sel.length ? vazio : sel.length <= 2 ? nomes.join(", ") : `${sel.length} ${unidade}`;
        botao.title = nomes.join(", ") || vazio;
      };
    }
    caixa._aoMudar = aoMudar;
    caixa._itens.replaceChildren();
    lista.forEach((x) => {
      const l = el("label", "check");
      const c = document.createElement("input"); c.type = "checkbox"; c.value = x.cod;
      c.dataset.rot = x.cod;
      c.onchange = () => caixa._ler();
      l.append(c, " " + (x.nome ? `${x.cod} - ${x.nome}` : x.cod));
      caixa._itens.appendChild(l);
    });
    caixa._sync();
    input._sincronizar = () => caixa._sync();
  }

  /* Monta uma página de dados: filtros -> API -> render. Também liga os botões Excel/PDF. */
  function paginaDados({ form, url, render, aoIniciar }) {
    const raiz = $(".conteudo");
    let ultimo = null;
    async function carregar() {
      const p = lerFiltros(form);
      history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : ""));
      raiz.classList.add("carregando");
      try {
        const d = await api(url() + "?" + p);
        ultimo = d;
        render(d, p);
      } catch (e) {
        aviso(raiz, e.message);
      } finally {
        raiz.classList.remove("carregando");
      }
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); carregar(); });
    form.addEventListener("change", (e) => { if (e.target.dataset.auto !== undefined) carregar(); });
    presets(form, carregar);
    preencherFiltros(form, new URLSearchParams(location.search));
    if (form.elements.ini && form.elements.fim && $("#periodo-global")) {
      const usarPeriodo = ([a, z]) => { form.elements.ini.value = a; form.elements.fim.value = z; };
      if (!new URLSearchParams(location.search).has("ini")) usarPeriodo(datasPeriodo(periodoGlobal()));
      aoMudarPeriodo = (d) => { usarPeriodo(d); carregar(); };
    }
    $$("[data-exportar]", form.closest(".secao") || document).forEach((b) => b.addEventListener("click", async () => {
      const p = lerFiltros(form);
      p.set("formato", b.dataset.exportar);
      b.disabled = true;
      try { await baixar(url() + "?" + p); } catch (e) { aviso(raiz, e.message); } finally { b.disabled = false; }
    }));
    const iniciar = async () => { if (aoIniciar) await aoIniciar(); carregar(); };
    iniciar();
    return { carregar, definir(campo, valor) { form.elements[campo].value = valor; carregar(); }, ultimo: () => ultimo };
  }

  let opcoesCache = null;
  async function opcoes() {
    if (!opcoesCache) opcoesCache = await api("/api/opcoes");
    return opcoesCache;
  }

  /* ------------------------------------------------------------- gaveta de detalhe */
  function gaveta(titulo, larga) {
    const fundo = $(".gaveta-fundo"), g = $(".gaveta");
    g.classList.toggle("larga", !!larga);
    $(".gaveta-cab h2", g).textContent = titulo;
    const corpo = $(".gaveta-corpo", g);
    corpo.replaceChildren();
    fundo.classList.add("aberta"); g.classList.add("aberta");
    const fechar = () => { fundo.classList.remove("aberta"); g.classList.remove("aberta"); };
    fundo.onclick = fechar;
    $(".gaveta .fechar").onclick = fechar;
    document.onkeydown = (e) => { if (e.key === "Escape") fechar(); };
    return corpo;
  }
  function campos(cont, pares) {
    const d = document.createElement("div");
    d.className = "campos";
    pares.forEach(([r, v]) => {
      const c = document.createElement("div");
      const s = document.createElement("span"); s.textContent = r;
      const b = document.createElement("strong"); b.textContent = v || "—";
      c.append(s, b); d.appendChild(c);
    });
    cont.appendChild(d);
  }

  /* =============================================================== INÍCIO */
  function alertas(cont, lista) {
    if (!cont) return;
    cont.replaceChildren();
    if (!lista.length) { const ok = document.createElement("div"); ok.className = "alerta ok"; ok.textContent = "✓ Nenhum alerta no momento"; cont.appendChild(ok); return; }
    lista.forEach((a) => {
      const l = document.createElement("a");
      l.className = "alerta " + a.nivel; l.href = a.link;
      const n = document.createElement("strong"); n.textContent = F.inteiro(a.qtd);
      const t = document.createElement("span"); t.textContent = " " + a.texto + (a.valor ? " · " + F.compacto(a.valor, true) : "");
      const s = document.createElement("span"); s.className = "seta"; s.textContent = "›";
      l.append(n, t, s);
      cont.appendChild(l);
    });
  }
  function saldoSemanas(cont, sem) {
    if (!cont) return;
    cont.replaceChildren();
    let acum = 0;
    sem.forEach((s) => {
      acum += s.receber - s.pagar;
      const c = document.createElement("div");
      c.className = "saldo-sem " + (acum < 0 ? "neg" : "pos");
      const r = document.createElement("span"); r.textContent = F.mes(s.rotulo);
      const v = document.createElement("strong"); v.textContent = F.compacto(acum, true);
      c.append(r, v);
      c.title = `Saldo acumulado até ${s.rotulo}: ${F.moeda(acum)}`;
      cont.appendChild(c);
    });
    const t = document.createElement("div"); t.className = "saldo-tit"; t.textContent = "Saldo acumulado (receber − pagar)";
    cont.prepend(t);
  }
  function aging(cont, ag, extra = "") {
    if (!cont) return;
    cont.replaceChildren();
    const cores = ["var(--ok, #2f9e44)", "#f2c94c", "#f2994a", "#e8590c", "var(--critico)"];
    [["R", "A receber"], ["P", "A pagar"]].forEach(([k, nome]) => {
      const fx = ag[k] || [];
      const tot = fx.reduce((a, b) => a + b.valor, 0);
      const bloco = document.createElement("div"); bloco.className = "aging";
      const cab = document.createElement("div"); cab.className = "aging-cab";
      const n = document.createElement("strong"); n.textContent = nome;
      const t = document.createElement("span"); t.textContent = F.moeda(tot);
      cab.append(n, t);
      const barra = document.createElement("div"); barra.className = "aging-barra";
      const leg = document.createElement("div"); leg.className = "aging-leg";
      fx.forEach((f, i) => {
        const link = `/financeiro?tipo=${k}&status=A` + extra;
        if (f.valor > 0) {
          const s = document.createElement("a"); s.href = link;
          s.style.flex = String(f.valor); s.style.background = cores[i];
          s.title = `${f.rotulo}: ${F.moeda(f.valor)} (${f.qtd} títulos)`;
          barra.appendChild(s);
        }
        const li = document.createElement("a"); li.href = link; li.className = "aging-item";
        const b = document.createElement("i"); b.style.background = cores[i];
        const r = document.createElement("span"); r.textContent = f.rotulo;
        const v = document.createElement("strong"); v.textContent = F.compacto(f.valor, true);
        const p = document.createElement("em"); p.textContent = tot ? Math.round((f.valor / tot) * 100) + "%" : "0%";
        li.append(b, r, v, p);
        leg.appendChild(li);
      });
      bloco.append(cab, barra, leg);
      cont.appendChild(bloco);
    });
  }
  const filialURL = (d) => (d.filial !== null && d.filial !== undefined ? `&filial=${d.filial}` : "");
  const mesURL = (d) => (d.periodo ? `&ini=${d.periodo[0]}&fim=${d.periodo[1]}` : "") + filialURL(d);
  /* filial escolhida na Início (lembrada neste navegador; vazio = todas) */
  function filialInicio() {
    try { return localStorage.getItem("filial_inicio") || ""; } catch (e) { return ""; }
  }
  /* período global (seletor no topo): vale para Início, Movimentos e Financeiro */
  const PERIODOS = { mes: "Este mês", mes_passado: "Mês passado", d30: "Últimos 30 dias", d90: "Últimos 90 dias", ano: "Este ano", m12: "Últimos 12 meses" };
  function periodoGlobal() {
    let k = null;
    try { k = localStorage.getItem("periodo"); } catch (e) { /* sem armazenamento */ }
    return PERIODOS[k] ? k : "mes";
  }
  function datasPeriodo(k) {
    const h = new Date(), y = h.getFullYear(), m = h.getMonth();
    const r = {
      mes: [new Date(y, m, 1), new Date(y, m + 1, 0)],
      mes_passado: [new Date(y, m - 1, 1), new Date(y, m, 0)],
      d30: [new Date(y, m, h.getDate() - 29), h],
      d90: [new Date(y, m, h.getDate() - 89), h],
      ano: [new Date(y, 0, 1), new Date(y, 11, 31)],
      m12: [new Date(y, m - 11, 1), new Date(y, m + 1, 0)],
    }[k] || [new Date(y, m, 1), new Date(y, m + 1, 0)];
    return r.map(iso);
  }
  let aoMudarPeriodo = null;
  function seletorPeriodo() {
    const sel = $("#periodo-global");
    if (!sel) return;
    sel.value = periodoGlobal();
    sel.addEventListener("change", () => {
      try { localStorage.setItem("periodo", sel.value); } catch (e) { /* */ }
      if (aoMudarPeriodo) aoMudarPeriodo(datasPeriodo(sel.value));
    });
  }
  function rotuloPeriodo(ini, fim) {
    const a = new Date(ini + "T12:00:00"), z = new Date(fim + "T12:00:00");
    const fimMes = new Date(a.getFullYear(), a.getMonth() + 1, 0).getDate();
    if (a.getDate() === 1 && a.getMonth() === z.getMonth() && a.getFullYear() === z.getFullYear() && z.getDate() === fimMes)
      return a.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
    return `${fmtData(ini)} a ${fmtData(fim)}`;
  }

  async function telaInicio(datas) {
    const raiz = $(".conteudo");
    const [ini, fim] = datas || datasPeriodo(periodoGlobal());
    aoMudarPeriodo = (d) => telaInicio(d);
    const selFil = $("#filial-inicio");
    if (selFil && !selFil.dataset.pronto) {
      selFil.dataset.pronto = "1";
      opcoes().then((o) => { opcoesSelect(selFil, o.filiais || [], "Todas"); selFil.value = filialInicio(); }).catch(() => {});
      selFil.value = filialInicio();
      selFil.addEventListener("change", () => {
        try { localStorage.setItem("filial_inicio", selFil.value); } catch (e) { /* */ }
        telaInicio(datas);
      });
    }
    const fil = filialInicio();
    const q = `ini=${ini}&fim=${fim}` + (fil ? `&filial=${encodeURIComponent(fil)}` : "");
    const sub = $("#mes-atual"); if (sub) sub.textContent = rotuloPeriodo(ini, fim);
    raiz.classList.add("carregando");
    const ehMes = rotuloPeriodo(ini, fim) !== `${fmtData(ini)} a ${fmtData(fim)}`;
    const suf = ehMes ? "(mês)" : "(período)";
    // etapa 1: cards, alertas e atraso | etapa 2: gráficos. As duas vão juntas; cada uma aparece quando chega.
    const resumo = api(`/api/inicio?parte=resumo&${q}`).then((d) => {
      const k = d.kpis;
      const cp = d.comparacao || {}, h = d.historico || { meses: [], qtd: [], valor: [] };
      const pct = (a, b) => (b ? ((a - b) / b) * 100 : null);
      const vtxt = `vs ${cp.rotulo || "período anterior"}`;
      kpis($("#kpis"), [
        { rotulo: `A receber em aberto ${suf}`, valor: F.compacto(k.receber_aberto, true), detalhe: `Vencido: ${F.moeda(k.receber_vencido)}`, classe: "destaque" },
        { rotulo: `A pagar em aberto ${suf}`, valor: F.compacto(k.pagar_aberto, true), detalhe: `Vencido: ${F.moeda(k.pagar_vencido)}` },
        { rotulo: `Movimentos ${suf}`, valor: F.inteiro(k.mov_mes), variacao: pct(k.mov_mes, cp.mov_mes), varTexto: vtxt, spark: h.qtd, sparkRot: h.meses },
        { rotulo: `Valor movimentado ${suf}`, valor: F.compacto(k.mov_mes_valor, true), variacao: pct(k.mov_mes_valor, cp.mov_mes_valor), varTexto: vtxt, spark: h.valor, sparkRot: h.meses },
        { rotulo: "Valor em estoque (hoje)", valor: F.compacto(k.estoque_valor, true), detalhe: "Saldo × custo médio" },
      ]);
      alertas($("#alertas"), d.alertas || []);
      $("#g-aging").classList.remove("g-esqueleto");
      aging($("#g-aging"), d.aging || {}, filialURL(d));
      raiz.classList.remove("carregando");      // cards prontos; os gráficos chegam em seguida
    });
    const graficos = api(`/api/inicio?parte=graficos&${q}`).then((d) => {
      $$(".g-esqueleto", raiz).forEach((x) => { if (x.id !== "g-aging") x.classList.remove("g-esqueleto"); });
      G.desenhar($("#g-movfunc"), () => G.barras($("#g-movfunc"), d.mov_func || [], {
        cor: "var(--serie-3)", larguraRotulo: 220,
        onClick: (x) => { const c = x.rotulo.split(" ")[0]; if (x.rotulo !== "Outros" && !x.rotulo.startsWith("(")) location.href = "/movimentos?vendedor=" + encodeURIComponent(c) + mesURL(d); },
      }));
      const sem = d.semanas || [];
      $("#rot-semanas").textContent = d.por_semana === false ? "mês" : "semana";
      G.desenhar($("#g-pagrec"), () => G.colunas($("#g-pagrec"), [
        { nome: "A receber", pontos: sem.map((s) => ({ rotulo: s.rotulo, valor: s.receber })) },
        { nome: "A pagar", pontos: sem.map((s) => ({ rotulo: s.rotulo, valor: s.pagar })) },
      ], { formato: F.moeda, moeda: true, altura: 230,
           onClick: (p) => { const w = sem.find((x) => x.rotulo === p.rotulo); if (w) location.href = `/financeiro?tipo=T&status=A&base=vencimento&ini=${w.ini}&fim=${w.fim}` + filialURL(d); } }));
      saldoSemanas($("#saldo-semanas"), sem);
      const modo = $("#modo-movtipo");
      const desenharTipo = () => {
        const cat = modo.value === "cat";
        $("#rot-movtipo").textContent = cat ? "categoria" : "tipo";
        G.desenhar($("#g-movtipo"), () => G.barras($("#g-movtipo"), cat ? d.mov_cat : d.mov_tipo, {
          larguraRotulo: cat ? 230 : 190,
          onClick: (x) => {
            if (x.rotulo === "Outros") return;
            const cod = x.rotulo.split(" ")[0];
            location.href = "/movimentos?" + (cat ? "prefixo=" + encodeURIComponent(cod + ".") : "tipos=" + encodeURIComponent(cod)) + mesURL(d);
          },
        }));
      };
      modo.onchange = () => { try { localStorage.setItem("inicio_movtipo", modo.value); } catch (e) { /* */ } desenharTipo(); };
      try { const v = localStorage.getItem("inicio_movtipo"); if (v) modo.value = v; } catch (e) { /* */ }
      desenharTipo();
    });
    try {
      await Promise.all([resumo, graficos]);
    } catch (e) {
      aviso(raiz, e.message);
    } finally {
      raiz.classList.remove("carregando");
    }
  }

  /* =============================================================== MOVIMENTOS */
  async function telaMovimentos() {
    const form = $("#filtros");
    const tabela = new Tabela($("#tabela"), {
      ocultar: ["IDMOV", "CODCFO"],
      onClick: (r, cols) => abrirMovimento(r[cols.indexOf("IDMOV")]),
    });
    const pg = paginaDados({
      form,
      url: () => "/api/movimentos",
      aoIniciar: async () => {
        const o = await opcoes();
        opcoesSelect(form.elements.tipos, o.tipos, "Todos os tipos");
        opcoesSelect(form.elements.vendedor, o.vendedores, "Todos");
        opcoesSelect(form.elements.filial, o.filiais, "Todas");
        multiEscolha(form.elements.ccusto, o.ccustos || [], "Todos", () => pg.carregar(), "centros selecionados");
        multiEscolha(form.elements.depto, o.departamentos || [], "Todos", () => pg.carregar(), "departamentos selecionados");
        preencherFiltros(form, new URLSearchParams(location.search));
      },
      render(d) {
        const k = d.kpis;
        if (!form.elements.ini.value) form.elements.ini.value = d.periodo[0];
        if (!form.elements.fim.value) form.elements.fim.value = d.periodo[1];
        kpis($("#kpis"), [
          { rotulo: "Movimentos", valor: F.inteiro(k.qtd), detalhe: `${fmtData(d.periodo[0])} a ${fmtData(d.periodo[1])}` },
          { rotulo: "Valor líquido", valor: F.compacto(k.valor, true), detalhe: F.moeda(k.valor) },
          { rotulo: "Valor bruto", valor: F.compacto(k.bruto, true), detalhe: F.moeda(k.bruto) },
          { rotulo: "Clientes distintos", valor: F.inteiro(k.clientes) },
        ]);
        const porMes = $("#metrica-mes").value === "qtd" ? d.qtd_mes : d.por_mes;
        const moeda = $("#metrica-mes").value !== "qtd";
        G.desenhar($("#g-mes"), () => G.colunas($("#g-mes"), [{ nome: moeda ? "Valor" : "Quantidade", pontos: porMes }],
          { formato: moeda ? F.moeda : F.inteiro, moeda }));
        const cat = $("#modo-tipo").value === "cat";
        $("#rot-tipo").textContent = cat ? "categoria" : "tipo";
        G.desenhar($("#g-tipo"), () => G.barras($("#g-tipo"), cat ? d.por_categoria : d.por_tipo, {
          onClick: (x) => {
            if (x.rotulo === "Outros") return;
            if (cat) pg.definir("prefixo", x.rotulo.split(" ")[0] + ".");
            else pg.definir("tipos", x.rotulo.split(" ")[0]);
          },
        }));
        G.desenhar($("#g-cli"), () => G.barras($("#g-cli"), d.top_clientes, { formato: F.moeda, compacto: true, moeda: true, cor: "var(--serie-3)",
          onClick: (x) => x.rotulo !== "Outros" && pg.definir("cliente", x.rotulo) }));
        G.desenhar($("#g-vend"), () => G.barras($("#g-vend"), d.top_vendedores, { formato: F.moeda, compacto: true, moeda: true, cor: "var(--serie-7)" }));
        tabela.definir(d.tabela, d.truncado);
      },
    });
    $("#metrica-mes").addEventListener("change", pg.carregar);
    try { const v = localStorage.getItem("mov_modo_tipo"); if (v) $("#modo-tipo").value = v; } catch (e) { /* */ }
    $("#modo-tipo").addEventListener("change", () => {
      try { localStorage.setItem("mov_modo_tipo", $("#modo-tipo").value); } catch (e) { /* */ }
      if (pg.ultimo()) pg.carregar();
    });
    $("#limpar").addEventListener("click", () => {
      form.reset();
      Array.from(form.elements.tipos.options).forEach((o) => (o.selected = false));
      ["ccusto", "depto"].forEach((n) => { form.elements[n].value = ""; if (form.elements[n]._sincronizar) form.elements[n]._sincronizar(); });
      pg.carregar();
    });
  }

  /* ficha do cliente/fornecedor: cadastro + abas Financeiro e Movimentos */
  async function abrirFicha(cod, abaInicial) {
    const corpo = gaveta("Carregando…", true);
    let d;
    try { d = await api("/api/cadastro/" + encodeURIComponent(cod)); }
    catch (e) { aviso(corpo, e.message); return; }
    const c = d.cadastro.colunas, r = d.cadastro.linhas[0];
    const v = (n) => r[c.indexOf(n)];
    $(".gaveta-cab h2").textContent = `${cod} - ${v("NOME") || ""}`;
    campos(corpo, [
      ["Nome fantasia", v("FANTASIA")], ["CPF/CNPJ", v("CPF_CNPJ")], ["Tipo", v("TIPO")],
      ["Cidade/UF", [v("CIDADE"), v("UF")].filter(Boolean).join(" / ")], ["Telefone", v("TELEFONE")], ["E-mail", v("EMAIL")],
    ]);
    if (!d.abas.length) { aviso(corpo, "Você não tem acesso ao Financeiro nem aos Movimentos.", "atencao"); return; }
    const abas = el("div", "abas"); abas.style.marginTop = "14px";
    const area = el("div"); area.style.marginTop = "12px";
    corpo.append(abas, area);
    const nomes = { financeiro: "Financeiro", movimentos: "Movimentos" };
    async function mostrar(aba) {
      $$("button", abas).forEach((b) => b.classList.toggle("ativa", b.dataset.aba === aba));
      area.replaceChildren(el("p", "nota", "Carregando…"));
      try {
        const x = await api(`/api/cadastro/${encodeURIComponent(cod)}?aba=${aba}`);
        area.replaceChildren();
        const k = x.kpis, kc = el("div", "kpis"); kc.style.marginBottom = "12px"; area.appendChild(kc);
        if (aba === "financeiro") {
          kpis(kc, [
            { rotulo: "A receber em aberto", valor: F.moeda(k.receber_aberto), detalhe: k.receber_vencido ? `vencido ${F.moeda(k.receber_vencido)}` : "nada vencido", classe: k.receber_vencido ? "critico" : "" },
            { rotulo: "A pagar em aberto", valor: F.moeda(k.pagar_aberto), detalhe: k.pagar_vencido ? `vencido ${F.moeda(k.pagar_vencido)}` : "nada vencido", classe: k.pagar_vencido ? "critico" : "" },
            { rotulo: "Já recebido", valor: F.moeda(k.recebido) },
            { rotulo: "Já pago", valor: F.moeda(k.pago) },
          ]);
        } else {
          kpis(kc, [
            { rotulo: "Movimentos", valor: F.inteiro(k.qtd), detalhe: k.cancelados ? `+ ${k.cancelados} cancelado(s)` : "" },
            { rotulo: "Valor total", valor: F.moeda(k.valor), detalhe: "sem cancelados" },
            { rotulo: "Primeiro", valor: k.primeiro ? fmtData(k.primeiro) : "—" },
            { rotulo: "Último", valor: k.ultimo ? fmtData(k.ultimo) : "—" },
          ]);
        }
        const botoes = [["Excel", "xlsx"], ["PDF", "pdf"]].map(([rot, fmt]) => {
          const b = el("button", "btn pequeno", rot);
          b.onclick = () => baixar(`/api/cadastro/${encodeURIComponent(cod)}?aba=${aba}&formato=${fmt}`).catch((e) => aviso(corpo, e.message));
          return b;
        });
        const t = el("div"); area.appendChild(t);
        new Tabela(t, {
          botoes, ocultar: ["IDMOV", "CODCFO", "CLIENTE"],
          onClick: aba === "movimentos" ? (row, cols) => abrirMovimento(row[cols.indexOf("IDMOV")], () => abrirFicha(cod, "movimentos")) : null,
        }).definir(x.tabela, x.truncado);
        if (!x.tabela.linhas.length) area.appendChild(el("p", "nota", aba === "financeiro" ? "Nenhum lançamento para este cadastro." : "Nenhum movimento para este cadastro."));
      } catch (e) { area.replaceChildren(); aviso(area, e.message); }
    }
    d.abas.forEach((a) => {
      const b = el("button", "", nomes[a]); b.dataset.aba = a;
      b.onclick = () => mostrar(a);
      abas.appendChild(b);
    });
    mostrar(d.abas.includes(abaInicial) ? abaInicial : d.abas[0]);
  }

  async function abrirMovimento(idmov, voltar, rotuloVoltar) {
    const corpo = gaveta("Carregando…", !!voltar);
    if (voltar) {
      const vb = el("button", "btn pequeno", rotuloVoltar || "‹ Voltar para a ficha"); vb.style.marginBottom = "12px";
      vb.onclick = voltar; corpo.appendChild(vb);
    }
    try {
      const d = await api("/api/movimentos/" + idmov);
      if (!d.cabecalho.linhas.length) { $(".gaveta-cab h2").textContent = "Documento"; aviso(corpo, "Documento não encontrado ou não liberado para você."); return; }
      const c = d.cabecalho.colunas, r = d.cabecalho.linhas[0] || [];
      const v = (n) => r[c.indexOf(n)];
      $(".gaveta-cab h2").textContent = `DOCUMENTO ${v("DOCUMENTO") || ""}`;
      campos(corpo, [
        ["Tipo", `${v("CODTMV") || ""} ${v("TIPO") || ""}`], ["Emissão", fmtData(v("EMISSAO"))], ["Status", v("STATUS")],
        ["Cliente", `${v("CODCFO") || ""} ${v("CLIENTE") || ""}`], ["Vendedor", v("VENDEDOR")], ["Valor", F.moeda(v("VALOR"))],
        ["Centro de custo", v("CENTRO_CUSTO")], ["Departamento", v("DEPARTAMENTO")],
      ]);
      const t = document.createElement("div");
      corpo.appendChild(t);
      new Tabela(t, { porPagina: 500, ocultar: ["CODPRD_INT"] }).definir(d.itens, false);
      const b = document.createElement("button");
      b.className = "btn"; b.textContent = "PDF deste documento";
      b.onclick = () => baixar(`/api/relatorio/documentos?ini=1900-01-01&fim=2999-12-31&cancelados=1&cliente=${encodeURIComponent(v("CODCFO") || "")}&tipos=${encodeURIComponent(v("CODTMV") || "")}&doc=${idmov}&formato=pdf`).catch((e) => aviso(corpo, e.message));
      if (document.body.dataset.modulos.includes("relatorios")) corpo.appendChild(b);
    } catch (e) {
      aviso(corpo, e.message);
    }
  }

  /* =============================================================== FROTAS */
  const ROT_FROTA = { CODMAQUINA: "Máquina", DESCRICAO: "Descrição", ABASTECIMENTOS: "Abastec.", LITROS: "Litros",
    VALOR_COMBUSTIVEL: "Combustível (R$)", PRECO_LITRO: "R$ / litro", MANUTENCOES: "Manutenções", VALOR_MANUTENCAO: "Manutenção (R$)",
    VALOR_TOTAL: "Total (R$)", KM_INICIAL: "KM inicial", KM_FINAL: "KM final", KM_RODADO: "KM rodado", KM_POR_LITRO: "KM / litro",
    ULTIMO: "Último lançamento", KM: "KM", ITENS: "Itens", FORNECEDOR: "Fornecedor" };
  async function telaFrotas() {
    const form = $("#filtros");
    const podeDoc = document.body.dataset.modulos.split(",").includes("movimentos");
    const tabMaq = new Tabela($("#tabela-maq"), { rotulos: ROT_FROTA, onClick: (r, cols) => abrirMaquinaFrota(r[cols.indexOf("CODMAQUINA")]) });
    const tabLanc = new Tabela($("#tabela-lanc"), { rotulos: ROT_FROTA, ocultar: ["IDMOV"],
      onClick: podeDoc ? (r, cols) => abrirMovimento(r[cols.indexOf("IDMOV")]) : null });
    let listas = false;
    const periodo = () => { const q = new URLSearchParams(); ["ini", "fim", "filial"].forEach((k) => { if (form.elements[k].value) q.set(k, form.elements[k].value); }); return q; };

    async function abrirMaquinaFrota(codigo) {
      const q = periodo();
      q.set("codigo", codigo);
      const corpo = gaveta("Carregando…", true);
      try {
        const d = await api("/api/frotas/maquina?" + q);
        const m = d.maquina, r = d.resumo;
        $(".gaveta-cab h2").textContent = `${m.placa || m.codigo} · ${m.nome || ""}`;
        campos(corpo, [
          ["Período", `${fmtData(d.periodo[0])} a ${fmtData(d.periodo[1])}`], ["Grupo", m.grupo], ["Marca", m.marca], ["Ano / modelo", [m.ano, m.modelo].filter(Boolean).join(" / ")],
          ["Abastecimentos", F.inteiro(r.abastecimentos)], ["Litros", F.numero(r.litros)], ["Combustível", F.moeda(r.combustivel)],
          ["Manutenções", F.inteiro(r.manutencoes)], ["Manutenção", F.moeda(r.manutencao)], ["Total", F.moeda(r.total)],
        ]);
        const t = el("div");
        corpo.appendChild(t);
        const bx = (fmt) => { const b = el("button", "btn pequeno", fmt === "xlsx" ? "Excel" : "PDF");
          b.onclick = () => { const z = new URLSearchParams(q); z.set("formato", fmt); baixar("/api/frotas/maquina?" + z).catch((e) => aviso(corpo, e.message)); };
          return b; };
        new Tabela(t, { rotulos: ROT_FROTA, ocultar: ["IDMOV"], botoes: [bx("xlsx"), bx("pdf")],
          onClick: podeDoc ? (row, cols) => abrirMovimento(row[cols.indexOf("IDMOV")], () => abrirMaquinaFrota(codigo), "‹ Voltar para a máquina") : null,
          celula: (c, v, td) => { if (c === "TIPO") { td.appendChild(el("span", "tag " + (v === "Manutenção" ? "atencao" : "entrada"), v)); return true; } return false; },
        }).definir(d.tabela, d.truncado);
      } catch (e) { aviso(corpo, e.message); }
    }

    const pg = paginaDados({
      form,
      url: () => "/api/frotas",
      aoIniciar: async () => {
        const o = await opcoes();
        opcoesSelect(form.elements.filial, o.filiais, "Todas");
        preencherFiltros(form, new URLSearchParams(location.search));
      },
      render(d) {
        if (!listas) {
          listas = true;
          opcoesSelect(form.elements.maquina, d.maquinas, "Todas as máquinas");
          opcoesSelect(form.elements.grupo, d.grupos, "Todos");
          preencherFiltros(form, new URLSearchParams(location.search));
        }
        if (!form.elements.ini.value) form.elements.ini.value = d.periodo[0];
        if (!form.elements.fim.value) form.elements.fim.value = d.periodo[1];
        const k = d.kpis;
        kpis($("#kpis"), [
          { rotulo: "Gasto total", valor: F.compacto(k.total, true), detalhe: F.moeda(k.total), classe: "destaque" },
          { rotulo: "Combustível", valor: F.compacto(k.combustivel, true), detalhe: `${F.inteiro(k.abastecimentos)} abastecimentos · ${F.numero(k.litros)} L` },
          { rotulo: "Preço médio do litro", valor: k.preco_litro ? F.moeda(k.preco_litro) : "—", detalhe: "combustível, sem ARLA" },
          { rotulo: "Manutenção", valor: F.compacto(k.manutencao, true), detalhe: `${F.inteiro(k.manutencoes)} lançamentos` },
        ]);
        G.desenhar($("#g-mes"), () => G.colunas($("#g-mes"), d.por_mes, { formato: F.moeda, moeda: true }));
        G.desenhar($("#g-prod"), () => G.barras($("#g-prod"), d.por_produto, { formato: F.moeda, compacto: true, moeda: true, cor: "var(--serie-4)", larguraRotulo: 120 }));
        G.desenhar($("#g-top"), () => G.barras($("#g-top"), d.top_maquinas, { formato: F.moeda, compacto: true, moeda: true, cor: "var(--serie-3)", larguraRotulo: 260,
          onClick: (x) => abrirMaquinaFrota(x.codigo) }));
        tabMaq.definir(d.tabela, false);
        tabLanc.definir(d.lancamentos, d.truncado);
      },
    });
    $$("#abas-frota button").forEach((b) => b.addEventListener("click", () => {
      $$("#abas-frota button").forEach((x) => x.classList.toggle("ativa", x === b));
      $("#sec-maquinas").hidden = b.dataset.aba !== "maquinas";
      $("#sec-lancamentos").hidden = b.dataset.aba !== "lancamentos";
    }));
    $$("[data-exp-lanc]").forEach((b) => b.addEventListener("click", async () => {
      const p = lerFiltros(form);
      p.set("ver", "lancamentos"); p.set("formato", b.dataset.expLanc);
      b.disabled = true;
      try { await baixar("/api/frotas?" + p); } catch (e) { aviso($(".conteudo"), e.message); } finally { b.disabled = false; }
    }));
    $("#limpar").addEventListener("click", () => { form.reset(); pg.carregar(); });
  }

  /* =============================================================== MOVIMENTAÇÕES */
  const ROT_MOV = { SALDO: "Saldo atual", ENTRADAS: "Qtd. entradas", SAIDAS: "Qtd. saídas", MOVIMENTOS: "Lançamentos",
    ULTIMO: "Último movimento", QTD_TOTAL: "Quantidade", ENTRADA: "Entrada", SAIDA: "Saída", MOVIMENTO: "Movimento" };
  const NOTA_MOV = {
    estoque: "Movimentos que dão entrada ou saída no saldo físico do produto (conforme o tipo de movimento no Puma). Cancelados não entram.",
    sem: "Movimentos que não alteram o saldo físico: pedidos, solicitações, orçamentos, empenhos, notas de serviço etc. Cancelados não entram.",
  };
  async function telaMovimentacoes() {
    const form = $("#filtros");
    const abas = $$("#abas-mov button");
    const podeDoc = document.body.dataset.modulos.split(",").includes("movimentos");
    let tabela = null;
    const novaTabela = () => {
      tabela = new Tabela($("#tabela"), {
        ocultar: ["CODPRD_INT"], rotulos: ROT_MOV,
        onClick: (r, cols) => abrirProdutoMov(r[cols.indexOf("CODPRD_INT")]),
        botoes: [],
      });
    };
    function marcarAba() {
      const aba = form.elements.aba.value === "sem" ? "sem" : "estoque";
      abas.forEach((b) => { b.classList.toggle("ativa", b.dataset.aba === aba); b.setAttribute("aria-selected", b.dataset.aba === aba); });
      $("#nota-aba").textContent = NOTA_MOV[aba];
    }
    // parâmetros que valem para a janela do produto (período, filial e aba)
    const paramsProduto = () => {
      const p = lerFiltros(form);
      const q = new URLSearchParams();
      ["aba", "ini", "fim", "filial"].forEach((k) => { if (p.get(k)) q.set(k, p.get(k)); });
      return q;
    };

    async function abrirProdutoMov(codprd) {
      const q = paramsProduto();
      q.set("codprd", codprd);
      const corpo = gaveta("Carregando…", true);
      try {
        const d = await api("/api/movimentacoes/produto?" + q);
        const p = d.produto, r = d.resumo;
        $(".gaveta-cab h2").textContent = `${p.fabricante || p.codprd} · ${p.nome}`;
        const per = q.get("ini") || q.get("fim") ? `${q.get("ini") ? fmtData(q.get("ini")) : "início"} a ${q.get("fim") ? fmtData(q.get("fim")) : "hoje"}` : "todo o histórico";
        if (d.aba === "estoque") {
          campos(corpo, [
            ["Período", per], ["Unidade", p.und],
            [q.get("ini") ? "Saldo antes do período" : "Saldo inicial", F.numero(r.saldo_anterior)], ["Entradas", F.numero(r.entradas)],
            ["Saídas", F.numero(r.saidas)], ["Saldo no fim do período", F.numero(r.saldo_final)],
          ]);
        } else {
          campos(corpo, [["Período", per], ["Unidade", p.und], ["Lançamentos", F.inteiro(r.lancamentos)],
            ["Quantidade", F.numero(r.qtd)], ["Valor", F.moeda(r.valor)], ["Saldo atual do estoque", F.numero(r.saldo_atual)]]);
        }
        const nota = el("p", "nota", (d.aba === "estoque" ? "Movimentos que mexem no estoque" : "Movimentos que não mexem no estoque") +
          " · mais recentes primeiro" + (podeDoc ? " · clique em um documento para ver os itens" : ""));
        corpo.appendChild(nota);
        const t = el("div");
        corpo.appendChild(t);
        const bx = (fmt) => { const b = el("button", "btn pequeno", fmt === "xlsx" ? "Excel" : "PDF");
          b.onclick = () => { const z = new URLSearchParams(q); z.set("formato", fmt); baixar("/api/movimentacoes/produto?" + z).catch((e) => aviso(corpo, e.message)); };
          return b; };
        new Tabela(t, {
          porPagina: 100, ocultar: ["IDMOV"], rotulos: Object.assign({}, ROT_MOV, { SALDO: "Saldo após" }), botoes: [bx("xlsx"), bx("pdf")],
          onClick: podeDoc ? (row, cols) => abrirMovimento(row[cols.indexOf("IDMOV")], () => abrirProdutoMov(codprd), "‹ Voltar para o produto") : null,
          celula: (c, v, td) => {
            if (c === "MOVIMENTO") { const s = el("span", "tag " + (v === "Entrada" ? "entrada" : "critico"), v); td.appendChild(s); return true; }
            if ((c === "ENTRADA" || c === "SAIDA") && !v) { td.className = "num"; td.textContent = ""; return true; }
            return false;
          },
        }).definir(d.tabela, d.truncado);
        if (!d.tabela.linhas.length) corpo.insertBefore(el("p", "nota", "Nenhum movimento deste produto com os filtros escolhidos."), t);
      } catch (e) {
        aviso(corpo, e.message);
      }
    }

    novaTabela();
    const pg = paginaDados({
      form,
      url: () => "/api/movimentacoes",
      aoIniciar: async () => {
        const o = await opcoes();
        opcoesSelect(form.elements.grupo, o.grupos, "Todos os grupos");
        opcoesSelect(form.elements.filial, o.filiais, "Todas");
        preencherFiltros(form, new URLSearchParams(location.search));
        marcarAba();
      },
      render(d) {
        const k = d.kpis;
        const lista = [
          { rotulo: "Produtos listados", valor: F.inteiro(k.produtos) },
          { rotulo: "Com movimento", valor: F.inteiro(k.com_mov), classe: "destaque" },
        ];
        if (d.aba === "estoque") {
          lista.push({ rotulo: "Lançamentos de entrada", valor: F.inteiro(k.entradas) }, { rotulo: "Lançamentos de saída", valor: F.inteiro(k.saidas) });
        } else {
          lista.push({ rotulo: "Lançamentos", valor: F.inteiro(k.lancamentos) }, { rotulo: "Valor dos itens", valor: F.compacto(k.valor, true), detalhe: F.moeda(k.valor) });
        }
        kpis($("#kpis"), lista);
        tabela.definir(d.tabela, d.truncado);
      },
    });
    abas.forEach((b) => b.addEventListener("click", () => {
      if (form.elements.aba.value === b.dataset.aba) return;
      form.elements.aba.value = b.dataset.aba;
      marcarAba();
      novaTabela();                     // colunas diferentes em cada aba
      pg.carregar();
    }));
    $("#limpar").addEventListener("click", () => { const aba = form.elements.aba.value; form.reset(); form.elements.aba.value = aba; pg.carregar(); });
  }

  /* =============================================================== ESTOQUE */
  async function telaEstoque() {
    const form = $("#filtros");
    const tabela = new Tabela($("#tabela"));
    let topProdutos = [];
    let ultimo = null;
    // cada gráfico pode mostrar o valor (saldo × custo médio) ou a quantidade (soma dos saldos)
    const modos = { local: "valor", grupo: "valor", top: "valor" };
    try { Object.assign(modos, JSON.parse(localStorage.getItem("estoque_modos") || "{}")); } catch (e) { /* */ }
    const opc = (modo, extra) => Object.assign(modo === "qtd" ? { formato: F.numero } : { formato: F.moeda, compacto: true, moeda: true }, extra);
    function desenharGraficos() {
      const d = ultimo;
      if (!d) return;
      $$("[data-alterna]").forEach((g) => {
        const m = modos[g.dataset.alterna];
        $$("button", g).forEach((b) => { b.classList.toggle("ativo", b.dataset.modo === m); b.setAttribute("aria-pressed", b.dataset.modo === m); });
        const tit = g.closest(".cartao").querySelector(".tit-modo");
        if (tit) tit.textContent = m === "qtd" ? tit.dataset.q : tit.dataset.v;
      });
      G.desenhar($("#g-local"), () => G.barras($("#g-local"), modos.local === "qtd" ? d.por_local_qtd : d.por_local, opc(modos.local, {
        onClick: (x) => x.rotulo !== "Outros" && pg.definir("local", x.rotulo.split(" ")[0]) })));
      G.desenhar($("#g-grupo"), () => G.barras($("#g-grupo"), modos.grupo === "qtd" ? d.por_grupo_qtd : d.por_grupo, opc(modos.grupo, { cor: "var(--serie-3)" })));
      const top = modos.top === "qtd" ? d.top_produtos_qtd : d.top_produtos;
      G.desenhar($("#g-top"), () => G.barras($("#g-top"), top, opc(modos.top, { cor: "var(--serie-2)", larguraRotulo: 260 })));
      topProdutos = top || [];
    }
    $$("[data-alterna]").forEach((g) => g.addEventListener("click", (e) => {
      e.stopPropagation();                      // não abre a janela do quadro "Produtos de maior valor"
      const b = e.target.closest("button[data-modo]");
      if (!b) return;
      modos[g.dataset.alterna] = b.dataset.modo;
      try { localStorage.setItem("estoque_modos", JSON.stringify(modos)); } catch (er) { /* */ }
      desenharGraficos();
    }));
    $$("[data-alterna]").forEach((g) => g.addEventListener("keydown", (e) => e.stopPropagation()));
    const cartaoTop = $("#cartao-top");
    if (cartaoTop) {
      const abrirTop = () => janelaTop(topProdutos);
      cartaoTop.addEventListener("click", abrirTop);
      cartaoTop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrirTop(); } });
    }
    const pg = paginaDados({
      form,
      url: () => "/api/estoque",
      aoIniciar: async () => {
        const o = await opcoes();
        opcoesSelect(form.elements.local, o.locais, "Todos os locais");
        opcoesSelect(form.elements.grupo, o.grupos, "Todos os grupos");
        opcoesSelect(form.elements.filial, o.filiais, "Todas");
        preencherFiltros(form, new URLSearchParams(location.search));
      },
      render(d) {
        const k = d.kpis;
        kpis($("#kpis"), [
          { rotulo: "Valor em estoque", valor: F.compacto(k.valor, true), detalhe: F.moeda(k.valor), classe: "destaque" },
          { rotulo: "Produtos com saldo", valor: F.inteiro(k.itens) },
          { rotulo: "Saldos negativos", valor: F.inteiro(k.negativos), classe: k.negativos ? "critico" : "" , detalhe: "produto × local" },
          { rotulo: "Com saldo e sem custo", valor: F.inteiro(k.sem_custo), detalhe: "não entram no valor" },
        ]);
        ultimo = d;
        desenharGraficos();
        tabela.definir(d.tabela, d.truncado);
      },
    });
    $("#limpar").addEventListener("click", () => { form.reset(); pg.carregar(); });
  }

  /* produtos de maior valor: janela com quantidade e preço de venda de cada um */
  function janelaTop(lista) {
    if (!lista || !lista.length) return;
    const fundo = el("div", "modal-fundo");
    const modal = el("div", "modal");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-label", "Produtos de maior valor em estoque");
    const cab = el("div", "modal-cab");
    cab.appendChild(el("h2", "", "Produtos de maior valor em estoque"));
    const fechar = el("button", "btn pequeno", "Fechar ✕");
    cab.appendChild(fechar);
    const corpo = el("div", "modal-corpo");
    const tb = el("table", "dados");
    const cols = [["Código", ""], ["Produto", ""], ["Und", ""], ["Quantidade", "num"], ["Preço de venda", "num"],
      ["Total a preço de venda", "num"], ["Valor em estoque (custo)", "num"]];
    const thead = el("thead"), trh = el("tr");
    cols.forEach(([c, cl]) => trh.appendChild(el("th", cl, c)));
    thead.appendChild(trh);
    const tbody = el("tbody");
    let somaVenda = 0, somaCusto = 0;
    lista.forEach((p) => {
      const tr = el("tr");
      const totVenda = (p.preco || 0) * (p.qtd || 0);
      somaVenda += totVenda; somaCusto += p.valor_estoque ?? p.valor ?? 0;
      [[p.codigo, ""], [p.produto, ""], [p.und, ""], [F.numero(p.qtd), "num"], [p.preco ? F.moeda(p.preco) : "-", "num"],
        [p.preco ? F.moeda(totVenda) : "-", "num"], [F.moeda(p.valor_estoque ?? p.valor), "num"]].forEach(([v, cl]) => tr.appendChild(el("td", cl, v)));
      tr.children[1].title = p.produto;
      tbody.appendChild(tr);
    });
    const tfoot = el("tfoot"), trf = el("tr");
    ["Total", "", "", "", "", F.moeda(somaVenda), F.moeda(somaCusto)].forEach((v, i) => trf.appendChild(el("td", i >= 3 ? "num" : "", v)));
    tfoot.appendChild(trf);
    tb.append(thead, tbody, tfoot);
    const w = el("div", "tabela-wrap");
    w.appendChild(tb);
    corpo.append(w, el("p", "nota", "Quantidade somada de todos os locais filtrados. Preço de venda do cadastro do produto."));
    modal.append(cab, corpo);
    fundo.appendChild(modal);
    document.body.appendChild(fundo);
    const sair = () => { fundo.remove(); document.removeEventListener("keydown", esc, true); };
    const esc = (e) => { if (e.key === "Escape") { e.stopPropagation(); sair(); } };
    fechar.onclick = sair;
    fundo.addEventListener("click", (e) => { if (e.target === fundo) sair(); });
    document.addEventListener("keydown", esc, true);
    fechar.focus();
  }

  /* =============================================================== FINANCEIRO */
  async function telaFinanceiro() {
    const form = $("#filtros");
    const tabela = new Tabela($("#tabela"), {
      ocultar: ["IDLAN"],
      celula: (c, v, td) => {
        if (c === "DIAS_ATRASO") {
          td.className = "num";
          if (v > 0) { const s = document.createElement("span"); s.className = "tag " + (v > 30 ? "critico" : "atencao"); s.textContent = v + " dias"; td.appendChild(s); }
          return true;
        }
        return false;
      },
    });
    const pg = paginaDados({
      form,
      url: () => "/api/financeiro",
      aoIniciar: async () => {
        try {
          const o = await opcoes();
          multiEscolha(form.elements.tipodoc, o.tipos_doc || [], "Todos os tipos", () => pg.carregar());
          multiEscolha(form.elements.ccusto, o.ccustos || [], "Todos", () => pg.carregar(), "centros selecionados");
          multiEscolha(form.elements.depto, o.departamentos || [], "Todos", () => pg.carregar(), "departamentos selecionados");
          opcoesSelect(form.elements.filial, o.filiais, "Todas");
          preencherFiltros(form, new URLSearchParams(location.search));
        } catch (e) { /* sem a lista de tipos: o filtro fica vazio */ }
      },
      render(d) {
        const k = d.kpis;
        const tipo = form.elements.tipo.value;
        if (!form.elements.ini.value) form.elements.ini.value = d.periodo[0];
        if (!form.elements.fim.value) form.elements.fim.value = d.periodo[1];
        kpis($("#kpis"), [
          { rotulo: tipo === "P" ? "A pagar em aberto" : tipo === "R" ? "A receber em aberto" : "Em aberto", valor: F.compacto(k.aberto, true), detalhe: F.moeda(k.aberto), classe: "destaque" },
          { rotulo: "Vencido", valor: F.compacto(k.vencido, true), detalhe: F.moeda(k.vencido), classe: k.vencido ? "critico" : "" },
          { rotulo: "Vence em 30 dias", valor: F.compacto(k.a_vencer_30, true), detalhe: F.moeda(k.a_vencer_30) },
          { rotulo: "Títulos no filtro", valor: F.inteiro(k.qtd), detalhe: `Total ${F.moeda(k.total)}` },
        ]);
        G.desenhar($("#g-mes"), () => G.colunas($("#g-mes"), d.por_mes, { formato: F.moeda, moeda: true, corInicial: tipo === "P" ? 1 : 0 }));
        G.desenhar($("#g-aging"), () => G.barras($("#g-aging"), d.aging.map((a, i) => ({ ...a, cor: i === 0 ? "var(--serie-1)" : i < 3 ? "var(--serie-4)" : "var(--serie-8)" })),
          { formato: F.moeda, compacto: true, moeda: true, larguraRotulo: 110 }));
        G.desenhar($("#g-nomes"), () => G.barras($("#g-nomes"), d.top_nomes, { formato: F.moeda, compacto: true, moeda: true, cor: "var(--serie-3)",
          onClick: (x) => x.rotulo !== "Outros" && pg.definir("cliente", x.rotulo) }));
        tabela.definir(d.tabela, d.truncado);
      },
    });
    $("#limpar").addEventListener("click", () => {
      form.reset();
      ["tipodoc", "ccusto", "depto"].forEach((n) => { form.elements[n].value = ""; if (form.elements[n]._sincronizar) form.elements[n]._sincronizar(); });
      pg.carregar();
    });
  }

  /* =============================================================== CADASTROS */
  async function telaCadastros() {
    const abas = $$(".abas button");
    const secoes = { clientes: $("#sec-clientes"), produtos: $("#sec-produtos"), maquinas: $("#sec-maquinas") };
    const ativa = new URLSearchParams(location.search).get("aba") || "clientes";
    const iniciadas = {};
    function mostrar(nome) {
      abas.forEach((b) => b.classList.toggle("ativa", b.dataset.aba === nome));
      Object.entries(secoes).forEach(([n, s]) => (s.hidden = n !== nome));
      if (!iniciadas[nome]) { iniciadas[nome] = true; ({ clientes: iniciarClientes, produtos: iniciarProdutos, maquinas: iniciarMaquinas }[nome] || iniciarClientes)(); }
    }
    abas.forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.aba)));
    mostrar(ativa);

    function iniciarClientes() {
      const form = $("#filtros-cli");
      const tabela = new Tabela($("#tabela-cli"), { onClick: (r, cols) => abrirFicha(r[cols.indexOf("CODIGO")]) });
      const pg = paginaDados({
        form,
        url: () => "/api/clientes",
        render(d) {
          const k = d.kpis;
          kpis($("#kpis-cli"), [
            { rotulo: "Cadastros", valor: F.inteiro(k.qtd) },
            { rotulo: "Ativos", valor: F.inteiro(k.ativos) },
            { rotulo: "Sem UF", valor: F.inteiro(k.sem_uf), classe: k.sem_uf ? "critico" : "" },
            { rotulo: "E-mail vazio ou genérico", valor: F.inteiro(k.email_generico), detalhe: "ex.: NAOTEM@NAOTEM.COM" },
          ]);
          G.desenhar($("#g-cidade"), () => G.barras($("#g-cidade"), d.por_cidade));
          G.desenhar($("#g-pessoa"), () => G.rosca($("#g-pessoa"), d.por_pessoa, { rotuloTotal: "cadastros" }));
          tabela.definir(d.tabela, d.truncado);
        },
      });
      $("#limpar-cli").addEventListener("click", () => { form.reset(); pg.carregar(); });
    }
    function iniciarMaquinas() {
      const form = $("#filtros-maq");
      const ROT = { DESCRICAO: "Descrição", NUMMOTOR: "Nº motor", NUMSERIE: "Nº série", KM: "KM / horímetro", TIPOCONTROLE: "Tipo controle",
        TIPOVERIFICACAO: "Tipo verificação", OBSERVACAO: "Observação", SITUACAO: "Situação", CODIGO: "Código" };
      const ficha = (r, cols) => {
        const v = (n) => r[cols.indexOf(n)];
        const corpo = gaveta(`${v("CODIGO")} · ${v("DESCRICAO") || ""}`);
        campos(corpo, cols.filter((c) => c !== "OBSERVACAO").map((c) => [ROT[c] || rotuloCol(c), c === "KM" ? F.numero(v(c)) : (v(c) ?? "")]));
        const h = el("h3", "", "Observação"); h.style.cssText = "font-size:13px;margin:4px 0";
        const p = el("p", "", v("OBSERVACAO") || "—"); p.style.whiteSpace = "pre-wrap";
        corpo.append(h, p);
      };
      const tabela = new Tabela($("#tabela-maq"), { rotulos: ROT, onClick: ficha });
      let grupos = false;
      const pg = paginaDados({
        form,
        url: () => "/api/maquinas",
        aoIniciar: async () => {
          const o = await opcoes();
          opcoesSelect(form.elements.filial, o.filiais, "Todas");
          preencherFiltros(form, new URLSearchParams(location.search));
        },
        render(d) {
          if (!grupos) { grupos = true; opcoesSelect(form.elements.grupo, d.grupos, "Todos os grupos"); preencherFiltros(form, new URLSearchParams(location.search)); }
          const k = d.kpis;
          kpis($("#kpis-maq"), [
            { rotulo: "Máquinas e veículos", valor: F.inteiro(k.qtd) },
            { rotulo: "Ativas", valor: F.inteiro(k.ativas) },
            { rotulo: "Grupos", valor: F.inteiro(k.grupos) },
            { rotulo: "Marcas", valor: F.inteiro(k.marcas) },
          ]);
          G.desenhar($("#g-maq-grupo"), () => G.barras($("#g-maq-grupo"), d.por_grupo, {
            onClick: (x) => x.rotulo !== "Outros" && x.rotulo !== "(sem grupo)" && pg.definir("grupo", x.rotulo.split(" - ")[0]) }));
          G.desenhar($("#g-maq-marca"), () => G.barras($("#g-maq-marca"), d.por_marca, { cor: "var(--serie-3)" }));
          tabela.definir(d.tabela, d.truncado);
        },
      });
      $("#limpar-maq").addEventListener("click", () => { form.reset(); pg.carregar(); });
    }
    function iniciarProdutos() {
      const form = $("#filtros-prod");
      const tabela = new Tabela($("#tabela-prod"), {
        celula: (c, v, td) => {
          if (c === "ALERTA" && v) {
            v.split("; ").forEach((a) => { const s = document.createElement("span"); s.className = "tag atencao"; s.textContent = a; td.append(s, " "); });
            return true;
          }
          return false;
        },
      });
      const pg = paginaDados({
        form,
        url: () => "/api/produtos",
        aoIniciar: async () => {
          const o = await opcoes();
          opcoesSelect(form.elements.grupo, o.grupos, "Todos os grupos");
          preencherFiltros(form, new URLSearchParams(location.search));
        },
        render(d) {
          const k = d.kpis;
          kpis($("#kpis-prod"), [
            { rotulo: "Produtos", valor: F.inteiro(k.qtd) },
            { rotulo: "Com algum alerta", valor: F.inteiro(k.com_alerta), classe: k.com_alerta ? "critico" : "" },
            { rotulo: "ST sem CEST", valor: F.inteiro(k["alerta_ST sem CEST"]) },
            { rotulo: "Sem situação tributária", valor: F.inteiro(k["alerta_Sem situação tributária"]) },
          ]);
          G.desenhar($("#g-sit"), () => G.barras($("#g-sit"), d.por_situacao, { larguraRotulo: 220 }));
          G.desenhar($("#g-alertas"), () => G.barras($("#g-alertas"), d.alertas, { cor: "var(--serie-8)", larguraRotulo: 170,
            onClick: (x) => pg.definir("alerta", x.rotulo) }));
          tabela.definir(d.tabela, d.truncado);
        },
      });
      $("#limpar-prod").addEventListener("click", () => { form.reset(); pg.carregar(); });
    }
  }

  /* =============================================================== RELATÓRIOS */
  async function telaRelatorios() {
    const raiz = $(".conteudo");
    const form = $("#filtros");
    form.addEventListener("submit", (e) => e.preventDefault());
    const o = await opcoes();
    opcoesSelect(form.elements.tipos, o.tipos, "Todos os tipos");
    opcoesSelect(form.elements.vendedor, o.vendedores, "Todos");
    opcoesSelect(form.elements.local, o.locais, "Todos os locais");
    opcoesSelect(form.elements.filial, o.filiais, "Todas");
    presets(form, () => {});
    const hoje = new Date();
    form.elements.ini.value = iso(new Date(hoje.getFullYear(), 0, 1));
    form.elements.fim.value = iso(hoje);
    $$("[data-rel]").forEach((b) => b.addEventListener("click", async () => {
      const p = lerFiltros(form);
      p.set("formato", b.dataset.formato);
      const rel = b.dataset.rel;
      if (rel === "titulos") { p.set("base", "vencimento"); }
      b.disabled = true;
      try { await baixar(`/api/relatorio/${rel}?${p}`); } catch (e) { aviso(raiz, e.message); } finally { b.disabled = false; }
    }));
    rbIniciar().catch((e) => aviso(raiz, e.message));
    // consultas salvas
    const cont = $("#consultas");
    try {
      const d = await api("/api/consultas");
      if (!d.consultas.length) {
        cont.textContent = "Nenhuma consulta salva ainda. Crie em Consulta SQL e marque \"Compartilhar\" para aparecer aqui para todos.";
        return;
      }
      cont.replaceChildren();
      d.consultas.forEach((c) => {
        const box = document.createElement("div"); box.className = "rel";
        const h = document.createElement("h3"); h.textContent = c.nome;
        const p = document.createElement("p"); p.textContent = (c.descricao || "") + (c.dono ? ` — por ${c.dono}` : "") + (c.compartilhada ? " · compartilhada" : "");
        const ac = document.createElement("div"); ac.className = "acoes";
        const temParams = parametrosSQL(c.sql).length > 0;
        [["Ver", null], ["Excel", "xlsx"], ["PDF", "pdf"]].forEach(([rot, fmt]) => {
          const b = document.createElement("button"); b.className = "btn pequeno" + (fmt ? "" : " primario"); b.textContent = rot;
          b.onclick = async () => {
            if (temParams) return verConsulta(c);
            b.disabled = true;
            try {
              if (fmt) await baixar(`/api/consultas/${c.id}/arquivo?formato=${fmt}`);
              else verConsulta(c);
            } catch (e) { aviso(raiz, e.message); } finally { b.disabled = false; }
          };
          ac.appendChild(b);
        });
        box.append(h, p, ac);
        cont.appendChild(box);
      });
    } catch (e) {
      cont.textContent = e.message;
    }
  }

  /* ------------------------------------------------------------- parâmetros :NOME */
  function parametrosSQL(sql) {
    const vistos = [];
    const re = /'(?:[^']|'')*'|"(?:[^"]|"")*"|--[^\n]*|\/\*[\s\S]*?\*\/|:([A-Za-z_][A-Za-z0-9_]*)/g;
    let m;
    while ((m = re.exec(sql || ""))) {
      if (m[1] && !vistos.includes(m[1].toUpperCase())) vistos.push(m[1].toUpperCase());
    }
    return vistos;
  }
  function tipoPorNome(n) {
    return /(^|_)(DATA|DT|INI|INICIAL|FIM|FINAL|EMISSAO|VENCIMENTO)(_|$)/.test(n) ? "data" : "texto";
  }
  /* formulário de parâmetros; devolve função que lê os valores */
  function formParams(cont, lista, anteriores = {}) {
    cont.replaceChildren();
    if (!lista.length) return () => ({});
    cont.className = "form-grade params-grade";
    const campos = {};
    lista.forEach((p) => {
      const l = document.createElement("label");
      const r = document.createElement("span"); r.textContent = p.rotulo + (p.obrigatorio ? " *" : "");
      const v0 = anteriores[p.nome] !== undefined ? anteriores[p.nome] : p.padrao;
      if (p.tipo === "opcao") {
        const s = document.createElement("select"); s.className = "campo";
        (p.opcoes || []).forEach(([val, rot]) => { const o = document.createElement("option"); o.value = val; o.textContent = rot; s.appendChild(o); });
        if (v0) s.value = v0;
        s.dataset.nome = p.nome;
        l.append(r, s);
        cont.appendChild(l);
        campos[p.nome] = s;
        return;
      }
      if (p.escolha === "filiais") {
        // filial (lista vinda do banco; vazio = todas)
        const s = document.createElement("select"); s.className = "campo";
        const o0 = document.createElement("option"); o0.value = ""; o0.textContent = "Todas"; s.appendChild(o0);
        if (v0) { const o1 = document.createElement("option"); o1.value = v0; o1.textContent = v0; s.appendChild(o1); s.value = v0; }
        s.dataset.nome = p.nome;
        l.append(r, s);
        cont.appendChild(l);
        campos[p.nome] = s;
        opcoes().then((o) => opcoesSelect(s, o.filiais || [], "Todas")).catch(() => {});
        return;
      }
      if (p.escolha === "tipos_mov") {
        // escolha de um ou mais tipos de movimento (caixas de seleção)
        const h = document.createElement("input"); h.type = "hidden"; h.value = v0 || "";
        const d = document.createElement("div"); d.className = "filtro-rot";
        const rr = document.createElement("span"); rr.textContent = p.rotulo + (p.obrigatorio ? " *" : "");
        d.append(rr, h);
        cont.appendChild(d);
        campos[p.nome] = h;
        opcoes().then((o) => multiEscolha(h, (o.tipos || []).filter((x) => !p.prefixo || String(x.cod).startsWith(p.prefixo)),
          p.prefixo ? `Todos os ${p.prefixo}.x` : "Todos os tipos")).catch(() => {});
        return;
      }
      const i = document.createElement("input"); i.className = "campo";
      i.type = p.tipo === "data" ? "date" : "text";
      if (p.tipo === "numero") i.inputMode = "decimal";
      const v = anteriores[p.nome] !== undefined ? anteriores[p.nome] : p.padrao;
      if (v !== null && v !== undefined) i.value = v;
      if (p.tipo === "lista") i.placeholder = /CFO|CLI|FOR/.test(p.nome) ? "ex.: C000001, F000433" : /TMV|TIPO_MOV/.test(p.nome) ? "ex.: 2.2.21, 2.1.05" : "separe por vírgula";
      if (!p.obrigatorio) i.title = "Deixe vazio para não filtrar";
      i.dataset.nome = p.nome;
      l.append(r, i);
      cont.appendChild(l);
      campos[p.nome] = i;
    });
    return () => Object.fromEntries(Object.entries(campos).map(([k, i]) => [k, i.value]));
  }

  async function verConsulta(c) {
    const corpo = gaveta(c.nome, true);
    const nomes = parametrosSQL(c.sql);
    const pform = document.createElement("div");
    corpo.appendChild(pform);
    const ler = formParams(pform, nomes.map((n) => ({ nome: n, rotulo: n.replace(/_/g, " ").toLowerCase(), tipo: tipoPorNome(n) })));
    const ac = document.createElement("div"); ac.className = "acoes-linha";
    const res = document.createElement("div");
    const qs = () => Object.entries(ler()).map(([k, v]) => `p_${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
    const rodar = async () => {
      res.replaceChildren();
      try {
        const d = await api(`/api/consultas/${c.id}/dados?${qs()}`);
        if (!d.visoes) d.visoes = [{ nome: "Resultado", colunas: d.colunas || [], linhas: d.linhas || [], truncado: d.truncado }];
        ultimo = d;
        editar.hidden = !d.pode_editar || respostaAntiga(d);
        mostrarVisoes(res, d.visoes);
        if (respostaAntiga(d)) res.prepend(el("div", "aviso atencao", SERVIDOR_ANTIGO));
      } catch (e) { aviso(corpo, e.message); }
    };
    let ultimo = null;
    const editar = el("button", "btn", "Editar layout"); editar.hidden = true;
    editar.onclick = () => ultimo && editorLayout({ chave: "sq:" + c.id, nome: c.nome, visoes: ultimo.visoes, layout: ultimo.layout, aoSalvar: rodar });
    [["Ver", null], ["Excel", "xlsx"], ["PDF", "pdf"]].forEach(([rot, fmt]) => {
      const b = document.createElement("button"); b.className = "btn" + (fmt ? "" : " primario"); b.textContent = rot;
      b.onclick = async () => {
        b.disabled = true;
        try { if (fmt) await baixar(`/api/consultas/${c.id}/arquivo?formato=${fmt}&${qs()}`); else await rodar(); }
        catch (e) { aviso(corpo, e.message); } finally { b.disabled = false; }
      };
      ac.appendChild(b);
    });
    ac.appendChild(editar);
    corpo.append(ac, res);
    if (!nomes.length) rodar();
  }

  /* ------------------------------------------------------------- relatórios do ReportBuilder */
  async function rbIniciar() {
    const cont = $("#rb-lista");
    if (!cont) return;
    const d = await api("/api/rb");
    $$("[data-rel]").forEach((b) => { if (!d.prontos.includes(b.dataset.rel)) { const card = b.closest(".rel"); if (card) card.hidden = true; } });
    const todos = d.relatorios;
    const pastas = [...new Set(todos.map((r) => r.pasta))].sort((a, b) => a.localeCompare(b, "pt-BR"));
    const selP = $("#rb-pasta");
    pastas.forEach((p) => { const o = document.createElement("option"); o.value = p; o.textContent = p; selP.appendChild(o); });
    const info = $("#rb-info");
    if (d.teste && d.teste.total) {
      info.textContent = d.teste.andamento ? `Teste em andamento: ${d.teste.feitos} de ${d.teste.total}`
        : `Último teste: ${d.teste.inicio || ""} · ${d.teste.com_erro || 0} com erro`;
    }
    function render() {
      const busca = $("#rb-busca").value.trim().toLowerCase();
      const pasta = selP.value;
      const antigos = $("#rb-antigos").checked;
      const filtrados = todos.filter((r) => (antigos || !r.antigo) && (!pasta || r.pasta === pasta) &&
        (!busca || r.nome.toLowerCase().includes(busca) || r.pasta.toLowerCase().includes(busca)));
      $("#rb-conta").textContent = `${filtrados.length} de ${todos.length} relatórios`;
      cont.replaceChildren();
      const grupos = new Map();
      filtrados.forEach((r) => { if (!grupos.has(r.pasta)) grupos.set(r.pasta, []); grupos.get(r.pasta).push(r); });
      const item = (r) => {
        const linha = document.createElement("button");
        linha.type = "button"; linha.className = "rb-item";
        const nome = document.createElement("span"); nome.className = "rb-nome"; nome.textContent = r.nome;
        const meta = document.createElement("span"); meta.className = "rb-meta";
        const partes = [`${r.visoes.length} ${r.visoes.length === 1 ? "visão" : "visões"}`];
        if (r.parametros.length) partes.push(`${r.parametros.length} filtro(s)`);
        partes.push("alterado " + fmtData(r.alterado));
        meta.textContent = partes.join(" · ");
        linha.append(nome, meta);
        if (r.antigo) { const t = document.createElement("span"); t.className = "tag"; t.textContent = "antigo/teste"; linha.appendChild(t); }
        if (r.erro) { const t = document.createElement("span"); t.className = "tag critico"; t.textContent = "erro no teste"; t.title = r.erro; linha.appendChild(t); }
        linha.onclick = () => abrirRB(r, d.pode_sql);
        return linha;
      };
      const MOD = { movimentos: "Movimentos", estoque: "Estoque", financeiro: "Financeiro", cadastros: "Cadastros", relatorios: "Relatórios" };
      const moduloDe = (lista) => {
        const c = {};
        lista.forEach((r) => { c[r.modulo] = (c[r.modulo] || 0) + 1; });
        return Object.keys(c).sort((x, y) => c[y] - c[x])[0] || "relatorios";
      };
      const ultima = (lista) => lista.reduce((m, r) => (r.alterado && (!m || r.alterado > m) ? r.alterado : m), null);

      if (pasta) {
        // dentro de uma pasta: cabeçalho com voltar + relatórios em cards
        const cab = el("div", "rb-pasta-cab");
        const voltar = el("button", "btn pequeno", "← Todas as pastas");
        voltar.type = "button";
        voltar.onclick = () => { selP.value = ""; render(); cont.scrollIntoView({ block: "nearest" }); };
        const titulo = el("h3", "", pasta);
        cab.append(voltar, titulo, el("span", "tag", String(filtrados.length)));
        cont.appendChild(cab);
        const grade = el("div", "rb-itens-grade");
        filtrados.forEach((r) => grade.appendChild(item(r)));
        cont.appendChild(grade);
      } else {
        // pastas como cards
        const grade = el("div", "rb-pastas");
        grupos.forEach((lista, p) => {
          const card = el("div", "rb-pasta-card mod-" + moduloDe(lista));
          const topo = el("button", "rb-pasta-topo");
          topo.type = "button";
          topo.title = "Abrir a pasta " + p;
          const ic = el("span", "rb-pasta-ic"); ic.setAttribute("aria-hidden", "true");
          const txt = el("span", "rb-pasta-txt");
          txt.append(el("strong", "", p),
            el("span", "rb-meta", `${lista.length} ${lista.length === 1 ? "relatório" : "relatórios"} · ${MOD[moduloDe(lista)] || ""}` +
              (ultima(lista) ? ` · alterado ${fmtData(ultima(lista))}` : "")));
          topo.append(ic, txt);
          topo.onclick = () => { selP.value = p; render(); cont.scrollIntoView({ block: "nearest" }); };
          card.appendChild(topo);
          const corpo = el("div", "rb-pasta-itens");
          const mostrar = busca ? lista : lista.slice(0, 4);   // com busca mostra todos os encontrados
          mostrar.forEach((r) => {
            const b = el("button", "rb-mini", r.nome);
            b.type = "button"; b.title = r.nome;
            b.onclick = () => abrirRB(r, d.pode_sql);
            corpo.appendChild(b);
          });
          if (lista.length > mostrar.length) {
            const mais = el("button", "rb-mais", `+ ${lista.length - mostrar.length} relatório(s) · ver pasta`);
            mais.type = "button";
            mais.onclick = topo.onclick;
            corpo.appendChild(mais);
          }
          card.appendChild(corpo);
          grade.appendChild(card);
        });
        cont.appendChild(grade);
      }
      if (!filtrados.length) cont.textContent = "Nenhum relatório encontrado.";
    }
    ["#rb-busca", "#rb-pasta", "#rb-antigos"].forEach((s) => $(s).addEventListener(s === "#rb-busca" ? "input" : "change", render));
    render();
  }

  function abrirRB(r, podeSQL) {
    const corpo = gaveta(r.nome, true);
    const sub = document.createElement("p"); sub.className = "gtick"; sub.style.margin = "0 0 12px";
    sub.textContent = `${r.pasta} · ${r.padrao_painel ? "relatório padrão do painel" : "importado do ReportBuilder"} · ${r.visoes.join(", ")}`;
    corpo.appendChild(sub);
    if (r.erro) aviso(corpo, "No último teste este relatório deu erro: " + r.erro, "atencao");
    const pform = document.createElement("div");
    corpo.appendChild(pform);
    const ler = formParams(pform, r.parametros);
    const ac = document.createElement("div"); ac.className = "acoes-linha";
    const res = document.createElement("div"); res.className = "rb-res";
    const ver = document.createElement("button"); ver.className = "btn primario"; ver.textContent = "Ver";
    const editar = el("button", "btn", "Editar layout"); editar.hidden = true;
    editar.title = "Escolher colunas, nomes, formatos, agrupamento, totais, gráfico e indicadores (vale para todos)";
    let ultimo = null;
    ver.onclick = async () => {
      ver.disabled = true; res.replaceChildren(); res.textContent = "Consultando…";
      try {
        const d = await api(`/api/rb/${encodeURIComponent(r.id)}/executar`, { json: { valores: ler() } });
        ultimo = d;
        editar.hidden = !d.pode_editar || respostaAntiga(d);
        mostrarVisoes(res, d.visoes);
        if (respostaAntiga(d)) res.prepend(el("div", "aviso atencao", SERVIDOR_ANTIGO));
      } catch (e) { res.textContent = ""; aviso(corpo, e.message); } finally { ver.disabled = false; }
    };
    editar.textContent = "Colunas da tela";
    editar.title = "Colunas, nomes, formatos, agrupamento, totais e gráfico da visualização na tela e do Excel (vale para todos)";
    editar.onclick = () => ultimo && editorLayout({ chave: "rb:" + encodeURIComponent(r.id), nome: r.nome, visoes: ultimo.visoes, layout: ultimo.layout, aoSalvar: () => ver.click() });
    ac.appendChild(ver);
    const opcoesPDF = [["Excel", "xlsx", false], ["PDF", "pdf", false]];
    if (r.impressao) opcoesPDF.push(["PDF em tabela", "pdf", true]);
    opcoesPDF.forEach(([rot, fmt, tabela]) => {
      const b = document.createElement("button"); b.className = "btn"; b.textContent = rot;
      if (fmt === "pdf") b.title = tabela ? "PDF com as colunas da tela (sem o layout de impressão)" : (r.impressao ? "PDF com o layout de impressão (como no ReportBuilder)" : "PDF");
      b.onclick = async () => {
        b.disabled = true;
        try { await baixar(`/api/rb/${encodeURIComponent(r.id)}/arquivo`, { json: { valores: ler(), formato: fmt, tabela } }); }
        catch (e) { aviso(corpo, e.message); } finally { b.disabled = false; }
      };
      ac.appendChild(b);
    });
    const desenhoBtn = el("button", "btn", "Editar layout");
    desenhoBtn.title = "Layout de impressão no estilo ReportBuilder: bandas, campos, textos, linhas, totais (o PDF sai assim)";
    desenhoBtn.onclick = () => {
      if (!window.DesignerRB) { aviso(corpo, "Atualize a página (Ctrl+F5) para carregar o editor."); return; }
      window.DesignerRB.abrir({ rid: r.id, nome: r.nome, valores: ler(), api, baixar });
    };
    ac.appendChild(desenhoBtn);
    ac.appendChild(editar);
    if (podeSQL) {
      const b = document.createElement("button"); b.className = "btn"; b.textContent = "Abrir SQL no editor";
      b.title = "Abre a consulta da primeira visão na tela Consulta SQL para ajustar e salvar";
      b.onclick = async () => {
        try {
          const d = await api(`/api/rb/${encodeURIComponent(r.id)}/sql`);
          const vals = ler();
          try { sessionStorage.setItem("sql_pendente", JSON.stringify({ sql: d.visoes[0].sql, valores: vals, nome: r.nome })); } catch (e) { /* */ }
          location.href = "/sql";
        } catch (e) { aviso(corpo, e.message); }
      };
      ac.appendChild(b);
    }
    corpo.append(ac, res);
    if (!r.parametros.some((p) => p.obrigatorio && (p.padrao === null || p.padrao === undefined))) ver.click();
  }

  /* ------------------------------------------------------------- visões com layout (relatórios) */
  function el(tag, classe, texto) {
    const e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  function mostrarVisoes(cont, visoes) {
    cont.replaceChildren();
    const vis = visoes.filter((v) => !v.oculta);
    const ocultas = visoes.length - vis.length;
    if (!vis.length) {
      cont.appendChild(el("div", "aviso atencao", "Todas as visões estão ocultas no layout deste relatório. Use \"Editar layout\" para mostrar."));
      return;
    }
    const abas = el("div", "abas");
    const area = el("div"); area.style.marginTop = "12px";
    if (vis.length > 1 || ocultas) cont.appendChild(abas);
    cont.appendChild(area);
    const mostrar = (i) => {
      $$("button", abas).forEach((b, k) => b.classList.toggle("ativa", k === i));
      renderVisao(area, vis[i]);
    };
    vis.forEach((v, i) => {
      const b = el("button", "", `${v.titulo || v.nome} (${v.erro ? "erro" : (v.linhas || []).length})`);
      b.onclick = () => mostrar(i);
      abas.appendChild(b);
    });
    if (ocultas) abas.appendChild(el("span", "nota", ` ${ocultas} oculta(s) pelo layout`));
    mostrar(Math.max(0, vis.findIndex((v) => v.linhas && v.linhas.length)));
  }

  const SERVIDOR_ANTIGO = "O servidor do painel ainda está rodando a versão anterior do programa, por isso o editor de layout não funciona. " +
    "No servidor, rode reiniciar_painel.bat (botão direito > Executar como administrador) e depois aperte Ctrl+F5 aqui.";
  const respostaAntiga = (d) => !!(d && d.visoes && d.visoes.length && d.visoes[0].colunas_originais === undefined);

  function renderVisao(area, v) {
    area.replaceChildren();
    if (v.erro) { area.appendChild(el("div", "aviso erro", v.erro)); return; }
    if (v.aviso) area.appendChild(el("div", "aviso atencao", v.aviso));
    if (v.colunas_originais === undefined) {   // servidor ainda na versão anterior
      if (!v.colunas || !v.colunas.length) return;
      const t0 = el("div"); area.appendChild(t0);
      new Tabela(t0, { porPagina: 100 }).definir(v, v.truncado);
      return;
    }
    if (!v.colunas || !v.colunas.length) {
      if (v.colunas_originais && v.colunas_originais.length) area.appendChild(el("div", "aviso atencao", "Nenhuma coluna visível no layout desta visão."));
      return;
    }
    if (v.indicadores && v.indicadores.length) {
      const k = el("div", "kpis"); k.style.marginBottom = "14px"; area.appendChild(k);
      kpis(k, v.indicadores.map((i) => ({ rotulo: i.rotulo, valor: i.formato === "moeda" && typeof i.valor === "number" ? F.moeda(i.valor) : fmtValor(i.formato, i.valor) || "—" })));
    }
    if (v.grafico && v.grafico.pontos && v.grafico.pontos.length) {
      const box = el("div", "cartao"); box.style.marginBottom = "14px";
      const cab = el("div", "cartao-cab"); cab.appendChild(el("h2", "", v.grafico.titulo));
      const g = el("div");
      box.append(cab, g); area.appendChild(box);
      desenharPontos(g, v.grafico);
    }
    const t = el("div"); area.appendChild(t);
    if (v.blocos) tabelaGrupos(t, v);
    else new Tabela(t, { porPagina: 100, defs: v.colunas }).definir({ colunas: v.colunas.map((c) => c.campo), linhas: v.linhas }, v.truncado);
  }

  function desenharPontos(cont, g) {
    let pts = g.pontos.slice();
    const juntar = (n) => {
      if (pts.length > n) {
        const resto = pts.slice(n - 1).reduce((a, p) => a + p.valor, 0);
        pts = pts.slice(0, n - 1).concat([{ rotulo: "Outros", valor: resto }]);
      }
    };
    if (g.tipo === "barras") juntar(15);
    if (g.tipo === "rosca") juntar(6);
    if (g.tipo === "colunas" && pts.length > 36) pts = pts.slice(-36);
    const moeda = g.formato === "moeda";
    const fmt = moeda ? F.moeda : F.numero;
    pts = pts.map((p) => ({ rotulo: /^\d{4}-\d{2}-\d{2}/.test(p.rotulo) ? fmtData(p.rotulo) : p.rotulo, valor: p.valor }));
    G.desenhar(cont, () => {
      if (g.tipo === "linhas") G.linhas(cont, [{ nome: g.titulo, pontos: pts }], { formato: fmt, moeda, area: true });
      else if (g.tipo === "colunas") G.colunas(cont, [{ nome: g.titulo, pontos: pts }], { formato: fmt, moeda });
      else if (g.tipo === "rosca") G.rosca(cont, pts, { formato: fmt, compacto: true, moeda });
      else G.barras(cont, pts, { formato: fmt, compacto: moeda, moeda, larguraRotulo: 240 });
    });
  }

  /* tabela com grupos e subtotais (recolher/expandir clicando no grupo) */
  function tabelaGrupos(cont, v) {
    cont.replaceChildren();
    const LIM = 6000;
    const barra = el("div", "tabela-barra");
    const nGrupos = v.blocos.filter((b) => b.t === "grupo" && b.nivel === 0).length;
    const info = el("span", "info", `${F.inteiro(v.linhas.length)} linhas em ${F.inteiro(nGrupos)} grupos` + (v.truncado ? " · limite atingido" : ""));
    const bRec = el("button", "btn pequeno", "Recolher grupos");
    const bExp = el("button", "btn pequeno", "Expandir tudo");
    barra.append(info, bRec, bExp);
    const wrap = el("div", "tabela-wrap");
    cont.append(barra, wrap);
    const cols = v.colunas;
    const vis = [];   // colunas visuais (as marcadas "abaixo" ficam na mesma célula da anterior)
    cols.forEach((c, j) => { if (c.abaixo && vis.length) vis[vis.length - 1].push(j); else vis.push([j]); });
    const numG = vis.map((gr) => gr.every((j) => NUMFMT.has(cols[j].formato)));
    const tb = el("table", "dados agrupada" + (vis.length < cols.length ? " empilhada" : ""));
    const th = tb.createTHead().insertRow();
    vis.forEach((gr, k) => {
      const h = el("th", numG[k] ? "num" : ""); h.style.cursor = "default";
      gr.forEach((j) => h.appendChild(el("div", "", cols[j].rotulo)));
      th.appendChild(h);
    });
    const body = tb.createTBody();
    const pilha = [];
    let gid = 0;
    const celulas = (tr, vals, rotulo) => {
      vis.forEach((gr, k) => {
        const td = tr.insertCell();
        if (numG[k]) td.className = "num";
        if (k === 0 && rotulo && gr.every((j) => vals[j] === null || vals[j] === undefined)) { td.textContent = rotulo; return; }
        gr.forEach((j) => {
          const x = vals[j];
          const d = el("div", typeof x === "number" && x < 0 ? "neg" : "", fmtValor(cols[j].formato, x) || "\u00a0");
          if (typeof x === "string" && x.length > 40) d.title = x;
          td.appendChild(d);
        });
      });
    };
    v.blocos.slice(0, LIM).forEach((b) => {
      const tr = body.insertRow();
      if (b.t === "grupo") {
        pilha.length = b.nivel;
        const id = "g" + (++gid);
        tr.className = `grupo n${b.nivel}`;
        tr.dataset.id = id;
        pilha.forEach((p) => tr.classList.add("em-" + p));
        const td = tr.insertCell(); td.colSpan = vis.length;
        const val = b.valor === null || b.valor === undefined || b.valor === "" ? "(vazio)" : (/^\d{4}-\d{2}-\d{2}/.test(String(b.valor)) ? fmtData(b.valor) : b.valor);
        td.textContent = `▾ ${b.rotulo}: ${val}`;
        td.appendChild(el("span", "qtd", ` ${b.qtd} ${b.qtd === 1 ? "linha" : "linhas"}`));
        tr.onclick = () => alternar(tr);
        pilha.push(id);
        return;
      }
      if (b.t === "subtotal") {
        // o subtotal fica visível mesmo com o grupo recolhido
        pilha.length = b.nivel + 1;
        const dono = pilha[b.nivel];
        pilha.slice(0, b.nivel).forEach((p) => tr.classList.add("em-" + p));
        tr.classList.add("subtotal", `n${b.nivel}`);
        tr.dataset.de = dono;
        const val = b.valor === null || b.valor === undefined || b.valor === "" ? "(vazio)" : (/^\d{4}-\d{2}-\d{2}/.test(String(b.valor)) ? fmtData(b.valor) : b.valor);
        celulas(tr, b.v, `Subtotal ${val}`);
        pilha.length = b.nivel;
        return;
      }
      pilha.forEach((p) => tr.classList.add("em-" + p));
      celulas(tr, b.v);
    });
    if (v.totais) {
      const tr = tb.createTFoot().insertRow();
      celulas(tr, v.totais, "Total geral");
    }
    function alternar(tr, forcar) {
      const fechar = forcar !== undefined ? forcar : !tr.classList.contains("fechado");
      tr.classList.toggle("fechado", fechar);
      tr.firstChild.firstChild.textContent = tr.firstChild.firstChild.textContent.replace(/^[▾▸]/, fechar ? "▸" : "▾");
      const id = tr.dataset.id;
      $$(".em-" + id, body).forEach((r) => {
        if (fechar) { r.hidden = true; return; }
        // reabre filhos, respeitando subgrupos ainda recolhidos
        const dentroFechado = Array.from(r.classList).some((c) => c.startsWith("em-") && c !== "em-" + id && $(`tr[data-id="${c.slice(3)}"]`, body)?.classList.contains("fechado"));
        r.hidden = dentroFechado;
      });
    }
    bRec.onclick = () => $$("tr.grupo.n0", body).forEach((tr) => alternar(tr, true));
    bExp.onclick = () => { $$("tr.grupo", body).forEach((tr) => tr.classList.remove("fechado")); $$("tr.grupo", body).forEach((tr) => alternar(tr, false)); };
    wrap.appendChild(tb);
    if (v.blocos.length > LIM) cont.appendChild(el("div", "aviso atencao", `Mostrando parte do relatório na tela. Exporte em Excel ou PDF para ver todos os ${F.inteiro(v.linhas.length)} registros.`));
  }

  /* ------------------------------------------------------------- editor de layout */
  const OPC_FORMATO = [["auto", "Automático"], ["texto", "Texto"], ["inteiro", "Inteiro"], ["numero", "Número"], ["moeda", "Valor (0,00)"], ["percentual", "Percentual"], ["data", "Data"], ["datahora", "Data e hora"]];
  const OPC_TOTAL = [["nenhum", "—"], ["soma", "Soma"], ["media", "Média"], ["contagem", "Contagem"], ["minimo", "Mínimo"], ["maximo", "Máximo"]];
  const OPC_GRAFICO = [["nenhum", "Sem gráfico"], ["barras", "Barras (ranking)"], ["colunas", "Colunas"], ["linhas", "Linhas (evolução)"], ["rosca", "Rosca (participação)"]];

  function selecao(opcoes, valor, aoMudar) {
    const s = el("select", "campo");
    opcoes.forEach(([v, r]) => { const o = el("option", "", r); o.value = v; s.appendChild(o); });
    s.value = valor ?? opcoes[0][0];
    if (s.value !== String(valor ?? opcoes[0][0])) s.value = opcoes[0][0];
    if (aoMudar) s.onchange = () => aoMudar(s.value);
    return s;
  }
  function rotulado(rotulo, campo) {
    const l = el("label", "ed-campo");
    l.append(el("span", "", rotulo), campo);
    return l;
  }

  function editorLayout({ chave, nome, visoes, layout, aoSalvar }) {
    const lay = JSON.parse(JSON.stringify(layout || {}));
    delete lay._info;
    lay.visoes = lay.visoes || {};
    lay.pdf = lay.pdf || { orientacao: "auto" };
    const editaveis = visoes.filter((v) => v.colunas_originais && v.colunas_originais.length);
    editaveis.forEach((v) => {
      const c = lay.visoes[v.nome] = lay.visoes[v.nome] || {};
      c.titulo = c.titulo || "";
      c.oculta = !!c.oculta;
      c.colunas = (v.config_colunas || []).map((x) => ({ campo: x.campo, rotulo: x.rotulo, visivel: x.visivel, formato: x.formato_salvo || "auto", total: x.total, abaixo: !!x.abaixo }));
      c.ordenar = c.ordenar || [];
      c.agrupar = c.agrupar || [];
      c.grafico = Object.assign({ tipo: "nenhum", x: "", y: "", agregacao: "soma", por_mes: false, titulo: "" }, c.grafico || {});
      c.indicadores = c.indicadores || [];
    });

    const fundo = el("div", "modal-fundo");
    const modal = el("div", "modal");
    modal.setAttribute("role", "dialog");
    const cab = el("div", "modal-cab");
    cab.appendChild(el("h2", "", "Editar layout · " + nome));
    const fechar = el("button", "btn pequeno", "Fechar ✕");
    cab.appendChild(fechar);
    const corpo = el("div", "modal-corpo");
    const rod = el("div", "modal-rodape");
    modal.append(cab, corpo, rod);
    fundo.appendChild(modal);
    document.body.appendChild(fundo);
    const sair = () => { fundo.remove(); document.removeEventListener("keydown", esc, true); };
    const esc = (e) => { if (e.key === "Escape") { e.stopPropagation(); sair(); } };
    document.addEventListener("keydown", esc, true);
    fechar.onclick = sair;
    fundo.addEventListener("click", (e) => { if (e.target === fundo) sair(); });

    corpo.appendChild(el("p", "nota", "O layout vale para todos os usuários e é usado na tela, no Excel e no PDF. Os dados e filtros do relatório não mudam."));
    if (!editaveis.length) {
      corpo.appendChild(el("div", "aviso atencao", "Nenhuma visão deste relatório devolveu colunas, então não há o que configurar. " +
        "Isso acontece quando a consulta dá erro no banco. Veja abaixo o motivo de cada visão; se for falta de filtro, preencha os campos e clique em Ver de novo."));
      const ul = el("ul", "nota");
      visoes.forEach((v) => ul.appendChild(el("li", "", `${v.nome}: ${v.erro || v.aviso || "sem colunas"}`)));
      corpo.appendChild(ul);
    }
    const abas = el("div", "abas");
    const painel = el("div", "ed-painel");
    if (editaveis.length > 1) corpo.appendChild(abas);
    corpo.appendChild(painel);

    function montar(v) {
      const c = lay.visoes[v.nome];
      const campos = v.colunas_originais;
      const rotuloDe = (campo) => (c.colunas.find((x) => x.campo === campo) || {}).rotulo || campo;
      const opCampos = (vazio) => [["", vazio]].concat(campos.map((x) => [x, `${rotuloDe(x)} (${x})`]));
      painel.replaceChildren();

      // visão
      const sv = el("section", "ed-secao");
      sv.appendChild(el("h3", "", "Visão"));
      const g1 = el("div", "ed-linha");
      const tit = el("input", "campo"); tit.value = c.titulo; tit.placeholder = v.nome; tit.oninput = () => { c.titulo = tit.value; };
      const oc = el("input"); oc.type = "checkbox"; oc.checked = c.oculta; oc.onchange = () => { c.oculta = oc.checked; };
      const lo = el("label", "ed-check"); lo.append(oc, document.createTextNode(" Ocultar esta visão (não aparece na tela nem nos arquivos)"));
      g1.append(rotulado("Título", tit), lo);
      sv.appendChild(g1);
      painel.appendChild(sv);

      // colunas
      const sc = el("section", "ed-secao");
      sc.appendChild(el("h3", "", "Colunas"));
      sc.appendChild(el("p", "nota", "Marque as colunas que aparecem, renomeie, escolha o formato e o total. Use as setas para mudar a ordem."));
      const wrap = el("div", "tabela-wrap ed-cols");
      const tb = el("table", "dados");
      const h = tb.createTHead().insertRow();
      ["Mostrar", "Nome na tela", "Campo", "Formato", "Total", "Abaixo da anterior", "Ordem"].forEach((t) => { const x = el("th", "", t); x.style.cursor = "default"; h.appendChild(x); });
      const body = tb.createTBody();
      function linhas() {
        body.replaceChildren();
        c.colunas.forEach((col, k) => {
          const tr = body.insertRow();
          const ck = el("input"); ck.type = "checkbox"; ck.checked = col.visivel !== false; ck.onchange = () => { col.visivel = ck.checked; tr.classList.toggle("apagada", !ck.checked); };
          tr.classList.toggle("apagada", col.visivel === false);
          const ro = el("input", "campo"); ro.value = col.rotulo || ""; ro.oninput = () => { col.rotulo = ro.value; };
          const fm = selecao(OPC_FORMATO, col.formato, (x) => { col.formato = x; });
          const tt = selecao(OPC_TOTAL, col.total, (x) => { col.total = x; });
          const sobe = el("button", "btn pequeno", "↑"); sobe.type = "button"; sobe.disabled = k === 0; sobe.title = "Subir";
          const desce = el("button", "btn pequeno", "↓"); desce.type = "button"; desce.disabled = k === c.colunas.length - 1; desce.title = "Descer";
          sobe.onclick = () => { c.colunas.splice(k - 1, 0, c.colunas.splice(k, 1)[0]); linhas(); };
          desce.onclick = () => { c.colunas.splice(k + 1, 0, c.colunas.splice(k, 1)[0]); linhas(); };
          const ord = el("div", "ed-ordem"); ord.append(sobe, desce);
          const ab = el("input"); ab.type = "checkbox"; ab.checked = !!col.abaixo; ab.disabled = k === 0;
          ab.title = "Mostra esta coluna embaixo da anterior, na mesma célula (ex.: base de cálculo em cima e valor embaixo)";
          ab.onchange = () => { col.abaixo = ab.checked; };
          [ck, ro, el("code", "", col.campo), fm, tt, ab, ord].forEach((x) => tr.insertCell().appendChild(x));
        });
      }
      linhas();
      wrap.appendChild(tb);
      const atalhos = el("div", "ed-linha");
      const todas = el("button", "btn pequeno", "Mostrar todas"); todas.type = "button";
      todas.onclick = () => { c.colunas.forEach((x) => { x.visivel = true; }); linhas(); };
      const nenhuma = el("button", "btn pequeno", "Ocultar todas"); nenhuma.type = "button";
      nenhuma.onclick = () => { c.colunas.forEach((x) => { x.visivel = false; }); linhas(); };
      atalhos.append(todas, nenhuma);
      sc.append(wrap, atalhos);
      painel.appendChild(sc);

      // ordenar e agrupar
      const so = el("section", "ed-secao");
      so.appendChild(el("h3", "", "Agrupar e ordenar"));
      so.appendChild(el("p", "nota", "Agrupar separa o relatório em blocos (ex.: por cliente) com subtotal das colunas que têm total."));
      const g2 = el("div", "ed-linha");
      [0, 1].forEach((n) => {
        g2.appendChild(rotulado(n === 0 ? "Agrupar por" : "Depois por", selecao(opCampos(n === 0 ? "Sem agrupamento" : "—"), c.agrupar[n] || "", (x) => {
          c.agrupar[n] = x;
          c.agrupar = c.agrupar.filter(Boolean);
        })));
      });
      [0, 1].forEach((n) => {
        const o = c.ordenar[n] || { campo: "", dir: "asc" };
        const sCampo = selecao(opCampos(n === 0 ? "Ordem da consulta" : "—"), o.campo, (x) => { o.campo = x; c.ordenar[n] = o; c.ordenar = c.ordenar.filter((y) => y && y.campo); });
        const sDir = selecao([["asc", "Crescente"], ["desc", "Decrescente"]], o.dir, (x) => { o.dir = x; });
        const d = el("div", "ed-par"); d.append(sCampo, sDir);
        g2.appendChild(rotulado(n === 0 ? "Ordenar por" : "Depois por", d));
      });
      so.appendChild(g2);
      painel.appendChild(so);

      // gráfico
      const sg = el("section", "ed-secao");
      sg.appendChild(el("h3", "", "Gráfico"));
      const gr = c.grafico;
      const g3 = el("div", "ed-linha");
      g3.appendChild(rotulado("Tipo", selecao(OPC_GRAFICO, gr.tipo, (x) => { gr.tipo = x; })));
      g3.appendChild(rotulado("Categoria (eixo)", selecao(opCampos("Escolha…"), gr.x, (x) => { gr.x = x; })));
      g3.appendChild(rotulado("Valor", selecao([["", "Quantidade de linhas"]].concat(campos.map((x) => [x, `${rotuloDe(x)} (${x})`])), gr.y, (x) => { gr.y = x; })));
      g3.appendChild(rotulado("Cálculo", selecao(OPC_TOTAL.slice(1), gr.agregacao, (x) => { gr.agregacao = x; })));
      const pm = el("input"); pm.type = "checkbox"; pm.checked = !!gr.por_mes; pm.onchange = () => { gr.por_mes = pm.checked; };
      const lpm = el("label", "ed-check"); lpm.append(pm, document.createTextNode(" Datas agrupadas por mês"));
      const gt = el("input", "campo"); gt.value = gr.titulo || ""; gt.placeholder = "automático"; gt.oninput = () => { gr.titulo = gt.value; };
      g3.append(rotulado("Título do gráfico", gt), lpm);
      sg.appendChild(g3);
      painel.appendChild(sg);

      // indicadores
      const si = el("section", "ed-secao");
      si.appendChild(el("h3", "", "Indicadores (cartões no topo)"));
      const lista = el("div");
      function inds() {
        lista.replaceChildren();
        c.indicadores.forEach((k, n) => {
          const d = el("div", "ed-linha ed-ind");
          const r = el("input", "campo"); r.value = k.rotulo || ""; r.placeholder = "Nome (ex.: Total vendido)"; r.oninput = () => { k.rotulo = r.value; };
          const cp = selecao([["", "(linhas do relatório)"]].concat(campos.map((x) => [x, `${rotuloDe(x)} (${x})`])), k.campo || "", (x) => { k.campo = x; });
          const ag = selecao(OPC_TOTAL.slice(1), k.agregacao || "soma", (x) => { k.agregacao = x; });
          const fm = selecao(OPC_FORMATO, k.formato || "auto", (x) => { k.formato = x; });
          const rm = el("button", "btn pequeno", "Remover"); rm.type = "button";
          rm.onclick = () => { c.indicadores.splice(n, 1); inds(); };
          d.append(rotulado("Nome", r), rotulado("Campo", cp), rotulado("Cálculo", ag), rotulado("Formato", fm), rm);
          lista.appendChild(d);
        });
        add.disabled = c.indicadores.length >= 6;
      }
      const add = el("button", "btn pequeno", "+ Adicionar indicador"); add.type = "button";
      add.onclick = () => { c.indicadores.push({ rotulo: "", campo: "", agregacao: "contagem", formato: "auto" }); inds(); };
      inds();
      si.append(lista, add);
      painel.appendChild(si);
    }

    editaveis.forEach((v, i) => {
      const b = el("button", "", v.nome);
      b.type = "button";
      b.onclick = () => { $$("button", abas).forEach((x, k) => x.classList.toggle("ativa", k === i)); montar(v); };
      abas.appendChild(b);
    });
    if (editaveis.length) { abas.firstChild.classList.add("ativa"); montar(editaveis[0]); }

    // rodapé
    const ori = selecao([["auto", "Automática"], ["retrato", "Retrato"], ["paisagem", "Paisagem"]], lay.pdf.orientacao, (x) => { lay.pdf.orientacao = x; });
    const lori = rotulado("PDF", ori); lori.classList.add("ed-ori");
    const restaurar = el("button", "btn", "Restaurar padrão"); restaurar.type = "button";
    restaurar.title = "Apaga o layout salvo e volta à apresentação original";
    const cancelar = el("button", "btn", "Cancelar"); cancelar.type = "button"; cancelar.onclick = sair;
    const salvar = el("button", "btn primario", "Salvar para todos"); salvar.type = "button";
    const msg = el("span", "nota");
    rod.append(lori, msg, restaurar, cancelar, salvar);
    let confirmar = false;
    restaurar.onclick = async () => {
      if (!confirmar) { confirmar = true; restaurar.textContent = "Confirmar restauração"; restaurar.classList.add("perigo"); return; }
      restaurar.disabled = true;
      try { await api(`/api/layout/${chave}/excluir`, { method: "POST" }); sair(); aoSalvar(); }
      catch (e) { msg.textContent = e.message; restaurar.disabled = false; }
    };
    salvar.onclick = async () => {
      salvar.disabled = true; msg.textContent = "Salvando…";
      try { await api(`/api/layout/${chave}`, { json: lay }); sair(); aoSalvar(); }
      catch (e) { msg.textContent = e.message; salvar.disabled = false; }
    };
    if (layout && layout._info) msg.textContent = `Última alteração: ${layout._info.atualizado} por ${layout._info.por}`;
  }

  /* gráfico montado pelo usuário a partir de um resultado SQL */
  function desenharGraficoLivre(cont, dados, cfg) {
    const ix = dados.colunas.indexOf(cfg.x), iy = dados.colunas.indexOf(cfg.y);
    if (ix < 0) return;
    const agg = new Map();
    dados.linhas.forEach((r) => {
      const k = r[ix] === null ? "(vazio)" : String(r[ix]).slice(0, cfg.tipo === "linhas" || cfg.tipo === "colunas" ? 10 : 60);
      const v = iy < 0 ? 1 : Number(r[iy]) || 0;
      agg.set(k, (agg.get(k) || 0) + v);
    });
    let pts = Array.from(agg, ([rotulo, valor]) => ({ rotulo, valor }));
    if (cfg.tipo === "barras" || cfg.tipo === "rosca") pts.sort((a, b) => b.valor - a.valor);
    else pts.sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR", { numeric: true }));
    if (cfg.tipo === "barras" && pts.length > 15) {
      const resto = pts.slice(14).reduce((a, p) => a + p.valor, 0);
      pts = pts.slice(0, 14).concat([{ rotulo: "Outros", valor: resto }]);
    }
    if (cfg.tipo === "rosca" && pts.length > 5) {
      const resto = pts.slice(4).reduce((a, p) => a + p.valor, 0);
      pts = pts.slice(0, 4).concat([{ rotulo: "Outros", valor: resto }]);
    }
    const moeda = iy >= 0 && MOEDA.test(cfg.y);
    const fmt = moeda ? F.moeda : F.numero;
    const nome = iy < 0 ? "Quantidade" : rotuloCol(cfg.y);
    G.desenhar(cont, () => {
      if (cfg.tipo === "linhas") G.linhas(cont, [{ nome, pontos: pts }], { formato: fmt, moeda, area: true });
      else if (cfg.tipo === "colunas") G.colunas(cont, [{ nome, pontos: pts }], { formato: fmt, moeda });
      else if (cfg.tipo === "rosca") G.rosca(cont, pts, { formato: fmt, compacto: true, moeda });
      else G.barras(cont, pts, { formato: fmt, compacto: moeda, moeda, larguraRotulo: 240 });
    });
  }

  /* =============================================================== SQL */
  async function telaSQL() {
    const raiz = $(".conteudo");
    const ed = $("#sql");
    const res = $("#resultado");
    const tabela = new Tabela($("#tabela"));
    let dados = null;
    let atualId = null;

    // atalho Ctrl+Enter e Tab
    ed.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); executar(); }
      if (e.key === "Tab") {
        e.preventDefault();
        const s = ed.selectionStart;
        ed.setRangeText("  ", s, ed.selectionEnd, "end");
      }
    });

    async function executar() {
      atualizarParams();
      $("#executar").disabled = true;
      $("#tempo").textContent = "Executando…";
      try {
        dados = await api("/api/sql", { json: { sql: textoSQL(), valores: lerParams() } });
        res.hidden = false;
        $("#tempo").textContent = `${F.inteiro(dados.linhas.length)} linhas em ${F.inteiro(dados.ms)} ms` + (dados.truncado ? " · limite de linhas atingido" : "");
        tabela.definir(dados, dados.truncado);
        prepararGrafico();
      } catch (e) {
        $("#tempo").textContent = "";
        aviso(raiz, e.message);
      } finally {
        $("#executar").disabled = false;
      }
    }
    // parâmetros :NOME digitados no SQL viram campos
    let lerParams = () => ({});
    let valoresParams = {};
    function atualizarParams() {
      const nomes = parametrosSQL(ed.value);
      const atuais = lerParams();
      Object.assign(valoresParams, atuais);
      const chave = nomes.join(",");
      if ($("#params").dataset.chave === chave) return;
      $("#params").dataset.chave = chave;
      lerParams = formParams($("#params"), nomes.map((n) => ({ nome: n, rotulo: n.replace(/_/g, " ").toLowerCase(), tipo: tipoPorNome(n) })), valoresParams);
    }
    ed.addEventListener("input", atualizarParams);
    function textoSQL() {
      const sel = ed.value.slice(ed.selectionStart, ed.selectionEnd);
      return sel.trim().length > 6 ? sel : ed.value;
    }
    $("#executar").addEventListener("click", executar);

    function prepararGrafico() {
      const sx = $("#g-x"), sy = $("#g-y");
      const ax = sx.value, ay = sy.value;
      sx.replaceChildren(); sy.replaceChildren();
      const cont = document.createElement("option"); cont.value = ""; cont.textContent = "(contar linhas)"; sy.appendChild(cont);
      dados.colunas.forEach((c, i) => {
        const o = document.createElement("option"); o.value = c; o.textContent = c; sx.appendChild(o);
        if (dados.linhas.some((r) => typeof r[i] === "number")) { const o2 = document.createElement("option"); o2.value = c; o2.textContent = c; sy.appendChild(o2); }
      });
      if (dados.colunas.includes(ax)) sx.value = ax;
      if ([...sy.options].some((o) => o.value === ay)) sy.value = ay;
      else if (sy.options.length > 1) sy.selectedIndex = 1;
      redesenhar();
    }
    function cfgGrafico() { return { tipo: $("#g-tipo").value, x: $("#g-x").value, y: $("#g-y").value }; }
    function redesenhar() {
      const c = cfgGrafico();
      $("#g-livre").hidden = c.tipo === "nenhum";
      if (dados && c.tipo !== "nenhum") desenharGraficoLivre($("#g-livre"), dados, c);
    }
    ["#g-tipo", "#g-x", "#g-y"].forEach((s) => $(s).addEventListener("change", redesenhar));

    $$("[data-exportar]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { await baixar("/api/sql/exportar", { json: { sql: textoSQL(), valores: lerParams(), formato: b.dataset.exportar, titulo: $("#nome").value || "Consulta SQL" } }); }
      catch (e) { aviso(raiz, e.message); } finally { b.disabled = false; }
    }));

    // esquema do banco
    const lista = $("#tabelas");
    const filtroT = $("#filtro-tabelas");
    let nomes = [];
    try { nomes = (await api("/api/esquema")).tabelas; } catch (e) { lista.textContent = e.message; }
    function listar() {
      const f = filtroT.value.toUpperCase();
      lista.replaceChildren();
      nomes.filter((n) => n.includes(f)).slice(0, 400).forEach((n) => {
        const d = document.createElement("div"); d.className = "t"; d.textContent = n;
        const cs = document.createElement("div"); cs.className = "campos-t"; cs.hidden = true;
        d.addEventListener("click", async () => {
          if (!cs.dataset.ok) {
            cs.dataset.ok = 1;
            try {
              (await api("/api/esquema?tabela=" + encodeURIComponent(n))).campos.forEach((c) => {
                const x = document.createElement("div");
                x.append(c.campo + " ");
                const i = document.createElement("i"); i.textContent = c.tipo; x.appendChild(i);
                x.title = "Clique para inserir no SQL";
                x.addEventListener("click", (ev) => { ev.stopPropagation(); ed.setRangeText(c.campo, ed.selectionStart, ed.selectionEnd, "end"); ed.focus(); });
                cs.appendChild(x);
              });
            } catch (e) { cs.textContent = e.message; }
          }
          cs.hidden = !cs.hidden;
        });
        d.addEventListener("dblclick", () => { ed.setRangeText(n, ed.selectionStart, ed.selectionEnd, "end"); ed.focus(); });
        lista.append(d, cs);
      });
    }
    filtroT.addEventListener("input", listar);
    listar();

    // consultas salvas
    const sel = $("#salvas");
    let salvas = [];
    async function carregarSalvas() {
      salvas = (await api("/api/consultas")).consultas;
      sel.replaceChildren();
      const o = document.createElement("option"); o.value = ""; o.textContent = "Abrir consulta salva…"; sel.appendChild(o);
      salvas.forEach((c) => { const x = document.createElement("option"); x.value = c.id; x.textContent = c.nome + (c.compartilhada ? " (compartilhada)" : ""); sel.appendChild(x); });
      if (atualId) sel.value = atualId;
    }
    sel.addEventListener("change", () => {
      const c = salvas.find((x) => String(x.id) === sel.value);
      if (!c) return;
      atualId = c.id;
      ed.value = c.sql; $("#nome").value = c.nome; $("#descricao").value = c.descricao || ""; $("#compartilhar").checked = !!c.compartilhada;
      if (c.grafico) {
        try { const g = JSON.parse(c.grafico); $("#g-tipo").value = g.tipo; $("#g-x").dataset.pend = g.x; } catch (e) { /* */ }
      }
      executar().then(() => {
        try { const g = JSON.parse(c.grafico || "{}"); if (g.x) { $("#g-x").value = g.x; $("#g-y").value = g.y || ""; redesenhar(); } } catch (e) { /* */ }
      });
    });
    $("#salvar").addEventListener("click", async () => {
      try {
        const r = await api("/api/consultas", { json: { id: atualId, nome: $("#nome").value, descricao: $("#descricao").value, sql: ed.value,
          compartilhada: $("#compartilhar").checked, grafico: JSON.stringify(cfgGrafico()) } });
        atualId = r.id;
        await carregarSalvas();
        aviso(raiz, "Consulta salva.", "atencao");
      } catch (e) { aviso(raiz, e.message); }
    });
    $("#nova").addEventListener("click", () => { atualId = null; sel.value = ""; ed.value = ""; $("#nome").value = ""; $("#descricao").value = ""; $("#compartilhar").checked = false; ed.focus(); });
    $("#excluir").addEventListener("click", async () => {
      if (!atualId) return;
      if (!window.confirm("Excluir esta consulta salva?")) return;
      try { await api(`/api/consultas/${atualId}/excluir`, { json: {} }); atualId = null; $("#nova").click(); await carregarSalvas(); }
      catch (e) { aviso(raiz, e.message); }
    });
    carregarSalvas().catch((e) => aviso(raiz, e.message));
    // SQL vindo de um relatório do ReportBuilder
    try {
      const pend = JSON.parse(sessionStorage.getItem("sql_pendente") || "null");
      if (pend) {
        sessionStorage.removeItem("sql_pendente");
        ed.value = pend.sql;
        $("#nome").value = pend.nome || "";
        valoresParams = pend.valores || {};
        atualizarParams();
      }
    } catch (e) { /* */ }
    ed.addEventListener("change", atualizarParams);
    sel.addEventListener("change", () => setTimeout(atualizarParams, 0));
  }

  /* =============================================================== ADMIN */
  /* seletor com grupos (pastas / grupos de tipos): marca o grupo inteiro ou itens soltos */
  function seletor(box, grupos, rotuloGrupo) {
    // grupos: [{chave, nome, itens: [{chave, nome, extra}]}]
    const sel = { grupos: new Set(), itens: new Set() };
    const busca = $("input[type=search]", box), conta = $(".picker-barra .nota", box), lista = $(".picker", box);
    function contar() {
      const n = sel.itens.size + grupos.filter((gr) => sel.grupos.has(gr.chave)).reduce((a, gr) => a + gr.itens.length, 0);
      conta.textContent = `${n} marcado(s)`;
    }
    function render() {
      const q = busca.value.trim().toLowerCase();
      lista.replaceChildren();
      grupos.forEach((gr) => {
        const itens = gr.itens.filter((it) => !q || it.nome.toLowerCase().includes(q) || it.chave.toLowerCase().includes(q) || gr.nome.toLowerCase().includes(q));
        if (!itens.length) return;
        const det = el("details", "picker-grupo");
        det.open = !!q || grupos.length === 1;
        const sum = el("summary");
        const cg = el("input"); cg.type = "checkbox"; cg.checked = sel.grupos.has(gr.chave);
        cg.title = rotuloGrupo;
        cg.onclick = (e) => e.stopPropagation();
        cg.onchange = () => { if (cg.checked) sel.grupos.add(gr.chave); else sel.grupos.delete(gr.chave); render(); };
        const parcial = gr.itens.filter((it) => sel.itens.has(it.chave)).length;
        sum.append(cg, el("span", "", ` ${gr.nome} `), el("span", "tag", parcial && !cg.checked ? `${parcial}/${gr.itens.length}` : String(gr.itens.length)));
        det.appendChild(sum);
        itens.forEach((it) => {
          const l = el("label", "check picker-item");
          const c = el("input"); c.type = "checkbox";
          c.checked = cg.checked || sel.itens.has(it.chave); c.disabled = cg.checked;
          c.onchange = () => { if (c.checked) sel.itens.add(it.chave); else sel.itens.delete(it.chave); contar(); };
          l.append(c, el("span", "", it.nome));
          if (it.extra) l.appendChild(el("span", "tag", it.extra));
          det.appendChild(l);
        });
        lista.appendChild(det);
      });
      if (!lista.children.length) lista.appendChild(el("p", "nota", "Nada encontrado."));
      contar();
    }
    busca.oninput = render;
    render();
    return {
      definir(gs, its) { sel.grupos = new Set(gs || []); sel.itens = new Set(its || []); busca.value = ""; render(); },
      valor: () => ({ grupos: [...sel.grupos], itens: [...sel.itens] }),
    };
  }

  async function telaAdmin() {
    const raiz = $(".conteudo");
    const form = $("#form-usuario");
    let modulos = {};
    let selRel = null, selTipos = null;
    const modo = (nome) => (form.querySelector(`input[name=${nome}]:checked`) || {}).value;
    let listaBancos = [];
    let empresaSite = null;
    ["rel_modo", "tipos_modo", "bancos_modo"].forEach((n) => $$(`input[name=${n}]`, form).forEach((r) => r.addEventListener("change", () => {
      $(".picker-box", r.closest(".perm")).hidden = modo(n) !== "escolher";
    })));
    try {
      const cat = await api("/api/admin/catalogo");
      const porPasta = new Map();
      cat.relatorios.forEach((r) => {
        if (!porPasta.has(r.pasta)) porPasta.set(r.pasta, []);
        porPasta.get(r.pasta).push({ chave: r.chave, nome: r.nome, extra: (r.antigo ? "antigo · " : "") + ({ movimentos: "Movimentos", estoque: "Estoque", financeiro: "Financeiro", cadastros: "Cadastros", relatorios: "Relatórios" }[r.modulo] || r.modulo) });
      });
      const ordemP = [...porPasta.keys()].sort((a, b) => (a === "Relatórios prontos" ? -2 : a === "Consultas salvas" ? -1 : 0) -
        (b === "Relatórios prontos" ? -2 : b === "Consultas salvas" ? -1 : 0) || a.localeCompare(b, "pt-BR"));
      selRel = seletor($("#perm-rel"), ordemP.map((p) => ({ chave: p, nome: p, itens: porPasta.get(p) })), "Liberar a pasta inteira");
      const porGrupo = new Map();
      cat.tipos.forEach((t) => {
        const gk = t.cod.split(".").slice(0, 2).join(".");
        if (!porGrupo.has(gk)) porGrupo.set(gk, []);
        porGrupo.get(gk).push({ chave: t.cod, nome: `${t.cod} - ${t.nome}` });
      });
      selTipos = seletor($("#perm-tipos"), [...porGrupo.keys()].sort().map((k) => ({ chave: k + ".*", nome: `Grupo ${k}`, itens: porGrupo.get(k) })), "Liberar o grupo inteiro");
      listaBancos = cat.bancos || [];
      if (cat.site && listaBancos.length > 1) {
        // TP DASH online (Tecnoplan): o usuário novo é cadastrado na empresa escolhida aqui, não na empresa em uso
        empresaSite = cat.empresa_id;
        const p = $("#perm-bancos");
        p.hidden = false;
        p.replaceChildren(el("div", "perm-tit", "Empresa do usuário"));
        const s = document.createElement("select"); s.name = "empresa_site"; s.className = "campo";
        listaBancos.forEach((b) => { const o = el("option", "", b.nome); o.value = b.id; s.append(o); });
        const n = el("p", "nota", "");
        n.style.margin = "6px 0 0";
        const avisoEmp = () => {
          const outra = s.value !== empresaSite;
          n.textContent = outra ? "O usuário será cadastrado na empresa escolhida. Relatórios e tipos de movimento ficam como \"todos\"; ajuste depois entrando na empresa dele."
            : "O usuário será cadastrado nesta empresa.";
          $("#perm-rel").hidden = outra; $("#perm-tipos").hidden = outra;
        };
        s.addEventListener("change", avisoEmp);
        p.append(s, n);
        avisoEmp();
        listaBancos = [];                      // no site, a empresa é única por usuário (não há "todas as empresas")
      } else if (listaBancos.length > 1) {
        $("#perm-bancos").hidden = false;
        const box = $("#perm-bancos .lista-bancos");
        listaBancos.forEach((b) => {
          const l = el("label", "check");
          const c = document.createElement("input"); c.type = "checkbox"; c.name = "bancos"; c.value = b.id;
          l.append(c, " " + b.nome); box.appendChild(l);
        });
        $("#rel-empresa").textContent = `· relatórios do ReportBuilder da empresa em uso (${cat.empresa}); para escolher os de outra empresa, troque a empresa no topo. As escolhas das outras empresas são mantidas.`;
      }
    } catch (e) { aviso(raiz, "Não foi possível carregar a lista de relatórios/tipos: " + e.message); }
    async function carregar() {
      const d = await api("/api/usuarios");
      modulos = d.modulos;
      const boxes = $("#modulos");
      if (!boxes.children.length) {
        Object.entries(modulos).forEach(([k, v]) => {
          const l = document.createElement("label"); l.className = "check";
          const c = document.createElement("input"); c.type = "checkbox"; c.name = "modulos"; c.value = k;
          l.append(c, v); boxes.appendChild(l);
        });
      }
      const t = new Tabela($("#tabela-usuarios"), {
        ocultar: ["id", "trocar_senha"],
        rotulos: { relatorios: "Relatórios", tipos_mov: "Tipos mov.", bancos: "Empresas" },
        onClick: (r, cols) => editar(Object.fromEntries(cols.map((c, i) => [c, r[i]]))),
      });
      const cols = ["id", "login", "nome", "admin", "modulos", ...(listaBancos.length > 1 ? ["bancos"] : []), "relatorios", "tipos_mov", "ativo", "trocar_senha", "ultimo_acesso"];
      const nomeBanco = (id) => (listaBancos.find((b) => b.id === id) || { nome: id }).nome;
      t.definir({ colunas: cols, linhas: d.usuarios.map((u) => cols.map((c) =>
        c === "admin" ? (u.admin ? "Sim" : "Não") : c === "ativo" ? (u.ativo ? "Ativo" : "Inativo") :
        c === "modulos" ? u.modulos.map((m) => modulos[m]).join(", ") :
        c === "relatorios" ? (u.relatorios ? `${u.relatorios.pastas.length} pasta(s), ${u.relatorios.ids.length} relatório(s)` : "Todos") :
        c === "tipos_mov" ? (u.tipos_mov.length ? u.tipos_mov.join(", ") : "Todos") :
        c === "bancos" ? (u.bancos ? u.bancos.map(nomeBanco).join(", ") : "Todas") : u[c])) }, false);
      t.dadosOriginais = d.usuarios;
      t.op.onClick = (r) => editar(d.usuarios.find((u) => u.id === r[0]));
      new Tabela($("#tabela-acessos")).definir({ colunas: ["quando", "usuario", "acao", "detalhe"],
        linhas: d.acessos.map((a) => [a.quando, a.usuario, a.acao, a.detalhe]) }, false);
    }
    function editar(u) {
      form.reset();
      form.elements.id.value = u ? u.id : "";
      form.elements.login.value = u ? u.login : "";
      form.elements.nome.value = u ? u.nome : "";
      form.elements.admin.checked = !!(u && u.admin);
      form.elements.ativo.checked = !u || !!u.ativo;
      $$("input[name=modulos]", form).forEach((c) => (c.checked = !!(u && u.modulos.includes(c.value))));
      if (empresaSite) {
        const s = form.elements.empresa_site;
        s.value = empresaSite; s.disabled = !!u;          // usuário já cadastrado: muda de empresa no TP DASH ADMIN
        s.dispatchEvent(new Event("change"));
      }
      const bs = u && u.bancos;
      const rb = form.querySelector(`input[name=bancos_modo][value=${bs ? "escolher" : "todos"}]`);
      if (rb) rb.checked = true;
      if ($("#perm-bancos .picker-box")) $("#perm-bancos .picker-box").hidden = !bs;
      $$("input[name=bancos]", form).forEach((c) => (c.checked = !!(bs && bs.includes(c.value))));
      const rel = u && u.relatorios, tip = (u && u.tipos_mov) || [];
      form.querySelector(`input[name=rel_modo][value=${rel ? "escolher" : "todos"}]`).checked = true;
      form.querySelector(`input[name=tipos_modo][value=${tip.length ? "escolher" : "todos"}]`).checked = true;
      $("#perm-rel .picker-box").hidden = !rel;
      $("#perm-tipos .picker-box").hidden = !tip.length;
      if (selRel) selRel.definir(rel ? rel.pastas : [], rel ? rel.ids : []);
      if (selTipos) selTipos.definir(tip.filter((x) => x.endsWith("*")), tip.filter((x) => !x.endsWith("*")));
      $("#titulo-form").textContent = u ? `Editar ${u.login}` : "Novo usuário";
      form.elements.senha.placeholder = u ? "Deixe vazio para manter a senha" : "Senha inicial";
      form.scrollIntoView({ behavior: "smooth" });
    }
    $("#novo-usuario").addEventListener("click", () => editar(null));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const dados = {
        id: form.elements.id.value ? +form.elements.id.value : null,
        login: form.elements.login.value, nome: form.elements.nome.value, senha: form.elements.senha.value,
        admin: form.elements.admin.checked, ativo: form.elements.ativo.checked,
        modulos: $$("input[name=modulos]:checked", form).map((c) => c.value),
        relatorios: modo("rel_modo") === "escolher" && selRel ? { pastas: selRel.valor().grupos, ids: selRel.valor().itens } : null,
        tipos_mov: modo("tipos_modo") === "escolher" && selTipos ? [...selTipos.valor().grupos, ...selTipos.valor().itens] : [],
        bancos: listaBancos.length > 1 && modo("bancos_modo") === "escolher" ? $$("input[name=bancos]:checked", form).map((c) => c.value) : null,
      };
      if (empresaSite && !dados.id) dados.empresa = form.elements.empresa_site.value;
      if (dados.bancos && !dados.bancos.length && !dados.admin) { aviso(raiz, "Marque pelo menos uma empresa ou escolha \"Todas as empresas\"."); return; }
      if (modo("tipos_modo") === "escolher" && !dados.tipos_mov.length) { aviso(raiz, "Marque pelo menos um tipo de movimento ou escolha \"Todos os tipos\"."); return; }
      try {
        const r = await api("/api/usuarios", { json: dados });
        aviso(raiz, r.nome_empresa ? `Usuário salvo na empresa ${r.nome_empresa}.` : "Usuário salvo.", "atencao");
        editar(null); await carregar();
      }
      catch (err) { aviso(raiz, err.message); }
    });
    const st = $("#rb-teste-status");
    async function statusRB() {
      try {
        const d = await api("/api/rb");
        const t = d.teste || {};
        if (!t.total) { st.textContent = `${d.relatorios.length} relatórios importados. Ainda não testados.`; return; }
        st.textContent = t.andamento ? `Testando… ${t.feitos} de ${t.total}` : `Último teste (${t.inicio}): ${t.total} relatórios, ${t.com_erro || 0} com erro. Os com erro aparecem marcados em Relatórios.`;
        if (t.andamento) setTimeout(statusRB, 4000);
      } catch (e) { st.textContent = e.message; }
    }
    $("#rb-testar").addEventListener("click", async () => {
      try { await api("/api/rb/testar", { json: {} }); statusRB(); } catch (e) { aviso(raiz, e.message); }
    });
    statusRB();
    const ss = $("#rb-sync-status");
    async function statusSync(depois) {
      try {
        const d = await api("/api/rb/sync");
        const e = d.estado || {}, r = e.resultado || {};
        ss.replaceChildren();
        const linha = (t, cls) => ss.appendChild(el("div", cls || "", t));
        linha(`${d.varios ? `Empresa ${d.empresa}: ` : ""}${d.total} relatórios no painel · verificação automática ${d.automatico ? `a cada ${d.automatico} min` : "desligada (config.ini)"}`);
        if (e.andamento) linha(`Sincronizando… (iniciado ${e.inicio})`);
        else if (e.ultima) linha(`Última verificação: ${e.ultima}` + (r.total !== undefined ? ` · ${r.novos} novo(s), ${r.alterados} alterado(s), ${r.removidos} removido(s) em ${r.segundos}s` : ""));
        else linha("Ainda não sincronizado com o banco.");
        if (e.ultima_mudanca && e.resultado_mudanca) {
          const m = e.resultado_mudanca;
          linha(`Última mudança encontrada: ${e.ultima_mudanca}` + ([...(m.nomes_novos || []).map((n) => "novo: " + n), ...(m.nomes_alterados || []).map((n) => "alterado: " + n)].slice(0, 8).length
            ? " — " + [...(m.nomes_novos || []).map((n) => "novo: " + n), ...(m.nomes_alterados || []).map((n) => "alterado: " + n)].slice(0, 8).join("; ") : ""), "nota");
        }
        if (e.erro) linha("Erro: " + e.erro, "aviso erro");
        if (r.erros && r.erros.length) linha(`${r.erros.length} relatório(s) não puderam ser lidos: ${r.erros.slice(0, 5).join("; ")}`, "aviso atencao");
        if (e.andamento || depois) setTimeout(() => statusSync(e.andamento ? false : 0), 3000);
      } catch (err) { ss.textContent = err.message; }
    }
    [["#rb-sync", false], ["#rb-sync-tudo", true]].forEach(([s, forcar]) => $(s).addEventListener("click", async () => {
      try { await api("/api/rb/sync", { json: { forcar } }); statusSync(true); } catch (e) { aviso(raiz, e.message); }
    }));
    statusSync();
    try {
      await carregar();
      const s = await api("/api/status");
      $("#status-banco").textContent = s.banco;
      const sg = s.seguranca || {};
      const box = el("div", "aviso " + (sg.https ? "atencao" : "erro"));
      box.style.marginTop = "8px";
      box.textContent = sg.https
        ? `Conexão criptografada (HTTPS) ativa. Certificado SHA-256: ${sg.certificado_sha256 || "-"}. Celulares: abra /certificado.cer para instalar.` +
          (sg.ip_restrito ? " Acesso limitado aos IPs de [servidor] permitir." : "")
        : "";
      $("#status-banco").closest(".aviso").after(box);
      if (sg.enderecos && sg.enderecos.length) {
        const rede = el("div", "aviso");
        rede.style.marginTop = "8px";
        const est = sg.nome_local
          ? (sg.nome_local_ativo ? `Nome na rede ${sg.nome_local}: anunciando.` : `Nome na rede ${sg.nome_local}: não está anunciando (${sg.nome_local_erro || "iniciando"}).`)
          : "Nome na rede desativado ([servidor] nome_local).";
        rede.textContent = `Endereços deste servidor: ${sg.enderecos.join("  |  ")}. ${est}` +
          (sg.certificado_nomes && sg.certificado_nomes.length ? ` Certificado aceita: ${sg.certificado_nomes.join(", ")}.` : "");
        box.after(rede);
      }
    } catch (e) { aviso(raiz, e.message); $("#status-banco").textContent = e.message; }
  }

  /* =============================================================== geral */
  function tema() {
    const salvo = (() => { try { return localStorage.getItem("tema"); } catch (e) { return null; } })();
    if (salvo) document.documentElement.dataset.tema = salvo;
    const b = $("#tema");
    if (b) b.addEventListener("click", () => {
      const escuro = getComputedStyle(document.documentElement).colorScheme === "dark";
      const novo = escuro ? "claro" : "escuro";
      document.documentElement.dataset.tema = novo;
      try { localStorage.setItem("tema", novo); } catch (e) { /* */ }
      window.dispatchEvent(new Event("resize"));
    });
    const m = $("#menu");
    const nm = $("#nav-menu");
    if (nm) nm.addEventListener("click", (e) => { e.stopPropagation(); $(".lateral").classList.toggle("aberta"); });
    seletorPeriodo();
    const rc = $("#recarregar");
    if (rc) rc.addEventListener("click", () => location.reload());
    const tb = $("#troca-banco");
    if (tb) {
      const antes = tb.value;
      tb.addEventListener("change", async () => {
        tb.disabled = true;
        try {
          await api("/api/banco", { json: { id: tb.value } });
          location.reload();          // recarrega a tela com os dados da outra empresa
        } catch (e) {
          tb.value = antes; tb.disabled = false;
          aviso($(".conteudo"), e.message);
        }
      });
    }
    if (m) {
      m.addEventListener("click", (e) => { e.stopPropagation(); $(".lateral").classList.toggle("aberta"); });
      // no celular: toque fora do menu ou em um item fecha o menu
      document.addEventListener("click", (e) => {
        const lat = $(".lateral");
        if (lat.classList.contains("aberta") && (!lat.contains(e.target) || e.target.closest("a"))) lat.classList.remove("aberta");
      });
    }
  }

  /* ---------------------------------------------------------- instalar como app (PC e celular) */
  function botaoInstalar() {
    const b = $("#btn-instalar");
    if (!b) return;
    const pi = window.PainelInstalar || {};
    b.hidden = !!window.PainelApp || !!pi.instalado;
    b.classList.toggle("primario", !!(pi.disponivel && pi.disponivel()));
    b.onclick = abrirInstalar;
    document.addEventListener("painel-instalacao", () => {
      b.hidden = !!window.PainelApp || !!pi.instalado;
      b.classList.toggle("primario", !!(pi.disponivel && pi.disponivel()));
    });
  }

  function abrirInstalar() {
    const pi = window.PainelInstalar || {};
    const ua = navigator.userAgent;
    const edge = /Edg\//.test(ua), chrome = /Chrome\//.test(ua) && !edge, firefox = /Firefox\//.test(ua);
    const celular = window.matchMedia("(max-width: 900px)").matches;
    const fundo = el("div", "modal-fundo");
    const modal = el("div", "modal instalar-modal");
    const cab = el("div", "modal-cab");
    cab.appendChild(el("h2", "", "Instalar o TP DASH como aplicativo"));
    const fechar = el("button", "btn pequeno", "Fechar ✕");
    cab.appendChild(fechar);
    const corpo = el("div", "modal-corpo");
    modal.append(cab, corpo);
    fundo.appendChild(modal);
    document.body.appendChild(fundo);
    const sair = () => fundo.remove();
    fechar.onclick = sair;
    fundo.addEventListener("click", (e) => { if (e.target === fundo) sair(); });

    // opção 1: pelo navegador (PWA)
    const o1 = el("section", "ed-secao");
    o1.appendChild(el("h3", "", "1. Instalar pelo navegador (recomendado)"));
    o1.appendChild(el("p", "nota", "Cria o ícone \"TP DASH\" na Área de Trabalho e no Menu Iniciar. Abre em janela própria, sem barra de endereço, como um programa do Windows. Atualiza sozinho junto com o painel."));
    if (pi.disponivel && pi.disponivel()) {
      const b = el("button", "btn primario", "Instalar agora");
      b.onclick = async () => { const ok = await pi.instalar(); if (ok) sair(); };
      o1.appendChild(b);
    } else if (pi.swFalhou && location.protocol === "https:") {
      o1.appendChild(el("div", "aviso atencao", "Este computador ainda não confia no certificado do painel, por isso o navegador não oferece a instalação. Use a opção 2 (ela instala o certificado) ou peça ao responsável para rodar o criar_atalho.bat neste computador."));
    } else {
      const passos = el("div", "nota");
      passos.style.fontSize = "13px";
      let txt;
      if (celular) txt = "No celular: Chrome (Android) → menu ⋮ → Instalar app. iPhone: Safari → Compartilhar → Adicionar à Tela de Início.";
      else if (edge) txt = "No Edge: menu ··· (canto superior direito) → Aplicativos → Instalar este site como um aplicativo → Instalar.";
      else if (chrome) txt = "No Chrome: clique no ícone de instalar na barra de endereço (monitor com seta, à direita) ou menu ⋮ → Transmitir, salvar e compartilhar → Instalar página como app.";
      else if (firefox) txt = "O Firefox não instala sites como aplicativo. Use o Edge ou o Chrome, ou a opção 2 abaixo.";
      else txt = "Abra o painel no Edge ou no Chrome e use a opção de instalar do navegador, ou a opção 2 abaixo.";
      passos.textContent = txt;
      o1.appendChild(passos);
    }
    corpo.appendChild(o1);

    // celular: QR para abrir a página de instalação
    if (!celular) {
      const o3 = el("section", "ed-secao");
      o3.appendChild(el("h3", "", "No celular"));
      const linha = el("div", "qr-linha");
      const img = el("img", "qr"); img.src = "/qr.svg"; img.width = 150; img.height = 150; img.alt = "QR Code da página de instalação";
      const txt = el("div", "nota");
      txt.textContent = "Aponte a câmera do celular para o código (na rede da empresa). Abre a página com o passo a passo para instalar no Android ou iPhone: ";
      const l = el("a", "", location.origin + "/instalar"); l.href = "/instalar"; l.target = "_blank";
      txt.appendChild(l);
      linha.append(img, txt);
      o3.appendChild(linha);
      corpo.appendChild(o3);
    }

    // opção 2: programa para Windows (TPDash.exe)
    if (!celular) {
      const o2 = el("section", "ed-secao");
      o2.appendChild(el("h3", "", "2. Baixar o app para Windows"));
      o2.appendChild(el("p", "nota", "Pacote com o TPDash.exe já configurado para este servidor (e o certificado de segurança). Extraia o .zip numa pasta (ex.: C:\\TPDash) e rode criar_atalho.bat: ele instala o certificado e cria o atalho na Área de Trabalho e no Menu Iniciar. Funciona mesmo se o navegador não oferecer a instalação."));
      const b2 = el("button", "btn", "Baixar app para Windows (.zip)");
      b2.onclick = () => baixar("/app-windows.zip").catch((e) => aviso(corpo, e.message));
      o2.appendChild(b2);
      corpo.appendChild(o2);
    }
  }

  /* celular: filtros recolhidos atrás de um botão, para os gráficos aparecerem logo */
  function filtrosCelular() {
    if (!window.matchMedia("(max-width: 760px)").matches) return;
    $$("form.filtros").forEach((f) => {
      if (f.dataset.celular || f.closest(".gaveta")) return;
      f.dataset.celular = "1";
      const b = el("button", "btn filtros-toggle", "Filtros ▾");
      b.type = "button";
      f.before(b);
      f.classList.add("recolhido");
      b.onclick = () => { const r = f.classList.toggle("recolhido"); b.textContent = r ? "Filtros ▾" : "Esconder filtros ▴"; };
      f.addEventListener("submit", () => { f.classList.add("recolhido"); b.textContent = "Filtros ▾"; });
    });
  }


  document.addEventListener("DOMContentLoaded", () => {
    filtrosCelular();
    botaoInstalar();
    tema();
    const telas = { inicio: telaInicio, movimentos: telaMovimentos, movimentacoes: telaMovimentacoes, estoque: telaEstoque, financeiro: telaFinanceiro,
      cadastros: telaCadastros, frotas: telaFrotas, relatorios: telaRelatorios, sql: telaSQL, admin: telaAdmin };
    const t = telas[document.body.dataset.pagina];
    if (t) t().catch((e) => aviso($(".conteudo"), e.message));
  });
})();
