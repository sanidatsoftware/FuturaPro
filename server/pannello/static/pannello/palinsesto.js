// «Creazione palinsesto»: libreria divisa tra verticali (totem) e orizzontali (monitor),
// campagne che raggruppano promozioni, calendario e importazione da CSV.
//
// Una campagna tiene i destinatari (insegne, gruppi, monitor e totem); ogni sua
// promozione ha date e immagini. Sul server ogni promozione diventa una
// pubblicazione per orientamento: qui si sceglie solo cosa, quando e dove.
// I testi che arrivano dai dati passano sempre da textContent.

import { avviaDiretta } from "../player/motore.js";
import { attivaAiuti } from "./aiuto.js";
import { AIUTI_PALINSESTO, osservaAiutiPagina } from "./aiuti-campi.js";
import { clienteRicordato, disegnaMenu, ricordaCliente } from "./menu.js";
import { apriEventi, caricaEventi, eventiCaricati, preparaEventi } from "./eventi.js";
import { FORMATO_LIBRERIA, apriAnteprima, apriSequenza, disegnaSequenza, inOnda, preparaSequenza } from "./sequenza.js";

const cliente = clienteRicordato();
const MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];
const STATI = {
  in_onda: { testo: "In onda", classe: "in-onda" },
  programmata: { testo: "Programmata", classe: "programmata" },
  bozza: { testo: "Bozza", classe: "bozza" },
  conclusa: { testo: "Conclusa", classe: "conclusa" },
};
const FORMATI_ACCETTATI = /\.(jpe?g|png|gif|webp|mp4|webm|mov)$/i;
const VISTE_LIBRERIA = {
  da_assegnare: "Da assegnare",
  attivi: "Nelle promozioni attive",
  scaduti: "Promozioni scadute",
  tutti: "Tutti",
};

const S = {
  io: null,
  contenuti: [],
  campagne: [],
  insegne: [],
  gruppi: [],
  monitor: [],
  sedi: [],
  selezione: new Set(),
  campagna: null, // la campagna aperta (copia modificabile)
  promozione: null, // la promozione aperta, dentro la campagna aperta
  modificata: false,
  creaCampagna: false, // il modulo «Nuova campagna» è aperto
  impostazioniAperte: false,
  zoom: 0, // livello del calendario (LIVELLI)
  inizioVista: new Date(new Date().getFullYear(), 0, 1),
  libreria: "da_assegnare",
  cartella: null, // la promozione aperta come cartella nella libreria
  cerca: "",
};

// --- Strumenti -----------------------------------------------------------------------

function cookie(nome) {
  const trovato = document.cookie.split("; ").find((c) => c.startsWith(`${nome}=`));
  return trovato ? decodeURIComponent(trovato.split("=")[1]) : "";
}

function spiega(corpo) {
  if (!corpo) return "";
  if (typeof corpo === "string") return corpo;
  if (Array.isArray(corpo)) return corpo.map(spiega).join(" ");
  return Object.entries(corpo)
    .map(([campo, v]) => (["detail", "non_field_errors"].includes(campo) ? spiega(v) : `${campo}: ${spiega(v)}`))
    .join(" · ");
}

async function api(metodo, url, dati) {
  const intestazioni = { "X-CSRFToken": cookie("csrftoken") };
  if (cliente && !url.startsWith("/api/piattaforma/")) intestazioni["X-Cliente"] = cliente;
  let corpo;
  if (dati instanceof FormData) corpo = dati;
  else if (dati !== undefined) {
    corpo = JSON.stringify(dati);
    intestazioni["Content-Type"] = "application/json";
  }
  const risposta = await fetch(url, { method: metodo, headers: intestazioni, body: corpo, credentials: "same-origin" });
  const contenuto = risposta.status === 204 ? null : await risposta.json().catch(() => null);
  if (!risposta.ok) {
    throw Object.assign(new Error(spiega(contenuto) || `Errore ${risposta.status}`), { stato: risposta.status, corpo: contenuto });
  }
  return contenuto;
}

// Tutte le pagine di un elenco.
async function tutte(url) {
  const risultati = [];
  let prossima = url;
  while (prossima) {
    const pagina = await api("GET", prossima);
    risultati.push(...pagina.results);
    prossima = pagina.next ? new URL(pagina.next).pathname + new URL(pagina.next).search : null;
  }
  return risultati;
}

const conCliente = (url) => (cliente ? `${url}${url.includes("?") ? "&" : "?"}cliente=${encodeURIComponent(cliente)}` : url);

function crea(tag, attributi = {}, genitore = null) {
  const el = document.createElement(tag);
  for (const [chiave, valore] of Object.entries(attributi)) {
    if (valore === undefined || valore === null) continue;
    if (chiave === "testo") el.textContent = valore;
    else if (chiave === "classe") el.className = valore;
    else if (chiave.startsWith("on") && typeof valore === "function") el.addEventListener(chiave.slice(2), valore);
    else if (chiave in el) el[chiave] = valore;
    else el.setAttribute(chiave, valore);
  }
  if (genitore) genitore.appendChild(el);
  return el;
}

let timerAvviso = null;
function avvisa(testo, tipo = "errore") {
  const box = document.getElementById("avviso");
  clearTimeout(timerAvviso);
  box.hidden = !testo;
  box.className = `avviso ${tipo}`;
  box.textContent = testo || "";
  if (testo && tipo !== "errore") timerAvviso = setTimeout(() => (box.hidden = true), 6000);
}

const isoLocale = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const data = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("it-IT", { day: "numeric", month: "short", year: "numeric" }) : "");
const giornoBreve = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" }) : "");
const periodo = (c) => (c.data_inizio || c.data_fine ? `${data(c.data_inizio) || "…"} → ${data(c.data_fine) || "…"}` : "Senza date");
const peso = (byte) => (byte > 1048576 ? `${(byte / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(byte / 1024))} KB`);
const perId = (elenco) => new Map(elenco.map((v) => [v.id, v]));
const orientamentoDi = (c) => (c.tipo === "diretta" ? "diretta" : c.orientamento || "altro");
const minuti = (secondi) => Math.max(1, Math.round((secondi || 300) / 60));
const promozioni = () => S.campagne.flatMap((c) => c.promozioni.map((p) => ({ ...p, campagnaDati: c })));

function confermaAbbandono() {
  return !S.modificata || confirm("Le modifiche non salvate andranno perse. Continuare?");
}

// --- Caricamento dei dati ---------------------------------------------------------------

async function caricaTutto() {
  const [contenuti, campagne, insegne, gruppi, monitor, sedi] = await Promise.all([
    tutte("/api/contenuti/?uso=libreria"), tutte("/api/campagne/"), tutte("/api/insegne/"),
    tutte("/api/gruppi/"), tutte("/api/monitor/"), tutte("/api/sedi/"), caricaEventi().catch(() => []),
  ]);
  Object.assign(S, { contenuti, campagne, insegne, gruppi, monitor, sedi });
}

// Dopo un salvataggio: si rilegge tutto e si riaprono campagna e promozione aggiornate.
async function ricarica() {
  await caricaTutto();
  if (S.campagna?.id && !S.modificata) {
    const campagna = S.campagne.find((c) => c.id === S.campagna.id);
    S.campagna = campagna ? structuredClone(campagna) : null;
    if (S.promozione?.id) {
      const promozione = campagna?.promozioni.find((p) => p.id === S.promozione.id);
      S.promozione = promozione ? structuredClone(promozione) : null;
    }
  }
  disegna();
}

function disegna() {
  disegnaStatistiche();
  disegnaLibreria();
  disegnaPannello();
  disegnaCalendario();
  disegnaSelezione();
}

// --- Uso dei contenuti nelle promozioni ----------------------------------------------------------

function usoContenuti() {
  const uso = new Map();
  for (const p of promozioni()) {
    for (const id of p.contenuti) {
      if (!uso.has(id)) uso.set(id, []);
      uso.get(id).push(p);
    }
  }
  return uso;
}

function categoria(contenuto, uso) {
  const promo = uso.get(contenuto.id);
  if (!promo) return "da_assegnare";
  return promo.every((p) => p.stato === "conclusa") ? "scaduti" : "attivi";
}

// Le dirette sono canali da riusare in più promozioni: restano sempre anche tra quelle da assegnare.
const inVista = (contenuto, uso, vista) => vista === "tutti" || categoria(contenuto, uso) === vista
  || (vista === "da_assegnare" && contenuto.tipo === "diretta");

// --- Statistiche --------------------------------------------------------------------------

function disegnaStatistiche() {
  const box = document.getElementById("statistiche");
  box.replaceChildren();
  const tutte_ = promozioni();
  const conta = (stato) => tutte_.filter((p) => p.stato === stato).length;
  const uso = usoContenuti();
  const daAssegnare = S.contenuti.filter((c) => !uso.has(c.id)).length;
  const totem = S.monitor.filter((m) => m.orientamento === "verticale").length;
  for (const [valore, etichetta, classe] of [
    [conta("in_onda"), "promozioni in onda", "in-onda"],
    [conta("programmata"), "programmate", "programmata"],
    [conta("bozza"), "bozze da completare", "bozza"],
    [daAssegnare, "contenuti da assegnare", ""],
    [`${totem} · ${S.monitor.length - totem}`, "totem · monitor", ""],
  ]) {
    const scheda = crea("div", { classe: `stat ${classe}` }, box);
    crea("strong", { testo: String(valore) }, scheda);
    crea("span", { testo: etichetta }, scheda);
  }
}

// --- Libreria ---------------------------------------------------------------------------------

function anteprima(contenuto, classe = "") {
  if (contenuto.tipo === "immagine") {
    return crea("img", { src: conCliente(`/api/contenuti/${contenuto.id}/miniatura/`), loading: "lazy", alt: "", classe, draggable: false });
  }
  if (contenuto.tipo === "video") {
    const v = crea("video", { src: `${conCliente(`/api/contenuti/${contenuto.id}/file/`)}#t=0.5`, muted: true, preload: "metadata", classe });
    v.playsInline = true;
    return v;
  }
  if (contenuto.tipo === "diretta") {
    const tile = crea("div", { classe: `web diretta ${classe}` });
    if (contenuto.logo_url) {
      const logo = crea("img", { src: contenuto.logo_url, alt: "", loading: "lazy", referrerPolicy: "no-referrer", draggable: false }, tile);
      logo.addEventListener("error", () => logo.replaceWith(crea("span", { testo: "📡" })));
    } else crea("span", { testo: "📡" }, tile);
    crea("span", { classe: "live", testo: "LIVE" }, tile);
    return tile;
  }
  const web = crea("div", { classe: `web ${classe}` });
  crea("span", { testo: "🌐" }, web);
  return web;
}

const AIUTI_LIBRERIA = {
  da_assegnare: "Le immagini caricate che non sono ancora in nessuna promozione: è qui che si prepara la prossima.",
  attivi: "Le promozioni in onda, programmate o in bozza, ognuna come una cartella con le sue immagini.",
  scaduti: "Le promozioni concluse. Le loro immagini, se non servono altrove, si possono cancellare con «Libera spazio».",
  tutti: "Tutta la libreria del cliente, senza filtri.",
};

function disegnaSchedeLibreria(uso) {
  const box = document.getElementById("schede-libreria");
  box.replaceChildren();
  const conteggi = { da_assegnare: 0, attivi: 0, scaduti: 0, tutti: S.contenuti.length };
  for (const c of S.contenuti) {
    conteggi[categoria(c, uso)] += 1;
    if (c.tipo === "diretta" && categoria(c, uso) !== "da_assegnare") conteggi.da_assegnare += 1;
  }
  for (const [chiave, titolo] of Object.entries(VISTE_LIBRERIA)) {
    const b = crea("button", { type: "button", classe: `scheda-libreria${S.libreria === chiave ? " attiva" : ""}`, "data-aiuto": AIUTI_LIBRERIA[chiave] }, box);
    b.append(titolo);
    crea("span", { classe: "conteggio", testo: String(conteggi[chiave]) }, b);
    b.addEventListener("click", () => {
      S.libreria = chiave;
      S.cartella = null;
      disegnaLibreria();
    });
  }
  if (S.libreria === "scaduti" && conteggi.scaduti) {
    crea("button", {
      type: "button", classe: "pericolo", testo: "Libera spazio…", onclick: liberaSpazio,
      "data-aiuto": "Cancella dalla libreria e dal server le immagini usate solo da promozioni concluse. Prima mostra quante sono e quanto spazio si libera.",
    }, box);
  }
}

async function liberaSpazio() {
  try {
    const stima = await api("GET", "/api/contenuti/pulizia/");
    if (!stima.contenuti) {
      avvisa("Nessun contenuto da eliminare: quelli delle promozioni scadute sono usati anche altrove.", "info");
      return;
    }
    if (!confirm(`Eliminare definitivamente ${stima.contenuti} contenuti delle promozioni scadute (${peso(stima.spazio)})?\nI file spariscono anche dal server. Restano quelli usati da promozioni in corso o future, dalle playlist e dai layout.`)) return;
    const esito = await api("POST", "/api/contenuti/pulizia/");
    avvisa(`Eliminati ${esito.contenuti} contenuti: liberati ${peso(esito.spazio)}.`, "ok");
    await ricarica();
  } catch (errore) {
    avvisa(errore.message);
  }
}

