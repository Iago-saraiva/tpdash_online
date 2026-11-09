// Consulta SQL: editor só de leitura, filtros :NOME, gráfico livre, tabelas do banco e consultas salvas.
import { useEffect, useRef, useState } from "react";
import { api, baixar } from "../api";
import { F } from "../formatos";
import { useAvisar } from "../componentes/Avisos";
import { Tabela, type DadosTabela } from "../componentes/Tabela";
import { GraficoLivre, Parametros, parametrosSQL, tipoPorNome } from "../componentes/Relatorio";

interface Resp extends DadosTabela { ms: number; truncado: boolean }
interface Consulta { id: number; nome: string; descricao?: string; compartilhada?: boolean; sql: string; grafico?: string }
interface Campo { campo: string; tipo: string }

/** tabela do banco na lista da esquerda: clique mostra os campos, dois cliques insere o nome */
function TabelaBanco({ nome, inserir }: { nome: string; inserir: (t: string) => void }) {
  const [campos, setCampos] = useState<Campo[] | string | null>(null);
  const [aberta, setAberta] = useState(false);
  const clicar = () => {
    if (campos === null) {
      setCampos([]);
      api<{ campos: Campo[] }>("/api/esquema?tabela=" + encodeURIComponent(nome)).then((d) => setCampos(d.campos)).catch((e) => setCampos(e.message));
    }
    setAberta((a) => !a);
  };
  return <>
    <div className="t" onClick={clicar} onDoubleClick={() => inserir(nome)}>{nome}</div>
    <div className="campos-t" hidden={!aberta}>
      {typeof campos === "string" ? campos : (campos || []).map((c) => (
        <div key={c.campo} title="Clique para inserir no SQL" onClick={(e) => { e.stopPropagation(); inserir(c.campo); }}>{c.campo + " "}<i>{c.tipo}</i></div>
      ))}
    </div>
  </>;
}

