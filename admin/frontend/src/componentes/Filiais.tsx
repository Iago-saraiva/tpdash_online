import { api } from "../api";
import type { Empresa } from "../tipos";

interface Props {
  empresa: Empresa | undefined;
  agir: (fn: () => Promise<unknown>, ok?: string) => Promise<boolean>;
}

export default function Filiais({ empresa: e, agir }: Props) {
  return (
    <>
      <div className="cartao-cab">
        <h2>{e ? `Filiais · ${e.nome}` : "Filiais"}</h2>
        {e && <button className="btn pequeno" type="button"
          onClick={() => agir(() => api(`/api/empresas/${encodeURIComponent(e.id)}/filiais`, {}), "Leitura nova pedida: atualiza em instantes.")}>Ler de novo</button>}
      </div>
      {!e && <div className="nota">Escolha uma empresa na lista.</div>}
      {e && e.filiais && e.filiais.length > 0 && (
        <table className="dados">
          <thead><tr><th>Código</th><th>Filial</th></tr></thead>
          <tbody>{e.filiais.map((f) => <tr key={String(f.codigo)}><td>{f.codigo}</td><td>{f.nome}</td></tr>)}</tbody>
        </table>
      )}
      {e && e.filiais && e.filiais.length === 0 && <span className="nota">Nenhuma filial cadastrada no Puma desta empresa.</span>}
      {e && !e.filiais && <span className="nota">{e.online ? "Lendo as filiais no banco da empresa…" : "As filiais aparecem quando o agente da empresa se conectar."}</span>}
      {e && e.filiais_pedidas && e.filiais && <p className="nota">Leitura nova pedida: atualiza em instantes.</p>}
      {e && e.filiais_erro && <p className="nota">Último erro ao ler as filiais: {e.filiais_erro}</p>}
    </>
  );
}
