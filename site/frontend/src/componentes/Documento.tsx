// Documento (movimento) na gaveta: cabeçalho, itens e PDF.
import { useEffect, useState } from "react";
import { api, baixar } from "../api";
import { DADOS } from "../dados";
import { F, fmtData } from "../formatos";
import { Campos, useGaveta } from "./Gaveta";
import { Tabela, type DadosTabela } from "./Tabela";

interface Resp { cabecalho: DadosTabela; itens: DadosTabela }

export function Erro({ msg, tipo = "erro" }: { msg: string; tipo?: string }) {
  return msg ? <div className={"aviso " + tipo}>{msg}</div> : null;
}

/** Abre o documento na gaveta. `voltar`: botão para voltar à janela anterior (ficha, produto). */
export function useAbrirDocumento() {
  const g = useGaveta();
  return (idmov: unknown, voltar?: () => void, rotuloVoltar?: string) =>
    g.abrir({ titulo: "Carregando…", larga: !!voltar, corpo: <Documento idmov={String(idmov)} voltar={voltar} rotuloVoltar={rotuloVoltar} /> });
}

function Documento({ idmov, voltar, rotuloVoltar }: { idmov: string; voltar?: () => void; rotuloVoltar?: string }) {
  const g = useGaveta();
  const [d, setD] = useState<Resp | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<Resp>("/api/movimentos/" + idmov).then((x) => {
      if (!x.cabecalho.linhas.length) { g.titulo("Documento"); setErro("Documento não encontrado ou não liberado para você."); return; }
      const c = x.cabecalho.colunas, r = x.cabecalho.linhas[0];
      g.titulo(`DOCUMENTO ${r[c.indexOf("DOCUMENTO")] || ""}`);
      setD(x);
    }).catch((e) => setErro(e.message));
  }, [idmov]);  // eslint-disable-line react-hooks/exhaustive-deps

  let corpo = null;
  if (d) {
    const c = d.cabecalho.colunas, r = d.cabecalho.linhas[0];
    const v = (n: string) => r[c.indexOf(n)] as string | number | null;
    const pdf = () => baixar(`/api/relatorio/documentos?ini=1900-01-01&fim=2999-12-31&cancelados=1&cliente=${encodeURIComponent(String(v("CODCFO") || ""))}` +
      `&tipos=${encodeURIComponent(String(v("CODTMV") || ""))}&doc=${idmov}&formato=pdf`).catch((e) => setErro(e.message));
    corpo = <>
      <Campos pares={[
        ["Tipo", `${v("CODTMV") || ""} ${v("TIPO") || ""}`], ["Emissão", fmtData(v("EMISSAO"))], ["Status", v("STATUS")],
        ["Cliente", `${v("CODCFO") || ""} ${v("CLIENTE") || ""}`], ["Vendedor", v("VENDEDOR")], ["Valor", F.moeda(v("VALOR") as number)],
        ["Centro de custo", v("CENTRO_CUSTO")], ["Departamento", v("DEPARTAMENTO")],
      ]} />
      <div><Tabela dados={d.itens} porPagina={500} ocultar={["CODPRD_INT"]} /></div>
      {DADOS.usuario?.modulos.includes("relatorios") && <button className="btn" onClick={pdf}>PDF deste documento</button>}
    </>;
  }
  return <>
    {voltar && <button className="btn pequeno" style={{ marginBottom: 12 }} onClick={voltar}>{rotuloVoltar || "‹ Voltar para a ficha"}</button>}
    <Erro msg={erro} />
    {corpo}
  </>;
}
