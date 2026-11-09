// Estoque: saldo por produto e local, com gráficos de valor ou quantidade.
import { useEffect, useState } from "react";
import { opcoesGerais, type Opcoes } from "../api";
import { F, guardado } from "../formatos";
import { Kpis } from "../componentes/Kpis";
import { Barras, type ItemBarra } from "../componentes/Graficos";
import { Modal } from "../componentes/Gaveta";
import { Tabela, type DadosTabela } from "../componentes/Tabela";
import { Escolha, Exportar, FormFiltros, Marcar, Texto, useDados, useFiltros } from "../componentes/Filtros";

interface Produto extends ItemBarra { codigo?: string; produto?: string; und?: string; qtd?: number; preco?: number; valor_estoque?: number }
interface Resp {
  kpis: { valor: number; itens: number; negativos: number; sem_custo: number };
  por_local: ItemBarra[]; por_local_qtd: ItemBarra[]; por_grupo: ItemBarra[]; por_grupo_qtd: ItemBarra[];
  top_produtos: Produto[]; top_produtos_qtd: Produto[];
  tabela: DadosTabela; truncado: boolean;
}
type Modo = "valor" | "qtd";
type Modos = { local: Modo; grupo: Modo; top: Modo };

const PADRAO = { filial: "", local: "", grupo: "", busca: "", negativos: "" };

function lerModos(): Modos {
  const m: Modos = { local: "valor", grupo: "valor", top: "valor" };
  try { Object.assign(m, JSON.parse(guardado.ler("estoque_modos") || "{}")); } catch { /* */ }
  return m;
}

/** botões Valor / Quantidade de cada gráfico */
function Alterna({ modo, mudar }: { modo: Modo; mudar: (m: Modo) => void }) {
  return (
    <div className="alterna" role="group" aria-label="Mostrar"
      onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      {(["valor", "qtd"] as Modo[]).map((m) => (
        <button key={m} type="button" className={modo === m ? "ativo" : ""} aria-pressed={modo === m} onClick={() => mudar(m)}>
          {m === "valor" ? "Valor" : "Quantidade"}
        </button>
      ))}
    </div>
  );
}

/* produtos de maior valor: janela com quantidade e preço de venda de cada um */
function JanelaTop({ lista, fechar }: { lista: Produto[]; fechar: () => void }) {
  let somaVenda = 0, somaCusto = 0;
  const linhas = lista.map((p, i) => {
    const totVenda = (p.preco || 0) * (p.qtd || 0);
    somaVenda += totVenda; somaCusto += p.valor_estoque ?? p.valor ?? 0;
    return (
      <tr key={i}>
        <td>{p.codigo}</td><td title={p.produto}>{p.produto}</td><td>{p.und}</td>
        <td className="num">{F.numero(p.qtd)}</td>
        <td className="num">{p.preco ? F.moeda(p.preco) : "-"}</td>
        <td className="num">{p.preco ? F.moeda(totVenda) : "-"}</td>
        <td className="num">{F.moeda(p.valor_estoque ?? p.valor)}</td>
      </tr>
    );
  });
  return (
    <Modal titulo="Produtos de maior valor em estoque" fechar={fechar}>
      <div className="tabela-wrap">
        <table className="dados">
          <thead><tr>
            <th>Código</th><th>Produto</th><th>Und</th><th className="num">Quantidade</th><th className="num">Preço de venda</th>
            <th className="num">Total a preço de venda</th><th className="num">Valor em estoque (custo)</th>
          </tr></thead>
          <tbody>{linhas}</tbody>
          <tfoot><tr><td>Total</td><td></td><td></td><td className="num"></td><td className="num"></td>
            <td className="num">{F.moeda(somaVenda)}</td><td className="num">{F.moeda(somaCusto)}</td></tr></tfoot>
        </table>
      </div>
      <p className="nota">Quantidade somada de todos os locais filtrados. Preço de venda do cadastro do produto.</p>
    </Modal>
  );
}

