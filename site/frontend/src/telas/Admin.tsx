// Administração: usuários (módulos, empresas, relatórios e tipos liberados), sincronização e teste do ReportBuilder,
// últimos acessos e avisos de segurança.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAvisar } from "../componentes/Avisos";
import { Tabela, type DadosTabela } from "../componentes/Tabela";

interface Usuario {
  id: number; login: string; nome: string; admin: boolean; ativo: boolean; modulos: string[]; trocar_senha?: boolean; ultimo_acesso?: string;
  relatorios: { pastas: string[]; ids: string[] } | null; tipos_mov: string[]; bancos: string[] | null;
}
interface RespUsuarios { modulos: Record<string, string>; usuarios: Usuario[]; acessos: { quando: string; usuario: string; acao: string; detalhe: string }[] }
interface Catalogo {
  relatorios: { chave: string; nome: string; pasta: string; modulo: string; antigo?: boolean }[];
  tipos: { cod: string; nome: string }[];
  bancos?: { id: string; nome: string }[]; site?: boolean; empresa_id?: string; empresa?: string;
}
interface GrupoSel { chave: string; nome: string; itens: { chave: string; nome: string; extra?: string }[] }
interface Sel { grupos: string[]; itens: string[] }

const MODULOS_REL: Record<string, string> = { movimentos: "Movimentos", estoque: "Estoque", financeiro: "Financeiro", cadastros: "Cadastros", relatorios: "Relatórios" };

/** lista com grupos marcáveis (pasta inteira / grupo de tipos) e itens soltos, com busca */
function Seletor({ grupos, rotuloGrupo, valor, mudar, placeholder }: { grupos: GrupoSel[]; rotuloGrupo: string; valor: Sel; mudar: (s: Sel) => void; placeholder: string }) {
  const [busca, setBusca] = useState("");
  const q = busca.trim().toLowerCase();
  const gs = new Set(valor.grupos), its = new Set(valor.itens);
  const n = its.size + grupos.filter((g) => gs.has(g.chave)).reduce((a, g) => a + g.itens.length, 0);
  const visiveis = grupos.map((g) => ({ g, itens: g.itens.filter((it) => !q || it.nome.toLowerCase().includes(q) || it.chave.toLowerCase().includes(q) || g.nome.toLowerCase().includes(q)) }))
    .filter((x) => x.itens.length);
  return <>
    <div className="picker-barra"><input className="campo" type="search" placeholder={placeholder} value={busca} onChange={(e) => setBusca(e.target.value)} /><span className="nota">{`${n} marcado(s)`}</span></div>
    <div className="picker">
      {visiveis.map(({ g, itens }) => {
        const inteiro = gs.has(g.chave);
        const parcial = g.itens.filter((it) => its.has(it.chave)).length;
        return (
          <details key={g.chave + (q ? "?" : "")} className="picker-grupo" open={!!q || grupos.length === 1}>
            <summary>
              <input type="checkbox" title={rotuloGrupo} checked={inteiro} onClick={(e) => e.stopPropagation()}
                onChange={(e) => mudar({ ...valor, grupos: e.target.checked ? [...valor.grupos, g.chave] : valor.grupos.filter((x) => x !== g.chave) })} />
              <span>{` ${g.nome} `}</span>
              <span className="tag">{parcial && !inteiro ? `${parcial}/${g.itens.length}` : String(g.itens.length)}</span>
            </summary>
            {itens.map((it) => (
              <label key={it.chave} className="check picker-item">
                <input type="checkbox" checked={inteiro || its.has(it.chave)} disabled={inteiro}
                  onChange={(e) => mudar({ ...valor, itens: e.target.checked ? [...valor.itens, it.chave] : valor.itens.filter((x) => x !== it.chave) })} />
                <span>{it.nome}</span>
                {it.extra && <span className="tag">{it.extra}</span>}
              </label>
            ))}
          </details>
        );
      })}
      {!visiveis.length && <p className="nota">Nada encontrado.</p>}
    </div>
  </>;
}

