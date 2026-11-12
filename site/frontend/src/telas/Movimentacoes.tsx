// Movimentações: produtos com entradas e saídas (abas "mexe" e "não mexe" com estoque) e o extrato de cada um.
import { useEffect, useState } from "react";
import { api, baixar, opcoesGerais, type Opcoes } from "../api";
import { DADOS } from "../dados";
import { F, fmtData } from "../formatos";
import { Kpis } from "../componentes/Kpis";
import { Campos, useGaveta } from "../componentes/Gaveta";
import { Tabela, type Celula, type DadosTabela } from "../componentes/Tabela";
import { Erro, useAbrirDocumento } from "../componentes/Documento";
import { Escolha, Exportar, FormFiltros, Marcar, Periodo, Texto, paraBusca, useDados, useFiltros, type Valores } from "../componentes/Filtros";

const ROT_MOV: Record<string, string> = { SALDO: "Saldo atual", ENTRADAS: "Qtd. entradas", SAIDAS: "Qtd. saídas", MOVIMENTOS: "Lançamentos",
  ULTIMO: "Último movimento", QTD_TOTAL: "Quantidade", ENTRADA: "Entrada", SAIDA: "Saída", MOVIMENTO: "Movimento" };
const ROT_PRODUTO = { ...ROT_MOV, SALDO: "Saldo após" };
const NOTA_MOV: Record<string, string> = {
  estoque: "Movimentos que dão entrada ou saída no saldo físico do produto (conforme o tipo de movimento no Puma). Cancelados não entram.",
  sem: "Movimentos que não alteram o saldo físico: pedidos, solicitações, orçamentos, empenhos, notas de serviço etc. Cancelados não entram.",
};
const PADRAO = { aba: "estoque", ini: "", fim: "", filial: "", grupo: "", busca: "", com_mov: "", inativos: "" };

interface Resp {
  aba: string;
  kpis: { produtos: number; com_mov: number; entradas: number; saidas: number; lancamentos: number; valor: number };
  tabela: DadosTabela; truncado: boolean;
}
interface RespProduto {
  aba: string;
  produto: { codprd: string; fabricante?: string; nome: string; und: string };
  resumo: Record<string, number>;
  tabela: DadosTabela; truncado: boolean;
}

const podeDoc = () => (DADOS.usuario?.modulos || []).includes("movimentos");
const celulaProduto: Celula = (c, v) => {
  if (c === "MOVIMENTO") return { conteudo: <span className={"tag " + (v === "Entrada" ? "entrada" : "critico")}>{String(v)}</span> };
  if ((c === "ENTRADA" || c === "SAIDA") && !v) return { className: "num", conteudo: "" };
  return null;
};

/** extrato do produto na gaveta (período, filial e aba da tela) */
function ExtratoProduto({ q, reabrir }: { q: URLSearchParams; reabrir: () => void }) {
  const g = useGaveta();
  const abrirDoc = useAbrirDocumento();
  const [d, setD] = useState<RespProduto | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<RespProduto>("/api/movimentacoes/produto?" + q).then((x) => {
      g.titulo(`${x.produto.fabricante || x.produto.codprd} · ${x.produto.nome}`);
      setD(x);
    }).catch((e) => setErro(e.message));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <Erro msg={erro} />;
  const p = d.produto, r = d.resumo;
  const per = q.get("ini") || q.get("fim") ? `${q.get("ini") ? fmtData(q.get("ini")) : "início"} a ${q.get("fim") ? fmtData(q.get("fim")) : "hoje"}` : "todo o histórico";
  const bx = (fmt: string) => { const z = new URLSearchParams(q); z.set("formato", fmt); baixar("/api/movimentacoes/produto?" + z).catch((e) => setErro(e.message)); };
  return <>
    <Erro msg={erro} />
    {d.aba === "estoque"
      ? <Campos pares={[["Período", per], ["Unidade", p.und],
        [q.get("ini") ? "Saldo antes do período" : "Saldo inicial", F.numero(r.saldo_anterior)], ["Entradas", F.numero(r.entradas)],
        ["Saídas", F.numero(r.saidas)], ["Saldo no fim do período", F.numero(r.saldo_final)]]} />
      : <Campos pares={[["Período", per], ["Unidade", p.und], ["Lançamentos", F.inteiro(r.lancamentos)],
        ["Quantidade", F.numero(r.qtd)], ["Valor", F.moeda(r.valor)], ["Saldo atual do estoque", F.numero(r.saldo_atual)]]} />}
    <p className="nota">{(d.aba === "estoque" ? "Movimentos que mexem no estoque" : "Movimentos que não mexem no estoque") +
      " · mais recentes primeiro" + (podeDoc() ? " · clique em um documento para ver os itens" : "")}</p>
    {!d.tabela.linhas.length && <p className="nota">Nenhum movimento deste produto com os filtros escolhidos.</p>}
    <div>
      <Tabela dados={d.tabela} truncado={d.truncado} porPagina={100} ocultar={["IDMOV"]} rotulos={ROT_PRODUTO} celula={celulaProduto}
        botoes={<><button className="btn pequeno" onClick={() => bx("xlsx")}>Excel</button><button className="btn pequeno" onClick={() => bx("pdf")}>PDF</button></>}
        onClick={podeDoc() ? (row, cols) => abrirDoc(row[cols.indexOf("IDMOV")], reabrir, "‹ Voltar para o produto") : undefined} />
    </div>
  </>;
}

