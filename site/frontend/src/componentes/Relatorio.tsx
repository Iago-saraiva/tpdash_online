// Peças dos relatórios: filtros :NOME, visões com layout (indicadores, gráfico, tabela com grupos),
// editor de layout e o gráfico livre da Consulta SQL.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, opcoesGerais, type Codigo } from "../api";
import { F, MOEDA, NUMFMT, fmtData, fmtValor, rotuloCol } from "../formatos";
import { Kpis } from "./Kpis";
import { Barras, Colunas, Linhas, Rosca, type ItemBarra } from "./Graficos";
import { Modal } from "./Gaveta";
import { Tabela, type DadosTabela, type DefColuna, type Linha } from "./Tabela";
import { MultiEscolha, type Filtros } from "./Filtros";

/* ------------------------------------------------------------ avisos dentro da gaveta (somem em 9 s) */
export function useAvisosLocais(): [ReactNode, (msg: string, tipo?: string) => void] {
  const [lista, setLista] = useState<{ id: number; msg: string; tipo: string }[]>([]);
  const n = useRef(0);
  const avisar = (msg: string, tipo = "erro") => {
    const id = ++n.current;
    setLista((l) => [{ id, msg, tipo }, ...l]);
    setTimeout(() => setLista((l) => l.filter((a) => a.id !== id)), 9000);
  };
  return [<>{lista.map((a) => <div key={a.id} className={"aviso " + a.tipo}>{a.msg}</div>)}</>, avisar];
}

/* ------------------------------------------------------------ parâmetros :NOME */
export function parametrosSQL(sql: string) {
  const vistos: string[] = [];
  const re = /'(?:[^']|'')*'|"(?:[^"]|"")*"|--[^\n]*|\/\*[\s\S]*?\*\/|:([A-Za-z_][A-Za-z0-9_]*)/g;
  let m;
  while ((m = re.exec(sql || ""))) {
    if (m[1] && !vistos.includes(m[1].toUpperCase())) vistos.push(m[1].toUpperCase());
  }
  return vistos;
}
export function tipoPorNome(n: string) {
  return /(^|_)(DATA|DT|INI|INICIAL|FIM|FINAL|EMISSAO|VENCIMENTO)(_|$)/.test(n) ? "data" : "texto";
}
export interface Param {
  nome: string; rotulo: string; tipo: string; obrigatorio?: boolean; padrao?: string | null;
  opcoes?: [string, string][]; escolha?: string; prefixo?: string;
}
/** parâmetros simples a partir dos :NOME do SQL */
export const paramsDoSQL = (sql: string): Param[] =>
  parametrosSQL(sql).map((n) => ({ nome: n, rotulo: n.replace(/_/g, " ").toLowerCase(), tipo: tipoPorNome(n) }));

/** valores iniciais: o que já foi digitado, senão o padrão do parâmetro */
export function valoresIniciais(lista: Param[], anteriores: Record<string, string> = {}) {
  const v: Record<string, string> = {};
  lista.forEach((p) => {
    const x = anteriores[p.nome] !== undefined ? anteriores[p.nome] : p.padrao;
    v[p.nome] = x === null || x === undefined ? "" : String(x);
  });
  return v;
}

