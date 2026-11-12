// Filtros das telas de dados: ficam na URL (dá para copiar o link), período do topo, atalhos de datas,
// escolha múltipla e o botão "Filtros" que recolhe tudo no celular.
import { Children, createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, baixar, type Codigo } from "../api";
import { fmtData, iso } from "../formatos";
import { datasPeriodo, useNav, usePeriodo } from "../navegacao";
import { useAvisar } from "./Avisos";

export type Valores = Record<string, string>;

/** junta os filtros preenchidos num "a=1&b=2" (vazios ficam de fora) */
export function paraBusca(v: Valores) {
  const p = new URLSearchParams();
  Object.entries(v).forEach(([k, x]) => { if (x !== "" && x !== undefined && x !== null) p.set(k, x); });
  return p;
}

/**
 * Estado dos filtros de uma tela.
 *  - `form`: o que está nos campos agora; `aplicado`: o que foi pedido ao servidor (vai para a URL).
 *  - `periodo`: a tela segue o período do topo (ini/fim), como Movimentos e Financeiro.
 */
export function useFiltros(padrao: Valores, op: { periodo?: boolean } = {}) {
  const { busca } = useNav();
  const { periodo } = usePeriodo();
  const inicial = () => {
    const url = new URLSearchParams(busca);
    const v: Valores = { ...padrao };
    url.forEach((x, k) => { if (k in padrao) v[k] = x; });      // só os campos desta tela, como antes
    if (op.periodo && !url.has("ini")) [v.ini, v.fim] = datasPeriodo(periodo);
    return v;
  };
  const [form, setForm] = useState<Valores>(inicial);
  const [aplicado, setAplicado] = useState<Valores>(form);
  const [versao, setVersao] = useState(0);           // "Aplicar" de novo com os mesmos filtros também recarrega

  const atual = useRef(form);
  atual.current = form;
  const aplicar = useCallback((mudar?: Valores) => {
    const novo = { ...atual.current, ...(mudar || {}) };
    atual.current = novo;
    setForm(novo); setAplicado(novo); setVersao((n) => n + 1);
  }, []);
  const set = useCallback((k: string, v: string) => {
    atual.current = { ...atual.current, [k]: v };
    setForm(atual.current);
  }, []);
  const limpar = useCallback((manter: Valores = {}) => {
    const novo = { ...padrao, ...manter };
    setForm(novo); setAplicado(novo); setVersao((n) => n + 1);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // período do topo mudou: usa as datas dele
  const primeiro = useRef(true);
  useEffect(() => {
    if (primeiro.current) { primeiro.current = false; return; }
    if (op.periodo) { const [ini, fim] = datasPeriodo(periodo); aplicar({ ini, fim }); }
  }, [periodo]);  // eslint-disable-line react-hooks/exhaustive-deps

  // filtros aplicados vão para a URL (sem criar outra entrada no histórico)
  const consulta = paraBusca(aplicado).toString();
  useEffect(() => {
    history.replaceState(null, "", location.pathname + (consulta ? "?" + consulta : ""));
  }, [consulta]);

  return { form, aplicado, consulta, versao, set, aplicar, limpar, setForm, padrao };
}
export type Filtros = ReturnType<typeof useFiltros>;

/**
 * Busca os dados da tela sempre que os filtros aplicados mudam.
 * Devolve os últimos dados e se está carregando (a tela antiga fica visível, esmaecida).
 */
export function useDados<T>(url: string, f: Filtros, pronto = true) {
  const avisar = useAvisar();
  const [dados, setDados] = useState<T | null>(null);
  const [carregando, setCarregando] = useState(false);
  useEffect(() => {
    if (!pronto) return;
    let vivo = true;
    setCarregando(true);
    api<T>(url + "?" + f.consulta)
      .then((d) => { if (vivo) setDados(d); })
      .catch((e) => { if (vivo) avisar(e.message); })
      .finally(() => { if (vivo) setCarregando(false); });
    return () => { vivo = false; };
  }, [url, f.consulta, f.versao, pronto, avisar]);
  return { dados, carregando };
}

/** Dentro do formulário de filtros os campos aplicam sozinhos (listas na hora, textos depois de uma pausa). */
const AutoCtx = createContext(false);

interface Chip { nome: string; rot: string; valor: string }

/** Lê, nos campos do formulário, o rótulo e o texto de cada filtro preenchido (diferente do padrão). */
function lerChips(form: HTMLFormElement, f: Filtros, semChip: string[]): Chip[] {
  const vistos = new Set<string>();
  const lista: Chip[] = [];
  form.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[name]").forEach((el) => {
    const nome = el.name;
    if (!nome || vistos.has(nome) || semChip.includes(nome)) return;
    const v = f.form[nome] || "";
    if (v === (f.padrao[nome] || "")) return;
    vistos.add(nome);
    const lab = el.closest("label");
    if (el instanceof HTMLInputElement && el.type === "checkbox") {
      lista.push({ nome, rot: "", valor: (lab?.textContent || nome).trim() });
      return;
    }
    const rot = (el.closest(".filtro-rot")?.querySelector("span")?.textContent
      || (lab?.childNodes[0]?.nodeType === 3 ? lab.childNodes[0].textContent : "") || nome).trim();
    let valor = v;
    if (el instanceof HTMLSelectElement) valor = el.selectedOptions[0]?.text || v;
    else if (el.type === "hidden") { const n = v.split(",").filter(Boolean); valor = n.length <= 2 ? n.join(", ") : `${n.length} selecionados`; }
    lista.push({ nome, rot, valor });
  });
  return lista;
}

