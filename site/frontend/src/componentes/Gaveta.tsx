// Gaveta lateral de detalhe (ficha do cliente, itens do movimento...).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

interface Conteudo { titulo: string; corpo: ReactNode; larga?: boolean }
interface Gaveta {
  abrir: (c: Conteudo) => void;
  fechar: () => void;
  /** troca o título (ex.: depois de carregar o documento) */
  titulo: (t: string) => void;
}
const Ctx = createContext<Gaveta>({ abrir: () => {}, fechar: () => {}, titulo: () => {} });
export const useGaveta = () => useContext(Ctx);

export function GavetaProvider({ children }: { children: ReactNode }) {
  const [c, setC] = useState<Conteudo | null>(null);
  const [aberta, setAberta] = useState(false);
  const n = useRef(0);
  const [chave, setChave] = useState(0);
  const abrir = useCallback((x: Conteudo) => { setC(x); setAberta(true); setChave(++n.current); }, []);
  const fechar = useCallback(() => setAberta(false), []);
  const titulo = useCallback((t: string) => setC((x) => (x ? { ...x, titulo: t } : x)), []);
  useEffect(() => {
    if (!aberta) return;
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") setAberta(false); };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [aberta]);
  return (
    <Ctx.Provider value={{ abrir, fechar, titulo }}>
      {children}
      <div className={"gaveta-fundo" + (aberta ? " aberta" : "")} onClick={fechar} />
      <aside className={"gaveta" + (aberta ? " aberta" : "") + (c?.larga ? " larga" : "")} aria-label="Detalhe">
        <div className="gaveta-cab"><h2>{c?.titulo}</h2><button className="btn pequeno fechar" onClick={fechar}>Fechar ✕</button></div>
        <div className="gaveta-corpo" key={chave}>{c?.corpo}</div>
      </aside>
    </Ctx.Provider>
  );
}

/** Pares "rótulo: valor" no alto da gaveta. */
export function Campos({ pares }: { pares: [string, ReactNode][] }) {
  return (
    <div className="campos">
      {pares.map(([r, v], i) => <div key={i}><span>{r}</span><strong>{v || "—"}</strong></div>)}
    </div>
  );
}

/** Janela no meio da tela (fecha com Esc ou clicando fora). */
export function Modal({ titulo, fechar, children, classe, rodape, focar = true }: {
  titulo: string; fechar: () => void; children: ReactNode; classe?: string; rodape?: ReactNode; focar?: boolean;
}) {
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focar) btn.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); fechar(); } };
    document.addEventListener("keydown", esc, true);
    return () => document.removeEventListener("keydown", esc, true);
  }, [fechar, focar]);
  return (
    <div className="modal-fundo" onClick={(e) => { if (e.target === e.currentTarget) fechar(); }}>
      <div className={"modal" + (classe ? " " + classe : "")} role="dialog" aria-label={titulo}>
        <div className="modal-cab"><h2>{titulo}</h2><button ref={btn} className="btn pequeno" onClick={fechar}>Fechar ✕</button></div>
        <div className="modal-corpo">{children}</div>
        {rodape && <div className="modal-rodape">{rodape}</div>}
      </div>
    </div>
  );
}
