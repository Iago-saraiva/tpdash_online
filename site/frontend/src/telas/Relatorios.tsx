// Relatórios: prontos (PDF/Excel com os filtros do topo), do ReportBuilder e padrões (por pasta) e consultas salvas.
import { Suspense, lazy, useEffect, useRef, useState, type ReactNode } from "react";
import { api, baixar, opcoesGerais, type Opcoes } from "../api";
import { DADOS } from "../dados";
import { fmtData, iso } from "../formatos";
import { useNav } from "../navegacao";
import { useAvisar } from "../componentes/Avisos";
import { useGaveta } from "../componentes/Gaveta";
import { Escolha, FormFiltros, Periodo, Texto, paraBusca, useFiltros } from "../componentes/Filtros";
import {
  EditorLayout, Parametros, SERVIDOR_ANTIGO, Visoes, paramsDoSQL, parametrosSQL, respostaAntiga, useAvisosLocais, valoresIniciais,
  type Param, type RespVisoes,
} from "../componentes/Relatorio";

interface RelRB {
  id: string; nome: string; pasta: string; modulo: string; antigo?: boolean; visoes: string[]; parametros: Param[];
  alterado?: string; erro?: string; padrao_painel?: boolean; impressao?: boolean;
}
interface RespRB { prontos: string[]; relatorios: RelRB[]; teste?: { total?: number; andamento?: boolean; feitos?: number; inicio?: string; com_erro?: number }; pode_sql?: boolean }
interface Consulta { id: number; nome: string; descricao?: string; dono?: string; compartilhada?: boolean; sql: string; grafico?: string }

const tem = (m: string) => (DADOS.usuario?.modulos || []).includes(m);

/* editor de layout de impressão: carrega só quando abre */
const Designer = lazy(() => import("../componentes/Designer").then((m) => ({ default: m.Designer })));

/* ------------------------------------------------------------ resultado com visões + botões (gaveta) */
function useResultado() {
  const [d, setD] = useState<RespVisoes | null>(null);
  const [estado, setEstado] = useState("");      // "" | "consultando"
  const [versao, setVersao] = useState(0);
  return { d, setD, estado, setEstado, versao, novo: () => setVersao((n) => n + 1) };
}
function Resultado({ r }: { r: ReturnType<typeof useResultado> }) {
  if (r.estado === "consultando") return <div className="rb-res">Consultando…</div>;
  if (!r.d) return <div className="rb-res" />;
  return <div className="rb-res">
    {respostaAntiga(r.d) && <div className="aviso atencao">{SERVIDOR_ANTIGO}</div>}
    <Visoes key={r.versao} visoes={r.d.visoes} />
  </div>;
}

function BotaoArquivo({ rotulo, classe = "btn", title, ir, avisar }: { rotulo: string; classe?: string; title?: string; ir: () => Promise<unknown>; avisar: (m: string) => void }) {
  const [ocupado, setOcupado] = useState(false);
  return <button className={classe} title={title} disabled={ocupado} onClick={async () => {
    setOcupado(true);
    try { await ir(); } catch (e) { avisar((e as Error).message); } finally { setOcupado(false); }
  }}>{rotulo}</button>;
}

