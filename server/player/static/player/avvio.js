// Avvio della pagina: come player (abbinamento, cache, segnale periodico) oppure
// come anteprima nel pannello (dati letti con la sessione dell'utente).

import { Motore } from "./motore.js";

const VERSIONE = "web-0.1";
const OGNI_MANIFEST = 30_000;
const OGNI_HEARTBEAT = 60_000;
const OGNI_STATO = 5_000;
const CACHE_FILE = "futurapro-file";

const radice = document.getElementById("schermo");
const avviso = document.getElementById("avviso");
const impostazioni = document.body.dataset;

function memoria(chiave, valore) {
  try {
    if (valore === undefined) return localStorage.getItem(chiave);
    if (valore === null) localStorage.removeItem(chiave);
    else localStorage.setItem(chiave, valore);
  } catch {
    return null;
  }
}

function mostraAvviso(titolo, testo, codice) {
  avviso.hidden = false;
  avviso.replaceChildren();
  const h = document.createElement("h1");
  h.textContent = titolo;
  avviso.appendChild(h);
  if (codice) {
    const c = document.createElement("div");
    c.className = "codice";
    c.textContent = codice.replace(/(\d{3})(\d{3})/, "$1 $2");
    avviso.appendChild(c);
  }
  const p = document.createElement("p");
  p.textContent = testo;
  avviso.appendChild(p);
}

const nascondiAvviso = () => (avviso.hidden = true);
const attendi = (ms) => new Promise((ok) => setTimeout(ok, ms));

// --- File: Cache API dove c'è (HTTPS o localhost), altrimenti solo in memoria ----

const inMemoria = new Map();

async function fileConCache(id, voce, scarica) {
  const chiave = `/file/${voce.sha256}`;
  if (inMemoria.has(chiave)) return inMemoria.get(chiave);
  let risposta;
  let cache = null;
  try {
    cache = await caches.open(CACHE_FILE);
    risposta = await cache.match(chiave);
  } catch {
    cache = null;
  }
  if (!risposta) {
    try {
      risposta = await scarica();
    } catch {
      return null; // offline e non ancora in cache
    }
    if (!risposta.ok) return null;
    if (cache) await cache.put(chiave, risposta.clone()).catch(() => {});
  }
  const url = URL.createObjectURL(await risposta.blob());
  inMemoria.set(chiave, url);
  return url;
}

// I file che non sono più nel manifest si tolgono dalla cache.
async function pulisciCache(manifest) {
  const validi = new Set(Object.values(manifest.contenuti).filter((v) => v.sha256).map((v) => `/file/${v.sha256}`));
  try {
    const cache = await caches.open(CACHE_FILE);
    for (const richiesta of await cache.keys()) {
      if (!validi.has(new URL(richiesta.url).pathname)) await cache.delete(richiesta);
    }
  } catch {
    // Nessuna Cache API: niente da pulire.
  }
  for (const [chiave, url] of inMemoria) {
    if (!validi.has(chiave)) {
      URL.revokeObjectURL(url);
      inMemoria.delete(chiave);
    }
  }
}

// --- Player --------------------------------------------------------------------

function nuovoToken() {
  const byte = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...byte)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function piattaforma() {
  return /android/i.test(navigator.userAgent) ? "android" : "windows";
}

async function abbina() {
  for (;;) {
    let token = memoria("futurapro.token");
    if (!token) {
      token = nuovoToken();
      memoria("futurapro.token", token);
    }
    const intestazioni = { Authorization: `Device ${token}` };
    let stato;
    try {
      stato = await fetch("/api/player/stato/", { headers: intestazioni });
    } catch {
      mostraAvviso("Server non raggiungibile", "Riprovo tra qualche secondo…");
      await attendi(OGNI_STATO);
      continue;
    }
    if (stato.ok) {
      const dati = await stato.json();
      if (dati.abbinato) return token;
      mostraAvviso("Abbina questo schermo", "Inserisci il codice nel pannello FuturaPro, in Monitor → Abbina.", dati.codice);
      await attendi(OGNI_STATO);
      continue;
    }
    // Token sconosciuto o codice scaduto: se ne chiede uno nuovo.
    const richiesta = await fetch("/api/player/abbinamento/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, piattaforma: piattaforma(), info: { userAgent: navigator.userAgent, schermo: `${screen.width}x${screen.height}` } }),
    }).catch(() => null);
    if (richiesta?.status === 400) memoria("futurapro.token", null); // token già usato: se ne genera un altro
    if (!richiesta?.ok) await attendi(OGNI_STATO);
  }
}

