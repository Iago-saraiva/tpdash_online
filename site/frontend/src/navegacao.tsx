// Troca de tela sem recarregar a página (telas já em React) e período global do topo.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode, type MouseEvent, type AnchorHTMLAttributes } from "react";
import { DADOS } from "./dados";
import { guardado, iso } from "./formatos";

/* ------------------------------------------------------------ tela atual */
interface Nav { tela: string; busca: string; navegar: (url: string) => void }
const NavCtx = createContext<Nav>({ tela: DADOS.tela, busca: "", navegar: (u) => { location.href = u; } });
export const useNav = () => useContext(NavCtx);

/** Tela de um endereço ("/movimentos?x=1" -> "movimentos"); null se não for tela do menu. */
function telaDaUrl(url: string): string | null {
  const caminho = new URL(url, location.href).pathname;
  if (caminho === "/admin" && DADOS.admin_link) return "admin";
  const p = (DADOS.paginas || []).find((x) => x.url === caminho);
  return p ? p.chave : null;
}

export function NavProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState({ tela: DADOS.tela, busca: location.search });
  const navegar = useCallback((url: string) => {
    const t = telaDaUrl(url);
    if (!t || !(DADOS.react || []).includes(t)) {
      location.href = url;            // tela ainda na versão antiga: abre a página normal
      return;
    }
    history.pushState(null, "", url);
    setEstado({ tela: t, busca: new URL(url, location.href).search });
    window.scrollTo(0, 0);
  }, []);
  useEffect(() => {
    const voltar = () => {
      const t = telaDaUrl(location.href);
      if (t && (DADOS.react || []).includes(t)) setEstado({ tela: t, busca: location.search });
      else location.reload();
    };
    window.addEventListener("popstate", voltar);
    return () => window.removeEventListener("popstate", voltar);
  }, []);
  return <NavCtx.Provider value={{ ...estado, navegar }}>{children}</NavCtx.Provider>;
}

/** <a> que troca de tela sem recarregar quando a tela de destino já está em React. */
export function Link({ href, onClick, ...resto }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  const { navegar } = useNav();
  const clicar = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navegar(href);
  };
  return <a href={href} onClick={clicar} {...resto} />;
}

/* ------------------------------------------------------------ período global (Início, Movimentos, Financeiro) */
export const PERIODOS: Record<string, string> = {
  mes: "Este mês", mes_passado: "Mês passado", d30: "Últimos 30 dias", d90: "Últimos 90 dias", ano: "Este ano", m12: "Últimos 12 meses",
};

export function datasPeriodo(k: string): [string, string] {
  const h = new Date(), y = h.getFullYear(), m = h.getMonth();
  const r: Record<string, [Date, Date]> = {
    mes: [new Date(y, m, 1), new Date(y, m + 1, 0)],
    mes_passado: [new Date(y, m - 1, 1), new Date(y, m, 0)],
    d30: [new Date(y, m, h.getDate() - 29), h],
    d90: [new Date(y, m, h.getDate() - 89), h],
    ano: [new Date(y, 0, 1), new Date(y, 11, 31)],
    m12: [new Date(y, m - 11, 1), new Date(y, m + 1, 0)],
  };
  const [a, b] = r[k] || r.mes;
  return [iso(a), iso(b)];
}

interface Periodo { periodo: string; setPeriodo: (k: string) => void }
const PeriodoCtx = createContext<Periodo>({ periodo: "mes", setPeriodo: () => {} });
export const usePeriodo = () => useContext(PeriodoCtx);

export function PeriodoProvider({ children }: { children: ReactNode }) {
  const [periodo, setP] = useState(() => {
    const k = guardado.ler("periodo");
    return k && PERIODOS[k] ? k : "mes";
  });
  const setPeriodo = useCallback((k: string) => { guardado.gravar("periodo", k); setP(k); }, []);
  return <PeriodoCtx.Provider value={{ periodo, setPeriodo }}>{children}</PeriodoCtx.Provider>;
}
