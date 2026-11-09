// "Instalar app": botão do topo e janela com as opções (navegador, celular, app Windows).
import { useEffect, useState } from "react";
import { baixar, painelApp } from "../api";

interface PainelInstalar {
  instalado?: boolean; swFalhou?: boolean;
  disponivel?: () => boolean; instalar?: () => Promise<boolean>;
}
// preparado pelo cabeca.js, que roda antes da página aparecer
const pi = (): PainelInstalar => (window as unknown as { PainelInstalar?: PainelInstalar }).PainelInstalar || {};

export function useInstalacao() {
  const [, setN] = useState(0);
  useEffect(() => {
    const f = () => setN((n) => n + 1);
    document.addEventListener("painel-instalacao", f);
    return () => document.removeEventListener("painel-instalacao", f);
  }, []);
  const p = pi();
  return { oculto: !!painelApp || !!p.instalado, disponivel: !!(p.disponivel && p.disponivel()) };
}

export function JanelaInstalar({ fechar }: { fechar: () => void }) {
  const p = pi();
  const [erro, setErro] = useState("");
  const ua = navigator.userAgent;
  const edge = /Edg\//.test(ua), chrome = /Chrome\//.test(ua) && !edge, firefox = /Firefox\//.test(ua);
  const celular = window.matchMedia("(max-width: 900px)").matches;
  let passos: string;
  if (celular) passos = "No celular: Chrome (Android) → menu ⋮ → Instalar app. iPhone: Safari → Compartilhar → Adicionar à Tela de Início.";
  else if (edge) passos = "No Edge: menu ··· (canto superior direito) → Aplicativos → Instalar este site como um aplicativo → Instalar.";
  else if (chrome) passos = "No Chrome: clique no ícone de instalar na barra de endereço (monitor com seta, à direita) ou menu ⋮ → Transmitir, salvar e compartilhar → Instalar página como app.";
  else if (firefox) passos = "O Firefox não instala sites como aplicativo. Use o Edge ou o Chrome, ou a opção 2 abaixo.";
  else passos = "Abra o painel no Edge ou no Chrome e use a opção de instalar do navegador, ou a opção 2 abaixo.";
  return (
    <div className="modal-fundo" onClick={(e) => { if (e.target === e.currentTarget) fechar(); }}>
      <div className="modal instalar-modal">
        <div className="modal-cab"><h2>Instalar o TP DASH como aplicativo</h2><button className="btn pequeno" onClick={fechar}>Fechar ✕</button></div>
        <div className="modal-corpo">
          {erro && <div className="aviso erro">{erro}</div>}
          <section className="ed-secao">
            <h3>1. Instalar pelo navegador (recomendado)</h3>
            <p className="nota">Cria o ícone "TP DASH" na Área de Trabalho e no Menu Iniciar. Abre em janela própria, sem barra de endereço, como um programa do Windows. Atualiza sozinho junto com o painel.</p>
            {p.disponivel && p.disponivel()
              ? <button className="btn primario" onClick={async () => { if (p.instalar && await p.instalar()) fechar(); }}>Instalar agora</button>
              : p.swFalhou && location.protocol === "https:"
                ? <div className="aviso atencao">Este computador ainda não confia no certificado do painel, por isso o navegador não oferece a instalação. Use a opção 2 (ela instala o certificado) ou peça ao responsável para rodar o criar_atalho.bat neste computador.</div>
                : <div className="nota" style={{ fontSize: 13 }}>{passos}</div>}
          </section>
          {!celular && (
            <section className="ed-secao">
              <h3>No celular</h3>
              <div className="qr-linha">
                <img className="qr" src="/qr.svg" width={150} height={150} alt="QR Code da página de instalação" />
                <div className="nota">Aponte a câmera do celular para o código (na rede da empresa). Abre a página com o passo a passo para instalar no Android ou iPhone: <a href="/instalar" target="_blank">{location.origin + "/instalar"}</a></div>
              </div>
            </section>
          )}
          {!celular && (
            <section className="ed-secao">
              <h3>2. Baixar o app para Windows</h3>
              <p className="nota">Pacote com o TPDash.exe já configurado para este servidor (e o certificado de segurança). Extraia o .zip numa pasta (ex.: C:\TPDash) e rode criar_atalho.bat: ele instala o certificado e cria o atalho na Área de Trabalho e no Menu Iniciar. Funciona mesmo se o navegador não oferecer a instalação.</p>
              <button className="btn" onClick={() => baixar("/app-windows.zip").catch((e) => setErro(e.message))}>Baixar app para Windows (.zip)</button>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