interface Form {
  id: number | null; login: string; nome: string; senha: string; admin: boolean; ativo: boolean; modulos: string[];
  bancosModo: string; bancos: string[]; relModo: string; rel: Sel; tiposModo: string; tipos: Sel; empresaSite: string;
}
const vazio = (empresa: string): Form => ({
  id: null, login: "", nome: "", senha: "", admin: false, ativo: true, modulos: [], bancosModo: "todos", bancos: [],
  relModo: "todos", rel: { grupos: [], itens: [] }, tiposModo: "todos", tipos: { grupos: [], itens: [] }, empresaSite: empresa,
});

function StatusSync({ avisar }: { avisar: (m: string) => void }) {
  const [d, setD] = useState<any>(null);   // eslint-disable-line @typescript-eslint/no-explicit-any
  const [erro, setErro] = useState("");
  const timer = useRef<number>();
  const ler = async (depois?: boolean) => {
    try {
      const x = await api<any>("/api/rb/sync");   // eslint-disable-line @typescript-eslint/no-explicit-any
      setD(x); setErro("");
      const e = x.estado || {};
      if (e.andamento || depois) timer.current = window.setTimeout(() => ler(false), 3000);
    } catch (e) { setErro((e as Error).message); }
  };
  useEffect(() => { ler(); return () => window.clearTimeout(timer.current); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const sincronizar = async (forcar: boolean) => {
    try { await api("/api/rb/sync", { forcar }); window.clearTimeout(timer.current); ler(true); } catch (e) { avisar((e as Error).message); }
  };
  const e = d?.estado || {}, r = e.resultado || {};
  const m = e.resultado_mudanca || {};
  const mudancas = [...(m.nomes_novos || []).map((n: string) => "novo: " + n), ...(m.nomes_alterados || []).map((n: string) => "alterado: " + n)].slice(0, 8);
  return (
    <div className="cartao c12"><div className="cartao-cab"><h2>Sincronização com o ReportBuilder</h2>
      <button className="btn pequeno primario" onClick={() => sincronizar(false)}>Sincronizar agora</button>
      <button className="btn pequeno" title="Converte de novo todos os relatórios (demora alguns minutos)" onClick={() => sincronizar(true)}>Reconverter todos</button></div>
      <p className="nota" style={{ fontSize: 13, margin: 0 }}>O painel confere sozinho o ReportBuilder do banco conectado e traz relatórios novos, alterados, movidos ou excluídos. Os ajustes feitos no painel (rb_ajustes.json) são mantidos.</p>
      <div style={{ marginTop: 8, fontSize: 13 }}>
        {erro ? erro : d && <>
          <div>{`${d.varios ? `Empresa ${d.empresa}: ` : ""}${d.total} relatórios no painel · verificação automática ${d.automatico ? `a cada ${d.automatico} min` : "desligada (config.ini)"}`}</div>
          {e.andamento ? <div>{`Sincronizando… (iniciado ${e.inicio})`}</div>
            : e.ultima ? <div>{`Última verificação: ${e.ultima}` + (r.total !== undefined ? ` · ${r.novos} novo(s), ${r.alterados} alterado(s), ${r.removidos} removido(s) em ${r.segundos}s` : "")}</div>
            : <div>Ainda não sincronizado com o banco.</div>}
          {e.ultima_mudanca && e.resultado_mudanca && <div className="nota">{`Última mudança encontrada: ${e.ultima_mudanca}` + (mudancas.length ? " — " + mudancas.join("; ") : "")}</div>}
          {e.erro && <div className="aviso erro">{"Erro: " + e.erro}</div>}
          {r.erros && r.erros.length > 0 && <div className="aviso atencao">{`${r.erros.length} relatório(s) não puderam ser lidos: ${r.erros.slice(0, 5).join("; ")}`}</div>}
        </>}
      </div>
    </div>
  );
}

function TesteRB({ avisar }: { avisar: (m: string) => void }) {
  const [txt, setTxt] = useState("");
  const timer = useRef<number>();
  const ler = async () => {
    try {
      const d = await api<{ relatorios: unknown[]; teste?: { total?: number; andamento?: boolean; feitos?: number; inicio?: string; com_erro?: number } }>("/api/rb");
      const t = d.teste || {};
      if (!t.total) { setTxt(`${d.relatorios.length} relatórios importados. Ainda não testados.`); return; }
      setTxt(t.andamento ? `Testando… ${t.feitos} de ${t.total}` : `Último teste (${t.inicio}): ${t.total} relatórios, ${t.com_erro || 0} com erro. Os com erro aparecem marcados em Relatórios.`);
      if (t.andamento) timer.current = window.setTimeout(ler, 4000);
    } catch (e) { setTxt((e as Error).message); }
  };
  useEffect(() => { ler(); return () => window.clearTimeout(timer.current); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="cartao c12"><div className="cartao-cab"><h2>Teste dos relatórios do ReportBuilder</h2>
      <button className="btn pequeno" onClick={async () => { try { await api("/api/rb/testar", {}); window.clearTimeout(timer.current); ler(); } catch (e) { avisar((e as Error).message); } }}>Testar todos no banco</button></div>
      <p className="gtick" style={{ fontSize: 13, margin: 0 }}>Executa cada relatório importado (1 linha, filtros vazios) para marcar os que dão erro. Leva alguns minutos; pode continuar usando o painel.</p>
      <p style={{ margin: "8px 0 0" }}>{txt}</p>
    </div>
  );
}

export default function Admin() {
  const avisar = useAvisar();
  const [cat, setCat] = useState<Catalogo | null>(null);
  const [dados, setDados] = useState<RespUsuarios | null>(null);
  const [f, setF] = useState<Form>(vazio(""));
  const [status, setStatus] = useState<{ banco: string; seguranca?: any } | null>(null);   // eslint-disable-line @typescript-eslint/no-explicit-any
  const [erroStatus, setErroStatus] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const mudar = (p: Partial<Form>) => setF((x) => ({ ...x, ...p }));

  const carregar = async () => {
    const d = await api<RespUsuarios>("/api/usuarios");
    setDados(d);
  };
  useEffect(() => {
    api<Catalogo>("/api/admin/catalogo").then((c) => { setCat(c); setF(vazio(c.site && (c.bancos || []).length > 1 ? c.empresa_id || "" : "")); })
      .catch((e) => avisar("Não foi possível carregar a lista de relatórios/tipos: " + e.message));
    (async () => {
      try {
        await carregar();
        setStatus(await api("/api/status"));
      } catch (e) { avisar((e as Error).message); setErroStatus((e as Error).message); }
    })();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // no TP DASH online (vários bancos) o usuário novo vai para a empresa escolhida; fora dele, escolhe as empresas que acessa
  const site = !!(cat && cat.site && (cat.bancos || []).length > 1);
  const listaBancos = cat && !site && (cat.bancos || []).length > 1 ? cat.bancos! : [];
  const outraEmpresa = site && f.empresaSite !== cat!.empresa_id;

  const gruposRel: GrupoSel[] = (() => {
    if (!cat) return [];
    const porPasta = new Map<string, GrupoSel["itens"]>();
    cat.relatorios.forEach((r) => {
      if (!porPasta.has(r.pasta)) porPasta.set(r.pasta, []);
      porPasta.get(r.pasta)!.push({ chave: r.chave, nome: r.nome, extra: (r.antigo ? "antigo · " : "") + (MODULOS_REL[r.modulo] || r.modulo) });
    });
    const peso = (a: string) => (a === "Relatórios prontos" ? -2 : a === "Consultas salvas" ? -1 : 0);
    return [...porPasta.keys()].sort((a, b) => peso(a) - peso(b) || a.localeCompare(b, "pt-BR")).map((p) => ({ chave: p, nome: p, itens: porPasta.get(p)! }));
  })();
  const gruposTipos: GrupoSel[] = (() => {
    if (!cat) return [];
    const porGrupo = new Map<string, GrupoSel["itens"]>();
    cat.tipos.forEach((t) => {
      const gk = t.cod.split(".").slice(0, 2).join(".");
      if (!porGrupo.has(gk)) porGrupo.set(gk, []);
      porGrupo.get(gk)!.push({ chave: t.cod, nome: `${t.cod} - ${t.nome}` });
    });
    return [...porGrupo.keys()].sort().map((k) => ({ chave: k + ".*", nome: `Grupo ${k}`, itens: porGrupo.get(k)! }));
  })();

  function editar(u: Usuario | null) {
    const rel = u && u.relatorios, tip = (u && u.tipos_mov) || [];
    setF({
      id: u ? u.id : null, login: u ? u.login : "", nome: u ? u.nome : "", senha: "", admin: !!(u && u.admin), ativo: !u || !!u.ativo,
      modulos: u ? [...u.modulos] : [], bancosModo: u && u.bancos ? "escolher" : "todos", bancos: (u && u.bancos) || [],
      relModo: rel ? "escolher" : "todos", rel: { grupos: rel ? rel.pastas : [], itens: rel ? rel.ids : [] },
      tiposModo: tip.length ? "escolher" : "todos", tipos: { grupos: tip.filter((x) => x.endsWith("*")), itens: tip.filter((x) => !x.endsWith("*")) },
      empresaSite: site ? cat!.empresa_id || "" : "",
    });
    formRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  async function salvar(e: FormEvent) {
    e.preventDefault();
    const d: Record<string, unknown> = {
      id: f.id, login: f.login, nome: f.nome, senha: f.senha, admin: f.admin, ativo: f.ativo, modulos: f.modulos,
      relatorios: f.relModo === "escolher" ? { pastas: f.rel.grupos, ids: f.rel.itens } : null,
      tipos_mov: f.tiposModo === "escolher" ? [...f.tipos.grupos, ...f.tipos.itens] : [],
      bancos: listaBancos.length > 1 && f.bancosModo === "escolher" ? f.bancos : null,
    };
    if (site && !f.id) d.empresa = f.empresaSite;
    if (d.bancos && !(d.bancos as string[]).length && !f.admin) { avisar("Marque pelo menos uma empresa ou escolha \"Todas as empresas\"."); return; }
    if (f.tiposModo === "escolher" && !(d.tipos_mov as string[]).length) { avisar("Marque pelo menos um tipo de movimento ou escolha \"Todos os tipos\"."); return; }
    try {
      const r = await api<{ nome_empresa?: string }>("/api/usuarios", d);
      avisar(r.nome_empresa ? `Usuário salvo na empresa ${r.nome_empresa}.` : "Usuário salvo.", "atencao");
      editar(null);
      await carregar();
    } catch (err) { avisar((err as Error).message); }
  }

  const modulos = dados?.modulos || {};
  const cols = ["id", "login", "nome", "admin", "modulos", ...(listaBancos.length > 1 ? ["bancos"] : []), "relatorios", "tipos_mov", "ativo", "trocar_senha", "ultimo_acesso"];
  const nomeBanco = (id: string) => (listaBancos.find((b) => b.id === id) || { nome: id }).nome;
  const tabUsuarios: DadosTabela | null = dados && {
    colunas: cols,
    linhas: dados.usuarios.map((u) => cols.map((c) =>
      c === "admin" ? (u.admin ? "Sim" : "Não") : c === "ativo" ? (u.ativo ? "Ativo" : "Inativo") :
      c === "modulos" ? u.modulos.map((m) => modulos[m]).join(", ") :
      c === "relatorios" ? (u.relatorios ? `${u.relatorios.pastas.length} pasta(s), ${u.relatorios.ids.length} relatório(s)` : "Todos") :
      c === "tipos_mov" ? (u.tipos_mov.length ? u.tipos_mov.join(", ") : "Todos") :
      c === "bancos" ? (u.bancos ? u.bancos.map(nomeBanco).join(", ") : "Todas") : (u as unknown as Record<string, unknown>)[c])),
  };
  const tabAcessos: DadosTabela | null = dados && { colunas: ["quando", "usuario", "acao", "detalhe"], linhas: dados.acessos.map((a) => [a.quando, a.usuario, a.acao, a.detalhe]) };

  const sg = status?.seguranca || {};
  const textoSeg = sg.https && sg.site ? "Conexão criptografada (HTTPS) ativa."
    : sg.https ? `Conexão criptografada (HTTPS) ativa. Certificado SHA-256: ${sg.certificado_sha256 || "-"}. Celulares: abra /certificado.cer para instalar.` + (sg.ip_restrito ? " Acesso limitado aos IPs de [servidor] permitir." : "")
    : "Conexão SEM criptografia (HTTP): senhas e dados passam abertos pela rede. " + (sg.site ? "Abra o site pelo endereço https://." : "Ative https = sim no config.ini e rode proteger_instalacao.bat (veja o LEIA-ME).");
  const radio = (nome: keyof Form, valor: string, rot: string) => (
    <label className="check"><input type="radio" name={nome} value={valor} checked={f[nome] === valor} onChange={() => mudar({ [nome]: valor } as Partial<Form>)} />{" " + rot}</label>
  );

  return <>
    <div className="aviso atencao" style={{ display: "flex", gap: 8 }}><strong>Banco:</strong><span>{status ? status.banco : erroStatus || "verificando…"}</span></div>
    {status && <div className={"aviso " + (sg.https ? "atencao" : "erro")} style={{ marginTop: 8 }}>{textoSeg}</div>}
    {status && sg.enderecos && sg.enderecos.length > 0 && (
      <div className="aviso" style={{ marginTop: 8 }}>
        {`Endereços deste servidor: ${sg.enderecos.join("  |  ")}. ` +
          (sg.nome_local ? (sg.nome_local_ativo ? `Nome na rede ${sg.nome_local}: anunciando.` : `Nome na rede ${sg.nome_local}: não está anunciando (${sg.nome_local_erro || "iniciando"}).`) : "Nome na rede desativado ([servidor] nome_local).") +
          (sg.certificado_nomes && sg.certificado_nomes.length ? ` Certificado aceita: ${sg.certificado_nomes.join(", ")}.` : "")}
      </div>
    )}
    <div className="grade">
      <div className="cartao c7" style={{ alignSelf: "start" }}>
        <div className="cartao-cab"><h2>Usuários <span className="sub">· clique para editar</span></h2><button className="btn pequeno primario" onClick={() => editar(null)}>Novo usuário</button></div>
        <Tabela dados={tabUsuarios} ocultar={["id", "trocar_senha"]} rotulos={{ relatorios: "Relatórios", tipos_mov: "Tipos mov.", bancos: "Empresas" }}
          onClick={(r) => editar(dados!.usuarios.find((u) => u.id === r[0]) || null)} />
      </div>
      <div className="cartao c5">
        <div className="cartao-cab"><h2>{f.id ? `Editar ${f.login}` : "Novo usuário"}</h2></div>
        <form ref={formRef} autoComplete="off" style={{ display: "flex", flexDirection: "column", gap: 12 }} onSubmit={salvar}>
          <div className="form-grade">
            <label>Login<input name="login" className="campo" required value={f.login} onChange={(e) => mudar({ login: e.target.value })} /></label>
            <label>Nome<input name="nome" className="campo" required value={f.nome} onChange={(e) => mudar({ nome: e.target.value })} /></label>
            <label>Senha<input name="senha" type="password" className="campo" autoComplete="new-password"
              placeholder={f.id ? "Deixe vazio para manter a senha" : "Senha inicial"} value={f.senha} onChange={(e) => mudar({ senha: e.target.value })} /></label>
          </div>
          <div><div className="gtick" style={{ fontSize: 12, marginBottom: 6 }}>Módulos liberados</div>
            <div className="form-grade" style={{ gridTemplateColumns: "repeat(2,1fr)", gap: 6 }}>
              {Object.entries(modulos).map(([k, v]) => (
                <label key={k} className="check"><input type="checkbox" name="modulos" value={k} checked={f.modulos.includes(k)}
                  onChange={(e) => mudar({ modulos: e.target.checked ? [...f.modulos, k] : f.modulos.filter((m) => m !== k) })} />{v}</label>
              ))}
            </div>
          </div>
          {site && (
            <div className="perm">
              <div className="perm-tit">Empresa do usuário</div>
              <select name="empresa_site" className="campo" value={f.empresaSite} disabled={!!f.id} onChange={(e) => mudar({ empresaSite: e.target.value })}>
                {(cat!.bancos || []).map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
              </select>
              <p className="nota" style={{ margin: "6px 0 0" }}>{outraEmpresa
                ? "O usuário será cadastrado na empresa escolhida. Relatórios e tipos de movimento ficam como \"todos\"; ajuste depois entrando na empresa dele."
                : "O usuário será cadastrado nesta empresa."}</p>
            </div>
          )}
          {listaBancos.length > 1 && (
            <div className="perm">
              <div className="perm-tit">Empresas (bancos) que pode acessar</div>
              {radio("bancosModo", "todos", "Todas as empresas")}
              {radio("bancosModo", "escolher", "Só as empresas que eu escolher")}
              <div className="picker-box lista-bancos" hidden={f.bancosModo !== "escolher"}>
                {listaBancos.map((b) => (
                  <label key={b.id} className="check"><input type="checkbox" name="bancos" value={b.id} checked={f.bancos.includes(b.id)}
                    onChange={(e) => mudar({ bancos: e.target.checked ? [...f.bancos, b.id] : f.bancos.filter((x) => x !== b.id) })} />{" " + b.nome}</label>
                ))}
              </div>
            </div>
          )}
          <div className="perm" hidden={outraEmpresa}>
            <div className="perm-tit">Relatórios que aparecem para este usuário <span className="nota">{listaBancos.length > 1 && cat ? `· relatórios do ReportBuilder da empresa em uso (${cat.empresa}); para escolher os de outra empresa, troque a empresa no topo. As escolhas das outras empresas são mantidas.` : ""}</span></div>
            {radio("relModo", "todos", "Todos os relatórios dos módulos liberados")}
            {radio("relModo", "escolher", "Só os relatórios que eu escolher")}
            <div className="picker-box" hidden={f.relModo !== "escolher"}>
              <Seletor grupos={gruposRel} rotuloGrupo="Liberar a pasta inteira" valor={f.rel} mudar={(rel) => mudar({ rel })} placeholder="Buscar relatório ou pasta" />
              <p className="nota">Marcar a pasta inteira libera também os relatórios que forem criados nela depois.</p>
            </div>
          </div>
          <div className="perm" hidden={outraEmpresa}>
            <div className="perm-tit">Tipos de movimento que pode consultar</div>
            {radio("tiposModo", "todos", "Todos os tipos")}
            {radio("tiposModo", "escolher", "Só os tipos que eu escolher")}
            <div className="picker-box" hidden={f.tiposModo !== "escolher"}>
              <Seletor grupos={gruposTipos} rotuloGrupo="Liberar o grupo inteiro" valor={f.tipos} mudar={(tipos) => mudar({ tipos })} placeholder="Buscar tipo (código ou nome)" />
              <p className="nota">Marcar o grupo (ex.: 2.2) libera também os tipos novos desse grupo. Vale para Início, Movimentos, ficha do cliente e relatórios (filtro de tipo e colunas CODTMV). Não é permitido junto com Consulta SQL.</p>
            </div>
          </div>
          <label className="check"><input type="checkbox" name="admin" checked={f.admin} onChange={(e) => mudar({ admin: e.target.checked })} /> Administrador (acessa tudo e gerencia usuários)</label>
          <label className="check"><input type="checkbox" name="ativo" checked={f.ativo} onChange={(e) => mudar({ ativo: e.target.checked })} /> Ativo</label>
          <p className="gtick" style={{ fontSize: 12, margin: 0 }}>Na primeira entrada (ou após troca de senha pelo administrador) o usuário é obrigado a definir uma senha própria.</p>
          <div><button className="btn primario">Salvar usuário</button></div>
        </form>
      </div>
      <StatusSync avisar={avisar} />
      <TesteRB avisar={avisar} />
      <div className="cartao c12"><div className="cartao-cab"><h2>Últimos acessos e ações</h2></div><Tabela dados={tabAcessos} /></div>
    </div>
  </>;
}
