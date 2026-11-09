// Assistente flutuante (perguntas programadas sobre o banco, com PDF/Excel). Mesmo visual do chat.js das páginas antigas;
// a conversa fica no sessionStorage com a mesma chave, então continua ao passar de uma página antiga para uma nova.
import { Fragment, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DADOS } from "../dados";

const CHAVE = "painel_chat";
interface Tab { colunas: string[]; linhas: unknown[][]; total: number; id?: string }
type Sugestao = string | { rotulo: string; pergunta: string };
interface Topico { nome: string; perguntas: { rotulo: string; texto: string; completar?: boolean }[] }
interface Msg { papel: "usuario" | "assistente"; texto: string; tabela?: Tab | null; sugestoes?: Sugestao[]; topicos?: Topico[] | null; erro?: boolean }

/* texto com **negrito** e listas (escapado antes de formatar) */
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const inline = (s: string) => esc(s).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
function markdown(texto: string) {
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

/* formatação das colunas (mesmas regras dos relatórios) */
const DINHEIRO = ["VALOR", "TOTAL", "PRECO", "CUSTO", "LIMITE", "VLR_UNIT", "VALOR_ESTOQUE", "VALOR_BAIXADO", "CUSTO_MEDIO"];
const DATAS = ["EMISSAO", "VENCIMENTO", "BAIXA", "CADASTRO", "ULTIMA_VENDA", "DATA"];
const ROTULOS: Record<string, string> = { QTD: "Qtd.", VALOR: "Valor", VALOR_ESTOQUE: "Valor em estoque", VALOR_BAIXADO: "Valor baixado", COD_FABRICANTE: "Cód. fabricante",
  NOME_LOCAL: "Local", DIAS_ATRASO: "Dias de atraso", MAIOR_ATRASO: "Maior atraso (dias)", TIPO_DOC: "Tipo doc.", EMISSAO: "Emissão",
  PRECO: "Preço", CUSTO_MEDIO: "Custo médio", MES: "Mês", UND: "Und.", CODIGO: "Código" };
const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const numero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });
const rotulo = (c: string) => ROTULOS[c] || c.charAt(0) + c.slice(1).toLowerCase().replace(/_/g, " ");
function tipoCol(c: string) {
  if (DINHEIRO.some((d) => c === d || c.startsWith(d + "_") || c.endsWith("_" + d))) return "moeda";
  if (DATAS.some((d) => c === d || c.startsWith(d))) return "data";
  return "";
}
function formatar(v: unknown, tipo: string) {
  if (v === null || v === undefined || v === "") return "";
  if (tipo === "moeda" && typeof v === "number") return moeda.format(v);
  if (tipo === "data" && typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(8, 10) + "/" + v.slice(5, 7) + "/" + v.slice(0, 4);
  if (typeof v === "number") return numero.format(v);
  return String(v);
}

const urlArquivo = (id: string, formato: string) => "/api/chat/arquivo/" + encodeURIComponent(id) + "?formato=" + formato + "&baixar=1";
const Icone = () => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /><path d="M8.5 10.5h7M8.5 13.5h4.5" />
  </svg>
);
const BotaoArquivo = ({ id, formato }: { id: string; formato: string }) => (
  <a className="btn pequeno chat-baixar" href={urlArquivo(id, formato)} download="">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14" /></svg>
    {formato === "xlsx" ? "Excel" : "PDF"}
  </a>
);

function TabelaChat({ t }: { t: Tab }) {
  const tipos = t.colunas.map(tipoCol);
  return (
    <div className="chat-tab-caixa">
      <div className="chat-tabela"><table>
        <thead><tr>{t.colunas.map((c, i) => <th key={i} className={t.linhas.some((l) => typeof l[i] === "number") ? "num" : ""}>{rotulo(c)}</th>)}</tr></thead>
        <tbody>{t.linhas.map((l, n) => <tr key={n}>{l.map((v, i) => <td key={i} className={typeof v === "number" ? "num" : ""}>{formatar(v, tipos[i])}</td>)}</tr>)}</tbody>
      </table></div>
      <div className="chat-tab-pe">
        <span>{t.total > t.linhas.length ? `Mostrando ${t.linhas.length} de ${t.total} linhas. Baixe para ver tudo:` : `${t.total} linha${t.total === 1 ? "" : "s"} · Baixar:`}</span>
        {t.id && <><BotaoArquivo id={t.id} formato="pdf" /><BotaoArquivo id={t.id} formato="xlsx" /></>}
      </div>
    </div>
  );
}

