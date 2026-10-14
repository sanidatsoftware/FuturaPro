// Service worker del player: tiene una copia della pagina e del motore, così il
// monitor riparte anche se all'accensione il server non risponde.
// Rete prima (per prendere subito gli aggiornamenti), copia salvata se la rete manca.
// Le chiamate alle API e i file dei contenuti non passano di qui: li gestisce avvio.js.

const CACHE = "futurapro-app-v6";
const FILE = [
  "/player/",
  "/static/player/avvio.js",
  "/static/player/motore.js",
  "/static/player/regole.js",
  "/static/player/schermo.css",
  "/static/player/vendor/hls.min.js",
  "/static/player/vendor/html2canvas.min.js",
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
  evento.respondWith(
    conLimite(evento.request, 5000)
      .then((risposta) => {
        if (risposta.ok) {
          const copia = risposta.clone();
          caches.open(CACHE).then((cache) => cache.put(chiave, copia));
        }
        return risposta;
      })
      .catch(() => caches.match(chiave).then((salvata) => salvata || Response.error())),
  );
});
