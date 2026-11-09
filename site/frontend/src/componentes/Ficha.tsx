// Ficha do cliente/fornecedor na gaveta: cadastro + abas Financeiro e Movimentos.
import { useEffect, useState } from "react";
import { api, baixar } from "../api";
import { F, fmtData } from "../formatos";
import { Campos, useGaveta } from "./Gaveta";
import { Erro, useAbrirDocumento } from "./Documento";
import { Kpis } from "./Kpis";
import { Tabela, type DadosTabela } from "./Tabela";

interface Resp { cadastro: DadosTabela; abas: string[] }
interface RespAba { kpis: Record<string, number | string | null>; tabela: DadosTabela; truncado: boolean }
const NOMES: Record<string, string> = { financeiro: "Financeiro", movimentos: "Movimentos" };

export function useAbrirFicha() {
  const g = useGaveta();
  const abrir = (cod: unknown, abaInicial?: string) =>
    g.abrir({ titulo: "Carregando…", larga: true, corpo: <Ficha cod={String(cod)} abaInicial={abaInicial} reabrir={abrir} /> });
  return abrir;
}

function Ficha({ cod, abaInicial, reabrir }: { cod: string; abaInicial?: string; reabrir: (cod: string, aba?: string) => void }) {
  const g = useGaveta();
  const [d, setD] = useState<Resp | null>(null);
  const [erro, setErro] = useState("");
  const [aba, setAba] = useState("");
  useEffect(() => {
    api<Resp>("/api/cadastro/" + encodeURIComponent(cod)).then((x) => {
      const c = x.cadastro.colunas, r = x.cadastro.linhas[0];
      g.titulo(`${cod} - ${r[c.indexOf("NOME")] || ""}`);
      setD(x);
      setAba(x.abas.includes(abaInicial || "") ? abaInicial! : x.abas[0] || "");
    }).catch((e) => setErro(e.message));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <Erro msg={erro} />;
  const c = d.cadastro.colunas, r = d.cadastro.linhas[0];
  const v = (n: string) => r[c.indexOf(n)] as string | null;
  return <>
    <Campos pares={[
      ["Nome fantasia", v("FANTASIA")], ["CPF/CNPJ", v("CPF_CNPJ")], ["Tipo", v("TIPO")],
      ["Cidade/UF", [v("CIDADE"), v("UF")].filter(Boolean).join(" / ")], ["Telefone", v("TELEFONE")], ["E-mail", v("EMAIL")],
    ]} />
    {!d.abas.length ? <Erro tipo="atencao" msg="Você não tem acesso ao Financeiro nem aos Movimentos." /> : <>
      <div className="abas" style={{ marginTop: 14 }}>
        {d.abas.map((a) => <button key={a} className={a === aba ? "ativa" : ""} onClick={() => setAba(a)}>{NOMES[a]}</button>)}
      </div>
      <div style={{ marginTop: 12 }}>{aba && <AbaFicha key={aba} cod={cod} aba={aba} voltar={() => reabrir(cod, "movimentos")} />}</div>
    </>}
  </>;
}

function AbaFicha({ cod, aba, voltar }: { cod: string; aba: string; voltar: () => void }) {
  const abrirDoc = useAbrirDocumento();
  const [x, setX] = useState<RespAba | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<RespAba>(`/api/cadastro/${encodeURIComponent(cod)}?aba=${aba}`).then(setX).catch((e) => setErro(e.message));
  }, [cod, aba]);
  if (!x) return erro ? <Erro msg={erro} /> : <p className="nota">Carregando…</p>;
  const k = x.kpis as Record<string, number>;
  const lista = aba === "financeiro" ? [
    { rotulo: "A receber em aberto", valor: F.moeda(k.receber_aberto), detalhe: k.receber_vencido ? `vencido ${F.moeda(k.receber_vencido)}` : "nada vencido", classe: k.receber_vencido ? "critico" : "" },
    { rotulo: "A pagar em aberto", valor: F.moeda(k.pagar_aberto), detalhe: k.pagar_vencido ? `vencido ${F.moeda(k.pagar_vencido)}` : "nada vencido", classe: k.pagar_vencido ? "critico" : "" },
    { rotulo: "Já recebido", valor: F.moeda(k.recebido) },
    { rotulo: "Já pago", valor: F.moeda(k.pago) },
  ] : [
    { rotulo: "Movimentos", valor: F.inteiro(k.qtd), detalhe: k.cancelados ? `+ ${k.cancelados} cancelado(s)` : "" },
    { rotulo: "Valor total", valor: F.moeda(k.valor), detalhe: "sem cancelados" },
    { rotulo: "Primeiro", valor: k.primeiro ? fmtData(k.primeiro) : "—" },
    { rotulo: "Último", valor: k.ultimo ? fmtData(k.ultimo) : "—" },
  ];
  const bx = (fmt: string) => baixar(`/api/cadastro/${encodeURIComponent(cod)}?aba=${aba}&formato=${fmt}`).catch((e) => setErro(e.message));
  return <>
    <Erro msg={erro} />
    <div className="kpis" style={{ marginBottom: 12 }}><Kpis lista={lista} /></div>
    <div>
      <Tabela dados={x.tabela} truncado={x.truncado} ocultar={["IDMOV", "CODCFO", "CLIENTE"]}
        botoes={<><button className="btn pequeno" onClick={() => bx("xlsx")}>Excel</button><button className="btn pequeno" onClick={() => bx("pdf")}>PDF</button></>}
        onClick={aba === "movimentos" ? (row, cols) => abrirDoc(row[cols.indexOf("IDMOV")], voltar) : undefined} />
    </div>
    {!x.tabela.linhas.length && <p className="nota">{aba === "financeiro" ? "Nenhum lançamento para este cadastro." : "Nenhum movimento para este cadastro."}</p>}
  </>;
}