/** a mesma tabela em HTML, para ir junto do texto formatado da resposta (como no chat.js) */
const SVG_BAIXAR = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>';
function tabelaHtml(t: Tab) {
  const tipos = t.colunas.map(tipoCol);
  const th = t.colunas.map((c, i) => `<th${t.linhas.some((l) => typeof l[i] === "number") ? ' class="num"' : ""}>${esc(rotulo(c))}</th>`).join("");
  const corpo = t.linhas.map((l) => "<tr>" + l.map((v, i) => `<td${typeof v === "number" ? ' class="num"' : ""}>${esc(formatar(v, tipos[i]))}</td>`).join("") + "</tr>").join("");
  const pe = t.total > t.linhas.length ? `Mostrando ${t.linhas.length} de ${t.total} linhas. Baixe para ver tudo:` : `${t.total} linha${t.total === 1 ? "" : "s"} · Baixar:`;
  const bt = (f: string) => `<a class="btn pequeno chat-baixar" href="${esc(urlArquivo(t.id || "", f))}" download="">${SVG_BAIXAR}${f === "xlsx" ? "Excel" : "PDF"}</a>`;
  return `<div class="chat-tab-caixa"><div class="chat-tabela"><table><thead><tr>${th}</tr></thead><tbody>${corpo}</tbody></table></div>` +
    `<div class="chat-tab-pe"><span>${esc(pe)}</span>${t.id ? bt("pdf") + bt("xlsx") : ""}</div></div>`;
}

