// Editor de layout de impressão no estilo ReportBuilder: bandas (título, cabeçalho, grupos, detalhe, sumário, rodapé),
// itens posicionados em milímetros, arrastar/redimensionar, propriedades, sub-relatórios, tabelas do banco e PDF.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type DragEvent, type PointerEvent as PE, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, baixar, enviarArquivo } from "../api";

const PX_MM = 96 / 25.4;              // pixels por mm com zoom 100%
const PT_MM = 25.4 / 72;              // mm por ponto (tamanho de fonte)
const PAPEIS: Record<string, [number, number]> = { A4: [210, 297], Carta: [215.9, 279.4], "Ofício": [215.9, 355.6], A5: [148, 210], A3: [297, 420] };
const FORMATOS = ["", "#,0.00;-#,0.00", "#,0.00", "$#,0.00;($#,0.00)", "0", "000000", "0.00 %", "dd/mm/yyyy", "dd/mm/yy", "mm/yyyy", "dd/mm/yyyy hh:nn", "hh:nn"];
const SISTEMA: Record<string, string> = { data: "Data", hora: "Hora", datahora: "Data e hora", pagina: "Nº da página", paginas: "Total de páginas", pagina_desc: "Página N", pagina_de: "N de T", pagina_x_de_y: "Página N de T" };
const CALCS: Record<string, string> = { soma: "Soma", contagem: "Contagem", media: "Média", maximo: "Máximo", minimo: "Mínimo" };
const NOMES_BANDA: Record<string, string> = { titulo: "Título", cabecalho: "Cabeçalho (toda página)", detalhe: "Detalhe", sumario: "Sumário (final)", rodape: "Rodapé (toda página)" };
const FONTES = ["Arial", "Times New Roman", "Courier New"];
const COMPONENTES: [string, string, string][] = [["texto", "Texto", "A"], ["campo", "Campo", "▭"], ["total", "Total", "Σ"], ["sistema", "Data / página", "#"],
  ["linha", "Linha", "—"], ["retangulo", "Retângulo", "□"], ["variavel", "Cálculo", "ƒ"], ["sub", "Sub-relatório", "⊞"], ["grade", "Tabela", "▦"]];

/* eslint-disable @typescript-eslint/no-explicit-any */
type Item = any;
interface Banda { altura: number; visivel?: boolean; dinamica?: boolean; itens: Item[] }
interface Grupo { campo: string; visao: string | null; nova_pagina: boolean; cab: Banda; rod: Banda }
interface Secao { visao: string | null; bandas: Record<string, Banda>; grupos: Grupo[]; titulo_antes?: boolean }
interface Tabela { nome: string; tabela: string; campos: string[]; mestre: string | null; ligacoes: [string, string][] }
interface Desenho { pagina: { largura: number; altura: number; margens: Record<string, number> }; relatorio: Secao; tabelas?: Tabela[]; [k: string]: unknown }
interface Info {
  desenho: Desenho; origem: string; tem_original: boolean; tem_salvo: boolean; pode_editar: boolean; pode_tabelas?: boolean;
  campos: Record<string, string[]>; numeros: Record<string, string[]>; visoes: { nome: string; mestre?: string | null; tabela?: string | null }[];
}
interface LB { banda: Banda; rot: string; tipo: string; grupo?: number }

const clone = <T,>(o: T): T => JSON.parse(JSON.stringify(o, (k, v) => (k === "_k" ? undefined : v)));
const r1 = (v: number) => Math.round(v * 10) / 10;
let seq = 0;

function todasBandas(sec: Secao): Banda[] {
  const r: Banda[] = [];
  ["titulo", "cabecalho", "detalhe", "sumario", "rodape"].forEach((t) => { if (sec.bandas[t]) r.push(sec.bandas[t]); });
  (sec.grupos || []).forEach((g) => { r.push(g.cab, g.rod); });
  return r;
}
function chaves(sec: Secao) {
  todasBandas(sec).forEach((b) => b.itens.forEach((i) => { i._k = ++seq; if (i.tipo === "sub" && i.secao) chaves(i.secao); }));
}
function familia(n: string) {
  n = (n || "").toLowerCase();
  if (n.includes("courier") || n.includes("draft") || n.includes("console")) return "'Courier New', monospace";
  if (n.includes("times")) return "'Times New Roman', serif";
  return "Arial, Helvetica, sans-serif";
}

/* campos que só gravam no "change" do navegador (ao sair do campo, Enter ou setas do número), como no editor antigo */
function Nativo({ valor, aoMudar, ...resto }: { valor: string; aoMudar: (v: string) => void } & React.InputHTMLAttributes<HTMLInputElement>) {
  const ref = useRef<HTMLInputElement>(null);
  const fn = useRef(aoMudar);
  fn.current = aoMudar;
  useEffect(() => {
    const i = ref.current;
    if (!i) return;
    const h = () => fn.current(i.value);
    i.addEventListener("change", h);
    return () => i.removeEventListener("change", h);
  }, []);
  useEffect(() => { if (ref.current && document.activeElement !== ref.current) ref.current.value = valor; }, [valor]);
  return <input ref={ref} defaultValue={valor} {...resto} />;
}

function Prop({ rot, children, dica }: { rot: string; children: ReactNode; dica?: string }) { return <label className="dz-prop" title={dica}><span>{rot}</span>{children}</label>; }

