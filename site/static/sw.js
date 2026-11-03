/* Service worker do TP DASH: permite instalar como aplicativo.
   Os dados sempre vêm do servidor (nada da empresa fica guardado no celular);
   sem rede, mostra uma tela avisando que o servidor não está acessível. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
const OFFLINE = '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>TP DASH</title><style>body{font-family:system-ui,sans-serif;background:#13253d;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center;padding:24px}button{margin-top:16px;padding:10px 20px;border:0;border-radius:8px;background:#2a78d6;color:#fff;font-size:16px}</style></head>' +
  '<body><div><h2>TP DASH</h2><p>Não foi possível falar com o servidor.<br>Confira se o aparelho está na rede da empresa (Wi-Fi ou VPN).<br>' +
  'Se o servidor estiver reiniciando, a tela volta sozinha.</p><p id="t" style="opacity:.75"></p><button onclick="location.reload()">Tentar agora</button></div>' +
  '<script>var n=0;function v(){n++;document.getElementById("t").textContent="Tentando de novo... ("+n+")";' +
  'fetch("/saude",{cache:"no-store"}).then(function(r){if(r.ok)location.reload();else setTimeout(v,5000)}).catch(function(){setTimeout(v,5000)})}' +
  'setTimeout(v,3000);window.addEventListener("online",function(){location.reload()});</script></body></html>';
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;           // demais pedidos seguem direto para a rede
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
