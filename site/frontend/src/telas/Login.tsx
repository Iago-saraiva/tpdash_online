// Telas de entrada e de troca de senha. O formulário é enviado normalmente ao Flask (POST), como antes.
import { DADOS } from "../dados";
import { painelApp } from "../api";

function TrocarServidor() {
  if (!painelApp?.configurar) return null;
  return <a href="#" className="trocar-servidor" onClick={(e) => { e.preventDefault(); painelApp?.configurar?.(); }}>Trocar servidor</a>;
}

export function Login() {
  const bancos = DADOS.bancos_login || [];
  return (
    <>
      <form className="login-box" method="post">
        <img src="/static/logo-tpdash-preto.svg" width={48} height={48} alt="TP DASH" className="logo-tpdash" />
        <h1>TP DASH</h1>
        {!bancos.length && <p>{DADOS.empresa}</p>}
        {DADOS.erro && <div className="aviso erro">{DADOS.erro}</div>}
        <input type="hidden" name="csrf" value={DADOS.csrf} />
        {bancos.length > 0 && (
          <label>Empresa<select name="banco" className="sel-empresa" defaultValue={DADOS.banco_sel}>
            {bancos.map((b) => <option key={b.id} value={b.id}>{b.nome}</option>)}
          </select></label>
        )}
        <label>Login<input name="login" autoFocus autoComplete="username" required /></label>
        <label>Senha<input name="senha" type="password" autoComplete="current-password" required /></label>
        {DADOS.lembrar && <label className="check lembrar"><input type="checkbox" name="lembrar" value="1" /> Manter conectado neste aparelho</label>}
        <button className="btn primario">Entrar</button>
        <a className="link-instalar" href="/instalar">Instalar o app no celular ou no computador</a>
      </form>
      <TrocarServidor />
    </>
  );
}

export function TrocarSenha() {
  return (
    <form className="login-box" method="post">
      <h1>Defina sua senha</h1>
      <p>Escolha uma senha pessoal com pelo menos 6 caracteres (letras, números ou os dois).</p>
      {DADOS.erro && <div className="aviso erro">{DADOS.erro}</div>}
      <input type="hidden" name="csrf" value={DADOS.csrf} />
      <label>Senha atual<input name="atual" type="password" autoComplete="current-password" required /></label>
      <label>Nova senha<input name="nova" type="password" autoComplete="new-password" minLength={6} required /></label>
      <label>Confirme a nova senha<input name="confirma" type="password" autoComplete="new-password" minLength={6} required /></label>
      <button className="btn primario">Salvar e entrar</button>
      <a href="/sair" style={{ textAlign: "center", fontSize: 13 }}>Sair</a>
    </form>
  );
}
