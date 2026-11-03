// Conversa com a API do ADMIN (mesmas rotas da versão anterior). O token de segurança e o início do
// endereço (quando o ADMIN roda num caminho, ex.: /adm-xxxx) vêm do HTML gerado pelo Flask.
const raiz = document.getElementById("raiz") as HTMLElement;
export const BASE = raiz.dataset.base || "";
const TOKEN = raiz.dataset.token || "";

export async function api<T = unknown>(url: string, json?: unknown): Promise<T> {
  const op: RequestInit = { headers: { "X-Admin": TOKEN } };
  if (json !== undefined) {
    op.method = "POST";
    op.headers = { "X-Admin": TOKEN, "Content-Type": "application/json" };
    op.body = JSON.stringify(json);
  }
  const r = await fetch(BASE + url, op);
  let d: unknown = null;
  try { d = await r.json(); } catch { /* sem JSON */ }
  if (r.status === 401) { location.href = BASE + "/login"; throw new Error("Sessão expirada"); }
  if (!r.ok) throw new Error((d as { erro?: string } | null)?.erro || `Erro ${r.status}`);
  return d as T;
}