/**
 * Formulário de filtros: os campos principais ficam à mostra e o resto em "Mais filtros".
 * Aplica sozinho; os filtros em uso aparecem como etiquetas que se removem com um clique.
 * No celular fica recolhido atrás do botão "Filtros".
 */
export function FormFiltros({ f, children, acoes = true, aoLimpar, principais = 4, extra, semChip = ["ini", "fim", "aba"] }: {
  f: Filtros; children: ReactNode; acoes?: boolean; aoLimpar?: () => void; principais?: number; extra?: ReactNode; semChip?: string[];
}) {
  const celular = typeof window !== "undefined" && window.matchMedia("(max-width: 760px)").matches;
  const [recolhido, setRecolhido] = useState(celular);
  const [mais, setMais] = useState(false);
  const [chips, setChips] = useState<Chip[]>([]);
  const [ocultos, setOcultos] = useState(0);
  const ref = useRef<HTMLFormElement>(null);
  const itens = Children.toArray(children);
  const dividir = !celular && itens.length - principais > 1;
  const visiveis = dividir ? itens.slice(0, principais) : itens;
  const resto = dividir ? itens.slice(principais) : [];

  useLayoutEffect(() => {
    if (!ref.current) return;
    const novos = lerChips(ref.current, f, semChip);
    if (JSON.stringify(novos) !== JSON.stringify(chips)) setChips(novos);
    const n = novos.filter((c) => ref.current?.querySelector(`.filtros-mais [name="${c.nome}"]`)).length;
    if (n !== ocultos) setOcultos(n);
  });

  const enviar = (e: FormEvent) => { e.preventDefault(); f.aplicar(); };
  // Teclado: ENTER aplica e passa para o próximo campo (SHIFT+ENTER volta); TAB segue a ordem normal.
  const teclas = (e: React.KeyboardEvent<HTMLFormElement>) => {
    const alvo = e.target as HTMLElement;
    if (e.key !== "Enter" || e.ctrlKey || e.altKey || e.metaKey) return;
    if (alvo.closest(".multi-painel, .periodo-painel")) return;          // painéis abertos tratam o próprio ENTER
    if (!(alvo instanceof HTMLInputElement || alvo instanceof HTMLSelectElement)) return;
    if (alvo instanceof HTMLInputElement && alvo.type === "checkbox") return;
    e.preventDefault();
    f.aplicar();
    const campos = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(
      "input:not([type=hidden]):not([tabindex='-1']), select, .multi-botao, .periodo-botao"))
      .filter((x) => !x.closest(".multi-painel, .periodo-painel, .filtros-mais:not(.aberto)") && x.offsetParent !== null);
    const i = campos.indexOf(alvo);
    const prox = campos[i + (e.shiftKey ? -1 : 1)];
    if (prox) prox.focus();
  };
  const limparTudo = () => (aoLimpar ? aoLimpar() : f.limpar());
  const tirar = (nome: string) => f.aplicar({ [nome]: f.padrao[nome] || "" });
  return (
    <AutoCtx.Provider value={true}>
      {celular && (
        <button type="button" className={"btn filtros-toggle" + (recolhido ? "" : " aberto")} onClick={() => setRecolhido((r) => !r)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" /></svg>
          {recolhido ? "Filtros" : "Esconder filtros"}{chips.length > 0 && <span className="filtros-conta">{chips.length}</span>}
        </button>
      )}
      <form ref={ref} className={"filtros" + (recolhido ? " recolhido" : "")} autoComplete="off" onSubmit={enviar} onKeyDown={teclas}>
        <div className="filtros-linha">
          {visiveis}
          {(resto.length > 0 || extra || acoes) && (
            <div className="filtros-botoes">
              {resto.length > 0 && (
                <button type="button" className={"btn filtros-mais-btn" + (mais ? " aberto" : "")} aria-expanded={mais} onClick={() => setMais(!mais)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" /></svg>
                  Mais filtros{ocultos > 0 && <span className="filtros-conta">{ocultos}</span>}
                </button>
              )}
              {extra}
            </div>
          )}
        </div>
        {resto.length > 0 && (
          <div className={"filtros-mais" + (mais ? " aberto" : "")} aria-hidden={!mais}>
            <div className="filtros-mais-dentro">{resto}</div>
          </div>
        )}
        {acoes && chips.length > 0 && (
          <div className="filtros-chips" aria-label="Filtros em uso">
            {chips.map((c) => (
              <button type="button" key={c.nome} className="chip-filtro" title="Remover este filtro" onClick={() => tirar(c.nome)}>
                {c.rot && <span className="chip-rot">{c.rot}:</span>} {c.valor}<span className="chip-x" aria-hidden="true">×</span>
              </button>
            ))}
            {chips.length > 1 && <button type="button" className="chip-limpar" onClick={limparTudo}>Limpar tudo</button>}
          </div>
        )}
        <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
      </form>
    </AutoCtx.Provider>
  );
}

/** Campo de texto ligado ao filtro (aplica só no Aplicar/Enter). */
export function Texto({ f, nome, ...resto }: { f: Filtros; nome: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const auto = useContext(AutoCtx);
  const espera = useRef(0);
  useEffect(() => () => window.clearTimeout(espera.current), []);
  return (
    <span className="campo-busca">
      <input name={nome} value={f.form[nome] || ""} {...resto}
        onChange={(e) => {
          f.set(nome, e.target.value);
          if (auto) { window.clearTimeout(espera.current); espera.current = window.setTimeout(() => f.aplicar(), 650); }
        }}
        onKeyDown={(e) => { if (e.key === "Enter") window.clearTimeout(espera.current); }} />
      {f.form[nome] && auto && (
        <button type="button" className="campo-limpar" aria-label="Limpar" tabIndex={-1}
          onClick={() => { window.clearTimeout(espera.current); f.aplicar({ [nome]: f.padrao[nome] || "" }); }}>×</button>
      )}
    </span>
  );
}

/** Data (aplica só no Aplicar/Enter). */
export function Data({ f, nome }: { f: Filtros; nome: string }) {
  return <input type="date" name={nome} value={f.form[nome] || ""} onChange={(e) => f.set(nome, e.target.value)} />;
}

/** Lista de opções. `auto`: aplica ao trocar. `lista`: códigos vindos do servidor. */
export function Escolha({ f, nome, lista, vazio, auto, className, children }: {
  f: Filtros; nome: string; lista?: Codigo[]; vazio?: string; auto?: boolean; className?: string; children?: ReactNode;
}) {
  const valor = f.form[nome] || "";
  const ctxAuto = useContext(AutoCtx);
  auto = auto ?? ctxAuto;
  const conhecido = !lista || !valor || lista.some((x) => x.cod === valor);
  return (
    <select name={nome} className={className} value={valor}
      onChange={(e) => (auto ? f.aplicar({ [nome]: e.target.value }) : f.set(nome, e.target.value))}>
      {vazio !== undefined && <option value="">{vazio}</option>}
      {children}
      {lista && lista.map((x) => <option key={x.cod} value={x.cod}>{x.nome ? `${x.cod} - ${x.nome}` : x.cod}</option>)}
      {!conhecido && <option value={valor}>{valor}</option>}
    </select>
  );
}

/** Caixa de marcar (valor "1" quando marcada). */
export function Marcar({ f, nome, auto, children }: { f: Filtros; nome: string; auto?: boolean; children: ReactNode }) {
  const ctxAuto = useContext(AutoCtx);
  auto = auto ?? ctxAuto;
  return (
    <label className="check">
      <input type="checkbox" name={nome} value="1" checked={f.form[nome] === "1"}
        onChange={(e) => (auto ? f.aplicar({ [nome]: e.target.checked ? "1" : "" }) : f.set(nome, e.target.checked ? "1" : ""))} /> {children}
    </label>
  );
}

/** Atalhos de período: Mês, 60 dias, 90 dias, Ano, 12 meses. */
export function Atalhos({ f }: { f: Filtros }) {
  const hoje = new Date();
  const ops: [string, () => [Date, Date]][] = [
    ["Mês", () => [new Date(hoje.getFullYear(), hoje.getMonth(), 1), hoje]],
    ["60 dias", () => [new Date(hoje.getTime() - 59 * 864e5), hoje]],
    ["90 dias", () => [new Date(hoje.getTime() - 89 * 864e5), hoje]],
    ["Ano", () => [new Date(hoje.getFullYear(), 0, 1), hoje]],
    ["12 meses", () => [new Date(hoje.getFullYear(), hoje.getMonth() - 11, 1), hoje]],
  ];
  return (
    <div className="presets">
      {ops.map(([rot, fn]) => (
        <button key={rot} type="button" className="btn pequeno" onClick={() => { const [a, z] = fn(); f.aplicar({ ini: iso(a), fim: iso(z) }); }}>{rot}</button>
      ))}
    </div>
  );
}

const ATALHOS: [string, () => [Date, Date]][] = [
  ["Este mês", () => { const h = new Date(); return [new Date(h.getFullYear(), h.getMonth(), 1), h]; }],
  ["Mês passado", () => { const h = new Date(); return [new Date(h.getFullYear(), h.getMonth() - 1, 1), new Date(h.getFullYear(), h.getMonth(), 0)]; }],
  ["Últimos 60 dias", () => { const h = new Date(); return [new Date(h.getTime() - 59 * 864e5), h]; }],
  ["Últimos 90 dias", () => { const h = new Date(); return [new Date(h.getTime() - 89 * 864e5), h]; }],
  ["Este ano", () => { const h = new Date(); return [new Date(h.getFullYear(), 0, 1), h]; }],
  ["Últimos 12 meses", () => { const h = new Date(); return [new Date(h.getFullYear(), h.getMonth() - 11, 1), h]; }],
];

/**
 * Período num botão só: mostra "01/11/2026 – 30/11/2026" (ou o nome do atalho) e abre um painel com os atalhos
 * e as duas datas. `ini`/`fim`: datas que o servidor usou quando o filtro está vazio.
 */
export function Periodo({ f, ini, fim, rotulo = "Período" }: { f: Filtros; ini?: string; fim?: string; rotulo?: string }) {
  const [aberto, setAberto] = useState(false);
  const vi = f.form.ini || ini || "", vf = f.form.fim || fim || "";
  const [a, setA] = useState(vi), [z, setZ] = useState(vf);
  const caixa = useRef<HTMLDivElement>(null);
  useEffect(() => { if (aberto) { setA(vi); setZ(vf); } }, [aberto]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => { if (!caixa.current?.contains(e.target as Node)) setAberto(false); };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, [aberto]);
  const ativo = ATALHOS.find(([, fn]) => { const [x, y] = fn(); return iso(x) === vi && iso(y) === vf; });
  const texto = ativo ? ativo[0] : vi || vf ? `${vi ? fmtData(vi) : "…"} – ${vf ? fmtData(vf) : "…"}` : "Qualquer data";
  const botao = useRef<HTMLButtonElement>(null);
  const ir = (x: string, y: string) => { f.aplicar({ ini: x, fim: y }); setAberto(false); botao.current?.focus(); };
  useEffect(() => { if (aberto) caixa.current?.querySelector<HTMLElement>(".chip-periodo.ativo, .chip-periodo")?.focus(); }, [aberto]);
  return (
    <div className="filtro-rot filtro-periodo"><span>{rotulo}</span>
      <div className="periodo" ref={caixa} onKeyDown={(e) => {
        if (e.key === "Escape" && aberto) { e.stopPropagation(); setAberto(false); botao.current?.focus(); }
        if (e.key === "ArrowDown" && !aberto && e.target === botao.current) { e.preventDefault(); setAberto(true); }
        if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && (e.target as HTMLElement).classList.contains("chip-periodo")) {
          e.preventDefault();
          const l = Array.from(caixa.current?.querySelectorAll<HTMLElement>(".chip-periodo") || []);
          const i = l.indexOf(e.target as HTMLElement);
          l[(i + (e.key === "ArrowRight" ? 1 : -1) + l.length) % l.length]?.focus();
        }
      }}>
        <button ref={botao} type="button" className={"periodo-botao campo" + (aberto ? " aberto" : "")} aria-haspopup="dialog" aria-expanded={aberto}
          title={vi || vf ? `${fmtData(vi)} a ${fmtData(vf)}` : ""} onClick={() => setAberto(!aberto)}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
          <span className="periodo-texto">{texto}</span>
        </button>
        {aberto && (
          <div className="periodo-painel" role="dialog" aria-label={rotulo}>
            <div className="periodo-atalhos">
              {ATALHOS.map(([rot, fn]) => (
                <button key={rot} type="button" className={"chip-periodo" + (ativo?.[0] === rot ? " ativo" : "")}
                  onClick={() => { const [x, y] = fn(); ir(iso(x), iso(y)); }}>{rot}</button>
              ))}
            </div>
            <div className="periodo-datas">
              <label>De<input type="date" value={a} onChange={(e) => setA(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.currentTarget.closest(".periodo-datas")?.querySelectorAll("input")[1] as HTMLInputElement | undefined)?.focus(); } }} /></label>
              <label>Até<input type="date" value={z} onChange={(e) => setZ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (a && z && a <= z) ir(a, z); } }} /></label>
            </div>
            <div className="periodo-acoes">
              <button type="button" className="btn" onClick={() => setAberto(false)}>Cancelar</button>
              <button type="button" className="btn primario" disabled={!a || !z || a > z} onClick={() => ir(a, z)}>Aplicar período</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Escolha múltipla com caixas de seleção (ex.: tipos de documento). Guarda os códigos separados por vírgula,
 * então funciona com os filtros na URL, Limpar e exportação. Aplica ao fechar, se mudou algo.
 */
export function MultiEscolha({ f, nome, rotulo, lista, vazio, unidade = "tipos selecionados" }: {
  f: Filtros; nome: string; rotulo: string; lista: Codigo[]; vazio: string; unidade?: string;
}) {
  const [aberto, setAberto] = useState(false);
  const [q, setQ] = useState("");
  const antes = useRef("");
  const caixa = useRef<HTMLDivElement>(null);
  const buscaRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (aberto) buscaRef.current?.focus(); }, [aberto]);
  const valor = f.form[nome] || "";
  const sel = valor.split(",").filter(Boolean);
  const visiveis = lista.filter((x) => !q.trim() || (x.nome ? `${x.cod} - ${x.nome}` : x.cod).toLowerCase().includes(q.trim().toLowerCase()));

  const abrir = (s: boolean) => {
    if (s === aberto) return;
    setAberto(s);
    if (s) { antes.current = valor; setQ(""); }
    else if (valor !== antes.current) f.aplicar();      // aplica ao fechar
  };
  // clique fora fecha
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => { if (!caixa.current?.contains(e.target as Node)) abrir(false); };
    document.addEventListener("click", fora);
    return () => document.removeEventListener("click", fora);
  });
  const gravar = (lista2: string[]) => f.set(nome, lista2.join(","));
  const marcar = (v: boolean) => {
    const vis = new Set(visiveis.map((x) => x.cod));
    gravar(v ? [...new Set([...sel, ...vis])] : sel.filter((c) => !vis.has(c)));
  };
  const nomes = sel;          // mostra os códigos, como antes
  const texto = !sel.length ? vazio : sel.length <= 2 ? nomes.join(", ") : `${sel.length} ${unidade}`;
  return (
    <div className="filtro-rot"><span>{rotulo}</span>
      <input type="hidden" name={nome} value={valor} />
      <div className="multi" ref={caixa} onKeyDown={(e) => {
        if (e.key === "Escape" && aberto) { e.stopPropagation(); abrir(false); caixa.current?.querySelector<HTMLElement>(".multi-botao")?.focus(); }
        if (e.key === "ArrowDown" && !aberto && (e.target as HTMLElement).classList.contains("multi-botao")) { e.preventDefault(); abrir(true); }
        if (e.key === "Enter" && (e.target as HTMLInputElement).type === "checkbox") { e.preventDefault(); (e.target as HTMLInputElement).click(); }
        if ((e.key === "ArrowDown" || e.key === "ArrowUp") && aberto && (e.target as HTMLElement).closest(".multi-painel")) {
          e.preventDefault();
          const l = Array.from(caixa.current?.querySelectorAll<HTMLElement>(".multi-painel > input, .multi-itens label:not([hidden]) input") || []);
          const i = l.indexOf(e.target as HTMLElement);
          l[Math.max(0, Math.min(l.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
        }
      }}>
        <button type="button" className={"multi-botao campo" + (aberto ? " aberto" : "")} aria-haspopup="listbox"
          title={nomes.join(", ") || vazio} onClick={(e) => { e.stopPropagation(); abrir(!aberto); }}>{texto}</button>
        <div className="multi-painel" hidden={!aberto}>
          <input ref={buscaRef} className="campo" placeholder="Buscar… (ENTER fecha, ↓ vai para a lista)" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              if (q.trim() && visiveis.length === 1) {       // um só resultado: ENTER marca/desmarca
                const c = visiveis[0].cod; gravar(sel.includes(c) ? sel.filter((x) => x !== c) : [...sel, c]); setQ("");
              } else { abrir(false); caixa.current?.querySelector<HTMLElement>(".multi-botao")?.focus(); }
            }} />
          <div className="multi-acoes">
            <button type="button" className="btn pequeno" onClick={() => marcar(true)}>Marcar todos</button>
            <button type="button" className="btn pequeno" onClick={() => marcar(false)}>Limpar</button>
          </div>
          <div className="multi-itens">
            {lista.map((x) => (
              <label key={x.cod} className="check" hidden={!visiveis.includes(x)}>
                <input type="checkbox" value={x.cod} checked={sel.includes(x.cod)}
                  onChange={(e) => gravar(e.target.checked ? [...sel, x.cod] : sel.filter((c) => c !== x.cod))} />
                {" " + (x.nome ? `${x.cod} - ${x.nome}` : x.cod)}
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Botões Excel e PDF: baixam a tabela com os filtros que estão nos campos. */
export function Exportar({ url, f }: { url: string; f: Filtros }) {
  const avisar = useAvisar();
  const [ocupado, setOcupado] = useState("");
  const ir = async (fmt: string) => {
    const p = paraBusca(f.form);
    p.set("formato", fmt);
    setOcupado(fmt);
    try { await baixar(url + "?" + p); } catch (e) { avisar((e as Error).message); } finally { setOcupado(""); }
  };
  return <>
    <button className="btn pequeno" disabled={ocupado === "xlsx"} onClick={() => ir("xlsx")}>Excel</button>
    <button className="btn pequeno" disabled={ocupado === "pdf"} onClick={() => ir("pdf")}>PDF</button>
  </>;
}
