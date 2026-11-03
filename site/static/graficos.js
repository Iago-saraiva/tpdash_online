/* Gráficos SVG do TP DASH - sem dependências externas (funciona sem internet).
   Barras, colunas (agrupadas), linhas/área e rosca, com tooltip, legenda e clique para filtrar. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const nfInt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const F = {
    moeda: (v) => "R$ " + nf2.format(v || 0),
    inteiro: (v) => nfInt.format(v || 0),
    numero: (v) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 }).format(v || 0),
    compacto(v, moeda) {
      const a = Math.abs(v || 0);
      let s;
      if (a >= 1e9) s = (v / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " bi";
      else if (a >= 1e6) s = (v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mi";
      else if (a >= 1e3) s = (v / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mil";
      else s = nfInt.format(v || 0);
      return (moeda ? "R$ " : "") + s;
    },
    mes(r) {
      if (/^\d{4}-\d{2}$/.test(r)) {
        const m = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"][+r.slice(5) - 1];
        return m + "/" + r.slice(2, 4);
      }
      return r;
    },
  };

  function el(tag, attrs, pai) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (pai) pai.appendChild(e);
    return e;
  }
  function txt(tag, attrs, texto, pai) {
    const e = el(tag, attrs, pai);
    e.textContent = texto;
    return e;
  }
  function cor(i) {
    return `var(--serie-${(i % 8) + 1})`;
  }

  /* escala "bonita" para o eixo */
  function escala(max, min) {
    min = Math.min(0, min || 0);
    if (max <= min) max = min + 1;
    const bruto = (max - min) / 4;
    const pot = Math.pow(10, Math.floor(Math.log10(bruto)));
    const passo = [1, 2, 2.5, 5, 10].map((m) => m * pot).find((p) => p >= bruto);
    const ini = Math.floor(min / passo) * passo;
    const fim = Math.ceil(max / passo) * passo;
    const ticks = [];
    for (let v = ini; v <= fim + passo / 2; v += passo) ticks.push(+v.toFixed(10));
    return { ini, fim, ticks };
  }

  /* tooltip único compartilhado */
  let tip;
  function tooltip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "gtip";
      tip.setAttribute("role", "status");
      document.body.appendChild(tip);
    }
    return tip;
  }
  function mostrarTip(ev, titulo, linhas) {
    const t = tooltip();
    t.replaceChildren();
    const h = document.createElement("div");
    h.className = "gtip-tit";
    h.textContent = titulo;
    t.appendChild(h);
    for (const l of linhas) {
      const r = document.createElement("div");
      r.className = "gtip-lin";
      if (l.cor) {
        const k = document.createElement("span");
        k.className = "gtip-key";
        k.style.background = l.cor;
        r.appendChild(k);
      }
      const v = document.createElement("strong");
      v.textContent = l.valor;
      r.appendChild(v);
      if (l.nome) {
        const n = document.createElement("span");
        n.className = "gtip-nome";
        n.textContent = l.nome;
        r.appendChild(n);
      }
      t.appendChild(r);
    }
    t.style.display = "block";
    const w = t.offsetWidth, hgt = t.offsetHeight;
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - 14;
    if (y + hgt > window.innerHeight - 8) y = ev.clientY - hgt - 14;
    t.style.left = x + "px";
    t.style.top = y + "px";
  }
  function esconderTip() {
    if (tip) tip.style.display = "none";
  }

  function legenda(cont, series, tipo) {
    if (series.length < 2) return;
    const lg = document.createElement("div");
    lg.className = "glegenda";
    series.forEach((s, i) => {
      const it = document.createElement("span");
      const k = document.createElement("span");
      k.className = tipo === "linha" ? "glk-linha" : "glk-barra";
      k.style.background = cor(i);
      it.appendChild(k);
      it.appendChild(document.createTextNode(s.nome));
      lg.appendChild(it);
    });
    cont.appendChild(lg);
  }

  function preparar(cont) {
    cont.replaceChildren();
    cont.classList.add("gcont");
    const w = Math.max(cont.clientWidth, 240);
    return w;
  }

  function vazio(cont) {
    const d = document.createElement("div");
    d.className = "gvazio";
    d.textContent = "Sem dados para os filtros escolhidos";
    cont.appendChild(d);
  }

  /* ----------------------------------------------------------- barras horizontais */
  function barras(cont, dados, op = {}) {
    const W = preparar(cont);
    dados = (dados || []).filter((d) => d.valor !== null);
    if (!dados.length) return vazio(cont);
    const fmt = op.formato || F.inteiro;
    const rotW = Math.min(op.larguraRotulo || 190, W * 0.42);
    const linhaH = 30, H = dados.length * linhaH + 8;
    const valW = 86;
    const svg = el("svg", { width: W, height: H, role: "img", "aria-label": op.titulo || "Gráfico de barras" }, cont);
    const max = Math.max(...dados.map((d) => d.valor), 0);
    const min = Math.min(...dados.map((d) => d.valor), 0);
    const plotW = W - rotW - valW - 8;
    const x = (v) => rotW + ((v - min) / ((max - min) || 1)) * plotW;
    el("line", { x1: x(0), x2: x(0), y1: 0, y2: H, class: "geixo" }, svg);
    dados.forEach((d, i) => {
      const y = i * linhaH + 4;
      const g = el("g", { class: "gmarca" + (op.onClick ? " clicavel" : ""), tabindex: 0 }, svg);
      const t = txt("text", { x: rotW - 8, y: y + linhaH / 2 - 2, class: "grot", "text-anchor": "end", "dominant-baseline": "middle" }, d.rotulo, g);
      let rot = d.rotulo;
      try {
        while (rot.length > 4 && t.getComputedTextLength() > rotW - 12) {
          rot = rot.slice(0, -2);
          t.textContent = rot.trimEnd() + "…";
        }
      } catch (e) { /* medição indisponível */ }
      const x0 = x(Math.min(0, d.valor)), x1 = x(Math.max(0, d.valor));
      const h = Math.min(18, linhaH - 10);
      const largura = Math.max(x1 - x0, 1);
      const r = Math.min(4, largura / 2);
      const yb = y + (linhaH - 4 - h) / 2;
      // ponta arredondada do lado do valor, reta na base
      const p = d.valor >= 0
        ? `M${x0},${yb} H${x1 - r} Q${x1},${yb} ${x1},${yb + r} V${yb + h - r} Q${x1},${yb + h} ${x1 - r},${yb + h} H${x0} Z`
        : `M${x1},${yb} H${x0 + r} Q${x0},${yb} ${x0},${yb + r} V${yb + h - r} Q${x0},${yb + h} ${x0 + r},${yb + h} H${x1} Z`;
      el("path", { d: p, fill: d.cor || op.cor || cor(0), class: "gbarra" }, g);
      txt("text", { x: x1 + 6, y: y + linhaH / 2 - 2, class: "gval", "dominant-baseline": "middle" },
        op.compacto ? F.compacto(d.valor, op.moeda) : fmt(d.valor), g);
      el("rect", { x: 0, y: y, width: W, height: linhaH, fill: "transparent" }, g);
      const tipFn = (ev) => mostrarTip(ev, d.rotulo, [{ valor: fmt(d.valor), cor: d.cor || op.cor || cor(0) }]);
      g.addEventListener("pointermove", tipFn);
      g.addEventListener("pointerleave", esconderTip);
      g.addEventListener("focus", (ev) => { const b = g.getBoundingClientRect(); tipFn({ clientX: b.right - 80, clientY: b.top }); });
      g.addEventListener("blur", esconderTip);
      if (op.onClick) {
        g.addEventListener("click", () => { esconderTip(); op.onClick(d); });
        g.addEventListener("keydown", (ev) => { if (ev.key === "Enter") op.onClick(d); });
      }
    });
  }

  /* ----------------------------------------------------------- colunas (1+ séries) */
  function colunas(cont, series, op = {}) {
    const W = preparar(cont);
    series = (series || []).filter((s) => s.pontos && s.pontos.length);
    if (!series.length || series.every((s) => s.pontos.every((p) => !p.valor))) return vazio(cont);
    const fmt = op.formato || F.inteiro;
    const H = op.altura || 240;
    const m = { t: 12, r: 8, b: 30, l: 64 };
    const svg = el("svg", { width: W, height: H, role: "img", "aria-label": op.titulo || "Gráfico de colunas" }, cont);
    const rotulos = series[0].pontos.map((p) => p.rotulo);
    const todos = series.flatMap((s) => s.pontos.map((p) => p.valor));
    const esc = escala(Math.max(...todos, 0), Math.min(...todos, 0));
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const y = (v) => m.t + ph - ((v - esc.ini) / (esc.fim - esc.ini)) * ph;
    esc.ticks.forEach((t) => {
      el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: t === 0 ? "geixo" : "ggrade" }, svg);
      txt("text", { x: m.l - 8, y: y(t), class: "gtick", "text-anchor": "end", "dominant-baseline": "middle" }, F.compacto(t, op.moeda), svg);
    });
    const banda = pw / rotulos.length;
    const ns = series.length;
    const bw = Math.min(24, Math.max(4, (banda * 0.7 - (ns - 1) * 2) / ns));
    const grupoW = ns * bw + (ns - 1) * 2;
    const passoRot = Math.ceil(rotulos.length / Math.max(1, Math.floor(pw / 56)));
    rotulos.forEach((r, i) => {
      const cx = m.l + banda * i + banda / 2;
      if (i % passoRot === 0)
        txt("text", { x: cx, y: H - m.b + 16, class: "gtick", "text-anchor": "middle" }, F.mes(r), svg);
      const g = el("g", { class: "gmarca" + (op.onClick ? " clicavel" : ""), tabindex: 0 }, svg);
      el("rect", { x: m.l + banda * i, y: m.t, width: banda, height: ph, fill: "transparent", class: "ghit" }, g);
      series.forEach((s, j) => {
        const v = s.pontos[i] ? s.pontos[i].valor : 0;
        const x0 = cx - grupoW / 2 + j * (bw + 2);
        const yt = y(Math.max(v, 0)), yb = y(Math.min(v, 0));
        const h = Math.max(yb - yt, v ? 1 : 0);
        const rr = Math.min(4, bw / 2, h);
        const d = v >= 0
          ? `M${x0},${yb} V${yt + rr} Q${x0},${yt} ${x0 + rr},${yt} H${x0 + bw - rr} Q${x0 + bw},${yt} ${x0 + bw},${yt + rr} V${yb} Z`
          : `M${x0},${yt} V${yb - rr} Q${x0},${yb} ${x0 + rr},${yb} H${x0 + bw - rr} Q${x0 + bw},${yb} ${x0 + bw},${yb - rr} V${yt} Z`;
        if (h > 0) el("path", { d, fill: cor(op.corInicial ? op.corInicial + j : j), class: "gbarra" }, g);
      });
      const tipFn = (ev) => mostrarTip(ev, F.mes(r), series.map((s, j) => ({
        valor: fmt(s.pontos[i] ? s.pontos[i].valor : 0), nome: ns > 1 ? s.nome : "", cor: cor(op.corInicial ? op.corInicial + j : j),
      })));
      g.addEventListener("pointermove", tipFn);
      g.addEventListener("pointerleave", esconderTip);
      g.addEventListener("focus", (ev) => { const b = g.getBoundingClientRect(); tipFn({ clientX: b.left + b.width / 2, clientY: b.top + 20 }); });
      g.addEventListener("blur", esconderTip);
      if (op.onClick) g.addEventListener("click", () => { esconderTip(); op.onClick({ rotulo: r }); });
    });
    legenda(cont, series, "barra");
  }

  /* ----------------------------------------------------------- linhas / área */
  function linhas(cont, series, op = {}) {
    const W = preparar(cont);
    series = (series || []).filter((s) => s.pontos && s.pontos.length);
    if (!series.length) return vazio(cont);
    const fmt = op.formato || F.inteiro;
    const H = op.altura || 240;
    const m = { t: 14, r: 16, b: 30, l: 64 };
    const svg = el("svg", { width: W, height: H, role: "img", "aria-label": op.titulo || "Gráfico de linhas" }, cont);
    const rotulos = series[0].pontos.map((p) => p.rotulo);
    const todos = series.flatMap((s) => s.pontos.map((p) => p.valor));
    const esc = escala(Math.max(...todos, 0), Math.min(...todos, 0));
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const n = rotulos.length;
    const x = (i) => m.l + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
    const y = (v) => m.t + ph - ((v - esc.ini) / (esc.fim - esc.ini)) * ph;
    esc.ticks.forEach((t) => {
      el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: t === 0 ? "geixo" : "ggrade" }, svg);
      txt("text", { x: m.l - 8, y: y(t), class: "gtick", "text-anchor": "end", "dominant-baseline": "middle" }, F.compacto(t, op.moeda), svg);
    });
    const passoRot = Math.ceil(n / Math.max(1, Math.floor(pw / 56)));
    rotulos.forEach((r, i) => {
      if (i % passoRot === 0) txt("text", { x: x(i), y: H - m.b + 16, class: "gtick", "text-anchor": "middle" }, F.mes(r), svg);
    });
    series.forEach((s, j) => {
      const pts = s.pontos.map((p, i) => [x(i), y(p.valor)]);
      const d = pts.map((p, i) => (i ? "L" : "M") + p[0] + "," + p[1]).join(" ");
      if (op.area && series.length === 1)
        el("path", { d: d + ` L${pts[pts.length - 1][0]},${y(Math.max(esc.ini, 0))} L${pts[0][0]},${y(Math.max(esc.ini, 0))} Z`, fill: cor(j), class: "garea" }, svg);
      el("path", { d, stroke: cor(j), class: "glinha" }, svg);
      const u = pts[pts.length - 1];
      el("circle", { cx: u[0], cy: u[1], r: 4, fill: cor(j), class: "gponto" }, svg);
    });
    // camada de interação com linha-guia
    const guia = el("line", { y1: m.t, y2: m.t + ph, class: "gguia", visibility: "hidden" }, svg);
    const pontosHover = series.map((s, j) => el("circle", { r: 4, fill: cor(j), class: "gponto", visibility: "hidden" }, svg));
    const hit = el("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (ev) => {
      const b = svg.getBoundingClientRect();
      const px = ev.clientX - b.left;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / pw) * (n - 1))));
      guia.setAttribute("x1", x(i)); guia.setAttribute("x2", x(i)); guia.setAttribute("visibility", "visible");
      series.forEach((s, j) => {
        pontosHover[j].setAttribute("cx", x(i)); pontosHover[j].setAttribute("cy", y(s.pontos[i].valor));
        pontosHover[j].setAttribute("visibility", "visible");
      });
      mostrarTip(ev, F.mes(rotulos[i]), series.map((s, j) => ({ valor: fmt(s.pontos[i].valor), nome: series.length > 1 ? s.nome : "", cor: cor(j) })));
    });
    hit.addEventListener("pointerleave", () => {
      esconderTip(); guia.setAttribute("visibility", "hidden");
      pontosHover.forEach((p) => p.setAttribute("visibility", "hidden"));
    });
    legenda(cont, series, "linha");
  }

  /* ----------------------------------------------------------- rosca (até 5 fatias) */
  function rosca(cont, dados, op = {}) {
    const W = preparar(cont);
    dados = (dados || []).filter((d) => d.valor > 0);
    if (!dados.length) return vazio(cont);
    const fmt = op.formato || F.inteiro;
    const total = dados.reduce((a, d) => a + d.valor, 0);
    const H = op.altura || 200, R = Math.min(H / 2 - 6, 90), r = R * 0.62;
    const wrap = document.createElement("div");
    wrap.className = "grosca";
    cont.appendChild(wrap);
    const svg = el("svg", { width: R * 2 + 12, height: H, role: "img", "aria-label": op.titulo || "Gráfico de rosca" }, wrap);
    const cx = R + 6, cy = H / 2;
    let a0 = -Math.PI / 2;
    dados.forEach((d, i) => {
      const ang = (d.valor / total) * Math.PI * 2;
      const a1 = a0 + ang;
      const grande = ang > Math.PI ? 1 : 0;
      const p = (rad, a) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
      const [x0, y0] = p(R, a0), [x1, y1] = p(R, a1 - 0.0001), [x2, y2] = p(r, a1 - 0.0001), [x3, y3] = p(r, a0);
      const g = el("g", { class: "gmarca" + (op.onClick ? " clicavel" : ""), tabindex: 0 }, svg);
      el("path", {
        d: `M${x0},${y0} A${R},${R} 0 ${grande} 1 ${x1},${y1} L${x2},${y2} A${r},${r} 0 ${grande} 0 ${x3},${y3} Z`,
        fill: d.cor || cor(i), class: "gfatia",
      }, g);
      const tipFn = (ev) => mostrarTip(ev, d.rotulo, [{ valor: fmt(d.valor), nome: nf2.format((d.valor / total) * 100) + "%", cor: d.cor || cor(i) }]);
      g.addEventListener("pointermove", tipFn);
      g.addEventListener("pointerleave", esconderTip);
      if (op.onClick) g.addEventListener("click", () => { esconderTip(); op.onClick(d); });
      a0 = a1;
    });
    txt("text", { x: cx, y: cy - 6, class: "grosca-total", "text-anchor": "middle" }, op.compacto ? F.compacto(total, op.moeda) : fmt(total), svg);
    txt("text", { x: cx, y: cy + 14, class: "gtick", "text-anchor": "middle" }, op.rotuloTotal || "total", svg);
    const lg = document.createElement("div");
    lg.className = "grosca-leg";
    dados.forEach((d, i) => {
      const it = document.createElement("div");
      const k = document.createElement("span");
      k.className = "glk-barra";
      k.style.background = d.cor || cor(i);
      const nome = document.createElement("span");
      nome.textContent = d.rotulo;
      const v = document.createElement("strong");
      v.textContent = nf2.format((d.valor / total) * 100) + "%";
      it.append(k, nome, v);
      lg.appendChild(it);
    });
    wrap.appendChild(lg);
  }

  /* re-desenha ao redimensionar */
  const desenhos = new Map();
  const ro = new ResizeObserver((ents) => {
    for (const e of ents) {
      const f = desenhos.get(e.target);
      if (f && Math.abs((e.target._w || 0) - e.contentRect.width) > 4) {
        e.target._w = e.contentRect.width;
        f();
      }
    }
  });
  function desenhar(cont, fn) {
    desenhos.set(cont, fn);
    cont._w = cont.clientWidth;
    fn();
    ro.observe(cont);
  }

  window.Graficos = { barras, colunas, linhas, rosca, desenhar, F };
})();