/** formulário dos parâmetros (vazio quando não há nenhum) */
export function Parametros({ lista, valores, mudar, id, style }: {
  lista: Param[]; valores: Record<string, string>; mudar: (v: Record<string, string>) => void; id?: string; style?: React.CSSProperties;
}) {
  const [filiais, setFiliais] = useState<Codigo[] | null>(null);
  const [tipos, setTipos] = useState<Codigo[] | null>(null);
  const precisa = lista.some((p) => p.escolha === "filiais" || p.escolha === "tipos_mov");
  useEffect(() => {
    if (!precisa) return;
    opcoesGerais().then((o) => { setFiliais(o.filiais || []); setTipos(o.tipos || []); }).catch(() => {});
  }, [precisa]);
  const atual = useRef(valores);
  atual.current = valores;
  const set = (k: string, x: string) => mudar({ ...atual.current, [k]: x });
  if (!lista.length) return <div id={id} style={style} />;
  return (
    <div id={id} style={style} className="form-grade params-grade">
      {lista.map((p) => {
        const rot = p.rotulo + (p.obrigatorio ? " *" : "");
        const v = valores[p.nome] ?? "";
        if (p.tipo === "opcao") {
          const ops = p.opcoes || [];
          const val = ops.some(([x]) => x === v) ? v : (ops[0]?.[0] ?? "");
          return <label key={p.nome}><span>{rot}</span>
            <select className="campo" data-nome={p.nome} value={val} onChange={(e) => set(p.nome, e.target.value)}>
              {ops.map(([x, r]) => <option key={x} value={x}>{r}</option>)}
            </select></label>;
        }
        if (p.escolha === "filiais") {
          const lst = filiais || [];
          return <label key={p.nome}><span>{rot}</span>
            <select className="campo" data-nome={p.nome} value={v} onChange={(e) => set(p.nome, e.target.value)}>
              <option value="">Todas</option>
              {lst.map((x) => <option key={x.cod} value={x.cod}>{x.nome ? `${x.cod} - ${x.nome}` : x.cod}</option>)}
              {v && !lst.some((x) => x.cod === v) && <option value={v}>{v}</option>}
            </select></label>;
        }
        if (p.escolha === "tipos_mov") {
          // um ou mais tipos de movimento (caixas de seleção)
          const f = { form: valores, set, aplicar: () => {} } as unknown as Filtros;
          const lst = (tipos || []).filter((x) => !p.prefixo || String(x.cod).startsWith(p.prefixo));
          return <MultiEscolha key={p.nome} f={f} nome={p.nome} rotulo={rot} lista={lst}
            vazio={p.prefixo ? `Todos os ${p.prefixo}.x` : "Todos os tipos"} />;
        }
        const ph = p.tipo === "lista" ? (/CFO|CLI|FOR/.test(p.nome) ? "ex.: C000001, F000433" : /TMV|TIPO_MOV/.test(p.nome) ? "ex.: 2.2.21, 2.1.05" : "separe por vírgula") : undefined;
        return <label key={p.nome}><span>{rot}</span>
          <input className="campo" type={p.tipo === "data" ? "date" : "text"} inputMode={p.tipo === "numero" ? "decimal" : undefined}
            placeholder={ph} title={p.obrigatorio ? undefined : "Deixe vazio para não filtrar"} data-nome={p.nome}
            value={v} onChange={(e) => set(p.nome, e.target.value)} /></label>;
      })}
    </div>
  );
}

/* ------------------------------------------------------------ visões com layout */
export interface ColunaVisao extends DefColuna { campo: string }
export interface Visao {
  nome: string; titulo?: string; oculta?: boolean; erro?: string; aviso?: string;
  colunas: (ColunaVisao | string)[]; linhas: Linha[]; truncado?: boolean;
  colunas_originais?: string[]; config_colunas?: { campo: string; rotulo: string; visivel: boolean; formato_salvo?: string; total: string; abaixo?: boolean }[];
  indicadores?: { rotulo: string; valor: unknown; formato: string }[];
  grafico?: { tipo: string; titulo: string; formato: string; pontos: { rotulo: string; valor: number }[] };
  blocos?: { t: string; nivel: number; rotulo?: string; valor?: unknown; qtd?: number; v: unknown[] }[];
  totais?: unknown[];
}
export interface RespVisoes { visoes: Visao[]; layout?: Layout; pode_editar?: boolean; colunas?: string[]; linhas?: Linha[]; truncado?: boolean }

export const SERVIDOR_ANTIGO = "O servidor do painel ainda está rodando a versão anterior do programa, por isso o editor de layout não funciona. " +
  "No servidor, rode reiniciar_painel.bat (botão direito > Executar como administrador) e depois aperte Ctrl+F5 aqui.";
export const respostaAntiga = (d: RespVisoes | null) => !!(d && d.visoes && d.visoes.length && d.visoes[0].colunas_originais === undefined);

