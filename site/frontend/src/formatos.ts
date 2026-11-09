// Formatação de números e datas (pt-BR), igual à das telas antigas.
const nfInt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf3 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

export const F = {
  moeda: (v: number | null | undefined) => "R$ " + nf2.format(v || 0),
  inteiro: (v: number | null | undefined) => nfInt.format(v || 0),
  numero: (v: number | null | undefined) => nf3.format(v || 0),
  dois: (v: number) => nf2.format(v),
  compacto(v: number | null | undefined, moeda?: boolean) {
    const n = v || 0;
    const a = Math.abs(n);
    let s;
    if (a >= 1e9) s = (n / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " bi";
    else if (a >= 1e6) s = (n / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mi";
    else if (a >= 1e3) s = (n / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mil";
    else s = nfInt.format(n);
    return (moeda ? "R$ " : "") + s;
  },
  /** "2026-03" vira "mar/26"; outros rótulos ficam como estão */
  mes(r: string) {
    if (/^\d{4}-\d{2}$/.test(r)) {
      const m = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"][+r.slice(5) - 1];
      return m + "/" + r.slice(2, 4);
    }
    return r;
  },
};

/** "2026-03-05" vira "05/03/2026" (com a hora, se tiver e não for 00:00) */
export function fmtData(v: unknown): string {
  if (typeof v !== "string" || v.length < 10 || v[4] !== "-") return v === null || v === undefined ? "" : String(v);
  const d = `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}`;
  return v.length > 10 && v.slice(11, 16) !== "00:00" ? d + " " + v.slice(11, 16) : d;
}

/** data local no formato 2026-03-05 */
export function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** localStorage sem erro (navegador sem armazenamento ou modo privado) */
export const guardado = {
  ler(k: string): string | null {
    try { return localStorage.getItem(k); } catch { return null; }
  },
  gravar(k: string, v: string) {
    try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ }
  },
};

/* ------------------------------------------------------------ células das tabelas */
export const MOEDA = /^(VALOR|TOTAL|PRECO|CUSTO|LIMITE|VLR_UNIT|VALOR_.*|CUSTO_.*|.*_VALOR)$/i;
export const SOMAVEL = /^(VALOR|TOTAL|VALOR_ESTOQUE|VALOR_BAIXADO|VALOR_DOC|.*_VALOR)$/i;
const DATA = /^(EMISSAO|VENCIMENTO|BAIXA|CADASTRO|ULTIMA_VENDA|DATA.*|DT.*)$/i;
export const sem$ = (s: string) => s.replace("R$ ", "");

/** valor de uma célula conforme o nome da coluna (moeda, data, número) */
export function fmtCel(col: string, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return MOEDA.test(col) ? sem$(F.moeda(v)) : F.numero(v);
  if (DATA.test(col) || /^\d{4}-\d{2}-\d{2}/.test(String(v))) return fmtData(v);
  return String(v);
}

export const NUMFMT = new Set(["moeda", "inteiro", "numero", "percentual"]);
/** valor conforme o formato escolhido no layout do relatório */
export function fmtValor(fmt: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (fmt === "moeda" && typeof v === "number") return sem$(F.moeda(v));
  if (fmt === "inteiro" && typeof v === "number") return F.inteiro(v);
  if (fmt === "numero" && typeof v === "number") return F.numero(v);
  if (fmt === "percentual" && typeof v === "number") return F.numero(v) + "%";
  if ((fmt === "data" || fmt === "datahora") && typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) {
    const d = `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}`;
    return fmt === "datahora" && v.length >= 16 ? d + " " + v.slice(11, 16) : d;
  }
  if (typeof v === "number") return F.numero(v);
  return String(v);
}

export function agregar(vals: unknown[], ag: string): unknown {
  const vs = vals.filter((v) => v !== null && v !== undefined);
  if (ag === "contagem") return vs.length;
  const ns = vs.filter((v): v is number => typeof v === "number");
  if (ag === "soma") return ns.length ? ns.reduce((a, b) => a + b, 0) : null;
  if (ag === "media") return ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : null;
  if (ag === "minimo" || ag === "maximo") {
    if (!vs.length) return null;
    const ord = vs.slice().sort((a, b) => (typeof a === "number" ? a - (b as number) : String(a).localeCompare(String(b))));
    return ag === "minimo" ? ord[0] : ord[ord.length - 1];
  }
  return null;
}

const ROTULOS: Record<string, string> = { CPF_CNPJ: "CPF/CNPJ", NCM: "NCM", CEST: "CEST", CODCFO: "Cód. cliente", CODTMV: "Tipo mov.", CODLOC: "Local", UND: "Und",
  VLR_UNIT: "Vlr unit.", SIT_DENTRO: "Sit. dentro UF", SIT_FORA: "Sit. fora UF", DESC_DENTRO: "Descr. dentro", DESC_FORA: "Descr. fora",
  CST_PISCOFINS: "CST PIS/COFINS", DIAS_ATRASO: "Dias atraso", VALOR_BAIXADO: "Valor baixado", VALOR_ESTOQUE: "Valor estoque",
  CUSTO_MEDIO: "Custo médio", modulos: "Módulos", usuario: "Usuário", acao: "Ação", ultimo_acesso: "Último acesso", CODIGO: "Código", CENTRO_CUSTO: "Centro de custo", COD_FABRICANTE: "Cód. fabricante", CODPRD_INT: "Cód. interno", SITUACAO: "Situação", DOCUMENTO: "Documento", NOME_LOCAL: "Nome do local", TIPO_DOC: "Tipo doc.", ULTIMA_VENDA: "Última venda", EMISSAO: "Emissão", PRECO: "Preço", ORIGEM: "Origem", LANCAMENTOS: "Lançamentos", PAGREC: "Pagar/Receber" };
/** "VALOR_ESTOQUE" vira "Valor estoque" */
export function rotuloCol(c: string) {
  if (ROTULOS[c]) return ROTULOS[c];
  const t = c.replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}
