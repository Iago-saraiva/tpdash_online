/* TP DASH ADMIN: empresas, chaves dos agentes, filiais e usuários de todas as empresas. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const TOKEN = $("meta[name=csrf]").content;
  const BASE = document.body.dataset.base || "";
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const td = (t) => el("td", "", t == null ? "" : String(t));
  const raiz = $(".conteudo");

  async function api(url, json) {
    const op = { headers: { "X-Admin": TOKEN } };
    if (json !== undefined) { op.method = "POST"; op.headers["Content-Type"] = "application/json"; op.body = JSON.stringify(json); }
    const r = await fetch(BASE + url, op);
    let d = null;
    try { d = await r.json(); } catch (e) { /* sem JSON */ }
    if (r.status === 401) { location.href = BASE + "/login"; throw new Error("Sessão expirada"); }
    if (!r.ok) throw new Error((d && d.erro) || `Erro ${r.status}`);
    return d;
  }
  function aviso(msg, tipo = "erro") {
    const d = el("div", "aviso " + tipo, msg);
    raiz.prepend(d);
    setTimeout(() => d.remove(), 9000);
  }
  const botao = (txt, cls, fn) => { const b = el("button", "btn pequeno " + (cls || ""), txt); b.type = "button"; b.onclick = fn; return b; };

  const corpo = $("#tabela-empresas tbody"), caixa = $("#chave-nova");
  const corpoU = $("#tabela-usuarios tbody"), filtro = $("#filtro-empresa");
  const form = $("#form-usuario"), cartaoU = $("#cartao-usuario"), selEmp = form.elements.empresa;
  let empresas = [], lista = [], escolhida = "";

  const nomeEmp = (id) => (empresas.find((e) => e.id === id) || { nome: id || "(sem empresa)" }).nome;
  const emp = (id) => empresas.find((e) => e.id === id);

  function mostrarChave(nome, chave) {
    caixa.hidden = false;
    caixa.replaceChildren(el("strong", "", `Chave do agente de ${nome} (aparece só agora, copie e guarde):`), el("br"));
    const cod = el("code", "", chave); cod.style.userSelect = "all"; cod.style.wordBreak = "break-all";
    caixa.append(cod, el("br"), el("span", "nota", "No TP DASH Agente do servidor do cliente: Adicionar empresa e colar esta chave."));
  }

  function desenharEmpresas() {
    corpo.replaceChildren();
    if (!empresas.length) { const tr = el("tr"); const c = td("Nenhuma empresa cadastrada."); c.colSpan = 6; tr.append(c); corpo.append(tr); }
    empresas.forEach((e) => {
      const tr = el("tr", e.id === escolhida ? "escolhida" : "");
      const cNome = el("td"); cNome.append(el("strong", "", e.nome), el("br"), el("span", "nota", e.id));
      const cAg = el("td");
      cAg.append(el("span", "tag " + (e.online ? "entrada" : ""), e.online ? "Conectado" : (e.tem_chave ? "Desconectado" : "Sem chave")),
        el("br"), el("span", "nota", e.visto ? `último contato ${e.visto}` : "nunca conectou"));
      const f = e.filiais;
      const cFil = td(f ? (f.length === 1 ? "1 filial" : f.length ? `${f.length} filiais` : "nenhuma") : "—");
      const nUs = lista.filter((u) => u.empresa_id === e.id).length;
      const cAc = el("td"), ac = el("div", "adm-acoes"); cAc.append(ac);
      ac.append(botao(e.tem_chave ? "Nova chave" : "Gerar chave", "", async (ev) => {
        ev.stopPropagation();
        if (e.tem_chave && !confirm(`Gerar uma chave nova para ${e.nome}? A chave atual para de funcionar e o agente precisa ser atualizado.`)) return;
        try { const r = await api(`/api/empresas/${encodeURIComponent(e.id)}/chave`, {}); mostrarChave(e.nome, r.chave); carregar(); }
        catch (err) { aviso(err.message); }
      }));
      if (e.tem_chave) ac.append(botao("Bloquear", "", async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Bloquear a chave de ${e.nome}? O agente desconecta até receber uma chave nova.`)) return;
        try { await api(`/api/empresas/${encodeURIComponent(e.id)}/chave`, { acao: "bloquear" }); carregar(); } catch (err) { aviso(err.message); }
      }));
      ac.append(botao("Renomear", "", async (ev) => {
        ev.stopPropagation();
        const nome = prompt("Nome da empresa:", e.nome);
        if (!nome || nome.trim() === e.nome) return;
        try { await api("/api/empresas", { id: e.id, nome: nome.trim(), ativa: !!e.ativa }); carregar(); } catch (err) { aviso(err.message); }
      }));
      ac.append(botao(e.ativa ? "Desativar" : "Ativar", "", async (ev) => {
        ev.stopPropagation();
        if (e.ativa && !confirm(`Desativar ${e.nome}? Os usuários e o agente dela perdem o acesso.`)) return;
        try { await api("/api/empresas", { id: e.id, nome: e.nome, ativa: !e.ativa }); carregar(); } catch (err) { aviso(err.message); }
      }));
      tr.append(cNome, td(e.ativa ? "Ativa" : "Desativada"), cAg, cFil, td(nUs), cAc);
      tr.onclick = () => escolher(e.id);
      corpo.append(tr);
    });
  }

  function desenharFiliais() {
    const box = $("#lista-filiais"), bAt = $("#atualizar-filiais"), e = emp(escolhida);
    if (!e) { $("#titulo-filiais").textContent = "Filiais"; box.textContent = "Escolha uma empresa na lista."; bAt.hidden = true; return; }
    $("#titulo-filiais").textContent = `Filiais · ${e.nome}`;
    bAt.hidden = false;
    box.replaceChildren();
    if (e.filiais && e.filiais.length) {
      const t = el("table", "dados"), th = el("tr");
      th.append(el("th", "", "Código"), el("th", "", "Filial")); t.append(th);
      e.filiais.forEach((x) => { const tr = el("tr"); tr.append(td(x.codigo), td(x.nome)); t.append(tr); });
      box.append(t);
    } else if (e.filiais) box.append(el("span", "nota", "Nenhuma filial cadastrada no Puma desta empresa."));
    else box.append(el("span", "nota", e.online ? "Lendo as filiais no banco da empresa…" : "As filiais aparecem quando o agente da empresa se conectar."));
    if (e.filiais_pedidas && e.filiais) box.append(el("p", "nota", "Leitura nova pedida: atualiza em instantes."));
    if (e.filiais_erro) box.append(el("p", "nota", "Último erro ao ler as filiais: " + e.filiais_erro));
  }

  function desenharUsuarios() {
    const fe = filtro.value;
    $("#titulo-usuarios").textContent = fe ? `Usuários · ${nomeEmp(fe)}` : "Usuários de todas as empresas";
    corpoU.replaceChildren();
    const us = lista.filter((u) => !fe || u.empresa_id === fe);
    if (!us.length) { const tr = el("tr"); const c = td("Nenhum usuário."); c.colSpan = 7; tr.append(c); corpoU.append(tr); }
    us.forEach((u) => {
      const tr = el("tr");
      const cAc = el("td"), ac = el("div", "adm-acoes"); cAc.append(ac);
      ac.append(botao("Editar", "", () => editar(u)), botao(u.ativo ? "Desativar" : "Ativar", "", async () => {
        if (u.ativo && !confirm(`Desativar ${u.login}? Ele deixa de conseguir entrar.`)) return;
        try { await api("/api/usuarios", { ...base(u), ativo: !u.ativo }); carregar(); } catch (err) { aviso(err.message); }
      }));
      tr.append(td(u.login), td(u.nome), td(nomeEmp(u.empresa_id)), td(u.admin ? "Administrador" : "Usuário"),
        td(u.ativo ? "Ativo" : "Inativo"), td(u.ultimo_acesso || "nunca"), cAc);
      corpoU.append(tr);
    });
  }

  const base = (u) => ({ id: u.id, empresa: u.empresa_id, login: u.login, nome: u.nome, admin: !!u.admin, ativo: !!u.ativo, modulos: u.modulos });

  function editar(u) {
    form.reset();
    cartaoU.hidden = false;
    form.elements.id.value = u ? u.id : "";
    selEmp.value = u ? u.empresa_id : (escolhida || filtro.value || (empresas[0] || {}).id || "");
    form.elements.login.value = u ? u.login : "";
    form.elements.nome.value = u ? u.nome : "";
    form.elements.admin.checked = !!(u && u.admin);
    form.elements.ativo.checked = !u || !!u.ativo;
    $$("input[name=modulos]", form).forEach((c) => (c.checked = u ? u.modulos.includes(c.value) : c.value === "inicio"));
    $("#titulo-form").textContent = u ? `Editar ${u.login}` : "Novo usuário";
    form.elements.senha.placeholder = u ? "Vazio mantém a senha; preenchida, ele troca na próxima entrada" : "Senha inicial";
    cartaoU.scrollIntoView({ behavior: "smooth" });
  }

  function escolher(eid) {
    escolhida = eid;
    filtro.value = eid;
    desenharEmpresas(); desenharUsuarios(); desenharFiliais();
  }

  async function carregar() {
    const [d, du] = await Promise.all([api("/api/empresas"), api("/api/usuarios")]);
    empresas = d.empresas; lista = du.usuarios;
    const opts = () => empresas.map((e) => { const o = el("option", "", `${e.nome} (${e.id})${e.ativa ? "" : " · desativada"}`); o.value = e.id; return o; });
    const fv = filtro.value, sv = selEmp.value;
    const todas = el("option", "", "Todas as empresas"); todas.value = "";
    filtro.replaceChildren(todas, ...opts()); filtro.value = fv;
    selEmp.replaceChildren(...opts()); if (sv) selEmp.value = sv;
    desenharEmpresas(); desenharUsuarios(); desenharFiliais();
  }

  filtro.addEventListener("change", () => { escolhida = filtro.value; desenharEmpresas(); desenharUsuarios(); desenharFiliais(); });
  $("#atualizar-filiais").addEventListener("click", async () => {
    try { await api(`/api/empresas/${encodeURIComponent(escolhida)}/filiais`, {}); await carregar(); } catch (err) { aviso(err.message); }
  });
  $("#novo-usuario").addEventListener("click", () => editar(null));
  $("#cancelar-usuario").addEventListener("click", () => { cartaoU.hidden = true; });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const dados = {
      id: form.elements.id.value ? +form.elements.id.value : null, empresa: selEmp.value,
      login: form.elements.login.value.trim(), nome: form.elements.nome.value.trim(), senha: form.elements.senha.value,
      admin: form.elements.admin.checked, ativo: form.elements.ativo.checked,
      modulos: $$("input[name=modulos]:checked", form).map((c) => c.value),
    };
    try {
      await api("/api/usuarios", dados);
      aviso(`Usuário ${dados.login} salvo na empresa ${nomeEmp(dados.empresa)}.`, "atencao");
      cartaoU.hidden = true;
      await carregar();
    } catch (err) { aviso(err.message); }
  });
  $("#form-empresa").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    const dados = { id: f.elements.id.value.trim(), nome: f.elements.nome.value.trim(), ativa: f.elements.ativa.checked };
    try {
      const r = await api("/api/empresas", dados);
      if (f.elements.gerar.checked) mostrarChave(dados.nome, (await api(`/api/empresas/${encodeURIComponent(r.id)}/chave`, {})).chave);
      f.reset(); f.elements.ativa.checked = true; f.elements.gerar.checked = true;
      await carregar();
      escolher(r.id);
    } catch (e) { aviso(e.message); }
  });
  carregar().catch((e) => aviso(e.message));
  setInterval(() => carregar().catch(() => {}), 15000);
})();
