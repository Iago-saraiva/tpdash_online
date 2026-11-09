// Cadastros: clientes e fornecedores, produtos e tributação, máquinas. Cada aba carrega na primeira vez que é aberta.
import { useEffect, useState } from "react";
import { opcoesGerais, type Codigo, type Opcoes } from "../api";
import { F, rotuloCol } from "../formatos";
import { useNav } from "../navegacao";
import { Kpis } from "../componentes/Kpis";
import { Barras, Rosca, type ItemBarra } from "../componentes/Graficos";
import { Campos, useGaveta } from "../componentes/Gaveta";
import { Tabela, type Celula, type DadosTabela, type Linha } from "../componentes/Tabela";
import { useAbrirFicha } from "../componentes/Ficha";
import { Escolha, Exportar, FormFiltros, Marcar, Texto, useDados, useFiltros } from "../componentes/Filtros";

const ABAS: [string, string][] = [["clientes", "Clientes e fornecedores"], ["produtos", "Produtos e tributação"], ["maquinas", "Máquinas"]];

export default function Cadastros() {
  const { busca } = useNav();
  const [aba, setAba] = useState(() => new URLSearchParams(busca).get("aba") || "clientes");
  const [abertas, setAbertas] = useState<string[]>([aba]);
  const mostrar = (a: string) => { setAba(a); setAbertas((x) => (x.includes(a) ? x : [...x, a])); };
  return (
    <>
      <div className="abas">
        {ABAS.map(([k, rot]) => <button key={k} className={aba === k ? "ativa" : ""} onClick={() => mostrar(k)}>{rot}</button>)}
      </div>
      {abertas.includes("clientes") && <div className="secao" hidden={aba !== "clientes"}><Clientes /></div>}
      {abertas.includes("produtos") && <div className="secao" hidden={aba !== "produtos"}><Produtos /></div>}
      {abertas.includes("maquinas") && <div className="secao" hidden={aba !== "maquinas"}><Maquinas /></div>}
    </>
  );
}

function useOpcoes() {
  const [o, setO] = useState<Opcoes | null>(null);
  useEffect(() => { opcoesGerais().then(setO).catch(() => setO({})); }, []);
  return o;
}

