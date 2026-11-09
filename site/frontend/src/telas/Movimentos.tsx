// Movimentos: documentos do período com gráficos por mês, categoria, cliente e vendedor.
import { useEffect, useState } from "react";
import { opcoesGerais, type Opcoes } from "../api";
import { F, fmtData, guardado } from "../formatos";
import { Kpis } from "../componentes/Kpis";
import { Barras, Colunas, type ItemBarra } from "../componentes/Graficos";
import { Tabela, type DadosTabela } from "../componentes/Tabela";
import { useAbrirDocumento } from "../componentes/Documento";
import { Atalhos, Escolha, Exportar, FormFiltros, MultiEscolha, Texto, useDados, useFiltros } from "../componentes/Filtros";

interface Resp {
  kpis: { qtd: number; valor: number; bruto: number; clientes: number };
  periodo: [string, string];
  por_mes: { rotulo: string; valor: number }[]; qtd_mes: { rotulo: string; valor: number }[];
  por_categoria: ItemBarra[]; por_tipo: ItemBarra[]; top_clientes: ItemBarra[]; top_vendedores: ItemBarra[];
  tabela: DadosTabela; truncado: boolean;
}

const PADRAO = { ini: "", fim: "", tipos: "", prefixo: "", vendedor: "", cliente: "", ccusto: "", depto: "", filial: "", cancelados: "" };

export default function Movimentos() {
  const f = useFiltros(PADRAO, { periodo: true });
  const [o, setO] = useState<Opcoes | null>(null);
  useEffect(() => { opcoesGerais().then(setO).catch(() => setO({})); }, []);
  // como antes: as opções chegam antes da primeira busca
  const { dados: d, carregando } = useDados<Resp>("/api/movimentos", f, o !== null);
  const abrirDoc = useAbrirDocumento();
  const [metrica, setMetrica] = useState("valor");
  const [modo, setModo] = useState(() => (guardado.ler("mov_modo_tipo") === "tipo" ? "tipo" : "cat"));

  // sem datas nos filtros: mostra o período que o servidor usou
  const ini = f.form.ini || d?.periodo[0] || "", fim = f.form.fim || d?.periodo[1] || "";
  const moeda = metrica !== "qtd";
  const cat = modo === "cat";

  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f} aoLimpar={() => f.limpar()}>
        <label>De<input type="date" name="ini" value={ini} onChange={(e) => f.set("ini", e.target.value)} /></label>
        <label>Até<input type="date" name="fim" value={fim} onChange={(e) => f.set("fim", e.target.value)} /></label>
        <Atalhos f={f} />
        <label>Tipo de movimento<Escolha f={f} nome="tipos" className="largo" lista={o?.tipos || []} vazio="Todos os tipos" /></label>
        <label>Tipo inicia com<Texto f={f} nome="prefixo" placeholder="ex.: 2.2" style={{ minWidth: 90, width: 100 }} /></label>
        <label>Vendedor / funcionário<Escolha f={f} nome="vendedor" className="largo" lista={o?.vendedores || []} vazio="Todos" /></label>
        <label>Cliente<Texto f={f} nome="cliente" placeholder="código ou nome" /></label>
        <MultiEscolha f={f} nome="ccusto" rotulo="Centro de custo" lista={o?.ccustos || []} vazio="Todos" unidade="centros selecionados" />
        <MultiEscolha f={f} nome="depto" rotulo="Departamento" lista={o?.departamentos || []} vazio="Todos" unidade="departamentos selecionados" />
        <label>Filial<Escolha f={f} nome="filial" auto lista={o?.filiais || []} vazio="Todas" /></label>
        <label>Cancelados<Escolha f={f} nome="cancelados" auto>
          <option value="">Sem cancelados</option><option value="1">Incluir cancelados</option><option value="so">Apenas cancelados</option>
        </Escolha></label>
      </FormFiltros>
      <div className="kpis">
        {d && <Kpis lista={[
          { rotulo: "Movimentos", valor: F.inteiro(d.kpis.qtd), detalhe: `${fmtData(d.periodo[0])} a ${fmtData(d.periodo[1])}` },
          { rotulo: "Valor líquido", valor: F.compacto(d.kpis.valor, true), detalhe: F.moeda(d.kpis.valor) },
          { rotulo: "Valor bruto", valor: F.compacto(d.kpis.bruto, true), detalhe: F.moeda(d.kpis.bruto) },
          { rotulo: "Clientes distintos", valor: F.inteiro(d.kpis.clientes) },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c8">
          <div className="cartao-cab"><h2>Por mês</h2>
            <select className="campo" style={{ minWidth: "auto", height: 28 }} value={metrica} onChange={(e) => setMetrica(e.target.value)}>
              <option value="valor">Valor líquido</option><option value="qtd">Quantidade</option>
            </select>
          </div>
          <div>{d && <Colunas series={[{ nome: moeda ? "Valor" : "Quantidade", pontos: moeda ? d.por_mes : d.qtd_mes }]} formato={moeda ? F.moeda : F.inteiro} moeda={moeda} />}</div>
        </div>
        <div className="cartao c4">
          <div className="cartao-cab"><h2>Por <span>{cat ? "categoria" : "tipo"}</span> <span className="sub">· quantidade, clique para filtrar</span></h2>
            <select className="campo" style={{ minWidth: "auto", height: 28 }} aria-label="Agrupar por" value={modo}
              onChange={(e) => { guardado.gravar("mov_modo_tipo", e.target.value); setModo(e.target.value); }}>
              <option value="cat">Categoria</option><option value="tipo">Tipo</option>
            </select>
          </div>
          <div>{d && <Barras key={modo} dados={cat ? d.por_categoria : d.por_tipo} onClick={(x) => {
            if (x.rotulo === "Outros") return;
            if (cat) f.aplicar({ prefixo: x.rotulo.split(" ")[0] + "." });
            else f.aplicar({ tipos: x.rotulo.split(" ")[0] });
          }} />}</div>
        </div>
        <div className="cartao c6">
          <div className="cartao-cab"><h2>10 maiores clientes <span className="sub">· valor, clique para filtrar</span></h2></div>
          <div>{d && <Barras dados={d.top_clientes} formato={F.moeda} compacto moeda cor="var(--serie-3)"
            onClick={(x) => { if (x.rotulo !== "Outros") f.aplicar({ cliente: x.rotulo }); }} />}</div>
        </div>
        <div className="cartao c6">
          <div className="cartao-cab"><h2>Por vendedor / funcionário <span className="sub">· 10 maiores, valor</span></h2></div>
          <div>{d && <Barras dados={d.top_vendedores} formato={F.moeda} compacto moeda cor="var(--serie-7)" />}</div>
        </div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>Documentos <span className="sub">· clique em uma linha para ver os materiais</span></h2>
            <Exportar url="/api/movimentos" f={f} /></div>
          <div><Tabela dados={d?.tabela || null} truncado={d?.truncado} ocultar={OCULTAR}
            onClick={(r, cols) => abrirDoc(r[cols.indexOf("IDMOV")])} /></div>
        </div>
      </div>
    </div>
  );
}
const OCULTAR = ["IDMOV", "CODCFO"];

