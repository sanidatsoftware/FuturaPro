// Editor visuale dei layout: zone da aggiungere, spostare, ridimensionare e configurare.
//
// Lavora sulle stesse API del pannello (/api/layout/…): le regole (zone dentro lo
// schermo, campi obbligatori, reparti e contenuti del cliente) le controlla il
// server al salvataggio, e gli errori tornano sulla zona che li ha.
// I testi che arrivano dai dati passano sempre da textContent.

import { attivaAiuti } from "../pannello/aiuto.js";

const parametri = new URLSearchParams(location.search);
const cliente = parametri.get("cliente");
const suffisso = cliente ? `?cliente=${encodeURIComponent(cliente)}` : "";
const PASSO = 0.5; // griglia di aggancio, in % dello schermo
const MINIMO = 2;
const RISOLUZIONE = { orizzontale: [1920, 1080], verticale: [1080, 1920] };
// Formato immagini proposto se il layout non ne ha uno: A4 a 300 dpi per i totem, Full HD per i monitor.
const FORMATO_PREDEFINITO = { orizzontale: [1920, 1080], verticale: [2480, 3508] };

// --- API -----------------------------------------------------------------------

function cookie(nome) {
  const trovato = document.cookie.split("; ").find((c) => c.startsWith(`${nome}=`));
  return trovato ? decodeURIComponent(trovato.split("=")[1]) : "";
}

