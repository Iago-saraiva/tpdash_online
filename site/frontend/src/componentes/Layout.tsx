// Estrutura das telas: menu lateral, topo (empresa, período, tema...), barra inferior no celular.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { DADOS } from "../dados";
import { api, fonteDados, painelApp, semConexao } from "../api";
import { Link, PERIODOS, useNav, usePeriodo } from "../navegacao";
import { useAvisar } from "./Avisos";
import { JanelaInstalar, useInstalacao } from "./Instalar";

const ICONES: Record<string, string> = {
  inicio: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  movimentos: "M4 7h13l-3-3M20 17H7l3 3",
  movimentacoes: "M7 20V4M3 8l4-4 4 4M17 4v16M13 16l4 4 4-4",
  estoque: "M3 7l9-4 9 4-9 4-9-4zm0 0v10l9 4 9-4V7M12 11v10",
  financeiro: "M3 6h18v12H3zM3 10h18M7 15h3",
  cadastros: "M16 11a4 4 0 1 0-8 0 4 4 0 0 0 8 0zM4 21c1-4 4-6 8-6s7 2 8 6",
  frotas: "M3 6h11v10H3zM14 10h4l3 3v3h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  relatorios: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7",
  sql: "M4 6c0-2 16-2 16 0v12c0 2-16 2-16 0zM4 6c0 2 16 2 16 0M4 12c0 2 16 2 16 0",
  admin: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 3.1V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 10h.1a2 2 0 1 1 0 4z",
};
// barra inferior no celular (estilo app): até 4 módulos + Menu
const CURTOS: Record<string, string> = { inicio: "Início", movimentos: "Movim.", financeiro: "Financ.", estoque: "Estoque", relatorios: "Relatórios", cadastros: "Cadastros" };
const COM_PERIODO = ["inicio", "movimentos", "financeiro"];