export function Designer({ rid, nome, valores, fechar }: { rid: string; nome: string; valores: Record<string, string>; fechar: () => void }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [erro, setErro] = useState("");
  const D = useRef<Desenho | null>(null);
  const [pilha, setPilha] = useState<Secao[]>([]);
  const [selecao, setSelecao] = useState<Item[]>([]);
  const [bandaSel, setBandaSel] = useState<LB | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pendente, setPendente] = useState<string | null>(null);
  const [snap, setSnap] = useState(0.5);
  const [msgs, setMsgs] = useState<{ id: number; msg: string; tipo: string }[]>([]);
  const [janela, setJanela] = useState<{ editar?: Tabela } | null>(null);
  const [, setN] = useState(0);
  const r = () => setN((n) => n + 1);
  const desfazer = useRef<string[]>([]), refazer = useRef<string[]>([]);
  const sujo = useRef(false), copia = useRef<Item[] | null>(null);
  const centro = useRef<HTMLDivElement>(null);
  const areas = useRef(new Map<HTMLElement, LB>());
  const domItens = useRef(new Map<Item, HTMLElement>());
  const rolagem = useRef(0);
  const nMsg = useRef(0);
  const guardouTxt = useRef(false);

  const d = D.current;
  const secao = () => pilha[pilha.length - 1];
  const largUtil = () => (d ? d.pagina.largura - d.pagina.margens.esq - d.pagina.margens.dir : 190);
  const esc = () => PX_MM * zoom;
  const arred = (v: number) => (snap ? Math.round(v / snap) * snap : r1(v));

  const alerta = (msg: string, tipo = "erro") => {
    const id = ++nMsg.current;
    setMsgs((l) => [...l, { id, msg, tipo }]);
    setTimeout(() => setMsgs((l) => l.filter((x) => x.id !== id)), 5000);
  };

  async function carregar(base?: string) {
    try {
      const x = await api<Info>(`/api/rb/${encodeURIComponent(rid)}/desenho/abrir`, { valores: valores || {}, base });
      D.current = x.desenho;
      D.current.tabelas = D.current.tabelas || [];
      chaves(D.current.relatorio);
      setPilha([D.current.relatorio]); setSelecao([]); setBandaSel(null);
      desfazer.current = []; refazer.current = [];
      sujo.current = !!base;
      setInfo(x);
      precisaZoom.current = true;
    } catch (e) {
      setErro("Não foi possível abrir: " + (e as Error).message);
    }
  }
  useEffect(() => {
    document.body.classList.add("dz-aberto");
    carregar();
    return () => document.body.classList.remove("dz-aberto");
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // zoom que cabe na largura (ao abrir)
  const precisaZoom = useRef(false);
  useLayoutEffect(() => {
    if (!precisaZoom.current || !centro.current || !D.current) return;
    precisaZoom.current = false;
    const disp = centro.current.clientWidth - 60;
    setZoom(Math.max(0.5, Math.min(2, Math.floor((disp / (D.current.pagina.largura * PX_MM)) * 10) / 10)));
  });
  // a rolagem da página fica onde estava quando a tela é redesenhada
  useLayoutEffect(() => { if (centro.current) centro.current.scrollTop = rolagem.current; });
  useEffect(() => {
    const f = () => r();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);

  function sair() {
    if (sujo.current && !confirm("Há alterações não salvas. Sair mesmo assim?")) return;
    fechar();
  }
  function guardar() {
    desfazer.current.push(JSON.stringify(D.current));
    if (desfazer.current.length > 60) desfazer.current.shift();
    refazer.current = [];
    sujo.current = true;
  }
  function restaurarDe(json: string) {
    D.current = JSON.parse(json);
    chaves(D.current!.relatorio);
    setPilha([D.current!.relatorio]);          // volta para o relatório principal
    setSelecao([]); setBandaSel(null);
    sujo.current = true;
    // as tabelas do banco também voltam: refaz a lista de campos
    if (info) setInfo(comTabelas(info, D.current!.tabelas || []));
    r();
  }
  const voltarAcao = () => { if (desfazer.current.length) { refazer.current.push(JSON.stringify(D.current)); restaurarDe(desfazer.current.pop()!); } };
  const refazerAcao = () => { if (refazer.current.length) { desfazer.current.push(JSON.stringify(D.current)); restaurarDe(refazer.current.pop()!); } };

  // ------------------------------------------------------------------ bandas
  function listaBandas(sec: Secao): LB[] {
    const res: LB[] = [];
    const b = sec.bandas;
    const principal = sec === D.current?.relatorio;
    if (b.titulo) res.push({ banda: b.titulo, rot: NOMES_BANDA.titulo, tipo: "titulo" });
    if (b.cabecalho) res.push({ banda: b.cabecalho, rot: principal ? NOMES_BANDA.cabecalho : "Cabeçalho", tipo: "cabecalho" });
    (sec.grupos || []).forEach((g, i) => res.push({ banda: g.cab, rot: `Grupo ${i + 1}: ${g.campo || "?"} · cabeçalho`, tipo: "gcab", grupo: i }));
    res.push({ banda: b.detalhe, rot: NOMES_BANDA.detalhe + (sec.visao ? " · " + sec.visao : ""), tipo: "detalhe" });
    (sec.grupos || []).slice().reverse().forEach((g, k) => {
      const i = sec.grupos.length - 1 - k;
      res.push({ banda: g.rod, rot: `Grupo ${i + 1}: ${g.campo || "?"} · rodapé`, tipo: "grod", grupo: i });
    });
    if (b.sumario) res.push({ banda: b.sumario, rot: NOMES_BANDA.sumario, tipo: "sumario" });
    if (b.rodape && principal) res.push({ banda: b.rodape, rot: NOMES_BANDA.rodape, tipo: "rodape" });
    return res;
  }
  const bandaDe = (it: Item) => listaBandas(secao()).find((l) => l.banda.itens.includes(it));
  const lbDe = (banda: Banda) => listaBandas(secao()).find((l) => l.banda === banda) || null;

  // ------------------------------------------------------------------ criar / apagar itens
  function fontePadrao() {
    const det = secao().bandas.detalhe;
    const f = (det.itens.find((i) => i.fonte) || {}).fonte;
    return f ? Object.assign({}, f, { n: false, i: false, s: false }) : { nome: "Arial", tam: 8, n: false, i: false, s: false, cor: "#000000" };
  }
  function novoItem(tipo: string, banda: Banda, x: number, y: number, extra?: { campo?: string; visao?: string | null }) {
    if (!info) return;
    guardar();
    const f = fontePadrao();
    const base = { _k: ++seq, tipo, x, y, w: 25, h: Math.max(r1(f.tam * PT_MM * 1.25), 3), fonte: f, alin: "e", nome: "" };
    let it: Item;
    switch (tipo) {
      case "texto": it = Object.assign(base, { texto: "Texto", auto: true }); break;
      case "campo": it = Object.assign(base, { campo: (extra && extra.campo) || "", visao: (extra && extra.visao) || null, formato: "" }); break;
      case "total": it = Object.assign(base, { campo: (extra && extra.campo) || "", calc: "soma", formato: "#,0.00;-#,0.00", alin: "d", fonte: Object.assign({}, f, { n: true }) }); break;
      case "sistema": it = Object.assign(base, { sistema: "pagina_x_de_y", w: 35, alin: "d" }); break;
      case "variavel": it = Object.assign(base, { nome: "Calculo" + seq, codigo: "begin\n  Value := 0;\nend;", tipo_dado: "numero", calc_tipo: "percurso", reset_tipo: "fim", ordem: 0, formato: "#,0.00;-#,0.00", alin: "d" }); break;
      case "linha": it = { _k: ++seq, tipo, x: 0, y, w: largUtil(), h: 1, posicao: "topo", espessura: 0.75, cor: "#000000" }; break;
      case "retangulo": it = { _k: ++seq, tipo, x, y, w: 40, h: 10, forma: "retangulo", cor: "#000000", fundo: null, espessura: 0.75 }; break;
      case "sub": {
        const filhas = (info.visoes || []).filter((v) => v.mestre && v.mestre === secao().visao);
        const vis = (filhas[0] || (info.visoes || [])[1] || {}).nome || null;
        it = { _k: ++seq, tipo, x: 0, y, w: largUtil(), h: 8, nome: "Sub" + seq, secao: { visao: vis, grupos: [], titulo_antes: true, bandas: { titulo: { altura: 5, itens: [] }, detalhe: { altura: 5, itens: [] }, sumario: { altura: 0, itens: [] } } } };
        break;
      }
      case "grade": {
        const atual = secao().visao;
        const filhas = (info.visoes || []).filter((v) => v.mestre && v.mestre === atual);
        const vis = (filhas[0] || (info.visoes || []).find((v) => v.nome !== atual) || (info.visoes || [])[0] || {}).nome || null;
        const larg = r1(largUtil() - x);
        const cs = (info.campos[vis || ""] || []).slice(0, 4);
        const nums = (info.numeros || {})[vis || ""] || [];
        it = { _k: ++seq, tipo, x, y, w: larg, h: 15, nome: "Tabela" + seq, visao: vis, fonte: { ...f, tam: 8 }, alt_linha: 5,
          cabecalho: true, bordas: true, cab_fundo: "#e6ecf2", cor_borda: "#999999",
          colunas: cs.map((c) => ({ campo: c, titulo: c, largura: r1(larg / Math.max(cs.length, 1)), alin: nums.includes(c) ? "d" : "e", formato: nums.includes(c) ? "#,0.00;-#,0.00" : "" })) };
        break;
      }
      default: return;
    }
    if (it.tipo === "campo" && it.campo) {
      const nums = (info.numeros || {})[it.visao || secao().visao || ""] || [];
      if (nums.includes(it.campo)) { it.alin = "d"; it.formato = "#,0.00;-#,0.00"; }
    }
    banda.itens.push(it);
    if (banda.altura < y + (it.h || 0)) banda.altura = r1(y + (it.h || 4));
    setSelecao([it]);
    setBandaSel(lbDe(banda) || bandaSel);
    r();
    if (tipo === "texto") setTimeout(() => { const t = document.querySelector<HTMLTextAreaElement>(".dz-dir textarea"); if (t) { t.focus(); t.select(); } }, 30);
  }
  function apagarSel() {
    if (!selecao.length) return;
    guardar();
    selecao.forEach((it) => { const lb = bandaDe(it); if (lb) lb.banda.itens = lb.banda.itens.filter((x) => x !== it); });
    setSelecao([]);
    r();
  }
  function duplicar(lista: Item[], dx: number, dy: number) {
    guardar();
    const novos: Item[] = [];
    lista.forEach((it) => {
      const lb = bandaDe(it) || bandaSel;
      if (!lb) return;
      const c = clone(it);
      c._k = ++seq; c.x = r1(c.x + dx); c.y = r1(c.y + dy);
      if (c.tipo === "sub") chaves(c.secao);
      lb.banda.itens.push(c); novos.push(c);
    });
    setSelecao(novos);
    r();
  }
  function entrarSub(it: Item) {
    if (!it.secao) return;
    setPilha((p) => [...p, it.secao]);
    setSelecao([]); setBandaSel(null);
  }

  // ------------------------------------------------------------------ teclado
  const estado = useRef({ pendente, selecao, pilha, bandaSel });
  estado.current = { pendente, selecao, pilha, bandaSel };
  const acoes = useRef<Record<string, () => void>>({});
  acoes.current = { voltar: voltarAcao, refazer: refazerAcao, salvar: acaoSalvar, apagar: apagarSel };
  useEffect(() => {
    function teclas(e: KeyboardEvent) {
      if (!D.current) return;
      const { pendente: pend, selecao: sel, pilha: pl, bandaSel: bs } = estado.current;
      const alvo = e.target as HTMLElement;
      if (alvo && alvo.closest && alvo.closest(".modal")) return;      // janela de tabelas aberta
      const emCampo = /^(INPUT|TEXTAREA|SELECT)$/.test((alvo || {}).tagName || "");
      const ctrl = e.ctrlKey || e.metaKey;
      if (e.key === "Escape") {
        e.stopPropagation();
        if (pend) { setPendente(null); return; }
        if (emCampo) { alvo.blur(); return; }
        if (sel.length) { setSelecao([]); return; }
        if (pl.length > 1) { setPilha(pl.slice(0, -1)); return; }
        return;
      }
      if (emCampo) return;
      const k = e.key.toLowerCase();
      if (ctrl && k === "z") { e.preventDefault(); acoes.current.voltar(); return; }
      if (ctrl && k === "y") { e.preventDefault(); acoes.current.refazer(); return; }
      if (ctrl && k === "s") { e.preventDefault(); acoes.current.salvar(); return; }
      if (ctrl && k === "c" && sel.length) { copia.current = sel.map((i) => clone(i)); return; }
      if (ctrl && k === "v" && copia.current && bs) {
        e.preventDefault();
        guardar();
        setSelecao(copia.current.map((c) => { const n = clone(c); n._k = ++seq; n.y = r1(n.y + 1); if (n.tipo === "sub") chaves(n.secao); bs.banda.itens.push(n); return n; }));
        r(); return;
      }
      if (ctrl && k === "d" && sel.length) { e.preventDefault(); duplicar(sel, 2, 2); return; }
      if ((e.key === "Delete" || e.key === "Backspace") && sel.length) { e.preventDefault(); acoes.current.apagar(); return; }
      const setas: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      if (setas[e.key] && sel.length) {
        e.preventDefault();
        guardar();
        const p = e.shiftKey ? 5 : (e.altKey ? 0.1 : 0.5);
        sel.forEach((it) => { it.x = r1(it.x + setas[e.key][0] * p); it.y = r1(it.y + setas[e.key][1] * p); });
        r();
      }
    }
    document.addEventListener("keydown", teclas, true);
    return () => document.removeEventListener("keydown", teclas, true);
  });

  // ------------------------------------------------------------------ ações
  async function acaoSalvar() {
    if (!info || !D.current) return;
    if (!info.pode_editar) { alerta("Você não tem permissão para salvar layouts."); return; }
    try {
      await api(`/api/rb/${encodeURIComponent(rid)}/desenho`, { desenho: clone(D.current) });
      sujo.current = false;
      info.tem_salvo = true;
      alerta("Layout salvo. O PDF deste relatório passa a sair assim para todos.", "ok");
      r();
    } catch (e) { alerta((e as Error).message); }
  }
  async function acaoPDF() {
    try { await baixar(`/api/rb/${encodeURIComponent(rid)}/desenho/pdf`, { valores: valores || {}, desenho: clone(D.current) }); }
    catch (e) { alerta((e as Error).message); }
  }
  async function mais(v: string) {
    if (!v || !info) return;
    if (v === "excluir") {
      if (!confirm("Apagar o layout salvo deste relatório?")) return;
      try { await api(`/api/rb/${encodeURIComponent(rid)}/desenho/excluir`, {}); sujo.current = false; carregar(); } catch (e) { alerta((e as Error).message); }
      return;
    }
    if (v === "rtm") {
      try { await baixar(`/api/rb/${encodeURIComponent(rid)}/desenho/rtm`, { desenho: clone(D.current) }); }
      catch (e) { alerta((e as Error).message); }
      return;
    }
    if (v === "rtm_importar") { arqRtm.current?.click(); return; }
    if (sujo.current && !confirm("Descartar as alterações atuais?")) return;
    carregar(v);
  }
  const arqRtm = useRef<HTMLInputElement>(null);
  async function importarRtm(arq: File | undefined) {
    if (arqRtm.current) arqRtm.current.value = "";
    if (!arq || !info) return;
    if (sujo.current && !confirm("Substituir o layout que está na tela pelo do arquivo? As alterações não salvas serão perdidas.")) return;
    try {
      const x = await enviarArquivo<{ desenho: Desenho; faltam: string[] }>(`/api/rb/${encodeURIComponent(rid)}/desenho/rtm/importar`, arq);
      guardar();                                   // dá para desfazer (Ctrl+Z) a importação
      D.current = x.desenho;
      D.current.tabelas = D.current.tabelas || [];
      chaves(D.current.relatorio);
      setPilha([D.current.relatorio]); setSelecao([]); setBandaSel(null);
      setInfo(comTabelas(info, D.current.tabelas));
      precisaZoom.current = true;
      sujo.current = true;
      alerta("Layout do arquivo carregado. Confira e clique em Salvar para manter." +
        (x.faltam.length ? " Atenção: este relatório não tem as fontes de dados " + x.faltam.join(", ") + " (os campos delas sairão vazios)." : ""),
        x.faltam.length ? "erro" : "ok");
      r();
    } catch (e) { alerta((e as Error).message); }
  }

  // ------------------------------------------------------------------ arrastar / redimensionar
  const posMM = (e: { clientX: number; clientY: number }, area: HTMLElement) => {
    const rc = area.getBoundingClientRect();
    const s = esc();
    return { x: Math.max(0, arred((e.clientX - rc.left) / s)), y: Math.max(0, arred((e.clientY - rc.top) / s)) };
  };
  function iniciarArraste(ev: PE<HTMLDivElement>, it: Item, lb: LB) {
    if (ev.button !== 0) return;
    ev.stopPropagation();
    const dom = ev.currentTarget;
    if (pendente) { const p = posMM(ev, dom.parentElement as HTMLElement); novoItem(pendente, lb.banda, p.x, p.y); setPendente(null); return; }
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
      setSelecao(selecao.includes(it) ? selecao.filter((x) => x !== it) : selecao.concat([it]));
      setBandaSel(lb); return;
    }
    const sel = selecao.includes(it) ? selecao : [it];
    if (!selecao.includes(it)) { setSelecao(sel); setBandaSel(lb); }
    const x0 = ev.clientX, y0 = ev.clientY;
    const orig = sel.map((i) => ({ i, x: i.x, y: i.y }));
    let mexeu = false;
    dom.setPointerCapture(ev.pointerId);
    const s = esc();
    const mover = (e: PointerEvent) => {
      const dx = (e.clientX - x0) / s, dy = (e.clientY - y0) / s;
      if (!mexeu && Math.abs(dx) + Math.abs(dy) < 0.6) return;
      if (!mexeu) { guardar(); mexeu = true; }
      orig.forEach((o) => {
        o.i.x = Math.max(-5, arred(o.x + dx)); o.i.y = arred(o.y + dy);
        const de = domItens.current.get(o.i);
        if (de) { de.style.left = o.i.x * s + "px"; de.style.top = o.i.y * s + "px"; }
      });
    };
    const soltar = (e: PointerEvent) => {
      dom.removeEventListener("pointermove", mover);
      dom.removeEventListener("pointerup", soltar);
      if (!mexeu) return;
      // soltou fora da banda: passa para a banda que está embaixo do mouse
      if (sel.length === 1) {
        const it1 = sel[0];
        const debaixo = document.elementsFromPoint(e.clientX, e.clientY).find((x) => x.classList && x.classList.contains("dz-area")) as HTMLElement | undefined;
        const lbAlvo = debaixo && areas.current.get(debaixo);
        if (debaixo && lbAlvo && lbAlvo.banda !== lb.banda) {
          const rc = debaixo.getBoundingClientRect();
          lb.banda.itens = lb.banda.itens.filter((x) => x !== it1);
          it1.y = Math.max(0, arred((e.clientY - rc.top) / s - 1));
          lbAlvo.banda.itens.push(it1);
          setBandaSel(lbAlvo);
        } else if (it1.y < 0 || it1.y > lb.banda.altura) {
          it1.y = Math.min(Math.max(0, it1.y), Math.max(lb.banda.altura - it1.h, 0));
        }
      }
      r();
    };
    dom.addEventListener("pointermove", mover);
    dom.addEventListener("pointerup", soltar);
  }
  function iniciarRedim(ev: PE<HTMLDivElement>, it: Item) {
    ev.stopPropagation(); ev.preventDefault();
    const x0 = ev.clientX, y0 = ev.clientY, w0 = it.w, h0 = it.h;
    const h = ev.currentTarget;
    const dom = h.parentElement as HTMLElement;
    h.setPointerCapture(ev.pointerId);
    guardar();
    const s = esc();
    const mover = (e: PointerEvent) => {
      it.w = Math.max(0.5, arred(w0 + (e.clientX - x0) / s));
      it.h = Math.max(0.3, arred(h0 + (e.clientY - y0) / s));
      dom.style.width = it.w * s + "px"; dom.style.height = it.h * s + "px";
    };
    const soltar = () => { h.removeEventListener("pointermove", mover); h.removeEventListener("pointerup", soltar); r(); };
    h.addEventListener("pointermove", mover);
    h.addEventListener("pointerup", soltar);
  }
  function ajustarBanda(ev: PE<HTMLDivElement>, lb: LB) {
    ev.preventDefault();
    const al = ev.currentTarget;
    al.setPointerCapture(ev.pointerId);
    const y0 = ev.clientY, h0 = lb.banda.altura;
    const area = al.previousElementSibling as HTMLElement, alt = al.parentElement?.querySelector(".dz-banda-alt");
    let mexeu = false;
    const s = esc();
    const mover = (e: PointerEvent) => {
      if (!mexeu) { guardar(); mexeu = true; }
      lb.banda.altura = Math.max(0, r1(h0 + (e.clientY - y0) / s));
      area.style.height = Math.max(lb.banda.altura * s, 2) + "px";
      if (alt) alt.textContent = r1(lb.banda.altura) + " mm";
    };
    const soltar = () => { al.removeEventListener("pointermove", mover); al.removeEventListener("pointerup", soltar); if (mexeu) r(); };
    al.addEventListener("pointermove", mover);
    al.addEventListener("pointerup", soltar);
  }

  // ------------------------------------------------------------------ tela
  if (erro) {
    return createPortal(<div className="dz" role="dialog" aria-label="Editor de layout de impressão">
      <div className="dz-carregando">{erro}<button className="btn" onClick={fechar}>Fechar</button></div>
    </div>, document.body);
  }
  if (!info || !d || !pilha.length) {
    return createPortal(<div className="dz" role="dialog" aria-label="Editor de layout de impressão"><div className="dz-carregando">Carregando o layout…</div></div>, document.body);
  }

  const sec = secao();
  const s = esc();
  const origem = ({ salvo: "layout salvo no painel", reportbuilder: "original do ReportBuilder", padrao: "layout padrão (tabela)" } as Record<string, string>)[info.origem] || "";

  const rotuloItem = (it: Item): string => {
    switch (it.tipo) {
      case "texto": return it.texto || "(texto)";
      case "campo": case "memo": {
        const outra = it.visao && (it.visao || "").toUpperCase() !== (sec.visao || "").toUpperCase();
        return (outra ? it.visao + "." : "") + (it.campo || "(campo)");
      }
      case "total": return (CALCS[it.calc] || "Soma") + "(" + (it.campo || "?") + ")";
      case "variavel": return "ƒ " + (it.nome || "cálculo");
      case "sistema": return ({ data: "dd/mm/aaaa", hora: "hh:mm", datahora: "dd/mm/aaaa hh:mm", pagina: "1", paginas: "9", pagina_desc: "Página 1", pagina_de: "1 de 9", pagina_x_de_y: "Página 1 de 9" } as Record<string, string>)[it.sistema] || "";
      default: return "";
    }
  };

  const itemDOM = (it: Item, lb: LB) => {
    const st: CSSProperties & Record<string, string> = { left: it.x * s + "px", top: it.y * s + "px", width: Math.max(it.w * s, 3) + "px", height: Math.max(it.h * s, 3) + "px" } as never;
    let cls = "dz-item t-" + it.tipo + (selecao.includes(it) ? " sel" : "");
    let corpo: ReactNode = null;
    let title: string | undefined;
    if (it.tipo === "linha") {
      cls += " pos-" + (it.posicao || "topo");
      st["--esp"] = Math.max((it.espessura || 0.75) * PT_MM * s, 1) + "px";
      st["--cor"] = it.cor || "#000";
    } else if (it.tipo === "retangulo") {
      st.borderColor = it.cor || "#000";
      st.borderWidth = Math.max((it.espessura || 0.75) * PT_MM * s, 1) + "px";
      if (it.fundo) st.background = it.fundo;
      if (it.forma === "arredondado") st.borderRadius = Math.min(it.w, it.h) * 0.12 * s + "px";
      if (it.forma === "elipse") st.borderRadius = "50%";
    } else if (it.tipo === "grade") {
      const cols: Item[] = it.colunas || [];
      const fator = it.w / (cols.reduce((a: number, c: Item) => a + (c.largura || 0), 0) || 1);
      const f = it.fonte || {};
      const alt = Math.max((it.alt_linha || 5) * s, 3);
      const cel = (c: Item, i: number, cab: boolean): ReactNode => (
        <div key={i} className="dz-grade-cel" style={{ width: c.largura * fator * s + "px", height: alt + "px", textAlign: ({ e: "left", c: "center", d: "right" } as Record<string, CSSProperties["textAlign"]>)[c.alin || "e"],
          fontWeight: cab ? 700 : 400, background: cab && it.cab_fundo ? it.cab_fundo : undefined, borderColor: it.bordas !== false ? it.cor_borda || "#999" : "transparent", lineHeight: alt + "px" }}>
          {cab ? c.titulo || c.campo : c.campo}
        </div>);
      st.fontFamily = familia(f.nome);
      st.fontSize = Math.max((f.tam || 8) * PT_MM * s, 4) + "px";
      corpo = <>
        {it.cabecalho !== false && <div className="dz-grade-lin">{cols.map((c, i) => cel(c, i, true))}</div>}
        {[0, 1].map((n) => <div key={n} className="dz-grade-lin dados">{cols.map((c, i) => cel(c, i, false))}</div>)}
        <span className="dz-grade-vis">{"▦ " + (it.visao || "(escolha a visão)")}</span>
      </>;
      title = "Tabela: lista as linhas de " + (it.visao || "?");
    } else if (it.tipo === "sub") {
      corpo = <><strong>Sub-relatório</strong><span>{" " + ((it.secao || {}).visao || "")}</span></>;
      title = "Duplo clique para editar o sub-relatório";
    } else {
      const f = it.fonte || {};
      corpo = rotuloItem(it);
      st.fontFamily = familia(f.nome);
      st.fontSize = Math.max((f.tam || 10) * PT_MM * s, 4) + "px";
      st.fontWeight = f.n ? "700" : "400";
      st.fontStyle = f.i ? "italic" : "normal";
      st.textDecoration = f.s ? "underline" : "none";
      st.color = f.cor || "#000";
      st.textAlign = ({ e: "left", c: "center", d: "right" } as Record<string, CSSProperties["textAlign"]>)[it.alin || "e"];
      st.whiteSpace = it.quebra ? "pre-wrap" : "pre";
      if (it.fundo) st.background = it.fundo;
      if (it.auto) cls += " auto";
    }
    return (
      <div key={it._k} className={cls} style={st} title={title}
        ref={(e) => { if (e) domItens.current.set(it, e); else domItens.current.delete(it); }}
        onPointerDown={(ev) => iniciarArraste(ev, it, lb)}
        onDoubleClick={it.tipo === "sub" ? (ev) => { ev.stopPropagation(); entrarSub(it); } : undefined}>
        {corpo}
        {selecao.length === 1 && selecao[0] === it && <div className="dz-alca" onPointerDown={(ev) => iniciarRedim(ev, it)} />}
      </div>
    );
  };

  const bandaDOM = (lb: LB, i: number) => (
    <div key={i} className={"dz-banda" + (bandaSel && bandaSel.banda === lb.banda ? " sel" : "") + (lb.banda.visivel === false ? " invisivel" : "")}>
      <div className="dz-banda-cab" onClick={() => { setBandaSel(lb); setSelecao([]); }}>{lb.rot}<span className="dz-banda-alt">{r1(lb.banda.altura) + " mm"}</span></div>
      <div className="dz-area" style={{ height: Math.max(lb.banda.altura * s, 2) + "px", backgroundSize: `${5 * s}px ${5 * s}px` }}
        ref={(e) => { if (e) areas.current.set(e, lb); }}
        onPointerDown={(e) => {
          if (e.target !== e.currentTarget) return;
          const p = posMM(e, e.currentTarget);
          if (pendente) { novoItem(pendente, lb.banda, p.x, p.y); setPendente(null); return; }
          setBandaSel(lb); setSelecao([]);
        }}
        onDragOver={(e: DragEvent<HTMLDivElement>) => { if (e.dataTransfer.types.includes("text/x-campo")) { e.preventDefault(); e.currentTarget.classList.add("alvo"); } }}
        onDragLeave={(e) => e.currentTarget.classList.remove("alvo")}
        onDrop={(e) => {
          e.currentTarget.classList.remove("alvo");
          const raw = e.dataTransfer.getData("text/x-campo");
          if (!raw) return;
          e.preventDefault();
          const c = JSON.parse(raw), p = posMM(e, e.currentTarget);
          novoItem("campo", lb.banda, p.x, p.y, { campo: c.campo, visao: c.visao === sec.visao ? null : c.visao });
        }}>
        {lb.banda.itens.map((it) => itemDOM(it, lb))}
      </div>
      <div className="dz-banda-ajuste" title="Arraste para mudar a altura da banda" onPointerDown={(e) => ajustarBanda(e, lb)} />
    </div>
  );

  const regua: ReactNode[] = [];
  for (let mm = 0; mm <= largUtil(); mm += 10) {
    regua.push(<span key={mm} className={mm % 50 !== 0 ? "menor" : undefined} style={{ left: mm * s + "px" }}>{mm % 50 === 0 ? String(mm / 10) : ""}</span>);
  }

  // ------------------------------------------------------------------ painel de propriedades
  const mudou = (fn: () => void) => { guardar(); fn(); r(); };
  const num = (valor: number, aoMudar: (v: number) => void, passo = "0.1") =>
    <Nativo type="number" step={passo} valor={String(r1(valor || 0))} aoMudar={(v) => mudou(() => aoMudar(parseFloat(v || "0") || 0))} />;
  const sel = (opcoes: [string, string][], valor: unknown, aoMudar: (v: string) => void) => (
    <select value={opcoes.some(([v]) => String(v) === String(valor ?? "")) ? String(valor ?? "") : opcoes[0]?.[0]} onChange={(e) => mudou(() => aoMudar(e.target.value))}>
      {opcoes.map(([v, rr]) => <option key={v} value={v}>{rr}</option>)}
    </select>
  );
  const chk = (rot: string, valor: unknown, aoMudar: (v: boolean) => void) =>
    <label className="dz-chk"><input type="checkbox" checked={!!valor} onChange={(e) => mudou(() => aoMudar(e.target.checked))} />{" " + rot}</label>;
  const txt = (valor: string, aoMudar: (v: string) => void, multi?: number, cls?: string) => {
    const props = {
      value: valor || "", className: cls,
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { if (!guardouTxt.current) { guardar(); guardouTxt.current = true; } aoMudar(e.target.value); r(); },
      onBlur: () => { guardouTxt.current = false; },
    };
    return multi ? <textarea rows={multi} {...props} /> : <input {...props} />;
  };
  const cor = (valor: string, aoMudar: (v: string) => void, extra?: React.InputHTMLAttributes<HTMLInputElement>) =>
    <Nativo type="color" valor={valor} aoMudar={(v) => mudou(() => aoMudar(v))} {...extra} />;
  const camposOpcoes = (visao?: string | null): [string, string][] => [["", "(escolha)"] as [string, string]].concat((info.campos[visao || sec.visao || ""] || []).map((c) => [c, c]));
  const visoesOpcoes = (padrao: string): [string, string][] => [["", padrao] as [string, string]].concat((info.visoes || []).map((v) => [v.nome, v.nome]));

  function painelDir(): ReactNode {
    if (selecao.length > 1) {
      const ref = selecao[0];
      const b = (rr: string, fn: () => void) => <button key={rr} type="button" className="btn pequeno" onClick={() => mudou(fn)}>{rr}</button>;
      return <>
        <div className="dz-sec">{`${selecao.length} itens selecionados`}</div>
        <div className="dz-botoes">
          {b("Alinhar à esquerda", () => selecao.forEach((i) => (i.x = ref.x)))}
          {b("Alinhar à direita", () => selecao.forEach((i) => (i.x = r1(ref.x + ref.w - i.w))))}
          {b("Alinhar no topo", () => selecao.forEach((i) => (i.y = ref.y)))}
          {b("Mesma largura", () => selecao.forEach((i) => (i.w = ref.w)))}
          {b("Mesma altura", () => selecao.forEach((i) => (i.h = ref.h)))}
        </div>
        {selecao.every((i) => i.fonte) && <>
          <Prop rot="Tamanho da fonte">{num(ref.fonte.tam, (v) => selecao.forEach((i) => (i.fonte.tam = v)), "0.5")}</Prop>
          {chk("Negrito", ref.fonte.n, (v) => selecao.forEach((i) => (i.fonte.n = v)))}
        </>}
        <button className="btn pequeno perigo" onClick={apagarSel}>Apagar selecionados</button>
      </>;
    }
    if (selecao.length === 1) return propsItem(selecao[0]);
    if (bandaSel) return propsBanda(bandaSel);
    return propsSecao(false);
  }

  function propsItem(it: Item): ReactNode {
    const nomes: Record<string, string> = { texto: "Texto", campo: "Campo", memo: "Campo (várias linhas)", total: "Total", variavel: "Cálculo (variável)", sistema: "Data / página", linha: "Linha", retangulo: "Retângulo", sub: "Sub-relatório", grade: "Tabela" };
    const grupos: [string, string][] = (sec.grupos || []).map((g, i) => [String(i), `Grupo ${i + 1} (${g.campo})`]);
    return <div key={it._k} style={{ display: "contents" }}>
      <div className="dz-sec">{nomes[it.tipo] || it.tipo}</div>
      {it.tipo === "texto" && <Prop rot="Texto">{txt(it.texto, (v) => (it.texto = v), 3)}</Prop>}
      {it.tipo === "grade" && propsGrade(it)}
      {["campo", "memo", "total"].includes(it.tipo) && <>
        <Prop rot="Visão">{sel(visoesOpcoes("(a desta seção" + (sec.visao ? ": " + sec.visao : "") + ")"), it.visao || "", (v) => (it.visao = v || null))}</Prop>
        <Prop rot="Campo">{sel(camposOpcoes(it.visao), it.campo, (v) => (it.campo = v))}</Prop>
      </>}
      {it.tipo === "total" && <>
        <Prop rot="Cálculo">{sel(Object.entries(CALCS), it.calc, (v) => (it.calc = v))}</Prop>
        <p className="dz-nota">No rodapé de grupo, soma as linhas do grupo; no sumário, o relatório todo.</p>
      </>}
      {it.tipo === "sistema" && <Prop rot="Mostrar">{sel(Object.entries(SISTEMA), it.sistema, (v) => (it.sistema = v))}</Prop>}
      {it.tipo === "variavel" && <>
        <Prop rot="Nome">{txt(it.nome, (v) => (it.nome = v.replace(/[^\w]/g, "")))}</Prop>
        <Prop rot="Cálculo (RAP / Pascal)">{txt(it.codigo, (v) => (it.codigo = v), 8, "dz-codigo")}</Prop>
        <p className="dz-nota">{"Ex.: Value := Value + Visao['Campo'];  Use Visao['Apelido ou CAMPO'], Variable1.Value, if/then/else, FormatFloat, Copy, Trim."}</p>
        <Prop rot="Tipo do valor">{sel([["numero", "Número"], ["texto", "Texto"], ["data", "Data"], ["logico", "Sim/Não"]], it.tipo_dado, (v) => (it.tipo_dado = v))}</Prop>
        <Prop rot="Calcula">{sel([["percurso", "A cada linha"], ["antes_rodape_grupo", "Antes do rodapé do grupo"], ["antes_cab_grupo", "Antes do cabeçalho do grupo"], ["fim", "No fim"]], it.calc_tipo, (v) => (it.calc_tipo = v))}</Prop>
        <Prop rot="Zera">{sel([["fim", "Nunca (acumula no relatório)"], ["inicio_grupo", "No início do grupo"], ["fim_grupo", "No fim do grupo"]], it.reset_tipo, (v) => (it.reset_tipo = v))}</Prop>
        {grupos.length > 0 && <Prop rot="Grupo">{sel([["", "(qualquer)"] as [string, string]].concat(grupos), it.reset_grupo ?? "", (v) => { it.reset_grupo = v === "" ? null : +v; it.calc_grupo = it.reset_grupo; })}</Prop>}
        <Prop rot="Ordem">{num(it.ordem, (v) => (it.ordem = v), "1")}</Prop>
      </>}
      {["campo", "memo", "total", "variavel", "sistema"].includes(it.tipo) && (
        <Prop rot="Formato" dica="Formato do Delphi: #,0.00 (números) · dd/mm/yyyy (datas)">
          <Nativo valor={it.formato || ""} list="dz-formatos" aoMudar={(v) => { guardar(); it.formato = v; }} />
        </Prop>
      )}
      {it.fonte && <>
        <div className="dz-sec2">Fonte</div>
        <div className="dz-linha">
          {sel(FONTES.concat(FONTES.includes(it.fonte.nome) ? [] : [it.fonte.nome]).map((x) => [x, x]), it.fonte.nome, (v) => (it.fonte.nome = v))}
          {num(it.fonte.tam, (v) => (it.fonte.tam = Math.max(3, v)), "0.5")}
        </div>
        {it.tipo !== "grade" && <><div className="dz-botoes">
          {([["n", "N", "Negrito"], ["i", "I", "Itálico"], ["s", "S", "Sublinhado"]] as [string, string, string][]).map(([k, rr, t]) => (
            <button key={k} type="button" className={"btn pequeno" + (it.fonte[k] ? " ativo" : "")} title={t} onClick={() => mudou(() => { it.fonte[k] = !it.fonte[k]; })}>{rr}</button>
          ))}
          {([["e", "⇤ Esq."], ["c", "Centro"], ["d", "Dir. ⇥"]] as [string, string][]).map(([k, rr]) => (
            <button key={k} type="button" className={"btn pequeno" + ((it.alin || "e") === k ? " ativo" : "")} onClick={() => mudou(() => { it.alin = k; })}>{rr}</button>
          ))}
          {cor(it.fonte.cor || "#000000", (v) => { it.fonte.cor = v; }, { title: "Cor do texto" })}
        </div>
        {chk("Ajustar largura ao texto", it.auto, (v) => (it.auto = v))}
        {chk("Quebrar linhas", it.quebra, (v) => (it.quebra = v))}
        {["campo", "memo"].includes(it.tipo) && chk("Esticar a banda se o texto for grande", it.esticar, (v) => (it.esticar = v))}
        {["campo", "memo", "total", "variavel"].includes(it.tipo) && chk("Em branco quando zero", it.branco_zero, (v) => (it.branco_zero = v))}
        <div className="dz-linha">
          {chk("Fundo", !!it.fundo, (v) => (it.fundo = v ? "#eeeeee" : null))}
          {cor(it.fundo || "#ffffff", (v) => { it.fundo = v; }, { disabled: !it.fundo })}
        </div>
        </>}
        {it.tipo === "grade" && <div className="dz-linha"><span className="dz-nota" style={{ margin: 0 }}>Cor do texto</span>{cor(it.fonte.cor || "#000000", (v) => { it.fonte.cor = v; })}</div>}
      </>}
      {it.tipo === "linha" && <>
        <Prop rot="Posição na caixa">{sel([["topo", "Em cima"], ["base", "Embaixo"], ["esq", "Esquerda (vertical)"], ["dir", "Direita (vertical)"]], it.posicao, (v) => (it.posicao = v))}</Prop>
        <Prop rot="Espessura (pt)">{num(it.espessura, (v) => (it.espessura = v), "0.25")}</Prop>
        {chk("Linha dupla", it.dupla, (v) => (it.dupla = v))}
      </>}
      {it.tipo === "retangulo" && <>
        <Prop rot="Forma">{sel([["retangulo", "Retângulo"], ["arredondado", "Cantos arredondados"], ["elipse", "Elipse"]], it.forma, (v) => (it.forma = v))}</Prop>
        <Prop rot="Borda (pt)">{num(it.espessura, (v) => (it.espessura = v), "0.25")}</Prop>
        <div className="dz-linha">{chk("Fundo", !!it.fundo, (v) => (it.fundo = v ? "#eeeeee" : null))}{cor(it.fundo || "#ffffff", (v) => { it.fundo = v; })}</div>
      </>}
      {["linha", "retangulo"].includes(it.tipo) && <Prop rot="Cor">{cor(it.cor || "#000000", (v) => { it.cor = v; })}</Prop>}
      {it.tipo === "sub" && <>
        <Prop rot="Visão do sub-relatório">{sel(visoesOpcoes("(nenhuma)"), (it.secao || {}).visao || "", (v) => (it.secao.visao = v || null))}</Prop>
        <button type="button" className="btn pequeno primario" onClick={() => entrarSub(it)}>Editar sub-relatório</button>
        <p className="dz-nota">Imprime as linhas da visão ligadas à linha atual (como no ReportBuilder). A banda cresce conforme o número de linhas.</p>
      </>}
      <div className="dz-sec2">Posição e tamanho (mm)</div>
      <div className="dz-grade4">
        <Prop rot="X">{num(it.x, (v) => (it.x = v))}</Prop>
        <Prop rot="Y">{num(it.y, (v) => (it.y = v))}</Prop>
        <Prop rot="Largura">{num(it.w, (v) => (it.w = Math.max(0.5, v)))}</Prop>
        <Prop rot="Altura">{num(it.h, (v) => (it.h = Math.max(0.3, v)))}</Prop>
      </div>
      <div className="dz-botoes">
        <button className="btn pequeno" onClick={() => duplicar([it], 2, 2)}>Duplicar</button>
        <button className="btn pequeno perigo" onClick={apagarSel}>Apagar</button>
      </div>
    </div>;
  }

  function propsGrade(it: Item): ReactNode {
    const cols: Item[] = it.colunas || (it.colunas = []);
    const disponiveis = (info!.campos[it.visao || ""] || []).filter((c) => !cols.some((x) => x.campo === c));
    const nums = (info!.numeros || {})[it.visao || ""] || [];
    const nova = (c: string) => ({ campo: c, titulo: c, largura: 25, alin: nums.includes(c) ? "d" : "e", formato: nums.includes(c) ? "#,0.00;-#,0.00" : "" });
    const mover = (i: number, d: number) => mudou(() => { const j = i + d; if (j < 0 || j >= cols.length) return; [cols[i], cols[j]] = [cols[j], cols[i]]; });
    const outras = (info!.visoes || []).filter((v) => v.nome !== sec.visao);
    return <>
      <Prop rot="Visão (de onde vêm as linhas)">{sel([["", "(escolha)"] as [string, string]].concat(outras.map((v) => [v.nome, v.nome + (v.mestre ? " · ligada a " + v.mestre : "")])), it.visao || "",
        (v) => { it.visao = v || null; it.colunas = (info!.campos[v] || []).slice(0, 4).map(nova); })}</Prop>
      <p className="dz-nota">{it.visao && outras.find((v) => v.nome === it.visao)?.mestre ? "Lista as linhas ligadas à linha atual de " + outras.find((v) => v.nome === it.visao)!.mestre + "." : "Lista todas as linhas da visão."} A banda cresce conforme o número de linhas.</p>
      <div className="dz-sec2">Colunas</div>
      <div className="dz-grade-cols">
        {cols.map((c, i) => (
          <div key={c.campo + i} className="dz-grade-col">
            <div className="dz-linha">
              <code title={c.campo}>{c.campo}</code>
              <button type="button" className="btn pequeno" title="Subir" disabled={i === 0} onClick={() => mover(i, -1)}>↑</button>
              <button type="button" className="btn pequeno" title="Descer" disabled={i === cols.length - 1} onClick={() => mover(i, 1)}>↓</button>
              <button type="button" className="btn pequeno perigo" title="Tirar a coluna" onClick={() => mudou(() => cols.splice(i, 1))}>✕</button>
            </div>
            <div className="dz-linha">
              {txt(c.titulo, (v) => (c.titulo = v), undefined, "dz-grade-tit")}
              {num(c.largura, (v) => (c.largura = Math.max(1, v)), "1")}
              {sel([["e", "Esq."], ["c", "Centro"], ["d", "Dir."]], c.alin, (v) => (c.alin = v))}
            </div>
            <Nativo valor={c.formato || ""} list="dz-formatos" placeholder="formato (opcional)" aoMudar={(v) => { guardar(); c.formato = v; }} />
          </div>
        ))}
      </div>
      {disponiveis.length > 0 && <div className="dz-linha">
        <select value="" onChange={(e) => { const v = e.target.value; if (v) mudou(() => cols.push(nova(v))); }}>
          <option value="">+ Adicionar coluna…</option>
          {disponiveis.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button type="button" className="btn pequeno" onClick={() => mudou(() => disponiveis.forEach((c) => cols.push(nova(c))))}>Todas</button>
      </div>}
      <p className="dz-nota">A largura das colunas é proporcional: elas se ajustam à largura da tabela.</p>
      <Prop rot="Altura de cada linha (mm)">{num(it.alt_linha, (v) => (it.alt_linha = Math.max(2, v)), "0.5")}</Prop>
      {chk("Mostrar títulos das colunas", it.cabecalho !== false, (v) => (it.cabecalho = v))}
      {chk("Bordas", it.bordas !== false, (v) => (it.bordas = v))}
      <div className="dz-linha">
        {chk("Fundo dos títulos", !!it.cab_fundo, (v) => (it.cab_fundo = v ? "#e6ecf2" : null))}
        {cor(it.cab_fundo || "#e6ecf2", (v) => { it.cab_fundo = v; }, { disabled: !it.cab_fundo })}
        {cor(it.cor_borda || "#999999", (v) => { it.cor_borda = v; }, { title: "Cor das bordas", disabled: it.bordas === false })}
      </div>
    </>;
  }

  function propsBanda(lb: LB): ReactNode {
    const g = lb.tipo === "gcab" || lb.tipo === "grod" ? sec.grupos[lb.grupo!] : null;
    return <>
      <div className="dz-sec">{"Banda: " + lb.rot}</div>
      <Prop rot="Altura (mm)">{num(lb.banda.altura, (v) => (lb.banda.altura = Math.max(0, v)))}</Prop>
      {chk("Visível", lb.banda.visivel !== false, (v) => (lb.banda.visivel = v))}
      {lb.tipo === "detalhe" && chk("Altura dinâmica (cresce com sub-relatórios e textos longos)", lb.banda.dinamica !== false, (v) => (lb.banda.dinamica = v))}
      {g && <>
        <Prop rot="Quebrar quando mudar o campo">{sel(camposOpcoes(g.visao), g.campo, (v) => (g.campo = v))}</Prop>
        {chk("Cada grupo em nova página", g.nova_pagina, (v) => (g.nova_pagina = v))}
        <button className="btn pequeno perigo" onClick={() => {
          if (!confirm("Remover o grupo e as suas bandas?")) return;
          guardar(); sec.grupos.splice(lb.grupo!, 1); setBandaSel(null); r();
        }}>Remover este grupo</button>
      </>}
      <p className="dz-nota">Dica: clique num componente à esquerda e depois na banda, ou arraste um campo para cá.</p>
      {propsSecao(true)}
    </>;
  }

  function propsSecao(resumido: boolean): ReactNode {
    const principal = sec === d!.relatorio;
    const pg = d!.pagina;
    const atual = Object.keys(PAPEIS).find((k) => { const [w, h] = PAPEIS[k]; return (Math.abs(w - pg.largura) < 1 && Math.abs(h - pg.altura) < 1) || (Math.abs(h - pg.largura) < 1 && Math.abs(w - pg.altura) < 1); }) || "";
    const paisagem = pg.largura > pg.altura;
    return <>
      {!resumido && <>
        <div className="dz-sec">{principal ? "Relatório" : "Sub-relatório"}</div>
        <p className="dz-nota">Clique numa banda ou num item para ver as propriedades. Arraste para mover, use a alça do canto para redimensionar. Setas movem (Shift = 5 mm), Delete apaga, Ctrl+C/Ctrl+V copia, Ctrl+Z desfaz.</p>
      </>}
      <div className="dz-sec2">Dados</div>
      <Prop rot={principal ? "Visão principal (uma linha por detalhe)" : "Visão do sub-relatório"}>{sel(visoesOpcoes("(nenhuma - imprime uma vez)"), sec.visao || "", (v) => (sec.visao = v || null))}</Prop>
      <div className="dz-sec2">Bandas</div>
      {["titulo", "cabecalho", "sumario"].concat(principal ? ["rodape"] : []).map((t) => (
        <div key={t} style={{ display: "contents" }}>{chk(NOMES_BANDA[t], !!sec.bandas[t], (v) => {
          if (v) sec.bandas[t] = sec.bandas[t] || { altura: 8, visivel: true, dinamica: true, itens: [] };
          else if (!sec.bandas[t].itens.length || confirm("A banda tem itens. Remover mesmo assim?")) delete sec.bandas[t];
        })}</div>
      ))}
      <NovoGrupo opcoes={camposOpcoes(sec.visao)} adicionar={(campo) => {
        if (!campo) { alerta("Escolha o campo que separa os grupos."); return; }
        guardar();
        sec.grupos = sec.grupos || [];
        sec.grupos.push({ campo, visao: null, nova_pagina: false, cab: { altura: 6, visivel: true, dinamica: true, itens: [] }, rod: { altura: 0, visivel: true, dinamica: true, itens: [] } });
        r();
      }} />
      {principal && !resumido && <>
        <div className="dz-sec2">Página</div>
        <Prop rot="Papel">{sel([["", "Personalizado"] as [string, string]].concat(Object.keys(PAPEIS).map((k) => [k, k])), atual, (v) => {
          if (!PAPEIS[v]) return;
          const [w, h] = PAPEIS[v];
          pg.largura = paisagem ? h : w; pg.altura = paisagem ? w : h;
        })}</Prop>
        <Prop rot="Orientação">{sel([["retrato", "Retrato"], ["paisagem", "Paisagem"]], paisagem ? "paisagem" : "retrato", (v) => {
          if ((v === "paisagem") !== (pg.largura > pg.altura)) { const t = pg.largura; pg.largura = pg.altura; pg.altura = t; }
        })}</Prop>
        <Prop rot="Margens (mm)"><div className="dz-grade4">
          {([["sup", "Sup."], ["inf", "Inf."], ["esq", "Esq."], ["dir", "Dir."]] as [string, string][]).map(([k, rr]) => (
            <Prop key={k} rot={rr}>{num(pg.margens[k], (v) => (pg.margens[k] = Math.max(0, v)))}</Prop>
          ))}
        </div></Prop>
        {chk("Título antes do cabeçalho", sec.titulo_antes !== false, (v) => (sec.titulo_antes = v))}
        <Prop rot="Encaixe na grade">
          <select value={String(snap)} onChange={(e) => setSnap(parseFloat(e.target.value))}>
            <option value="0.5">0,5 mm</option><option value="1">1 mm</option><option value="0">livre</option>
          </select>
        </Prop>
      </>}
      {!principal && <button type="button" className="btn pequeno" onClick={() => { setPilha([d!.relatorio]); setSelecao([]); setBandaSel(null); }}>← Voltar ao relatório principal</button>}
    </>;
  }

  // ------------------------------------------------------------------ tabelas do banco
  const tabelas = d.tabelas || [];
  const salvarTabela = (t: Tabela, antiga?: Tabela) => {
    guardar();
    const lista = (d.tabelas || []).filter((x) => x !== antiga);
    lista.push(t);
    d.tabelas = lista;
    setInfo(comTabelas(info, lista));
    setJanela(null);
    r();
  };
  const removerTabela = (t: Tabela) => {
    const usados = contarUsos(d.relatorio, t.nome);
    if (!confirm(usados ? `${usados} item(ns) do layout usam a tabela ${t.nome}. Remover mesmo assim?` : `Remover a tabela ${t.nome} do layout?`)) return;
    guardar();
    d.tabelas = (d.tabelas || []).filter((x) => x !== t);
    setInfo(comTabelas(info, d.tabelas));
    r();
  };

  return createPortal(
    <div className={"dz" + (pendente ? " dz-inserindo" : "")} role="dialog" aria-label="Editor de layout de impressão">
      <div className="dz-topo">
        <div className="dz-tit"><strong>Layout de impressão</strong><span>{nome}</span><small>{origem}</small></div>
        <button type="button" className="btn pequeno primario" title="Salva o layout para todos os usuários (o PDF passa a sair assim)" disabled={!info.pode_editar} onClick={acaoSalvar}>Salvar</button>
        <button type="button" className="btn pequeno " title="Gera o PDF com este layout e os filtros atuais (sem salvar)" onClick={acaoPDF}>Visualizar PDF</button>
        <button type="button" className="btn pequeno " title="Desfazer (Ctrl+Z)" onClick={voltarAcao}>↶</button>
        <button type="button" className="btn pequeno " title="Refazer (Ctrl+Y)" onClick={refazerAcao}>↷</button>
        <select className="dz-sel" value="" onChange={(e) => mais(e.target.value)}>
          <option value="">Mais…</option>
          {info.tem_original && <option value="original">Recomeçar do original do ReportBuilder</option>}
          <option value="padrao">Recomeçar com layout em tabela</option>
          {info.pode_editar && <option value="rtm">Exportar .rtm (ReportBuilder)</option>}
          {info.pode_editar && <option value="rtm_importar">Importar .rtm…</option>}
          {info.tem_salvo && info.pode_editar && <option value="excluir">{"Apagar o layout salvo (voltar ao " + (info.tem_original ? "original do RB" : "PDF em tabela") + ")"}</option>}
        </select>
        <input ref={arqRtm} type="file" accept=".rtm" hidden onChange={(e) => importarRtm(e.target.files?.[0])} />
        <div className="dz-zoom">
          <button className="btn pequeno" onClick={() => setZoom((z) => Math.max(0.4, z - 0.1))}>−</button>
          <span>{Math.round(zoom * 100) + "%"}</span>
          <button className="btn pequeno" onClick={() => setZoom((z) => Math.min(3, z + 0.1))}>+</button>
        </div>
        <button type="button" className="btn pequeno " onClick={sair}>Fechar ✕</button>
      </div>
      {window.matchMedia("(max-width: 900px)").matches && <div className="dz-aviso">O editor de layout funciona melhor no computador (tela grande e mouse).</div>}
      <div className="dz-corpo">
        <div className="dz-esq">
          <div className="dz-sec">Componentes</div>
          <div className="dz-comps">
            {COMPONENTES.map(([t, rot, ic]) => (
              <button key={t} type="button" className={"dz-comp" + (pendente === t ? " ativo" : "")} data-tipo={t} title="Clique aqui e depois na banda onde quer colocar"
                onClick={() => setPendente((p) => (p === t ? null : t))}><span className="ic">{ic}</span><span>{rot}</span></button>
            ))}
          </div>
          <div className="dz-sec">Campos</div>
          <p className="dz-nota">Arraste um campo para uma banda.</p>
          <div className="dz-campos">
            {(info.visoes || []).map((v) => (
              <details key={v.nome} open={v.nome === (sec.visao || "") || !v.mestre}>
                <summary>{v.nome + (v.mestre ? " (detalhe de " + v.mestre + ")" : "")}</summary>
                {(info.campos[v.nome] || []).map((c) => (
                  <div key={c} className="dz-campo" draggable
                    onDragStart={(e) => { e.dataTransfer.setData("text/x-campo", JSON.stringify({ visao: v.nome, campo: c })); e.dataTransfer.effectAllowed = "copy"; }}
                    onDoubleClick={() => { if (bandaSel) novoItem("campo", bandaSel.banda, 2, 2, { campo: c, visao: v.nome }); }}>{c}</div>
                ))}
              </details>
            ))}
          </div>
          {info.pode_tabelas && <>
            <div className="dz-sec">Tabelas do banco</div>
            <p className="dz-nota">Traga campos de outras tabelas (ex.: endereço do cliente, dados da empresa). Eles aparecem em Campos para arrastar.</p>
            <div className="dz-tabelas">
              {tabelas.map((t) => (
                <div key={t.nome} className="dz-tabela-item">
                  <div><strong>{t.nome}</strong><span className="dz-nota">{`${t.tabela} · ${t.campos.length} campo(s)` + (t.mestre ? ` · ligada a ${t.mestre} por ${t.ligacoes.map(([a, b]) => a === b ? a : `${a} = ${b}`).join(", ")}` : " · sem ligação (1ª linha)")}</span></div>
                  <div className="dz-botoes">
                    <button type="button" className="btn pequeno" onClick={() => setJanela({ editar: t })}>Editar</button>
                    <button type="button" className="btn pequeno perigo" onClick={() => removerTabela(t)}>Remover</button>
                  </div>
                </div>
              ))}
            </div>
            <button type="button" className="btn pequeno primario dz-add-tabela" onClick={() => setJanela({})}>+ Adicionar tabela</button>
          </>}
        </div>
        <div className="dz-centro" ref={centro} onScroll={(e) => { rolagem.current = e.currentTarget.scrollTop; }}>
          <div className="dz-abas">
            {pilha.map((sx, i) => (
              <button key={i} type="button" className={"dz-aba" + (i === pilha.length - 1 ? " ativa" : "")}
                onClick={() => { setPilha(pilha.slice(0, i + 1)); setSelecao([]); setBandaSel(null); }}>{i === 0 ? "Principal" : "Sub: " + (sx.visao || "?")}</button>
            ))}
          </div>
          <div className="dz-pagina" style={{ width: largUtil() * s + "px" }}>
            <div className="dz-regua">{regua}</div>
            {listaBandas(sec).map(bandaDOM)}
          </div>
        </div>
        <div className="dz-dir">{painelDir()}</div>
      </div>
      <datalist id="dz-formatos">{FORMATOS.map((f) => <option key={f} value={f} />)}</datalist>
      {msgs.map((m) => <div key={m.id} className={"dz-msg " + m.tipo}>{m.msg}</div>)}
      {janela && <JanelaTabela info={info} existentes={tabelas} editar={janela.editar} fechar={() => setJanela(null)}
        salvar={(t) => salvarTabela(t, janela.editar)} />}
    </div>,
    document.body,
  );
}

/* lista de campos das visões, com as tabelas do banco do layout no lugar das antigas */
function comTabelas(info: Info, lista: Tabela[]): Info {
  const visoes = info.visoes.filter((v) => !v.tabela);
  const campos = { ...info.campos };
  info.visoes.filter((v) => v.tabela).forEach((v) => { delete campos[v.nome]; });
  lista.forEach((t) => {
    visoes.push({ nome: t.nome, mestre: t.mestre, tabela: t.tabela });
    campos[t.nome] = [...t.campos, ...t.ligacoes.map(([, b]) => b).filter((b) => !t.campos.includes(b))];
  });
  return { ...info, visoes, campos };
}
function contarUsos(sec: Secao, visao: string): number {
  let n = 0;
  const V = visao.toUpperCase();
  if ((sec.visao || "").toUpperCase() === V) n++;
  todasBandas(sec).forEach((b) => b.itens.forEach((i) => {
    if ((i.visao || "").toUpperCase() === V) n++;
    if (i.tipo === "sub" && i.secao) n += contarUsos(i.secao, visao);
  }));
  return n;
}

function NovoGrupo({ opcoes, adicionar }: { opcoes: [string, string][]; adicionar: (c: string) => void }) {
  const [v, setV] = useState("");
  return <label className="dz-prop"><span>Grupos (quebra por campo)</span>
    <div className="dz-linha">
      <select value={v} onChange={(e) => setV(e.target.value)}>{opcoes.map(([x, rr]) => <option key={x} value={x}>{rr === "(escolha)" ? "(campo do grupo)" : rr}</option>)}</select>
      <button type="button" className="btn pequeno" onClick={() => adicionar(v)}>Adicionar grupo</button>
    </div>
  </label>;
}

/* janela "Adicionar tabela": escolhe a tabela do banco, os campos e a ligação com uma visão do relatório */
function JanelaTabela({ info, existentes, editar, fechar, salvar }: {
  info: Info; existentes: Tabela[]; editar?: Tabela; fechar: () => void; salvar: (t: Tabela) => void;
}) {
  const [todas, setTodas] = useState<string[] | null>(null);
  const [filtro, setFiltro] = useState("");
  const [tabela, setTabela] = useState(editar?.tabela || "");
  const [campos, setCampos] = useState<{ campo: string; tipo: string }[] | null>(null);
  const [marcados, setMarcados] = useState<string[]>(editar?.campos || []);
  const [buscaCampo, setBuscaCampo] = useState("");
  const [nome, setNome] = useState(editar?.nome || "");
  const visoesLig = info.visoes.filter((v) => v.nome !== editar?.nome);
  const [mestre, setMestre] = useState<string>(editar ? editar.mestre || "" : (visoesLig[0]?.nome || ""));
  const [ligacoes, setLigacoes] = useState<[string, string][]>(editar?.ligacoes || []);
  const [erro, setErro] = useState("");

  useEffect(() => { api<{ tabelas: string[] }>("/api/esquema").then((x) => setTodas(x.tabelas)).catch((e) => setErro(e.message)); }, []);
  useEffect(() => {
    if (!tabela) { setCampos(null); return; }
    let vivo = true;
    setCampos(null);
    api<{ campos: { campo: string; tipo: string }[] }>("/api/esquema?tabela=" + encodeURIComponent(tabela))
      .then((x) => { if (vivo) setCampos(x.campos.map((c) => ({ campo: c.campo.toUpperCase(), tipo: c.tipo }))); })
      .catch((e) => vivo && setErro(e.message));
    return () => { vivo = false; };
  }, [tabela]);
  // sugere a ligação pelos campos com o mesmo nome (ex.: CODCFO = CODCFO)
  useEffect(() => {
    if (!campos || !mestre || ligacoes.length) return;
    const daVisao = info.campos[mestre] || [];
    const nomes = campos.map((c) => c.campo);
    const iguais: [string, string][] = daVisao.filter((c) => nomes.includes(c) && /^(COD|ID|NUM)/.test(c)).map((c) => [c, c]);
    // também FILIAL = CODFILIAL, CLIENTE = CODCLIENTE...
    if (!iguais.length) daVisao.forEach((c) => { if (!/^(COD|ID|NUM)/.test(c) && nomes.includes("COD" + c)) iguais.push([c, "COD" + c]); });
    if (iguais.length) setLigacoes(iguais.slice(0, 2));
  }, [campos, mestre]);  // eslint-disable-line react-hooks/exhaustive-deps

  const escolherTabela = (t: string) => {
    setTabela(t); setMarcados([]); setLigacoes([]);
    if (!editar) {
      let n = t, i = 2;
      while (info.visoes.some((v) => v.nome.toUpperCase() === n.toUpperCase())) n = `${t}_${i++}`;
      setNome(n);
    }
  };
  const lista = (todas || []).filter((t) => !filtro || t.toUpperCase().includes(filtro.toUpperCase())).slice(0, 300);
  const camposVis = (campos || []).filter((c) => !buscaCampo || c.campo.includes(buscaCampo.toUpperCase()));
  const camposMestre = info.campos[mestre] || [];
  const nomeLimpo = nome.replace(/[^\w ]/g, "").trim();
  const repetido = !!nomeLimpo && info.visoes.some((v) => v.nome.toUpperCase() === nomeLimpo.toUpperCase() && v.nome !== editar?.nome) ||
    existentes.some((t) => t !== editar && t.nome.toUpperCase() === nomeLimpo.toUpperCase());
  const ligValidas = ligacoes.filter(([a, b]) => a && b);
  const pronto = !!tabela && marcados.length > 0 && !!nomeLimpo && !repetido && (!mestre || ligValidas.length > 0);

  return (
    <div className="modal-fundo dz-janela" onClick={(e) => { if (e.target === e.currentTarget) fechar(); }}>
      <div className="modal" role="dialog" aria-label="Adicionar tabela do banco" style={{ width: "min(860px, 96vw)" }}
        onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); fechar(); } }}>
        <div className="modal-cab"><h2>{editar ? "Editar tabela · " + editar.nome : "Adicionar tabela do banco"}</h2><button className="btn pequeno" onClick={fechar}>Fechar ✕</button></div>
        <div className="modal-corpo">
          {erro && <div className="aviso erro">{erro}</div>}
          <div className="dz-tab-grade">
            <section>
              <h3>1. Tabela</h3>
              <input className="campo" placeholder="Buscar tabela (ex.: FCFO, GFILIAL)" value={filtro} onChange={(e) => setFiltro(e.target.value)} disabled={!!editar} />
              <div className="dz-picker" role="listbox" aria-label="Tabelas">
                {todas === null ? <p className="nota">Carregando…</p> : lista.map((t) => (
                  <button key={t} type="button" role="option" aria-selected={t === tabela} className={"dz-opcao" + (t === tabela ? " ativa" : "")}
                    disabled={!!editar && t !== tabela} onClick={() => escolherTabela(t)}>{t}</button>
                ))}
              </div>
            </section>
            <section>
              <h3>2. Campos {tabela && <span className="nota">{`· ${marcados.length} marcado(s)`}</span>}</h3>
              {!tabela ? <p className="nota">Escolha uma tabela à esquerda.</p> : campos === null ? <p className="nota">Carregando…</p> : <>
                <div className="dz-linha">
                  <input className="campo" placeholder="Buscar campo" value={buscaCampo} onChange={(e) => setBuscaCampo(e.target.value)} />
                  <button type="button" className="btn pequeno" onClick={() => setMarcados([...new Set([...marcados, ...camposVis.map((c) => c.campo)])])}>Marcar todos</button>
                  <button type="button" className="btn pequeno" onClick={() => setMarcados(marcados.filter((m) => !camposVis.some((c) => c.campo === m)))}>Limpar</button>
                </div>
                <div className="dz-picker">
                  {camposVis.map((c) => (
                    <label key={c.campo} className="check dz-opcao-campo">
                      <input type="checkbox" checked={marcados.includes(c.campo)}
                        onChange={(e) => setMarcados(e.target.checked ? [...marcados, c.campo] : marcados.filter((m) => m !== c.campo))} />
                      {" " + c.campo} <i>{c.tipo}</i>
                    </label>
                  ))}
                </div>
              </>}
            </section>
          </div>
          <section className="dz-tab-lig">
            <h3>3. Ligação com o relatório</h3>
            <div className="form-grade">
              <label>Nome no layout<input className="campo" value={nome} onChange={(e) => setNome(e.target.value)} disabled={!!editar} placeholder="ex.: CLIENTE" /></label>
              <label>Ligar com a visão
                <select className="campo" value={mestre} onChange={(e) => { setMestre(e.target.value); setLigacoes([]); }}>
                  <option value="">(sem ligação: usa a primeira linha da tabela)</option>
                  {visoesLig.map((v) => <option key={v.nome} value={v.nome}>{v.nome}</option>)}
                </select>
              </label>
            </div>
            {mestre && <>
              <p className="nota">Para cada linha de {mestre}, o layout usa a linha da tabela em que os campos abaixo são iguais (ex.: CODCFO do movimento = CODCFO do cliente).</p>
              {ligacoes.map(([a, b], i) => (
                <div key={i} className="dz-linha dz-par-lig">
                  <select className="campo" value={a} onChange={(e) => setLigacoes(ligacoes.map((x, k) => (k === i ? [e.target.value, x[1]] : x)))}>
                    <option value="">{`(campo de ${mestre})`}</option>{camposMestre.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <span>=</span>
                  <select className="campo" value={b} onChange={(e) => setLigacoes(ligacoes.map((x, k) => (k === i ? [x[0], e.target.value] : x)))}>
                    <option value="">{`(campo de ${tabela || "tabela"})`}</option>{(campos || []).map((c) => <option key={c.campo} value={c.campo}>{c.campo}</option>)}
                  </select>
                  <button type="button" className="btn pequeno" onClick={() => setLigacoes(ligacoes.filter((_, k) => k !== i))}>Remover</button>
                </div>
              ))}
              {ligacoes.length < 5 && <button type="button" className="btn pequeno" onClick={() => setLigacoes([...ligacoes, ["", ""]])}>+ Campo de ligação</button>}
              <p className="nota">Para listar várias linhas (ex.: todos os títulos do cliente), use o componente Tabela com esta visão.</p>
            </>}
            {!mestre && <p className="nota">Sem ligação, o layout mostra os campos da primeira linha da tabela (bom para dados fixos, como os da empresa).</p>}
            {repetido && <div className="aviso atencao">Já existe uma visão com esse nome. Escolha outro nome.</div>}
          </section>
        </div>
        <div className="modal-rodape">
          <span className="nota">{!tabela ? "Escolha a tabela." : !marcados.length ? "Marque pelo menos um campo." : mestre && !ligValidas.length ? "Escolha os campos de ligação." : ""}</span>
          <button type="button" className="btn" onClick={fechar}>Cancelar</button>
          <button type="button" className="btn primario" disabled={!pronto}
            onClick={() => salvar({ nome: nomeLimpo, tabela, campos: marcados, mestre: mestre || null, ligacoes: mestre ? ligValidas : [] })}>
            {editar ? "Salvar tabela" : "Adicionar tabela"}
          </button>
        </div>
      </div>
    </div>
  );
}