// Il nome delle promozioni di un'immagine, per l'etichetta sulla miniatura.
function etichettaPromozioni(usi) {
  if (!usi.length) return "";
  return usi.length === 1 ? usi[0].nome : `${usi[0].nome} +${usi.length - 1}`;
}

function disegnaLibreria() {
  const uso = usoContenuti();
  disegnaSchedeLibreria(uso);
  const box = document.getElementById("gallerie");
  box.replaceChildren();
  const filtro = S.cerca.trim().toLowerCase();
  const corrisponde = (c) => !filtro || c.nome.toLowerCase().includes(filtro);

  // Promozioni attive e scadute: prima le cartelle, una per promozione.
  if ((S.libreria === "attivi" || S.libreria === "scaduti") && !S.cartella) {
    disegnaCartelle(box, uso, corrisponde);
    return;
  }
  let visibili;
  if (S.cartella) {
    const promo = promozioni().find((p) => p.id === S.cartella);
    if (!promo) {
      S.cartella = null;
      disegnaLibreria();
      return;
    }
    const percorso = crea("div", { classe: "percorso" }, box);
    crea("button", { type: "button", classe: "leggero", testo: `← ${VISTE_LIBRERIA[S.libreria]}`, onclick: () => { S.cartella = null; disegnaLibreria(); } }, percorso);
    crea("span", { classe: "pallino", style: `background:${promo.campagnaDati.colore}` }, percorso);
    crea("span", { classe: "tenue", testo: promo.campagnaDati.nome }, percorso);
    crea("span", { classe: "tenue", testo: "›" }, percorso);
    crea("strong", { testo: promo.nome }, percorso);
    crea("span", { classe: `stato ${STATI[promo.stato].classe}`, testo: STATI[promo.stato].testo }, percorso);
    crea("span", { classe: "tenue", testo: periodo(promo) }, percorso);
    crea("button", {
      type: "button", testo: "Apri la promozione", onclick: () => apriPromozione(promo.campagnaDati.id, promo.id),
      "data-aiuto": "Apre la promozione a destra per cambiarne date e immagini.",
    }, percorso);
    const contenuti = perId(S.contenuti);
    visibili = promo.contenuti.map((id) => contenuti.get(id)).filter((c) => c && corrisponde(c));
  } else {
    visibili = S.contenuti.filter((c) => corrisponde(c) && inVista(c, uso, S.libreria));
  }
  if (!visibili.length) {
    const vuoto = crea("div", { classe: "galleria vuota" }, box);
    crea("p", {
      classe: "vuoto",
      testo: filtro ? "Nessun contenuto con questo nome."
        : S.libreria === "da_assegnare" ? "Tutto assegnato. Trascina qui sopra le immagini della prossima promozione."
          : "Nessun contenuto in questa vista.",
    }, vuoto);
    return;
  }
  disegnaGallerie(box, visibili, uso);
}

function disegnaCartelle(box, uso, corrisponde) {
  const contenuti = perId(S.contenuti);
  const scadute = S.libreria === "scaduti";
  const cartelle = promozioni()
    .filter((p) => (scadute ? p.stato === "conclusa" : p.stato !== "conclusa"))
    .filter((p) => !S.cerca.trim() || p.nome.toLowerCase().includes(S.cerca.trim().toLowerCase())
      || p.contenuti.some((id) => contenuti.has(id) && corrisponde(contenuti.get(id))))
    .sort((a, b) => (a.data_inizio || "").localeCompare(b.data_inizio || ""));
  if (!cartelle.length) {
    const vuoto = crea("div", { classe: "galleria vuota" }, box);
    crea("p", { classe: "vuoto", testo: scadute ? "Nessuna promozione conclusa." : "Nessuna promozione attiva: crea la prima dalle immagini da assegnare." }, vuoto);
    return;
  }
  const griglia = crea("div", { classe: "cartelle" }, box);
  for (const p of cartelle) {
    const info = STATI[p.stato];
    const cartella = crea("button", {
      type: "button", classe: `cartella ${info.classe}`,
      "data-aiuto": `Apri la cartella: le ${p.contenuti.length} immagini di «${p.nome}» (campagna «${p.campagnaDati.nome}»).`,
      onclick: () => { S.cartella = p.id; disegnaLibreria(); },
    }, griglia);
    cartella.style.setProperty("--colore", p.campagnaDati.colore);
    const mosaico = crea("div", { classe: "mosaico" }, cartella);
    const prime = p.contenuti.map((id) => contenuti.get(id)).filter(Boolean).slice(0, 4);
    for (const c of prime) mosaico.appendChild(anteprima(c));
    if (!prime.length) crea("span", { classe: "senza", testo: "nessuna immagine" }, mosaico);
    const testo = crea("div", { classe: "testo" }, cartella);
    const riga = crea("div", { classe: "riga-cartella" }, testo);
    crea("span", { classe: "linguetta" }, riga);
    crea("strong", { testo: p.nome }, riga);
    crea("span", { classe: "tenue", testo: `${p.campagnaDati.nome} · ${periodo(p)}` }, testo);
    const piede = crea("div", { classe: "riga-cartella" }, testo);
    crea("span", { classe: `stato ${info.classe}`, testo: info.testo }, piede);
    const vert = p.contenuti.filter((id) => contenuti.get(id)?.orientamento === "verticale").length;
    crea("span", { classe: "tenue", testo: `${vert} totem · ${p.contenuti.length - vert} monitor` }, piede);
  }
}

function disegnaGallerie(box, visibili, uso) {
  const nellaPromozione = new Set(S.promozione?.contenuti || []);
  const gruppi = [
    ["verticale", "Verticali", "per i totem", "▯"],
    ["orizzontale", "Orizzontali", "per i monitor", "▭"],
    ["diretta", "Dirette", "streaming in tempo reale: vanno ai monitor, ognuno con la sua connessione", "📡"],
    ["altro", "Altri contenuti", "pagine web e video senza misure: vanno a tutti", "◇"],
  ];
  for (const [chiave, titolo, sottotitolo, simbolo] of gruppi) {
    const elementi = visibili.filter((c) => orientamentoDi(c) === chiave);
    if (!elementi.length) continue;
    const sezione = crea("section", { classe: `galleria ${chiave}` }, box);
    const testa = crea("header", {}, sezione);
    const titoli = crea("div", { classe: "titoli" }, testa);
    crea("span", { classe: "simbolo", testo: simbolo }, titoli);
    crea("h2", { testo: titolo }, titoli);
    crea("span", { classe: "conteggio", testo: String(elementi.length) }, titoli);
    crea("span", { classe: "sottotitolo", testo: sottotitolo }, titoli);
    const tuttiScelti = elementi.every((c) => S.selezione.has(c.id));
    crea("button", {
      type: "button", classe: "leggero", testo: tuttiScelti ? "Deseleziona tutti" : "Seleziona tutti",
      "data-aiuto": "Seleziona tutte le immagini di questo riquadro: poi in basso scegli «Nuova promozione con queste immagini».",
      onclick: () => {
        for (const c of elementi) (tuttiScelti ? S.selezione.delete(c.id) : S.selezione.add(c.id));
        disegnaLibreria();
        disegnaSelezione();
      },
    }, testa);

    const griglia = crea("div", { classe: "griglia" }, sezione);
    for (const c of elementi) {
      const usi = uso.get(c.id) || [];
      const scheda = crea("article", {
        classe: `media${S.selezione.has(c.id) ? " scelta" : ""}${nellaPromozione.has(c.id) ? " in-campagna" : ""}`,
        tabIndex: 0, title: [c.nome, ...usi.map((p) => `· ${p.campagnaDati.nome} › ${p.nome}`)].join("\n"),
      }, griglia);
      const cornice = crea("div", { classe: "cornice" }, scheda);
      cornice.appendChild(anteprima(c));
      crea("span", { classe: "spunta", testo: "✓" }, cornice);
      if (usi.length) {
        const etichetta = crea("span", { classe: nellaPromozione.has(c.id) ? "etichetta-campagna" : "etichetta-usato", testo: etichettaPromozioni(usi) }, cornice);
        etichetta.style.setProperty("--colore", usi[0].campagnaDati.colore);
      }
      const azioni = crea("div", { classe: "azioni-media" }, cornice);
      crea("button", { type: "button", title: c.tipo === "diretta" ? "Prova la diretta" : "Ingrandisci", testo: c.tipo === "diretta" ? "▶" : "⤢", onclick: (e) => { e.stopPropagation(); apriVisore(c); } }, azioni);
      if (S.promozione) {
        const dentro = nellaPromozione.has(c.id);
        crea("button", {
          type: "button", title: dentro ? "Togli dalla promozione aperta" : "Aggiungi alla promozione aperta", testo: dentro ? "−" : "+",
          onclick: (e) => { e.stopPropagation(); dentro ? togliDallaPromozione(c.id) : aggiungiAllaPromozione([c.id]); },
        }, azioni);
      }
      const didascalia = crea("div", { classe: "didascalia" }, scheda);
      crea("strong", { testo: c.nome }, didascalia);
      crea("span", {
        testo: c.tipo === "diretta"
          ? `diretta · ${minuti(c.durata)} min come intermezzo${c.autorizzata_da ? ` · autorizzata da ${c.autorizzata_da}` : ""}`
          : [c.larghezza && `${c.larghezza}×${c.altezza}`, c.tipo === "video" ? "video" : null, c.dimensione ? peso(c.dimensione) : null].filter(Boolean).join(" · "),
      }, didascalia);
      const scegli = () => {
        S.selezione.has(c.id) ? S.selezione.delete(c.id) : S.selezione.add(c.id);
        scheda.classList.toggle("scelta", S.selezione.has(c.id));
        disegnaSelezione();
      };
      scheda.addEventListener("click", scegli);
      // Con una promozione aperta le immagini si trascinano nella timeline (anche tutte le selezionate).
      if (S.promozione) {
        scheda.draggable = true;
        scheda.addEventListener("dragstart", (e) => {
          const ids = S.selezione.has(c.id) ? [...S.selezione] : [c.id];
          e.dataTransfer.setData(FORMATO_LIBRERIA, JSON.stringify(ids));
          e.dataTransfer.effectAllowed = "copy";
          document.body.classList.add("trascina-libreria");
        });
        scheda.addEventListener("dragend", () => document.body.classList.remove("trascina-libreria"));
      }
      scheda.addEventListener("dblclick", () => apriVisore(c));
      scheda.addEventListener("keydown", (e) => {
        if (e.key === " " || e.key === "Enter") { e.preventDefault(); scegli(); }
      });
    }
  }
}

function apriVisore(contenuto) {
  const finestra = document.getElementById("visore");
  const box = document.getElementById("visore-contenuto");
  box.replaceChildren();
  if (contenuto.tipo === "diretta") {
    provaDiretta(contenuto, box, finestra);
    return;
  }
  if (contenuto.tipo === "immagine") crea("img", { src: conCliente(`/api/contenuti/${contenuto.id}/file/`), alt: contenuto.nome }, box);
  else if (contenuto.tipo === "video") crea("video", { src: conCliente(`/api/contenuti/${contenuto.id}/file/`), controls: true, autoplay: true, muted: true }, box);
  else crea("p", { testo: contenuto.url }, box);
  crea("p", { classe: "nome", testo: `${contenuto.nome}${contenuto.larghezza ? ` · ${contenuto.larghezza}×${contenuto.altezza}` : ""}` }, box);
  finestra.showModal();
}

// Prova la diretta in questo browser, con lo stesso lettore dei player: dice subito se parte
// e, se no, perché (lo stesso motivo che il monitor segnala nella scheda Monitor).
async function provaDiretta(contenuto, box, finestra) {
  const video = crea("video", { muted: true, playsInline: true, controls: true, classe: "prova-diretta" }, box);
  const esito = crea("p", { classe: "esito-diretta", testo: "Collegamento al canale…" }, box);
  crea("p", { classe: "nome", testo: `${contenuto.nome} · ${contenuto.url}` }, box);
  finestra.showModal();
  const diretta = await avviaDiretta(video, contenuto.url);
  finestra.addEventListener("close", () => diretta.chiudi(), { once: true });
  const risultato = await diretta.pronta;
  if (risultato.ok) {
    video.play().catch(() => {});
    esito.className = "esito-diretta ok";
    esito.textContent = "✓ Il canale parte da questo computer: con la stessa rete partirà anche sui monitor.";
  } else {
    esito.className = "esito-diretta errore";
    esito.textContent = `✕ Non parte: ${risultato.motivo}. Prova un altro indirizzo del canale o rileggi la lista.`;
  }
}

// --- Barra della selezione -------------------------------------------------------------------

