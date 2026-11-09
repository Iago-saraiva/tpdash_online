// Avisos no alto da tela (erro, atenção, ok). Somem sozinhos depois de 9 segundos.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type Tipo = "erro" | "atencao" | "ok" | "info";
interface Aviso { id: number; msg: string; tipo: Tipo }
const Ctx = createContext<(msg: string, tipo?: Tipo) => void>(() => {});
export const useAvisar = () => useContext(Ctx);

export function AvisosProvider({ children }: { children: (lista: ReactNode) => ReactNode }) {
  const [lista, setLista] = useState<Aviso[]>([]);
  const n = useRef(0);
  const avisar = useCallback((msg: string, tipo: Tipo = "erro") => {
    const id = ++n.current;
    setLista((l) => [{ id, msg, tipo }, ...l]);
    setTimeout(() => setLista((l) => l.filter((a) => a.id !== id)), 9000);
  }, []);
  const avisos = lista.map((a) => <div key={a.id} className={"aviso " + a.tipo}>{a.msg}</div>);
  return <Ctx.Provider value={avisar}>{children(avisos)}</Ctx.Provider>;
}
