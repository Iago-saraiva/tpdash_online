// Filtros das telas de dados: ficam na URL (dá para copiar o link), período do topo, atalhos de datas,
// escolha múltipla e o botão "Filtros" que recolhe tudo no celular.
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, baixar, type Codigo } from "../api";
import { iso } from "../formatos";
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

  return { form, aplicado, consulta, versao, set, aplicar, limpar, setForm };
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

/** Formulário de filtros. No celular fica recolhido atrás do botão "Filtros". */
export function FormFiltros({ f, children, acoes = true, aoLimpar }: { f: Filtros; children: ReactNode; acoes?: boolean; aoLimpar?: () => void }) {
  const celular = typeof window !== "undefined" && window.matchMedia("(max-width: 760px)").matches;
  const [recolhido, setRecolhido] = useState(celular);
  const enviar = (e: FormEvent) => {
    e.preventDefault();
    if (celular) setRecolhido(true);
    f.aplicar();
  };
  return (
    <>
      {celular && (
        <button type="button" className="btn filtros-toggle" onClick={() => setRecolhido((r) => !r)}>
          {recolhido ? "Filtros ▾" : "Esconder filtros ▴"}
        </button>
      )}
      <form className={"filtros" + (recolhido ? " recolhido" : "")} autoComplete="off" onSubmit={enviar}>
        {children}
        {acoes && (
          <div className="acoes">
            <button type="button" className="btn" onClick={() => (aoLimpar ? aoLimpar() : f.limpar())}>Limpar</button>
            <button className="btn primario">Aplicar</button>
          </div>
        )}
      </form>
    </>
  );
}

/** Campo de texto ligado ao filtro (aplica só no Aplicar/Enter). */
export function Texto({ f, nome, ...resto }: { f: Filtros; nome: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return <input name={nome} value={f.form[nome] || ""} onChange={(e) => f.set(nome, e.target.value)} {...resto} />;
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
      <div className="multi" ref={caixa} onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); abrir(false); } }}>
        <button type="button" className={"multi-botao campo" + (aberto ? " aberto" : "")} aria-haspopup="listbox"
          title={nomes.join(", ") || vazio} onClick={(e) => { e.stopPropagation(); abrir(!aberto); }}>{texto}</button>
        <div className="multi-painel" hidden={!aberto}>
          <input ref={buscaRef} className="campo" placeholder="Buscar…" value={q} onChange={(e) => setQ(e.target.value)} />
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
