// Conversa com o servidor (mesmas rotas /api/... das telas antigas).
import { DADOS } from "./dados";

type Ouvinte<T> = (v: T) => void;
function canal<T>() {
  const ouvintes = new Set<Ouvinte<T>>();
  return {
    avisar: (v: T) => ouvintes.forEach((f) => f(v)),
    ouvir(f: Ouvinte<T>) { ouvintes.add(f); return () => { ouvintes.delete(f); }; },
  };
}

/** "Sem resposta do servidor. Tentando de novo..." */
export const semConexao = canal<boolean>();
/** cabeçalho X-Dados da última resposta: "agente", "copia:<epoch>" ou "misto:<epoch>" */
export const fonteDados = canal<string>();

/* Se o servidor estiver reiniciando ou a rede oscilar (conexão recusada / sem resposta),
   tenta de novo algumas vezes antes de mostrar erro. */
const ESPERAS = [800, 2000, 4000, 7000, 10000];
async function buscar(url: string, op: RequestInit): Promise<Response> {
  for (let i = 0; ; i++) {
    try {
      const resp = await fetch(url, op);
      if ((resp.status === 502 || resp.status === 503 || resp.status === 504) && i < 2) throw new TypeError("indisponível");
      if (i) semConexao.avisar(false);
      return resp;
    } catch (e) {
      if (!(e instanceof TypeError) || i >= ESPERAS.length) {
        semConexao.avisar(false);
        if (e instanceof TypeError) {
          throw new Error("Não foi possível falar com o servidor (conexão recusada ou sem rede). " +
            "Ele pode estar reiniciando: aguarde alguns segundos e tente de novo. Se continuar, confira se o servidor está ligado.");
        }
        throw e;
      }
      semConexao.avisar(true);
      await new Promise((ok) => setTimeout(ok, ESPERAS[i]));
    }
  }
}

function opcoes(json?: unknown, metodo?: string): RequestInit {
  const headers: Record<string, string> = { "X-Painel": DADOS.csrf };
  const op: RequestInit = { headers };
  if (json !== undefined) {
    op.method = metodo || "POST";
    headers["Content-Type"] = "application/json";
    op.body = JSON.stringify(json);
  } else if (metodo) {
    op.method = metodo;
  }
  return op;
}

export async function api<T = unknown>(url: string, json?: unknown, metodo?: string): Promise<T> {
  const r = await buscar(url, opcoes(json, metodo));
  const x = r.headers.get("X-Dados");
  if (x) fonteDados.avisar(x);
  let d: unknown = null;
  try { d = await r.json(); } catch { /* sem JSON */ }
  if (r.status === 401) {
    location.href = "/login?proximo=" + encodeURIComponent(location.pathname + location.search);
    throw new Error("Sessão expirada");
  }
  if (!r.ok) throw new Error((d as { erro?: string } | null)?.erro || `Erro ${r.status}`);
  return d as T;
}

interface PainelApp { salvar?: (b64: string, tipo: string, nome: string) => void; configurar?: () => void }
export const painelApp = (window as unknown as { PainelApp?: PainelApp }).PainelApp;

/** Baixa um arquivo (Excel, PDF, zip). PDF abre em outra aba. */
export async function baixar(url: string, json?: unknown) {
  const r = await buscar(url, opcoes(json));
  if (!r.ok) {
    let msg = `Erro ${r.status}`;
    try { msg = (await r.json()).erro || msg; } catch { /* */ }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const nome = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "arquivo";
  if (painelApp && painelApp.salvar) {
    // dentro do app Android: o arquivo é salvo em Downloads e aberto pelo próprio celular
    const salvar = painelApp.salvar;
    const leitor = new FileReader();
    leitor.onload = () => salvar(String(leitor.result).split(",")[1], blob.type, nome);
    leitor.readAsDataURL(blob);
    return;
  }
  const href = URL.createObjectURL(blob);
  if (blob.type === "application/pdf") {
    window.open(href, "_blank");
  } else {
    const a = document.createElement("a");
    a.href = href; a.download = nome; document.body.appendChild(a); a.click(); a.remove();
  }
  setTimeout(() => URL.revokeObjectURL(href), 60000);
}

/** /api/opcoes (filiais, tipos de movimento...) uma vez só por página */
let cacheOpcoes: Promise<Opcoes> | null = null;
export interface Codigo { cod: string; nome?: string }
export interface Opcoes {
  filiais?: Codigo[]; tipos?: Codigo[]; vendedores?: Codigo[]; locais?: Codigo[]; grupos?: Codigo[];
  tipos_doc?: Codigo[]; ccustos?: Codigo[]; departamentos?: Codigo[]; [k: string]: unknown;
}
export function opcoesGerais(): Promise<Opcoes> {
  if (!cacheOpcoes) cacheOpcoes = api<Opcoes>("/api/opcoes").catch((e) => { cacheOpcoes = null; throw e; });
  return cacheOpcoes;
}
