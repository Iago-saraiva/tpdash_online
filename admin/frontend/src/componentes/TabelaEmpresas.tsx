import { api } from "../api";
import type { Empresa, Usuario } from "../tipos";

interface Props {
  empresas: Empresa[];
  usuarios: Usuario[];
  escolhida: string;
  carregado: boolean;
  onEscolher: (id: string) => void;
  agir: (fn: () => Promise<unknown>, ok?: string) => Promise<boolean>;
  onChave: (nome: string, chave: string) => void;
}

const url = (id: string, resto = "") => `/api/empresas/${encodeURIComponent(id)}${resto}`;

export default function TabelaEmpresas({ empresas, usuarios, escolhida, carregado, onEscolher, agir, onChave }: Props) {
  const parar = (fn: () => void) => (ev: React.MouseEvent) => { ev.stopPropagation(); fn(); };

  const gerarChave = (e: Empresa) => {
    if (e.tem_chave && !confirm(`Gerar uma chave nova para ${e.nome}? A chave atual para de funcionar e o agente precisa ser atualizado.`)) return;
    agir(async () => onChave(e.nome, (await api<{ chave: string }>(url(e.id, "/chave"), {})).chave));
  };
  const bloquear = (e: Empresa) => {
    if (!confirm(`Bloquear a chave de ${e.nome}? O agente desconecta até receber uma chave nova.`)) return;
    agir(() => api(url(e.id, "/chave"), { acao: "bloquear" }), `Chave de ${e.nome} bloqueada.`);
  };
  const renomear = (e: Empresa) => {
    const nome = prompt("Nome da empresa:", e.nome)?.trim();
    if (!nome || nome === e.nome) return;
    agir(() => api("/api/empresas", { id: e.id, nome, ativa: !!e.ativa }));
  };
  const alternar = (e: Empresa) => {
    if (e.ativa && !confirm(`Desativar ${e.nome}? Os usuários e o agente dela perdem o acesso.`)) return;
    agir(() => api("/api/empresas", { id: e.id, nome: e.nome, ativa: !e.ativa }));
  };

  return (
    <>
      <div className="cartao-cab"><h2>Empresas <span className="sub">· clique em uma empresa para ver filiais e usuários</span></h2></div>
      <div className="tabela-wrap">
        <table className="dados">
          <thead><tr><th>Empresa</th><th>Situação</th><th>Agente</th><th>Filiais</th><th>Usuários</th><th /></tr></thead>
          <tbody>
            {carregado && !empresas.length && <tr><td colSpan={6} className="adm-vazio">Nenhuma empresa cadastrada.</td></tr>}
            {empresas.map((e) => {
              const f = e.filiais;
              return (
                <tr key={e.id} className={"adm-linha" + (e.id === escolhida ? " escolhida" : "")} onClick={() => onEscolher(e.id)}>
                  <td><strong>{e.nome}</strong><br /><span className="nota">{e.id}</span></td>
                  <td>{e.ativa ? "Ativa" : "Desativada"}</td>
                  <td>
                    <span className={"tag " + (e.online ? "entrada" : "")}>{e.online ? "Conectado" : e.tem_chave ? "Desconectado" : "Sem chave"}</span><br />
                    <span className="nota">{e.visto ? `último contato ${e.visto}` : "nunca conectou"}</span>
                  </td>
                  <td>{f ? (f.length === 1 ? "1 filial" : f.length ? `${f.length} filiais` : "nenhuma") : "—"}</td>
                  <td>{usuarios.filter((u) => u.empresa_id === e.id).length}</td>
                  <td>
                    <div className="adm-acoes">
                      <button className="btn pequeno" type="button" onClick={parar(() => gerarChave(e))}>{e.tem_chave ? "Nova chave" : "Gerar chave"}</button>
                      {!!e.tem_chave && <button className="btn pequeno" type="button" onClick={parar(() => bloquear(e))}>Bloquear</button>}
                      <button className="btn pequeno" type="button" onClick={parar(() => renomear(e))}>Renomear</button>
                      <button className="btn pequeno" type="button" onClick={parar(() => alternar(e))}>{e.ativa ? "Desativar" : "Ativar"}</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
