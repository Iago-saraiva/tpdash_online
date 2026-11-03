/* Página /instalar: guia para instalar o TP DASH como app (celular e PC). */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const ua = navigator.userAgent;
  const iphone = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const android = /Android/.test(ua);
  const celular = iphone || android;
  const edge = /Edg\//.test(ua), samsung = /SamsungBrowser/.test(ua), firefox = /Firefox|FxiOS/.test(ua);
  const chrome = /Chrome\/|CriOS/.test(ua) && !edge && !samsung;
  const safari = iphone && !/CriOS|FxiOS|EdgiOS/.test(ua);
  const https = document.body.dataset.https === "1";
  const pi = () => window.PainelInstalar || {};

  function el(tag, cls, txt) { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; }
  function lista(itens) { const ol = el("ol", "passos-lista"); itens.forEach((t) => ol.appendChild(el("li", "", t))); return ol; }
  function status(id, ok, txt) { const s = $(id); s.textContent = txt; s.className = "passo-status " + (ok === true ? "ok" : ok === false ? "pendente" : ""); }

  function render() {
    const est = pi();
    // ---------------------------------------------- 1. certificado
    const cc = $("#cert-corpo");
    cc.replaceChildren();
    if (!https) {
      status("#st-cert", false, "sem HTTPS");
      cc.appendChild(el("p", "nota", "O servidor está sem HTTPS. Para instalar como app, o responsável precisa ativar https = sim no config.ini do servidor (veja SEGURANCA.txt)."));
    } else if (est.swOk || est.instalado) {
      status("#st-cert", true, "✓ pronto");
      cc.appendChild(el("p", "nota", "Este aparelho já confia no certificado do painel."));
    } else if (est.swFalhou) {
      status("#st-cert", false, "falta o certificado");
      cc.appendChild(el("p", "nota", "Instale o certificado de segurança do painel (só uma vez por aparelho):"));
      const b = el("a", "btn primario", "Baixar certificado");
      b.href = "/certificado.cer";
      cc.appendChild(b);
      if (iphone) {
        cc.appendChild(lista([
          "Toque em Baixar certificado e em Permitir (\"Perfil transferido\").",
          "Abra Ajustes → Perfil Transferido → Instalar (digite o código do iPhone) → Instalar.",
          "Ajustes → Geral → Sobre → Ajustes de Confiança de Certificados → ligue \"TP DASH\".",
          "Volte aqui e recarregue a página.",
        ]));
      } else if (android) {
        cc.appendChild(lista([
          "Toque em Baixar certificado.",
          "Configurações → Segurança → Criptografia e credenciais → Instalar certificado → Certificado CA → Instalar mesmo assim → escolha tp-dash.cer.",
          "Feche o navegador por completo (tire da lista de apps abertos) e abra esta página de novo.",
        ]));
      } else {
        cc.appendChild(lista([
          "Toque em Baixar certificado e abra o arquivo.",
          "Instalar Certificado → Usuário Atual → Colocar todos os certificados no repositório a seguir → Autoridades de Certificação Raiz Confiáveis → Concluir → Sim.",
          "Feche o navegador e abra esta página de novo.",
        ]));
      }
      cc.appendChild(el("p", "nota", "Confira a impressão digital (SHA-256) com a que aparece em Administração no painel."));
    } else {
      status("#st-cert", null, "verificando…");
    }

    // ---------------------------------------------- 2. instalar
    const ic = $("#inst-corpo");
    ic.replaceChildren();
    if (est.instalado) {
      status("#st-inst", true, "✓ instalado");
      ic.appendChild(el("p", "nota", "Você já está usando o app."));
      return;
    }
    if (est.disponivel && est.disponivel()) {
      status("#st-inst", null, "");
      const b = el("button", "btn primario grande", "Instalar app");
      b.type = "button";
      b.onclick = () => est.instalar().then((ok) => { if (ok) render(); });
      ic.appendChild(b);
      ic.appendChild(el("p", "nota", celular ? "O ícone \"TP DASH\" aparece na tela inicial e abre em tela cheia." :
        "O ícone \"TP DASH\" aparece na Área de Trabalho e no Menu Iniciar e abre em janela própria."));
      return;
    }
    status("#st-inst", null, "");
    let passos;
    if (iphone && !safari) passos = ["No iPhone a instalação é pelo Safari: copie o endereço desta página e abra no Safari."];
    else if (iphone) passos = ["Toque em Compartilhar (quadrado com seta, embaixo).", "Role e toque em Adicionar à Tela de Início.", "Toque em Adicionar."];
    else if (android && samsung) passos = ["Toque no menu ≡ (embaixo).", "Adicionar página a → Tela inicial."];
    else if (android && firefox) passos = ["Toque no menu ⋮ → Instalar (ou Adicionar à tela inicial)."];
    else if (android) passos = ["Toque no menu ⋮ (canto superior direito).", "Toque em Instalar app (ou Adicionar à tela inicial → Instalar)."];
    else if (edge) passos = ["Menu ··· (canto superior direito) → Aplicativos → Instalar este site como um aplicativo → Instalar."];
    else if (chrome) passos = ["Clique no ícone de instalar na barra de endereço (monitor com seta) ou menu ⋮ → Transmitir, salvar e compartilhar → Instalar página como app."];
    else passos = ["Abra esta página no Chrome ou no Edge e use a opção Instalar do navegador."];
    if (https && !est.swOk && !iphone) passos.unshift("Primeiro conclua o passo 1 (certificado); depois a opção de instalar aparece.");
    ic.appendChild(lista(passos));
  }

  // QR no computador, para abrir no celular
  if (!celular) {
    $("#passo-qr").hidden = false;
    $("#endereco").textContent = location.origin + "/instalar";
  }
  document.addEventListener("painel-instalacao", render);
  document.addEventListener("DOMContentLoaded", render);
  render();
  // se o service worker não responder (http sem localhost, navegador antigo), mostra o estado final
  setTimeout(() => { const e = pi(); if (!e.swOk && !e.swFalhou && https) { e.swFalhou = true; render(); } }, 4000);
})();
