// Gráficos SVG sem bibliotecas externas (funciona sem internet): barras, colunas, linhas/área e rosca,
// com dica ao passar o mouse, legenda e clique para filtrar. Mesmo desenho e classes CSS das telas antigas.
import { useLayoutEffect, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { F } from "../formatos";

type Fmt = (v: number) => string;
const cor = (i: number) => `var(--serie-${(i % 8) + 1})`;

/* ------------------------------------------------------------ dica (tooltip) única */
interface LinhaDica { valor: string; nome?: string; cor?: string }
interface Dica { x: number; y: number; titulo: string; linhas: LinhaDica[] }
let dicaAtual: Dica | null = null;
const ouvintesDica = new Set<() => void>();
function mostrarDica(ev: { clientX: number; clientY: number }, titulo: string, linhas: LinhaDica[]) {
  dicaAtual = { x: ev.clientX, y: ev.clientY, titulo, linhas };
  ouvintesDica.forEach((f) => f());
}
function esconderDica() {
  if (!dicaAtual) return;
  dicaAtual = null;
  ouvintesDica.forEach((f) => f());
}
const assinarDica = (f: () => void) => { ouvintesDica.add(f); return () => { ouvintesDica.delete(f); }; };

/** Colocar uma vez na página (o App já coloca). */
export function DicaGrafico() {
  const d = useSyncExternalStore(assinarDica, () => dicaAtual);
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const t = ref.current;
    if (!t || !d) return;
    const w = t.offsetWidth, h = t.offsetHeight;
    let x = d.x + 14, y = d.y + 14;
    if (x + w > window.innerWidth - 8) x = d.x - w - 14;
    if (y + h > window.innerHeight - 8) y = d.y - h - 14;
    t.style.left = x + "px";
    t.style.top = y + "px";
  }, [d]);
  return (
    <div ref={ref} className="gtip" role="status" style={{ display: d ? "block" : "none" }}>
      {d && <>
        <div className="gtip-tit">{d.titulo}</div>
        {d.linhas.map((l, i) => (
          <div className="gtip-lin" key={i}>
            {l.cor && <span className="gtip-key" style={{ background: l.cor }} />}
            <strong>{l.valor}</strong>
            {l.nome && <span className="gtip-nome">{l.nome}</span>}
          </div>
        ))}
      </>}
    </div>
  );
}

