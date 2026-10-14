// Avvio della pagina: come player (abbinamento, cache, segnale periodico) oppure
// come anteprima nel pannello (dati letti con la sessione dell'utente).

import { Motore } from "./motore.js";

const VERSIONE = "web-0.2";
const OGNI_MANIFEST = 30_000;
const OGNI_HEARTBEAT = 60_000;
const OGNI_STATO = 5_000;
// Ogni quanto il player chiede se il pannello vuole una fotografia dello schermo.
const OGNI_SCHERMATA = 8_000;
const LARGHEZZA_SCHERMATA = 960;
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

// I file audio dei numeri chiamati (annunci registrati): { id, sha256, url } per ognuno.
function fileAnnunci(manifest) {
  const voci = [];
  for (const serie of Object.values(manifest.annunci?.serie || {})) {
    for (const [id, sha256] of [...Object.values(serie.numeri), ...(serie.predefinito ? [serie.predefinito] : [])]) {
      voci.push({ id, sha256, url: `/api/player/annunci/${id}/` });
    }
  }
  return voci;
}

// I file che non sono più nel manifest si tolgono dalla cache.
async function pulisciCache(manifest) {
  const validi = new Set([...Object.values(manifest.contenuti), ...fileAnnunci(manifest)].filter((v) => v.sha256).map((v) => `/file/${v.sha256}`));
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

// Scarica in cache tutti i file di un manifest, prima di mostrarlo: così non manca
// mai una slide, e se la rete cade dopo, il monitor ha già tutto. Restituisce
// false se qualcosa non è arrivato (si riprova al giro successivo).
async function preparaFile(manifest, scarica, voci = Object.values(manifest.contenuti)) {
  let cache;
  try {
    cache = await caches.open(CACHE_FILE);
  } catch {
    return true; // niente Cache API (pagina non sicura): i file arrivano quando servono
  }
  let completo = true;
  for (const voce of voci) {
    if (!voce.sha256) continue;
    const chiave = `/file/${voce.sha256}`;
    if (await cache.match(chiave)) continue;
    try {
      const risposta = await scarica(voce);
      if (!risposta.ok) throw new Error(risposta.status);
      await cache.put(chiave, risposta);
    } catch {
      completo = false;
    }
  }
  return completo;
}

// Una richiesta che non resta appesa: il servizio code o il server potrebbero non rispondere.
async function conLimite(url, opzioni = {}, ms = 8000) {
  const controllo = new AbortController();
  const limite = setTimeout(() => controllo.abort(), ms);
  try {
    return await fetch(url, { ...opzioni, signal: controllo.signal });
  } finally {
    clearTimeout(limite);
  }
}

// Meteo, notizie e code: l'ultimo dato ricevuto resta salvato e si usa se la fonte non risponde.
async function conRiserva(chiave, leggi) {
  try {
    const dati = await leggi();
    memoria(`futurapro.dati.${chiave}`, JSON.stringify(dati));
    return dati;
  } catch (errore) {
    const salvato = memoria(`futurapro.dati.${chiave}`);
    if (salvato) return JSON.parse(salvato);
    throw errore;
  }
}

// --- Code del negozio: sul totem o sul server -----------------------------------
//
// Se la sede ha un totem, le code le tiene il suo servizio (porta 8443): i monitor
// leggono i numeri da lì, il totem stesso emette i biglietti in locale. Il totem si
// riconosce perché solo il suo manifest porta la configurazione dei reparti.

const SERVIZIO_LOCALE = "https://127.0.0.1:8443";

function serviziCode(manifest) {
  const code = manifest?.code;
  if (!code || code.modo !== "totem") return null;
  return code.reparti ? SERVIZIO_LOCALE : code.indirizzo;
}

function zonaDelManifest(manifest, zonaId) {
  return manifest?.layout?.zone.find((z) => z.id === zonaId);
}

async function codeDalTotem(indirizzo, zona) {
  const risposta = await conLimite(`${indirizzo}/stato`, {}, 5000);
  if (!risposta.ok) throw new Error(risposta.status);
  const { reparti } = await risposta.json();
  const scelti = zona.configurazione.reparti || [];
  if (!scelti.length) return { code: reparti };
  const perId = new Map(reparti.map((r) => [r.id, r]));
  return { code: scelti.map((id) => perId.get(id)).filter(Boolean) };
}

// La configurazione dei reparti passa dal manifest al servizio code del totem.
let configInviata = null;
async function inviaConfigCode(manifest, scarica) {
  const reparti = manifest?.code?.reparti;
  if (!reparti) return;
  // Con la configurazione va l'elenco degli annunci da tenere: gli altri il servizio li cancella.
  const annunci = fileAnnunci(manifest);
  const firma = JSON.stringify([reparti, annunci.map((v) => v.sha256)]);
  if (firma !== configInviata) {
    try {
      const risposta = await conLimite(`${SERVIZIO_LOCALE}/config`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reparti, annunci: annunci.map((v) => v.sha256) }),
      });
      if (risposta.ok) configInviata = firma;
    } catch {
      return; // servizio code non ancora partito: si riprova al prossimo giro
    }
  }
  await copiaAnnunciSulTotem(annunci, scarica);
}