export function Visoes({ visoes }: { visoes: Visao[] }) {
  const vis = visoes.filter((v) => !v.oculta);
  const ocultas = visoes.length - vis.length;
  const [i, setI] = useState(() => Math.max(0, vis.findIndex((v) => v.linhas && v.linhas.length)));
  if (!vis.length) return <div className="aviso atencao">Todas as visões estão ocultas no layout deste relatório. Use "Editar layout" para mostrar.</div>;
  const atual = vis[Math.min(i, vis.length - 1)];
  return <>
    {(vis.length > 1 || ocultas > 0) && (
      <div className="abas">
        {vis.map((v, k) => <button key={k} className={k === i ? "ativa" : ""} onClick={() => setI(k)}>{`${v.titulo || v.nome} (${v.erro ? "erro" : (v.linhas || []).length})`}</button>)}
        {ocultas > 0 && <span className="nota">{` ${ocultas} oculta(s) pelo layout`}</span>}
      </div>
    )}
    <div style={{ marginTop: 12 }}><VisaoTela key={i} v={atual} /></div>
  </>;
}

function VisaoTela({ v }: { v: Visao }) {
  if (v.erro) return <div className="aviso erro">{v.erro}</div>;
  const av = v.aviso ? <div className="aviso atencao">{v.aviso}</div> : null;
  if (v.colunas_originais === undefined) {   // servidor ainda na versão anterior
    if (!v.colunas || !v.colunas.length) return av;
    return <>{av}<div><Tabela dados={v as unknown as DadosTabela} truncado={v.truncado} porPagina={100} /></div></>;
  }
  if (!v.colunas || !v.colunas.length) {
    return <>{av}{v.colunas_originais && v.colunas_originais.length ? <div className="aviso atencao">Nenhuma coluna visível no layout desta visão.</div> : null}</>;
  }
  const cols = v.colunas as ColunaVisao[];
  return <>
    {av}
    {v.indicadores && v.indicadores.length > 0 && (
      <div className="kpis" style={{ marginBottom: 14 }}>
        <Kpis lista={v.indicadores.map((k) => ({ rotulo: k.rotulo, valor: k.formato === "moeda" && typeof k.valor === "number" ? F.moeda(k.valor) : fmtValor(k.formato, k.valor) || "—" }))} />
      </div>
    )}
    {v.grafico && v.grafico.pontos && v.grafico.pontos.length > 0 && (
      <div className="cartao" style={{ marginBottom: 14 }}>
        <div className="cartao-cab"><h2>{v.grafico.titulo}</h2></div>
        <div><GraficoPontos g={v.grafico} /></div>
      </div>
    )}
    <div>
      {v.blocos ? <TabelaGrupos v={v} cols={cols} />
        : <Tabela dados={{ colunas: cols.map((c) => c.campo), linhas: v.linhas }} truncado={v.truncado} porPagina={100} defs={cols} />}
    </div>
  </>;
}

/** gráfico com tipo e pontos já calculados (barras, colunas, linhas, rosca) */
function Grafico({ tipo, nome, pts, moeda }: { tipo: string; nome: string; pts: ItemBarra[]; moeda: boolean }) {
  const fmt = moeda ? F.moeda : F.numero;
  const serie = [{ nome, pontos: pts.map((p) => ({ rotulo: p.rotulo, valor: p.valor || 0 })) }];
  if (tipo === "linhas") return <Linhas series={serie} formato={fmt} moeda={moeda} area />;
  if (tipo === "colunas") return <Colunas series={serie} formato={fmt} moeda={moeda} />;
  if (tipo === "rosca") return <Rosca dados={pts} formato={fmt} compacto moeda={moeda} />;
  return <Barras dados={pts} formato={fmt} compacto={moeda} moeda={moeda} larguraRotulo={240} />;
}

function GraficoPontos({ g }: { g: NonNullable<Visao["grafico"]> }) {
  let pts: ItemBarra[] = g.pontos.slice();
  const juntar = (n: number) => {
    if (pts.length > n) {
      const resto = pts.slice(n - 1).reduce((a, p) => a + (p.valor || 0), 0);
      pts = pts.slice(0, n - 1).concat([{ rotulo: "Outros", valor: resto }]);
    }
  };
  if (g.tipo === "barras") juntar(15);
  if (g.tipo === "rosca") juntar(6);
  if (g.tipo === "colunas" && pts.length > 36) pts = pts.slice(-36);
  pts = pts.map((p) => ({ rotulo: /^\d{4}-\d{2}-\d{2}/.test(p.rotulo) ? fmtData(p.rotulo) : p.rotulo, valor: p.valor }));
  return <Grafico tipo={g.tipo} nome={g.titulo} pts={pts} moeda={g.formato === "moeda"} />;
}