export function Chat() {
  const [conversa, setConversa] = useState<Msg[]>(() => { try { return JSON.parse(sessionStorage.getItem(CHAVE) || "[]"); } catch { return []; } });
  const [aberto, setAberto] = useState(() => { try { return sessionStorage.getItem(CHAVE + "_aberto") === "1"; } catch { return false; } });
  const [ocupado, setOcupado] = useState(false);
  const [texto, setTexto] = useState("");
  const [sugestoesIniciais, setSugestoes] = useState<Sugestao[]>(["Resumo do mês", "Ajuda"]);
  const [topicosIniciais, setTopicos] = useState<Topico[]>([]);
  const [semTopicos, setSemTopicos] = useState(false);
  const [abaTopico, setAbaTopico] = useState(0);
  const lista = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLTextAreaElement>(null);
  const ocupadoRef = useRef(false);

  const gravar = (c: Msg[]) => { try { sessionStorage.setItem(CHAVE, JSON.stringify(c.slice(-30))); } catch { /* sem armazenamento */ } };
  const ajustarCampo = () => {
    const c = campo.current;
    if (!c) return;
    c.style.height = "auto";
    c.style.height = Math.min(c.scrollHeight, 120) + "px";
  };
  const primeiro = useRef(true);
  useEffect(() => { if (primeiro.current) { primeiro.current = false; return; } ajustarCampo(); }, [texto]);   // como antes: só depois de digitar
  useEffect(() => { if (lista.current) lista.current.scrollTop = lista.current.scrollHeight; });

  useEffect(() => {
    fetch("/api/chat/inicio", { headers: { "X-Painel": DADOS.csrf } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        if (d.sugestoes && d.sugestoes.length) setSugestoes(d.sugestoes.concat(["Ajuda"]));
        if (d.topicos && d.topicos.length) setTopicos(d.topicos);
        else setSemTopicos(true);
      })
      .catch(() => { /* fica com as sugestões padrão */ });
  }, []);

  const abrir = (sim: boolean) => {
    setAberto(sim);
    try { sessionStorage.setItem(CHAVE + "_aberto", sim ? "1" : ""); } catch { /* */ }
    if (sim) setTimeout(() => campo.current?.focus(), 50);
  };
  useEffect(() => {
    document.body.classList.toggle("chat-aberto", aberto);
    if (!aberto) return;
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") abrir(false); };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [aberto]);
  useEffect(() => {
    if (aberto) setTimeout(() => campo.current?.focus(), 50);     // reabriu aberto (outra página): já com o cursor na pergunta
    return () => document.body.classList.remove("chat-aberto");
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const perguntar = async (t: string) => {
    t = (t || "").trim();
    if (!t || ocupadoRef.current) return;
    ocupadoRef.current = true;
    setOcupado(true);
    setTexto("");
    let c: Msg[] = [...conversa, { papel: "usuario", texto: t }];
    setConversa(c);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "X-Painel": DADOS.csrf, "Content-Type": "application/json" },
        body: JSON.stringify({ pergunta: t }),
      });
      if (r.status === 401) { location.href = "/login?proximo=" + encodeURIComponent(location.pathname); return; }
      let d = null;
      try { d = await r.json(); } catch { /* sem JSON */ }
      if (!r.ok) throw new Error((d && d.erro) || `Erro ${r.status}`);
      c = [...c, { papel: "assistente", texto: d.texto, tabela: d.tabela || null, sugestoes: d.sugestoes || [], topicos: d.topicos || null }];
      if (d.formato && d.tabela && d.tabela.id) {
        const a = document.createElement("a"); a.href = urlArquivo(d.tabela.id, d.formato); a.setAttribute("download", "");
        document.body.appendChild(a); a.click(); a.remove();
      }
    } catch (e) {
      const msg = e instanceof TypeError ? "Não foi possível falar com o servidor. Confira a rede e tente de novo." : (e as Error).message;
      c = [...c, { papel: "assistente", texto: msg, erro: true }];
    } finally {
      ocupadoRef.current = false;
      setOcupado(false);
      setConversa(c);
      gravar(c);
      campo.current?.focus();
    }
  };

  const completar = (t: string) => {
    setTexto(t);
    setTimeout(() => { const x = campo.current; if (x) { x.focus(); x.setSelectionRange(x.value.length, x.value.length); } }, 0);
  };
  const chips = (l: Sugestao[]) => (
    <div className="chat-chips">
      {l.map((s, i) => {
        const rot = typeof s === "string" ? s : s.rotulo;
        const perg = typeof s === "string" ? s : s.pergunta;
        return <button key={i} type="button" className="chat-sugestao" title={perg !== rot ? perg : undefined} onClick={() => perguntar(perg)}>{rot}</button>;
      })}
    </div>
  );
  const cardTopicos = (tps: Topico[] | null | undefined) => {
    if (!tps || !tps.length) return <div className="chat-topicos" />;
    const i = abaTopico >= tps.length ? 0 : abaTopico;
    return (
      <div className="chat-topicos">
        <div className="chat-abas" role="tablist">
          {tps.map((tp, j) => <button key={j} type="button" className={"chat-aba" + (j === i ? " ativa" : "")} role="tab" aria-selected={j === i} onClick={() => setAbaTopico(j)}>{tp.nome}</button>)}
        </div>
        <div className="chat-topico-lista">
          {tps[i].perguntas.map((q, k) => (
            <button key={k} type="button" className={"chat-sugestao chat-topico-perg" + (q.completar ? " completar" : "")}
              title={q.completar ? "Completa a pergunta na caixa de texto para você terminar de digitar" : undefined}
              onClick={() => (q.completar ? completar(q.texto) : perguntar(q.texto))}>{q.rotulo}</button>
          ))}
        </div>
      </div>
    );
  };
  const topicos = () => {
    if (ocupadoRef.current || !conversa.length) return;
    const c: Msg[] = [...conversa, { papel: "assistente", texto: "Escolha um assunto e toque numa pergunta. As que terminam com \"…\" você completa com o nome (cliente, produto, vendedor).", topicos: topicosIniciais }];
    setConversa(c); gravar(c);
  };

  return createPortal(<>
    <button type="button" className={"chat-fab" + (aberto ? " aberto" : "")} title="Assistente: pergunte sobre os dados"
      aria-label={aberto ? "Fechar o assistente" : "Abrir o assistente"} onClick={() => abrir(!aberto)}><Icone /></button>
    <section className="chat-painel" aria-label="Assistente" hidden={!aberto}>
      <header className="chat-cab">
        <div className="chat-tit"><strong>Assistente</strong><small>Movimentos, financeiro, estoque, produtos...</small></div>
        <button type="button" className="btn pequeno" title="Perguntas prontas por assunto" hidden={semTopicos} onClick={topicos}>Tópicos</button>
        <button type="button" className="btn pequeno" onClick={() => { if (ocupadoRef.current) return; setConversa([]); gravar([]); campo.current?.focus(); }}>Nova conversa</button>
        <button type="button" className="btn pequeno chat-fechar" aria-label="Fechar o assistente" onClick={() => abrir(false)}>✕</button>
      </header>
      <div className="chat-lista" role="log" aria-live="polite" ref={lista}>
        {!conversa.length && (
          <div className="chat-vazio">
            {topicosIniciais.length ? <>
              <p>Olá! Pergunte do seu jeito sobre os dados do Puma (posso montar tabelas e gerar PDF ou Excel), ou escolha um assunto:</p>
              {cardTopicos(topicosIniciais)}
            </> : <>
              <p>Olá! Faça uma pergunta sobre os dados do Puma. Posso montar tabelas e gerar PDF ou Excel. Algumas ideias:</p>
              {chips(sugestoesIniciais)}
            </>}
          </div>
        )}
        {conversa.map((m, i) => (
          <Fragment key={i}>
            {m.papel === "usuario" || m.erro
              ? <div className={"chat-msg " + (m.papel === "usuario" ? "eu" : "erro")}>{m.texto}{m.tabela && <TabelaChat t={m.tabela} />}</div>
              : <div className="chat-msg ia" dangerouslySetInnerHTML={{ __html: markdown(m.texto) + (m.tabela ? tabelaHtml(m.tabela) : "") }} />}
            {m.topicos && m.topicos.length > 0 && cardTopicos(m.topicos)}
            {i === conversa.length - 1 && m.sugestoes && m.sugestoes.length > 0 && chips(m.sugestoes)}
          </Fragment>
        ))}
        {ocupado && <div className="chat-msg ia chat-pensando">Consultando...</div>}
      </div>
      <form className="chat-form" onSubmit={(e) => { e.preventDefault(); perguntar(texto); }}>
        <textarea ref={campo} rows={1} maxLength={500} placeholder="Ex.: contas a receber vencidas" aria-label="Pergunta" value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); perguntar(texto); } }} />
        <button type="submit" className="btn primario" disabled={ocupado}>Enviar</button>
      </form>
      <div className="chat-rodape">Escreva do seu jeito (ex.: "quem me deve?") ou toque em Tópicos para ver as perguntas prontas.</div>
    </section>
  </>, document.body);
}