export default function Sql() {
  const avisar = useAvisar();
  const ed = useRef<HTMLTextAreaElement>(null);
  const [sql, setSql] = useState("");
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [compartilhar, setCompartilhar] = useState(false);
  const [atualId, setAtualId] = useState<number | null>(null);
  const [salvas, setSalvas] = useState<Consulta[]>([]);
  const [dados, setDados] = useState<Resp | null>(null);
  const [executando, setExecutando] = useState(false);
  const [tempo, setTempo] = useState("");
  const [g, setG] = useState({ tipo: "barras", x: "", y: "" });
  const [ocupado, setOcupado] = useState("");
  // filtros :NOME (os valores digitados ficam guardados mesmo se o filtro sumir e voltar)
  const [chaveParams, setChaveParams] = useState("");
  const [valores, setValores] = useState<Record<string, string>>({});
  const listaParams = chaveParams ? chaveParams.split(",").map((n) => ({ nome: n, rotulo: n.replace(/_/g, " ").toLowerCase(), tipo: tipoPorNome(n) })) : [];
  const atualizarParams = (texto: string) => setChaveParams(parametrosSQL(texto).join(","));
  const lerParams = () => Object.fromEntries(listaParams.map((p) => [p.nome, valores[p.nome] ?? ""]));

  const textoSQL = () => {
    const e = ed.current;
    if (!e) return sql;
    const sel = e.value.slice(e.selectionStart, e.selectionEnd);
    return sel.trim().length > 6 ? sel : e.value;
  };

  // eixo e valor do gráfico conforme as colunas do resultado
  const opcoesGrafico = (d: Resp) => {
    const xs = d.colunas;
    const ys = d.colunas.filter((_, i) => d.linhas.some((r) => typeof r[i] === "number"));
    return { xs, ys };
  };
  const ajustarGrafico = (d: Resp, pref: { tipo?: string; x?: string; y?: string } = {}) => {
    const { xs, ys } = opcoesGrafico(d);
    setG((a) => {
      const ax = pref.x ?? a.x, ay = pref.y ?? a.y;
      const x = xs.includes(ax) ? ax : (xs[0] || "");
      const y = ay === "" || ys.includes(ay) ? ay : (ys[0] ?? "");
      return { tipo: pref.tipo ?? a.tipo, x, y };
    });
  };

  const executar = async (texto?: string, pref?: { tipo?: string; x?: string; y?: string }) => {
    const t = texto ?? textoSQL();
    atualizarParams(ed.current?.value ?? t);
    setExecutando(true);
    setTempo("Executando…");
    try {
      const d = await api<Resp>("/api/sql", { sql: t, valores: lerParams() });
      setDados(d);
      setTempo(`${F.inteiro(d.linhas.length)} linhas em ${F.inteiro(d.ms)} ms` + (d.truncado ? " · limite de linhas atingido" : ""));
      ajustarGrafico(d, pref);
    } catch (e) {
      setTempo("");
      avisar((e as Error).message);
    } finally {
      setExecutando(false);
    }
  };

  const carregarSalvas = () => api<{ consultas: Consulta[] }>("/api/consultas").then((d) => setSalvas(d.consultas));

  // tabelas do banco
  const [tabelas, setTabelas] = useState<string[] | string>([]);
  const [filtroT, setFiltroT] = useState("");
  useEffect(() => {
    api<{ tabelas: string[] }>("/api/esquema").then((d) => setTabelas(d.tabelas)).catch((e) => setTabelas(e.message));
    carregarSalvas().catch((e) => avisar(e.message));
    // SQL vindo de um relatório do ReportBuilder
    try {
      const pend = JSON.parse(sessionStorage.getItem("sql_pendente") || "null");
      if (pend) {
        sessionStorage.removeItem("sql_pendente");
        setSql(pend.sql);
        setNome(pend.nome || "");
        setValores(pend.valores || {});
        atualizarParams(pend.sql);
      }
    } catch { /* */ }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const inserir = (t: string) => {
    const e = ed.current;
    if (!e) return;
    e.setRangeText(t, e.selectionStart, e.selectionEnd, "end");
    setSql(e.value);
    e.focus();
  };

  const abrirSalva = (id: string) => {
    const c = salvas.find((x) => String(x.id) === id);
    if (!c) return;
    setAtualId(c.id);
    setSql(c.sql); setNome(c.nome); setDescricao(c.descricao || ""); setCompartilhar(!!c.compartilhada);
    let pref: { tipo?: string; x?: string; y?: string } = {};
    try { const gg = JSON.parse(c.grafico || "{}"); if (gg.tipo) pref.tipo = gg.tipo; if (gg.x) pref = { ...pref, x: gg.x, y: gg.y || "" }; } catch { /* */ }
    if (ed.current) ed.current.value = c.sql;
    executar(c.sql, pref);
  };
  const nova = () => { setAtualId(null); setSql(""); setNome(""); setDescricao(""); setCompartilhar(false); ed.current?.focus(); };
  const salvar = async () => {
    try {
      const r = await api<{ id: number }>("/api/consultas", { id: atualId, nome, descricao, sql, compartilhada: compartilhar, grafico: JSON.stringify(g) });
      setAtualId(r.id);
      await carregarSalvas();
      avisar("Consulta salva.", "atencao");
    } catch (e) { avisar((e as Error).message); }
  };
  const excluir = async () => {
    if (!atualId) return;
    if (!window.confirm("Excluir esta consulta salva?")) return;
    try { await api(`/api/consultas/${atualId}/excluir`, {}); nova(); await carregarSalvas(); }
    catch (e) { avisar((e as Error).message); }
  };
  const exportar = async (fmt: string) => {
    setOcupado(fmt);
    try { await baixar("/api/sql/exportar", { sql: textoSQL(), valores: lerParams(), formato: fmt, titulo: nome || "Consulta SQL" }); }
    catch (e) { avisar((e as Error).message); } finally { setOcupado(""); }
  };

  const op = dados ? opcoesGrafico(dados) : { xs: [], ys: [] };
  const listaT = typeof tabelas === "string" ? null : tabelas.filter((n) => n.includes(filtroT.toUpperCase())).slice(0, 400);
  return (
    <div className="sql-layout">
      <div className="cartao lista-tabelas">
        <div className="cartao-cab"><h2>Tabelas</h2></div>
        <input id="filtro-tabelas" className="campo" placeholder="Filtrar tabelas…" value={filtroT} onChange={(e) => setFiltroT(e.target.value)} />
        <div id="tabelas">{listaT ? listaT.map((n) => <TabelaBanco key={n} nome={n} inserir={inserir} />) : tabelas}</div>
        <p className="gtick" style={{ marginTop: 8 }}>Clique para ver os campos; clique no campo (ou dê dois cliques na tabela) para inserir no SQL.</p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
        <div className="cartao">
          <div className="cartao-cab">
            <select id="salvas" className="campo" style={{ maxWidth: 340 }} value={atualId ? String(atualId) : ""} onChange={(e) => abrirSalva(e.target.value)}>
              <option value="">Abrir consulta salva…</option>
              {salvas.map((c) => <option key={c.id} value={c.id}>{c.nome + (c.compartilhada ? " (compartilhada)" : "")}</option>)}
            </select>
            <span style={{ flex: 1 }} />
            <button className="btn pequeno" id="nova" onClick={nova}>Nova</button>
          </div>
          <textarea id="sql" ref={ed} className="sql-editor" spellCheck={false} value={sql}
            placeholder={"SELECT M.NUMEROMOV, M.DATAEMISSAO, M.VALORLIQUIDO\nFROM TMOV M\nWHERE M.CODTMV STARTING WITH '2.2'\nORDER BY M.DATAEMISSAO DESC"}
            onChange={(e) => { setSql(e.target.value); atualizarParams(e.target.value); }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); executar(); }
              if (e.key === "Tab") {
                e.preventDefault();
                const t = e.currentTarget;
                t.setRangeText("  ", t.selectionStart, t.selectionEnd, "end");
                setSql(t.value);
              }
            }} />
          <Parametros id="params" style={{ marginTop: 8 }} lista={listaParams} valores={lerParams()} mudar={(v) => setValores((a) => ({ ...a, ...v }))} />
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
            <button className="btn primario" id="executar" disabled={executando} onClick={() => executar()}>▶ Executar <span className="gtick" style={{ fill: "none", color: "inherit", opacity: 0.8 }}>(Ctrl+Enter)</span></button>
            <span className="gtick" id="tempo" style={{ fontSize: 12 }}>{tempo}</span>
            <span style={{ flex: 1 }} />
            <button className="btn pequeno" disabled={ocupado === "xlsx"} onClick={() => exportar("xlsx")}>Excel</button>
            <button className="btn pequeno" disabled={ocupado === "pdf"} onClick={() => exportar("pdf")}>PDF</button>
          </div>
          <div className="form-grade" style={{ marginTop: 12 }}>
            <label>Nome da consulta<input id="nome" className="campo" placeholder="ex.: Empréstimos por funcionário" value={nome} onChange={(e) => setNome(e.target.value)} /></label>
            <label>Descrição<input id="descricao" className="campo" value={descricao} onChange={(e) => setDescricao(e.target.value)} /></label>
            <label className="check" style={{ flexDirection: "row", alignSelf: "end" }}><input type="checkbox" id="compartilhar" checked={compartilhar} onChange={(e) => setCompartilhar(e.target.checked)} /> Compartilhar com todos (aparece em Relatórios)</label>
            <div style={{ display: "flex", gap: 8, alignItems: "end" }}><button className="btn" id="salvar" onClick={salvar}>Salvar</button><button className="btn perigo" id="excluir" onClick={excluir}>Excluir</button></div>
          </div>
          <p className="gtick" style={{ fontSize: 12, margin: "10px 0 0" }}>Somente leitura: o painel só aceita SELECT e roda tudo em transação de leitura — nada é gravado no banco do Puma. Selecione um trecho para executar só ele. Use <code>:NOME</code> no SQL para criar filtros (ex.: <code>WHERE M.DATAEMISSAO BETWEEN :DATA_INICIAL AND :DATA_FINAL</code>) — os campos aparecem acima do botão Executar. Para um filtro opcional use <code>(CAST(:TIPO AS VARCHAR(20)) IS NULL OR M.CODTMV = :TIPO)</code>.</p>
        </div>
        <div id="resultado" className="secao" hidden={!dados}>
          <div className="cartao">
            <div className="cartao-cab"><h2>Gráfico</h2>
              <label className="gtick">Tipo <select id="g-tipo" className="campo" style={{ minWidth: "auto", height: 28 }} value={g.tipo} onChange={(e) => setG({ ...g, tipo: e.target.value })}>
                <option value="barras">Barras</option><option value="colunas">Colunas</option><option value="linhas">Linhas</option><option value="rosca">Rosca</option><option value="nenhum">Nenhum</option>
              </select></label>
              <label className="gtick">Eixo / categoria <select id="g-x" className="campo" style={{ minWidth: "auto", height: 28 }} value={g.x} onChange={(e) => setG({ ...g, x: e.target.value })}>
                {op.xs.map((c) => <option key={c} value={c}>{c}</option>)}
              </select></label>
              <label className="gtick">Valor <select id="g-y" className="campo" style={{ minWidth: "auto", height: 28 }} value={g.y} onChange={(e) => setG({ ...g, y: e.target.value })}>
                <option value="">(contar linhas)</option>{op.ys.map((c) => <option key={c} value={c}>{c}</option>)}
              </select></label>
            </div>
            <div id="g-livre" hidden={g.tipo === "nenhum"}>{dados && g.tipo !== "nenhum" && <GraficoLivre dados={dados} cfg={g} />}</div>
          </div>
          <div className="cartao"><div className="cartao-cab"><h2>Resultado</h2></div><div id="tabela"><Tabela dados={dados} truncado={dados?.truncado} /></div></div>
        </div>
      </div>
    </div>
  );
}