// I file degli annunci restano anche sul totem: i monitor del negozio li prendono da lì,
// e li suonano anche quando il server o internet non rispondono.
let copiaInCorso = false;
async function copiaAnnunciSulTotem(annunci, scarica) {
  if (copiaInCorso || !annunci.length) return;
  copiaInCorso = true;
  try {
    const presenti = new Set((await (await conLimite(`${SERVIZIO_LOCALE}/annunci`)).json()).file || []);
    let cache = null;
    try {
      cache = await caches.open(CACHE_FILE);
    } catch {
      cache = null;
    }
    for (const voce of annunci) {
      if (presenti.has(voce.sha256)) continue;
      const risposta = (cache && (await cache.match(`/file/${voce.sha256}`))) || (await scarica(voce).catch(() => null));
      if (!risposta?.ok) continue;
      await conLimite(`${SERVIZIO_LOCALE}/annunci/${voce.sha256}`, { method: "POST", body: await risposta.blob() }).catch(() => {});
    }
  } catch {
    // Si riprova al prossimo giro.
  } finally {
    copiaInCorso = false;
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
  // Già abbinato e con un manifest salvato: si parte subito, anche senza server.
  // Se nel frattempo il monitor è stato rimosso, il primo aggiornamento lo scopre.
  const salvato = memoria("futurapro.manifest");
  const token = memoria("futurapro.token") && salvato ? memoria("futurapro.token") : await abbina();
  const intestazioni = { Authorization: `Device ${token}` };
  const scaricaFile = (voce) => conLimite(voce.url, { headers: intestazioni }, 120_000);
  // Gli annunci dei numeri: prima dal totem del negozio (rete locale), poi dal server.
  const scaricaAnnuncio = async (voce) => {
    const totem = serviziCode(motore.manifest);
    if (totem) {
      const locale = await conLimite(`${totem}/annunci/${voce.sha256}`, {}, 5000).catch(() => null);
      if (locale?.ok) return locale;
    }
    return scaricaFile(voce);
  };
  const motore = new Motore(radice, {
    file: (id, voce) => (voce ? fileConCache(id, voce, () => scaricaFile(voce)) : Promise.resolve(null)),
    annuncio: (voce) => fileConCache(voce.id, voce, () => scaricaAnnuncio(voce)),
    dati: (zonaId) =>
      conRiserva(zonaId, async () => {
        const zona = zonaDelManifest(motore.manifest, zonaId);
        const totem = serviziCode(motore.manifest);
        if (totem && zona && (zona.tipo === "coda" || zona.tipo === "prendi_numero")) return codeDalTotem(totem, zona);
        const risposta = await conLimite(`/api/player/zone/${zonaId}/dati/`, { headers: intestazioni });
        if (!risposta.ok) throw new Error(risposta.status);
        return risposta.json();
      }),
    emetti: async (zonaId, reparto) => {
      const totem = serviziCode(motore.manifest);
      const risposta = totem
        ? await conLimite(`${SERVIZIO_LOCALE}/emetti/${reparto}`, { method: "POST" }, 5000)
        : await conLimite(`/api/player/zone/${zonaId}/emetti/`, {
          method: "POST",
          headers: { ...intestazioni, "Content-Type": "application/json" },
          body: JSON.stringify({ reparto }),
        });
      if (!risposta.ok) throw new Error(risposta.status);
      return risposta.json();
    },
  });

  // All'avvio, l'ultimo manifest ricevuto: lo schermo riparte anche senza rete.
  let mostrato = null;
  if (salvato) {
    mostrato = JSON.parse(salvato);
    nascondiAvviso();
    motore.mostra(mostrato);
    inviaConfigCode(mostrato, scaricaFile);
  }

  let etichetta = null;
  let inCorso = false;
  const aggiorna = async () => {
    if (inCorso) return; // un download lungo non si sovrappone al successivo
    inCorso = true;
    try {
      const risposta = await conLimite("/api/player/palinsesto/", {
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
      const manifest = await risposta.json();
      // Il nuovo palinsesto va in onda solo quando tutti i suoi file sono sul monitor.
      const pronto = await preparaFile(manifest, scaricaFile);
      if (!pronto && mostrato) return; // si riprova al prossimo giro, intanto resta il precedente
      etichetta = risposta.headers.get("ETag");
      mostrato = manifest;
      memoria("futurapro.manifest", JSON.stringify(manifest));
      nascondiAvviso();
      motore.mostra(manifest);
      // Gli annunci dei numeri si scaricano dopo, senza far aspettare le slide.
      pulisciCache(manifest).then(() => preparaFile(manifest, scaricaAnnuncio, fileAnnunci(manifest)));
      battito();
    } catch {
      // Offline: si continua con quello che c'è.
    } finally {
      inCorso = false;
      inviaConfigCode(mostrato, scaricaFile);
    }
  };

  // Il segnale periodico dice anche quale versione del palinsesto è in onda.
  const battito = () =>
    fetch("/api/player/heartbeat/", {
      method: "POST",
      headers: { ...intestazioni, "Content-Type": "application/json" },
      body: JSON.stringify({ versione: VERSIONE, manifest: mostrato?.versione || "", problema: motore.problema || null }),
    }).catch(() => {});
  await aggiorna();
  setInterval(aggiorna, OGNI_MANIFEST);
  battito();
  setInterval(battito, OGNI_HEARTBEAT);

  // Fotografia dello schermo su richiesta del pannello.
  let scatto = false;
  setInterval(async () => {
    if (scatto || document.hidden) return;
    try {
      const risposta = await conLimite("/api/player/schermata/", { headers: intestazioni }, 5000);
      if (!risposta.ok || !(await risposta.json()).richiesta) return;
      scatto = true;
      const foto = await fotografaSchermo(motore);
      const dati = new FormData();
      dati.append("immagine", foto, "schermo.jpg");
      await conLimite("/api/player/schermata/", { method: "POST", headers: intestazioni, body: dati }, 20000);
    } catch {
      // Offline o fotografia non riuscita: si riproverà alla prossima richiesta.
    } finally {
      scatto = false;
    }
  }, OGNI_SCHERMATA);
}

// --- Fotografia dello schermo -------------------------------------------------------
// html2canvas ridisegna la pagina; video e dirette li si ricopia fotogramma per
// fotogramma. Quello che il browser non lascia copiare (una diretta di un altro sito
// senza permessi, una pagina web) diventa un riquadro con il suo nome.

function caricaScript(percorso, globale) {
  if (window[globale]) return Promise.resolve(window[globale]);
  return new Promise((ok, ko) => {
    const script = document.createElement("script");
    script.src = new URL(percorso, import.meta.url).href;
    script.onload = () => ok(window[globale]);
    script.onerror = () => ko(new Error(`${percorso} non caricato`));
    document.head.appendChild(script);
  });
}

function copiabile(video) {
  try {
    const prova = document.createElement("canvas");
    prova.width = prova.height = 1;
    const c = prova.getContext("2d");
    c.drawImage(video, 0, 0, 1, 1);
    c.getImageData(0, 0, 1, 1);
    return true;
  } catch {
    return false;
  }
}

function riquadro(contesto, r, testo) {
  contesto.fillStyle = "#101828";
  contesto.fillRect(r.x, r.y, r.w, r.h);
  contesto.fillStyle = "#c9d3e3";
  contesto.font = `${Math.max(12, Math.round(r.h / 10))}px system-ui, sans-serif`;
  contesto.textAlign = "center";
  contesto.textBaseline = "middle";
  contesto.fillText(testo, r.x + r.w / 2, r.y + r.h / 2);
}

// La posizione di un elemento nel palco, alla misura vera dello schermo (1920×1080 o
// 1080×1920): le coordinate «offset» non risentono di scala e rotazione del palco.
function posizioneNelPalco(el, palco) {
  let x = 0;
  let y = 0;
  for (let n = el; n && n !== palco; n = n.offsetParent) {
    x += n.offsetLeft;
    y += n.offsetTop;
  }
  return { x, y, w: el.offsetWidth, h: el.offsetHeight };
}

async function fotografaSchermo(motore) {
  const html2canvas = await caricaScript("./vendor/html2canvas.min.js", "html2canvas");
  const palco = motore.palco;
  const { larghezza, altezza } = motore.dimensioni;
  const scala = Math.min(1, LARGHEZZA_SCHERMATA / Math.max(larghezza, altezza));
  // Si fotografa una copia del palco alla sua misura vera, senza scala né rotazione:
  // lo schermo vero non cambia e la foto è dritta anche per un televisore montato in verticale.
  const tela = await html2canvas(palco, {
    backgroundColor: "#000000", scale: scala, logging: false, useCORS: true,
    width: larghezza, height: altezza, windowWidth: larghezza, windowHeight: altezza, x: 0, y: 0, scrollX: 0, scrollY: 0,
    ignoreElements: (el) => el.tagName === "VIDEO" || el.tagName === "IFRAME",
    onclone: (_, copia) => Object.assign(copia.style, { transform: "none", left: "0px", top: "0px" }),
  });
  const contesto = tela.getContext("2d");
  // html2canvas lascia la tela con la sua scala: si torna ai pixel veri della foto.
  contesto.setTransform(1, 0, 0, 1, 0, 0);
  for (const el of palco.querySelectorAll("video, iframe")) {
    const p = posizioneNelPalco(el, palco);
    if (!p.w || !p.h) continue;
    const r = { x: p.x * scala, y: p.y * scala, w: p.w * scala, h: p.h * scala };
    const nome = el.dataset.nome || "";
    if (el.tagName === "IFRAME") {
      riquadro(contesto, r, `🌐 ${nome || "pagina web"}`);
    } else if (el.readyState >= 2 && copiabile(el)) {
      // Come «adatta»: il fotogramma intero, centrato nel suo riquadro.
      const rapporto = Math.min(r.w / el.videoWidth, r.h / el.videoHeight);
      const w = el.videoWidth * rapporto;
      const h = el.videoHeight * rapporto;
      contesto.fillStyle = "#000";
      contesto.fillRect(r.x, r.y, r.w, r.h);
      contesto.drawImage(el, r.x + (r.w - w) / 2, r.y + (r.h - h) / 2, w, h);
    } else {
      // Una diretta di un altro sito senza permessi: il browser non la lascia copiare.
      riquadro(contesto, r, `📡 ${nome || "diretta"} · in onda`);
    }
  }
  // Ora dello scatto, in basso a destra.
  const ora = new Date().toLocaleTimeString("it-IT");
  contesto.font = "bold 14px system-ui, sans-serif";
  contesto.textAlign = "right";
  contesto.textBaseline = "bottom";
  contesto.fillStyle = "rgba(0,0,0,.6)";
  contesto.fillRect(tela.width - 86, tela.height - 24, 86, 24);
  contesto.fillStyle = "#fff";
  contesto.fillText(ora, tela.width - 8, tela.height - 5);
  return new Promise((ok, ko) => tela.toBlob((blob) => (blob ? ok(blob) : ko(new Error("fotografia vuota"))), "image/jpeg", 0.78));
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
    annuncio: (voce) => fileConCache(voce.id, voce, () => leggi(`/api/annunci/ascolta/${voce.id}/`)),
    dati: async (zonaId) => (await leggi(`/api/zone/${zonaId}/dati/?monitor=${monitor}`)).json(),
    // In anteprima non si emettono biglietti veri.
    emetti: async () => ({ reparto: "Anteprima", colore: "#5a5a5a", numero: 0, davanti: 0, anteprima: true }),
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

if (impostazioni.modo === "anteprima") {
  avviaAnteprima();
} else {
  // Il player si salva nel browser: riparte anche se all'accensione il server non risponde.
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/player/sw.js", { scope: "/player/" }).catch(() => {});
  avviaPlayer();
}
