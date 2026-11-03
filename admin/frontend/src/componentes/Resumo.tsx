import type { Empresa, Usuario } from "../tipos";

export default function Resumo({ empresas, usuarios }: { empresas: Empresa[]; usuarios: Usuario[] }) {
  const ativas = empresas.filter((e) => e.ativa).length;
  const online = empresas.filter((e) => e.online).length;
  const semChave = empresas.filter((e) => e.ativa && !e.tem_chave).length;
  const itens: [string, number][] = [
    ["Empresas ativas", ativas],
    ["Agentes conectados", online],
    ["Empresas sem chave", semChave],
    ["Usuários ativos", usuarios.filter((u) => u.ativo).length],
  ];
  return (
    <div className="adm-resumo">
      {itens.map(([rot, n]) => (
        <div className="cartao" key={rot}><div className="num">{n}</div><div className="rot">{rot}</div></div>
      ))}
    </div>
  );
}
