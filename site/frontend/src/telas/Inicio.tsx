// Tela Início: cards, alertas, atraso dos títulos e gráficos do período.
import { useEffect, useState } from "react";
import { api, opcoesGerais, type Codigo } from "../api";
import { F, fmtData, guardado } from "../formatos";
import { Link, datasPeriodo, useNav, usePeriodo } from "../navegacao";
import { useAvisar } from "../componentes/Avisos";
import { Barras, Colunas, type ItemBarra } from "../componentes/Graficos";
import { Kpis } from "../componentes/Kpis";

interface Resumo {
  kpis: Record<string, number>;
  comparacao?: Record<string, number> & { rotulo?: string };
  historico?: { meses: string[]; qtd: number[]; valor: number[] };
  alertas?: { nivel: string; link: string; qtd: number; texto: string; valor?: number }[];
  aging?: Record<string, { rotulo: string; valor: number; qtd: number }[]>;
  periodo?: [string, string];
  filial?: string | null;
}
interface Semana { rotulo: string; receber: number; pagar: number; ini: string; fim: string }
interface Graficos {
  mov_func?: ItemBarra[]; mov_cat?: ItemBarra[]; mov_tipo?: ItemBarra[];
  semanas?: Semana[]; por_semana?: boolean;
  periodo?: [string, string];
  filial?: string | null;
}

const filialURL = (d: { filial?: string | null }) => (d.filial !== null && d.filial !== undefined ? `&filial=${d.filial}` : "");
const mesURL = (d: { periodo?: [string, string]; filial?: string | null }) =>
  (d.periodo ? `&ini=${d.periodo[0]}&fim=${d.periodo[1]}` : "") + filialURL(d);

function rotuloPeriodo(ini: string, fim: string) {
  const a = new Date(ini + "T12:00:00"), z = new Date(fim + "T12:00:00");
  const fimMes = new Date(a.getFullYear(), a.getMonth() + 1, 0).getDate();
  if (a.getDate() === 1 && a.getMonth() === z.getMonth() && a.getFullYear() === z.getFullYear() && z.getDate() === fimMes)
    return a.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return `${fmtData(ini)} a ${fmtData(fim)}`;
}

function Alertas({ lista }: { lista: NonNullable<Resumo["alertas"]> }) {
  if (!lista.length) return <div className="alerta ok">✓ Nenhum alerta no momento</div>;
  return <>{lista.map((a, i) => (
    <Link key={i} className={"alerta " + a.nivel} href={a.link}>
      <strong>{F.inteiro(a.qtd)}</strong>
      <span>{" " + a.texto + (a.valor ? " · " + F.compacto(a.valor, true) : "")}</span>
      <span className="seta">›</span>
    </Link>
  ))}</>;
}

const CORES_ATRASO = ["var(--ok, #2f9e44)", "#f2c94c", "#f2994a", "#e8590c", "var(--critico)"];
function Atraso({ ag, extra }: { ag: NonNullable<Resumo["aging"]>; extra: string }) {
  return <>{([["R", "A receber"], ["P", "A pagar"]] as const).map(([k, nome]) => {
    const fx = ag[k] || [];
    const tot = fx.reduce((a, b) => a + b.valor, 0);
    const link = `/financeiro?tipo=${k}&status=A` + extra;
    return (
      <div className="aging" key={k}>
        <div className="aging-cab"><strong>{nome}</strong><span>{F.moeda(tot)}</span></div>
        <div className="aging-barra">
          {fx.map((f, i) => f.valor > 0 && (
            <Link key={i} href={link} style={{ flex: String(f.valor), background: CORES_ATRASO[i] }}
              title={`${f.rotulo}: ${F.moeda(f.valor)} (${f.qtd} títulos)`} />
          ))}
        </div>
        <div className="aging-leg">
          {fx.map((f, i) => (
            <Link key={i} href={link} className="aging-item">
              <i style={{ background: CORES_ATRASO[i] }} /><span>{f.rotulo}</span><strong>{F.compacto(f.valor, true)}</strong>
              <em>{tot ? Math.round((f.valor / tot) * 100) + "%" : "0%"}</em>
            </Link>
          ))}
        </div>
      </div>
    );
  })}</>;
}