function Icone({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
}

/** "Dados ao vivo" / "Dados de 14:32" conforme o cabeçalho X-Dados da última resposta */
function SeloDados() {
  const [x, setX] = useState("");
  useEffect(() => fonteDados.ouvir(setX), []);
  if (!x) return <span className="dados-de" hidden />;
  const [tipo, quando] = x.split(":");
  if (tipo === "agente") return <span className="dados-de" title="Lidos agora do servidor da empresa">Dados ao vivo</span>;
  const t = new Date(Number(quando) * 1000);
  const hoje = new Date().toDateString() === t.toDateString();
  const hora = t.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return (
    <span className="dados-de" title={"Cópia do banco guardada no site, atualizada pelo agente" + (tipo === "misto" ? " (parte lida agora do servidor da empresa)" : "")}>
      Dados de {hoje ? hora : t.toLocaleDateString("pt-BR") + " " + hora}
    </span>
  );
}

function SemConexao() {
  const [on, setOn] = useState(false);
  useEffect(() => semConexao.ouvir(setOn), []);
  return on ? <div className="sem-conexao" role="status">Sem resposta do servidor. Tentando de novo...</div> : null;
}

function TrocaEmpresa() {
  const avisar = useAvisar();
  const [valor, setValor] = useState(DADOS.banco_atual || "");
  const [ocupado, setOcupado] = useState(false);
  const bancos = DADOS.bancos || [];
  if (bancos.length < 2) return null;
  const trocar = async (id: string) => {
    const antes = valor;
    setValor(id); setOcupado(true);
    try {
      await api("/api/banco", { id });
      location.reload();          // recarrega a tela com os dados da outra empresa
    } catch (e) {
      setValor(antes); setOcupado(false);
      avisar((e as Error).message);
    }
  };
  return (
    <label className="troca-empresa" title="Empresa (banco) em uso"><span className="rot">Empresa</span>
      <select aria-label="Empresa em uso" value={valor} disabled={ocupado} onChange={(e) => trocar(e.target.value)}>
        {bancos.map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
      </select>
    </label>
  );
}

function alternarTema() {
  const escuro = getComputedStyle(document.documentElement).colorScheme === "dark";
  const novo = escuro ? "claro" : "escuro";
  document.documentElement.dataset.tema = novo;
  try { localStorage.setItem("tema", novo); } catch { /* */ }
  window.dispatchEvent(new Event("resize"));
}

export function Layout({ titulo, avisos, aoRecarregar, children }: { titulo: string; avisos: ReactNode; aoRecarregar: () => void; children: ReactNode }) {
  const { tela } = useNav();
  const { periodo, setPeriodo } = usePeriodo();
  const [menuAberto, setMenuAberto] = useState(false);
  const [instalar, setInstalar] = useState(false);
  const inst = useInstalacao();
  const lateral = useRef<HTMLElement>(null);
  const u = DADOS.usuario!;
  const paginas = DADOS.paginas || [];

  useEffect(() => { document.title = `${titulo} · TP DASH`; }, [titulo]);
  // no celular: toque fora do menu ou em um item fecha o menu
  useEffect(() => {
    if (!menuAberto) return;
    const f = (e: Event) => {
      const alvo = e.target as HTMLElement;
      if (!lateral.current?.contains(alvo) || alvo.closest("a")) setMenuAberto(false);
    };
    document.addEventListener("click", f);
    return () => document.removeEventListener("click", f);
  }, [menuAberto]);

  const abrirMenu = (e: React.MouseEvent) => { e.stopPropagation(); setMenuAberto((v) => !v); };
  const inferior = ["inicio", "movimentos", "financeiro", "estoque", "relatorios", "cadastros"]
    .map((k) => paginas.find((p) => p.chave === k)).filter(Boolean).slice(0, 4);

  return (
    <>
      <div className="app">
        <aside className={"lateral" + (menuAberto ? " aberta" : "")} ref={lateral}>
          <div className="marca">
            <img src="/static/logo-tpdash-preto.svg" width={32} height={32} alt="TP DASH" className="logo-tpdash" />
            <div>TP DASH<small>{DADOS.empresa}</small></div>
          </div>
          <nav className="nav">
            {paginas.map((p) => (
              <Link key={p.chave} href={p.url} className={tela === p.chave ? "ativo" : ""}><Icone d={ICONES[p.chave]} />{p.titulo}</Link>
            ))}
            {DADOS.admin_link && <Link href="/admin" className={tela === "admin" ? "ativo" : ""}><Icone d={ICONES.admin} />Administração</Link>}
          </nav>
          <div className="rodape">
            {u.nome}<br /><a href="/trocar-senha">Trocar senha</a> · <a href="/sair">Sair</a>
            {painelApp?.configurar && <><br /><a href="#" onClick={(e) => { e.preventDefault(); painelApp?.configurar?.(); }}>Trocar servidor</a></>}
          </div>
        </aside>
        <main className="principal">
          <header className="topo">
            <button className="btn menu-btn" aria-label="Menu" onClick={abrirMenu}>☰</button>
            <h1>{titulo}</h1>
            {DADOS.modo === "demo" && <span className="selo-demo">Modo demonstração</span>}
            <TrocaEmpresa />
            {COM_PERIODO.includes(tela) && (
              <label className="periodo-topo" title="Período usado na Início, em Movimentos e no Financeiro"><span className="rot">Período</span>
                <select aria-label="Período" value={periodo} onChange={(e) => setPeriodo(e.target.value)}>
                  {Object.entries(PERIODOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            )}
            <SeloDados />
            <span className="usuario">{u.nome}</span>
            <button className="btn pequeno" id="recarregar" title="Atualizar a tela" aria-label="Atualizar a tela" onClick={aoRecarregar}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></svg>
            </button>
            <button id="btn-instalar" className={"btn pequeno" + (inst.disponivel ? " primario" : "")} hidden={inst.oculto}
              title="Instalar o TP DASH como aplicativo neste computador" onClick={() => setInstalar(true)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14" /></svg>
              <span className="rot-instalar">Instalar app</span>
            </button>
            <button className="btn pequeno" title="Alternar tema claro/escuro" aria-label="Alternar tema claro/escuro" onClick={alternarTema}>
              <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" /></svg>
            </button>
          </header>
          <section className="conteudo">
            {avisos}
            {children}
          </section>
        </main>
      </div>
      <nav className="nav-inferior" aria-label="Navegação">
        {inferior.map((p) => (
          <Link key={p!.chave} href={p!.url} className={tela === p!.chave ? "ativo" : ""}><Icone d={ICONES[p!.chave]} /><span>{CURTOS[p!.chave]}</span></Link>
        ))}
        <button type="button" onClick={abrirMenu}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 7h16M4 12h16M4 17h16" /></svg><span>Menu</span>
        </button>
      </nav>
      {instalar && <JanelaInstalar fechar={() => setInstalar(false)} />}
      <SemConexao />
    </>
  );
}
