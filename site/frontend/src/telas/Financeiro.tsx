// Financeiro: títulos a pagar e a receber, por mês, por atraso e por cliente/fornecedor.
import { useEffect, useState } from "react";
import { opcoesGerais, type Opcoes } from "../api";
import { F } from "../formatos";
import { Kpis } from "../componentes/Kpis";
import { Barras, Colunas, type ItemBarra, type Serie } from "../componentes/Graficos";
import { Tabela, type Celula, type DadosTabela } from "../componentes/Tabela";
import { Escolha, Exportar, FormFiltros, MultiEscolha, Periodo, Texto, useDados, useFiltros } from "../componentes/Filtros";

interface Resp {
  kpis: { aberto: number; vencido: number; a_vencer_30: number; qtd: number; total: number };
  periodo: [string, string];
  por_mes: Serie[]; aging: ItemBarra[]; top_nomes: ItemBarra[];
  tabela: DadosTabela; truncado: boolean;
}

const PADRAO = { tipo: "R", status: "A", base: "vencimento", ini: "", fim: "", tipodoc: "", ccusto: "", depto: "", cliente: "", filial: "" };
const OCULTAR = ["IDLAN"];
const celula: Celula = (c, v) => {
  if (c !== "DIAS_ATRASO") return null;
  const n = v as number;
  return { className: "num", conteudo: n > 0 ? <span className={"tag " + (n > 30 ? "critico" : "atencao")}>{n} dias</span> : null };
};

export default function Financeiro() {
  const f = useFiltros(PADRAO, { periodo: true });
  const [o, setO] = useState<Opcoes | null>(null);
  useEffect(() => { opcoesGerais().then(setO).catch(() => setO({})); }, []);
  const { dados: d, carregando } = useDados<Resp>("/api/financeiro", f, o !== null);
  const tipo = f.form.tipo;
  const ini = f.form.ini || d?.periodo[0] || "", fim = f.form.fim || d?.periodo[1] || "";

  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f}>
        <label>Tipo<Escolha f={f} nome="tipo" auto><option value="R">A receber</option><option value="P">A pagar</option><option value="T">Ambos</option></Escolha></label>
        <label>Situação<Escolha f={f} nome="status" auto><option value="A">Em aberto</option><option value="B">Baixados</option><option value="C">Cancelados</option><option value="*">Todos</option></Escolha></label>
        <Periodo f={f} ini={ini} fim={fim} rotulo={"Período · " + (({ vencimento: "vencimento", emissao: "emissão", baixa: "baixa" } as Record<string, string>)[f.form.base] || "vencimento")} />
        <label>Cliente / fornecedor<Texto f={f} nome="cliente" placeholder="código ou nome" className="largo" /></label>
        <label>Data base<Escolha f={f} nome="base"><option value="vencimento">Vencimento</option><option value="emissao">Emissão</option><option value="baixa">Baixa</option></Escolha></label>
        <MultiEscolha f={f} nome="tipodoc" rotulo="Tipo de documento" lista={o?.tipos_doc || []} vazio="Todos os tipos" />
        <MultiEscolha f={f} nome="ccusto" rotulo="Centro de custo" lista={o?.ccustos || []} vazio="Todos" unidade="centros selecionados" />
        <MultiEscolha f={f} nome="depto" rotulo="Departamento" lista={o?.departamentos || []} vazio="Todos" unidade="departamentos selecionados" />
        <label>Filial<Escolha f={f} nome="filial" auto lista={o?.filiais || []} vazio="Todas" /></label>
      </FormFiltros>
      <div className="kpis">
        {d && <Kpis lista={[
          { rotulo: tipo === "P" ? "A pagar em aberto" : tipo === "R" ? "A receber em aberto" : "Em aberto", valor: F.compacto(d.kpis.aberto, true), detalhe: F.moeda(d.kpis.aberto), classe: "destaque" },
          { rotulo: "Vencido", valor: F.compacto(d.kpis.vencido, true), detalhe: F.moeda(d.kpis.vencido), classe: d.kpis.vencido ? "critico" : "" },
          { rotulo: "Vence em 30 dias", valor: F.compacto(d.kpis.a_vencer_30, true), detalhe: F.moeda(d.kpis.a_vencer_30) },
          { rotulo: "Títulos no filtro", valor: F.inteiro(d.kpis.qtd), detalhe: `Total ${F.moeda(d.kpis.total)}` },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c8">
          <div className="cartao-cab"><h2>Por mês <span className="sub">· conforme a data base escolhida</span></h2></div>
          <div>{d && <Colunas series={d.por_mes} formato={F.moeda} moeda corInicial={f.aplicado.tipo === "P" ? 1 : 0} />}</div>
        </div>
        <div className="cartao c4">
          <div className="cartao-cab"><h2>Em aberto por atraso</h2></div>
          <div>{d && <Barras dados={d.aging.map((a, i) => ({ ...a, cor: i === 0 ? "var(--serie-1)" : i < 3 ? "var(--serie-4)" : "var(--serie-8)" }))}
            formato={F.moeda} compacto moeda larguraRotulo={110} />}</div>
        </div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>10 maiores clientes / fornecedores <span className="sub">· clique para filtrar</span></h2></div>
          <div>{d && <Barras dados={d.top_nomes} formato={F.moeda} compacto moeda cor="var(--serie-3)"
            onClick={(x) => { if (x.rotulo !== "Outros") f.aplicar({ cliente: x.rotulo }); }} />}</div>
        </div>
        <div className="cartao c12">
          <div className="cartao-cab"><h2>Títulos</h2><Exportar url="/api/financeiro" f={f} /></div>
          <div><Tabela dados={d?.tabela || null} truncado={d?.truncado} ocultar={OCULTAR} celula={celula} /></div>
        </div>
      </div>
    </div>
  );
}