async function avviaPlayer() {
  const token = await abbina();
  const intestazioni = { Authorization: `Device ${token}` };
  const motore = new Motore(radice, {
    file: (id, voce) => (voce ? fileConCache(id, voce, () => fetch(voce.url, { headers: intestazioni })) : Promise.resolve(null)),
    dati: async (zonaId) => (await fetch(`/api/player/zone/${zonaId}/dati/`, { headers: intestazioni })).json(),
    emetti: async (zonaId, reparto) => {
      const risposta = await fetch(`/api/player/zone/${zonaId}/emetti/`, {
        method: "POST",
        headers: { ...intestazioni, "Content-Type": "application/json" },
        body: JSON.stringify({ reparto }),
      });
      if (!risposta.ok) throw new Error(risposta.status);
      return risposta.json();
    },
  });

  // All'avvio, l'ultimo manifest ricevuto: lo schermo riparte anche senza rete.
  const salvato = memoria("futurapro.manifest");
  if (salvato) {
    nascondiAvviso();
    motore.mostra(JSON.parse(salvato));
  }

  let etichetta = null;
  const aggiorna = async () => {
    try {
      const risposta = await fetch("/api/player/palinsesto/", {
        headers: { ...intestazioni, ...(etichetta ? { "If-None-Match": etichetta } : {}) },
      });
      if (risposta.status === 401) {
        // Credenziale revocata o monitor rimosso: si torna all'abbinamento.
        memoria("futurapro.token", null);
        memoria("futurapro.manifest", null);
        location.reload();
        return;
      }
      if (risposta.status === 304 || !risposta.ok) return;
      etichetta = risposta.headers.get("ETag");
      const manifest = await risposta.json();
      memoria("futurapro.manifest", JSON.stringify(manifest));
      nascondiAvviso();
      motore.mostra(manifest);
      pulisciCache(manifest);
    } catch {
      // Offline: si continua con quello che c'è.
    }
  };
  await aggiorna();
  setInterval(aggiorna, OGNI_MANIFEST);

  const battito = () =>
    fetch("/api/player/heartbeat/", {
      method: "POST",
      headers: { ...intestazioni, "Content-Type": "application/json" },
      body: JSON.stringify({ versione: VERSIONE }),
    }).catch(() => {});
  battito();
  setInterval(battito, OGNI_HEARTBEAT);
}

// --- Anteprima nel pannello ----------------------------------------------------

async function avviaAnteprima() {
  const monitor = impostazioni.monitor;
  const cliente = new URLSearchParams(location.search).get("cliente");
  const intestazioni = cliente ? { "X-Cliente": cliente } : {};
  const leggi = async (url) => {
    const risposta = await fetch(url, { headers: intestazioni, credentials: "same-origin" });
    if (!risposta.ok) throw new Error(risposta.status);
    return risposta;
  };
  const motore = new Motore(radice, {
    file: (id, voce) => (voce ? fileConCache(id, voce, () => leggi(`/api/contenuti/${id}/file/`)) : Promise.resolve(null)),
    dati: async (zonaId) => (await leggi(`/api/zone/${zonaId}/dati/?monitor=${monitor}`)).json(),
    // In anteprima non si emettono biglietti veri.
    emetti: async () => ({ reparto: "Anteprima", colore: "#5a5a5a", numero: 0, davanti: 0 }),
  });
  const aggiorna = async () => {
    try {
      const manifest = await (await leggi(`/api/anteprima/${monitor}/manifest/`)).json();
      nascondiAvviso();
      motore.mostra(manifest);
    } catch (errore) {
      mostraAvviso("Anteprima non disponibile", errore.message === "403" ? "Accedi al pannello." : "Monitor inesistente.");
    }
  };
  await aggiorna();
  setInterval(aggiorna, 15_000);
}

if (impostazioni.modo === "anteprima") avviaAnteprima();
else avviaPlayer();