export default function Movimentacoes() {
  const f = useFiltros(PADRAO);
  const g = useGaveta();
  const [o, setO] = useState<Opcoes | null>(null);
  useEffect(() => { opcoesGerais().then(setO).catch(() => setO({})); }, []);
  const { dados: d, carregando } = useDados<Resp>("/api/movimentacoes", f, o !== null);
  const aba = f.form.aba === "sem" ? "sem" : "estoque";

  // parâmetros que valem para a janela do produto (período, filial e aba)
  const abrirProduto = (codprd: unknown, filtros: Valores) => {
    const p = paraBusca(filtros);
    const q = new URLSearchParams();
    ["aba", "ini", "fim", "filial"].forEach((k) => { if (p.get(k)) q.set(k, p.get(k)!); });
    q.set("codprd", String(codprd));
    const abrir = () => g.abrir({ titulo: "Carregando…", larga: true, corpo: <ExtratoProduto q={q} reabrir={abrir} /> });
    abrir();
  };

  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <div className="abas" role="tablist">
        {[["estoque", "Mexe com estoque"], ["sem", "Não mexe com estoque"]].map(([k, rot]) => (
          <button key={k} type="button" className={aba === k ? "ativa" : ""} aria-selected={aba === k}
            onClick={() => { if (aba !== k) f.aplicar({ aba: k }); }}>{rot}</button>
        ))}
      </div>
      <div className="secao">
        <FormFiltros f={f} aoLimpar={() => f.limpar({ aba })}>
          <Periodo f={f} />
          <label>Produto<Texto f={f} nome="busca" placeholder="código ou nome" className="largo" /></label>
          <label>Grupo<Escolha f={f} nome="grupo" className="largo" auto lista={o?.grupos || []} vazio="Todos os grupos" /></label>
          <label>Filial<Escolha f={f} nome="filial" auto lista={o?.filiais || []} vazio="Todas" /></label>
          <Marcar f={f} nome="com_mov" auto>só produtos com movimento</Marcar>
          <Marcar f={f} nome="inativos" auto>incluir inativos</Marcar>
        </FormFiltros>
        <p className="nota">{NOTA_MOV[aba]}</p>
        <div className="kpis">
          {d && <Kpis lista={[
            { rotulo: "Produtos listados", valor: F.inteiro(d.kpis.produtos) },
            { rotulo: "Com movimento", valor: F.inteiro(d.kpis.com_mov), classe: "destaque" },
            ...(d.aba === "estoque"
              ? [{ rotulo: "Lançamentos de entrada", valor: F.inteiro(d.kpis.entradas) }, { rotulo: "Lançamentos de saída", valor: F.inteiro(d.kpis.saidas) }]
              : [{ rotulo: "Lançamentos", valor: F.inteiro(d.kpis.lancamentos) }, { rotulo: "Valor dos itens", valor: F.compacto(d.kpis.valor, true), detalhe: F.moeda(d.kpis.valor) }]),
          ]} />}
        </div>
        <div className="grade">
          <div className="cartao c12">
            <div className="cartao-cab"><h2>Produtos <span className="sub">· clique em um produto para ver os movimentos</span></h2>
              <Exportar url="/api/movimentacoes" f={f} /></div>
            {/* colunas diferentes em cada aba: tabela nova ao trocar */}
            <div><Tabela key={d?.aba} dados={d && d.aba === aba ? d.tabela : null} truncado={d?.truncado} ocultar={["CODPRD_INT"]} rotulos={ROT_MOV}
              onClick={(r, cols) => abrirProduto(r[cols.indexOf("CODPRD_INT")], f.form)} /></div>
          </div>
        </div>
      </div>
    </div>
  );
}
