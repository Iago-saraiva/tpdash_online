// Frotas: abastecimento e manutenção das máquinas. Cada empresa escolhe quais tipos de movimento entram.
import { useEffect, useState } from "react";
import { api, baixar, opcoesGerais, type Codigo, type Opcoes } from "../api";
import { DADOS } from "../dados";
import { F, fmtData } from "../formatos";
import { Kpis } from "../componentes/Kpis";
import { Barras, Colunas, type ItemBarra, type Serie } from "../componentes/Graficos";
import { Campos, useGaveta } from "../componentes/Gaveta";
import { Tabela, type Celula, type DadosTabela } from "../componentes/Tabela";
import { Erro, useAbrirDocumento } from "../componentes/Documento";
import { useAvisar } from "../componentes/Avisos";
import { Atalhos, Escolha, Exportar, FormFiltros, Texto, paraBusca, useDados, useFiltros, type Valores } from "../componentes/Filtros";

const ROT_FROTA: Record<string, string> = { CODMAQUINA: "Máquina", DESCRICAO: "Descrição", ABASTECIMENTOS: "Abastec.", LITROS: "Litros",
  VALOR_COMBUSTIVEL: "Combustível (R$)", PRECO_LITRO: "R$ / litro", MANUTENCOES: "Manutenções", VALOR_MANUTENCAO: "Manutenção (R$)",
  VALOR_TOTAL: "Total (R$)", KM_INICIAL: "KM inicial", KM_FINAL: "KM final", KM_RODADO: "KM rodado", KM_POR_LITRO: "KM / litro",
  ULTIMO: "Último lançamento", KM: "KM", ITENS: "Itens", FORNECEDOR: "Fornecedor" };
const CAT_FROTA: Record<string, string> = { abastecimento: "Abastecimento", manutencao: "Manutenção" };
const sugerirCategoria = (nome?: string) => (/COMBUST|ABASTEC|LUBRIF|DIESEL|GASOLINA|ETANOL|ARLA/i.test(nome || "") ? "abastecimento" : "manutencao");
const podeDoc = () => (DADOS.usuario?.modulos || []).includes("movimentos");

interface TipoFrota { cod: string; nome?: string; qtd: number; de?: string; ate?: string; pede_maquina?: boolean }
interface Config { tipos: TipoFrota[]; escolha: Record<string, string>; pode_configurar: boolean }
interface Resp {
  kpis: Record<string, number>; periodo: [string, string];
  maquinas: Codigo[]; grupos: Codigo[];
  por_mes: Serie[]; por_produto: ItemBarra[]; top_maquinas: (ItemBarra & { codigo: string })[];
  tabela: DadosTabela; lancamentos: DadosTabela; truncado: boolean;
}