/* tabela com grupos e subtotais (recolher/expandir clicando no grupo) */
const LIM = 6000;
const vazioOu = (x: unknown) => (x === null || x === undefined || x === "" ? "(vazio)" : (/^\d{4}-\d{2}-\d{2}/.test(String(x)) ? fmtData(x) : String(x)));

function TabelaGrupos({ v, cols }: { v: Visao; cols: ColunaVisao[] }) {
  const [fechados, setFechados] = useState<Set<string>>(new Set());
  const blocos = v.blocos || [];
  const nGrupos = blocos.filter((b) => b.t === "grupo" && b.nivel === 0).length;
  // colunas visuais (as marcadas "abaixo" ficam na mesma célula da anterior)
  const vis: number[][] = [];
  cols.forEach((c, j) => { if (c.abaixo && vis.length) vis[vis.length - 1].push(j); else vis.push([j]); });
  const numG = vis.map((gr) => gr.every((j) => NUMFMT.has(cols[j].formato)));

  // cada linha sabe de quais grupos faz parte (para esconder quando um deles estiver recolhido)
  const linhas: { b: (typeof blocos)[number]; id?: string; dentro: string[] }[] = [];
  const pilha: string[] = [];
  let gid = 0;
  blocos.slice(0, LIM).forEach((b) => {
    if (b.t === "grupo") {
      pilha.length = b.nivel;
      const id = "g" + (++gid);
      linhas.push({ b, id, dentro: pilha.slice() });
      pilha.push(id);
      return;
    }
    if (b.t === "subtotal") {
      // o subtotal fica visível mesmo com o grupo recolhido
      pilha.length = b.nivel + 1;
      linhas.push({ b, dentro: pilha.slice(0, b.nivel) });
      pilha.length = b.nivel;
      return;
    }
    linhas.push({ b, dentro: pilha.slice() });
  });
  const grupos0 = linhas.filter((l) => l.id && l.b.nivel === 0).map((l) => l.id as string);

  const celulas = (vals: unknown[], rotulo?: string) => vis.map((gr, k) => {
    if (k === 0 && rotulo && gr.every((j) => vals[j] === null || vals[j] === undefined)) return <td key={k} className={numG[k] ? "num" : undefined}>{rotulo}</td>;
    return <td key={k} className={numG[k] ? "num" : undefined}>
      {gr.map((j) => {
        const x = vals[j];
        return <div key={j} className={typeof x === "number" && x < 0 ? "neg" : undefined}
          title={typeof x === "string" && x.length > 40 ? x : undefined}>{fmtValor(cols[j].formato, x) || " "}</div>;
      })}
    </td>;
  });
  const alternar = (id: string) => setFechados((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return <>
    <div className="tabela-barra">
      <span className="info">{`${F.inteiro(v.linhas.length)} linhas em ${F.inteiro(nGrupos)} grupos` + (v.truncado ? " · limite atingido" : "")}</span>
      <button className="btn pequeno" onClick={() => setFechados((s) => new Set([...s, ...grupos0]))}>Recolher grupos</button>
      <button className="btn pequeno" onClick={() => setFechados(new Set())}>Expandir tudo</button>
    </div>
    <div className="tabela-wrap">
      <table className={"dados agrupada" + (vis.length < cols.length ? " empilhada" : "")}>
        <thead><tr>{vis.map((gr, k) => <th key={k} className={numG[k] ? "num" : ""} style={{ cursor: "default" }}>{gr.map((j) => <div key={j}>{cols[j].rotulo}</div>)}</th>)}</tr></thead>
        <tbody>
          {linhas.map((l, n) => {
            const escondida = l.dentro.some((g) => fechados.has(g));
            if (l.b.t === "grupo") {
              const fechado = fechados.has(l.id as string);
              return <tr key={n} className={`grupo n${l.b.nivel}` + (fechado ? " fechado" : "")} hidden={escondida} onClick={() => alternar(l.id as string)}>
                <td colSpan={vis.length}>{`${fechado ? "▸" : "▾"} ${l.b.rotulo}: ${vazioOu(l.b.valor)}`}<span className="qtd">{` ${l.b.qtd} ${l.b.qtd === 1 ? "linha" : "linhas"}`}</span></td>
              </tr>;
            }
            if (l.b.t === "subtotal") return <tr key={n} className={`subtotal n${l.b.nivel}`} hidden={escondida}>{celulas(l.b.v, `Subtotal ${vazioOu(l.b.valor)}`)}</tr>;
            return <tr key={n} hidden={escondida}>{celulas(l.b.v)}</tr>;
          })}
        </tbody>
        {v.totais && <tfoot><tr>{celulas(v.totais, "Total geral")}</tr></tfoot>}
      </table>
    </div>
    {blocos.length > LIM && <div className="aviso atencao">{`Mostrando parte do relatório na tela. Exporte em Excel ou PDF para ver todos os ${F.inteiro(v.linhas.length)} registros.`}</div>}
  </>;
}

/* ------------------------------------------------------------ editor de layout */
const OPC_FORMATO: [string, string][] = [["auto", "Automático"], ["texto", "Texto"], ["inteiro", "Inteiro"], ["numero", "Número"], ["moeda", "Valor (0,00)"], ["percentual", "Percentual"], ["data", "Data"], ["datahora", "Data e hora"]];
const OPC_TOTAL: [string, string][] = [["nenhum", "—"], ["soma", "Soma"], ["media", "Média"], ["contagem", "Contagem"], ["minimo", "Mínimo"], ["maximo", "Máximo"]];
const OPC_GRAFICO: [string, string][] = [["nenhum", "Sem gráfico"], ["barras", "Barras (ranking)"], ["colunas", "Colunas"], ["linhas", "Linhas (evolução)"], ["rosca", "Rosca (participação)"]];

interface ColLay { campo: string; rotulo: string; visivel: boolean; formato: string; total: string; abaixo: boolean }
interface VisLay {
  titulo: string; oculta: boolean; colunas: ColLay[]; ordenar: { campo: string; dir: string }[]; agrupar: string[];
  grafico: { tipo: string; x: string; y: string; agregacao: string; por_mes: boolean; titulo: string };
  indicadores: { rotulo: string; campo: string; agregacao: string; formato: string }[];
}
export interface Layout { visoes?: Record<string, VisLay>; pdf?: { orientacao: string }; _info?: { atualizado: string; por: string } }

function Sel({ opcoes, valor, mudar }: { opcoes: [string, string][]; valor: string | undefined | null; mudar: (v: string) => void }) {
  const v = opcoes.some(([x]) => x === String(valor ?? opcoes[0][0])) ? String(valor ?? opcoes[0][0]) : opcoes[0][0];
  return <select className="campo" value={v} onChange={(e) => mudar(e.target.value)}>{opcoes.map(([x, r]) => <option key={x} value={x}>{r}</option>)}</select>;
}
const Rotulado = ({ rotulo, children, classe }: { rotulo: string; children: ReactNode; classe?: string }) =>
  <label className={"ed-campo" + (classe ? " " + classe : "")}><span>{rotulo}</span>{children}</label>;

export function EditorLayout({ chave, nome, visoes, layout, aoSalvar, fechar }: {
  chave: string; nome: string; visoes: Visao[]; layout?: Layout; aoSalvar: () => void; fechar: () => void;
}) {
  const editaveis = visoes.filter((v) => v.colunas_originais && v.colunas_originais.length);
  const lay = useRef<Layout & { visoes: Record<string, VisLay>; pdf: { orientacao: string } }>(null as never);
  if (!lay.current) {
    const l = JSON.parse(JSON.stringify(layout || {}));
    delete l._info;
    l.visoes = l.visoes || {};
    l.pdf = l.pdf || { orientacao: "auto" };
    editaveis.forEach((v) => {
      const c = l.visoes[v.nome] = l.visoes[v.nome] || {};
      c.titulo = c.titulo || "";
      c.oculta = !!c.oculta;
      c.colunas = (v.config_colunas || []).map((x) => ({ campo: x.campo, rotulo: x.rotulo, visivel: x.visivel, formato: x.formato_salvo || "auto", total: x.total, abaixo: !!x.abaixo }));
      c.ordenar = c.ordenar || [];
      c.agrupar = c.agrupar || [];
      c.grafico = Object.assign({ tipo: "nenhum", x: "", y: "", agregacao: "soma", por_mes: false, titulo: "" }, c.grafico || {});
      c.indicadores = c.indicadores || [];
    });
    lay.current = l;
  }
  const [, setN] = useState(0);
  const r = () => setN((n) => n + 1);           // o layout é editado no próprio objeto; isto redesenha
  const [aba, setAba] = useState(0);
  const [msg, setMsg] = useState(layout && layout._info ? `Última alteração: ${layout._info.atualizado} por ${layout._info.por}` : "");
  const [confirmar, setConfirmar] = useState(false);
  const [ocupado, setOcupado] = useState("");
  const ordemPend = useRef<Record<string, { campo: string; dir: string }>>({});

  const restaurar = async () => {
    if (!confirmar) { setConfirmar(true); return; }
    setOcupado("restaurar");
    try { await api(`/api/layout/${chave}/excluir`, undefined, "POST"); fechar(); aoSalvar(); }
    catch (e) { setMsg((e as Error).message); setOcupado(""); }
  };
  const salvar = async () => {
    setOcupado("salvar"); setMsg("Salvando…");
    try { await api(`/api/layout/${chave}`, lay.current); fechar(); aoSalvar(); }
    catch (e) { setMsg((e as Error).message); setOcupado(""); }
  };

  const v = editaveis[aba];
  const painel = v && (() => {
    const c = lay.current.visoes[v.nome];
    const campos = v.colunas_originais || [];
    const rotuloDe = (campo: string) => (c.colunas.find((x) => x.campo === campo) || ({} as ColLay)).rotulo || campo;
    const opCampos = (vazio: string): [string, string][] => [["", vazio] as [string, string]].concat(campos.map((x) => [x, `${rotuloDe(x)} (${x})`]));
    const opValor = (primeiro: string): [string, string][] => [["", primeiro] as [string, string]].concat(campos.map((x) => [x, `${rotuloDe(x)} (${x})`]));
    const mover = (k: number, d: number) => { c.colunas.splice(k + d, 0, c.colunas.splice(k, 1)[0]); r(); };
    const gr = c.grafico;
    return (
      <div className="ed-painel" key={v.nome}>
        <section className="ed-secao">
          <h3>Visão</h3>
          <div className="ed-linha">
            <Rotulado rotulo="Título"><input className="campo" value={c.titulo} placeholder={v.nome} onChange={(e) => { c.titulo = e.target.value; r(); }} /></Rotulado>
            <label className="ed-check"><input type="checkbox" checked={c.oculta} onChange={(e) => { c.oculta = e.target.checked; r(); }} /> Ocultar esta visão (não aparece na tela nem nos arquivos)</label>
          </div>
        </section>
        <section className="ed-secao">
          <h3>Colunas</h3>
          <p className="nota">Marque as colunas que aparecem, renomeie, escolha o formato e o total. Use as setas para mudar a ordem.</p>
          <div className="tabela-wrap ed-cols">
            <table className="dados">
              <thead><tr>{["Mostrar", "Nome na tela", "Campo", "Formato", "Total", "Abaixo da anterior", "Ordem"].map((t) => <th key={t} style={{ cursor: "default" }}>{t}</th>)}</tr></thead>
              <tbody>
                {c.colunas.map((col, k) => (
                  <tr key={col.campo} className={col.visivel === false ? "apagada" : undefined}>
                    <td><input type="checkbox" checked={col.visivel !== false} onChange={(e) => { col.visivel = e.target.checked; r(); }} /></td>
                    <td><input className="campo" value={col.rotulo || ""} onChange={(e) => { col.rotulo = e.target.value; r(); }} /></td>
                    <td><code>{col.campo}</code></td>
                    <td><Sel opcoes={OPC_FORMATO} valor={col.formato} mudar={(x) => { col.formato = x; r(); }} /></td>
                    <td><Sel opcoes={OPC_TOTAL} valor={col.total} mudar={(x) => { col.total = x; r(); }} /></td>
                    <td><input type="checkbox" checked={!!col.abaixo} disabled={k === 0}
                      title="Mostra esta coluna embaixo da anterior, na mesma célula (ex.: base de cálculo em cima e valor embaixo)"
                      onChange={(e) => { col.abaixo = e.target.checked; r(); }} /></td>
                    <td><div className="ed-ordem">
                      <button type="button" className="btn pequeno" disabled={k === 0} title="Subir" onClick={() => mover(k, -1)}>↑</button>
                      <button type="button" className="btn pequeno" disabled={k === c.colunas.length - 1} title="Descer" onClick={() => mover(k, 1)}>↓</button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="ed-linha">
            <button type="button" className="btn pequeno" onClick={() => { c.colunas.forEach((x) => { x.visivel = true; }); r(); }}>Mostrar todas</button>
            <button type="button" className="btn pequeno" onClick={() => { c.colunas.forEach((x) => { x.visivel = false; }); r(); }}>Ocultar todas</button>
          </div>
        </section>
        <section className="ed-secao">
          <h3>Agrupar e ordenar</h3>
          <p className="nota">Agrupar separa o relatório em blocos (ex.: por cliente) com subtotal das colunas que têm total.</p>
          <div className="ed-linha">
            {[0, 1].map((n) => (
              <Rotulado key={"a" + n} rotulo={n === 0 ? "Agrupar por" : "Depois por"}>
                <Sel opcoes={opCampos(n === 0 ? "Sem agrupamento" : "—")} valor={c.agrupar[n] || ""} mudar={(x) => { c.agrupar[n] = x; c.agrupar = c.agrupar.filter(Boolean); r(); }} />
              </Rotulado>
            ))}
            {[0, 1].map((n) => {
              const k = v.nome + ":" + n;
              const o = c.ordenar[n] || (ordemPend.current[k] = ordemPend.current[k] || { campo: "", dir: "asc" });
              return (
                <Rotulado key={"o" + n} rotulo={n === 0 ? "Ordenar por" : "Depois por"}>
                  <div className="ed-par">
                    <Sel opcoes={opCampos(n === 0 ? "Ordem da consulta" : "—")} valor={o.campo} mudar={(x) => { o.campo = x; c.ordenar[n] = o; c.ordenar = c.ordenar.filter((y) => y && y.campo); delete ordemPend.current[k]; r(); }} />
                    <Sel opcoes={[["asc", "Crescente"], ["desc", "Decrescente"]]} valor={o.dir} mudar={(x) => { o.dir = x; r(); }} />
                  </div>
                </Rotulado>
              );
            })}
          </div>
        </section>
        <section className="ed-secao">
          <h3>Gráfico</h3>
          <div className="ed-linha">
            <Rotulado rotulo="Tipo"><Sel opcoes={OPC_GRAFICO} valor={gr.tipo} mudar={(x) => { gr.tipo = x; r(); }} /></Rotulado>
            <Rotulado rotulo="Categoria (eixo)"><Sel opcoes={opCampos("Escolha…")} valor={gr.x} mudar={(x) => { gr.x = x; r(); }} /></Rotulado>
            <Rotulado rotulo="Valor"><Sel opcoes={opValor("Quantidade de linhas")} valor={gr.y} mudar={(x) => { gr.y = x; r(); }} /></Rotulado>
            <Rotulado rotulo="Cálculo"><Sel opcoes={OPC_TOTAL.slice(1)} valor={gr.agregacao} mudar={(x) => { gr.agregacao = x; r(); }} /></Rotulado>
            <Rotulado rotulo="Título do gráfico"><input className="campo" value={gr.titulo || ""} placeholder="automático" onChange={(e) => { gr.titulo = e.target.value; r(); }} /></Rotulado>
            <label className="ed-check"><input type="checkbox" checked={!!gr.por_mes} onChange={(e) => { gr.por_mes = e.target.checked; r(); }} /> Datas agrupadas por mês</label>
          </div>
        </section>
        <section className="ed-secao">
          <h3>Indicadores (cartões no topo)</h3>
          <div>
            {c.indicadores.map((k, n) => (
              <div key={n} className="ed-linha ed-ind">
                <Rotulado rotulo="Nome"><input className="campo" value={k.rotulo || ""} placeholder="Nome (ex.: Total vendido)" onChange={(e) => { k.rotulo = e.target.value; r(); }} /></Rotulado>
                <Rotulado rotulo="Campo"><Sel opcoes={opValor("(linhas do relatório)")} valor={k.campo || ""} mudar={(x) => { k.campo = x; r(); }} /></Rotulado>
                <Rotulado rotulo="Cálculo"><Sel opcoes={OPC_TOTAL.slice(1)} valor={k.agregacao || "soma"} mudar={(x) => { k.agregacao = x; r(); }} /></Rotulado>
                <Rotulado rotulo="Formato"><Sel opcoes={OPC_FORMATO} valor={k.formato || "auto"} mudar={(x) => { k.formato = x; r(); }} /></Rotulado>
                <button type="button" className="btn pequeno" onClick={() => { c.indicadores.splice(n, 1); r(); }}>Remover</button>
              </div>
            ))}
          </div>
          <button type="button" className="btn pequeno" disabled={c.indicadores.length >= 6}
            onClick={() => { c.indicadores.push({ rotulo: "", campo: "", agregacao: "contagem", formato: "auto" }); r(); }}>+ Adicionar indicador</button>
        </section>
      </div>
    );
  })();

  const rodape = <>
    <Rotulado rotulo="PDF" classe="ed-ori"><Sel opcoes={[["auto", "Automática"], ["retrato", "Retrato"], ["paisagem", "Paisagem"]]} valor={lay.current.pdf.orientacao} mudar={(x) => { lay.current.pdf.orientacao = x; r(); }} /></Rotulado>
    <span className="nota">{msg}</span>
    <button type="button" className={"btn" + (confirmar ? " perigo" : "")} title="Apaga o layout salvo e volta à apresentação original"
      disabled={ocupado === "restaurar"} onClick={restaurar}>{confirmar ? "Confirmar restauração" : "Restaurar padrão"}</button>
    <button type="button" className="btn" onClick={fechar}>Cancelar</button>
    <button type="button" className="btn primario" disabled={ocupado === "salvar"} onClick={salvar}>Salvar para todos</button>
  </>;

  return (
    <Modal titulo={"Editar layout · " + nome} fechar={fechar} rodape={rodape} focar={false}>
      <p className="nota">O layout vale para todos os usuários e é usado na tela, no Excel e no PDF. Os dados e filtros do relatório não mudam.</p>
      {!editaveis.length && <>
        <div className="aviso atencao">{"Nenhuma visão deste relatório devolveu colunas, então não há o que configurar. " +
          "Isso acontece quando a consulta dá erro no banco. Veja abaixo o motivo de cada visão; se for falta de filtro, preencha os campos e clique em Ver de novo."}</div>
        <ul className="nota">{visoes.map((x) => <li key={x.nome}>{`${x.nome}: ${x.erro || x.aviso || "sem colunas"}`}</li>)}</ul>
      </>}
      {editaveis.length > 1 && (
        <div className="abas">{editaveis.map((x, i) => <button key={x.nome} type="button" className={i === aba ? "ativa" : ""} onClick={() => setAba(i)}>{x.nome}</button>)}</div>
      )}
      {painel}
    </Modal>
  );
}

/* ------------------------------------------------------------ gráfico livre (Consulta SQL) */
export function GraficoLivre({ dados, cfg }: { dados: DadosTabela; cfg: { tipo: string; x: string; y: string } }) {
  const ix = dados.colunas.indexOf(cfg.x), iy = dados.colunas.indexOf(cfg.y);
  if (ix < 0) return null;
  const agg = new Map<string, number>();
  dados.linhas.forEach((r) => {
    const k = r[ix] === null ? "(vazio)" : String(r[ix]).slice(0, cfg.tipo === "linhas" || cfg.tipo === "colunas" ? 10 : 60);
    const v = iy < 0 ? 1 : Number(r[iy]) || 0;
    agg.set(k, (agg.get(k) || 0) + v);
  });
  let pts: ItemBarra[] = Array.from(agg, ([rotulo, valor]) => ({ rotulo, valor }));
  if (cfg.tipo === "barras" || cfg.tipo === "rosca") pts.sort((a, b) => (b.valor || 0) - (a.valor || 0));
  else pts.sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR", { numeric: true }));
  if (cfg.tipo === "barras" && pts.length > 15) {
    const resto = pts.slice(14).reduce((a, p) => a + (p.valor || 0), 0);
    pts = pts.slice(0, 14).concat([{ rotulo: "Outros", valor: resto }]);
  }
  if (cfg.tipo === "rosca" && pts.length > 5) {
    const resto = pts.slice(4).reduce((a, p) => a + (p.valor || 0), 0);
    pts = pts.slice(0, 4).concat([{ rotulo: "Outros", valor: resto }]);
  }
  const moeda = iy >= 0 && MOEDA.test(cfg.y);
  return <Grafico tipo={cfg.tipo} nome={iy < 0 ? "Quantidade" : rotuloCol(cfg.y)} pts={pts} moeda={moeda} />;
}
