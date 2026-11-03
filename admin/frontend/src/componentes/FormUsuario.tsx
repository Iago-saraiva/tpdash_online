import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Empresa, Modulos, Usuario } from "../tipos";

interface Props {
  usuario: Usuario | null;          // null = novo
  empresas: Empresa[];
  modulos: Modulos;
  empresaPadrao: string;
  agir: (fn: () => Promise<unknown>, ok?: string) => Promise<boolean>;
  onFechar: () => void;
}

export default function FormUsuario({ usuario: u, empresas, modulos, empresaPadrao, agir, onFechar }: Props) {
  const [empresa, setEmpresa] = useState(u?.empresa_id || empresaPadrao);
  const [login, setLogin] = useState(u?.login || "");
  const [nome, setNome] = useState(u?.nome || "");
  const [senha, setSenha] = useState("");
  const [admin, setAdmin] = useState(!!u?.admin);
  const [ativo, setAtivo] = useState(u ? !!u.ativo : true);
  const [mods, setMods] = useState<string[]>(u ? u.modulos : ["inicio"]);
  const ref = useRef<HTMLFormElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth" }); }, []);

  const nomeEmp = empresas.find((e) => e.id === empresa)?.nome || empresa;
  const mudouEmpresa = !!u && u.empresa_id !== empresa;

  const salvar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const ok = await agir(() => api("/api/usuarios", {
      id: u?.id ?? null, empresa, login: login.trim(), nome: nome.trim(), senha, admin, ativo, modulos: mods,
    }), `Usuário ${login.trim()} salvo na empresa ${nomeEmp}.`);
    if (ok) onFechar();
  };

  return (
    <form ref={ref} onSubmit={salvar} autoComplete="off" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="cartao-cab" style={{ margin: 0 }}><h2>{u ? `Editar ${u.login}` : "Novo usuário"}</h2></div>
      <div className="form-grade">
        <label>Empresa do usuário
          <select className="campo" required value={empresa} onChange={(e) => setEmpresa(e.target.value)}>
            {empresas.map((e) => <option key={e.id} value={e.id}>{e.nome} ({e.id}){e.ativa ? "" : " · desativada"}</option>)}
          </select>
        </label>
        <label>Login<input className="campo" required value={login} onChange={(e) => setLogin(e.target.value)} /></label>
        <label>Nome<input className="campo" required value={nome} onChange={(e) => setNome(e.target.value)} /></label>
        <label>Senha<input className="campo" type="password" autoComplete="new-password" value={senha} required={!u}
          placeholder={u ? "Vazio mantém a senha; preenchida, ele troca na próxima entrada" : "Senha inicial"}
          onChange={(e) => setSenha(e.target.value)} /></label>
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
        <label className="check"><input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> Administrador da empresa</label>
        <label className="check"><input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} /> Ativo</label>
      </div>
      <div>
        <div className="gtick" style={{ fontSize: 12, marginBottom: 6 }}>Módulos liberados (o administrador vê todos)</div>
        <div className="adm-mods">
          {Object.entries(modulos).map(([k, v]) => (
            <label className="check" key={k}>
              <input type="checkbox" checked={admin || mods.includes(k)} disabled={admin}
                onChange={(e) => setMods((m) => e.target.checked ? [...m, k] : m.filter((x) => x !== k))} /> {v}
            </label>
          ))}
        </div>
      </div>
      {mudouEmpresa && <div className="aviso atencao" style={{ margin: 0 }}>O usuário vai mudar de empresa. Os relatórios e tipos de movimento escolhidos para ele voltam para "todos".</div>}
      <p className="nota" style={{ margin: 0 }}>
        O usuário é cadastrado na empresa escolhida acima, troca a senha na primeira entrada e só enxerga os dados dela.
        Relatórios e tipos de movimento de cada usuário são ajustados na Administração do TP DASH, dentro da empresa.
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn primario">Salvar usuário</button>
        <button className="btn" type="button" onClick={onFechar}>Cancelar</button>
      </div>
    </form>
  );
}