/** relatório do ReportBuilder / padrão na gaveta */
function RelatorioRB({ r, podeSQL }: { r: RelRB; podeSQL?: boolean }) {
  const g = useGaveta();
  const { navegar } = useNav();
  const [avisos, avisar] = useAvisosLocais();
  const [valores, setValores] = useState(() => valoresIniciais(r.parametros));
  const atual = useRef(valores);
  atual.current = valores;
  const res = useResultado();
  const [editar, setEditar] = useState(false);
  const [desenho, setDesenho] = useState<Record<string, string> | null>(null);
  const url = `/api/rb/${encodeURIComponent(r.id)}`;
  const ver = async () => {
    res.setEstado("consultando");
    try {
      const d = await api<RespVisoes>(url + "/executar", { valores: atual.current });
      res.setD(d); res.novo();
    } catch (e) { res.setD(null); avisar((e as Error).message); } finally { res.setEstado(""); }
  };
  useEffect(() => {
    if (!r.parametros.some((p) => p.obrigatorio && (p.padrao === null || p.padrao === undefined))) ver();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const d = res.d;
  const podeEditar = !!d && !!d.pode_editar && !respostaAntiga(d);
  return <>
    {avisos}
    <p className="gtick" style={{ margin: "0 0 12px" }}>{`${r.pasta} · ${r.padrao_painel ? "relatório padrão do painel" : "importado do ReportBuilder"} · ${r.visoes.join(", ")}`}</p>
    {r.erro && <div className="aviso atencao">{"No último teste este relatório deu erro: " + r.erro}</div>}
    <Parametros lista={r.parametros} valores={valores} mudar={setValores} />
    <div className="acoes-linha">
      <button className="btn primario" disabled={res.estado === "consultando"} onClick={ver}>Ver</button>
      {([["Excel", "xlsx", false], ["PDF", "pdf", false]] as [string, string, boolean][]).concat(r.impressao ? [["PDF em tabela", "pdf", true]] : []).map(([rot, fmt, tabela]) => (
        <BotaoArquivo key={rot} rotulo={rot} avisar={avisar}
          title={fmt === "pdf" ? (tabela ? "PDF com as colunas da tela (sem o layout de impressão)" : (r.impressao ? "PDF com o layout de impressão (como no ReportBuilder)" : "PDF")) : undefined}
          ir={() => baixar(url + "/arquivo", { valores: atual.current, formato: fmt, tabela })} />
      ))}
      <button className="btn" title="Layout de impressão no estilo ReportBuilder: bandas, campos, textos, linhas, totais (o PDF sai assim)"
        onClick={() => setDesenho({ ...atual.current })}>Editar layout</button>
      <button className="btn" hidden={!podeEditar} title="Colunas, nomes, formatos, agrupamento, totais e gráfico da visualização na tela e do Excel (vale para todos)"
        onClick={() => d && setEditar(true)}>Colunas da tela</button>
      {podeSQL && (
        <button className="btn" title="Abre a consulta da primeira visão na tela Consulta SQL para ajustar e salvar" onClick={async () => {
          try {
            const x = await api<{ visoes: { sql: string }[] }>(url + "/sql");
            try { sessionStorage.setItem("sql_pendente", JSON.stringify({ sql: x.visoes[0].sql, valores: atual.current, nome: r.nome })); } catch { /* */ }
            g.fechar();
            navegar("/sql");
          } catch (e) { avisar((e as Error).message); }
        }}>Abrir SQL no editor</button>
      )}
    </div>
    <Resultado r={res} />
    {editar && d && <EditorLayout chave={"rb:" + encodeURIComponent(r.id)} nome={r.nome} visoes={d.visoes} layout={d.layout}
      fechar={() => setEditar(false)} aoSalvar={ver} />}
    {desenho && <Suspense fallback={null}><Designer rid={r.id} nome={r.nome} valores={desenho} fechar={() => setDesenho(null)} /></Suspense>}
  </>;
}

/** consulta salva na gaveta (com os filtros :NOME dela) */
function ConsultaSalva({ c }: { c: Consulta }) {
  const [avisos, avisar] = useAvisosLocais();
  const lista = paramsDoSQL(c.sql);
  const [valores, setValores] = useState(() => valoresIniciais(lista));
  const atual = useRef(valores);
  atual.current = valores;
  const res = useResultado();
  const [editar, setEditar] = useState(false);
  const qs = () => Object.entries(atual.current).map(([k, v]) => `p_${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  const rodar = async () => {
    res.setD(null);
    try {
      const d = await api<RespVisoes>(`/api/consultas/${c.id}/dados?${qs()}`);
      if (!d.visoes) d.visoes = [{ nome: "Resultado", colunas: d.colunas || [], linhas: d.linhas || [], truncado: d.truncado }];
      res.setD(d); res.novo();
    } catch (e) { avisar((e as Error).message); }
  };
  useEffect(() => { if (!lista.length) rodar(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const d = res.d;
  return <>
    {avisos}
    <Parametros lista={lista} valores={valores} mudar={setValores} />
    <div className="acoes-linha">
      {([["Ver", null], ["Excel", "xlsx"], ["PDF", "pdf"]] as [string, string | null][]).map(([rot, fmt]) => (
        <BotaoArquivo key={rot} rotulo={rot} classe={"btn" + (fmt ? "" : " primario")} avisar={avisar}
          ir={() => (fmt ? baixar(`/api/consultas/${c.id}/arquivo?formato=${fmt}&${qs()}`) : rodar())} />
      ))}
      <button className="btn" hidden={!d || !d.pode_editar || respostaAntiga(d)} onClick={() => setEditar(true)}>Editar layout</button>
    </div>
    <div>
      {d && respostaAntiga(d) && <div className="aviso atencao">{SERVIDOR_ANTIGO}</div>}
      {d && <Visoes key={res.versao} visoes={d.visoes} />}
    </div>
    {editar && d && <EditorLayout chave={"sq:" + c.id} nome={c.nome} visoes={d.visoes} layout={d.layout} fechar={() => setEditar(false)} aoSalvar={rodar} />}
  </>;
}

/* ------------------------------------------------------------ lista do ReportBuilder (pastas) */
const MOD: Record<string, string> = { movimentos: "Movimentos", estoque: "Estoque", financeiro: "Financeiro", cadastros: "Cadastros", relatorios: "Relatórios" };
const moduloDe = (lista: RelRB[]) => {
  const c: Record<string, number> = {};
  lista.forEach((r) => { c[r.modulo] = (c[r.modulo] || 0) + 1; });
  return Object.keys(c).sort((x, y) => c[y] - c[x])[0] || "relatorios";
};
const ultima = (lista: RelRB[]) => lista.reduce<string | null>((m, r) => (r.alterado && (!m || r.alterado > m) ? r.alterado : m), null);

function ListaRB({ d, abrir }: { d: RespRB | null; abrir: (r: RelRB) => void }) {
  const [busca, setBusca] = useState("");
  const [pasta, setPasta] = useState("");
  const [antigos, setAntigos] = useState(false);
  const cont = useRef<HTMLDivElement>(null);
  const todos = d ? d.relatorios : [];
  const pastas = [...new Set(todos.map((r) => r.pasta))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  const q = busca.trim().toLowerCase();
  const filtrados = todos.filter((r) => (antigos || !r.antigo) && (!pasta || r.pasta === pasta) &&
    (!q || r.nome.toLowerCase().includes(q) || r.pasta.toLowerCase().includes(q)));
  const irPasta = (p: string) => { setPasta(p); cont.current?.scrollIntoView({ block: "nearest" }); };
  const grupos = new Map<string, RelRB[]>();
  filtrados.forEach((r) => { if (!grupos.has(r.pasta)) grupos.set(r.pasta, []); grupos.get(r.pasta)!.push(r); });
  let info = "";
  if (d && d.teste && d.teste.total) {
    info = d.teste.andamento ? `Teste em andamento: ${d.teste.feitos} de ${d.teste.total}` : `Último teste: ${d.teste.inicio || ""} · ${d.teste.com_erro || 0} com erro`;
  }
  const item = (r: RelRB) => {
    const partes = [`${r.visoes.length} ${r.visoes.length === 1 ? "visão" : "visões"}`];
    if (r.parametros.length) partes.push(`${r.parametros.length} filtro(s)`);
    partes.push("alterado " + fmtData(r.alterado));
    return (
      <button key={r.id} type="button" className="rb-item" onClick={() => abrir(r)}>
        <span className="rb-nome">{r.nome}</span><span className="rb-meta">{partes.join(" · ")}</span>
        {r.antigo && <span className="tag">antigo/teste</span>}
        {r.erro && <span className="tag critico" title={r.erro}>erro no teste</span>}
      </button>
    );
  };
  let corpo: ReactNode;
  if (!d) corpo = "Carregando…";
  else if (!filtrados.length) corpo = "Nenhum relatório encontrado.";
  else if (pasta) {
    corpo = <>
      <div className="rb-pasta-cab">
        <button type="button" className="btn pequeno" onClick={() => irPasta("")}>← Todas as pastas</button>
        <h3>{pasta}</h3><span className="tag">{String(filtrados.length)}</span>
      </div>
      <div className="rb-itens-grade">{filtrados.map(item)}</div>
    </>;
  } else {
    corpo = <div className="rb-pastas">
      {[...grupos].map(([p, lista]) => {
        const mostrar = q ? lista : lista.slice(0, 4);   // com busca mostra todos os encontrados
        const u = ultima(lista);
        return (
          <div key={p} className={"rb-pasta-card mod-" + moduloDe(lista)}>
            <button type="button" className="rb-pasta-topo" title={"Abrir a pasta " + p} onClick={() => irPasta(p)}>
              <span className="rb-pasta-ic" aria-hidden="true" />
              <span className="rb-pasta-txt"><strong>{p}</strong>
                <span className="rb-meta">{`${lista.length} ${lista.length === 1 ? "relatório" : "relatórios"} · ${MOD[moduloDe(lista)] || ""}` + (u ? ` · alterado ${fmtData(u)}` : "")}</span>
              </span>
            </button>
            <div className="rb-pasta-itens">
              {mostrar.map((r) => <button key={r.id} type="button" className="rb-mini" title={r.nome} onClick={() => abrir(r)}>{r.nome}</button>)}
              {lista.length > mostrar.length && (
                <button type="button" className="rb-mais" onClick={() => irPasta(p)}>{`+ ${lista.length - mostrar.length} relatório(s) · ver pasta`}</button>
              )}
            </div>
          </div>
        );
      })}
    </div>;
  }
  return (
    <div className="cartao">
      <div className="cartao-cab"><h2>Relatórios do ReportBuilder e padrões <span className="sub">· importados do Puma e criados no painel (pasta Relatórios padrões)</span></h2>
        <span className="gtick" id="rb-info">{info}</span></div>
      <div className="filtros" style={{ boxShadow: "none", marginBottom: 12 }}>
        <label>Buscar<input id="rb-busca" className="largo" placeholder="nome do relatório ou pasta" value={busca} onChange={(e) => setBusca(e.target.value)} /></label>
        <label>Pasta<select id="rb-pasta" className="largo" value={pasta} onChange={(e) => setPasta(e.target.value)}>
          <option value="">Todas as pastas</option>{pastas.map((p) => <option key={p} value={p}>{p}</option>)}
        </select></label>
        <label className="check"><input type="checkbox" id="rb-antigos" checked={antigos} onChange={(e) => setAntigos(e.target.checked)} /> mostrar antigos, cópias e testes</label>
        <span className="gtick" id="rb-conta" style={{ marginLeft: "auto", alignSelf: "center" }}>{d ? `${filtrados.length} de ${todos.length} relatórios` : ""}</span>
      </div>
      <div id="rb-lista" ref={cont}>{corpo}</div>
    </div>
  );
}

/* ------------------------------------------------------------ tela */
const PRONTOS: { rel: string; modulo: string; titulo: string; texto: string; formatos: string[] }[] = [
  { rel: "documentos", modulo: "movimentos", titulo: "Movimentos documento por documento", formatos: ["pdf", "xlsx"],
    texto: "Cada DOCUMENTO com data, cliente e valor, seguido dos materiais (código, quantidade, unitário, total). No fim, resumo por material. Filtros: período, tipo, vendedor, cliente." },
  { rel: "titulos", modulo: "financeiro", titulo: "Títulos em aberto", formatos: ["pdf", "xlsx"],
    texto: "Contas a pagar e a receber em aberto com vencimento no período, dias de atraso e valor. Filtros: período (vencimento), cliente/fornecedor." },
  { rel: "estoque", modulo: "estoque", titulo: "Saldo de estoque por local", formatos: ["pdf", "xlsx"],
    texto: "Produtos com saldo diferente de zero, custo médio e valor em estoque. Filtro: local de estoque." },
  { rel: "produtos", modulo: "cadastros", titulo: "Produtos – cadastro e tributação", formatos: ["xlsx", "pdf"],
    texto: "Todos os produtos ativos com NCM, CEST, situação tributária dentro e fora do estado, saldo e alertas de cadastro." },
  { rel: "clientes", modulo: "cadastros", titulo: "Clientes", formatos: ["xlsx", "pdf"],
    texto: "Cadastro completo de clientes: CPF/CNPJ, cidade, telefone, e-mail, situação e datas." },
];

export default function Relatorios() {
  const avisar = useAvisar();
  const g = useGaveta();
  const hoje = new Date();
  const f = useFiltros({ ini: iso(new Date(hoje.getFullYear(), 0, 1)), fim: iso(hoje), tipos: "", prefixo: "", vendedor: "", cliente: "", local: "", filial: "" });
  const [o, setO] = useState<Opcoes | null>(null);
  const [rb, setRb] = useState<RespRB | null>(null);
  const [consultas, setConsultas] = useState<Consulta[] | string | null>(null);
  useEffect(() => {
    opcoesGerais().then(setO).catch((e) => { setO({}); avisar(e.message); });
    api<RespRB>("/api/rb").then(setRb).catch((e) => avisar(e.message));
    api<{ consultas: Consulta[] }>("/api/consultas").then((d) => setConsultas(d.consultas)).catch((e) => setConsultas(e.message));
  }, [avisar]);

  const abrirRB = (r: RelRB) => g.abrir({ titulo: r.nome, larga: true, corpo: <RelatorioRB r={r} podeSQL={rb?.pode_sql} /> });
  const verConsulta = (c: Consulta) => g.abrir({ titulo: c.nome, larga: true, corpo: <ConsultaSalva c={c} /> });
  const baixarPronto = (rel: string, fmt: string) => {
    const p = paraBusca(f.form);
    p.set("formato", fmt);
    if (rel === "titulos") p.set("base", "vencimento");
    return baixar(`/api/relatorio/${rel}?${p}`);
  };

  return <>
    <FormFiltros f={f}>
      <Periodo f={f} />
      <label>Tipo de movimento<Escolha f={f} nome="tipos" className="largo" lista={o?.tipos || []} vazio="Todos os tipos" /></label>
      <label>Cliente / fornecedor<Texto f={f} nome="cliente" placeholder="código ou nome" /></label>
      <label>Filial<Escolha f={f} nome="filial" lista={o?.filiais || []} vazio="Todas" /></label>
      <label>Tipo inicia com<Texto f={f} nome="prefixo" placeholder="ex.: 2.2" style={{ minWidth: 90, width: 100 }} /></label>
      <label>Vendedor / funcionário<Escolha f={f} nome="vendedor" className="largo" lista={o?.vendedores || []} vazio="Todos" /></label>
      <label>Local de estoque<Escolha f={f} nome="local" lista={o?.locais || []} vazio="Todos os locais" /></label>
    </FormFiltros>
    <div className="cartao">
      <div className="cartao-cab"><h2>Relatórios prontos <span className="sub">· usam os filtros acima quando se aplicam</span></h2></div>
      <div className="lista-rel">
        {PRONTOS.filter((x) => tem(x.modulo)).map((x) => (
          <div key={x.rel} className="rel" hidden={!!rb && !rb.prontos.includes(x.rel)}>
            <h3>{x.titulo}</h3><p>{x.texto}</p>
            <div className="acoes">
              {x.formatos.map((fmt, i) => <BotaoArquivo key={fmt} rotulo={fmt === "pdf" ? "PDF" : "Excel"} classe={"btn pequeno" + (i === 0 ? " primario" : "")}
                avisar={avisar} ir={() => baixarPronto(x.rel, fmt)} />)}
            </div>
          </div>
        ))}
      </div>
    </div>
    <ListaRB d={rb} abrir={abrirRB} />
    <div className="cartao">
      <div className="cartao-cab"><h2>Consultas salvas <span className="sub">· criadas na tela Consulta SQL</span></h2></div>
      <div className="lista-rel" id="consultas">
        {consultas === null ? "Carregando…" : typeof consultas === "string" ? consultas
          : !consultas.length ? "Nenhuma consulta salva ainda. Crie em Consulta SQL e marque \"Compartilhar\" para aparecer aqui para todos."
            : consultas.map((c) => {
              const temParams = parametrosSQL(c.sql).length > 0;
              return (
                <div key={c.id} className="rel">
                  <h3>{c.nome}</h3>
                  <p>{(c.descricao || "") + (c.dono ? ` — por ${c.dono}` : "") + (c.compartilhada ? " · compartilhada" : "")}</p>
                  <div className="acoes">
                    {([["Ver", null], ["Excel", "xlsx"], ["PDF", "pdf"]] as [string, string | null][]).map(([rot, fmt]) => (
                      <BotaoArquivo key={rot} rotulo={rot} classe={"btn pequeno" + (fmt ? "" : " primario")} avisar={avisar}
                        ir={async () => { if (temParams || !fmt) verConsulta(c); else await baixar(`/api/consultas/${c.id}/arquivo?formato=${fmt}`); }} />
                    ))}
                  </div>
                </div>
              );
            })}
      </div>
    </div>
  </>;
}
