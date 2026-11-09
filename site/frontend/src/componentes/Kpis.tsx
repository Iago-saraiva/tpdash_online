// Cards de indicadores (com variação e mini gráfico dos últimos meses).
import { F } from "../formatos";

export interface Kpi {
  rotulo: string; valor: string; detalhe?: string; classe?: string;
  variacao?: number | null; varTexto?: string;
  spark?: number[]; sparkRot?: string[];
}

function Spark({ vals, rots }: { vals: number[]; rots: string[] }) {
  const W = 120, H = 30, n = vals.length;
  const max = Math.max(...vals), min = Math.min(...vals, 0);
  const x = (i: number) => 3 + (i / (n - 1)) * (W - 6), y = (v: number) => 3 + (H - 6) * (1 - (v - min) / ((max - min) || 1));
  const pts = vals.map((v, i) => `${x(i)},${y(v)}`);
  return (
    <div className="spark-box" title={"Últimos 6 meses: " + vals.map((v, i) => `${F.mes(rots[i] || "")} ${F.compacto(v)}`).join(" · ")}>
      <svg viewBox={`0 0 ${W} ${H}`} className="spark" preserveAspectRatio="none">
        <path d={`M${x(0)},${H} L${pts.join(" L")} L${x(n - 1)},${H} Z`} className="spark-area" />
        <polyline points={pts.join(" ")} className="spark-linha" />
        <circle cx={x(n - 1)} cy={y(vals[n - 1])} r={2.6} className="spark-ponto" />
      </svg>
      <span className="spark-leg">6 meses</span>
    </div>
  );
}

export function Kpis({ lista }: { lista: Kpi[] }) {
  return <>{lista.map((k, i) => {
    const v = k.variacao;
    return (
      <div key={i} className={"kpi" + (k.classe ? " " + k.classe : "")}>
        <div className="rot">{k.rotulo}</div>
        <div className="val">{k.valor}</div>
        {k.detalhe && <div className="det">{k.detalhe}</div>}
        {v !== undefined && v !== null && (
          <div className={"var " + (Math.abs(v) < 0.5 ? "igual" : v > 0 ? "sobe" : "desce")}>
            {(Math.abs(v) < 0.5 ? "● " : v > 0 ? "▲ " : "▼ ") + Math.abs(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 }) + "% " + (k.varTexto || "")}
          </div>
        )}
        {k.spark && k.spark.length > 1 && <Spark vals={k.spark} rots={k.sparkRot || []} />}
      </div>
    );
  })}</>;
}