function SaldoSemanas({ sem }: { sem: Semana[] }) {
  let acum = 0;
  return (
    <div className="saldo-semanas">
      <div className="saldo-tit">Saldo acumulado (receber − pagar)</div>
      {sem.map((s, i) => {
        acum += s.receber - s.pagar;
        return (
          <div key={i} className={"saldo-sem " + (acum < 0 ? "neg" : "pos")} title={`Saldo acumulado até ${s.rotulo}: ${F.moeda(acum)}`}>
            <span>{F.mes(s.rotulo)}</span><strong>{F.compacto(acum, true)}</strong>
          </div>
        );
      })}
    </div>
  );
}

export default function Inicio() {
  const { periodo } = usePeriodo();
  const { navegar } = useNav();
  const avisar = useAvisar();
  const [filiais, setFiliais] = useState<Codigo[]>([]);
  const [filial, setFilial] = useState(() => guardado.ler("filial_inicio") || "");
  const [modoTipo, setModoTipo] = useState(() => (guardado.ler("inicio_movtipo") === "tipo" ? "tipo" : "cat"));
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [graf, setGraf] = useState<Graficos | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [ini, fim] = datasPeriodo(periodo);

  useEffect(() => {
    opcoesGerais().then((o) => setFiliais(o.filiais || [])).catch(() => {});
  }, []);

  // etapa 1: cards, alertas e atraso | etapa 2: gráficos. As duas vão juntas; cada uma aparece quando chega.
  useEffect(() => {
    let vivo = true;
    const q = `ini=${ini}&fim=${fim}` + (filial ? `&filial=${encodeURIComponent(filial)}` : "");
    setCarregando(true);
    const r = api<Resumo>(`/api/inicio?parte=resumo&${q}`).then((d) => { if (vivo) { setResumo(d); setCarregando(false); } });
    const g = api<Graficos>(`/api/inicio?parte=graficos&${q}`).then((d) => { if (vivo) setGraf(d); });
    Promise.all([r, g]).catch((e) => { if (vivo) avisar(e.message); }).finally(() => { if (vivo) setCarregando(false); });
    return () => { vivo = false; };
  }, [ini, fim, filial, avisar]);

  const rotulo = rotuloPeriodo(ini, fim);
  const suf = rotulo !== `${fmtData(ini)} a ${fmtData(fim)}` ? "(mês)" : "(período)";

  let cards = null;
  if (resumo) {
    const k = resumo.kpis;
    const cp = resumo.comparacao || {};
    const h = resumo.historico || { meses: [], qtd: [], valor: [] };
    const pct = (a: number, b?: number) => (b ? ((a - b) / b) * 100 : null);
    const vtxt = `vs ${cp.rotulo || "período anterior"}`;
    cards = [
      { rotulo: `A receber em aberto ${suf}`, valor: F.compacto(k.receber_aberto, true), detalhe: `Vencido: ${F.moeda(k.receber_vencido)}`, classe: "destaque" },
      { rotulo: `A pagar em aberto ${suf}`, valor: F.compacto(k.pagar_aberto, true), detalhe: `Vencido: ${F.moeda(k.pagar_vencido)}` },
      { rotulo: `Movimentos ${suf}`, valor: F.inteiro(k.mov_mes), variacao: pct(k.mov_mes, cp.mov_mes as number), varTexto: vtxt, spark: h.qtd, sparkRot: h.meses },
      { rotulo: `Valor movimentado ${suf}`, valor: F.compacto(k.mov_mes_valor, true), variacao: pct(k.mov_mes_valor, cp.mov_mes_valor as number), varTexto: vtxt, spark: h.valor, sparkRot: h.meses },
      { rotulo: "Valor em estoque (hoje)", valor: F.compacto(k.estoque_valor, true), detalhe: "Saldo × custo médio" },
    ];
  }

  const cat = modoTipo === "cat";
  const sem = graf?.semanas || [];

  return (
    <div className={carregando && resumo ? "carregando" : ""} style={{ display: "contents" }}>
      <p className="nota linha-filial" style={{ margin: "0 0 10px" }}>Período: <strong>{rotulo}</strong>{" "}
        <label className="filial-inicio">Filial{" "}
          <select className="campo" aria-label="Filial" value={filial}
            onChange={(e) => { guardado.gravar("filial_inicio", e.target.value); setFilial(e.target.value); }}>
            <option value="">Todas</option>
            {filiais.map((f) => <option key={f.cod} value={f.cod}>{f.nome ? `${f.cod} - ${f.nome}` : f.cod}</option>)}
            {filial && !filiais.some((f) => f.cod === filial) && <option value={filial}>{filial}</option>}
          </select>
        </label>
      </p>
      <div className="alertas">
        {resumo ? <Alertas lista={resumo.alertas || []} /> : <><span className="alerta esqueleto">&nbsp;</span><span className="alerta esqueleto">&nbsp;</span></>}
      </div>
      <div className="kpis">
        {cards ? <Kpis lista={cards} /> : [0, 1, 2, 3, 4].map((i) => <div key={i} className="kpi esqueleto" />)}
      </div>
      <div className="grade">
        <div className="cartao c7">
          <div className="cartao-cab"><h2>Movimentações por funcionário <span className="sub">· quantidade no período, sem cancelados · clique para abrir</span></h2></div>
          {graf ? <Barras dados={graf.mov_func || []} cor="var(--serie-3)" larguraRotulo={220}
            onClick={(x) => {
              const c = x.rotulo.split(" ")[0];
              if (x.rotulo !== "Outros" && !x.rotulo.startsWith("(")) navegar("/movimentos?vendedor=" + encodeURIComponent(c) + mesURL(graf));
            }} /> : <div className="g-esqueleto" />}
        </div>
        <div className="cartao c5">
          <div className="cartao-cab">
            <h2>Movimentos por <span>{cat ? "categoria" : "tipo"}</span> <span className="sub">· quantidade no período, clique para abrir</span></h2>
            <select className="campo" style={{ minWidth: "auto", height: 28 }} aria-label="Agrupar movimentos por" value={modoTipo}
              onChange={(e) => { guardado.gravar("inicio_movtipo", e.target.value); setModoTipo(e.target.value); }}>
              <option value="cat">Categoria</option><option value="tipo">Tipo</option>
            </select>
          </div>
          {graf ? <Barras key={modoTipo} dados={(cat ? graf.mov_cat : graf.mov_tipo) || []} larguraRotulo={cat ? 230 : 190}
            onClick={(x) => {
              if (x.rotulo === "Outros") return;
              const cod = x.rotulo.split(" ")[0];
              navegar("/movimentos?" + (cat ? "prefixo=" + encodeURIComponent(cod + ".") : "tipos=" + encodeURIComponent(cod)) + mesURL(graf));
            }} /> : <div className="g-esqueleto" />}
        </div>
        <div className="cartao c7">
          <div className="cartao-cab"><h2>Contas a pagar e a receber por <span>{graf?.por_semana === false ? "mês" : "semana"}</span> <span className="sub">· títulos em aberto no período · clique para abrir</span></h2></div>
          {graf ? <>
            <Colunas moeda altura={230} formato={F.moeda} series={[
              { nome: "A receber", pontos: sem.map((s) => ({ rotulo: s.rotulo, valor: s.receber })) },
              { nome: "A pagar", pontos: sem.map((s) => ({ rotulo: s.rotulo, valor: s.pagar })) },
            ]} onClick={(p) => {
              const w = sem.find((x) => x.rotulo === p.rotulo);
              if (w) navegar(`/financeiro?tipo=T&status=A&base=vencimento&ini=${w.ini}&fim=${w.fim}` + filialURL(graf));
            }} />
            <SaldoSemanas sem={sem} />
          </> : <><div className="g-esqueleto" /><div className="saldo-semanas" /></>}
        </div>
        <div className="cartao c5">
          <div className="cartao-cab"><h2>Atraso dos títulos em aberto <span className="sub">· todos os vencimentos · clique para abrir</span></h2></div>
          {resumo ? <div><Atraso ag={resumo.aging || {}} extra={filialURL(resumo)} /></div> : <div className="g-esqueleto" />}
        </div>
      </div>
    </div>
  );
}
