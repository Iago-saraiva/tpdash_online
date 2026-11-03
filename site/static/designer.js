/* TP DASH - editor de layout de impressão no estilo ReportBuilder
   Bandas (título, cabeçalho, grupos, detalhe, sumário, rodapé), itens posicionados em milímetros,
   arrastar/redimensionar, propriedades, sub-relatórios, pré-visualização em PDF. */
(function () {
  "use strict";

  const PX_MM = 96 / 25.4;              // pixels por mm com zoom 100%
  const PT_MM = 25.4 / 72;              // mm por ponto (tamanho de fonte)
  const PAPEIS = { A4: [210, 297], Carta: [215.9, 279.4], "Ofício": [215.9, 355.6], A5: [148, 210], A3: [297, 420] };
  const FORMATOS = ["", "#,0.00;-#,0.00", "#,0.00", "$#,0.00;($#,0.00)", "0", "000000", "0.00 %", "dd/mm/yyyy", "dd/mm/yy", "mm/yyyy", "dd/mm/yyyy hh:nn", "hh:nn"];
  const SISTEMA = { data: "Data", hora: "Hora", datahora: "Data e hora", pagina: "Nº da página", paginas: "Total de páginas", pagina_desc: "Página N", pagina_de: "N de T", pagina_x_de_y: "Página N de T" };
  const CALCS = { soma: "Soma", contagem: "Contagem", media: "Média", maximo: "Máximo", minimo: "Mínimo" };
  const NOMES_BANDA = { titulo: "Título", cabecalho: "Cabeçalho (toda página)", detalhe: "Detalhe", sumario: "Sumário (final)", rodape: "Rodapé (toda página)" };
  const FONTES = ["Arial", "Times New Roman", "Courier New"];

  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt !== undefined) e.textContent = txt;
    return e;
  }
  const clone = (o) => JSON.parse(JSON.stringify(o, (k, v) => (k === "_k" ? undefined : v)));
  const r1 = (v) => Math.round(v * 10) / 10;
  let seq = 0;

  function abrir(op) {
    const { rid, nome, api, baixar } = op;
    const raiz = el("div", "dz");
    raiz.setAttribute("role", "dialog");
    raiz.setAttribute("aria-label", "Editor de layout de impressão");
    document.body.appendChild(raiz);
    document.body.classList.add("dz-aberto");
    raiz.append(el("div", "dz-carregando", "Carregando o layout…"));

    let info = null, d = null, pilha = [], selecao = [], bandaSel = null, zoom = 1, pendente = null;
    let desfazer = [], refazer = [], sujo = false, copia = null, snap = 0.5;

    function sair() {
      if (sujo && !confirm("Há alterações não salvas. Sair mesmo assim?")) return;
      document.removeEventListener("keydown", teclas, true);
      document.body.classList.remove("dz-aberto");
      raiz.remove();
      if (op.aoFechar) op.aoFechar();
    }

    async function carregar(base) {
      try {
        info = await api(`/api/rb/${encodeURIComponent(rid)}/desenho/abrir`, { json: { valores: op.valores || {}, base } });
      } catch (e) {
        raiz.replaceChildren(el("div", "dz-carregando", "Não foi possível abrir: " + e.message));
        const b = el("button", "btn", "Fechar"); b.onclick = sair; raiz.firstChild.appendChild(b);
        return;
      }
      d = info.desenho;
      chaves(d.relatorio);
      pilha = [d.relatorio]; selecao = []; bandaSel = null; desfazer = []; refazer = [];
      sujo = !!base;
      montar();
      ajustarZoom();
    }

    function chaves(sec) {
      todasBandas(sec).forEach((b) => b.itens.forEach((i) => { i._k = ++seq; if (i.tipo === "sub" && i.secao) chaves(i.secao); }));
    }
    function todasBandas(sec) {
      const r = [];
      ["titulo", "cabecalho", "detalhe", "sumario", "rodape"].forEach((t) => { if (sec.bandas[t]) r.push(sec.bandas[t]); });
      (sec.grupos || []).forEach((g) => { r.push(g.cab, g.rod); });
      return r;
    }
    const secao = () => pilha[pilha.length - 1];
    const largUtil = () => d.pagina.largura - d.pagina.margens.esq - d.pagina.margens.dir;
    const esc = () => PX_MM * zoom;

    function guardar() {
      desfazer.push(JSON.stringify(d));
      if (desfazer.length > 60) desfazer.shift();
      refazer = [];
      sujo = true;
    }
    function restaurarDe(json) {
      d = JSON.parse(json);
      chaves(d.relatorio);
      pilha = [d.relatorio];          // volta para o relatório principal
      selecao = []; bandaSel = null;
      sujo = true;
      painelEsq();
      desenhar();
    }

    // ------------------------------------------------------------------ estrutura da tela
    let eTopo, eEsq, eCentro, eDir, ePagina, eAbas;
    function montar() {
      raiz.replaceChildren();
      eTopo = el("div", "dz-topo");
      const tit = el("div", "dz-tit");
      tit.append(el("strong", "", "Layout de impressão"), el("span", "", nome));
      const origem = { salvo: "layout salvo no painel", reportbuilder: "original do ReportBuilder", padrao: "layout padrão (tabela)" }[info.origem] || "";
      tit.append(el("small", "", origem));
      eTopo.appendChild(tit);
      const bt = (txt, fn, cls, title) => { const b = el("button", "btn pequeno " + (cls || ""), txt); b.type = "button"; if (title) b.title = title; b.onclick = fn; eTopo.appendChild(b); return b; };
      const salvar = bt("Salvar", acaoSalvar, "primario", "Salva o layout para todos os usuários (o PDF passa a sair assim)");
      salvar.disabled = !info.pode_editar;
      bt("Visualizar PDF", acaoPDF, "", "Gera o PDF com este layout e os filtros atuais (sem salvar)");
      bt("↶", () => { if (desfazer.length) { refazer.push(JSON.stringify(d)); restaurarDe(desfazer.pop()); } }, "", "Desfazer (Ctrl+Z)");
      bt("↷", () => { if (refazer.length) { desfazer.push(JSON.stringify(d)); restaurarDe(refazer.pop()); } }, "", "Refazer (Ctrl+Y)");
      const mais = el("select", "dz-sel");
      mais.innerHTML = "<option value=''>Mais…</option>" +
        (info.tem_original ? "<option value='original'>Recomeçar do original do ReportBuilder</option>" : "") +
        "<option value='padrao'>Recomeçar com layout em tabela</option>" +
        (info.tem_salvo && info.pode_editar ? "<option value='excluir'>Apagar o layout salvo (voltar ao " + (info.tem_original ? "original do RB" : "PDF em tabela") + ")</option>" : "");
      mais.onchange = async () => {
        const v = mais.value; mais.value = "";
        if (!v) return;
        if (v === "excluir") {
          if (!confirm("Apagar o layout salvo deste relatório?")) return;
          try { await api(`/api/rb/${encodeURIComponent(rid)}/desenho/excluir`, { json: {} }); sujo = false; carregar(); } catch (e) { alerta(e.message); }
          return;
        }
        if (sujo && !confirm("Descartar as alterações atuais?")) return;
        carregar(v);
      };
      eTopo.appendChild(mais);
      const z = el("div", "dz-zoom");
      const zm = el("button", "btn pequeno", "−"), zp = el("button", "btn pequeno", "+"), zt = el("span", "", "");
      zm.onclick = () => { zoom = Math.max(0.4, zoom - 0.1); desenhar(); };
      zp.onclick = () => { zoom = Math.min(3, zoom + 0.1); desenhar(); };
      z.append(zm, zt, zp);
      eTopo.appendChild(z);
      eTopo._zoom = zt;
      bt("Fechar ✕", sair);
      const corpo = el("div", "dz-corpo");
      eEsq = el("div", "dz-esq");
      eCentro = el("div", "dz-centro");
      eDir = el("div", "dz-dir");
      corpo.append(eEsq, eCentro, eDir);
      raiz.append(eTopo, corpo);
      if (window.matchMedia("(max-width: 900px)").matches) {
        raiz.insertBefore(el("div", "dz-aviso", "O editor de layout funciona melhor no computador (tela grande e mouse)."), corpo);
      }
      painelEsq();
      desenhar();
    }

    function alerta(msg, tipo) {
      const a = el("div", "dz-msg " + (tipo || "erro"), msg);
      raiz.appendChild(a);
      setTimeout(() => a.remove(), 5000);
    }

    function ajustarZoom() {
      if (!eCentro) return;
      const disp = eCentro.clientWidth - 60;
      zoom = Math.max(0.5, Math.min(2, Math.floor((disp / (d.pagina.largura * PX_MM)) * 10) / 10));
      desenhar();
    }

    // ------------------------------------------------------------------ painel esquerdo: componentes e campos
    function painelEsq() {
      eEsq.replaceChildren();
      eEsq.appendChild(el("div", "dz-sec", "Componentes"));
      const comps = el("div", "dz-comps");
      [["texto", "Texto", "A"], ["campo", "Campo", "▭"], ["total", "Total", "Σ"], ["sistema", "Data / página", "#"],
        ["linha", "Linha", "—"], ["retangulo", "Retângulo", "□"], ["variavel", "Cálculo", "ƒ"], ["sub", "Sub-relatório", "⊞"]]
        .forEach(([t, rot, ic]) => {
          const b = el("button", "dz-comp"); b.type = "button";
          b.append(el("span", "ic", ic), el("span", "", rot));
          b.title = "Clique aqui e depois na banda onde quer colocar";
          b.onclick = () => { pendente = pendente === t ? null : t; marcarPendente(); };
          b.dataset.tipo = t;
          comps.appendChild(b);
        });
      eEsq.appendChild(comps);
      eEsq.appendChild(el("div", "dz-sec", "Campos"));
      eEsq.appendChild(el("p", "dz-nota", "Arraste um campo para uma banda."));
      const lista = el("div", "dz-campos");
      (info.visoes || []).forEach((v) => {
        const det = el("details"); det.open = v.nome === (secao().visao || "") || !v.mestre;
        const sm = el("summary", "", v.nome + (v.mestre ? " (detalhe de " + v.mestre + ")" : ""));
        det.appendChild(sm);
        (info.campos[v.nome] || []).forEach((c) => {
          const it = el("div", "dz-campo", c);
          it.draggable = true;
          it.ondragstart = (e) => { e.dataTransfer.setData("text/x-campo", JSON.stringify({ visao: v.nome, campo: c })); e.dataTransfer.effectAllowed = "copy"; };
          it.ondblclick = () => { if (bandaSel) novoItem("campo", bandaSel.banda, 2, 2, { campo: c, visao: v.nome }); };
          det.appendChild(it);
        });
        lista.appendChild(det);
      });
      eEsq.appendChild(lista);
    }
    function marcarPendente() {
      eEsq.querySelectorAll(".dz-comp").forEach((b) => b.classList.toggle("ativo", b.dataset.tipo === pendente));
      raiz.classList.toggle("dz-inserindo", !!pendente);
    }

    // ------------------------------------------------------------------ centro: página e bandas
    function listaBandas(sec) {
      const r = [];
      const b = sec.bandas;
      const principal = sec === d.relatorio;
      if (b.titulo) r.push({ banda: b.titulo, rot: NOMES_BANDA.titulo, tipo: "titulo" });
      if (b.cabecalho) r.push({ banda: b.cabecalho, rot: principal ? NOMES_BANDA.cabecalho : "Cabeçalho", tipo: "cabecalho" });
      (sec.grupos || []).forEach((g, i) => r.push({ banda: g.cab, rot: `Grupo ${i + 1}: ${g.campo || "?"} · cabeçalho`, tipo: "gcab", grupo: i }));
      r.push({ banda: b.detalhe, rot: NOMES_BANDA.detalhe + (sec.visao ? " · " + sec.visao : ""), tipo: "detalhe" });
      (sec.grupos || []).slice().reverse().forEach((g, k) => {
        const i = sec.grupos.length - 1 - k;
        r.push({ banda: g.rod, rot: `Grupo ${i + 1}: ${g.campo || "?"} · rodapé`, tipo: "grod", grupo: i });
      });
      if (b.sumario) r.push({ banda: b.sumario, rot: NOMES_BANDA.sumario, tipo: "sumario" });
      if (b.rodape && principal) r.push({ banda: b.rodape, rot: NOMES_BANDA.rodape, tipo: "rodape" });
      return r;
    }

    function desenhar() {
      if (!eCentro) return;
      eTopo._zoom.textContent = Math.round(zoom * 100) + "%";
      const rolagem = eCentro.scrollTop;
      eCentro.replaceChildren();
      eAbas = el("div", "dz-abas");
      pilha.forEach((s, i) => {
        const a = el("button", "dz-aba" + (i === pilha.length - 1 ? " ativa" : ""), i === 0 ? "Principal" : "Sub: " + (s.visao || "?"));
        a.type = "button";
        a.onclick = () => { pilha = pilha.slice(0, i + 1); selecao = []; bandaSel = null; desenhar(); };
        eAbas.appendChild(a);
      });
      eCentro.appendChild(eAbas);
      const s = esc();
      ePagina = el("div", "dz-pagina");
      ePagina.style.width = (largUtil() * s) + "px";
      const regua = el("div", "dz-regua");
      for (let mm = 0; mm <= largUtil(); mm += 10) {
        const t = el("span", "", mm % 50 === 0 ? String(mm / 10) : "");
        t.style.left = (mm * s) + "px";
        if (mm % 50 !== 0) t.classList.add("menor");
        regua.appendChild(t);
      }
      ePagina.appendChild(regua);
      listaBandas(secao()).forEach((lb) => ePagina.appendChild(bandaDOM(lb)));
      eCentro.appendChild(ePagina);
      eCentro.scrollTop = rolagem;
      painelDir();
    }

    function bandaDOM(lb) {
      const s = esc();
      const caixa = el("div", "dz-banda" + (bandaSel && bandaSel.banda === lb.banda ? " sel" : "") + (lb.banda.visivel === false ? " invisivel" : ""));
      const cab = el("div", "dz-banda-cab", lb.rot);
      cab.appendChild(el("span", "dz-banda-alt", r1(lb.banda.altura) + " mm"));
      cab.onclick = () => { bandaSel = lb; selecao = []; desenhar(); };
      const area = el("div", "dz-area");
      area.style.height = Math.max(lb.banda.altura * s, 2) + "px";
      area.style.backgroundSize = `${5 * s}px ${5 * s}px`;
      area._lb = lb;
      lb.banda.itens.forEach((it) => area.appendChild(itemDOM(it, lb)));
      area.addEventListener("pointerdown", (e) => {
        if (e.target !== area) return;
        const p = posMM(e, area);
        if (pendente) { novoItem(pendente, lb.banda, p.x, p.y); pendente = null; marcarPendente(); return; }
        bandaSel = lb; selecao = []; desenhar();
      });
      area.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/x-campo")) { e.preventDefault(); area.classList.add("alvo"); } });
      area.addEventListener("dragleave", () => area.classList.remove("alvo"));
      area.addEventListener("drop", (e) => {
        area.classList.remove("alvo");
        const raw = e.dataTransfer.getData("text/x-campo");
        if (!raw) return;
        e.preventDefault();
        const c = JSON.parse(raw), p = posMM(e, area);
        novoItem("campo", lb.banda, p.x, p.y, { campo: c.campo, visao: c.visao === secao().visao ? null : c.visao });
      });
      const al = el("div", "dz-banda-ajuste");
      al.title = "Arraste para mudar a altura da banda";
      al.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        al.setPointerCapture(e.pointerId);
        const y0 = e.clientY, h0 = lb.banda.altura;
        let mexeu = false;
        const mover = (ev) => {
          if (!mexeu) { guardar(); mexeu = true; }
          lb.banda.altura = Math.max(0, r1(h0 + (ev.clientY - y0) / esc()));
          area.style.height = Math.max(lb.banda.altura * esc(), 2) + "px";
          cab.lastChild.textContent = r1(lb.banda.altura) + " mm";
        };
        const soltar = () => { al.removeEventListener("pointermove", mover); al.removeEventListener("pointerup", soltar); if (mexeu) painelDir(); };
        al.addEventListener("pointermove", mover);
        al.addEventListener("pointerup", soltar);
      });
      caixa.append(cab, area, al);
      return caixa;
    }

    function posMM(e, area) {
      const r = area.getBoundingClientRect();
      const s = esc();
      return { x: Math.max(0, arred((e.clientX - r.left) / s)), y: Math.max(0, arred((e.clientY - r.top) / s)) };
    }
    const arred = (v) => (snap ? Math.round(v / snap) * snap : r1(v));

    function rotuloItem(it) {
      switch (it.tipo) {
        case "texto": return it.texto || "(texto)";
        case "campo": case "memo": {
          const outra = it.visao && (it.visao || "").toUpperCase() !== (secao().visao || "").toUpperCase();
          return (outra ? it.visao + "." : "") + (it.campo || "(campo)");
        }
        case "total": return (CALCS[it.calc] || "Soma") + "(" + (it.campo || "?") + ")";
        case "variavel": return "ƒ " + (it.nome || "cálculo");
        case "sistema": return { data: "dd/mm/aaaa", hora: "hh:mm", datahora: "dd/mm/aaaa hh:mm", pagina: "1", paginas: "9", pagina_desc: "Página 1", pagina_de: "1 de 9", pagina_x_de_y: "Página 1 de 9" }[it.sistema] || "";
        default: return "";
      }
    }
    function familia(n) {
      n = (n || "").toLowerCase();
      if (n.includes("courier") || n.includes("draft") || n.includes("console")) return "'Courier New', monospace";
      if (n.includes("times")) return "'Times New Roman', serif";
      return "Arial, Helvetica, sans-serif";
    }

    function itemDOM(it, lb) {
      const s = esc();
      const e = el("div", "dz-item t-" + it.tipo + (selecao.includes(it) ? " sel" : ""));
      e.style.left = it.x * s + "px"; e.style.top = it.y * s + "px";
      e.style.width = Math.max(it.w * s, 3) + "px"; e.style.height = Math.max(it.h * s, 3) + "px";
      e._it = it;
      if (it.tipo === "linha") {
        e.classList.add("pos-" + (it.posicao || "topo"));
        e.style.setProperty("--esp", Math.max((it.espessura || 0.75) * PT_MM * s, 1) + "px");
        e.style.setProperty("--cor", it.cor || "#000");
      } else if (it.tipo === "retangulo") {
        e.style.borderColor = it.cor || "#000";
        e.style.borderWidth = Math.max((it.espessura || 0.75) * PT_MM * s, 1) + "px";
        if (it.fundo) e.style.background = it.fundo;
        if (it.forma === "arredondado") e.style.borderRadius = Math.min(it.w, it.h) * 0.12 * s + "px";
        if (it.forma === "elipse") e.style.borderRadius = "50%";
      } else if (it.tipo === "sub") {
        e.append(el("strong", "", "Sub-relatório"), el("span", "", " " + ((it.secao || {}).visao || "")));
        e.title = "Duplo clique para editar o sub-relatório";
        e.ondblclick = (ev) => { ev.stopPropagation(); entrarSub(it); };
      } else {
        const f = it.fonte || {};
        e.textContent = rotuloItem(it);
        e.style.fontFamily = familia(f.nome);
        e.style.fontSize = Math.max((f.tam || 10) * PT_MM * s, 4) + "px";
        e.style.fontWeight = f.n ? "700" : "400";
        e.style.fontStyle = f.i ? "italic" : "normal";
        e.style.textDecoration = f.s ? "underline" : "none";
        e.style.color = f.cor || "#000";
        e.style.textAlign = { e: "left", c: "center", d: "right" }[it.alin || "e"];
        e.style.whiteSpace = it.quebra ? "pre-wrap" : "pre";
        if (it.fundo) e.style.background = it.fundo;
        if (it.auto) e.classList.add("auto");
      }
      e.addEventListener("pointerdown", (ev) => iniciarArraste(ev, it, lb, e));
      if (selecao.length === 1 && selecao[0] === it) {
        const h = el("div", "dz-alca");
        h.addEventListener("pointerdown", (ev) => iniciarRedim(ev, it, e));
        e.appendChild(h);
      }
      return e;
    }

    function entrarSub(it) {
      if (!it.secao) return;
      pilha.push(it.secao);
      selecao = []; bandaSel = null;
      painelEsq();
      desenhar();
    }

    // ------------------------------------------------------------------ arrastar / redimensionar
    function iniciarArraste(ev, it, lb, dom) {
      if (ev.button !== 0) return;
      ev.stopPropagation();
      if (pendente) { const area = dom.parentElement; const p = posMM(ev, area); novoItem(pendente, lb.banda, p.x, p.y); pendente = null; marcarPendente(); return; }
      if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
        selecao = selecao.includes(it) ? selecao.filter((x) => x !== it) : selecao.concat([it]);
        bandaSel = lb; desenhar(); return;
      }
      if (!selecao.includes(it)) { selecao = [it]; bandaSel = lb; desenhar(); dom = acharDOM(it); if (!dom) return; }
      const x0 = ev.clientX, y0 = ev.clientY;
      const orig = selecao.map((i) => ({ i, x: i.x, y: i.y }));
      let mexeu = false;
      const alvo = dom;
      alvo.setPointerCapture(ev.pointerId);
      const mover = (e) => {
        const dx = (e.clientX - x0) / esc(), dy = (e.clientY - y0) / esc();
        if (!mexeu && Math.abs(dx) + Math.abs(dy) < 0.6) return;
        if (!mexeu) { guardar(); mexeu = true; }
        orig.forEach((o) => {
          o.i.x = Math.max(-5, arred(o.x + dx)); o.i.y = arred(o.y + dy);
          const de = acharDOM(o.i);
          if (de) { de.style.left = o.i.x * esc() + "px"; de.style.top = o.i.y * esc() + "px"; }
        });
      };
      const soltar = (e) => {
        alvo.removeEventListener("pointermove", mover);
        alvo.removeEventListener("pointerup", soltar);
        if (!mexeu) return;
        // soltou fora da banda: passa para a banda que está embaixo do mouse
        if (selecao.length === 1) {
          const it1 = selecao[0];
          const debaixo = document.elementsFromPoint(e.clientX, e.clientY).find((x) => x.classList && x.classList.contains("dz-area"));
          if (debaixo && debaixo._lb && debaixo._lb.banda !== lb.banda) {
            const r = debaixo.getBoundingClientRect();
            lb.banda.itens = lb.banda.itens.filter((x) => x !== it1);
            it1.y = Math.max(0, arred((e.clientY - r.top) / esc() - 1));
            debaixo._lb.banda.itens.push(it1);
            bandaSel = debaixo._lb;
          } else if (it1.y < 0 || it1.y > lb.banda.altura) {
            it1.y = Math.min(Math.max(0, it1.y), Math.max(lb.banda.altura - it1.h, 0));
          }
        }
        desenhar();
      };
      alvo.addEventListener("pointermove", mover);
      alvo.addEventListener("pointerup", soltar);
    }

    function iniciarRedim(ev, it, dom) {
      ev.stopPropagation(); ev.preventDefault();
      const x0 = ev.clientX, y0 = ev.clientY, w0 = it.w, h0 = it.h;
      const h = ev.currentTarget;
      h.setPointerCapture(ev.pointerId);
      guardar();
      const mover = (e) => {
        it.w = Math.max(0.5, arred(w0 + (e.clientX - x0) / esc()));
        it.h = Math.max(0.3, arred(h0 + (e.clientY - y0) / esc()));
        dom.style.width = it.w * esc() + "px"; dom.style.height = it.h * esc() + "px";
      };
      const soltar = () => { h.removeEventListener("pointermove", mover); h.removeEventListener("pointerup", soltar); painelDir(); };
      h.addEventListener("pointermove", mover);
      h.addEventListener("pointerup", soltar);
    }

    function acharDOM(it) {
      return Array.from(ePagina.querySelectorAll(".dz-item")).find((x) => x._it === it) || null;
    }

    // ------------------------------------------------------------------ criar / apagar itens
    function fontePadrao() {
      const det = secao().bandas.detalhe;
      const f = (det.itens.find((i) => i.fonte) || {}).fonte;
      return f ? Object.assign({}, f, { n: false, i: false, s: false }) : { nome: "Arial", tam: 8, n: false, i: false, s: false, cor: "#000000" };
    }
    function novoItem(tipo, banda, x, y, extra) {
      guardar();
      const f = fontePadrao();
      const base = { _k: ++seq, tipo, x, y, w: 25, h: Math.max(r1(f.tam * PT_MM * 1.25), 3), fonte: f, alin: "e", nome: "" };
      let it;
      switch (tipo) {
        case "texto": it = Object.assign(base, { texto: "Texto", auto: true }); break;
        case "campo": it = Object.assign(base, { campo: (extra && extra.campo) || "", visao: (extra && extra.visao) || null, formato: "" }); break;
        case "total": it = Object.assign(base, { campo: (extra && extra.campo) || "", calc: "soma", formato: "#,0.00;-#,0.00", alin: "d", fonte: Object.assign({}, f, { n: true }) }); break;
        case "sistema": it = Object.assign(base, { sistema: "pagina_x_de_y", w: 35, alin: "d" }); break;
        case "variavel": it = Object.assign(base, { nome: "Calculo" + seq, codigo: "begin\n  Value := 0;\nend;", tipo_dado: "numero", calc_tipo: "percurso", reset_tipo: "fim", ordem: 0, formato: "#,0.00;-#,0.00", alin: "d" }); break;
        case "linha": it = { _k: ++seq, tipo, x: 0, y, w: largUtil(), h: 1, posicao: "topo", espessura: 0.75, cor: "#000000" }; break;
        case "retangulo": it = { _k: ++seq, tipo, x, y, w: 40, h: 10, forma: "retangulo", cor: "#000000", fundo: null, espessura: 0.75 }; break;
        case "sub": {
          const filhas = (info.visoes || []).filter((v) => v.mestre && v.mestre === secao().visao);
          const vis = (filhas[0] || (info.visoes || [])[1] || {}).nome || null;
          it = { _k: ++seq, tipo, x: 0, y, w: largUtil(), h: 8, nome: "Sub" + seq, secao: { visao: vis, grupos: [], titulo_antes: true, bandas: { titulo: { altura: 5, itens: [] }, detalhe: { altura: 5, itens: [] }, sumario: { altura: 0, itens: [] } } } };
          break;
        }
        default: return;
      }
      if (it.tipo === "campo" && it.campo) {
        const nums = (info.numeros || {})[it.visao || secao().visao] || [];
        if (nums.includes(it.campo)) { it.alin = "d"; it.formato = "#,0.00;-#,0.00"; }
      }
      banda.itens.push(it);
      if (banda.altura < y + (it.h || 0)) banda.altura = r1(y + (it.h || 4));
      selecao = [it];
      bandaSel = listaBandas(secao()).find((l) => l.banda === banda) || bandaSel;
      desenhar();
      if (tipo === "texto") setTimeout(() => { const t = eDir.querySelector("textarea"); if (t) { t.focus(); t.select(); } }, 30);
    }

    function bandaDe(it) {
      return listaBandas(secao()).find((l) => l.banda.itens.includes(it));
    }
    function apagarSel() {
      if (!selecao.length) return;
      guardar();
      selecao.forEach((it) => { const lb = bandaDe(it); if (lb) lb.banda.itens = lb.banda.itens.filter((x) => x !== it); });
      selecao = [];
      desenhar();
    }
    function duplicar(lista, dx, dy) {
      guardar();
      const novos = [];
      lista.forEach((it) => {
        const lb = bandaDe(it) || bandaSel;
        if (!lb) return;
        const c = JSON.parse(JSON.stringify(it, (k, v) => (k === "_k" ? undefined : v)));
        c._k = ++seq; c.x = r1(c.x + dx); c.y = r1(c.y + dy);
        if (c.tipo === "sub") chaves(c.secao);
        lb.banda.itens.push(c); novos.push(c);
      });
      selecao = novos;
      desenhar();
    }

    // ------------------------------------------------------------------ teclado
    function teclas(e) {
      if (!document.body.contains(raiz)) return;
      const emCampo = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "");
      const ctrl = e.ctrlKey || e.metaKey;
      if (e.key === "Escape") {
        e.stopPropagation();
        if (pendente) { pendente = null; marcarPendente(); return; }
        if (emCampo) { e.target.blur(); return; }
        if (selecao.length) { selecao = []; desenhar(); return; }
        if (pilha.length > 1) { pilha.pop(); painelEsq(); desenhar(); return; }
        return;
      }
      if (emCampo) return;
      if (ctrl && e.key.toLowerCase() === "z") { e.preventDefault(); if (desfazer.length) { refazer.push(JSON.stringify(d)); restaurarDe(desfazer.pop()); } return; }
      if (ctrl && e.key.toLowerCase() === "y") { e.preventDefault(); if (refazer.length) { desfazer.push(JSON.stringify(d)); restaurarDe(refazer.pop()); } return; }
      if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); acaoSalvar(); return; }
      if (ctrl && e.key.toLowerCase() === "c" && selecao.length) { copia = selecao.map((i) => clone(i)); return; }
      if (ctrl && e.key.toLowerCase() === "v" && copia && bandaSel) {
        e.preventDefault();
        guardar();
        selecao = copia.map((c) => { const n = clone(c); n._k = ++seq; n.y = r1(n.y + 1); if (n.tipo === "sub") chaves(n.secao); bandaSel.banda.itens.push(n); return n; });
        desenhar(); return;
      }
      if (ctrl && e.key.toLowerCase() === "d" && selecao.length) { e.preventDefault(); duplicar(selecao, 2, 2); return; }
      if ((e.key === "Delete" || e.key === "Backspace") && selecao.length) { e.preventDefault(); apagarSel(); return; }
      const setas = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      if (setas[e.key] && selecao.length) {
        e.preventDefault();
        guardar();
        const p = e.shiftKey ? 5 : (e.altKey ? 0.1 : 0.5);
        selecao.forEach((it) => { it.x = r1(it.x + setas[e.key][0] * p); it.y = r1(it.y + setas[e.key][1] * p); });
        desenhar();
      }
    }
    document.addEventListener("keydown", teclas, true);

    // ------------------------------------------------------------------ painel de propriedades
    function campoForm(rot, entrada, dica) {
      const l = el("label", "dz-prop");
      l.append(el("span", "", rot), entrada);
      if (dica) l.title = dica;
      return l;
    }
    function num(valor, aoMudar, passo) {
      const i = el("input"); i.type = "number"; i.step = passo || "0.1"; i.value = r1(valor || 0);
      i.onchange = () => { guardar(); aoMudar(parseFloat(i.value || "0") || 0); desenhar(); };
      return i;
    }
    function txt(valor, aoMudar, multi) {
      const i = el(multi ? "textarea" : "input"); i.value = valor || "";
      if (multi) i.rows = multi;
      let guardou = false;
      i.oninput = () => { if (!guardou) { guardar(); guardou = true; } aoMudar(i.value); atualizarSel(); };
      i.onchange = () => { guardou = false; };
      return i;
    }
    function sel(opcoes, valor, aoMudar) {
      const s = el("select");
      opcoes.forEach(([v, r]) => { const o = el("option", "", r); o.value = v; if (String(v) === String(valor ?? "")) o.selected = true; s.appendChild(o); });
      s.onchange = () => { guardar(); aoMudar(s.value); desenhar(); };
      return s;
    }
    function chk(rot, valor, aoMudar) {
      const l = el("label", "dz-chk"); const c = el("input"); c.type = "checkbox"; c.checked = !!valor;
      c.onchange = () => { guardar(); aoMudar(c.checked); desenhar(); };
      l.append(c, " " + rot);
      return l;
    }
    function atualizarSel() {
      selecao.forEach((it) => {
        const e = acharDOM(it);
        if (e && !["linha", "retangulo", "sub"].includes(it.tipo)) {
          const h = e.querySelector(".dz-alca");
          e.textContent = rotuloItem(it);
          if (h) e.appendChild(h);
        }
      });
    }
    function camposOpcoes(visao) {
      const v = visao || secao().visao;
      const lista = (info.campos[v] || []).map((c) => [c, c]);
      return [["", "(escolha)"]].concat(lista);
    }
    function visoesOpcoes(padrao) {
      return [["", padrao]].concat((info.visoes || []).map((v) => [v.nome, v.nome]));
    }

    function painelDir() {
      eDir.replaceChildren();
      const sec = secao();
      if (selecao.length > 1) {
        eDir.appendChild(el("div", "dz-sec", `${selecao.length} itens selecionados`));
        const g = el("div", "dz-botoes");
        const b = (r, fn) => { const x = el("button", "btn pequeno", r); x.type = "button"; x.onclick = () => { guardar(); fn(); desenhar(); }; g.appendChild(x); };
        const ref = selecao[0];
        b("Alinhar à esquerda", () => selecao.forEach((i) => (i.x = ref.x)));
        b("Alinhar à direita", () => selecao.forEach((i) => (i.x = r1(ref.x + ref.w - i.w))));
        b("Alinhar no topo", () => selecao.forEach((i) => (i.y = ref.y)));
        b("Mesma largura", () => selecao.forEach((i) => (i.w = ref.w)));
        b("Mesma altura", () => selecao.forEach((i) => (i.h = ref.h)));
        eDir.appendChild(g);
        if (selecao.every((i) => i.fonte)) {
          eDir.appendChild(campoForm("Tamanho da fonte", num(ref.fonte.tam, (v) => selecao.forEach((i) => (i.fonte.tam = v)), "0.5")));
          eDir.appendChild(chk("Negrito", ref.fonte.n, (v) => selecao.forEach((i) => (i.fonte.n = v))));
        }
        const ap = el("button", "btn pequeno perigo", "Apagar selecionados"); ap.onclick = apagarSel; eDir.appendChild(ap);
        return;
      }
      if (selecao.length === 1) { propsItem(selecao[0]); return; }
      if (bandaSel) { propsBanda(bandaSel, sec); return; }
      propsSecao(sec);
    }

    function propsItem(it) {
      const nomes = { texto: "Texto", campo: "Campo", memo: "Campo (várias linhas)", total: "Total", variavel: "Cálculo (variável)", sistema: "Data / página", linha: "Linha", retangulo: "Retângulo", sub: "Sub-relatório" };
      eDir.appendChild(el("div", "dz-sec", nomes[it.tipo] || it.tipo));
      if (it.tipo === "texto") eDir.appendChild(campoForm("Texto", txt(it.texto, (v) => (it.texto = v), 3)));
      if (["campo", "memo", "total"].includes(it.tipo)) {
        eDir.appendChild(campoForm("Visão", sel(visoesOpcoes("(a desta seção" + (secao().visao ? ": " + secao().visao : "") + ")"), it.visao || "", (v) => (it.visao = v || null))));
        eDir.appendChild(campoForm("Campo", sel(camposOpcoes(it.visao), it.campo, (v) => (it.campo = v))));
      }
      if (it.tipo === "total") {
        eDir.appendChild(campoForm("Cálculo", sel(Object.entries(CALCS), it.calc, (v) => (it.calc = v))));
        eDir.appendChild(el("p", "dz-nota", "No rodapé de grupo, soma as linhas do grupo; no sumário, o relatório todo."));
      }
      if (it.tipo === "sistema") eDir.appendChild(campoForm("Mostrar", sel(Object.entries(SISTEMA), it.sistema, (v) => (it.sistema = v))));
      if (it.tipo === "variavel") {
        eDir.appendChild(campoForm("Nome", txt(it.nome, (v) => (it.nome = v.replace(/[^\w]/g, "")))));
        const cod = txt(it.codigo, (v) => (it.codigo = v), 8);
        cod.classList.add("dz-codigo");
        eDir.appendChild(campoForm("Cálculo (RAP / Pascal)", cod));
        eDir.appendChild(el("p", "dz-nota", "Ex.: Value := Value + Visao['Campo'];  Use Visao['Apelido ou CAMPO'], Variable1.Value, if/then/else, FormatFloat, Copy, Trim."));
        eDir.appendChild(campoForm("Tipo do valor", sel([["numero", "Número"], ["texto", "Texto"], ["data", "Data"], ["logico", "Sim/Não"]], it.tipo_dado, (v) => (it.tipo_dado = v))));
        const grupos = (secao().grupos || []).map((g, i) => [String(i), `Grupo ${i + 1} (${g.campo})`]);
        eDir.appendChild(campoForm("Calcula", sel([["percurso", "A cada linha"], ["antes_rodape_grupo", "Antes do rodapé do grupo"], ["antes_cab_grupo", "Antes do cabeçalho do grupo"], ["fim", "No fim"]], it.calc_tipo, (v) => (it.calc_tipo = v))));
        eDir.appendChild(campoForm("Zera", sel([["fim", "Nunca (acumula no relatório)"], ["inicio_grupo", "No início do grupo"], ["fim_grupo", "No fim do grupo"]], it.reset_tipo, (v) => (it.reset_tipo = v))));
        if (grupos.length) eDir.appendChild(campoForm("Grupo", sel([["", "(qualquer)"]].concat(grupos), it.reset_grupo ?? "", (v) => { it.reset_grupo = v === "" ? null : +v; it.calc_grupo = it.reset_grupo; })));
        eDir.appendChild(campoForm("Ordem", num(it.ordem, (v) => (it.ordem = v), "1")));
      }
      if (["campo", "memo", "total", "variavel", "sistema"].includes(it.tipo)) {
        const f = el("input"); f.value = it.formato || ""; f.setAttribute("list", "dz-formatos");
        f.onchange = () => { guardar(); it.formato = f.value; };
        eDir.appendChild(campoForm("Formato", f, "Formato do Delphi: #,0.00 (números) · dd/mm/yyyy (datas)"));
      }
      if (it.fonte) {
        eDir.appendChild(el("div", "dz-sec2", "Fonte"));
        const linha = el("div", "dz-linha");
        linha.append(sel(FONTES.concat(FONTES.includes(it.fonte.nome) ? [] : [it.fonte.nome]).map((x) => [x, x]), it.fonte.nome, (v) => (it.fonte.nome = v)),
          num(it.fonte.tam, (v) => (it.fonte.tam = Math.max(3, v)), "0.5"));
        eDir.appendChild(linha);
        const est = el("div", "dz-botoes");
        [["n", "N", "Negrito"], ["i", "I", "Itálico"], ["s", "S", "Sublinhado"]].forEach(([k, r, t]) => {
          const b = el("button", "btn pequeno" + (it.fonte[k] ? " ativo" : ""), r); b.title = t; b.type = "button";
          b.onclick = () => { guardar(); it.fonte[k] = !it.fonte[k]; desenhar(); };
          est.appendChild(b);
        });
        [["e", "⇤ Esq."], ["c", "Centro"], ["d", "Dir. ⇥"]].forEach(([k, r]) => {
          const b = el("button", "btn pequeno" + ((it.alin || "e") === k ? " ativo" : ""), r); b.type = "button";
          b.onclick = () => { guardar(); it.alin = k; desenhar(); };
          est.appendChild(b);
        });
        const cor = el("input"); cor.type = "color"; cor.value = it.fonte.cor || "#000000"; cor.title = "Cor do texto";
        cor.onchange = () => { guardar(); it.fonte.cor = cor.value; desenhar(); };
        est.appendChild(cor);
        eDir.appendChild(est);
        eDir.appendChild(chk("Ajustar largura ao texto", it.auto, (v) => (it.auto = v)));
        eDir.appendChild(chk("Quebrar linhas", it.quebra, (v) => (it.quebra = v)));
        if (["campo", "memo"].includes(it.tipo)) eDir.appendChild(chk("Esticar a banda se o texto for grande", it.esticar, (v) => (it.esticar = v)));
        if (["campo", "memo", "total", "variavel"].includes(it.tipo)) eDir.appendChild(chk("Em branco quando zero", it.branco_zero, (v) => (it.branco_zero = v)));
        const fl = el("div", "dz-linha");
        const fc = el("input"); fc.type = "color"; fc.value = it.fundo || "#ffffff"; fc.disabled = !it.fundo;
        fc.onchange = () => { guardar(); it.fundo = fc.value; desenhar(); };
        fl.append(chk("Fundo", !!it.fundo, (v) => (it.fundo = v ? "#eeeeee" : null)), fc);
        eDir.appendChild(fl);
      }
      if (it.tipo === "linha") {
        eDir.appendChild(campoForm("Posição na caixa", sel([["topo", "Em cima"], ["base", "Embaixo"], ["esq", "Esquerda (vertical)"], ["dir", "Direita (vertical)"]], it.posicao, (v) => (it.posicao = v))));
        eDir.appendChild(campoForm("Espessura (pt)", num(it.espessura, (v) => (it.espessura = v), "0.25")));
        eDir.appendChild(chk("Linha dupla", it.dupla, (v) => (it.dupla = v)));
      }
      if (it.tipo === "retangulo") {
        eDir.appendChild(campoForm("Forma", sel([["retangulo", "Retângulo"], ["arredondado", "Cantos arredondados"], ["elipse", "Elipse"]], it.forma, (v) => (it.forma = v))));
        eDir.appendChild(campoForm("Borda (pt)", num(it.espessura, (v) => (it.espessura = v), "0.25")));
        const fc = el("input"); fc.type = "color"; fc.value = it.fundo || "#ffffff";
        fc.onchange = () => { guardar(); it.fundo = fc.value; desenhar(); };
        const l = el("div", "dz-linha"); l.append(chk("Fundo", !!it.fundo, (v) => (it.fundo = v ? "#eeeeee" : null)), fc);
        eDir.appendChild(l);
      }
      if (["linha", "retangulo"].includes(it.tipo)) {
        const c = el("input"); c.type = "color"; c.value = it.cor || "#000000";
        c.onchange = () => { guardar(); it.cor = c.value; desenhar(); };
        eDir.appendChild(campoForm("Cor", c));
      }
      if (it.tipo === "sub") {
        eDir.appendChild(campoForm("Visão do sub-relatório", sel(visoesOpcoes("(nenhuma)"), (it.secao || {}).visao || "", (v) => (it.secao.visao = v || null))));
        const b = el("button", "btn pequeno primario", "Editar sub-relatório"); b.type = "button"; b.onclick = () => entrarSub(it);
        eDir.appendChild(b);
        eDir.appendChild(el("p", "dz-nota", "Imprime as linhas da visão ligadas à linha atual (como no ReportBuilder). A banda cresce conforme o número de linhas."));
      }
      eDir.appendChild(el("div", "dz-sec2", "Posição e tamanho (mm)"));
      const pos = el("div", "dz-grade4");
      pos.append(campoForm("X", num(it.x, (v) => (it.x = v))), campoForm("Y", num(it.y, (v) => (it.y = v))),
        campoForm("Largura", num(it.w, (v) => (it.w = Math.max(0.5, v)))), campoForm("Altura", num(it.h, (v) => (it.h = Math.max(0.3, v)))));
      eDir.appendChild(pos);
      const acoes = el("div", "dz-botoes");
      const dup = el("button", "btn pequeno", "Duplicar"); dup.onclick = () => duplicar([it], 2, 2);
      const ap = el("button", "btn pequeno perigo", "Apagar"); ap.onclick = apagarSel;
      acoes.append(dup, ap);
      eDir.appendChild(acoes);
    }

    function propsBanda(lb, sec) {
      eDir.appendChild(el("div", "dz-sec", "Banda: " + lb.rot));
      eDir.appendChild(campoForm("Altura (mm)", num(lb.banda.altura, (v) => (lb.banda.altura = Math.max(0, v)))));
      eDir.appendChild(chk("Visível", lb.banda.visivel !== false, (v) => (lb.banda.visivel = v)));
      if (lb.tipo === "detalhe") eDir.appendChild(chk("Altura dinâmica (cresce com sub-relatórios e textos longos)", lb.banda.dinamica !== false, (v) => (lb.banda.dinamica = v)));
      if (lb.tipo === "gcab" || lb.tipo === "grod") {
        const g = sec.grupos[lb.grupo];
        eDir.appendChild(campoForm("Quebrar quando mudar o campo", sel(camposOpcoes(g.visao), g.campo, (v) => (g.campo = v))));
        eDir.appendChild(chk("Cada grupo em nova página", g.nova_pagina, (v) => (g.nova_pagina = v)));
        const b = el("button", "btn pequeno perigo", "Remover este grupo");
        b.onclick = () => { if (!confirm("Remover o grupo e as suas bandas?")) return; guardar(); sec.grupos.splice(lb.grupo, 1); bandaSel = null; desenhar(); };
        eDir.appendChild(b);
      }
      eDir.appendChild(el("p", "dz-nota", "Dica: clique num componente à esquerda e depois na banda, ou arraste um campo para cá."));
      propsSecao(sec, true);
    }

    function propsSecao(sec, resumido) {
      const principal = sec === d.relatorio;
      if (!resumido) {
        eDir.appendChild(el("div", "dz-sec", principal ? "Relatório" : "Sub-relatório"));
        eDir.appendChild(el("p", "dz-nota", "Clique numa banda ou num item para ver as propriedades. Arraste para mover, use a alça do canto para redimensionar. Setas movem (Shift = 5 mm), Delete apaga, Ctrl+C/Ctrl+V copia, Ctrl+Z desfaz."));
      }
      eDir.appendChild(el("div", "dz-sec2", "Dados"));
      eDir.appendChild(campoForm(principal ? "Visão principal (uma linha por detalhe)" : "Visão do sub-relatório",
        sel(visoesOpcoes("(nenhuma - imprime uma vez)"), sec.visao || "", (v) => (sec.visao = v || null))));
      eDir.appendChild(el("div", "dz-sec2", "Bandas"));
      ["titulo", "cabecalho", "sumario"].concat(principal ? ["rodape"] : []).forEach((t) => {
        eDir.appendChild(chk(NOMES_BANDA[t], !!sec.bandas[t], (v) => {
          if (v) sec.bandas[t] = sec.bandas[t] || { altura: 8, visivel: true, dinamica: true, itens: [] };
          else if (!sec.bandas[t].itens.length || confirm("A banda tem itens. Remover mesmo assim?")) delete sec.bandas[t];
        }));
      });
      const novo = el("div", "dz-linha");
      const sc = el("select"); camposOpcoes(sec.visao).forEach(([v, r]) => { const o = el("option", "", r === "(escolha)" ? "(campo do grupo)" : r); o.value = v; sc.appendChild(o); });
      const b = el("button", "btn pequeno", "Adicionar grupo"); b.type = "button";
      b.onclick = () => {
        if (!sc.value) { alerta("Escolha o campo que separa os grupos."); return; }
        guardar();
        sec.grupos = sec.grupos || [];
        sec.grupos.push({ campo: sc.value, visao: null, nova_pagina: false, cab: { altura: 6, visivel: true, dinamica: true, itens: [] }, rod: { altura: 0, visivel: true, dinamica: true, itens: [] } });
        desenhar();
      };
      novo.append(sc, b);
      eDir.appendChild(campoForm("Grupos (quebra por campo)", novo));
      if (principal && !resumido) {
        eDir.appendChild(el("div", "dz-sec2", "Página"));
        const pg = d.pagina;
        const atual = Object.keys(PAPEIS).find((k) => { const [w, h] = PAPEIS[k]; return (Math.abs(w - pg.largura) < 1 && Math.abs(h - pg.altura) < 1) || (Math.abs(h - pg.largura) < 1 && Math.abs(w - pg.altura) < 1); }) || "";
        const paisagem = pg.largura > pg.altura;
        eDir.appendChild(campoForm("Papel", sel([["", "Personalizado"]].concat(Object.keys(PAPEIS).map((k) => [k, k])), atual, (v) => {
          if (!PAPEIS[v]) return;
          const [w, h] = PAPEIS[v];
          pg.largura = paisagem ? h : w; pg.altura = paisagem ? w : h;
        })));
        eDir.appendChild(campoForm("Orientação", sel([["retrato", "Retrato"], ["paisagem", "Paisagem"]], paisagem ? "paisagem" : "retrato", (v) => {
          if ((v === "paisagem") !== (pg.largura > pg.altura)) { const t = pg.largura; pg.largura = pg.altura; pg.altura = t; }
        })));
        const mg = el("div", "dz-grade4");
        [["sup", "Sup."], ["inf", "Inf."], ["esq", "Esq."], ["dir", "Dir."]].forEach(([k, r]) => mg.appendChild(campoForm(r, num(pg.margens[k], (v) => (pg.margens[k] = Math.max(0, v))))));
        eDir.appendChild(campoForm("Margens (mm)", mg));
        eDir.appendChild(chk("Título antes do cabeçalho", sec.titulo_antes !== false, (v) => (sec.titulo_antes = v)));
        const sn = sel([["0.5", "0,5 mm"], ["1", "1 mm"], ["0", "livre"]], String(snap), (v) => { snap = parseFloat(v); });
        eDir.appendChild(campoForm("Encaixe na grade", sn));
      }
      if (!principal) {
        const v = el("button", "btn pequeno", "← Voltar ao relatório principal"); v.type = "button";
        v.onclick = () => { pilha = [d.relatorio]; selecao = []; bandaSel = null; painelEsq(); desenhar(); };
        eDir.appendChild(v);
      }
    }

    // ------------------------------------------------------------------ ações
    async function acaoSalvar() {
      if (!info.pode_editar) { alerta("Você não tem permissão para salvar layouts."); return; }
      try {
        await api(`/api/rb/${encodeURIComponent(rid)}/desenho`, { json: { desenho: clone(d) } });
        sujo = false;
        info.tem_salvo = true;
        alerta("Layout salvo. O PDF deste relatório passa a sair assim para todos.", "ok");
      } catch (e) { alerta(e.message); }
    }
    async function acaoPDF() {
      try {
        await baixar(`/api/rb/${encodeURIComponent(rid)}/desenho/pdf`, { json: { valores: op.valores || {}, desenho: clone(d) } });
      } catch (e) { alerta(e.message); }
    }

    // lista de formatos para o campo "Formato"
    if (!document.getElementById("dz-formatos")) {
      const dl = el("datalist"); dl.id = "dz-formatos";
      FORMATOS.forEach((f) => { const o = el("option"); o.value = f; dl.appendChild(o); });
      document.body.appendChild(dl);
    }
    window.addEventListener("resize", () => { if (document.body.contains(raiz)) desenhar(); });
    carregar();
  }

  window.DesignerRB = { abrir };
})();