export default function Estoque() {
  const f = useFiltros(PADRAO);
  const [o, setO] = useState<Opcoes | null>(null);
  useEffect(() => { opcoesGerais().then(setO).catch(() => setO({})); }, []);
  const { dados: d, carregando } = useDados<Resp>("/api/estoque", f, o !== null);
  const [modos, setModos] = useState<Modos>(lerModos);
  const [janela, setJanela] = useState(false);
  const mudar = (k: keyof Modos) => (m: Modo) => {
    const novo = { ...modos, [k]: m };
    guardado.gravar("estoque_modos", JSON.stringify(novo));
    setModos(novo);
  };
  const opc = (m: Modo) => (m === "qtd" ? { formato: F.numero } : { formato: F.moeda, compacto: true, moeda: true });
  const top = d ? (modos.top === "qtd" ? d.top_produtos_qtd : d.top_produtos) || [] : [];
  const abrirTop = () => { if (top.length) setJanela(true); };

  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f}>
        <label>Filial<Escolha f={f} nome="filial" auto lista={o?.filiais || []} vazio="Todas" /></label>
        <label>Local<Escolha f={f} nome="local" className="largo" auto lista={o?.locais || []} vazio="Todos os locais" /></label>
        <label>Grupo<Escolha f={f} nome="grupo" className="largo" auto lista={o?.grupos || []} vazio="Todos os grupos" /></label>
        <label>Produto<Texto f={f} nome="busca" placeholder="código ou nome" className="largo" /></label>
        <Marcar f={f} nome="negativos" auto>só saldos negativos</Marcar>
      </FormFiltros>
      <div className="kpis">
        {d && <Kpis lista={[
          { rotulo: "Valor em estoque", valor: F.compacto(d.kpis.valor, true), detalhe: F.moeda(d.kpis.valor), classe: "destaque" },
          { rotulo: "Produtos com saldo", valor: F.inteiro(d.kpis.itens) },
          { rotulo: "Saldos negativos", valor: F.inteiro(d.kpis.negativos), classe: d.kpis.negativos ? "critico" : "", detalhe: "produto × local" },
          { rotulo: "Com saldo e sem custo", valor: F.inteiro(d.kpis.sem_custo), detalhe: "não entram no valor" },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c6">
          <div className="cartao-cab"><h2><span className="tit-modo">{modos.local === "qtd" ? "Quantidade por local" : "Valor por local"}</span> <span className="sub">· clique para filtrar</span></h2>
            <Alterna modo={modos.local} mudar={mudar("local")} /></div>
          <div>{d && <Barras key={modos.local} dados={modos.local === "qtd" ? d.por_local_qtd : d.por_local} {...opc(modos.local)}
            onClick={(x) => { if (x.rotulo !== "Outros") f.aplicar({ local: x.rotulo.split(" ")[0] }); }} />}</div>
        </div>
        <div className="cartao c6">
          <div className="cartao-cab"><h2><span className="tit-modo">{modos.grupo === "qtd" ? "Quantidade por grupo" : "Valor por grupo"}</span></h2>
            <Alterna modo={modos.grupo} mudar={mudar("grupo")} /></div>
          <div>{d && <Barras key={modos.grupo} dados={modos.grupo === "qtd" ? d.por_grupo_qtd : d.por_grupo} {...opc(modos.grupo)} cor="var(--serie-3)" />}</div>
        </div>
        <div className="cartao c12 clicavel" tabIndex={0} role="button" title="Clique para ver quantidade e preço de venda de cada produto"
          onClick={abrirTop} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrirTop(); } }}>
          <div className="cartao-cab"><h2><span className="tit-modo">{modos.top === "qtd" ? "Produtos com maior quantidade em estoque" : "Produtos de maior valor em estoque"}</span> <span className="sub">· clique para ver quantidade e preço de venda</span></h2>
            <Alterna modo={modos.top} mudar={mudar("top")} /></div>
          <div>{d && <Barras key={modos.top} dados={top} {...opc(modos.top)} cor="var(--serie-2)" larguraRotulo={260} />}</div>
        </div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>Saldo por produto e local</h2><Exportar url="/api/estoque" f={f} /></div>
          <div><Tabela dados={d?.tabela || null} truncado={d?.truncado} /></div>
        </div>
      </div>
      {janela && <JanelaTop lista={top} fechar={() => setJanela(false)} />}
    </div>
  );
}