/* ------------------------------------------------------------ escolha dos movimentos (gaveta) */
function EscolhaMovimentos({ primeira }: { primeira: boolean }) {
  const [d, setD] = useState<Config | null>(null);
  const [erro, setErro] = useState("");
  const [marc, setMarc] = useState<Record<string, boolean>>({});
  const [cats, setCats] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState(false);
  useEffect(() => {
    api<Config>("/api/frotas/tipos").then((x) => {
      const m: Record<string, boolean> = {}, c: Record<string, string> = {};
      x.tipos.forEach((t) => { m[t.cod] = !!x.escolha[t.cod]; c[t.cod] = x.escolha[t.cod] || sugerirCategoria(t.nome); });
      setMarc(m); setCats(c); setD(x);
    }).catch((e) => setErro(e.message));
  }, []);
  if (!d) return <Erro msg={erro} />;
  const salvar = async () => {
    const tipos: Record<string, string> = {};
    d.tipos.forEach((t) => { if (marc[t.cod]) tipos[t.cod] = cats[t.cod]; });
    setSalvando(true);
    try { await api("/api/frotas/tipos", { tipos }); location.reload(); }
    catch (e) { setErro((e as Error).message); setSalvando(false); }
  };
  return <>
    <p>{primeira
      ? "Escolha os tipos de movimento que são abastecimento ou manutenção das máquinas desta empresa. A escolha fica salva e vale para todos os usuários."
      : "Marque os tipos de movimento que entram no Frotas e diga se cada um é abastecimento ou manutenção. Os litros e o preço do litro saem só dos de abastecimento."}</p>
    <p className="nota">Aparecem os tipos que já têm movimento com máquina informada e os que pedem máquina no Puma. Não marque a nota e o rateio da mesma despesa, senão o valor conta duas vezes.</p>
    {!d.tipos.length ? <Erro msg="Nenhum tipo de movimento desta empresa tem máquina informada." /> : <>
      <div style={{ overflowX: "auto" }}>
        <table className="dados">
          <thead><tr><th></th><th>Movimento</th><th className="num">Lançamentos</th><th>Período</th><th>Conta como</th></tr></thead>
          <tbody>
            {d.tipos.map((t) => {
              const marcado = !!marc[t.cod];
              const cat = cats[t.cod];
              return (
                <tr key={t.cod}>
                  <td><input type="checkbox" id={"frota-" + t.cod} checked={marcado} disabled={!d.pode_configurar}
                    onChange={(e) => setMarc({ ...marc, [t.cod]: e.target.checked })} /></td>
                  <td><label htmlFor={"frota-" + t.cod}>{`${t.cod} · ${t.nome || ""}`}</label>{t.pede_maquina && <> <span className="tag">pede máquina</span></>}</td>
                  <td className="num">{F.inteiro(t.qtd)}</td>
                  <td>{t.qtd ? `${fmtData(t.de)} a ${fmtData(t.ate)}` : "sem lançamentos"}</td>
                  <td><select id={"frota-cat-" + t.cod} value={cat} disabled={!marcado || !d.pode_configurar}
                    onChange={(e) => setCats({ ...cats, [t.cod]: e.target.value })}>
                    {Object.entries(CAT_FROTA).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
                  </select></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {d.pode_configurar
        ? <><button type="button" className="btn primario" style={{ marginTop: 12 }} disabled={salvando} onClick={salvar}>Salvar</button><div><Erro msg={erro} /></div></>
        : <p className="nota">Só o administrador da empresa pode mudar esta escolha.</p>}
    </>}
  </>;
}

/* ------------------------------------------------------------ lançamentos de uma máquina (gaveta) */
const celulaTipo: Celula = (c, v) => (c === "TIPO" ? { conteudo: <span className={"tag " + (v === "Manutenção" ? "atencao" : "entrada")}>{String(v)}</span> } : null);
interface RespMaquina { maquina: Record<string, string>; resumo: Record<string, number>; periodo: [string, string]; tabela: DadosTabela; truncado: boolean }
function LancamentosMaquina({ q, reabrir }: { q: URLSearchParams; reabrir: () => void }) {
  const g = useGaveta();
  const abrirDoc = useAbrirDocumento();
  const [d, setD] = useState<RespMaquina | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<RespMaquina>("/api/frotas/maquina?" + q).then((x) => { g.titulo(`${x.maquina.placa || x.maquina.codigo} · ${x.maquina.nome || ""}`); setD(x); })
      .catch((e) => setErro(e.message));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <Erro msg={erro} />;
  const m = d.maquina, r = d.resumo;
  const bx = (fmt: string) => { const z = new URLSearchParams(q); z.set("formato", fmt); baixar("/api/frotas/maquina?" + z).catch((e) => setErro(e.message)); };
  return <>
    <Erro msg={erro} />
    <Campos pares={[
      ["Período", `${fmtData(d.periodo[0])} a ${fmtData(d.periodo[1])}`], ["Grupo", m.grupo], ["Marca", m.marca], ["Ano / modelo", [m.ano, m.modelo].filter(Boolean).join(" / ")],
      ["Abastecimentos", F.inteiro(r.abastecimentos)], ["Litros", F.numero(r.litros)], ["Combustível", F.moeda(r.combustivel)],
      ["Manutenções", F.inteiro(r.manutencoes)], ["Manutenção", F.moeda(r.manutencao)], ["Total", F.moeda(r.total)],
    ]} />
    <div>
      <Tabela dados={d.tabela} truncado={d.truncado} rotulos={ROT_FROTA} ocultar={["IDMOV"]} celula={celulaTipo}
        botoes={<><button className="btn pequeno" onClick={() => bx("xlsx")}>Excel</button><button className="btn pequeno" onClick={() => bx("pdf")}>PDF</button></>}
        onClick={podeDoc() ? (row, cols) => abrirDoc(row[cols.indexOf("IDMOV")], reabrir, "‹ Voltar para a máquina") : undefined} />
    </div>
  </>;
}

/* ------------------------------------------------------------ tela */
export default function Frotas() {
  const g = useGaveta();
  const avisar = useAvisar();
  const [cfg, setCfg] = useState<Config | null>(null);
  useEffect(() => {
    api<Config>("/api/frotas/tipos").then((c) => {
      setCfg(c);
      // primeira vez: o administrador já vê a escolha dos movimentos
      if (!Object.keys(c.escolha || {}).length && c.pode_configurar) abrirConfig(true);
    }).catch((e) => avisar(e.message));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const abrirConfig = (primeira: boolean) => g.abrir({ titulo: "Movimentos do Frotas", larga: true, corpo: <EscolhaMovimentos primeira={primeira} /> });

  if (!cfg) return null;
  const escolhidos = Object.entries(cfg.escolha || {});
  if (!escolhidos.length) {
    return (
      <div className="aviso" id="aviso-frota">
        {cfg.pode_configurar
          ? <>Os movimentos do Frotas ainda não foram escolhidos para esta empresa. <button type="button" className="btn primario pequeno" onClick={() => abrirConfig(true)}>Escolher movimentos</button></>
          : "O Frotas ainda não foi configurado para esta empresa. Peça ao administrador para escolher os movimentos de abastecimento e manutenção."}
      </div>
    );
  }
  return <Painel cfg={cfg} escolhidos={escolhidos} abrirConfig={() => abrirConfig(false)} />;
}

const PADRAO = { ini: "", fim: "", maquina: "", grupo: "", filial: "", busca: "" };
function Painel({ cfg, escolhidos, abrirConfig }: { cfg: Config; escolhidos: [string, string][]; abrirConfig: () => void }) {
  const g = useGaveta();
  const avisar = useAvisar();
  const abrirDoc = useAbrirDocumento();
  const f = useFiltros(PADRAO);
  const [o, setO] = useState<Opcoes | null>(null);
  useEffect(() => { opcoesGerais().then(setO).catch(() => setO({})); }, []);
  const { dados: d, carregando } = useDados<Resp>("/api/frotas", f, o !== null);
  const [listas, setListas] = useState<{ maquinas: Codigo[]; grupos: Codigo[] } | null>(null);
  useEffect(() => { if (d && !listas) setListas({ maquinas: d.maquinas || [], grupos: d.grupos || [] }); }, [d]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [aba, setAba] = useState("maquinas");

  const nomes = (cat: string) => escolhidos.filter(([, c]) => c === cat).map(([cod]) => cod).join(", ") || "nenhum";
  const ini = f.form.ini || d?.periodo[0] || "", fim = f.form.fim || d?.periodo[1] || "";
  const abrirMaquina = (codigo: unknown, filtros: Valores) => {
    const p = paraBusca(filtros);
    const q = new URLSearchParams();
    ["ini", "fim", "filial"].forEach((k) => { if (p.get(k)) q.set(k, p.get(k)!); });
    q.set("codigo", String(codigo));
    const abrir = () => g.abrir({ titulo: "Carregando…", larga: true, corpo: <LancamentosMaquina q={q} reabrir={abrir} /> });
    abrir();
  };
  const expLanc = async (fmt: string) => {
    const p = paraBusca(f.form);
    p.set("ver", "lancamentos"); p.set("formato", fmt);
    try { await baixar("/api/frotas?" + p); } catch (e) { avisar((e as Error).message); }
  };
  const k = d?.kpis;
  return (
    <div className={carregando ? "carregando" : ""} style={{ display: "contents" }}>
      <FormFiltros f={f} acoes={false}>
        <label>De<input type="date" name="ini" value={ini} onChange={(e) => f.set("ini", e.target.value)} /></label>
        <label>Até<input type="date" name="fim" value={fim} onChange={(e) => f.set("fim", e.target.value)} /></label>
        <Atalhos f={f} />
        <label>Máquina<Escolha f={f} nome="maquina" className="largo" auto lista={listas?.maquinas || []} vazio="Todas as máquinas" /></label>
        <label>Grupo<Escolha f={f} nome="grupo" auto lista={listas?.grupos || []} vazio="Todos" /></label>
        <label>Filial<Escolha f={f} nome="filial" auto lista={o?.filiais || []} vazio="Todas" /></label>
        <label>Busca<Texto f={f} nome="busca" placeholder="placa, código ou nome" /></label>
        <div className="acoes">
          {cfg.pode_configurar && <button type="button" className="btn" title="Escolher os movimentos de abastecimento e manutenção" onClick={abrirConfig}>Movimentos…</button>}
          <button type="button" className="btn" onClick={() => f.limpar()}>Limpar</button>
          <button className="btn primario">Aplicar</button>
        </div>
      </FormFiltros>
      <p className="nota">{`Abastecimentos pelos movimentos ${nomes("abastecimento")} e manutenções pelos movimentos ${nomes("manutencao")}, ligados à máquina informada no movimento. Cancelados não entram.`}</p>
      <div className="kpis">
        {k && <Kpis lista={[
          { rotulo: "Gasto total", valor: F.compacto(k.total, true), detalhe: F.moeda(k.total), classe: "destaque" },
          { rotulo: "Combustível", valor: F.compacto(k.combustivel, true), detalhe: `${F.inteiro(k.abastecimentos)} abastecimentos · ${F.numero(k.litros)} L` },
          { rotulo: "Preço médio do litro", valor: k.preco_litro ? F.moeda(k.preco_litro) : "—", detalhe: "combustível, sem ARLA" },
          { rotulo: "Manutenção", valor: F.compacto(k.manutencao, true), detalhe: `${F.inteiro(k.manutencoes)} lançamentos` },
        ]} />}
      </div>
      <div className="grade">
        <div className="cartao c8"><div className="cartao-cab"><h2>Gasto por mês</h2></div><div>{d && <Colunas series={d.por_mes} formato={F.moeda} moeda />}</div></div>
        <div className="cartao c4"><div className="cartao-cab"><h2>Combustível por produto</h2></div>
          <div>{d && <Barras dados={d.por_produto} formato={F.moeda} compacto moeda cor="var(--serie-4)" larguraRotulo={120} />}</div></div>
        <div className="cartao c12"><div className="cartao-cab"><h2>10 máquinas com maior gasto <span className="sub">· clique para ver os lançamentos</span></h2></div>
          <div>{d && <Barras dados={d.top_maquinas} formato={F.moeda} compacto moeda cor="var(--serie-3)" larguraRotulo={260}
            onClick={(x) => abrirMaquina((x as ItemBarra & { codigo: string }).codigo, f.form)} />}</div></div>
        <div className="cartao c12">
          <div className="abas">
            <button type="button" className={aba === "maquinas" ? "ativa" : ""} onClick={() => setAba("maquinas")}>Por máquina</button>
            <button type="button" className={aba === "lancamentos" ? "ativa" : ""} onClick={() => setAba("lancamentos")}>Lançamentos</button>
          </div>
          <div hidden={aba !== "maquinas"}>
            <div className="cartao-cab"><h2><span className="sub">clique em uma máquina para ver os lançamentos dela</span></h2><Exportar url="/api/frotas" f={f} /></div>
            <div><Tabela dados={d?.tabela || null} rotulos={ROT_FROTA} onClick={(r, cols) => abrirMaquina(r[cols.indexOf("CODMAQUINA")], f.form)} /></div>
          </div>
          <div hidden={aba !== "lancamentos"}>
            <div className="cartao-cab"><h2><span className="sub">abastecimentos e manutenções, do mais recente para o mais antigo</span></h2>
              <button className="btn pequeno" onClick={() => expLanc("xlsx")}>Excel</button><button className="btn pequeno" onClick={() => expLanc("pdf")}>PDF</button></div>
            <div><Tabela dados={d?.lancamentos || null} truncado={d?.truncado} rotulos={ROT_FROTA} ocultar={["IDMOV"]}
              onClick={podeDoc() ? (r, cols) => abrirDoc(r[cols.indexOf("IDMOV")]) : undefined} /></div>
          </div>
        </div>
      </div>
    </div>
  );
}