/* ------------------------------------------------------------ caixa que mede a própria largura */
function Caixa({ className, children }: { className?: string; children: (largura: number) => ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver((ents) => {
      const nova = ents[0].contentRect.width;
      setW((antes) => (Math.abs(antes - nova) > 4 ? nova : antes));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return <div ref={ref} className={"gcont" + (className ? " " + className : "")}>{w > 0 && children(Math.max(w, 240))}</div>;
}

function Vazio() {
  return <div className="gvazio">Sem dados para os filtros escolhidos</div>;
}

function Legenda({ series, tipo }: { series: { nome: string }[]; tipo: "linha" | "barra" }) {
  if (series.length < 2) return null;
  return (
    <div className="glegenda">
      {series.map((s, i) => (
        <span key={i}><span className={tipo === "linha" ? "glk-linha" : "glk-barra"} style={{ background: cor(i) }} />{s.nome}</span>
      ))}
    </div>
  );
}

/* escala "bonita" para o eixo */
function escala(max: number, min: number) {
  min = Math.min(0, min || 0);
  if (max <= min) max = min + 1;
  const bruto = (max - min) / 4;
  const pot = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 5, 10].map((m) => m * pot).find((p) => p >= bruto) || bruto;
  const ini = Math.floor(min / passo) * passo;
  const fim = Math.ceil(max / passo) * passo;
  const ticks: number[] = [];
  for (let v = ini; v <= fim + passo / 2; v += passo) ticks.push(+v.toFixed(10));
  return { ini, fim, ticks };
}

/** Texto que corta com "…" se não couber na largura. */
function RotuloCortado({ texto, largura, ...attrs }: { texto: string; largura: number } & React.SVGProps<SVGTextElement>) {
  const ref = useRef<SVGTextElement>(null);
  const [mostrar, setMostrar] = useState(texto);
  useLayoutEffect(() => {
    const t = ref.current;
    if (!t) return;
    let rot = texto;
    t.textContent = rot;
    try {
      while (rot.length > 4 && t.getComputedTextLength() > largura) {
        rot = rot.slice(0, -2);
        t.textContent = rot.trimEnd() + "…";
      }
    } catch { /* medição indisponível */ }
    setMostrar(t.textContent || texto);
  }, [texto, largura]);
  return <text ref={ref} {...attrs}>{mostrar}</text>;
}

/* ------------------------------------------------------------ barras horizontais */
export interface ItemBarra { rotulo: string; valor: number | null; cor?: string }
interface OpBarras {
  dados: ItemBarra[];
  formato?: Fmt; cor?: string; larguraRotulo?: number; compacto?: boolean; moeda?: boolean; titulo?: string;
  onClick?: (d: ItemBarra) => void;
  className?: string;
}
export function Barras(op: OpBarras) {
  return <Caixa className={op.className}>{(W) => <BarrasSvg {...op} W={W} />}</Caixa>;
}
function BarrasSvg({ W, ...op }: OpBarras & { W: number }) {
  const dados = (op.dados || []).filter((d) => d.valor !== null) as (ItemBarra & { valor: number })[];
  if (!dados.length) return <Vazio />;
  const fmt = op.formato || F.inteiro;
  const rotW = Math.min(op.larguraRotulo || 190, W * 0.42);
  const linhaH = 30, H = dados.length * linhaH + 8;
  const valW = 86;
  const max = Math.max(...dados.map((d) => d.valor), 0);
  const min = Math.min(...dados.map((d) => d.valor), 0);
  const plotW = W - rotW - valW - 8;
  const x = (v: number) => rotW + ((v - min) / ((max - min) || 1)) * plotW;
  return (
    <svg width={W} height={H} role="img" aria-label={op.titulo || "Gráfico de barras"}>
      <line x1={x(0)} x2={x(0)} y1={0} y2={H} className="geixo" />
      {dados.map((d, i) => {
        const y = i * linhaH + 4;
        const x0 = x(Math.min(0, d.valor)), x1 = x(Math.max(0, d.valor));
        const h = Math.min(18, linhaH - 10);
        const largura = Math.max(x1 - x0, 1);
        const r = Math.min(4, largura / 2);
        const yb = y + (linhaH - 4 - h) / 2;
        // ponta arredondada do lado do valor, reta na base
        const p = d.valor >= 0
          ? `M${x0},${yb} H${x1 - r} Q${x1},${yb} ${x1},${yb + r} V${yb + h - r} Q${x1},${yb + h} ${x1 - r},${yb + h} H${x0} Z`
          : `M${x1},${yb} H${x0 + r} Q${x0},${yb} ${x0},${yb + r} V${yb + h - r} Q${x0},${yb + h} ${x0 + r},${yb + h} H${x1} Z`;
        const c = d.cor || op.cor || cor(0);
        const dica = (ev: { clientX: number; clientY: number }) => mostrarDica(ev, d.rotulo, [{ valor: fmt(d.valor), cor: c }]);
        return (
          <g key={i} className={"gmarca" + (op.onClick ? " clicavel" : "")} tabIndex={0}
            onPointerMove={dica} onPointerLeave={esconderDica} onBlur={esconderDica}
            onFocus={(ev) => { const b = ev.currentTarget.getBoundingClientRect(); dica({ clientX: b.right - 80, clientY: b.top }); }}
            onClick={op.onClick ? () => { esconderDica(); op.onClick!(d); } : undefined}
            onKeyDown={op.onClick ? (ev) => { if (ev.key === "Enter") op.onClick!(d); } : undefined}>
            <RotuloCortado texto={d.rotulo} largura={rotW - 12} x={rotW - 8} y={y + linhaH / 2 - 2} className="grot"
              textAnchor="end" dominantBaseline="middle" />
            <path d={p} fill={c} className="gbarra" />
            <text x={x1 + 6} y={y + linhaH / 2 - 2} className="gval" dominantBaseline="middle">
              {op.compacto ? F.compacto(d.valor, op.moeda) : fmt(d.valor)}
            </text>
            <rect x={0} y={y} width={W} height={linhaH} fill="transparent" />
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------ colunas (1+ séries) */
export interface Serie { nome: string; pontos: { rotulo: string; valor: number }[] }
interface OpColunas {
  series: Serie[];
  formato?: Fmt; moeda?: boolean; altura?: number; titulo?: string; corInicial?: number;
  onClick?: (p: { rotulo: string }) => void;
  className?: string;
}
export function Colunas(op: OpColunas) {
  return <Caixa className={op.className}>{(W) => <ColunasSvg {...op} W={W} />}</Caixa>;
}
function ColunasSvg({ W, ...op }: OpColunas & { W: number }) {
  const series = (op.series || []).filter((s) => s.pontos && s.pontos.length);
  if (!series.length || series.every((s) => s.pontos.every((p) => !p.valor))) return <Vazio />;
  const fmt = op.formato || F.inteiro;
  const H = op.altura || 240;
  const m = { t: 12, r: 8, b: 30, l: 64 };
  const rotulos = series[0].pontos.map((p) => p.rotulo);
  const todos = series.flatMap((s) => s.pontos.map((p) => p.valor));
  const esc = escala(Math.max(...todos, 0), Math.min(...todos, 0));
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const y = (v: number) => m.t + ph - ((v - esc.ini) / (esc.fim - esc.ini)) * ph;
  const banda = pw / rotulos.length;
  const ns = series.length;
  const bw = Math.min(24, Math.max(4, (banda * 0.7 - (ns - 1) * 2) / ns));
  const grupoW = ns * bw + (ns - 1) * 2;
  const passoRot = Math.ceil(rotulos.length / Math.max(1, Math.floor(pw / 56)));
  const corJ = (j: number) => cor(op.corInicial ? op.corInicial + j : j);
  return (
    <>
      <svg width={W} height={H} role="img" aria-label={op.titulo || "Gráfico de colunas"}>
        {esc.ticks.map((t) => (
          <g key={"t" + t}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} className={t === 0 ? "geixo" : "ggrade"} />
            <text x={m.l - 8} y={y(t)} className="gtick" textAnchor="end" dominantBaseline="middle">{F.compacto(t, op.moeda)}</text>
          </g>
        ))}
        {rotulos.map((r, i) => {
          const cx = m.l + banda * i + banda / 2;
          const dica = (ev: { clientX: number; clientY: number }) => mostrarDica(ev, F.mes(r), series.map((s, j) => ({
            valor: fmt(s.pontos[i] ? s.pontos[i].valor : 0), nome: ns > 1 ? s.nome : "", cor: corJ(j),
          })));
          return (
            <g key={i}>
              {i % passoRot === 0 && <text x={cx} y={H - m.b + 16} className="gtick" textAnchor="middle">{F.mes(r)}</text>}
              <g className={"gmarca" + (op.onClick ? " clicavel" : "")} tabIndex={0}
                onPointerMove={dica} onPointerLeave={esconderDica} onBlur={esconderDica}
                onFocus={(ev) => { const b = ev.currentTarget.getBoundingClientRect(); dica({ clientX: b.left + b.width / 2, clientY: b.top + 20 }); }}
                onClick={op.onClick ? () => { esconderDica(); op.onClick!({ rotulo: r }); } : undefined}>
                <rect x={m.l + banda * i} y={m.t} width={banda} height={ph} fill="transparent" className="ghit" />
                {series.map((s, j) => {
                  const v = s.pontos[i] ? s.pontos[i].valor : 0;
                  const x0 = cx - grupoW / 2 + j * (bw + 2);
                  const yt = y(Math.max(v, 0)), yb = y(Math.min(v, 0));
                  const h = Math.max(yb - yt, v ? 1 : 0);
                  const rr = Math.min(4, bw / 2, h);
                  const d = v >= 0
                    ? `M${x0},${yb} V${yt + rr} Q${x0},${yt} ${x0 + rr},${yt} H${x0 + bw - rr} Q${x0 + bw},${yt} ${x0 + bw},${yt + rr} V${yb} Z`
                    : `M${x0},${yt} V${yb - rr} Q${x0},${yb} ${x0 + rr},${yb} H${x0 + bw - rr} Q${x0 + bw},${yb} ${x0 + bw},${yb - rr} V${yt} Z`;
                  return h > 0 ? <path key={j} d={d} fill={corJ(j)} className="gbarra" /> : null;
                })}
              </g>
            </g>
          );
        })}
      </svg>
      <Legenda series={series} tipo="barra" />
    </>
  );
}

/* ------------------------------------------------------------ linhas / área */
interface OpLinhas { series: Serie[]; formato?: Fmt; moeda?: boolean; altura?: number; titulo?: string; area?: boolean; className?: string }
export function Linhas(op: OpLinhas) {
  return <Caixa className={op.className}>{(W) => <LinhasSvg {...op} W={W} />}</Caixa>;
}
function LinhasSvg({ W, ...op }: OpLinhas & { W: number }) {
  const [guia, setGuia] = useState<number | null>(null);
  const series = (op.series || []).filter((s) => s.pontos && s.pontos.length);
  if (!series.length) return <Vazio />;
  const fmt = op.formato || F.inteiro;
  const H = op.altura || 240;
  const m = { t: 14, r: 16, b: 30, l: 64 };
  const rotulos = series[0].pontos.map((p) => p.rotulo);
  const todos = series.flatMap((s) => s.pontos.map((p) => p.valor));
  const esc = escala(Math.max(...todos, 0), Math.min(...todos, 0));
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const n = rotulos.length;
  const x = (i: number) => m.l + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
  const y = (v: number) => m.t + ph - ((v - esc.ini) / (esc.fim - esc.ini)) * ph;
  const passoRot = Math.ceil(n / Math.max(1, Math.floor(pw / 56)));
  const base = y(Math.max(esc.ini, 0));
  return (
    <>
      <svg width={W} height={H} role="img" aria-label={op.titulo || "Gráfico de linhas"}>
        {esc.ticks.map((t) => (
          <g key={"t" + t}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} className={t === 0 ? "geixo" : "ggrade"} />
            <text x={m.l - 8} y={y(t)} className="gtick" textAnchor="end" dominantBaseline="middle">{F.compacto(t, op.moeda)}</text>
          </g>
        ))}
        {rotulos.map((r, i) => (i % passoRot === 0
          ? <text key={"r" + i} x={x(i)} y={H - m.b + 16} className="gtick" textAnchor="middle">{F.mes(r)}</text> : null))}
        {series.map((s, j) => {
          const pts = s.pontos.map((p, i) => [x(i), y(p.valor)]);
          const d = pts.map((p, i) => (i ? "L" : "M") + p[0] + "," + p[1]).join(" ");
          const u = pts[pts.length - 1];
          return (
            <g key={j}>
              {op.area && series.length === 1 &&
                <path d={d + ` L${u[0]},${base} L${pts[0][0]},${base} Z`} fill={cor(j)} className="garea" />}
              <path d={d} stroke={cor(j)} className="glinha" />
              <circle cx={u[0]} cy={u[1]} r={4} fill={cor(j)} className="gponto" />
            </g>
          );
        })}
        {guia !== null && <>
          <line x1={x(guia)} x2={x(guia)} y1={m.t} y2={m.t + ph} className="gguia" />
          {series.map((s, j) => <circle key={j} cx={x(guia)} cy={y(s.pontos[guia].valor)} r={4} fill={cor(j)} className="gponto" />)}
        </>}
        <rect x={m.l} y={m.t} width={pw} height={ph} fill="transparent"
          onPointerMove={(ev) => {
            const b = ev.currentTarget.ownerSVGElement!.getBoundingClientRect();
            const i = Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - b.left - m.l) / pw) * (n - 1))));
            setGuia(i);
            mostrarDica(ev, F.mes(rotulos[i]), series.map((s, j) => ({ valor: fmt(s.pontos[i].valor), nome: series.length > 1 ? s.nome : "", cor: cor(j) })));
          }}
          onPointerLeave={() => { esconderDica(); setGuia(null); }} />
      </svg>
      <Legenda series={series} tipo="linha" />
    </>
  );
}

/* ------------------------------------------------------------ rosca */
interface OpRosca {
  dados: ItemBarra[]; formato?: Fmt; altura?: number; titulo?: string; compacto?: boolean; moeda?: boolean; rotuloTotal?: string;
  onClick?: (d: ItemBarra) => void; className?: string;
}
export function Rosca(op: OpRosca) {
  return <Caixa className={op.className}>{() => <RoscaSvg {...op} />}</Caixa>;
}
function RoscaSvg(op: OpRosca) {
  const dados = (op.dados || []).filter((d) => (d.valor || 0) > 0) as (ItemBarra & { valor: number })[];
  if (!dados.length) return <Vazio />;
  const fmt = op.formato || F.inteiro;
  const total = dados.reduce((a, d) => a + d.valor, 0);
  const H = op.altura || 200, R = Math.min(H / 2 - 6, 90), r = R * 0.62;
  const cx = R + 6, cy = H / 2;
  let a0 = -Math.PI / 2;
  const pct = (v: number) => F.dois((v / total) * 100) + "%";
  return (
    <div className="grosca">
      <svg width={R * 2 + 12} height={H} role="img" aria-label={op.titulo || "Gráfico de rosca"}>
        {dados.map((d, i) => {
          const ang = (d.valor / total) * Math.PI * 2;
          const a1 = a0 + ang;
          const grande = ang > Math.PI ? 1 : 0;
          const p = (rad: number, a: number) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
          const [x0, y0] = p(R, a0), [x1, y1] = p(R, a1 - 0.0001), [x2, y2] = p(r, a1 - 0.0001), [x3, y3] = p(r, a0);
          a0 = a1;
          const c = d.cor || cor(i);
          return (
            <g key={i} className={"gmarca" + (op.onClick ? " clicavel" : "")} tabIndex={0}
              onPointerMove={(ev) => mostrarDica(ev, d.rotulo, [{ valor: fmt(d.valor), nome: pct(d.valor), cor: c }])}
              onPointerLeave={esconderDica}
              onClick={op.onClick ? () => { esconderDica(); op.onClick!(d); } : undefined}>
              <path d={`M${x0},${y0} A${R},${R} 0 ${grande} 1 ${x1},${y1} L${x2},${y2} A${r},${r} 0 ${grande} 0 ${x3},${y3} Z`} fill={c} className="gfatia" />
            </g>
          );
        })}
        <text x={cx} y={cy - 6} className="grosca-total" textAnchor="middle">{op.compacto ? F.compacto(total, op.moeda) : fmt(total)}</text>
        <text x={cx} y={cy + 14} className="gtick" textAnchor="middle">{op.rotuloTotal || "total"}</text>
      </svg>
      <div className="grosca-leg">
        {dados.map((d, i) => (
          <div key={i}><span className="glk-barra" style={{ background: d.cor || cor(i) }} /><span>{d.rotulo}</span><strong>{pct(d.valor)}</strong></div>
        ))}
      </div>
    </div>
  );
}

/** Esconde a dica ao trocar de tela. */
export function useLimparDica() {
  useEffect(() => esconderDica, []);
}
