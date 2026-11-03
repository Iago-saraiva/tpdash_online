/* TP DASH - assistente flutuante (perguntas programadas sobre o banco, com PDF/Excel) */
(function () {
  "use strict";
  const TOKEN = document.querySelector('meta[name="csrf"]')?.content || "";
  const CHAVE = "painel_chat";          // conversa só nesta aba (sessionStorage some ao fechar)
  let sugestoesIniciais = ["Resumo do mês", "Ajuda"];
  let topicosIniciais = [];
  let abaTopico = 0;

  let conversa = [];
  try { conversa = JSON.parse(sessionStorage.getItem(CHAVE) || "[]"); } catch (e) { conversa = []; }
  let ocupado = false;

  function salvar() {
    try { sessionStorage.setItem(CHAVE, JSON.stringify(conversa.slice(-30))); } catch (e) { /* sem armazenamento */ }
  }

  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt !== undefined) e.textContent = txt;
    return e;
  }

  /* ---------- texto com **negrito** e listas (escapado antes de formatar) ---------- */
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function inline(s) {
    return esc(s).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }
  function markdown(texto) {
    const linhas = String(texto || "").replace(/\r/g, "").split("\n");
    let html = "", i = 0;
    while (i < linhas.length) {
      const l = linhas[i];
      if (/^\s*([-*]|\d+[.)])\s+/.test(l)) {
        const ordenada = /^\s*\d/.test(l);
        let t = ordenada ? "<ol>" : "<ul>";
        while (i < linhas.length && /^\s*([-*]|\d+[.)])\s+/.test(linhas[i])) {
          t += "<li>" + inline(linhas[i].replace(/^\s*([-*]|\d+[.)])\s+/, "")) + "</li>";
          i++;
        }
        html += t + (ordenada ? "</ol>" : "</ul>");
        continue;
      }
      if (!l.trim()) { i++; continue; }
      const par = [];
      while (i < linhas.length && linhas[i].trim() && !/^\s*([-*]|\d+[.)])\s+/.test(linhas[i])) par.push(linhas[i++]);
      html += "<p>" + par.map(inline).join("<br>") + "</p>";
    }
    return html;
  }

  /* ---------- formatação das colunas (mesmas regras dos relatórios) ---------- */
  const DINHEIRO = ["VALOR", "TOTAL", "PRECO", "CUSTO", "LIMITE", "VLR_UNIT", "VALOR_ESTOQUE", "VALOR_BAIXADO", "CUSTO_MEDIO"];
  const DATAS = ["EMISSAO", "VENCIMENTO", "BAIXA", "CADASTRO", "ULTIMA_VENDA", "DATA"];
  const ROTULOS = { QTD: "Qtd.", VALOR: "Valor", VALOR_ESTOQUE: "Valor em estoque", VALOR_BAIXADO: "Valor baixado", COD_FABRICANTE: "Cód. fabricante",
    NOME_LOCAL: "Local", DIAS_ATRASO: "Dias de atraso", MAIOR_ATRASO: "Maior atraso (dias)", TIPO_DOC: "Tipo doc.", EMISSAO: "Emissão",
    PRECO: "Preço", CUSTO_MEDIO: "Custo médio", MES: "Mês", UND: "Und.", CODIGO: "Código" };
  const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const numero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });
  function rotulo(c) {
    return ROTULOS[c] || c.charAt(0) + c.slice(1).toLowerCase().replace(/_/g, " ");
  }
  function tipoCol(c) {
    if (DINHEIRO.some((d) => c === d || c.startsWith(d + "_") || c.endsWith("_" + d))) return "moeda";
    if (DATAS.some((d) => c === d || c.startsWith(d))) return "data";
    return "";
  }
  function formatar(v, tipo) {
    if (v === null || v === undefined || v === "") return "";
    if (tipo === "moeda" && typeof v === "number") return moeda.format(v);
    if (tipo === "data" && typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(8, 10) + "/" + v.slice(5, 7) + "/" + v.slice(0, 4);
    if (typeof v === "number") return numero.format(v);
    return String(v);
  }

  /* ---------- montagem da tela ---------- */
  const icone = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M8.5 10.5h7M8.5 13.5h4.5"/></svg>';
  const fab = el("button", "chat-fab");
  fab.type = "button";
  fab.title = "Assistente: pergunte sobre os dados";
  fab.setAttribute("aria-label", "Abrir o assistente");
  fab.innerHTML = icone;

  const painel = el("section", "chat-painel");
  painel.setAttribute("aria-label", "Assistente");
  painel.hidden = true;
  const cab = el("header", "chat-cab");
  const tit = el("div", "chat-tit");
  tit.append(el("strong", "", "Assistente"), el("small", "", "Movimentos, financeiro, estoque, produtos..."));
  const btnTopicos = el("button", "btn pequeno", "Tópicos");
  btnTopicos.type = "button";
  btnTopicos.title = "Perguntas prontas por assunto";
  const limpar = el("button", "btn pequeno", "Nova conversa");
  limpar.type = "button";
  const fechar = el("button", "btn pequeno chat-fechar", "✕");
  fechar.type = "button";
  fechar.setAttribute("aria-label", "Fechar o assistente");
  cab.append(tit, btnTopicos, limpar, fechar);
  const lista = el("div", "chat-lista");
  lista.setAttribute("role", "log");
  lista.setAttribute("aria-live", "polite");
  const form = el("form", "chat-form");
  const campo = el("textarea");
  campo.rows = 1;
  campo.maxLength = 500;
  campo.placeholder = "Ex.: contas a receber vencidas";
  campo.setAttribute("aria-label", "Pergunta");
  const enviar = el("button", "btn primario", "Enviar");
  enviar.type = "submit";
  form.append(campo, enviar);
  const rodape = el("div", "chat-rodape", "Escreva do seu jeito (ex.: \"quem me deve?\") ou toque em Tópicos para ver as perguntas prontas.");
  painel.append(cab, lista, form, rodape);
  document.body.append(fab, painel);

  function urlArquivo(id, formato) {
    return "/api/chat/arquivo/" + encodeURIComponent(id) + "?formato=" + formato + "&baixar=1";
  }

  function botaoArquivo(id, formato) {
    const a = el("a", "btn pequeno chat-baixar");
    a.href = urlArquivo(id, formato);
    a.setAttribute("download", "");
    a.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>';
    a.append(formato === "xlsx" ? "Excel" : "PDF");
    return a;
  }

  function tabela(t) {
    const caixa = el("div", "chat-tab-caixa");
    const wrap = el("div", "chat-tabela");
    const tb = el("table");
    const tipos = t.colunas.map(tipoCol);
    const tr = el("tr");
    t.colunas.forEach((c, i) => {
      const th = el("th", "", rotulo(c));
      if (t.linhas.some((l) => typeof l[i] === "number")) th.className = "num";
      tr.appendChild(th);
    });
    const thead = el("thead"); thead.appendChild(tr); tb.appendChild(thead);
    const tbody = el("tbody");
    t.linhas.forEach((l) => {
      const r = el("tr");
      l.forEach((v, i) => r.appendChild(el("td", typeof v === "number" ? "num" : "", formatar(v, tipos[i]))));
      tbody.appendChild(r);
    });
    tb.appendChild(tbody);
    wrap.appendChild(tb);
    caixa.appendChild(wrap);
    const pe = el("div", "chat-tab-pe");
    pe.appendChild(el("span", "", t.total > t.linhas.length ? `Mostrando ${t.linhas.length} de ${t.total} linhas. Baixe para ver tudo:` : `${t.total} linha${t.total === 1 ? "" : "s"} · Baixar:`));
    if (t.id) pe.append(botaoArquivo(t.id, "pdf"), botaoArquivo(t.id, "xlsx"));
    caixa.appendChild(pe);
    return caixa;
  }

  function chips(lista) {
    const c = el("div", "chat-chips");
    lista.forEach((s) => {
      const rot = typeof s === "string" ? s : s.rotulo;
      const pergunta = typeof s === "string" ? s : s.pergunta;
      const b = el("button", "chat-sugestao", rot);
      b.type = "button";
      if (pergunta !== rot) b.title = pergunta;
      b.addEventListener("click", () => perguntar(pergunta));
      c.appendChild(b);
    });
    return c;
  }

  /* ---------- tópicos: abas por assunto com perguntas prontas ---------- */
  function completar(texto) {
    campo.value = texto;
    ajustarCampo();
    campo.focus();
    campo.setSelectionRange(campo.value.length, campo.value.length);
  }
  function cardTopicos(tps) {
    const card = el("div", "chat-topicos");
    if (!tps || !tps.length) return card;
    if (abaTopico >= tps.length) abaTopico = 0;
    const abas = el("div", "chat-abas");
    abas.setAttribute("role", "tablist");
    const corpo = el("div", "chat-topico-lista");
    function mostrar(i) {
      abaTopico = i;
      Array.from(abas.children).forEach((b, j) => { b.classList.toggle("ativa", j === i); b.setAttribute("aria-selected", j === i); });
      corpo.replaceChildren();
      tps[i].perguntas.forEach((q) => {
        const b = el("button", "chat-sugestao chat-topico-perg" + (q.completar ? " completar" : ""), q.rotulo);
        b.type = "button";
        if (q.completar) b.title = "Completa a pergunta na caixa de texto para você terminar de digitar";
        b.addEventListener("click", () => (q.completar ? completar(q.texto) : perguntar(q.texto)));
        corpo.appendChild(b);
      });
    }
    tps.forEach((tp, i) => {
      const b = el("button", "chat-aba", tp.nome);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.addEventListener("click", () => mostrar(i));
      abas.appendChild(b);
    });
    card.append(abas, corpo);
    mostrar(abaTopico);
    return card;
  }

  function bolha(m, ultima) {
    const b = el("div", "chat-msg " + (m.papel === "usuario" ? "eu" : m.erro ? "erro" : "ia"));
    if (m.papel === "usuario" || m.erro) b.textContent = m.texto;
    else b.innerHTML = markdown(m.texto);
    if (m.tabela) b.appendChild(tabela(m.tabela));
    const frag = document.createDocumentFragment();
    frag.appendChild(b);
    if (m.topicos && m.topicos.length) frag.appendChild(cardTopicos(m.topicos));
    if (ultima && m.sugestoes && m.sugestoes.length) frag.appendChild(chips(m.sugestoes));
    return frag;
  }

  function vazio() {
    const v = el("div", "chat-vazio");
    if (topicosIniciais.length) {
      v.append(el("p", "", "Olá! Pergunte do seu jeito sobre os dados do Puma (posso montar tabelas e gerar PDF ou Excel), ou escolha um assunto:"));
      v.appendChild(cardTopicos(topicosIniciais));
    } else {
      v.append(el("p", "", "Olá! Faça uma pergunta sobre os dados do Puma. Posso montar tabelas e gerar PDF ou Excel. Algumas ideias:"));
      v.appendChild(chips(sugestoesIniciais));
    }
    return v;
  }

  function desenhar() {
    lista.replaceChildren();
    if (!conversa.length) lista.appendChild(vazio());
    conversa.forEach((m, i) => lista.appendChild(bolha(m, i === conversa.length - 1)));
    lista.scrollTop = lista.scrollHeight;
  }

  function ajustarCampo() {
    campo.style.height = "auto";
    campo.style.height = Math.min(campo.scrollHeight, 120) + "px";
  }

  async function perguntar(texto) {
    texto = (texto || "").trim();
    if (!texto || ocupado) return;
    ocupado = true;
    enviar.disabled = true;
    campo.value = "";
    ajustarCampo();
    conversa.push({ papel: "usuario", texto });
    desenhar();
    const espera = el("div", "chat-msg ia chat-pensando", "Consultando...");
    lista.appendChild(espera);
    lista.scrollTop = lista.scrollHeight;
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "X-Painel": TOKEN, "Content-Type": "application/json" },
        body: JSON.stringify({ pergunta: texto }),
      });
      if (r.status === 401) { location.href = "/login?proximo=" + encodeURIComponent(location.pathname); return; }
      let d = null;
      try { d = await r.json(); } catch (e) { /* sem JSON */ }
      if (!r.ok) throw new Error((d && d.erro) || `Erro ${r.status}`);
      conversa.push({ papel: "assistente", texto: d.texto, tabela: d.tabela || null, sugestoes: d.sugestoes || [], topicos: d.topicos || null });
      if (d.formato && d.tabela && d.tabela.id) {
        const a = el("a"); a.href = urlArquivo(d.tabela.id, d.formato); a.setAttribute("download", "");
        document.body.appendChild(a); a.click(); a.remove();
      }
    } catch (e) {
      const msg = e instanceof TypeError ? "Não foi possível falar com o servidor. Confira a rede e tente de novo." : e.message;
      conversa.push({ papel: "assistente", texto: msg, erro: true });
    } finally {
      ocupado = false;
      enviar.disabled = false;
      salvar();
      desenhar();
      campo.focus();
    }
  }

  function abrir(sim) {
    painel.hidden = !sim;
    fab.classList.toggle("aberto", sim);
    fab.setAttribute("aria-label", sim ? "Fechar o assistente" : "Abrir o assistente");
    document.body.classList.toggle("chat-aberto", sim);
    try { sessionStorage.setItem(CHAVE + "_aberto", sim ? "1" : ""); } catch (e) { /* */ }
    if (sim) { desenhar(); setTimeout(() => campo.focus(), 50); }
  }

  fab.addEventListener("click", () => abrir(painel.hidden));
  fechar.addEventListener("click", () => abrir(false));
  btnTopicos.addEventListener("click", () => {
    if (ocupado) return;
    if (!conversa.length) { desenhar(); return; }
    conversa.push({ papel: "assistente", texto: "Escolha um assunto e toque numa pergunta. As que terminam com \"…\" você completa com o nome (cliente, produto, vendedor).", topicos: topicosIniciais });
    salvar(); desenhar();
  });
  limpar.addEventListener("click", () => { if (ocupado) return; conversa = []; salvar(); desenhar(); campo.focus(); });
  form.addEventListener("submit", (e) => { e.preventDefault(); perguntar(campo.value); });
  campo.addEventListener("input", ajustarCampo);
  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); perguntar(campo.value); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !painel.hidden) abrir(false); });

  fetch("/api/chat/inicio", { headers: { "X-Painel": TOKEN } })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      if (!d) return;
      if (d.sugestoes && d.sugestoes.length) sugestoesIniciais = d.sugestoes.concat(["Ajuda"]);
      if (d.topicos && d.topicos.length) topicosIniciais = d.topicos;
      else btnTopicos.hidden = true;
      if (!painel.hidden && !conversa.length) desenhar();
    })
    .catch(() => { /* fica com as sugestões padrão */ });

  let reabrir = false;
  try { reabrir = sessionStorage.getItem(CHAVE + "_aberto") === "1"; } catch (e) { /* */ }
  if (reabrir) abrir(true);
})();