async function api(metodo, url, dati) {
  const intestazioni = { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken") };
  if (cliente) intestazioni["X-Cliente"] = cliente;
  const risposta = await fetch(url, {
    method: metodo, headers: intestazioni, credentials: "same-origin", body: dati ? JSON.stringify(dati) : undefined,
  });
  if (risposta.status === 401 || risposta.status === 403) {
    const corpo = await risposta.json().catch(() => ({}));
    throw Object.assign(new Error(corpo.detail || "Accesso non consentito."), { stato: risposta.status });
  }
  const corpo = risposta.status === 204 ? null : await risposta.json().catch(() => null);
  if (!risposta.ok) throw Object.assign(new Error("Errore"), { stato: risposta.status, corpo });
  return corpo;
}

const tutti = async (url) => (await api("GET", url)).results;

function crea(tag, attributi = {}, genitore = null) {
  const el = document.createElement(tag);
  for (const [chiave, valore] of Object.entries(attributi)) {
    if (chiave === "testo") el.textContent = valore;
    else if (chiave === "classe") el.className = valore;
    else if (chiave in el) el[chiave] = valore;
    else el.setAttribute(chiave, valore);
  }
  if (genitore) genitore.appendChild(el);
  return el;
}

function avvisa(testo, tipo = "errore") {
  const box = document.getElementById("messaggio");
  box.hidden = !testo;
  box.className = `messaggio ${tipo}`;
  box.textContent = testo || "";
}

// Al passaggio del mouse sui pulsanti per aggiungere le zone.
const SPIEGAZIONI = {
  slide: "Le immagini e i video in sequenza, con transizione: di solito le promozioni in onda sullo schermo.",
  orologio: "Ora e data, con colori e dimensioni a scelta.",
  meteo: "Il tempo di oggi nella località scelta (si aggiorna da solo).",
  notizie: "Il rullo che scorre con le notizie dei feed RSS scelti e i messaggi del negozio.",
  testo: "Una scritta fissa, es. un saluto o un orario.",
  immagine: "Un'immagine sempre ferma, es. il logo del negozio.",
  coda: "I numeri chiamati dei reparti (eliminacode), con il din-don quando cambiano.",
  prendi_numero: "I pulsanti del totem per prendere il numero e stampare il biglietto.",
};

// --- Tipi di zona e loro campi ----------------------------------------------------
// Rispecchiano server/layout/zone.py: i valori predefiniti li completa il server.

const TIPI = {
  slide: { nome: "Slide", colore: "#3d6fb6", dimensioni: [60, 60] },
  orologio: { nome: "Orologio", colore: "#1f4e79", dimensioni: [22, 16] },
  meteo: { nome: "Meteo", colore: "#2a6f97", dimensioni: [22, 16] },
  notizie: { nome: "Rullo notizie", colore: "#ec6a1f", dimensioni: [100, 12] },
  testo: { nome: "Testo", colore: "#5b5b5b", dimensioni: [40, 10] },
  immagine: { nome: "Immagine fissa", colore: "#7a5c99", dimensioni: [20, 20] },
  coda: { nome: "Numeri dei reparti", colore: "#c62828", dimensioni: [22, 50] },
  prendi_numero: { nome: "Prendi il numero", colore: "#ef6c00", dimensioni: [100, 33] },
};

const ALLINEAMENTO = [["sinistra", "Sinistra"], ["centro", "Centro"], ["destra", "Destra"]];
const ADATTAMENTO = [
  ["adatta", "Adatta (intera, senza tagli)"],
  ["sfondo", "Adatta con sfondo sfocato"],
  ["riempi", "Riempi (taglia i bordi)"],
  ["allunga", "Allunga (riempie deformando)"],
];

const CAMPI = {
  slide: [
    { nome: "sorgente", etichetta: "Cosa mostra", tipo: "playlist" },
    { nome: "transizione", etichetta: "Transizione", tipo: "scelta", valori: [["nessuna", "Nessuna"], ["dissolvenza", "Dissolvenza"], ["scorri_sinistra", "Scorrimento laterale"], ["scorri_alto", "Scorrimento verticale"], ["zoom", "Zoom"]], predefinito: "dissolvenza" },
    { nome: "durata_transizione", etichetta: "Durata transizione (ms)", tipo: "numero", min: 0, max: 5000, passo: 100, predefinito: 800 },
    { nome: "adattamento", etichetta: "Immagini", tipo: "scelta", valori: ADATTAMENTO, predefinito: "adatta" },
  ],
  orologio: [
    { nome: "mostra_data", etichetta: "Mostra la data", tipo: "si_no", predefinito: true },
    { nome: "secondi", etichetta: "Mostra i secondi", tipo: "si_no", predefinito: false },
    { nome: "colore", etichetta: "Colore testo", tipo: "colore", predefinito: "#ffffff" },
    { nome: "sfondo", etichetta: "Sfondo", tipo: "sfondo" },
    { nome: "allineamento", etichetta: "Allineamento", tipo: "scelta", valori: ALLINEAMENTO, predefinito: "centro" },
  ],
  meteo: [
    { nome: "localita", etichetta: "Località", tipo: "localita" },
    { nome: "colore", etichetta: "Colore testo", tipo: "colore", predefinito: "#ffffff" },
    { nome: "sfondo", etichetta: "Sfondo", tipo: "sfondo" },
  ],
  notizie: [
    { nome: "feed", etichetta: "Feed RSS (uno per riga)", tipo: "righe" },
    { nome: "messaggi", etichetta: "Messaggi propri (uno per riga)", tipo: "righe" },
    { nome: "velocita", etichetta: "Velocità (pixel al secondo)", tipo: "numero", min: 20, max: 400, passo: 10, predefinito: 80 },
    { nome: "aggiornamento_minuti", etichetta: "Aggiorna le notizie ogni (minuti)", tipo: "numero", min: 5, max: 240, passo: 5, predefinito: 15 },
    { nome: "colore", etichetta: "Colore testo", tipo: "colore", predefinito: "#ffffff" },
    { nome: "sfondo", etichetta: "Sfondo", tipo: "colore", predefinito: "#b00020" },
  ],
  testo: [
    { nome: "testo", etichetta: "Testo", tipo: "testo_lungo" },
    { nome: "dimensione", etichetta: "Dimensione (% dell'altezza)", tipo: "numero", min: 5, max: 100, passo: 5, predefinito: 50 },
    { nome: "colore", etichetta: "Colore testo", tipo: "colore", predefinito: "#ffffff" },
    { nome: "sfondo", etichetta: "Sfondo", tipo: "sfondo" },
    { nome: "allineamento", etichetta: "Allineamento", tipo: "scelta", valori: ALLINEAMENTO, predefinito: "centro" },
  ],
  immagine: [
    { nome: "contenuto", etichetta: "Immagine", tipo: "immagine" },
    { nome: "adattamento", etichetta: "Adattamento", tipo: "scelta", valori: ADATTAMENTO, predefinito: "adatta" },
  ],
  coda: [
    { nome: "reparti", etichetta: "Reparti", tipo: "reparti" },
    { nome: "disposizione", etichetta: "Disposizione", tipo: "scelta", valori: [["automatica", "Automatica"], ["colonna", "In colonna"], ["riga", "In riga"], ["griglia", "A griglia"]], predefinito: "automatica" },
    { nome: "testo_coda", etichetta: "Testo clienti in coda ({n} = numero; vuoto = nascosto)", tipo: "testo", predefinito: "" },
    { nome: "bordo", etichetta: "Bordo tra i riquadri", tipo: "si_no", predefinito: true },
    { nome: "annuncio", etichetta: "Alla chiamata", tipo: "scelta", valori: [["nessuno", "Solo lampeggio"], ["suono", "Din-don"], ["voce", "Din-don e voce"]], predefinito: "suono" },
    { nome: "personalizza", etichetta: "Aspetto dei reparti in questa zona", tipo: "personalizza" },
  ],
  prendi_numero: [
    { nome: "reparti", etichetta: "Reparti", tipo: "reparti" },
    { nome: "titolo", etichetta: "Titolo (vuoto = senza barra)", tipo: "testo", predefinito: "PRENDI QUI IL TUO NUMERO" },
    { nome: "colore", etichetta: "Colore titolo", tipo: "colore", predefinito: "#ffffff" },
    { nome: "sfondo", etichetta: "Sfondo titolo", tipo: "colore", predefinito: "#ec6a1f" },
    { nome: "sfondo_pulsanti", etichetta: "Sfondo dei pulsanti", tipo: "colore", predefinito: "#ffffff" },
    { nome: "colonne", etichetta: "Colonne di pulsanti (0 = automatico)", tipo: "numero", min: 0, max: 4, passo: 1, predefinito: 0 },
    { nome: "arrotondamento", etichetta: "Arrotondamento angoli (px)", tipo: "numero", min: 0, max: 60, passo: 2, predefinito: 14 },
    { nome: "testo_coda", etichetta: "Testo clienti in coda ({n} = numero; vuoto = nascosto)", tipo: "testo", predefinito: "Clienti in coda: {n}" },
    { nome: "stampa", etichetta: "Stampa del biglietto", tipo: "scelta", valori: [["nessuna", "Nessuna"], ["browser", "Stampante di sistema"], ["epson", "Stampante Epson di rete"]], predefinito: "nessuna" },
    { nome: "stampante", etichetta: "Indirizzo stampante Epson", tipo: "testo", predefinito: "" },
    { nome: "intestazione", etichetta: "Intestazione del biglietto", tipo: "testo", predefinito: "" },
    { nome: "messaggio", etichetta: "Messaggio sul biglietto", tipo: "testo", predefinito: "Attendi il tuo turno, grazie!" },
    { nome: "personalizza", etichetta: "Aspetto dei reparti in questa zona", tipo: "personalizza" },
  ],
};

// --- Stato dell'editor -------------------------------------------------------------

const stato = {
  layout: null, // come salvato sul server
  zone: [], // in modifica; ogni zona ha un _chiave locale
  selezionata: null,
  modificato: false,
  errori: new Map(), // _chiave -> messaggi dal server
  archivi: { playlist: [], immagini: [], reparti: [] },
};
let contatore = 0;
const nuovaChiave = () => `z${++contatore}`;
const arrotonda = (v) => Math.round(v / PASSO) * PASSO;
const limita = (v, min, max) => Math.min(Math.max(v, min), max);

function segnaModificato() {
  stato.modificato = true;
  document.getElementById("salva").classList.add("attenzione");
}

// --- Disegno del palco -------------------------------------------------------------

const palco = document.getElementById("palco");
const area = document.getElementById("area");

function adattaPalco() {
  if (!stato.layout) return;
  const [w, h] = RISOLUZIONE[stato.layout.orientamento];
  const spazio = area.getBoundingClientRect();
  const scala = Math.min((spazio.width - 32) / w, (spazio.height - 32) / h);
  Object.assign(palco.style, { width: `${w * scala}px`, height: `${h * scala}px` });
}

function anteprimaZona(el, zona) {
  // Una resa indicativa del contenuto: basta per capire cosa va dove.
  const c = zona.configurazione || {};
  const corpo = crea("div", { classe: "contenuto" }, el);
  const sfondo = c.sfondo || (zona.tipo === "notizie" ? "#b00020" : "");
  if (sfondo) el.style.background = sfondo;
  corpo.style.color = c.colore || "#ffffff";
  switch (zona.tipo) {
    case "slide": {
      const playlist = stato.archivi.playlist.find((p) => p.id === c.sorgente);
      crea("div", { classe: "grande", testo: "Slide" }, corpo);
      crea("div", { testo: playlist ? `Playlist «${playlist.nome}»` : "Palinsesto del monitor" }, corpo);
      break;
    }
    case "orologio":
      crea("div", { classe: "grande", testo: c.secondi ? "12:34:56" : "12:34" }, corpo);
      if (c.mostra_data !== false) crea("div", { testo: "Martedì 13 ottobre" }, corpo);
      break;
    case "meteo":
      crea("div", { classe: "grande", testo: "☀ 22°" }, corpo);
      crea("div", { testo: c.localita || "Scegli la località" }, corpo);
      break;
    case "notizie":
      crea("div", { classe: "rullo", testo: [...(c.messaggi || []), "Le notizie dei feed scorrono qui…"].join("  •  ") }, corpo);
      break;
    case "testo":
      crea("div", { classe: "grande", testo: c.testo || "Testo" }, corpo);
      break;
    case "immagine": {
      const immagine = stato.archivi.immagini.find((i) => i.id === c.contenuto);
      crea("div", { classe: "grande", testo: "🖼" }, corpo);
      crea("div", { testo: immagine ? immagine.nome : "Scegli l'immagine" }, corpo);
      break;
    }
    case "coda":
    case "prendi_numero": {
      corpo.classList.add(zona.tipo === "coda" ? "riquadri" : "pulsanti");
      if (zona.tipo === "prendi_numero" && c.titolo !== "") {
        const titolo = crea("div", { classe: "titolo", testo: c.titolo ?? "PRENDI QUI IL TUO NUMERO" }, el);
        Object.assign(titolo.style, { background: c.sfondo || "#ec6a1f", color: c.colore || "#fff" });
        el.insertBefore(titolo, corpo);
        el.style.background = c.sfondo_pulsanti || "#ffffff";
      }
      const scelti = c.reparti?.length ? c.reparti.map((id) => stato.archivi.reparti.find((r) => r.id === id)).filter(Boolean) : stato.archivi.reparti.slice(0, 3);
      for (const reparto of scelti) {
        const proprio = c.personalizza?.[reparto.id] || {};
        const blocco = crea("div", { classe: "reparto", testo: proprio.etichetta || reparto.nome }, corpo);
        Object.assign(blocco.style, { background: proprio.colore || reparto.colore, color: proprio.colore_testo || reparto.colore_testo });
        if (zona.tipo === "coda") crea("b", { testo: "27" }, blocco);
      }
      if (!scelti.length) crea("div", { testo: "Nessun reparto: creali nel pannello" }, corpo);
      break;
    }
  }
}

function disegna() {
  palco.replaceChildren();
  palco.style.background = stato.layout.sfondo;
  for (const zona of [...stato.zone].sort((a, b) => a.livello - b.livello)) {
    const el = crea("div", { classe: `zona tipo-${zona.tipo}` }, palco);
    el.dataset.chiave = zona._chiave;
    Object.assign(el.style, {
      left: `${zona.x}%`, top: `${zona.y}%`, width: `${zona.larghezza}%`, height: `${zona.altezza}%`,
      background: `${TIPI[zona.tipo].colore}cc`,
    });
    if (zona._chiave === stato.selezionata) el.classList.add("selezionata");
    if (stato.errori.has(zona._chiave)) el.classList.add("con-errore");
    anteprimaZona(el, zona);
    crea("span", { classe: "nome-tipo", testo: zona.nome || TIPI[zona.tipo].nome }, el);
    for (const lato of ["n", "s", "e", "o", "ne", "no", "se", "so"]) crea("span", { classe: `maniglia ${lato}` }, el).dataset.lato = lato;
    el.addEventListener("pointerdown", (evento) => iniziaTrascinamento(evento, zona));
  }
}

// --- Spostare e ridimensionare ------------------------------------------------------

function iniziaTrascinamento(evento, zona) {
  evento.preventDefault();
  evento.stopPropagation();
  seleziona(zona._chiave);
  const lato = evento.target.dataset.lato || "";
  const rettangolo = palco.getBoundingClientRect();
  const inizio = { x: evento.clientX, y: evento.clientY, zona: { ...zona } };
  const el = palco.querySelector(`[data-chiave="${zona._chiave}"]`);
  el.setPointerCapture(evento.pointerId);

  const muovi = (e) => {
    const dx = ((e.clientX - inizio.x) / rettangolo.width) * 100;
    const dy = ((e.clientY - inizio.y) / rettangolo.height) * 100;
    const p = inizio.zona;
    let { x, y, larghezza, altezza } = p;
    if (!lato) {
      x = limita(arrotonda(p.x + dx), 0, 100 - p.larghezza);
      y = limita(arrotonda(p.y + dy), 0, 100 - p.altezza);
    } else {
      if (lato.includes("e")) larghezza = limita(arrotonda(p.larghezza + dx), MINIMO, 100 - p.x);
      if (lato.includes("s")) altezza = limita(arrotonda(p.altezza + dy), MINIMO, 100 - p.y);
      if (lato.includes("o")) {
        x = limita(arrotonda(p.x + dx), 0, p.x + p.larghezza - MINIMO);
        larghezza = p.x + p.larghezza - x;
      }
      if (lato.includes("n")) {
        y = limita(arrotonda(p.y + dy), 0, p.y + p.altezza - MINIMO);
        altezza = p.y + p.altezza - y;
      }
    }
    Object.assign(zona, { x, y, larghezza, altezza });
    Object.assign(el.style, { left: `${x}%`, top: `${y}%`, width: `${larghezza}%`, height: `${altezza}%` });
    aggiornaGeometria(zona);
  };
  const fine = () => {
    el.removeEventListener("pointermove", muovi);
    el.removeEventListener("pointerup", fine);
    if (["x", "y", "larghezza", "altezza"].some((k) => zona[k] !== inizio.zona[k])) segnaModificato();
  };
  el.addEventListener("pointermove", muovi);
  el.addEventListener("pointerup", fine);
}

document.addEventListener("keydown", (e) => {
  const zona = stato.zone.find((z) => z._chiave === stato.selezionata);
  if (!zona || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  const passo = e.shiftKey ? 5 : PASSO;
  const spostamenti = { ArrowLeft: [-passo, 0], ArrowRight: [passo, 0], ArrowUp: [0, -passo], ArrowDown: [0, passo] };
  if (spostamenti[e.key]) {
    e.preventDefault();
    const [dx, dy] = spostamenti[e.key];
    zona.x = limita(arrotonda(zona.x + dx), 0, 100 - zona.larghezza);
    zona.y = limita(arrotonda(zona.y + dy), 0, 100 - zona.altezza);
    segnaModificato();
    disegna();
    aggiornaGeometria(zona);
  } else if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    elimina(zona);
  }
});

palco.addEventListener("pointerdown", (e) => {
  if (e.target === palco) seleziona(null);
});

// --- Pannello delle proprietà -------------------------------------------------------

const pannello = document.getElementById("proprieta");

function seleziona(chiave) {
  stato.selezionata = chiave;
  disegna();
  mostraProprieta();
}

function aggiornaGeometria(zona) {
  for (const k of ["x", "y", "larghezza", "altezza"]) {
    const campo = pannello.querySelector(`[data-geometria="${k}"]`);
    if (campo && document.activeElement !== campo) campo.value = zona[k];
  }
  // Le immagini preparate a questa misura riempiono la zona senza tagli né bande.
  const pixel = pannello.querySelector(".pixel");
  if (pixel) {
    const [w, h] = RISOLUZIONE[stato.layout.orientamento];
    pixel.textContent = `Immagini ideali: ${Math.round((w * zona.larghezza) / 100)} × ${Math.round((h * zona.altezza) / 100)} pixel`;
  }
  const confronto = pannello.querySelector(".confronto-formato");
  if (confronto) confronto.textContent = confrontaFormato(zona);
}

// Il formato è del layout (vale per tutte le sue zone), ma si imposta dalle zone che mostrano immagini.
function formato() {
  const { formato_larghezza: l, formato_altezza: a } = stato.formato;
  return l > 0 && a > 0 ? [l, a] : FORMATO_PREDEFINITO[stato.layout.orientamento];
}

// Quanto un'immagine del formato standard lascia di bande (con «Adatta») o perde (con «Riempi»).
function confrontaFormato(zona) {
  const [W, H] = RISOLUZIONE[stato.layout.orientamento];
  const [fl, fa] = formato();
  const zonaRapporto = (W * zona.larghezza) / (H * zona.altezza);
  const rapporto = fl / fa;
  const scarto = Math.round(Math.abs(1 - Math.min(zonaRapporto, rapporto) / Math.max(zonaRapporto, rapporto)) * 100);
  if (scarto < 2) return `Formato ${fl}×${fa}: la zona ha già le stesse proporzioni.`;
  const lati = zonaRapporto > rapporto ? "ai lati" : "sopra e sotto";
  const tagli = zonaRapporto > rapporto ? "sopra e sotto" : "ai lati";
  return `Formato ${fl}×${fa}: con «Adatta» resta vuoto il ${scarto}% ${lati}; con «Riempi» si taglia il ${scarto}% ${tagli}.`;
}

// Cambia la zona perché abbia le proporzioni del formato standard: tiene la larghezza
// e cambia l'altezza; se non c'è spazio in basso, tiene l'altezza e restringe la larghezza.
function proporzioniDelFormato(zona) {
  const [W, H] = RISOLUZIONE[stato.layout.orientamento];
  const [fl, fa] = formato();
  let larghezza = zona.larghezza;
  let altezza = (((W * larghezza) / 100) * (fa / fl) / H) * 100;
  let x = zona.x;
  if (altezza > 100 - zona.y) {
    altezza = 100 - zona.y;
    larghezza = (((H * altezza) / 100) * (fl / fa) / W) * 100;
    x = zona.x + (zona.larghezza - larghezza) / 2;
  }
  Object.assign(zona, { x: arrotonda(x), larghezza: arrotonda(larghezza), altezza: arrotonda(altezza) });
  segnaModificato();
  disegna();
  aggiornaGeometria(zona);
}

function cambia(zona, nome, valore) {
  zona.configurazione = { ...zona.configurazione, [nome]: valore };
  segnaModificato();
  disegna();
}

function campoColore(contenitore, valore, alCambio, vuotoAmmesso) {
  const riga = crea("div", { classe: "riga-colore" }, contenitore);
  const colore = crea("input", { type: "color", value: valore || "#000000" }, riga);
  let trasparente = null;
  if (vuotoAmmesso) {
    const etichetta = crea("label", { classe: "spunta" }, riga);
    trasparente = crea("input", { type: "checkbox", checked: !valore }, etichetta);
    etichetta.append(" trasparente");
    trasparente.addEventListener("change", () => alCambio(trasparente.checked ? "" : colore.value));
  }
  colore.addEventListener("input", () => {
    if (trasparente) trasparente.checked = false;
    alCambio(colore.value);
  });
}

function campoReparti(contenitore, zona) {
  const scelti = new Set(zona.configurazione.reparti || []);
  crea("p", { classe: "nota", testo: "Nessuno spuntato: tutti i reparti della sede del monitor." }, contenitore);
  for (const reparto of stato.archivi.reparti) {
    const etichetta = crea("label", { classe: "spunta" }, contenitore);
    const spunta = crea("input", { type: "checkbox", checked: scelti.has(reparto.id) }, etichetta);
    const pallino = crea("span", { classe: "pallino" }, etichetta);
    pallino.style.background = reparto.colore;
    etichetta.append(` ${reparto.nome}`);
    spunta.addEventListener("change", () => {
      spunta.checked ? scelti.add(reparto.id) : scelti.delete(reparto.id);
      // L'ordine è quello dei reparti nel pannello.
      cambia(zona, "reparti", stato.archivi.reparti.filter((r) => scelti.has(r.id)).map((r) => r.id));
    });
  }
}

function campoPersonalizza(contenitore, zona) {
  const valori = structuredClone(zona.configurazione.personalizza || {});
  const salva = () => cambia(zona, "personalizza", Object.fromEntries(Object.entries(valori).filter(([, v]) => Object.keys(v).length)));
  for (const reparto of stato.archivi.reparti) {
    const proprio = valori[reparto.id] || {};
    const blocco = crea("fieldset", { classe: "aspetto" }, contenitore);
    crea("legend", { testo: reparto.nome }, blocco);
    const etichetta = crea("input", { placeholder: `Etichetta (${reparto.nome})`, value: proprio.etichetta || "" }, blocco);
    etichetta.addEventListener("change", () => {
      valori[reparto.id] = { ...valori[reparto.id] };
      if (etichetta.value.trim()) valori[reparto.id].etichetta = etichetta.value.trim();
      else delete valori[reparto.id].etichetta;
      salva();
    });
    for (const [chiave, testo, base] of [["colore", "Fondo", reparto.colore], ["colore_testo", "Testo", reparto.colore_testo]]) {
      const riga = crea("label", { classe: "spunta" }, blocco);
      riga.append(`${testo} `);
      const colore = crea("input", { type: "color", value: proprio[chiave] || base }, riga);
      const ripristina = crea("button", { type: "button", classe: "piccolo", testo: "come il reparto" }, riga);
      colore.addEventListener("input", () => {
        valori[reparto.id] = { ...valori[reparto.id], [chiave]: colore.value };
        salva();
      });
      ripristina.addEventListener("click", () => {
        if (valori[reparto.id]) delete valori[reparto.id][chiave];
        colore.value = base;
        salva();
      });
    }
  }
}

async function campoLocalita(contenitore, zona) {
  const c = zona.configurazione;
  const attuale = crea("p", { classe: "nota", testo: c.localita ? `${c.localita} (${c.latitudine}, ${c.longitudine})` : "Nessuna località scelta." }, contenitore);
  const cerca = crea("input", { placeholder: "Cerca la città…" }, contenitore);
  const risultati = crea("div", { classe: "risultati" }, contenitore);
  let attesa;
  cerca.addEventListener("input", () => {
    clearTimeout(attesa);
    attesa = setTimeout(async () => {
      risultati.replaceChildren();
      if (cerca.value.trim().length < 2) return;
      try {
        for (const luogo of await api("GET", `/api/meteo/localita/?nome=${encodeURIComponent(cerca.value.trim())}`)) {
          const scelta = crea("button", { type: "button", classe: "risultato", testo: `${luogo.nome} — ${luogo.zona}` }, risultati);
          scelta.addEventListener("click", () => {
            zona.configurazione = { ...c, localita: luogo.nome, latitudine: luogo.latitudine, longitudine: luogo.longitudine };
            attuale.textContent = `${luogo.nome} (${luogo.latitudine}, ${luogo.longitudine})`;
            risultati.replaceChildren();
            segnaModificato();
            disegna();
          });
        }
      } catch {
        crea("p", { classe: "nota", testo: "Ricerca non disponibile: indica nome e coordinate qui sotto." }, risultati);
      }
    }, 350);
  });
  const manuale = crea("details", {}, contenitore);
  crea("summary", { testo: "Inserisci a mano" }, manuale);
  for (const [chiave, etichetta] of [["localita", "Nome"], ["latitudine", "Latitudine"], ["longitudine", "Longitudine"]]) {
    const riga = crea("label", { classe: "campo" }, manuale);
    riga.append(etichetta);
    const input = crea("input", { value: c[chiave] ?? "" }, riga);
    input.addEventListener("change", () => cambia(zona, chiave, chiave === "localita" ? input.value : parseFloat(input.value)));
  }
}

function mostraProprieta() {
  pannello.replaceChildren();
  const zona = stato.zone.find((z) => z._chiave === stato.selezionata);
  if (!zona) {
    crea("p", { classe: "vuoto", testo: "Seleziona una zona per modificarla, o aggiungine una dalla colonna a sinistra." }, pannello);
    return;
  }
  crea("h2", { testo: TIPI[zona.tipo].nome }, pannello);
  for (const messaggio of stato.errori.get(zona._chiave) || []) crea("p", { classe: "errore-campo", testo: messaggio }, pannello);

  const nome = crea("label", { classe: "campo" }, pannello);
  nome.append("Nome (facoltativo)");
  const inputNome = crea("input", { value: zona.nome || "" }, nome);
  inputNome.addEventListener("change", () => {
    zona.nome = inputNome.value;
    segnaModificato();
    disegna();
  });

  const geometria = crea("fieldset", { classe: "geometria" }, pannello);
  crea("legend", { testo: "Posizione e dimensioni (% dello schermo)" }, geometria);
  for (const [k, etichetta] of [["x", "Da sinistra"], ["y", "Dall'alto"], ["larghezza", "Larghezza"], ["altezza", "Altezza"]]) {
    const riga = crea("label", { classe: "campo corto" }, geometria);
    riga.append(etichetta);
    const input = crea("input", { type: "number", min: 0, max: 100, step: PASSO, value: zona[k] }, riga);
    input.dataset.geometria = k;
    input.addEventListener("change", () => {
      const v = parseFloat(input.value);
      if (Number.isNaN(v)) return;
      zona[k] = k === "x" ? limita(v, 0, 100 - zona.larghezza) : k === "y" ? limita(v, 0, 100 - zona.altezza)
        : k === "larghezza" ? limita(v, MINIMO, 100 - zona.x) : limita(v, MINIMO, 100 - zona.y);
      segnaModificato();
      disegna();
      aggiornaGeometria(zona);
    });
  }
  crea("p", { classe: "nota pixel" }, geometria);
  if (zona.tipo === "slide" || zona.tipo === "immagine") {
    const riga = crea("div", { classe: "formato-immagini", title: "Misura in pixel delle immagini che prepari di solito" }, geometria);
    crea("span", { testo: "Formato immagini (pixel, vale per tutto il layout)" }, riga);
    formato().forEach((valore, i) => {
      const chiave = i ? "formato_altezza" : "formato_larghezza";
      if (i) crea("b", { testo: "×" }, riga);
      const input = crea("input", { type: "number", min: 100, max: 20000, value: valore }, riga);
      input.setAttribute("aria-label", i ? "Altezza in pixel" : "Larghezza in pixel");
      input.addEventListener("input", () => {
        const [l, a] = formato();
        stato.formato = { formato_larghezza: l, formato_altezza: a, [chiave]: parseInt(input.value, 10) || null };
        segnaModificato();
        aggiornaGeometria(zona);
      });
    });
    crea("p", { classe: "nota confronto-formato" }, geometria);
    crea("button", { type: "button", classe: "formato", testo: "Proporzioni del formato immagini" }, geometria)
      .addEventListener("click", () => proporzioniDelFormato(zona));
  }
  aggiornaGeometria(zona);

  const azioni = crea("div", { classe: "azioni" }, pannello);
  const pulsante = (testo, azione, classe = "") => crea("button", { type: "button", testo, classe }, azioni).addEventListener("click", azione);
  pulsante("Porta avanti", () => cambiaLivello(zona, 1));
  pulsante("Porta indietro", () => cambiaLivello(zona, -1));
  pulsante("Duplica", () => duplica(zona));
  pulsante("Elimina", () => elimina(zona), "pericolo");

  for (const campo of CAMPI[zona.tipo]) {
    const valore = zona.configurazione[campo.nome] ?? campo.predefinito;
    const riga = crea("div", { classe: "campo" }, pannello);
    crea("span", { classe: "etichetta-campo", testo: campo.etichetta }, riga);
    switch (campo.tipo) {
      case "testo":
      case "testo_lungo": {
        const input = crea(campo.tipo === "testo" ? "input" : "textarea", { value: valore ?? "" }, riga);
        input.addEventListener("change", () => cambia(zona, campo.nome, input.value));
        break;
      }
      case "righe": {
        const input = crea("textarea", { value: (valore || []).join("\n"), rows: 3 }, riga);
        input.addEventListener("change", () => cambia(zona, campo.nome, input.value.split("\n").map((r) => r.trim()).filter(Boolean)));
        break;
      }
      case "numero": {
        const input = crea("input", { type: "number", min: campo.min, max: campo.max, step: campo.passo, value: valore }, riga);
        input.addEventListener("change", () => cambia(zona, campo.nome, parseInt(input.value, 10)));
        break;
      }
      case "si_no": {
        const etichetta = crea("label", { classe: "spunta" }, riga);
        const input = crea("input", { type: "checkbox", checked: !!valore }, etichetta);
        etichetta.append(" sì");
        input.addEventListener("change", () => cambia(zona, campo.nome, input.checked));
        break;
      }
      case "scelta": {
        const select = crea("select", {}, riga);
        for (const [v, t] of campo.valori) crea("option", { value: v, testo: t, selected: v === valore }, select);
        select.addEventListener("change", () => cambia(zona, campo.nome, select.value));
        break;
      }
      case "colore":
        campoColore(riga, valore, (v) => cambia(zona, campo.nome, v), false);
        break;
      case "sfondo":
        campoColore(riga, valore, (v) => cambia(zona, campo.nome, v), true);
        break;
      case "playlist": {
        const select = crea("select", {}, riga);
        crea("option", { value: "palinsesto", testo: "Il palinsesto pubblicato sul monitor" }, select);
        for (const p of stato.archivi.playlist) crea("option", { value: p.id, testo: `Playlist fissa: ${p.nome}`, selected: p.id === valore }, select);
        select.addEventListener("change", () => cambia(zona, campo.nome, select.value));
        break;
      }
      case "immagine": {
        const select = crea("select", {}, riga);
        crea("option", { value: "", testo: "— scegli —" }, select);
        for (const i of stato.archivi.immagini) crea("option", { value: i.id, testo: i.nome, selected: i.id === valore }, select);
        select.addEventListener("change", () => cambia(zona, campo.nome, select.value));
        break;
      }
      case "reparti":
        campoReparti(riga, zona);
        break;
      case "personalizza":
        campoPersonalizza(riga, zona);
        break;
      case "localita":
        campoLocalita(riga, zona);
        break;
    }
  }
}

// --- Operazioni sulle zone -----------------------------------------------------------

function aggiungi(tipo) {
  const [larghezza, altezza] = TIPI[tipo].dimensioni;
  const livello = Math.max(0, ...stato.zone.map((z) => z.livello + 1));
  const zona = {
    _chiave: nuovaChiave(), tipo, nome: "", livello, configurazione: {},
    x: arrotonda((100 - larghezza) / 2), y: arrotonda((100 - altezza) / 2), larghezza, altezza,
  };
  stato.zone.push(zona);
  segnaModificato();
  seleziona(zona._chiave);
}

function duplica(zona) {
  const copia = {
    ...structuredClone(zona), _chiave: nuovaChiave(), id: undefined,
    x: limita(zona.x + 2, 0, 100 - zona.larghezza), y: limita(zona.y + 2, 0, 100 - zona.altezza),
    livello: Math.max(...stato.zone.map((z) => z.livello)) + 1,
  };
  stato.zone.push(copia);
  segnaModificato();
  seleziona(copia._chiave);
}

function elimina(zona) {
  stato.zone = stato.zone.filter((z) => z !== zona);
  stato.errori.delete(zona._chiave);
  segnaModificato();
  seleziona(null);
}

function cambiaLivello(zona, verso) {
  const ordinate = [...stato.zone].sort((a, b) => a.livello - b.livello);
  const i = ordinate.indexOf(zona);
  const j = i + verso;
  if (j < 0 || j >= ordinate.length) return;
  [ordinate[i], ordinate[j]] = [ordinate[j], ordinate[i]];
  ordinate.forEach((z, livello) => (z.livello = livello));
  segnaModificato();
  disegna();
}

// --- Caricamento e salvataggio --------------------------------------------------------

function caricaLayout(layout) {
  stato.layout = layout;
  stato.zone = layout.zone.map((z) => ({ ...structuredClone(z), _chiave: nuovaChiave() }));
  stato.selezionata = null;
  stato.errori.clear();
  stato.modificato = false;
  document.getElementById("salva").classList.remove("attenzione");
  document.getElementById("nome").value = layout.nome;
  document.getElementById("sfondo").value = layout.sfondo;
  document.getElementById("predefinito").checked = layout.predefinito;
  stato.formato = { formato_larghezza: layout.formato_larghezza, formato_altezza: layout.formato_altezza };
  document.getElementById("orientamento").textContent =
    layout.orientamento === "verticale" ? "Verticale · totem 1080×1920" : "Orizzontale · monitor 1920×1080";
  adattaPalco();
  disegna();
  mostraProprieta();
}

// Gli errori del server arrivano nello stesso ordine delle zone inviate.
function erroriDelServer(corpo, inviate) {
  stato.errori.clear();
  const generali = [];
  const appiattisci = (valore) =>
    typeof valore === "string" ? [valore]
      : Array.isArray(valore) ? valore.flatMap(appiattisci)
        : Object.entries(valore || {}).flatMap(([campo, v]) => appiattisci(v).map((m) => (campo === "non_field_errors" ? m : `${campo}: ${m}`)));
  for (const [campo, valore] of Object.entries(corpo || {})) {
    // Errori per zona: una lista allineata alle zone, o un oggetto {indice: errori}
    // secondo la versione di Django REST Framework.
    const perZona = campo === "zone" && valore && typeof valore === "object" &&
      (Array.isArray(valore) ? valore.length === inviate.length && typeof valore[0] === "object" : Object.keys(valore).every((k) => /^\d+$/.test(k)));
    if (perZona) {
      for (const [i, errori] of Object.entries(valore)) {
        const messaggi = appiattisci(errori);
        if (messaggi.length && inviate[i]) stato.errori.set(inviate[i]._chiave, messaggi);
      }
    } else {
      generali.push(...appiattisci(valore).map((m) => (campo === "non_field_errors" || campo === "zone" ? m : `${campo}: ${m}`)));
    }
  }
  return generali;
}

async function salva() {
  const inviate = [...stato.zone];
  const dati = {
    nome: document.getElementById("nome").value.trim() || stato.layout.nome,
    sfondo: document.getElementById("sfondo").value,
    predefinito: document.getElementById("predefinito").checked,
    ...(stato.formato.formato_larghezza > 0 && stato.formato.formato_altezza > 0
      ? stato.formato : { formato_larghezza: null, formato_altezza: null }),
    zone: inviate.map(({ tipo, nome, x, y, larghezza, altezza, livello, configurazione }) => ({
      tipo, nome, x, y, larghezza, altezza, livello, configurazione,
    })),
  };
  try {
    const salvato = await api("PATCH", `/api/layout/${stato.layout.id}/`, dati);
    caricaLayout(salvato);
    avvisa("Layout salvato: i monitor lo ricevono al prossimo aggiornamento.", "ok");
  } catch (errore) {
    const generali = errore.corpo ? erroriDelServer(errore.corpo, inviate) : [errore.message];
    const conErrori = stato.errori.size;
    avvisa([conErrori ? (conErrori === 1 ? "1 zona da correggere (in rosso)." : `${conErrori} zone da correggere (in rosso).`) : "", ...generali].filter(Boolean).join(" ") || "Salvataggio non riuscito.");
    const prima = inviate.find((z) => stato.errori.has(z._chiave));
    if (prima) seleziona(prima._chiave);
    else disegna();
  }
}

async function avviaEditor(id) {
  document.querySelector(".editor").hidden = false;
  document.getElementById("torna").href = `/editor/${suffisso}`;
  const tavolozza = document.getElementById("tavolozza");
  for (const [tipo, info] of Object.entries(TIPI)) {
    const b = crea("button", { type: "button", classe: "aggiungi", testo: info.nome, "data-aiuto": SPIEGAZIONI[tipo] }, tavolozza);
    b.style.borderLeftColor = info.colore;
    b.addEventListener("click", () => aggiungi(tipo));
  }
  for (const id of ["nome", "sfondo", "predefinito"]) {
    document.getElementById(id).addEventListener("input", () => {
      segnaModificato();
      if (id === "sfondo") palco.style.background = document.getElementById("sfondo").value;
    });
  }
  document.getElementById("salva").addEventListener("click", salva);
  document.getElementById("annulla").addEventListener("click", async () => {
    if (!stato.modificato || confirm("Annullare le modifiche non salvate?")) {
      caricaLayout(await api("GET", `/api/layout/${id}/`));
      avvisa("");
    }
  });
  window.addEventListener("beforeunload", (e) => {
    if (stato.modificato) e.preventDefault();
  });
  new ResizeObserver(adattaPalco).observe(area);

  try {
    const [layout, playlist, contenuti, reparti] = await Promise.all([
      api("GET", `/api/layout/${id}/`), tutti("/api/playlist/"), tutti("/api/contenuti/"), tutti("/api/reparti/"),
    ]);
    stato.archivi = { playlist, immagini: contenuti.filter((c) => c.tipo === "immagine"), reparti };
    caricaLayout(layout);
  } catch (errore) {
    avvisa(errore.stato === 403 ? "Accedi al pannello per modificare i layout." : errore.message);
  }
}

// --- Elenco dei layout -----------------------------------------------------------------

async function avviaElenco() {
  document.querySelector(".editor").hidden = true;
  for (const id of ["salva", "annulla", "nome", "orientamento"]) document.getElementById(id).hidden = true;
  document.querySelectorAll(".campo-barra").forEach((el) => (el.hidden = true));
  document.getElementById("torna").hidden = true;
  const elenco = document.getElementById("elenco");
  elenco.hidden = false;

  let layout, modelli;
  try {
    [layout, modelli] = await Promise.all([tutti("/api/layout/"), api("GET", "/api/layout/modelli/")]);
  } catch (errore) {
    avvisa(errore.stato === 403 ? "Accedi al pannello per gestire i layout." : errore.message);
    return;
  }
  crea("h1", { testo: "Layout" }, elenco);
  const griglia = crea("div", { classe: "schede" }, elenco);
  for (const l of layout) {
    const scheda = crea("a", { classe: "scheda", href: `/editor/${l.id}/${suffisso}` }, griglia);
    const mini = crea("div", { classe: `mini ${l.orientamento}` }, scheda);
    mini.style.background = l.sfondo;
    for (const z of l.zone) {
      const b = crea("span", {}, mini);
      Object.assign(b.style, { left: `${z.x}%`, top: `${z.y}%`, width: `${z.larghezza}%`, height: `${z.altezza}%`, background: TIPI[z.tipo]?.colore });
    }
    crea("strong", { testo: l.nome }, scheda);
    crea("span", { testo: `${l.orientamento === "verticale" ? "Verticale" : "Orizzontale"}${l.predefinito ? " · predefinito" : ""}` }, scheda);
  }

  const nuovo = crea("section", { classe: "nuovo" }, elenco);
  crea("h2", { testo: "Nuovo layout" }, nuovo);
  const nome = crea("input", { placeholder: "Nome" }, nuovo);
  const orientamento = crea("select", {}, nuovo);
  crea("option", { value: "orizzontale", testo: "Orizzontale (monitor)" }, orientamento);
  crea("option", { value: "verticale", testo: "Verticale (totem)" }, orientamento);
  crea("button", { type: "button", classe: "primario", testo: "Crea vuoto" }, nuovo).addEventListener("click", async () => {
    try {
      const creato = await api("POST", "/api/layout/", { nome: nome.value.trim() || "Nuovo layout", orientamento: orientamento.value, zone: [] });
      location.href = `/editor/${creato.id}/${suffisso}`;
    } catch (errore) {
      avvisa(errore.stato === 403 ? "Non hai il permesso di creare layout." : "Creazione non riuscita.");
    }
  });
  crea("p", { classe: "nota", testo: "Oppure parti da un modello pronto (lo modifichi poi a piacere):" }, nuovo);
  for (const m of modelli) {
    crea("button", { type: "button", testo: `${m.nome} (${m.orientamento})` }, nuovo).addEventListener("click", async () => {
      // I modelli con meteo e notizie partono con valori da completare nell'editor.
      try {
        const creato = await api("POST", "/api/layout/da-modello/", {
          modello: m.modello, nome: nome.value.trim() || m.nome,
          localita: "Roma", latitudine: 41.89, longitudine: 12.48, messaggi: ["Benvenuti!"],
        });
        location.href = `/editor/${creato.id}/${suffisso}`;
      } catch (errore) {
        avvisa(errore.stato === 403 ? "Non hai il permesso di creare layout." : "Creazione non riuscita.");
      }
    });
  }
}

const id = document.body.dataset.layout;
attivaAiuti();
if (id) avviaEditor(id);
else avviaElenco();
