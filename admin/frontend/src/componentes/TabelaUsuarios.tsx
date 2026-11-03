import { useMemo, useState } from "react";
import { api } from "../api";
import type { Empresa, Usuario } from "../tipos";

interface Props {
  usuarios: Usuario[];
  empresas: Empresa[];
  filtro: string;
  onFiltro: (id: string) => void;
  onNovo: () => void;
  onEditar: (u: Usuario) => void;
  agir: (fn: () => Promise<unknown>, ok?: string) => Promise<boolean>;
}

export default function TabelaUsuarios({ usuarios, empresas, filtro, onFiltro, onNovo, onEditar, agir }: Props) {
  const [busca, setBusca] = useState("");
  const nomeEmp = (id: string | null) => empresas.find((e) => e.id === id)?.nome || id || "(sem empresa)";
  const lista = useMemo(() => {
    const b = busca.trim().toLowerCase();
    return usuarios.filter((u) => (!filtro || u.empresa_id === filtro) &&
      (!b || u.login.toLowerCase().includes(b) || u.nome.toLowerCase().includes(b)));
  }, [usuarios, filtro, busca]);

  const alternar = (u: Usuario) => {
    if (u.ativo && !confirm(`Desativar ${u.login}? Ele deixa de conseguir entrar.`)) return;
    agir(() => api("/api/usuarios", { id: u.id, empresa: u.empresa_id, login: u.login, nome: u.nome, admin: !!u.admin, ativo: !u.ativo, modulos: u.modulos }));
  };

  return (
    <>
      <div className="cartao-cab">
        <h2>{filtro ? `Usuários · ${nomeEmp(filtro)}` : "Usuários de todas as empresas"}</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input className="campo adm-busca" placeholder="Buscar login ou nome" value={busca} onChange={(e) => setBusca(e.target.value)} />
          <select className="campo" style={{ minWidth: 180 }} value={filtro} onChange={(e) => onFiltro(e.target.value)}>
            <option value="">Todas as empresas</option>
            {empresas.map((e) => <option key={e.id} value={e.id}>{e.nome} ({e.id}){e.ativa ? "" : " · desativada"}</option>)}
          </select>
          <button className="btn pequeno primario" type="button" onClick={onNovo}>Novo usuário</button>
        </div>
      </div>
      <div className="tabela-wrap">
        <table className="dados">
          <thead><tr><th>Login</th><th>Nome</th><th>Empresa</th><th>Perfil</th><th>Situação</th><th>Último acesso</th><th /></tr></thead>
          <tbody>
            {!lista.length && <tr><td colSpan={7} className="adm-vazio">Nenhum usuário.</td></tr>}
            {lista.map((u) => (
              <tr key={u.id}>
                <td>{u.login}</td><td>{u.nome}</td><td>{nomeEmp(u.empresa_id)}</td>
                <td>{u.admin ? "Administrador" : "Usuário"}</td><td>{u.ativo ? "Ativo" : "Inativo"}</td>
                <td>{u.ultimo_acesso || "nunca"}</td>
                <td><div className="adm-acoes">
                  <button className="btn pequeno" type="button" onClick={() => onEditar(u)}>Editar</button>
                  <button className="btn pequeno" type="button" onClick={() => alternar(u)}>{u.ativo ? "Desativar" : "Ativar"}</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
