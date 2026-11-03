import { useState } from "react";
import { api } from "../api";

interface Props {
  agir: (fn: () => Promise<unknown>, ok?: string) => Promise<boolean>;
  onCriada: (id: string, nome: string, chave: string | null) => void;
}

export default function NovaEmpresa({ agir, onCriada }: Props) {
  const [id, setId] = useState("");
  const [nome, setNome] = useState("");
  const [ativa, setAtiva] = useState(true);
  const [gerar, setGerar] = useState(true);

  const salvar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    let criada: { id: string; chave: string | null } | null = null;
    const ok = await agir(async () => {
      const r = await api<{ id: string }>("/api/empresas", { id: id.trim(), nome: nome.trim(), ativa });
      const chave = gerar ? (await api<{ chave: string }>(`/api/empresas/${encodeURIComponent(r.id)}/chave`, {})).chave : null;
      criada = { id: r.id, chave };
    }, `Empresa ${nome.trim()} salva.`);
    if (ok && criada) {
      const c: { id: string; chave: string | null } = criada;
      onCriada(c.id, nome.trim(), c.chave);
      setId(""); setNome(""); setAtiva(true); setGerar(true);
    }
  };

  return (
    <>
      <div className="cartao-cab"><h2>Nova empresa</h2></div>
      <form onSubmit={salvar} autoComplete="off" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <label className="adm-campo">Identificador
          <input className="campo" required placeholder="ex.: metodo" pattern="[a-z0-9][a-z0-9_\-]{1,29}" value={id}
            onChange={(e) => setId(e.target.value.toLowerCase())} />
        </label>
        <label className="adm-campo">Nome
          <input className="campo" required placeholder="ex.: Método Construções Elétricas" value={nome} onChange={(e) => setNome(e.target.value)} />
        </label>
        <label className="check"><input type="checkbox" checked={ativa} onChange={(e) => setAtiva(e.target.checked)} /> Ativa</label>
        <label className="check"><input type="checkbox" checked={gerar} onChange={(e) => setGerar(e.target.checked)} /> Gerar a chave do agente agora</label>
        <p className="nota" style={{ margin: 0 }}>O identificador não muda depois. Desativar uma empresa bloqueia o acesso dos usuários e do agente dela.</p>
        <div><button className="btn primario">Salvar empresa</button></div>
      </form>
    </>
  );
}
