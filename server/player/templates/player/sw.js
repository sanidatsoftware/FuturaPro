// Service worker del player: tiene una copia della pagina e del motore, così il
// monitor riparte anche se all'accensione il server non risponde.
// Rete prima (per prendere subito gli aggiornamenti), copia salvata se la rete manca.
// Le chiamate alle API e i file dei contenuti non passano di qui: li gestisce avvio.js.

// Il nome cambia da solo con la versione del player (player/versione.py): una versione nuova
// prende una copia nuova e cancella le vecchie.
const CACHE = "futurapro-app-{{ versione }}";
const FILE = [
  "/player/",
  "/static/player/avvio.js",
  "/static/player/motore.js",
  "/static/player/plugin.js",
  "/static/player/ticket.js",
  "/static/player/regole.js",
  "/static/player/schermo.css",
  "/static/player/plugin.css",
  "/static/player/vendor/hls.min.js",
  "/static/player/vendor/html2canvas.min.js",
  "/static/player/vendor/qrcode.js",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(FILE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((nomi) => Promise.all(nomi.filter((n) => n.startsWith("futurapro-app-") && n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

function conLimite(richiesta, ms) {
  return Promise.race([fetch(richiesta), new Promise((_, no) => setTimeout(() => no(new Error("tempo")), ms))]);
}

self.addEventListener("fetch", (evento) => {
  const url = new URL(evento.request.url);
  if (evento.request.method !== "GET" || url.origin !== location.origin) return;
  const chiave = url.pathname === "/player/" || evento.request.mode === "navigate" ? "/player/" : url.pathname;
  if (!FILE.includes(chiave)) return;
  // I moduli arrivano con la loro versione nell'indirizzo («?v=»): la copia si tiene per
  // indirizzo completo, così senza rete la pagina salvata trova proprio i suoi file.
  const completa = chiave === "/player/" ? chiave : url.pathname + url.search;
  evento.respondWith(
    conLimite(evento.request, 5000)
      .then((risposta) => {
        if (risposta.ok) {
          const copia = risposta.clone();
          caches.open(CACHE).then((cache) => cache.put(completa, copia));
        }
        return risposta;
      })
      .catch(() => caches.match(completa).then((salvata) => salvata || caches.match(chiave)).then((salvata) => salvata || Response.error())),
  );
});