function disegnaSelezione() {
  const barra = document.getElementById("barra-selezione");
  barra.replaceChildren();
  const scelti = [...S.selezione].filter((id) => S.contenuti.some((c) => c.id === id));
  barra.hidden = !scelti.length;
  if (!scelti.length) return;
  crea("strong", { testo: `${scelti.length} ${scelti.length === 1 ? "immagine selezionata" : "immagini selezionate"}` }, barra);
  if (S.promozione) {
    crea("button", {
      type: "button", classe: "primario", testo: `Aggiungi a «${S.promozione.nome || "nuova promozione"}»`,
      "data-aiuto": "Aggiunge le immagini selezionate alla promozione aperta a destra. Ricorda di salvarla.",
      onclick: () => { aggiungiAllaPromozione(scelti); S.selezione.clear(); disegnaLibreria(); disegnaSelezione(); },
    }, barra);
  }
  crea("button", {
    type: "button", classe: S.promozione ? "" : "primario", testo: "Nuova promozione con queste immagini",
    "data-aiuto": "Crea una promozione con le immagini selezionate: poi scegli la campagna, il nome e le date.",
    onclick: () => chiediNuovaPromozione({ contenuti: scelti }),
  }, barra);
  crea("button", {
    type: "button", classe: "pericolo", testo: "Elimina dalla libreria",
    "data-aiuto": "Cancella le immagini selezionate dalla libreria e dal server. Spariscono anche dalle promozioni.",
    onclick: async () => {
      if (!confirm(`Eliminare ${scelti.length} contenuti dalla libreria? Spariranno anche dalle promozioni e dalle playlist.`)) return;
      try {
        for (const id of scelti) await api("DELETE", `/api/contenuti/${id}/`);
        S.selezione.clear();
        avvisa("Contenuti eliminati.", "ok");
      } catch (errore) {
        avvisa(errore.message);
      }
      await ricarica();
    },
  }, barra);
  crea("button", { type: "button", classe: "leggero", testo: "Annulla", onclick: () => { S.selezione.clear(); disegnaLibreria(); disegnaSelezione(); } }, barra);
}

// --- Caricamento dei file ------------------------------------------------------------------

// Misure lette dal browser: per i video il server non sa leggerle da solo.
function misura(file) {
  if (file.type.startsWith("image/")) {
    return createImageBitmap(file).then((b) => {
      const misure = { larghezza: b.width, altezza: b.height };
      b.close();
      return misure;
    }).catch(() => ({}));
  }
  if (file.type.startsWith("video/")) {
    return new Promise((ok) => {
      const v = document.createElement("video");
      const url = URL.createObjectURL(file);
      const fine = (misure) => { URL.revokeObjectURL(url); ok(misure); };
      v.preload = "metadata";
      v.onloadedmetadata = () => fine({ larghezza: v.videoWidth, altezza: v.videoHeight });
      v.onerror = () => fine({});
      setTimeout(() => fine({}), 8000);
      v.src = url;
    });
  }
  return Promise.resolve({});
}

function invia(file, misure) {
  return new Promise((ok, ko) => {
    const dati = new FormData();
    dati.append("file", file);
    dati.append("nome", file.name.replace(/\.[^.]+$/, ""));
    if (misure.larghezza) {
      dati.append("larghezza", misure.larghezza);
      dati.append("altezza", misure.altezza);
    }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/contenuti/");
    xhr.setRequestHeader("X-CSRFToken", cookie("csrftoken"));
    if (cliente) xhr.setRequestHeader("X-Cliente", cliente);
    xhr.onload = () => {
      let corpo = null;
      try { corpo = JSON.parse(xhr.responseText); } catch { /* risposta non JSON */ }
      if (xhr.status === 201) ok(corpo);
      else ko(new Error(spiega(corpo) || `Errore ${xhr.status}`));
    };
    xhr.onerror = () => ko(new Error("Rete non raggiungibile"));
    xhr.send(dati);
  });
}

async function caricaFile(file, cartella) {
  const elenco = [...file].filter((f) => FORMATI_ACCETTATI.test(f.name));
  const scartati = file.length - elenco.length;
  if (!elenco.length) {
    avvisa("Nessun file adatto: si caricano immagini (JPEG, PNG, GIF, WebP) e video (MP4, WebM, MOV).");
    return;
  }
  const box = document.getElementById("avanzamento");
  box.hidden = false;
  box.replaceChildren();
  const totale = crea("div", { classe: "totale" }, box);
  const barraTotale = crea("div", { classe: "barra" }, crea("div", { classe: "binario" }, box));
  const caricati = [];
  const errori = [];
  let fatti = 0;
  const aggiorna = () => {
    totale.textContent = `Caricamento ${fatti} di ${elenco.length}${cartella ? ` dalla cartella «${cartella}»` : ""}…`;
    barraTotale.style.width = `${(fatti / elenco.length) * 100}%`;
  };
  aggiorna();
  const coda = [...elenco];
  // Tre alla volta: abbastanza per andare veloci, senza intasare la rete del negozio.
  await Promise.all([0, 1, 2].map(async () => {
    while (coda.length) {
      const f = coda.shift();
      try {
        caricati.push(await invia(f, await misura(f)));
      } catch (errore) {
        errori.push(`${f.name}: ${errore.message}`);
      }
      fatti += 1;
      aggiorna();
    }
  }));
  box.hidden = true;
  S.libreria = "da_assegnare";
  await ricarica();
  for (const c of caricati) S.selezione.add(c.id);
  disegnaLibreria();
  disegnaSelezione();
  if (errori.length) avvisa(`Non caricati: ${errori.join(" · ")}`);
  else avvisa(`${caricati.length} immagini caricate${scartati ? ` (${scartati} file ignorati)` : ""}: sono già selezionate.`, "ok");
  if (cartella && caricati.length && !S.promozione) {
    // Una cartella è quasi sempre una promozione: la si propone già pronta.
    chiediNuovaPromozione({ nome: cartella, contenuti: caricati.map((c) => c.id) });
  }
}

