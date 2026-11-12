import type { Empresa, Usuario, UsoBanco } from "../tipos";

function mb(bytes: number) {
  const m = bytes / 1048576;
  return m >= 1024 ? `${(m / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} GB` : `${Math.round(m).toLocaleString("pt-BR")} MB`;
}

export default function Resumo({ empresas, usuarios, banco }: { empresas: Empresa[]; usuarios: Usuario[]; banco?: UsoBanco | null }) {
  const ativas = empresas.filter((e) => e.ativa).length;
  const online = empresas.filter((e) => e.online).length;
  const semChave = empresas.filter((e) => e.ativa && !e.tem_chave).length;
  const itens: [string, number][] = [
    ["Empresas ativas", ativas],
    ["Agentes conectados", online],
    ["Empresas sem chave", semChave],
    ["Usuários ativos", usuarios.filter((u) => u.ativo).length],
  ];
  const nivel = !banco ? "" : banco.pct >= 95 ? "critico" : banco.pct >= 80 ? "alerta" : "";
  return (
    <>
      {nivel && banco && (
        <div className={"aviso-banco " + nivel} role="alert">
          <strong>{nivel === "critico" ? "Banco do site quase cheio" : "Banco do site passando de 80%"}:</strong>{" "}
          {mb(banco.usado)} de {mb(banco.limite)} ({banco.pct.toLocaleString("pt-BR")}%). Quando encher, o site para de gravar
          (logins, agentes e sincronização). Libere espaço (ex.: cópia de uma empresa grande) ou aumente o plano do Neon.
        </div>
      )}
      <div className="adm-resumo">
        {itens.map(([rot, n]) => (
          <div className="cartao" key={rot}><div className="num">{n}</div><div className="rot">{rot}</div></div>
        ))}
        {banco && (
          <div className={"cartao banco " + nivel} title={`${mb(banco.usado)} usados de ${mb(banco.limite)}`}>
            <div className="num">{Math.round(banco.pct)}%</div>
            <div className="rot">Banco do site · {mb(banco.usado)} de {mb(banco.limite)}</div>
            <div className="barra-banco"><span style={{ width: `${Math.min(100, banco.pct)}%` }} /></div>
          </div>
        )}
      </div>
    </>
  );
}
