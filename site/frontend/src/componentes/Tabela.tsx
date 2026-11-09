// Tabela de dados: filtro rápido, ordenação por coluna, paginação e totais. Mesmo visual das telas antigas.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { F, NUMFMT, SOMAVEL, agregar, fmtCel, fmtData, fmtValor, rotuloCol, sem$ } from "../formatos";

export type Linha = unknown[];
export interface DadosTabela { colunas: string[]; linhas: Linha[] }
/** coluna do layout de um relatório: rótulo, formato, total e se fica embaixo da anterior */
export interface DefColuna { rotulo: string; formato: string; total: string; abaixo?: boolean }
/** conteúdo próprio para uma célula (ex.: etiqueta "30 dias"); null = formatação padrão */
export type Celula = (col: string, v: unknown, linha: Linha) => { conteudo: ReactNode; className?: string } | null;

interface Props {
  dados: DadosTabela | null;
  truncado?: boolean;
  ocultar?: string[];
  rotulos?: Record<string, string>;
  defs?: DefColuna[] | null;
  porPagina?: number;
  onClick?: (linha: Linha, colunas: string[]) => void;
  celula?: Celula;
  botoes?: ReactNode;
}

export function Tabela({ dados, truncado, ocultar, rotulos, defs, porPagina = 100, onClick, celula, botoes }: Props) {
  const [pagina, setPagina] = useState(0);
  const [ordem, setOrdem] = useState<{ i: number; dir: number } | null>(null);
  const [busca, setBusca] = useState("");
  useEffect(() => setPagina(0), [dados]);

  const cols = useMemo(() => {
    if (!dados) return [];
    const esconder = new Set(ocultar || []);
    return dados.colunas.map((c, i) => ({ c, i })).filter((x) => !esconder.has(x.c));
  }, [dados, ocultar]);
  const numericas = useMemo(() => {
    if (!dados) return new Set<number>();
    return new Set(defs ? cols.filter((x) => NUMFMT.has(defs[x.i].formato)).map((x) => x.i)
      : cols.filter((x) => dados.linhas.some((r) => typeof r[x.i] === "number")).map((x) => x.i));
  }, [dados, cols, defs]);
  const filtradas = useMemo(() => {
    if (!dados) return [];
    let ls = dados.linhas;
    if (busca) ls = ls.filter((r) => r.some((v) => (v !== null && String(v).toLowerCase().includes(busca)) || (typeof v === "string" && fmtData(v).includes(busca))));
    if (ordem) {
      const { i, dir } = ordem;
      ls = ls.slice().sort((a, b) => {
        const x = a[i], y = b[i];
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (typeof x === "number" ? x - (y as number) : String(x).localeCompare(String(y), "pt-BR", { numeric: true })) * dir;
      });
    }
    return ls;
  }, [dados, busca, ordem]);

  const total = filtradas.length;
  const paginas = Math.ceil(total / porPagina);
  const pag = filtradas.slice(pagina * porPagina, pagina * porPagina + porPagina);
  const ordenar = (i: number) => setOrdem((o) => (o && o.i === i ? { i, dir: -o.dir } : { i, dir: numericas.has(i) ? -1 : 1 }));
  const seta = (i: number) => (ordem && ordem.i === i ? <span className="seta">{ordem.dir > 0 ? "▲" : "▼"}</span> : null);
  const titulo = (c: string, i: number) => (defs ? defs[i].rotulo : (rotulos && rotulos[c]) || rotuloCol(c));

  let tabela: ReactNode = null;
  if (dados && defs && defs.some((d) => d.abaixo)) {
    tabela = <Empilhada cols={cols} defs={defs} numericas={numericas} todas={filtradas} pag={pag} ordenar={ordenar} seta={seta} />;
  } else if (dados) {
    const comTotais = defs && total && cols.some(({ i }) => defs[i].total !== "nenhum");
    const somar = defs ? [] : cols.filter(({ c, i }) => numericas.has(i) && SOMAVEL.test(c));
    tabela = (
      <table className="dados">
        <thead><tr>
          {cols.map(({ c, i }) => <th key={i} className={numericas.has(i) ? "num" : undefined} onClick={() => ordenar(i)}>{titulo(c, i)}{seta(i)}</th>)}
        </tr></thead>
        <tbody>
          {pag.map((r, k) => (
            <tr key={k} className={onClick ? "clicavel" : undefined} onClick={onClick ? () => onClick(r, dados.colunas) : undefined}>
              {cols.map(({ c, i }) => {
                const v = r[i];
                const prop = celula && celula(c, v, r);
                if (prop) return <td key={i} className={prop.className}>{prop.conteudo}</td>;
                const num = numericas.has(i);
                return (
                  <td key={i} className={num ? (typeof v === "number" && v < 0 ? "num neg" : "num") : undefined}
                    title={typeof v === "string" && v.length > 40 ? v : undefined}>
                    {defs ? fmtValor(defs[i].formato, v) : fmtCel(c, v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        {comTotais ? (
          <tfoot><tr>
            {cols.map(({ i }, k) => {
              const d = defs![i];
              if (d.total === "nenhum") return <td key={i}>{k === 0 ? "Total" : ""}</td>;
              const x = agregar(filtradas.map((r) => r[i]), d.total);
              return <td key={i} className={numericas.has(i) || d.total === "contagem" ? "num" : undefined}>{fmtValor(d.total === "contagem" ? "inteiro" : d.formato, x)}</td>;
            })}
          </tr></tfoot>
        ) : somar.length && total ? (
          <tfoot><tr>
            {cols.map(({ i }, k) => somar.some((s) => s.i === i)
              ? <td key={i} className="num">{sem$(F.moeda(filtradas.reduce((a, r) => a + ((r[i] as number) || 0), 0)))}</td>
              : <td key={i}>{k === 0 ? "Total" : ""}</td>)}
          </tr></tfoot>
        ) : null}
      </table>
    );
  }

  return (
    <>
      <div className="tabela-barra">
        <span className="info">{dados ? `${F.inteiro(total)} ${total === 1 ? "linha" : "linhas"}` + (truncado ? " · limite atingido, refine os filtros para ver tudo" : "") : ""}</span>
        <input className="campo busca" placeholder="Filtrar nesta tabela…" value={busca}
          onChange={(e) => { setBusca(e.target.value.toLowerCase()); setPagina(0); }} />
        {botoes}
      </div>
      <div className="tabela-wrap">{tabela}</div>
      <div className="paginacao">
        {paginas > 1 && <>
          <button className="btn pequeno" disabled={pagina === 0} onClick={() => setPagina((p) => p - 1)}>‹ Anterior</button>
          <span>Página {pagina + 1} de {paginas}</span>
          <button className="btn pequeno" disabled={pagina >= paginas - 1} onClick={() => setPagina((p) => p + 1)}>Próxima ›</button>
        </>}
      </div>
    </>
  );
}

/* colunas marcadas "abaixo" no layout aparecem embaixo da anterior, na mesma célula */
function Empilhada({ cols, defs, numericas, todas, pag, ordenar, seta }: {
  cols: { c: string; i: number }[]; defs: DefColuna[]; numericas: Set<number>; todas: Linha[]; pag: Linha[];
  ordenar: (i: number) => void; seta: (i: number) => ReactNode;
}) {
  const grupos: { c: string; i: number }[][] = [];
  cols.forEach((x) => { if (defs[x.i].abaixo && grupos.length) grupos[grupos.length - 1].push(x); else grupos.push([x]); });
  const ehNum = (gr: { i: number }[]) => gr.every((x) => numericas.has(x.i));
  const temTotal = todas.length && cols.some(({ i }) => defs[i].total !== "nenhum");
  return (
    <table className="dados empilhada">
      <thead><tr>
        {grupos.map((gr, k) => (
          <th key={k} className={ehNum(gr) ? "num" : ""} onClick={() => ordenar(gr[0].i)}>
            {gr.map((x, j) => <div key={j}>{defs[x.i].rotulo}{j === 0 && seta(gr[0].i)}</div>)}
          </th>
        ))}
      </tr></thead>
      <tbody>
        {pag.map((r, n) => (
          <tr key={n}>
            {grupos.map((gr, k) => (
              <td key={k} className={ehNum(gr) ? "num" : undefined}>
                {gr.map((x, j) => {
                  const v = r[x.i];
                  return <div key={j} className={typeof v === "number" && v < 0 ? "neg" : ""}>{fmtValor(defs[x.i].formato, v) || " "}</div>;
                })}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
      {temTotal ? (
        <tfoot><tr>
          {grupos.map((gr, k) => {
            const textos = gr.map((x) => {
              const d = defs[x.i];
              if (d.total === "nenhum") return "";
              return fmtValor(d.total === "contagem" ? "inteiro" : d.formato, agregar(todas.map((r) => r[x.i]), d.total));
            });
            if (k === 0 && !textos.join("").trim()) textos[0] = "Total";
            return (
              <td key={k} className={ehNum(gr) ? "num" : undefined}>
                {textos.map((t, j) => <div key={j} style={{ fontWeight: 600 }}>{t || " "}</div>)}
              </td>
            );
          })}
        </tr></tfoot>
      ) : null}
    </table>
  );
}
