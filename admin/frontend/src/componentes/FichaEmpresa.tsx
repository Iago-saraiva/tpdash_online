import { api } from "../api";
import type { Empresa, Filial } from "../tipos";

interface Props {
  empresa: Empresa;
  agir: (fn: () => Promise<unknown>, ok?: string) => Promise<boolean>;
}

const cnpj = (v?: string) => {
  const d = (v || "").replace(/\D/g, "");
  if (d.length === 14) return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
  if (d.length === 11) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
  return v || "";
};
const cep = (v?: string) => { const d = (v || "").replace(/\D/g, ""); return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : v || ""; };
const endereco = (f: Filial) =>
  [[f.rua, f.numero].filter(Boolean).join(", "), f.complemento, f.bairro].filter(Boolean).join(" · ");
const cidade = (f: Filial) => [f.cidade, f.uf].filter(Boolean).join("/");
const inativa = (f: Filial) => ["1", "S", "T"].includes(String(f.inativo || "").trim().toUpperCase());
const dia = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const modo = (m: string) => ({ firebird: "Firebird", demo: "Demonstração" } as Record<string, string>)[m] || m || "—";

function Linha({ rotulo, valor }: { rotulo: string; valor: React.ReactNode }) {
  return <div className="ficha-linha"><span>{rotulo}</span><strong>{valor || "—"}</strong></div>;
}

export default function FichaEmpresa({ empresa: e, agir }: Props) {
  const ag = e.agente;
  const sinc = ag?.sincronizacao;
  const hoje = e.consultas?.hoje;
  const media = hoje && hoje.n ? (hoje.segundos / hoje.n).toFixed(1) : null;
  return (
    <>
      <div className="cartao-cab">
        <h2>Ficha · {e.nome}</h2>
        <button className="btn pequeno" type="button"
          onClick={() => agir(() => api(`/api/empresas/${encodeURIComponent(e.id)}/filiais`, {}), "Leitura nova pedida: atualiza em instantes.")}>
          Ler filiais de novo
        </button>
      </div>

      <div className="ficha-grade">
        <section>
          <h3>Agente</h3>
          <Linha rotulo="Situação" valor={<span className={"tag " + (e.online ? "entrada" : "")}>{e.online ? "Conectado" : e.tem_chave ? "Desconectado" : "Sem chave"}</span>} />
          <Linha rotulo="Versão" valor={e.versao} />
          <Linha rotulo="Último contato" valor={e.visto} />
          <Linha rotulo="Conectou em" valor={ag?.conectado} />
          <Linha rotulo="Computador" valor={ag?.maquina ? `${ag.maquina}${ag.sistema ? ` (${ag.sistema})` : ""}` : null} />
          <Linha rotulo="IP de saída" valor={e.ip} />
          <Linha rotulo="Banco" valor={e.banco ? `${modo(ag?.modo)} · ${e.banco}` : null} />
          <Linha rotulo="Código da empresa no Puma" valor={ag?.codempresa != null ? String(ag.codempresa) : null} />
        </section>

        <section>
          <h3>Consultas ao banco</h3>
          <Linha rotulo="Hoje" valor={hoje ? `${hoje.n} consulta${hoje.n === 1 ? "" : "s"}${hoje.erros ? ` · ${hoje.erros} com erro` : ""}` : "nenhuma"} />
          <Linha rotulo="Tempo médio hoje" valor={media ? `${media} s` : null} />
          <Linha rotulo="Últimos 7 dias" valor={`${e.consultas?.semana || 0} consultas`} />
          {(e.consultas?.dias?.length ?? 0) > 0 && (
            <div className="ficha-dias">
              {e.consultas.dias.slice().reverse().map((d) => (
                <div key={d.dia} title={`${d.n} consultas, ${d.erros} com erro`}>
                  <span className="barra" style={{ height: `${Math.max(4, (d.n / Math.max(...e.consultas.dias.map((x) => x.n), 1)) * 48)}px` }} />
                  <small>{dia(d.dia)}</small><small>{d.n}</small>
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h3>Sincronização</h3>
          {!sinc && <p className="nota">Ainda não ativada nesta versão do agente. Quando estiver, aparecem aqui o intervalo programado, a última e a próxima rodada e o que mudou.</p>}
          {sinc && <>
            <Linha rotulo="Intervalo programado" valor={sinc.intervalo_min ? `a cada ${sinc.intervalo_min} min` : null} />
            <Linha rotulo="Carga inicial" valor={sinc.carga_inicial} />
            <Linha rotulo="Última rodada" valor={sinc.ultima ? `${sinc.ultima}${sinc.duracao_s != null ? ` · ${sinc.duracao_s} s` : ""}` : null} />
            <Linha rotulo="Mudanças na última" valor={sinc.ultima ? `${sinc.inseridas || 0} novas · ${sinc.alteradas || 0} alteradas · ${sinc.apagadas || 0} apagadas` : null} />
            <Linha rotulo="Próxima rodada" valor={sinc.proxima} />
            {sinc.erro && <p className="nota">Último erro: {sinc.erro}</p>}
          </>}
        </section>
      </div>

      <h3 style={{ marginTop: 18 }}>Filiais {e.filiais ? `(${e.filiais.length})` : ""}</h3>
      {e.filiais && e.filiais.length > 0 && (
        <div className="tabela-rolar">
          <table className="dados">
            <thead><tr><th>Cód.</th><th>Filial</th><th>CNPJ</th><th>Inscrição estadual</th><th>Endereço</th><th>Cidade/UF</th><th>Contato</th><th>Situação</th></tr></thead>
            <tbody>{e.filiais.map((f) => (
              <tr key={String(f.codigo)}>
                <td>{f.codigo}</td>
                <td><strong>{f.nome}</strong>{f.razao && f.razao !== f.nome && <div className="nota">{f.razao}</div>}</td>
                <td style={{ whiteSpace: "nowrap" }}>{cnpj(f.cnpj)}</td>
                <td>{f.ie}{f.im && <div className="nota">IM {f.im}</div>}</td>
                <td>{endereco(f)}{f.cep && <div className="nota">CEP {cep(f.cep)}</div>}</td>
                <td style={{ whiteSpace: "nowrap" }}>{cidade(f)}</td>
                <td>{f.telefone}{f.email && <div className="nota">{f.email}</div>}{f.contato && <div className="nota">{f.contato}</div>}</td>
                <td>{inativa(f) ? "Inativa" : "Ativa"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {e.filiais && e.filiais.length === 0 && <span className="nota">Nenhuma filial cadastrada no Puma desta empresa.</span>}
      {!e.filiais && <span className="nota">{e.online ? "Lendo as filiais no banco da empresa…" : "As filiais aparecem quando o agente da empresa se conectar."}</span>}
      {e.filiais_lidas && <p className="nota">Filiais lidas em {e.filiais_lidas}{e.filiais_pedidas ? " · leitura nova pedida" : ""}.</p>}
      {e.filiais_erro && <p className="nota">Último erro ao ler as filiais: {e.filiais_erro}</p>}
    </>
  );
}
