// TP DASH (site) em React. O Flask entrega uma página com os dados iniciais e este código monta a tela.
import { StrictMode, useState, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { DADOS } from "./dados";
import { NavProvider, PeriodoProvider, useNav } from "./navegacao";
import { AvisosProvider } from "./componentes/Avisos";
import { GavetaProvider } from "./componentes/Gaveta";
import { DicaGrafico } from "./componentes/Graficos";
import { Layout } from "./componentes/Layout";
import { Login, TrocarSenha } from "./telas/Login";
import Inicio from "./telas/Inicio";
import Movimentos from "./telas/Movimentos";
import Movimentacoes from "./telas/Movimentacoes";
import Financeiro from "./telas/Financeiro";
import Estoque from "./telas/Estoque";
import Cadastros from "./telas/Cadastros";
import Frotas from "./telas/Frotas";
import Relatorios from "./telas/Relatorios";
import Sql from "./telas/Sql";
import Admin from "./telas/Admin";
import { Chat } from "./componentes/Chat";

// telas já em React (as demais continuam nas páginas antigas até serem migradas)
const TELAS: Record<string, ComponentType> = {
  inicio: Inicio, movimentos: Movimentos, movimentacoes: Movimentacoes, financeiro: Financeiro, estoque: Estoque,
  cadastros: Cadastros, frotas: Frotas, relatorios: Relatorios, sql: Sql, admin: Admin,
};

function Painel() {
  const { tela, busca } = useNav();
  const [versao, setVersao] = useState(0);        // "Atualizar a tela": monta a tela de novo
  const Tela = TELAS[tela];
  const titulo = tela === "admin" ? "Administração" : (DADOS.paginas || []).find((p) => p.chave === tela)?.titulo || DADOS.titulo;
  return (
    <AvisosProvider>
      {(avisos) => (
        <GavetaProvider>
          <Layout titulo={titulo} avisos={avisos} aoRecarregar={() => setVersao((v) => v + 1)}>
            {Tela ? <Tela key={tela + versao + busca} /> : null}
          </Layout>
          <DicaGrafico />
          {(DADOS.usuario?.modulos || []).includes("chat") && <Chat />}
        </GavetaProvider>
      )}
    </AvisosProvider>
  );
}

function App() {
  if (DADOS.tela === "login") return <Login />;
  if (DADOS.tela === "trocar_senha") return <TrocarSenha />;
  return (
    <NavProvider>
      <PeriodoProvider>
        <Painel />
      </PeriodoProvider>
    </NavProvider>
  );
}

createRoot(document.getElementById("raiz") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
