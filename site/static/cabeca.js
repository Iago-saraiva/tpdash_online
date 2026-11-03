/* Executa antes de desenhar a página: tema salvo, registro do service worker e instalação como app. */
try { var t = localStorage.getItem("tema"); if (t) document.documentElement.dataset.tema = t; } catch (e) { /* sem armazenamento */ }
(function () {
  var pedido = null;
  var estado = {
    swFalhou: false,
    swOk: false,
    instalado: !!(window.matchMedia && (window.matchMedia("(display-mode: standalone)").matches ||
      window.matchMedia("(display-mode: window-controls-overlay)").matches)),
    disponivel: function () { return !!pedido; },
    instalar: function () {
      if (!pedido) return Promise.resolve(false);
      var p = pedido;
      p.prompt();
      return p.userChoice.then(function (r) { pedido = null; atualizar(); return r && r.outcome === "accepted"; });
    },
  };
  window.PainelInstalar = estado;     // usado pelo app.js (botão "Instalar app" do topo)

  window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); pedido = e; atualizar(); });
  window.addEventListener("appinstalled", function () { pedido = null; estado.instalado = true; atualizar(); });
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    navigator.serviceWorker.register("/sw.js")
      .then(function () { estado.swOk = true; atualizar(); })
      .catch(function () { estado.swFalhou = true; atualizar(); });
  }

  /* botão flutuante: no celular e na tela de login (no PC, dentro do painel, fica o botão do topo) */
  function atualizar() {
    document.dispatchEvent(new Event("painel-instalacao"));
    if (window.PainelApp || !document.body) return;          // dentro do app Android não precisa instalar nada
    var b = document.getElementById("instalar-app");
    var celular = window.matchMedia("(max-width: 900px)").matches;
    var login = document.body.classList.contains("login-pag");
    if (document.body.classList.contains("instalar-pag")) return;   // a página /instalar tem o próprio guia
    if (pedido && !estado.instalado && (celular || login)) {
      if (!b) {
        b = document.createElement("button");
        b.id = "instalar-app"; b.type = "button"; b.className = "instalar-app";
        b.textContent = "Instalar app";
        b.onclick = function () { estado.instalar(); };
        document.body.appendChild(b);
      }
    } else if (b) {
      b.remove();
    }
    if (!pedido && estado.swFalhou && celular && location.protocol === "https:" && !document.getElementById("aviso-cert")) {
      var a = document.createElement("div");
      a.id = "aviso-cert"; a.className = "instalar-app aviso-cert";
      a.textContent = "Para instalar como app, instale antes o certificado do painel. ";
      var l = document.createElement("a"); l.href = "/certificado.cer"; l.textContent = "Baixar certificado";
      a.appendChild(l);
      document.body.appendChild(a);
    }
  }
  document.addEventListener("DOMContentLoaded", atualizar);

  // app Android: opção para trocar o endereço do servidor
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.PainelApp || !window.PainelApp.configurar) return;
    var l = document.createElement("a");
    l.href = "#"; l.textContent = "Trocar servidor";
    l.onclick = function (e) { e.preventDefault(); window.PainelApp.configurar(); };
    var rod = document.querySelector(".lateral .rodape");
    if (rod) { rod.appendChild(document.createElement("br")); rod.appendChild(l); return; }
    l.className = "trocar-servidor";
    document.body.appendChild(l);
  });
})();
