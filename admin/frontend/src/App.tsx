import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Aviso, Empresa, Modulos, Usuario } from "./tipos";
import Resumo from "./componentes/Resumo";
import TabelaEmpresas from "./componentes/TabelaEmpresas";
import NovaEmpresa from "./componentes/NovaEmpresa";
import Filiais from "./componentes/Filiais";
import TabelaUsuarios from "./componentes/TabelaUsuarios";
import FormUsuario from "./componentes/FormUsuario";
import Avisos from "./componentes/Avisos";

let proximoAviso = 1;

export default function App() {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [modulos, setModulos] = useState<Modulos>({});
  const [escolhida, setEscolhida] = useState("");          // empresa selecionada ("" = todas)
  const [editando, setEditando] = useState<Usuario | null | undefined>(undefined);   // undefined = formulário fechado
  const [chaveNova, setChaveNova] = useState<{ nome: string; chave: string } | null>(null);
  const [avisos, setAvisos] = useState<Aviso[]>([]);
  const [carregado, setCarregado] = useState(false);

  const avisar = useCallback((texto: string, tipo: Aviso["tipo"] = "erro") => {
    const id = proximoAviso++;
    setAvisos((a) => [...a, { id, texto, tipo }]);
    setTimeout(() => setAvisos((a) => a.filter((x) => x.id !== id)), 9000);
  }, []);

  const carregar = useCallback(async () => {
    const [e, u] = await Promise.all([
      api<{ empresas: Empresa[] }>("/api/empresas"),
      api<{ usuarios: Usuario[]; modulos: Modulos }>("/api/usuarios"),
    ]);
    setEmpresas(e.empresas);
    setUsuarios(u.usuarios);
    setModulos(u.modulos);
    setCarregado(true);
  }, []);

  useEffect(() => {
    carregar().catch((e: Error) => avisar(e.message));
    const t = setInterval(() => carregar().catch(() => {}), 15000);
    return () => clearInterval(t);
  }, [carregar, avisar]);

  // executa uma ação e recarrega; erros viram aviso
  const agir = useCallback(async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) avisar(ok, "atencao");
      await carregar();
      return true;
    } catch (e) {
      avisar((e as Error).message);
      return false;
    }
  }, [carregar, avisar]);

  const empresa = useMemo(() => empresas.find((e) => e.id === escolhida), [empresas, escolhida]);

  return (
    <>
      <p className="nota" style={{ margin: 0 }}>
        Cadastro de todas as empresas clientes do TP DASH online: chaves dos agentes, filiais e usuários de cada empresa.
        Os usuários de uma empresa só enxergam os dados dela no TP DASH.
      </p>
      {carregado && <Resumo empresas={empresas} usuarios={usuarios} />}
      <div className="grade">
        <div className="cartao c8" style={{ alignSelf: "start" }}>
          <TabelaEmpresas
            empresas={empresas} usuarios={usuarios} escolhida={escolhida} carregado={carregado}
            onEscolher={(id) => setEscolhida(id === escolhida ? "" : id)}
            agir={agir}
            onChave={(nome, chave) => setChaveNova({ nome, chave })}
          />
          {chaveNova && (
            <div className="aviso adm-chave" style={{ marginTop: 12 }}>
              <strong>Chave do agente de {chaveNova.nome} (aparece só agora, copie e guarde):</strong>
              <code>{chaveNova.chave}</code>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn pequeno" type="button" onClick={() => {
                  navigator.clipboard?.writeText(chaveNova.chave).then(() => avisar("Chave copiada.", "atencao"), () => avisar("Não deu para copiar: selecione e copie a chave."));
                }}>Copiar chave</button>
                <button className="btn pequeno" type="button" onClick={() => setChaveNova(null)}>Fechar</button>
              </div>
              <span className="nota">No TP DASH Agente do servidor do cliente: Adicionar empresa e colar esta chave.</span>
            </div>
          )}
        </div>
        <div className="cartao c4" style={{ alignSelf: "start" }}>
          <NovaEmpresa agir={agir} onCriada={(id, nome, chave) => { setEscolhida(id); if (chave) setChaveNova({ nome, chave }); }} />
        </div>
        <div className="cartao c4" style={{ alignSelf: "start" }}>
          <Filiais empresa={empresa} agir={agir} />
        </div>
        <div className="cartao c8" style={{ alignSelf: "start" }}>
          <TabelaUsuarios
            usuarios={usuarios} empresas={empresas} filtro={escolhida} onFiltro={setEscolhida}
            onNovo={() => setEditando(null)} onEditar={(u) => setEditando(u)} agir={agir}
          />
        </div>
        {editando !== undefined && (
          <div className="cartao c12">
            <FormUsuario
              key={editando ? editando.id : "novo"}
              usuario={editando} empresas={empresas} modulos={modulos} empresaPadrao={escolhida || empresas[0]?.id || ""}
              agir={agir} onFechar={() => setEditando(undefined)}
            />
          </div>
        )}
      </div>
      <Avisos avisos={avisos} />
    </>
  );
}