// Le cartelle trascinate: si leggono ricorsivamente.
async function fileDaTrascinamento(trasferimento) {
  const voci = [...trasferimento.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
  if (!voci.length) return { file: [...trasferimento.files], cartella: null };
  const file = [];
  const leggi = (voce) => new Promise((ok) => {
    if (voce.isFile) voce.file((f) => { file.push(f); ok(); }, ok);
    else if (voce.isDirectory) {
      const lettore = voce.createReader();
      const figli = [];
      const prossime = () => lettore.readEntries(async (blocco) => {
        if (!blocco.length) { await Promise.all(figli.map(leggi)); ok(); return; }
        figli.push(...blocco);
        prossime();
      }, ok);
      prossime();
    } else ok();
  });
  await Promise.all(voci.map(leggi));
  const cartella = voci.length === 1 && voci[0].isDirectory ? voci[0].name : null;
  return { file, cartella };
}

function preparaCaricamento() {
  const zona = document.getElementById("caricamento");
  for (const evento of ["dragenter", "dragover"]) {
    zona.addEventListener(evento, (e) => { e.preventDefault(); zona.classList.add("sopra"); });
  }
  zona.addEventListener("dragleave", (e) => { if (!zona.contains(e.relatedTarget)) zona.classList.remove("sopra"); });
  zona.addEventListener("drop", async (e) => {
    e.preventDefault();
    zona.classList.remove("sopra");
    const { file, cartella } = await fileDaTrascinamento(e.dataTransfer);
    caricaFile(file, cartella);
  });
  document.getElementById("scegli-file").addEventListener("change", (e) => {
    caricaFile(e.target.files, null);
    e.target.value = "";
  });
  document.getElementById("scegli-cartella").addEventListener("change", (e) => {
    const file = [...e.target.files];
    const cartella = file[0]?.webkitRelativePath?.split("/")[0] || null;
    caricaFile(file, cartella);
    e.target.value = "";
  });
}

// --- Nuova promozione: in quale campagna? --------------------------------------------------

// Una campagna nuova vale di solito per tutto l'anno in corso.
function annoInCorso() {
  const anno = new Date().getFullYear();
  return { data_inizio: `${anno}-01-01`, data_fine: `${anno}-12-31` };
}

function nuovaCampagnaVuota(valori = {}) {
  return {
    nome: "", ...annoInCorso(), codice: "", fornitore: "", colore: "#ec6a1f", note: "", priorita: 0, durata: 10,
    insegne: [], gruppi: [], monitor: [], promozioni: [], stato: "bozza", ...valori,
  };
}

// Due settimane da oggi, ma dentro la validità della campagna.
function nuovaPromozioneVuota(campagna, valori = {}) {
  let inizio = isoLocale(new Date());
  if (campagna.data_inizio && inizio < campagna.data_inizio) inizio = campagna.data_inizio;
  if (campagna.data_fine && inizio > campagna.data_fine) inizio = campagna.data_fine;
  let fine = isoLocale(new Date(new Date(`${inizio}T00:00:00`).getTime() + 13 * 86400000));
  if (campagna.data_fine && fine > campagna.data_fine) fine = campagna.data_fine;
  return {
    nome: "", data_inizio: inizio, data_fine: fine,
    ora_inizio: null, ora_fine: null, giorni: [], contenuti: [], durate: {}, audio: [], stato: "bozza", ...valori,
  };
}

// Apre la promozione nuova: nella campagna aperta, oppure chiede quale.
function chiediNuovaPromozione(valori) {
  if (S.campagna) {
    if (!confermaAbbandono()) return;
    apriNuovaPromozione(valori);
    return;
  }
  const finestra = document.getElementById("scegli-campagna");
  const corpo = document.getElementById("scegli-campagna-corpo");
  corpo.replaceChildren();
  crea("p", { testo: "Una promozione appartiene a una campagna, che ne decide i destinatari (insegne, gruppi, monitor e totem)." }, corpo);
  const scelta = crea("select", { id: "campagna-scelta" }, corpo);
  crea("option", { value: "", testo: "+ Nuova campagna…" }, scelta);
  for (const c of S.campagne) crea("option", { value: c.id, testo: `${c.nome}${c.promozioni.length ? ` · ${c.promozioni.length} promozioni` : ""}` }, scelta);
  if (S.campagne.length) scelta.value = S.campagne[S.campagne.length - 1].id;
  const nuova = crea("div", { classe: "nuova-campagna-dialogo" }, corpo);
  const nome = campoIn(nuova, "Nome della nuova campagna", crea("input", { placeholder: "es. Volantini 2026", maxLength: 200 }), "largo");
  const anno = annoInCorso();
  const dal = campoIn(nuova, "Valida dal", crea("input", { type: "date", value: anno.data_inizio }));
  const al = campoIn(nuova, "al", crea("input", { type: "date", value: anno.data_fine }));
  const aggiornaNome = () => (nuova.hidden = Boolean(scelta.value));
  scelta.addEventListener("change", aggiornaNome);
  aggiornaNome();
  const azioni = crea("div", { classe: "azioni" }, corpo);
  crea("button", { type: "button", classe: "leggero", testo: "Annulla", onclick: () => finestra.close() }, azioni);
  crea("button", {
    type: "button", classe: "primario", testo: "Continua",
    onclick: () => {
      if (!scelta.value && !nome.value.trim()) { nome.focus(); return; }
      if (!scelta.value && (!dal.value || !al.value || al.value < dal.value)) { avvisa("Indica la validità della campagna: dal … al …."); return; }
      finestra.close();
      S.campagna = scelta.value
        ? structuredClone(S.campagne.find((c) => c.id === scelta.value))
        : nuovaCampagnaVuota({ nome: nome.value.trim(), data_inizio: dal.value, data_fine: al.value });
      apriNuovaPromozione(valori);
    },
  }, azioni);
  finestra.showModal();
}

function apriNuovaPromozione(valori) {
  if (valori.contenuti && !confermaDirette(valori.contenuti)) return;
  S.promozione = nuovaPromozioneVuota(S.campagna, valori);
  S.modificata = true;
  S.selezione.clear();
  disegna();
  document.getElementById("nome-promozione")?.focus();
}

function apriCampagna(id) {
  if (S.campagna?.id === id && !S.promozione) return;
  if (!confermaAbbandono()) return;
  const trovata = S.campagne.find((c) => c.id === id);
  if (!trovata) return;
  S.campagna = structuredClone(trovata);
  S.promozione = null;
  S.modificata = false;
  disegna();
  apriSequenza();
  document.getElementById("campagna").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function apriPromozione(campagnaId, promozioneId) {
  // Già aperta: si riapre comunque la timeline della sequenza (magari era ridotta).
  if (S.promozione?.id === promozioneId) {
    apriSequenza();
    document.getElementById("campagna").scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  if (!confermaAbbandono()) return;
  const campagna = S.campagne.find((c) => c.id === campagnaId);
  const promozione = campagna?.promozioni.find((p) => p.id === promozioneId);
  if (!promozione) return;
  S.campagna = structuredClone(campagna);
  S.promozione = structuredClone(promozione);
  S.modificata = false;
  disegna();
  document.getElementById("campagna").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function chiudi() {
  if (!confermaAbbandono()) return;
  S.campagna = null;
  S.promozione = null;
  S.modificata = false;
  disegna();
}

// Una modifica non salvata: il pulsante «Salva» si attiva e lampeggia, e compare il promemoria.
function segnaModificata() {
  S.modificata = true;
  for (const pulsante of document.querySelectorAll(".salva")) {
    pulsante.disabled = false;
    pulsante.classList.add("pulsa");
  }
  for (const promemoria of document.querySelectorAll(".da-salvare")) promemoria.hidden = false;
}

// Il pulsante «Salva» di campagna e promozione: spento finché non si cambia qualcosa.
function pulsanteSalva(genitore, testo, azione) {
  const promemoria = crea("div", {
    classe: "da-salvare", hidden: !S.modificata,
    testo: "Modifiche non salvate: premi «Salva», altrimenti non verranno applicate agli schermi.",
  }, genitore);
  promemoria.setAttribute("role", "status");
  return crea("button", {
    type: "button", classe: `primario salva${S.modificata ? " pulsa" : ""}`, testo, disabled: !S.modificata,
    "data-aiuto": "Salva e manda le modifiche agli schermi (entro un minuto). Si attiva quando cambi qualcosa.",
    onclick: azione,
  }, genitore);
}

// Prima di mettere in onda una diretta si ricorda che va autorizzata.
function confermaDirette(ids) {
  const contenuti = perId(S.contenuti);
  const dirette = ids.map((id) => contenuti.get(id)).filter((c) => c?.tipo === "diretta");
  if (!dirette.length) return true;
  return confirm(
    `Stai mettendo in onda ${dirette.length === 1 ? `la diretta «${dirette[0].nome}»` : `${dirette.length} dirette`}.\n\n`
    + "Prima di trasmetterla in un locale aperto al pubblico verifica che sia autorizzata: canone RAI speciale, "
    + "licenze SIAE/SCF, abbonamenti o permessi dell'editore.\n\nProcedere?",
  );
}

function aggiungiAllaPromozione(ids) {
  if (!confermaDirette(ids)) return;
  const presenti = new Set(S.promozione.contenuti);
  for (const id of ids) if (!presenti.has(id)) S.promozione.contenuti.push(id);
  segnaModificata();
  disegnaLibreria();
  disegnaPannello();
}

function togliDallaPromozione(id) {
  S.promozione.contenuti = S.promozione.contenuti.filter((c) => c !== id);
  segnaModificata();
  disegnaLibreria();
  disegnaPannello();
}

// Chi riceve davvero la campagna: monitor scelti, quelli dei gruppi e quelli delle sedi delle insegne.
function destinatari(campagna) {
  const sediInsegne = new Set(S.sedi.filter((s) => s.insegna && campagna.insegne.includes(s.insegna)).map((s) => s.id));
  const gruppi = new Set(campagna.gruppi);
  const scelti = new Set(campagna.monitor);
  return S.monitor.filter((m) => scelti.has(m.id) || m.gruppi.some((g) => gruppi.has(g)) || sediInsegne.has(m.sede));
}

// --- Pannello di destra: campagna o promozione -------------------------------------------------

function disegnaPannello() {
  disegnaSequenza();
  const colonna = document.getElementById("campagna");
  colonna.replaceChildren();
  disegnaRiquadroCampagne(crea("section", { classe: "riquadro-destra riquadro-campagne" }, colonna));
  const box = crea("section", { classe: "riquadro-destra riquadro-corrente" }, colonna);
  if (!S.campagna) {
    const vuoto = crea("div", { classe: "invito" }, box);
    crea("div", { classe: "illustrazione", testo: "▭ ▯ ▭" }, vuoto);
    crea("h3", { testo: "Scegli o crea una campagna" }, vuoto);
    crea("p", { testo: "Una campagna (es. «Volantini 2026», valida dal 1° gennaio al 31 dicembre) raggruppa le promozioni e decide dove vanno in onda. Poi aggiungi le promozioni, ognuna con le sue date e le sue immagini." }, vuoto);
    return;
  }
  if (S.promozione) disegnaPromozione(box);
  else disegnaCampagna(box);
}

// Primo riquadro: quale campagna, oppure una nuova.
function disegnaRiquadroCampagne(box) {
  const testa = crea("div", { classe: "titolo-sezione" }, box);
  crea("h3", { testo: "Campagne", "data-aiuto": "Le campagne raggruppano le promozioni: ognuna ha una validità (es. tutto l'anno) e i suoi schermi." }, testa);
  const apri = crea("button", {
    type: "button", classe: S.creaCampagna ? "leggero" : "primario", testo: S.creaCampagna ? "Annulla" : "＋ Nuova campagna",
    "data-aiuto": "Crea una campagna: nome e validità (dal … al …). Destinatari e promozioni si aggiungono subito dopo.",
    onclick: () => { S.creaCampagna = !S.creaCampagna; disegnaPannello(); },
  }, testa);
  if (S.creaCampagna) {
    const modulo = crea("div", { classe: "campi nuova-campagna" }, box);
    const anno = annoInCorso();
    const nome = campoIn(modulo, "Nome della campagna", crea("input", { placeholder: "es. Volantini 2026", maxLength: 200 }), "largo");
    const dal = campoIn(modulo, "Valida dal", crea("input", { type: "date", value: anno.data_inizio }), "", "Il primo giorno in cui possono andare in onda le sue promozioni.");
    const al = campoIn(modulo, "al (compreso)", crea("input", { type: "date", value: anno.data_fine }), "", "L'ultimo giorno: nessuna sua promozione può andare oltre.");
    const colore = campoIn(modulo, "Colore", crea("input", { type: "color", value: "#ec6a1f" }), "stretto", "Il colore della campagna nel calendario e sulle cartelle.");
    crea("button", {
      type: "button", classe: "primario largo-pulsante", testo: "Crea la campagna",
      onclick: async () => {
        if (!nome.value.trim()) { nome.focus(); return; }
        try {
          const creata = await api("POST", "/api/campagne/", {
            nome: nome.value.trim(), data_inizio: dal.value || null, data_fine: al.value || null, colore: colore.value,
          });
          S.creaCampagna = false;
          S.modificata = false;
          await caricaTutto();
          S.campagna = structuredClone(S.campagne.find((c) => c.id === creata.id) || creata);
          S.promozione = null;
          S.impostazioniAperte = true;
          avvisa(`Campagna «${creata.nome}» creata: scegli dove va in onda, poi aggiungi le promozioni.`, "ok");
          disegna();
        } catch (errore) {
          avvisa(errore.message);
        }
      },
    }, modulo);
    nome.focus();
    return;
  }
  if (!S.campagne.length) {
    crea("p", { classe: "vuoto", testo: "Ancora nessuna campagna: creane una, oppure importale da CSV." }, box);
    return;
  }
  const scelta = crea("select", { "aria-label": "Campagna", classe: "scelta-campagna", "data-aiuto": "La campagna su cui lavorare: le sue promozioni, i contenuti e dove vanno in onda." }, box);
  crea("option", { value: "", testo: S.campagna && !S.campagna.id ? `${S.campagna.nome || "Nuova campagna"} (non salvata)` : "— scegli una campagna —" }, scelta);
  for (const c of S.campagne) {
    const validita = c.data_inizio ? ` · ${data(c.data_inizio)} → ${data(c.data_fine)}` : "";
    crea("option", { value: c.id, testo: `${c.nome}${validita} · ${c.promozioni.length} promo`, selected: c.id === S.campagna?.id }, scelta);
  }
  scelta.addEventListener("change", () => (scelta.value ? apriCampagna(scelta.value) : chiudi()));
}

function campoIn(contenitore, etichetta, controllo, classe = "", aiuto = null) {
  const l = crea("label", { classe: `campo ${classe}`, "data-aiuto": aiuto }, contenitore);
  crea("span", { testo: etichetta }, l);
  l.appendChild(controllo);
  return controllo;
}

function disegnaCampagna(box) {
  const c = S.campagna;
  const stato = STATI[c.stato] || STATI.bozza;
  const intestazione = crea("div", { classe: "intestazione-campagna" }, box);
  intestazione.style.setProperty("--colore", c.colore);
  const riga = crea("div", { classe: "riga-titolo" }, intestazione);
  crea("span", { classe: "pallino grande", style: `background:${c.colore}` }, riga);
  crea("strong", { classe: "nome-campagna", testo: c.nome || "Nuova campagna" }, riga);
  crea("span", { classe: `stato ${stato.classe}`, testo: c.id ? stato.testo : "Nuova" }, riga);
  const validita = crea("div", { classe: "validita", "data-aiuto": "La validità della campagna: le sue promozioni devono stare dentro queste date." }, intestazione);
  crea("span", { classe: "tenue", testo: "Valida" }, validita);
  crea("strong", { testo: c.data_inizio ? `dal ${data(c.data_inizio)} al ${data(c.data_fine)}` : "senza date" }, validita);
  const raggiunti = destinatari(c);
  const totem = raggiunti.filter((m) => m.orientamento === "verticale").length;
  crea("div", {
    classe: `dove${raggiunti.length ? "" : " attenzione"}`,
    testo: raggiunti.length ? `In onda su ${totem} totem e ${raggiunti.length - totem} monitor` : "Nessuno schermo scelto: apri «Impostazioni e destinatari»",
  }, intestazione);

  // Impostazioni: chiuse di solito, aperte se mancano i destinatari o appena creata.
  const impostazioni = crea("details", { classe: "impostazioni", open: Boolean(S.impostazioniAperte || !raggiunti.length) }, box);
  impostazioni.addEventListener("toggle", () => (S.impostazioniAperte = impostazioni.open));
  crea("summary", { testo: "Impostazioni e destinatari", "data-aiuto": "Nome, validità, colore, secondi per immagine, priorità e gli schermi su cui vanno in onda tutte le promozioni della campagna." }, impostazioni);
  const campi = crea("div", { classe: "campi" }, impostazioni);
  const nome = campoIn(campi, "Nome della campagna", crea("input", { id: "nome-campagna", value: c.nome, placeholder: "es. Volantini 2026", maxLength: 200 }), "largo", "Il nome che raggruppa le promozioni, es. l'anno o il tipo di offerte.");
  nome.addEventListener("input", () => { c.nome = nome.value; segnaModificata(); });
  const dal = campoIn(campi, "Valida dal", crea("input", { type: "date", value: c.data_inizio || "" }), "", "Il primo giorno in cui possono andare in onda le sue promozioni.");
  dal.addEventListener("change", () => { c.data_inizio = dal.value || null; segnaModificata(); });
  const al = campoIn(campi, "al (compreso)", crea("input", { type: "date", value: c.data_fine || "" }), "", "L'ultimo giorno: nessuna sua promozione può andare oltre.");
  al.addEventListener("change", () => { c.data_fine = al.value || null; segnaModificata(); });
  const colore = campoIn(campi, "Colore", crea("input", { type: "color", value: c.colore || "#ec6a1f" }), "stretto", "Il colore della campagna nel calendario e sulle cartelle.");
  colore.addEventListener("input", () => { c.colore = colore.value; segnaModificata(); });
  const durata = campoIn(campi, "Secondi per immagine", crea("input", { type: "number", min: 1, max: 3600, value: c.durata || "", placeholder: "10" }), "", "Quanto resta sullo schermo ogni immagine delle promozioni di questa campagna. I video vanno sempre fino alla fine.");
  durata.addEventListener("change", () => { c.durata = parseInt(durata.value, 10) || null; segnaModificata(); });
  const priorita = campoIn(campi, "Priorità", crea("input", { type: "number", min: -100, max: 100, value: c.priorita || 0 }), "", "Di solito 0: le promozioni dello stesso periodo si alternano. Con un numero più alto questa campagna, quando è in onda, sostituisce tutte le altre (es. un'offerta lampo).");
  priorita.addEventListener("change", () => { c.priorita = parseInt(priorita.value, 10) || 0; segnaModificata(); });
  const codice = campoIn(campi, "Codice", crea("input", { value: c.codice || "", placeholder: "es. V26", maxLength: 50 }), "", "Un riferimento interno libero.");
  codice.addEventListener("input", () => { c.codice = codice.value; segnaModificata(); });
  const fornitore = campoIn(campi, "Fornitore / sponsor", crea("input", { value: c.fornitore || "", placeholder: "es. il marchio che paga lo spazio", maxLength: 120 }), "", "Facoltativo: chi paga lo spazio della campagna. I rapporti di messa in onda si possono fare per fornitore.");
  fornitore.addEventListener("input", () => { c.fornitore = fornitore.value; segnaModificata(); });
  disegnaDestinatari(impostazioni, c);
  const piede = crea("div", { classe: "piede-campagna" }, impostazioni);
  pulsanteSalva(piede, c.id ? "Salva la campagna" : "Salva e crea la campagna", salvaCampagna);
  if (c.id) {
    crea("button", {
      type: "button", classe: "pericolo", testo: "Elimina la campagna",
      onclick: async () => {
        if (!confirm(`Eliminare la campagna «${c.nome}» con tutte le sue ${c.promozioni.length} promozioni? Le immagini restano nella libreria.`)) return;
        try {
          await api("DELETE", `/api/campagne/${c.id}/`);
          S.campagna = null;
          S.modificata = false;
          avvisa("Campagna eliminata.", "ok");
          await ricarica();
        } catch (errore) {
          avvisa(errore.message);
        }
      },
    }, piede);
  }

  // Le promozioni della campagna, e il pulsante per aggiungerne.
  const sezione = crea("section", { classe: "elenco-promo" }, box);
  crea("h3", { testo: `Promozioni (${c.promozioni.length})`, "data-aiuto": "Le promozioni di questa campagna, in ordine di data. Clic per aprirne una." }, sezione);
  if (!c.promozioni.length) crea("p", { classe: "vuoto", testo: "Nessuna promozione ancora." }, sezione);
  const contenuti = perId(S.contenuti);
  for (const p of c.promozioni) {
    const info = STATI[p.stato] || STATI.bozza;
    const scheda = crea("button", { type: "button", classe: `scheda-promo ${info.classe}`, onclick: () => apriPromozione(c.id, p.id) }, sezione);
    const anteprime = crea("div", { classe: "anteprime" }, scheda);
    for (const id of p.contenuti.slice(0, 4)) if (contenuti.has(id)) anteprime.appendChild(anteprima(contenuti.get(id)));
    if (!p.contenuti.length) crea("span", { classe: "senza", testo: "nessuna immagine" }, anteprime);
    const testo = crea("div", { classe: "testo" }, scheda);
    crea("strong", { testo: p.nome }, testo);
    crea("span", { testo: periodo(p) }, testo);
    const vert = p.contenuti.filter((id) => contenuti.get(id)?.orientamento === "verticale").length;
    const oriz = p.contenuti.filter((id) => contenuti.get(id)?.orientamento === "orizzontale").length;
    crea("span", { classe: "numeri", testo: `${vert} totem · ${oriz} monitor` }, testo);
    crea("span", { classe: `stato ${info.classe}`, testo: info.testo }, scheda);
  }
  crea("button", {
    type: "button", classe: "primario nuova-promo", testo: "＋ Nuova promozione",
    disabled: !c.id,
    "data-aiuto": c.id
      ? "Aggiunge una promozione a questa campagna: nome e date (dentro la validità della campagna), poi le immagini dalla libreria."
      : "Salva prima la campagna.",
    onclick: () => (confermaAbbandono() ? apriNuovaPromozione({}) : null),
  }, sezione);
  crea("button", { type: "button", classe: "leggero chiudi-campagna", testo: "Chiudi la campagna", onclick: chiudi }, box);
}

// Anche gli eventi straordinari la usano: «opzioni» cambia titolo e cosa fare a ogni scelta.
function disegnaDestinatari(box, c, opzioni = {}) {
  const { titolo: titoloSezione = "Dove vanno in onda le sue promozioni", modificata = segnaModificata, ridisegna = disegnaPannello } = opzioni;
  const sezione = crea("section", { classe: "destinatari" }, box);
  crea("h3", { testo: titoloSezione, "data-aiuto": "Gli schermi che ricevono tutte le promozioni della campagna: per insegna, per gruppo o uno per uno. Le immagini verticali vanno ai totem, le orizzontali ai monitor." }, sezione);

  const chips = (titolo, voci, campo, aiuto) => {
    if (!voci.length) return;
    const riga = crea("div", { classe: "gruppo-chip" }, sezione);
    crea("span", { classe: "etichetta", testo: titolo, "data-aiuto": aiuto }, riga);
    for (const v of voci) {
      const attivo = c[campo].includes(v.id);
      const chip = crea("button", { type: "button", classe: `chip${attivo ? " attivo" : ""}`, testo: v.nome }, riga);
      if (v.colore) chip.style.setProperty("--chip", v.colore);
      chip.addEventListener("click", () => {
        c[campo] = attivo ? c[campo].filter((x) => x !== v.id) : [...c[campo], v.id];
        modificata();
        ridisegna();
      });
    }
  };
  chips("Insegne", S.insegne, "insegne", "Tutti i monitor e i totem dei negozi di queste insegne");
  chips("Gruppi", S.gruppi, "gruppi", "Tutti i monitor e i totem di questi gruppi");

  const sedi = perId(S.sedi);
  for (const [orientamento, titolo] of [["verticale", "Totem"], ["orizzontale", "Monitor"]]) {
    const elenco = S.monitor.filter((m) => m.orientamento === orientamento);
    if (!elenco.length) continue;
    const scelti = elenco.filter((m) => c.monitor.includes(m.id)).length;
    const blocco = crea("details", { classe: "singoli", open: scelti > 0 }, sezione);
    crea("summary", { testo: `${titolo} singoli${scelti ? ` · ${scelti} scelti` : ""}`, "data-aiuto": `Scegli i singoli ${titolo.toLowerCase()} uno per uno, oltre a insegne e gruppi.` }, blocco);
    const lista = crea("div", { classe: "lista-schermi" }, blocco);
    for (const m of elenco) {
      const voce = crea("label", { classe: "schermo" }, lista);
      crea("input", {
        type: "checkbox", checked: c.monitor.includes(m.id),
        onchange: (e) => {
          c.monitor = e.target.checked ? [...c.monitor, m.id] : c.monitor.filter((x) => x !== m.id);
          modificata();
          ridisegna();
        },
      }, voce);
      crea("span", { classe: `led${m.online ? " acceso" : ""}`, title: m.online ? "In linea" : "Non in linea" }, voce);
      crea("span", { testo: m.nome }, voce);
      crea("small", { testo: sedi.get(m.sede)?.nome || "" }, voce);
    }
  }

  const raggiunti = destinatari(c);
  const totem = raggiunti.filter((m) => m.orientamento === "verticale").length;
  const riepilogo = crea("div", { classe: `riepilogo${raggiunti.length ? "" : " attenzione"}` }, sezione);
  const sceltiQualcosa = c.insegne.length || c.gruppi.length || c.monitor.length;
  riepilogo.textContent = raggiunti.length
    ? `Raggiunge ${totem} totem e ${raggiunti.length - totem} monitor.`
    : sceltiQualcosa
      ? "Le insegne o i gruppi scelti non comprendono ancora nessuno schermo: assegna sedi e gruppi ai monitor nel pannello."
      : opzioni.vuoto || "Nessuno schermo scelto: le promozioni restano in bozza e non vanno in onda.";
}

function disegnaPromozione(box) {
  const c = S.campagna;
  const p = S.promozione;
  const torna = crea("button", { type: "button", classe: "torna", onclick: () => { if (confermaAbbandono()) { S.promozione = null; S.modificata = false; disegna(); } } }, box);
  crea("span", { testo: "←" }, torna);
  crea("span", { classe: "pallino", style: `background:${c.colore}` }, torna);
  torna.append(` Campagna «${c.nome || "nuova"}»`);

  const stato = STATI[p.stato] || STATI.bozza;
  const intestazione = crea("div", { classe: "intestazione" }, box);
  crea("span", { classe: "tipo", testo: "Promozione" }, intestazione);
  crea("span", { classe: `stato ${stato.classe}`, testo: p.id ? stato.testo : "Nuova" }, intestazione);

  const campi = crea("div", { classe: "campi" }, box);
  const nome = campoIn(campi, "Nome della promozione", crea("input", { id: "nome-promozione", value: p.nome, placeholder: "es. Volantino 6-19 ottobre", maxLength: 200 }), "largo", "Il nome della promozione, es. il volantino del periodo.");
  nome.addEventListener("input", () => { p.nome = nome.value; segnaModificata(); });
  // Nel calendario si sceglie qualunque giorno: se si esce dalla validità della campagna, al
  // salvataggio si propone di allungarla (prima i giorni fuori non erano cliccabili).
  const dal = campoIn(campi, "Dal", crea("input", { type: "date", value: p.data_inizio || "", required: true }), "", "Il primo giorno in cui la promozione va in onda.");
  const al = campoIn(campi, "Al (compreso)", crea("input", { type: "date", value: p.data_fine || "", required: true, min: p.data_inizio || "" }), "", "L'ultimo giorno in onda, compreso. Dal giorno dopo la promozione è conclusa e sparisce dagli schermi da sola.");
  const validita = crea("p", { classe: "tenue validita-campagna" }, campi);
  const aggiornaValidita = () => {
    const fuori = (c.data_inizio && p.data_inizio && p.data_inizio < c.data_inizio) || (c.data_fine && p.data_fine && p.data_fine > c.data_fine);
    validita.textContent = !c.data_inizio && !c.data_fine ? ""
      : `Campagna valida ${c.data_inizio ? `dal ${giornoBreve(c.data_inizio)} ` : ""}${c.data_fine ? `al ${giornoBreve(c.data_fine)}` : ""}${fuori ? " · le date della promozione escono dalla campagna: al salvataggio ti propongo di allungarla." : ""}`;
    validita.classList.toggle("attenzione", Boolean(fuori));
  };
  dal.addEventListener("change", () => { p.data_inizio = dal.value || null; al.min = dal.value || ""; segnaModificata(); aggiornaValidita(); });
  al.addEventListener("change", () => { p.data_fine = al.value || null; segnaModificata(); aggiornaValidita(); });
  aggiornaValidita();

  const avanzate = crea("details", { classe: "avanzate", open: Boolean(p.ora_inizio || p.ora_fine || p.giorni.length) }, box);
  crea("summary", { testo: "Solo in certe ore o certi giorni", "data-aiuto": "Facoltativo: limita la promozione a una fascia oraria (es. 8-12) o ad alcuni giorni (es. sabato e domenica)." }, avanzate);
  const griglia = crea("div", { classe: "campi" }, avanzate);
  const dalle = campoIn(griglia, "Dalle", crea("input", { type: "time", value: p.ora_inizio?.slice(0, 5) || "" }));
  dalle.addEventListener("change", () => { p.ora_inizio = dalle.value || null; segnaModificata(); });
  const alle = campoIn(griglia, "Alle", crea("input", { type: "time", value: p.ora_fine?.slice(0, 5) || "" }));
  alle.addEventListener("change", () => { p.ora_fine = alle.value || null; segnaModificata(); });
  const giorni = crea("div", { classe: "giorni" }, avanzate);
  crea("span", { testo: "Giorni (nessuno = tutti)" }, giorni);
  GIORNI.forEach((g, i) => {
    const attivo = p.giorni.includes(i);
    crea("button", {
      type: "button", classe: `chip${attivo ? " attivo" : ""}`, testo: g,
      onclick: () => {
        p.giorni = attivo ? p.giorni.filter((x) => x !== i) : [...p.giorni, i].sort();
        segnaModificata();
        disegnaPannello();
      },
    }, giorni);
  });

  disegnaContenutiPromozione(box, p);

  // Riepilogo: chi riceve cosa, con gli avvisi se manca un formato.
  const contenuti = perId(S.contenuti);
  const scelti = p.contenuti.map((id) => contenuti.get(id)).filter(Boolean);
  const vert = scelti.filter((x) => x.orientamento === "verticale").length;
  const oriz = scelti.filter((x) => x.orientamento === "orizzontale").length;
  const altri = scelti.length - vert - oriz;
  const raggiunti = destinatari(c);
  const totem = raggiunti.filter((m) => m.orientamento === "verticale").length;
  const monitor = raggiunti.length - totem;
  const giro = crea("div", { classe: "giro", id: "giro-promozione" }, box);
  aggiornaGiro(giro);
  const riepilogo = crea("div", { classe: `riepilogo${raggiunti.length ? "" : " attenzione"}` }, box);
  if (!raggiunti.length) {
    riepilogo.textContent = c.insegne.length || c.gruppi.length || c.monitor.length
      ? "Le insegne o i gruppi della campagna non comprendono ancora nessuno schermo."
      : "La campagna non ha destinatari: torna alla campagna e scegli insegne, gruppi o schermi.";
  } else {
    if (totem) crea("div", { testo: `${totem} totem mostrano ${vert + altri} immagini${vert + altri ? "" : " — mancano immagini verticali!"}`, classe: vert + altri ? "" : "manca" }, riepilogo);
    if (monitor) crea("div", { testo: `${monitor} monitor mostrano ${oriz + altri} immagini${oriz + altri ? "" : " — mancano immagini orizzontali!"}`, classe: oriz + altri ? "" : "manca" }, riepilogo);
  }

  const piede = crea("div", { classe: "piede-campagna" }, box);
  pulsanteSalva(piede, p.id ? "Salva la promozione" : "Salva e crea la promozione", salvaPromozione).classList.add("grande");
  if (p.id) {
    crea("button", {
      type: "button", classe: "pericolo", testo: "Elimina",
      onclick: async () => {
        if (!confirm(`Eliminare la promozione «${p.nome}»? Le immagini restano nella libreria.`)) return;
        try {
          await api("DELETE", `/api/promozioni/${p.id}/`);
          S.promozione = null;
          S.modificata = false;
          avvisa("Promozione eliminata.", "ok");
          await ricarica();
        } catch (errore) {
          avvisa(errore.message);
        }
      },
    }, piede);
  }
  crea("button", { type: "button", classe: "leggero", testo: "Chiudi", onclick: chiudi }, piede);
}

// Che cosa ripete ogni schermo, nell'ordine, e quanto dura un giro: così si vede subito
// se la diretta è l'unica voce per i monitor (in quel caso resta in onda di continuo).
function descriviGiro(elenco, p, c) {
  const secondiImmagine = c.durata || 10;
  // Come andrà in onda: le dirette con una regola si ripetono al loro ritmo.
  const voci = inOnda(elenco, p.ripeti, (x) => (x.tipo === "diretta" ? (p.durate?.[x.id] || x.durata || 300)
    : x.tipo === "video" ? (p.durate?.[x.id] || x.durata || 30) : (p.durate?.[x.id] || secondiImmagine))).map((s) => s.voce);
  const testo = voci.map((x) => (x.tipo === "diretta"
    ? `📡 ${x.nome} ${minuti(p.durate?.[x.id] || x.durata)} min`
    : x.tipo === "video" ? "▶ video" : "🖼"));
  const totale = voci.reduce((somma, x) => somma + (x.tipo === "diretta" ? (p.durate?.[x.id] || x.durata || 300) : x.tipo === "video" ? 0 : secondiImmagine), 0);
  // Le immagini consecutive si raccolgono: «🖼 ×5 (10 s)».
  const compatto = [];
  for (const voce of testo) {
    const ultimo = compatto[compatto.length - 1];
    if (voce === "🖼" && ultimo?.startsWith("🖼")) compatto[compatto.length - 1] = `🖼 ×${(parseInt(ultimo.split("×")[1], 10) || 1) + 1}`;
    else compatto.push(voce);
  }
  const durata = totale >= 60 ? `${Math.floor(totale / 60)} min ${totale % 60 ? `${totale % 60} s` : ""}` : `${totale} s`;
  return `${compatto.join(" → ")} → da capo · un giro ≈ ${durata.trim()} (immagini da ${secondiImmagine} s)`;
}

function aggiornaGiro(box = document.getElementById("giro-promozione")) {
  if (!box || !S.promozione || !S.campagna) return;
  const p = S.promozione;
  const contenuti = perId(S.contenuti);
  const voci = p.contenuti.map((id) => contenuti.get(id)).filter(Boolean);
  box.replaceChildren();
  crea("strong", { testo: "Cosa ripete ogni schermo" }, box);
  const totem = voci.filter((x) => x.orientamento === "verticale" || !x.orientamento);
  const monitor = voci.filter((x) => x.orientamento === "orizzontale" || x.tipo === "diretta" || !x.orientamento);
  for (const [titolo, elenco] of [["Totem", totem], ["Monitor", monitor]]) {
    if (!elenco.length) continue;
    const riga = crea("div", {}, box);
    crea("span", { classe: "tenue", testo: `${titolo}: ` }, riga);
    riga.append(descriviGiro(elenco, p, S.campagna));
    if (elenco.length === 1 && elenco[0].tipo === "diretta") {
      crea("div", { classe: "manca", testo: "La diretta è l'unica voce per i monitor: resta in onda di continuo. Aggiungi immagini orizzontali per alternarla." }, box);
    }
  }
}

// Nel riquadro solo il riassunto: la sequenza si monta nella timeline in basso.
function disegnaContenutiPromozione(box, p) {
  const sezione = crea("section", { classe: "contenuti-campagna" }, box);
  crea("h3", { testo: `Sequenza (${p.contenuti.length} ${p.contenuti.length === 1 ? "voce" : "voci"})` }, sezione);
  crea("p", {
    classe: "nota",
    testo: p.contenuti.length
      ? "Ordine e durate si cambiano nella timeline «🎬 Sequenza» in basso: trascina le voci, tira il bordo destro di un blocco per la durata, e guarda l'anteprima prima di salvare."
      : "Trascina le immagini dalla libreria nella timeline «🎬 Sequenza» in basso, oppure selezionale e premi «Aggiungi».",
  }, sezione);
  const azioni = crea("div", { classe: "azioni-sequenza" }, sezione);
  crea("button", { type: "button", classe: "leggero", testo: "▶ Anteprima", disabled: !p.contenuti.length, onclick: () => apriAnteprima() }, azioni);
}

function datiCampagna(c) {
  return {
    nome: c.nome.trim(), data_inizio: c.data_inizio || null, data_fine: c.data_fine || null,
    codice: c.codice || "", fornitore: c.fornitore || "", colore: c.colore, note: c.note || "",
    priorita: c.priorita || 0, durata: c.durata || null,
    insegne: c.insegne, gruppi: c.gruppi, monitor: c.monitor,
  };
}

async function salvaCampagna() {
  const c = S.campagna;
  if (!c.nome.trim()) {
    avvisa("Dai un nome alla campagna.");
    document.getElementById("nome-campagna")?.focus();
    return;
  }
  try {
    const salvata = c.id ? await api("PATCH", `/api/campagne/${c.id}/`, datiCampagna(c)) : await api("POST", "/api/campagne/", datiCampagna(c));
    S.campagna = structuredClone(salvata);
    S.modificata = false;
    S.impostazioniAperte = false;
    avvisa(c.id ? "Campagna salvata: le sue promozioni seguono i nuovi destinatari entro un minuto." : "Campagna creata: ora aggiungi le sue promozioni.", "ok");
    await ricarica();
  } catch (errore) {
    avvisa(errore.message);
  }
}

async function salvaPromozione() {
  const c = S.campagna;
  const p = S.promozione;
  if (!p.nome.trim()) {
    avvisa("Dai un nome alla promozione.");
    document.getElementById("nome-promozione")?.focus();
    return;
  }
  if (!p.data_inizio || !p.data_fine) {
    avvisa("Indica le date di inizio e di fine della promozione.");
    return;
  }
  if (p.data_fine < p.data_inizio) {
    avvisa("La data di fine viene prima di quella di inizio.");
    return;
  }
  // Promozione fuori dalla validità della campagna: si propone di allungare la campagna.
  const inizio = c.data_inizio && p.data_inizio < c.data_inizio ? p.data_inizio : c.data_inizio;
  const fine = c.data_fine && p.data_fine > c.data_fine ? p.data_fine : c.data_fine;
  const allunga = inizio !== c.data_inizio || fine !== c.data_fine;
  if (allunga && !confirm(`La campagna «${c.nome}» è valida ${c.data_inizio ? `dal ${giornoBreve(c.data_inizio)} ` : ""}${c.data_fine ? `al ${giornoBreve(c.data_fine)}` : ""}.\n`
    + `La promozione va dal ${giornoBreve(p.data_inizio)} al ${giornoBreve(p.data_fine)}.\n\nAllungo la validità della campagna ${inizio ? `dal ${giornoBreve(inizio)} ` : ""}${fine ? `al ${giornoBreve(fine)}` : ""}?`)) {
    avvisa("Promozione non salvata: le sue date devono stare dentro la validità della campagna.");
    return;
  }
  try {
    if (allunga && c.id) {
      await api("PATCH", `/api/campagne/${c.id}/`, { data_inizio: inizio || null, data_fine: fine || null });
      Object.assign(c, { data_inizio: inizio, data_fine: fine });
    } else if (allunga) {
      Object.assign(c, { data_inizio: inizio, data_fine: fine });
    }
    // Una campagna nuova si salva insieme alla sua prima promozione.
    if (!c.id) {
      if (!c.nome.trim()) {
        avvisa("Dai un nome alla campagna.");
        return;
      }
      const creata = await api("POST", "/api/campagne/", datiCampagna(c));
      c.id = creata.id;
    }
    const dati = {
      campagna: c.id, nome: p.nome.trim(), data_inizio: p.data_inizio, data_fine: p.data_fine,
      ora_inizio: p.ora_inizio || null, ora_fine: p.ora_fine || null, giorni: p.giorni, contenuti: p.contenuti,
      // Solo per le voci ancora nella promozione.
      durate: Object.fromEntries(Object.entries(p.durate || {}).filter(([id]) => p.contenuti.includes(id))),
      audio: (p.audio || []).filter((id) => p.contenuti.includes(id)),
      ripeti: Object.fromEntries(Object.entries(p.ripeti || {}).filter(([id]) => p.contenuti.includes(id))),
    };
    const salvata = p.id ? await api("PATCH", `/api/promozioni/${p.id}/`, dati) : await api("POST", "/api/promozioni/", dati);
    S.promozione = structuredClone(salvata);
    S.modificata = false;
    const info = STATI[salvata.stato];
    avvisa(
      salvata.stato === "bozza"
        ? "Promozione salvata come bozza: servono immagini e destinatari nella campagna per mandarla in onda."
        : `Promozione salvata · ${info.testo.toLowerCase()}. Gli schermi la ricevono entro un minuto.`,
      "ok",
    );
    await ricarica();
  } catch (errore) {
    avvisa(errore.message);
  }
}

// --- Calendario ----------------------------------------------------------------------------------

// Dal più largo al più stretto: la lente «+» passa al livello dopo, «−» a quello prima.
const LIVELLI = [
  { titolo: "Anno", mesi: 12 },
  { titolo: "6 mesi", mesi: 6 },
  { titolo: "3 mesi", mesi: 3 },
  { titolo: "Mese", mesi: 1 },
  { titolo: "2 settimane", giorni: 14 },
];
const GIORNO = 86400000;
const ALTEZZA_CORSIA = 40;

const aggiungiMesi = (d, n) => new Date(d.getFullYear(), d.getMonth() + n, 1);
const aggiungiGiorni = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const lunedi = (d) => aggiungiGiorni(d, -((d.getDay() + 6) % 7));

// Il primo giorno della vista di quel livello che contiene (circa al centro) la data.
function inizioPer(livello, centro) {
  if (livello.giorni) return lunedi(aggiungiGiorni(centro, -3));
  if (livello.mesi === 12) return new Date(centro.getFullYear(), 0, 1);
  return aggiungiMesi(new Date(centro.getFullYear(), centro.getMonth(), 1), -Math.floor((livello.mesi - 1) / 2));
}

function intervalloCalendario() {
  const livello = LIVELLI[S.zoom];
  const inizio = S.inizioVista;
  const fine = livello.giorni ? aggiungiGiorni(inizio, livello.giorni) : aggiungiMesi(inizio, livello.mesi);
  const colonne = [];
  if (livello.mesi && livello.mesi > 1) {
    for (let k = 0; k < livello.mesi; k += 1) {
      const m = aggiungiMesi(inizio, k);
      colonne.push({ testo: livello.mesi === 12 ? MESI[m.getMonth()] : m.toLocaleDateString("it-IT", { month: "long", year: "numeric" }) });
    }
  } else {
    // Mese e due settimane: una colonna per giorno, il fine settimana in evidenza.
    for (let d = inizio; d < fine; d = aggiungiGiorni(d, 1)) {
      colonne.push({ testo: livello.giorni ? `${GIORNI[(d.getDay() + 6) % 7]} ${d.getDate()}` : String(d.getDate()), festivo: d.getDay() === 0 || d.getDay() === 6 });
    }
  }
  const titolo = livello.mesi === 12 ? String(inizio.getFullYear())
    : livello.mesi === 1 ? inizio.toLocaleDateString("it-IT", { month: "long", year: "numeric" })
      : `${data(isoLocale(inizio))} – ${data(isoLocale(aggiungiGiorni(fine, -1)))}`;
  return { inizio, fine, colonne, titolo };
}

function sposta(passo) {
  const livello = LIVELLI[S.zoom];
  S.inizioVista = livello.giorni ? aggiungiGiorni(S.inizioVista, passo * 7) : aggiungiMesi(S.inizioVista, passo * livello.mesi);
  disegnaCalendario();
}

function ingrandisci(passo, centro) {
  const nuovo = Math.max(0, Math.min(LIVELLI.length - 1, S.zoom + passo));
  if (nuovo === S.zoom) return;
  const { inizio, fine } = intervalloCalendario();
  const adesso = new Date();
  const riferimento = centro || (adesso >= inizio && adesso < fine ? adesso : new Date((inizio.getTime() + fine.getTime()) / 2));
  S.zoom = nuovo;
  S.inizioVista = inizioPer(LIVELLI[nuovo], riferimento);
  disegnaCalendario();
}

function disegnaCalendario() {
  chiudiDettaglio();
  const box = document.getElementById("calendario");
  box.replaceChildren();
  const { inizio, fine, colonne, titolo } = intervalloCalendario();
  const testa = crea("header", {}, box);
  crea("h2", { testo: "Calendario delle promozioni" }, testa);
  const comandi = crea("div", { classe: "anno" }, testa);
  const lente = crea("div", { classe: "lente" }, comandi);
  crea("button", {
    type: "button", classe: "leggero", testo: "－", disabled: S.zoom === 0,
    "data-aiuto": "Riduci: mostra un periodo più lungo (fino a tutto l'anno). Anche Ctrl + rotellina sul calendario.",
    onclick: () => ingrandisci(-1),
  }, lente);
  crea("span", { classe: "livello", testo: `🔍 ${LIVELLI[S.zoom].titolo}` }, lente);
  crea("button", {
    type: "button", classe: "leggero", testo: "＋", disabled: S.zoom === LIVELLI.length - 1,
    "data-aiuto": "Ingrandisci: mostra un periodo più corto, fino ai singoli giorni. Anche Ctrl + rotellina sul calendario.",
    onclick: () => ingrandisci(1),
  }, lente);
  crea("button", {
    type: "button", classe: "leggero", testo: "Oggi", "data-aiuto": "Riporta il calendario su oggi.",
    onclick: () => { S.inizioVista = inizioPer(LIVELLI[S.zoom], new Date()); disegnaCalendario(); },
  }, comandi);
  crea("button", { type: "button", classe: "leggero", testo: "‹", "data-aiuto": "Periodo precedente", onclick: () => sposta(-1) }, comandi);
  crea("strong", { testo: titolo }, comandi);
  crea("button", { type: "button", classe: "leggero", testo: "›", "data-aiuto": "Periodo successivo", onclick: () => sposta(1) }, comandi);

  const durata = fine - inizio;
  const posizione = (d) => Math.min(100, Math.max(0, ((d - inizio) / durata) * 100));
  const inizioDi = (p) => (p.data_inizio ? new Date(`${p.data_inizio}T00:00:00`) : inizio);
  const fineDi = (p) => (p.data_fine ? aggiungiGiorni(new Date(`${p.data_fine}T00:00:00`), 1) : fine);

  const tela = crea("div", { classe: "tela" }, box);
  tela.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const r = tela.getBoundingClientRect();
    const frazione = (e.clientX - r.left - parseFloat(getComputedStyle(tela).getPropertyValue("--colonna-nomi"))) / (r.width - parseFloat(getComputedStyle(tela).getPropertyValue("--colonna-nomi")));
    const centro = new Date(inizio.getTime() + Math.max(0, Math.min(1, frazione)) * durata);
    ingrandisci(e.deltaY < 0 ? 1 : -1, centro);
  }, { passive: false });
  const intestazione = crea("div", { classe: "mesi" }, tela);
  intestazione.style.gridTemplateColumns = `repeat(${colonne.length}, 1fr)`;
  for (const c of colonne) crea("span", { testo: c.testo, classe: c.festivo ? "festivo" : "" }, intestazione);

  // Gli eventi straordinari, sopra le campagne: hanno la precedenza su tutto.
  const eventi = eventiCaricati().filter((e) => new Date(e.inizio) < fine && new Date(e.fine) > inizio);
  let fasce = 0;
  if (eventi.length) {
    fasce += 1;
    const fascia = crea("div", { classe: "fascia fascia-eventi" }, tela);
    const etichetta = crea("button", { type: "button", classe: "etichetta-fascia", onclick: apriEventi, "data-aiuto": "Eventi straordinari: in quei momenti interrompono tutte le promozioni." }, fascia);
    crea("span", { testo: "⚡ Eventi straordinari" }, etichetta);
    const righe = crea("div", { classe: "righe" }, fascia);
    righe.style.backgroundSize = `calc(100% / ${colonne.length}) 100%`;
    righe.style.height = `${ALTEZZA_CORSIA + 4}px`;
    for (const e of eventi) {
      const i = new Date(e.inizio);
      const sinistra = posizione(i);
      const segno = crea("button", {
        type: "button", classe: `segno-evento ${e.stato}`, onclick: apriEventi,
        title: `${e.nome} · ${i.toLocaleString("it-IT", { dateStyle: "medium", timeStyle: "short" })} · ${Math.round(e.durata / 60)} min`,
      }, righe);
      Object.assign(segno.style, { left: `${sinistra}%`, width: `${Math.max(0.5, posizione(new Date(e.fine)) - sinistra)}%` });
      crea("span", { testo: `⚡ ${e.nome}` }, segno);
    }
  }

  // Una fascia per campagna; dentro, le sue promozioni su corsie se si sovrappongono.
  const spazioNome = durata * 0.16;
  for (const campagna of S.campagne) {
    const visibili = campagna.promozioni
      .filter((p) => inizioDi(p) < fine && fineDi(p) > inizio)
      .sort((a, b) => (a.data_inizio || "").localeCompare(b.data_inizio || ""));
    if (!visibili.length) continue;
    fasce += 1;
    const fascia = crea("div", { classe: `fascia${S.campagna?.id === campagna.id ? " aperta" : ""}` }, tela);
    const etichetta = crea("button", {
      type: "button", classe: "etichetta-fascia", onclick: () => apriCampagna(campagna.id),
      "data-aiuto": `Apri la campagna «${campagna.nome}»: destinatari, priorità e l'elenco delle sue promozioni.`,
    }, fascia);
    crea("span", { classe: "pallino", style: `background:${campagna.colore}` }, etichetta);
    crea("span", { testo: campagna.nome }, etichetta);
    const righe = crea("div", { classe: "righe" }, fascia);
    righe.style.backgroundSize = `calc(100% / ${colonne.length}) 100%`;
    const corsie = [];
    for (const p of visibili) {
      const i = inizioDi(p);
      const f = fineDi(p);
      const sinistra = posizione(i);
      const larghezza = Math.max(0.6, posizione(f) - sinistra);
      const stretta = larghezza < 12;
      const occupa = stretta ? new Date(Math.max(f, i.getTime() + spazioNome)) : f;
      let corsia = corsie.findIndex((termine) => termine <= i);
      if (corsia === -1) { corsia = corsie.length; corsie.push(occupa); } else corsie[corsia] = occupa;
      const barra = crea("button", {
        type: "button", classe: `barra-campagna ${STATI[p.stato]?.classe || ""}${S.promozione?.id === p.id ? " aperta" : ""}`,
        "aria-label": `${p.nome}, ${periodo(p)}`,
        "data-aiuto": `${p.nome} · ${periodo(p)} · ${p.contenuti.length} contenut${p.contenuti.length === 1 ? "o" : "i"}. Clic per vedere e modificare la promozione.`,
        onclick: (e) => { e.stopPropagation(); apriDettaglio(campagna, p, barra); },
      }, righe);
      Object.assign(barra.style, { left: `${sinistra}%`, width: `${larghezza}%`, top: `${corsia * ALTEZZA_CORSIA}px` });
      barra.style.setProperty("--colore", campagna.colore);
      if (stretta) {
        crea("span", { classe: "numeri", testo: String(p.contenuti.length) }, barra);
        const nome = crea("button", { type: "button", classe: "nome-accanto", testo: p.nome, "data-aiuto": `${periodo(p)}: clic per vedere e modificare la promozione.`, onclick: (e) => { e.stopPropagation(); apriDettaglio(campagna, p, barra); } }, righe);
        // Verso il bordo destro il nome va a sinistra della barra, per non uscire dal calendario.
        if (sinistra + larghezza > 78) Object.assign(nome.style, { right: `calc(${100 - sinistra}% + 6px)`, top: `${corsia * ALTEZZA_CORSIA}px`, textAlign: "right" });
        else Object.assign(nome.style, { left: `calc(${sinistra + larghezza}% + 6px)`, top: `${corsia * ALTEZZA_CORSIA}px` });
      } else {
        crea("span", { classe: "nome", testo: p.nome }, barra);
        crea("span", { classe: "numeri", testo: String(p.contenuti.length) }, barra);
      }
    }
    righe.style.height = `${corsie.length * ALTEZZA_CORSIA + 4}px`;
  }
  if (!fasce) crea("p", { classe: "vuoto vuoto-calendario", testo: "Nessuna promozione in questo periodo. Creane una, o importale tutte da CSV." }, tela);

  const adesso = new Date();
  if (adesso >= inizio && adesso < fine) {
    const linea = crea("div", { classe: "oggi", title: "Oggi" }, tela);
    linea.style.left = `calc(var(--colonna-nomi) + (100% - var(--colonna-nomi)) * ${posizione(adesso) / 100})`;
  }
}

// --- Dettaglio di una promozione (clic sulla barra del calendario) -------------------------------

function chiudiDettaglio() {
  document.getElementById("dettaglio-promo")?.remove();
}

function apriDettaglio(campagna, p, ancora) {
  chiudiDettaglio();
  const scheda = crea("div", { id: "dettaglio-promo", classe: "dettaglio-promo", role: "dialog", "aria-label": p.nome }, document.body);
  scheda.style.setProperty("--colore", campagna.colore);
  const testa = crea("div", { classe: "testa" }, scheda);
  const titoli = crea("div", {}, testa);
  const riga = crea("div", { classe: "campagna-riga" }, titoli);
  crea("span", { classe: "pallino", style: `background:${campagna.colore}` }, riga);
  crea("span", { testo: campagna.nome }, riga);
  crea("strong", { classe: "nome", testo: p.nome }, titoli);
  crea("button", { type: "button", classe: "leggero chiudi-dettaglio", testo: "✕", "aria-label": "Chiudi", onclick: chiudiDettaglio }, testa);

  const info = crea("div", { classe: "info" }, scheda);
  crea("span", { classe: `stato ${STATI[p.stato].classe}`, testo: STATI[p.stato].testo }, info);
  crea("span", { testo: periodo(p) }, info);
  if (p.ora_inizio || p.ora_fine) crea("span", { testo: `dalle ${p.ora_inizio?.slice(0, 5) || "…"} alle ${p.ora_fine?.slice(0, 5) || "…"}` }, info);
  if (p.giorni.length) crea("span", { testo: p.giorni.map((g) => GIORNI[g]).join(" ") }, info);
  const raggiunti = destinatari(campagna);
  const totem = raggiunti.filter((m) => m.orientamento === "verticale").length;
  crea("span", { testo: raggiunti.length ? `${totem} totem · ${raggiunti.length - totem} monitor` : "nessuno schermo" }, info);

  const contenuti = perId(S.contenuti);
  const immagini = p.contenuti.map((id) => contenuti.get(id)).filter(Boolean);
  if (p.stato === "conclusa") {
    crea("p", { classe: "nota", testo: `Promozione conclusa: ${immagini.length} immagini. Se non servono più, «Promozioni scadute» › «Libera spazio» le cancella.` }, scheda);
  } else if (!immagini.length) {
    crea("p", { classe: "nota", testo: "Ancora nessuna immagine: aprila e aggiungile dalla libreria." }, scheda);
  } else {
    for (const [chiave, titolo] of [["verticale", "Totem"], ["orizzontale", "Monitor"], ["diretta", "Dirette"], ["altro", "Tutti"]]) {
      const gruppo = immagini.filter((c) => orientamentoDi(c) === chiave);
      if (!gruppo.length) continue;
      crea("div", { classe: "titolo-striscia", testo: `${titolo} · ${gruppo.length}` }, scheda);
      const striscia = crea("div", { classe: `striscia ${chiave}` }, scheda);
      for (const c of gruppo) {
        const voce = crea("button", { type: "button", classe: "voce", title: c.nome, onclick: () => apriVisore(c) }, striscia);
        voce.appendChild(anteprima(c));
      }
    }
  }
  const azioni = crea("div", { classe: "azioni" }, scheda);
  crea("button", {
    type: "button", classe: "primario", testo: "Modifica la promozione",
    "data-aiuto": "Apre la promozione nel riquadro a destra per cambiarne nome, date e immagini.",
    onclick: () => { chiudiDettaglio(); apriPromozione(campagna.id, p.id); },
  }, azioni);
  crea("button", {
    type: "button", testo: "Vedi le immagini",
    "data-aiuto": "Mostra le immagini della promozione nella libreria, a grandezza piena.",
    onclick: () => {
      chiudiDettaglio();
      S.libreria = p.stato === "conclusa" ? "scaduti" : "attivi";
      S.cartella = p.id;
      disegnaLibreria();
      document.getElementById("libreria").scrollIntoView({ behavior: "smooth" });
    },
  }, azioni);

  // Vicino alla barra, dentro la finestra.
  const r = ancora.getBoundingClientRect();
  const b = scheda.getBoundingClientRect();
  const x = Math.max(12, Math.min(r.left + r.width / 2 - b.width / 2, window.innerWidth - b.width - 12));
  let y = r.top - b.height - 10;
  if (y < 70) y = Math.min(r.bottom + 10, window.innerHeight - b.height - 12);
  Object.assign(scheda.style, { left: `${x}px`, top: `${Math.max(12, y)}px` });
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape") chiudiDettaglio(); });
document.addEventListener("click", (e) => {
  const scheda = document.getElementById("dettaglio-promo");
  if (scheda && !scheda.contains(e.target)) chiudiDettaglio();
});
window.addEventListener("scroll", chiudiDettaglio, { passive: true });

// --- Importazione CSV ----------------------------------------------------------------------------

const TRACCIATO = [
  ["campagna", "obbligatoria", "Nome della campagna: le righe con lo stesso nome finiscono nella stessa campagna"],
  ["campagna_dal", "", "Validità della campagna, gg/mm/aaaa (es. 01/01/2026). Vuota: dalla prima promozione"],
  ["campagna_al", "", "Validità della campagna, gg/mm/aaaa (es. 31/12/2026). Vuota: fino all'ultima promozione"],
  ["promozione", "obbligatoria", "Nome della promozione: se esiste già nella campagna, viene aggiornata"],
  ["data_inizio", "obbligatoria", "gg/mm/aaaa"],
  ["data_fine", "obbligatoria", "gg/mm/aaaa (compresa)"],
  ["insegne", "", "Della campagna: nomi delle insegne separati da | (es. Insegna A|Insegna B)"],
  ["gruppi", "", "Della campagna: nomi dei gruppi di schermi separati da |"],
  ["monitor", "", "Della campagna: nomi di singoli monitor o totem separati da |"],
  ["ora_inizio", "", "hh:mm, se la promozione va in onda solo in una fascia"],
  ["ora_fine", "", "hh:mm"],
  ["giorni", "", "lun|mar|mer|gio|ven|sab|dom — vuoto: tutti"],
  ["priorita", "", "Della campagna: da -100 a 100, la più alta vince sulle altre nello stesso periodo"],
  ["durata", "", "Della campagna: secondi per immagine (vuoto: 10)"],
  ["colore", "", "Della campagna: colore nel calendario, es. #ec6a1f"],
  ["codice", "", "Della campagna: riferimento interno"],
  ["note", "", "Della campagna: testo libero"],
];

function preparaImportazione() {
  const finestra = document.getElementById("importa");
  const fileCsv = document.getElementById("file-csv");
  const esito = document.getElementById("esito-csv");
  const conferma = document.getElementById("conferma-csv");
  const tracciato = document.getElementById("tracciato");
  const t = crea("table", {}, tracciato);
  for (const [colonna, obbligo, spiegazione] of TRACCIATO) {
    const r = crea("tr", {}, t);
    crea("td", {}, r).appendChild(crea("code", { testo: colonna }));
    crea("td", { testo: obbligo }, r);
    crea("td", { testo: spiegazione }, r);
  }
  crea("p", { classe: "nota", testo: "Una riga per promozione. Separatore: punto e virgola (Excel italiano) o virgola. Prima riga: i nomi delle colonne. Insegne, gruppi e monitor devono esistere già; quelli delle righe di una stessa campagna si sommano." }, tracciato);

  document.getElementById("apri-importa").addEventListener("click", () => {
    fileCsv.value = "";
    esito.replaceChildren();
    conferma.disabled = true;
    conferma.textContent = "Importa";
    finestra.showModal();
  });
  document.getElementById("scarica-modello").href = conCliente("/api/campagne/modello/");

  const invia_ = async (prova) => {
    const dati = new FormData();
    dati.append("file", fileCsv.files[0]);
    if (prova) dati.append("prova", "1");
    try {
      return await api("POST", "/api/campagne/importa/", dati);
    } catch (errore) {
      if (errore.corpo?.righe) return errore.corpo;
      throw errore;
    }
  };

  fileCsv.addEventListener("change", async () => {
    esito.replaceChildren();
    conferma.disabled = true;
    if (!fileCsv.files[0]) return;
    try {
      const risposta = await invia_(true);
      mostraEsito(esito, risposta);
      const nuove = risposta.righe.filter((r) => r.azione === "crea").length;
      const aggiornate = risposta.righe.filter((r) => r.azione === "aggiorna").length;
      conferma.disabled = !risposta.valido;
      conferma.textContent = risposta.valido ? `Importa: ${nuove} promozioni nuove, ${aggiornate} aggiornate` : "Correggi gli errori e riprova";
    } catch (errore) {
      crea("p", { classe: "errore", testo: errore.message }, esito);
    }
  });

  conferma.addEventListener("click", async () => {
    conferma.disabled = true;
    try {
      const risposta = await invia_(false);
      finestra.close();
      avvisa(`${risposta.salvate} promozioni importate in ${risposta.campagne} campagne. Ora aggiungi le immagini a ciascuna, quando sono pronte.`, "ok");
      await ricarica();
    } catch (errore) {
      crea("p", { classe: "errore", testo: errore.message }, esito);
    }
  });
}

function mostraEsito(box, risposta) {
  box.replaceChildren();
  const errori = risposta.righe.filter((r) => r.errori.length).length;
  crea("p", {
    classe: errori ? "errore" : "ok",
    testo: errori ? `${errori} righe con errori: non verrà salvato nulla finché non le correggi.` : `${risposta.righe.length} righe corrette.`,
  }, box);
  const t = crea("table", { classe: "esito" }, box);
  const testa = crea("tr", {}, crea("thead", {}, t));
  for (const h of ["Riga", "Campagna", "Promozione", "Periodo", "Destinatari", "Esito"]) crea("th", { testo: h }, testa);
  const corpo = crea("tbody", {}, t);
  for (const r of risposta.righe) {
    const tr = crea("tr", { classe: r.errori.length ? "con-errori" : "" }, corpo);
    crea("td", { testo: String(r.riga) }, tr);
    crea("td", { testo: `${r.campagna}${r.campagna_nuova ? " (nuova)" : ""}${r.campagna_dal ? ` · ${data(r.campagna_dal)} → ${data(r.campagna_al)}` : ""}` }, tr);
    crea("td", { testo: r.promozione }, tr);
    crea("td", { testo: r.data_inizio ? `${data(r.data_inizio)} → ${data(r.data_fine)}` : "" }, tr);
    crea("td", { testo: [...(r.insegne || []), ...(r.gruppi || []), ...(r.monitor || [])].join(", ") }, tr);
    crea("td", { testo: r.errori.length ? r.errori.join("; ") : r.azione === "crea" ? "Nuova" : "Aggiorna" }, tr);
  }
}

// --- Dirette: lista M3U o indirizzo a mano -----------------------------------------------------

function preparaDirette() {
  const finestra = document.getElementById("dirette");
  const elenco = document.getElementById("elenco-canali");
  const conferma = document.getElementById("conferma-dirette");
  const aggiungi = document.getElementById("aggiungi-dirette");
  const scelti = new Map(); // url → canale
  let canali = [];

  const aggiorna = () => {
    const manuale = document.getElementById("url-diretta").value.trim();
    const quanti = scelti.size + (manuale ? 1 : 0);
    aggiungi.disabled = !quanti || !conferma.checked;
    aggiungi.textContent = quanti ? `Aggiungi ${quanti} ${quanti === 1 ? "canale" : "canali"} alla libreria` : "Aggiungi alla libreria";
  };

  const disegnaCanali = () => {
    elenco.replaceChildren();
    if (!canali.length) return;
    const filtri = crea("div", { classe: "filtri-canali" }, elenco);
    const cerca = crea("input", { type: "search", placeholder: `Cerca tra ${canali.length} canali…` }, filtri);
    const gruppi = [...new Set(canali.map((c) => c.gruppo).filter(Boolean))].sort();
    const gruppo = crea("select", {}, filtri);
    crea("option", { value: "", testo: "Tutte le categorie" }, gruppo);
    for (const g of gruppi) crea("option", { value: g, testo: g }, gruppo);
    const lista = crea("div", { classe: "lista-canali" }, elenco);
    const riempi = () => {
      lista.replaceChildren();
      const testo = cerca.value.trim().toLowerCase();
      const visibili = canali.filter((c) => (!testo || c.nome.toLowerCase().includes(testo)) && (!gruppo.value || c.gruppo === gruppo.value));
      for (const c of visibili.slice(0, 400)) {
        const voce = crea("label", { classe: `canale${c.presente ? " presente" : ""}` }, lista);
        crea("input", {
          type: "checkbox", checked: scelti.has(c.url),
          onchange: (e) => { e.target.checked ? scelti.set(c.url, c) : scelti.delete(c.url); aggiorna(); },
        }, voce);
        const logo = crea("span", { classe: "logo-canale" }, voce);
        if (c.logo) {
          const img = crea("img", { src: c.logo, alt: "", loading: "lazy", referrerPolicy: "no-referrer" }, logo);
          img.addEventListener("error", () => img.remove());
        }
        const testi = crea("span", { classe: "testi-canale" }, voce);
        crea("strong", { testo: c.nome }, testi);
        crea("small", { testo: [c.gruppo, c.presente ? "già in libreria: sceglilo per riusarlo" : ""].filter(Boolean).join(" · ") }, testi);
      }
      if (visibili.length > 400) crea("p", { classe: "nota", testo: `Mostrati 400 canali su ${visibili.length}: usa la ricerca.` }, lista);
    };
    cerca.addEventListener("input", riempi);
    gruppo.addEventListener("change", riempi);
    riempi();
  };

  document.getElementById("apri-dirette").addEventListener("click", () => {
    conferma.checked = false;
    aggiorna();
    finestra.showModal();
  });
  conferma.addEventListener("change", aggiorna);
  document.getElementById("url-diretta").addEventListener("input", aggiorna);

  const leggi = async (dati) => {
    try {
      const risposta = await api("POST", "/api/contenuti/m3u/", dati);
      canali = risposta.canali;
      scelti.clear();
      disegnaCanali();
      aggiorna();
    } catch (errore) {
      elenco.replaceChildren(crea("p", { classe: "errore", testo: errore.message }));
    }
  };
  for (const suggerimento of document.querySelectorAll(".suggerimento")) {
    suggerimento.addEventListener("click", () => {
      document.getElementById("url-m3u").value = suggerimento.dataset.url;
      leggi({ url: suggerimento.dataset.url });
    });
  }
  document.getElementById("leggi-m3u").addEventListener("click", () => {
    const url = document.getElementById("url-m3u").value.trim();
    if (!url) { document.getElementById("url-m3u").focus(); return; }
    leggi({ url });
  });
  document.getElementById("file-m3u").addEventListener("change", (e) => {
    if (!e.target.files[0]) return;
    const dati = new FormData();
    dati.append("file", e.target.files[0]);
    leggi(dati);
    e.target.value = "";
  });

  aggiungi.addEventListener("click", async () => {
    const elencoScelti = [...scelti.values()].map((c) => ({ nome: c.nome, url: c.url, logo: c.logo }));
    const manuale = document.getElementById("url-diretta").value.trim();
    if (manuale) elencoScelti.push({ nome: document.getElementById("nome-diretta").value.trim() || manuale, url: manuale, logo: "" });
    const gia = new Set(S.contenuti.filter((c) => c.tipo === "diretta").map((c) => c.url));
    const riusate = elencoScelti.filter((c) => gia.has(c.url)).length;
    try {
      const creati = await api("POST", "/api/contenuti/dirette/", { canali: elencoScelti, autorizzazione: conferma.checked });
      finestra.close();
      document.getElementById("url-diretta").value = "";
      document.getElementById("nome-diretta").value = "";
      S.libreria = "da_assegnare";
      S.cartella = null;
      await ricarica();
      for (const c of creati) S.selezione.add(c.id);
      disegnaLibreria();
      disegnaSelezione();
      avvisa(`${creati.length === 1 ? "Diretta selezionata" : `${creati.length} dirette selezionate`}${riusate ? " (già in libreria: si riusa la stessa)" : ""}: `
        + (S.promozione ? "trascinala nella sequenza o premi «+» per aggiungerla alla promozione aperta." : "mettila in una promozione, da sola o tra le immagini."), "ok");
      document.querySelector("#gallerie .galleria.diretta")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (errore) {
      avvisa(errore.message);
    }
  });
}

// --- Avvio -------------------------------------------------------------------------------------

async function sceltaCliente() {
  if (!S.io.di_piattaforma) return true;
  const clienti = await tutte("/api/piattaforma/clienti/");
  const scelta = document.getElementById("cliente");
  document.getElementById("scelta-cliente").hidden = false;
  crea("option", { value: "", testo: "— scegli —" }, scelta);
  for (const c of clienti) crea("option", { value: c.id, testo: c.nome, selected: c.id === cliente }, scelta);
  scelta.addEventListener("change", () => {
    ricordaCliente(scelta.value);
    const url = new URL(location.href);
    url.searchParams.set("cliente", scelta.value);
    location.href = url.toString();
  });
  if (!cliente) {
    avvisa("Scegli il cliente in alto per lavorare sulle sue campagne.", "info");
    return false;
  }
  return true;
}

async function avvia() {
  document.getElementById("al-pannello").href = conCliente("/pannello/");
  try {
    S.io = await api("GET", "/api/io/");
    const ruoli = { admin_assoluto: "SystemAdministrator", tecnico: "Tecnico", admin_cliente: "Administrator", user_cliente: "User" };
    document.getElementById("utente").textContent = `${S.io.username} · ${ruoli[S.io.ruolo] || ""}`;
  } catch {
    location.href = `/accesso/?next=${encodeURIComponent(location.pathname + location.search)}`;
    return;
  }
  disegnaMenu(document.getElementById("menu"), { io: S.io, attiva: "palinsesto", cliente });
  attivaAiuti();
  osservaAiutiPagina(document.body, AIUTI_PALINSESTO);
  if (!(await sceltaCliente())) return;
  preparaCaricamento();
  preparaImportazione();
  preparaDirette();
  preparaSequenza({
    S, crea, perId, conCliente, anteprima, avvisa, destinatari, confermaDirette, apriVisore,
    segnaModificata,
    aggiorna: () => { disegnaLibreria(); disegnaPannello(); },
    salva: salvaPromozione,
  });
  preparaEventi({
    S, crea, perId, api, tutte, avvisa, destinatari, confermaDirette, disegnaDestinatari,
    aggiorna: () => disegnaCalendario(),
    caricaFile: async (file) => {
      const nuovo = await invia(file, await misura(file));
      S.contenuti.unshift(nuovo);
      disegnaLibreria();
      return nuovo;
    },
  });
  document.getElementById("cerca").addEventListener("input", (e) => { S.cerca = e.target.value; disegnaLibreria(); });
  window.addEventListener("beforeunload", (e) => { if (S.modificata) e.preventDefault(); });
  try {
    await caricaTutto();
    disegna();
  } catch (errore) {
    avvisa(errore.message);
  }
}

avvia();