/* ------------------------------------------------------------ clientes e fornecedores */
interface RespCli { kpis: Record<string, number>; por_cidade: ItemBarra[]; por_pessoa: ItemBarra[]; tabela: DadosTabela; truncado: boolean }
function Clientes() {
  const f = useFiltros({ tipo: "clientes", ativo: "", uf: "", busca: "", acima_limite: "" });
  const { dados: d, carregando } = useDados<RespCli>("/api/clientes", f);
  const abrirFicha = useAbrirFicha();
  const k = d?.kpis;
  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f}>
        <label>Mostrar<Escolha f={f} nome="tipo" auto><option value="clientes">Clientes</option><option value="fornecedores">Fornecedores</option><option value="todos">Todos</option></Escolha></label>
        <label>Situação<Escolha f={f} nome="ativo" auto><option value="">Todos</option><option value="T">Ativos</option><option value="F">Inativos</option></Escolha></label>
        <label>UF<Texto f={f} nome="uf" maxLength={2} style={{ minWidth: 60, width: 70 }} /></label>
        <label>Busca<Texto f={f} nome="busca" placeholder="código, nome, CNPJ ou cidade" className="largo" /></label>
        <Marcar f={f} nome="acima_limite" auto>só acima do limite de crédito</Marcar>
      </FormFiltros>
      <div className="kpis">
        {k && <Kpis lista={[
          { rotulo: "Cadastros", valor: F.inteiro(k.qtd) },
          { rotulo: "Ativos", valor: F.inteiro(k.ativos) },
          { rotulo: "Sem UF", valor: F.inteiro(k.sem_uf), classe: k.sem_uf ? "critico" : "" },
          { rotulo: "E-mail vazio ou genérico", valor: F.inteiro(k.email_generico), detalhe: "ex.: NAOTEM@NAOTEM.COM" },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c8"><div className="cartao-cab"><h2>12 cidades com mais cadastros</h2></div><div>{d && <Barras dados={d.por_cidade} />}</div></div>
        <div className="cartao c4"><div className="cartao-cab"><h2>Pessoa física × jurídica</h2></div><div>{d && <Rosca dados={d.por_pessoa} rotuloTotal="cadastros" />}</div></div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>Cadastros</h2><Exportar url="/api/clientes" f={f} /></div>
          <div><Tabela dados={d?.tabela || null} truncado={d?.truncado} onClick={(r, cols) => abrirFicha(r[cols.indexOf("CODIGO")])} /></div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ produtos e tributação */
interface RespProd { kpis: Record<string, number>; por_situacao: ItemBarra[]; alertas: ItemBarra[]; tabela: DadosTabela; truncado: boolean }
const celulaAlerta: Celula = (c, v) => {
  if (c !== "ALERTA" || !v) return null;
  return { conteudo: String(v).split("; ").map((a, i) => <span key={i}><span className="tag atencao">{a}</span> </span>) };
};
function Produtos() {
  const o = useOpcoes();
  const f = useFiltros({ grupo: "", busca: "", alerta: "", inativos: "" });
  const { dados: d, carregando } = useDados<RespProd>("/api/produtos", f, o !== null);
  const k = d?.kpis;
  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f}>
        <label>Grupo<Escolha f={f} nome="grupo" className="largo" auto lista={o?.grupos || []} vazio="Todos os grupos" /></label>
        <label>Busca<Texto f={f} nome="busca" placeholder="código, NCM ou nome" className="largo" /></label>
        <label>Alerta<Escolha f={f} nome="alerta" auto>
          <option value="">Todos os produtos</option><option>Sem situação tributária</option><option>Sem NCM</option><option>ST sem CEST</option>
          <option>Sem preço</option><option>Saldo negativo</option><option value="Inativos">Apenas inativos</option>
        </Escolha></label>
        <Marcar f={f} nome="inativos" auto>incluir inativos</Marcar>
      </FormFiltros>
      <div className="kpis">
        {k && <Kpis lista={[
          { rotulo: "Produtos", valor: F.inteiro(k.qtd) },
          { rotulo: "Com algum alerta", valor: F.inteiro(k.com_alerta), classe: k.com_alerta ? "critico" : "" },
          { rotulo: "ST sem CEST", valor: F.inteiro(k["alerta_ST sem CEST"]) },
          { rotulo: "Sem situação tributária", valor: F.inteiro(k["alerta_Sem situação tributária"]) },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c6"><div className="cartao-cab"><h2>Por situação tributária</h2></div><div>{d && <Barras dados={d.por_situacao} larguraRotulo={220} />}</div></div>
        <div className="cartao c6"><div className="cartao-cab"><h2>Alertas de cadastro <span className="sub">· clique para filtrar</span></h2></div>
          <div>{d && <Barras dados={d.alertas} cor="var(--serie-8)" larguraRotulo={170} onClick={(x) => f.aplicar({ alerta: x.rotulo })} />}</div></div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>Produtos <span className="sub">· do código mais recente para o mais antigo</span></h2><Exportar url="/api/produtos" f={f} /></div>
          <div><Tabela dados={d?.tabela || null} truncado={d?.truncado} celula={celulaAlerta} /></div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ máquinas */
interface RespMaq { kpis: Record<string, number>; grupos: Codigo[]; por_grupo: ItemBarra[]; por_marca: ItemBarra[]; tabela: DadosTabela; truncado: boolean }
const ROT_MAQ: Record<string, string> = { DESCRICAO: "Descrição", NUMMOTOR: "Nº motor", NUMSERIE: "Nº série", KM: "KM / horímetro", TIPOCONTROLE: "Tipo controle",
  TIPOVERIFICACAO: "Tipo verificação", OBSERVACAO: "Observação", SITUACAO: "Situação", CODIGO: "Código" };
function Maquinas() {
  const o = useOpcoes();
  const g = useGaveta();
  const f = useFiltros({ grupo: "", filial: "", situacao: "", busca: "" });
  const { dados: d, carregando } = useDados<RespMaq>("/api/maquinas", f, o !== null);
  const [grupos, setGrupos] = useState<Codigo[]>([]);
  useEffect(() => { if (d && !grupos.length) setGrupos(d.grupos || []); }, [d]);  // eslint-disable-line react-hooks/exhaustive-deps
  const ficha = (r: Linha, cols: string[]) => {
    const v = (n: string) => r[cols.indexOf(n)];
    g.abrir({
      titulo: `${v("CODIGO")} · ${v("DESCRICAO") || ""}`,
      corpo: <>
        <Campos pares={cols.filter((c) => c !== "OBSERVACAO").map((c) => [ROT_MAQ[c] || rotuloCol(c), c === "KM" ? F.numero(v(c) as number) : String(v(c) ?? "")])} />
        <h3 style={{ fontSize: 13, margin: "4px 0" }}>Observação</h3>
        <p style={{ whiteSpace: "pre-wrap" }}>{String(v("OBSERVACAO") || "—")}</p>
      </>,
    });
  };
  const k = d?.kpis;
  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f}>
        <label>Grupo<Escolha f={f} nome="grupo" className="largo" auto lista={grupos} vazio="Todos os grupos" /></label>
        <label>Filial<Escolha f={f} nome="filial" auto lista={o?.filiais || []} vazio="Todas" /></label>
        <label>Situação<Escolha f={f} nome="situacao" auto><option value="">Todas</option><option value="ativas">Ativas</option><option value="inativas">Inativas</option></Escolha></label>
        <label>Busca<Texto f={f} nome="busca" placeholder="código, placa, nome, marca, chassi ou motor" className="largo" /></label>
      </FormFiltros>
      <div className="kpis">
        {k && <Kpis lista={[
          { rotulo: "Máquinas e veículos", valor: F.inteiro(k.qtd) },
          { rotulo: "Ativas", valor: F.inteiro(k.ativas) },
          { rotulo: "Grupos", valor: F.inteiro(k.grupos) },
          { rotulo: "Marcas", valor: F.inteiro(k.marcas) },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c6"><div className="cartao-cab"><h2>Por grupo <span className="sub">· clique para filtrar</span></h2></div>
          <div>{d && <Barras dados={d.por_grupo} onClick={(x) => { if (x.rotulo !== "Outros" && x.rotulo !== "(sem grupo)") f.aplicar({ grupo: x.rotulo.split(" - ")[0] }); }} />}</div></div>
        <div className="cartao c6"><div className="cartao-cab"><h2>Por marca</h2></div><div>{d && <Barras dados={d.por_marca} cor="var(--serie-3)" />}</div></div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>Máquinas e veículos <span className="sub">· clique para ver a ficha completa</span></h2><Exportar url="/api/maquinas" f={f} /></div>
          <div><Tabela dados={d?.tabela || null} truncado={d?.truncado} rotulos={ROT_MAQ} onClick={ficha} /></div>
        </div>
      </div>
    </div>
  );
}
