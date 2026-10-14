// «Creazione palinsesto»: libreria divisa tra verticali (totem) e orizzontali (monitor),
// campagne che raggruppano promozioni, calendario e importazione da CSV.
//
// Una campagna tiene i destinatari (insegne, gruppi, monitor e totem); ogni sua
// promozione ha date e immagini. Sul server ogni promozione diventa una
// pubblicazione per orientamento: qui si sceglie solo cosa, quando e dove.
// I testi che arrivano dai dati passano sempre da textContent.

const parametri = new URLSearchParams(location.search);
const cliente = parametri.get("cliente");
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
  anno: new Date().getFullYear(),
  mese: new Date().getMonth(),
  vista: "anno",
  libreria: "da_assegnare",
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
const periodo = (c) => (c.data_inizio || c.data_fine ? `${data(c.data_inizio) || "…"} → ${data(c.data_fine) || "…"}` : "Senza date");
const peso = (byte) => (byte > 1048576 ? `${(byte / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(byte / 1024))} KB`);
const perId = (elenco) => new Map(elenco.map((v) => [v.id, v]));
const orientamentoDi = (c) => c.orientamento || "altro";
const promozioni = () => S.campagne.flatMap((c) => c.promozioni.map((p) => ({ ...p, campagnaDati: c })));

function confermaAbbandono() {
  return !S.modificata || confirm("Le modifiche non salvate andranno perse. Continuare?");
}

// --- Caricamento dei dati ---------------------------------------------------------------

async function caricaTutto() {
  const [contenuti, campagne, insegne, gruppi, monitor, sedi] = await Promise.all([
    tutte("/api/contenuti/"), tutte("/api/campagne/"), tutte("/api/insegne/"),
    tutte("/api/gruppi/"), tutte("/api/monitor/"), tutte("/api/sedi/"),
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
  const web = crea("div", { classe: `web ${classe}` });
  crea("span", { testo: "🌐" }, web);
  return web;
}

function disegnaSchedeLibreria(uso) {
  const box = document.getElementById("schede-libreria");
  box.replaceChildren();
  const conteggi = { da_assegnare: 0, attivi: 0, scaduti: 0, tutti: S.contenuti.length };
  for (const c of S.contenuti) conteggi[categoria(c, uso)] += 1;
  for (const [chiave, titolo] of Object.entries(VISTE_LIBRERIA)) {
    const b = crea("button", { type: "button", classe: `scheda-libreria${S.libreria === chiave ? " attiva" : ""}` }, box);
    b.append(titolo);
    crea("span", { classe: "conteggio", testo: String(conteggi[chiave]) }, b);
    b.addEventListener("click", () => {
      S.libreria = chiave;
      disegnaLibreria();
    });
  }
  if (S.libreria === "scaduti" && conteggi.scaduti) {
    crea("button", { type: "button", classe: "pericolo", testo: "Libera spazio…", onclick: liberaSpazio }, box);
  }
}

async function liberaSpazio() {
  try {
    const stima = await api("GET", "/api/contenuti/pulizia/");
    if (!stima.contenuti) {
      avvisa("Nessun contenuto da eliminare: quelli delle promozioni scadute sono usati anche altrove.", "info");
      return;
    }
    if (!confirm(`Eliminare definitivamente ${stima.contenuti} contenuti delle promozioni scadute (${peso(stima.spazio)})?\nI file spariscono anche dal server. Restano quelli usati da promozioni in corso o future, dalle playlist fatte a mano e dai layout.`)) return;
    const esito = await api("POST", "/api/contenuti/pulizia/");
    avvisa(`Eliminati ${esito.contenuti} contenuti: liberati ${peso(esito.spazio)}.`, "ok");
    await ricarica();
  } catch (errore) {
    avvisa(errore.message);
  }
}

function disegnaLibreria() {
  const uso = usoContenuti();
  disegnaSchedeLibreria(uso);
  const box = document.getElementById("gallerie");
  box.replaceChildren();
  const nellaPromozione = new Set(S.promozione?.contenuti || []);
  const filtro = S.cerca.trim().toLowerCase();
  const visibili = S.contenuti.filter(
    (c) => (!filtro || c.nome.toLowerCase().includes(filtro)) && (S.libreria === "tutti" || categoria(c, uso) === S.libreria),
  );
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

  const gruppi = [
    ["verticale", "Verticali", "per i totem", "▯"],
    ["orizzontale", "Orizzontali", "per i monitor", "▭"],
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
        tabIndex: 0, title: [c.nome, ...usi.map((p) => `· ${p.campagnaDati.nome} / ${p.nome}`)].join("\n"),
      }, griglia);
      const cornice = crea("div", { classe: "cornice" }, scheda);
      cornice.appendChild(anteprima(c));
      crea("span", { classe: "spunta", testo: "✓" }, cornice);
      if (nellaPromozione.has(c.id)) crea("span", { classe: "etichetta-campagna", testo: "nella promozione" }, cornice);
      else if (usi.length) crea("span", { classe: "etichetta-usato", testo: usi.length === 1 ? usi[0].nome : `${usi.length} promozioni` }, cornice);
      const azioni = crea("div", { classe: "azioni-media" }, cornice);
      crea("button", { type: "button", title: "Ingrandisci", testo: "⤢", onclick: (e) => { e.stopPropagation(); apriVisore(c); } }, azioni);
      if (S.promozione) {
        const dentro = nellaPromozione.has(c.id);
        crea("button", {
          type: "button", title: dentro ? "Togli dalla promozione" : "Aggiungi alla promozione", testo: dentro ? "−" : "+",
          onclick: (e) => { e.stopPropagation(); dentro ? togliDallaPromozione(c.id) : aggiungiAllaPromozione([c.id]); },
        }, azioni);
      }
      const didascalia = crea("div", { classe: "didascalia" }, scheda);
      crea("strong", { testo: c.nome }, didascalia);
      crea("span", { testo: [c.larghezza && `${c.larghezza}×${c.altezza}`, c.tipo === "video" ? "video" : null, c.dimensione ? peso(c.dimensione) : null].filter(Boolean).join(" · ") }, didascalia);
      const scegli = () => {
        S.selezione.has(c.id) ? S.selezione.delete(c.id) : S.selezione.add(c.id);
        scheda.classList.toggle("scelta", S.selezione.has(c.id));
        disegnaSelezione();
      };
      scheda.addEventListener("click", scegli);
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
  if (contenuto.tipo === "immagine") crea("img", { src: conCliente(`/api/contenuti/${contenuto.id}/file/`), alt: contenuto.nome }, box);
  else if (contenuto.tipo === "video") crea("video", { src: conCliente(`/api/contenuti/${contenuto.id}/file/`), controls: true, autoplay: true, muted: true }, box);
  else crea("p", { testo: contenuto.url }, box);
  crea("p", { classe: "nome", testo: `${contenuto.nome}${contenuto.larghezza ? ` · ${contenuto.larghezza}×${contenuto.altezza}` : ""}` }, box);
  finestra.showModal();
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
      onclick: () => { aggiungiAllaPromozione(scelti); S.selezione.clear(); disegnaLibreria(); disegnaSelezione(); },
    }, barra);
  }
  crea("button", {
    type: "button", classe: S.promozione ? "" : "primario", testo: "Nuova promozione con queste immagini",
    onclick: () => chiediNuovaPromozione({ contenuti: scelti }),
  }, barra);
  crea("button", {
    type: "button", classe: "pericolo", testo: "Elimina dalla libreria",
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

function nuovaCampagnaVuota(nome = "") {
  return {
    nome, codice: "", colore: "#ec6a1f", note: "", priorita: 0, durata: 10,
    insegne: [], gruppi: [], monitor: [], promozioni: [], stato: "bozza",
  };
}

function nuovaPromozioneVuota(valori = {}) {
  const inizio = new Date();
  const fine = new Date(inizio.getTime() + 13 * 86400000);
  return {
    nome: "", data_inizio: isoLocale(inizio), data_fine: isoLocale(fine),
    ora_inizio: null, ora_fine: null, giorni: [], contenuti: [], stato: "bozza", ...valori,
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
  const nome = crea("input", { placeholder: "Nome della nuova campagna, es. Autunno 2026", maxLength: 200 }, corpo);
  const aggiornaNome = () => (nome.hidden = Boolean(scelta.value));
  scelta.addEventListener("change", aggiornaNome);
  aggiornaNome();
  const azioni = crea("div", { classe: "azioni" }, corpo);
  crea("button", { type: "button", classe: "leggero", testo: "Annulla", onclick: () => finestra.close() }, azioni);
  crea("button", {
    type: "button", classe: "primario", testo: "Continua",
    onclick: () => {
      if (!scelta.value && !nome.value.trim()) { nome.focus(); return; }
      finestra.close();
      S.campagna = scelta.value ? structuredClone(S.campagne.find((c) => c.id === scelta.value)) : nuovaCampagnaVuota(nome.value.trim());
      apriNuovaPromozione(valori);
    },
  }, azioni);
  finestra.showModal();
}

function apriNuovaPromozione(valori) {
  S.promozione = nuovaPromozioneVuota(valori);
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
  document.getElementById("campagna").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function apriPromozione(campagnaId, promozioneId) {
  if (S.promozione?.id === promozioneId) return;
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

function segnaModificata() {
  S.modificata = true;
  document.querySelector(".piede-campagna .primario")?.classList.add("pulsa");
}

function aggiungiAllaPromozione(ids) {
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
  const box = document.getElementById("campagna");
  box.replaceChildren();

  const testa = crea("div", { classe: "testa-campagna" }, box);
  const scelta = crea("select", { "aria-label": "Campagna" }, testa);
  crea("option", { value: "", testo: S.campagna && !S.campagna.id ? `${S.campagna.nome || "Nuova campagna"} (non salvata)` : "— scegli una campagna —" }, scelta);
  for (const c of S.campagne) {
    crea("option", { value: c.id, testo: `${c.nome} · ${c.promozioni.length} promo · ${STATI[c.stato]?.testo || ""}`, selected: c.id === S.campagna?.id }, scelta);
  }
  scelta.addEventListener("change", () => (scelta.value ? apriCampagna(scelta.value) : null));
  crea("button", {
    type: "button", classe: "primario", testo: "+ Campagna",
    onclick: () => {
      if (!confermaAbbandono()) return;
      S.campagna = nuovaCampagnaVuota();
      S.promozione = null;
      S.modificata = true;
      disegna();
      document.getElementById("nome-campagna")?.focus();
    },
  }, testa);

  if (!S.campagna) {
    const vuoto = crea("div", { classe: "invito" }, box);
    crea("div", { classe: "illustrazione", testo: "▭ ▯ ▭" }, vuoto);
    crea("h3", { testo: "Prepara una promozione" }, vuoto);
    crea("p", { testo: "Trascina la cartella del volantino nella libreria, oppure seleziona le immagini e scegli «Nuova promozione con queste immagini». Le promozioni si raggruppano in campagne, che decidono dove vanno in onda." }, vuoto);
    return;
  }
  if (S.promozione) disegnaPromozione(box);
  else disegnaCampagna(box);
}

function campoIn(contenitore, etichetta, controllo, classe = "") {
  const l = crea("label", { classe: `campo ${classe}` }, contenitore);
  crea("span", { testo: etichetta }, l);
  l.appendChild(controllo);
  return controllo;
}

function disegnaCampagna(box) {
  const c = S.campagna;
  const stato = STATI[c.stato] || STATI.bozza;
  const intestazione = crea("div", { classe: "intestazione" }, box);
  crea("span", { classe: "tipo", testo: "Campagna" }, intestazione);
  crea("span", { classe: `stato ${stato.classe}`, testo: c.id ? stato.testo : "Nuova" }, intestazione);
  if (c.data_inizio) crea("span", { classe: "periodo", testo: periodo(c) }, intestazione);

  const campi = crea("div", { classe: "campi" }, box);
  const nome = campoIn(campi, "Nome della campagna", crea("input", { id: "nome-campagna", value: c.nome, placeholder: "es. Autunno 2026", maxLength: 200 }), "largo");
  nome.addEventListener("input", () => { c.nome = nome.value; segnaModificata(); });
  const colore = campoIn(campi, "Colore", crea("input", { type: "color", value: c.colore || "#ec6a1f" }), "stretto");
  colore.addEventListener("input", () => { c.colore = colore.value; segnaModificata(); });
  const durata = campoIn(campi, "Secondi per immagine", crea("input", { type: "number", min: 1, max: 3600, value: c.durata || "", placeholder: "10" }));
  durata.addEventListener("change", () => { c.durata = parseInt(durata.value, 10) || null; segnaModificata(); });
  const priorita = campoIn(campi, "Priorità", crea("input", { type: "number", min: -100, max: 100, value: c.priorita || 0, title: "Più alta: nello stesso periodo sostituisce le altre campagne" }));
  priorita.addEventListener("change", () => { c.priorita = parseInt(priorita.value, 10) || 0; segnaModificata(); });
  const codice = campoIn(campi, "Codice", crea("input", { value: c.codice || "", placeholder: "es. AUT26", maxLength: 50 }));
  codice.addEventListener("input", () => { c.codice = codice.value; segnaModificata(); });

  disegnaDestinatari(box, c);

  const sezione = crea("section", { classe: "elenco-promo" }, box);
  const titolo = crea("div", { classe: "titolo-sezione" }, sezione);
  crea("h3", { testo: `Promozioni (${c.promozioni.length})` }, titolo);
  crea("button", {
    type: "button", classe: "leggero", testo: "+ Nuova promozione",
    onclick: () => (confermaAbbandono() ? apriNuovaPromozione({}) : null),
  }, titolo);
  if (!c.id) crea("p", { classe: "vuoto", testo: "Salva la campagna, poi aggiungi le sue promozioni (o seleziona le immagini nella libreria)." }, sezione);
  else if (!c.promozioni.length) crea("p", { classe: "vuoto", testo: "Nessuna promozione: seleziona le immagini nella libreria e scegli «Nuova promozione con queste immagini»." }, sezione);
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

  const piede = crea("div", { classe: "piede-campagna" }, box);
  crea("button", { type: "button", classe: `primario grande${S.modificata ? " pulsa" : ""}`, testo: c.id ? "Salva la campagna" : "Crea la campagna", onclick: salvaCampagna }, piede);
  if (c.id) {
    crea("button", {
      type: "button", classe: "pericolo", testo: "Elimina",
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
  crea("button", { type: "button", classe: "leggero", testo: "Chiudi", onclick: chiudi }, piede);
}

function disegnaDestinatari(box, c) {
  const sezione = crea("section", { classe: "destinatari" }, box);
  crea("h3", { testo: "Dove vanno in onda le sue promozioni" }, sezione);

  const chips = (titolo, voci, campo, aiuto) => {
    if (!voci.length) return;
    const riga = crea("div", { classe: "gruppo-chip" }, sezione);
    crea("span", { classe: "etichetta", testo: titolo, title: aiuto }, riga);
    for (const v of voci) {
      const attivo = c[campo].includes(v.id);
      const chip = crea("button", { type: "button", classe: `chip${attivo ? " attivo" : ""}`, testo: v.nome }, riga);
      if (v.colore) chip.style.setProperty("--chip", v.colore);
      chip.addEventListener("click", () => {
        c[campo] = attivo ? c[campo].filter((x) => x !== v.id) : [...c[campo], v.id];
        segnaModificata();
        disegnaPannello();
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
    crea("summary", { testo: `${titolo} singoli${scelti ? ` · ${scelti} scelti` : ""}` }, blocco);
    const lista = crea("div", { classe: "lista-schermi" }, blocco);
    for (const m of elenco) {
      const voce = crea("label", { classe: "schermo" }, lista);
      crea("input", {
        type: "checkbox", checked: c.monitor.includes(m.id),
        onchange: (e) => {
          c.monitor = e.target.checked ? [...c.monitor, m.id] : c.monitor.filter((x) => x !== m.id);
          segnaModificata();
          disegnaPannello();
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
      : "Nessuno schermo scelto: le promozioni restano in bozza e non vanno in onda.";
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
  const nome = campoIn(campi, "Nome della promozione", crea("input", { id: "nome-promozione", value: p.nome, placeholder: "es. Volantino 6-19 ottobre", maxLength: 200 }), "largo");
  nome.addEventListener("input", () => { p.nome = nome.value; segnaModificata(); });
  const dal = campoIn(campi, "Dal", crea("input", { type: "date", value: p.data_inizio || "", required: true }));
  dal.addEventListener("change", () => { p.data_inizio = dal.value || null; segnaModificata(); });
  const al = campoIn(campi, "Al (compreso)", crea("input", { type: "date", value: p.data_fine || "", required: true }));
  al.addEventListener("change", () => { p.data_fine = al.value || null; segnaModificata(); });

  const avanzate = crea("details", { classe: "avanzate", open: Boolean(p.ora_inizio || p.ora_fine || p.giorni.length) }, box);
  crea("summary", { testo: "Solo in certe ore o certi giorni" }, avanzate);
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
  crea("button", { type: "button", classe: `primario grande${S.modificata ? " pulsa" : ""}`, testo: p.id ? "Salva la promozione" : "Crea la promozione", onclick: salvaPromozione }, piede);
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

function disegnaContenutiPromozione(box, p) {
  const sezione = crea("section", { classe: "contenuti-campagna" }, box);
  crea("h3", { testo: `Immagini (${p.contenuti.length})` }, sezione);
  if (!p.contenuti.length) {
    crea("p", { classe: "vuoto", testo: "Seleziona le immagini nella libreria e premi «Aggiungi», o usa il + su ognuna." }, sezione);
    return;
  }
  const contenuti = perId(S.contenuti);
  for (const [chiave, titolo] of [["verticale", "Totem"], ["orizzontale", "Monitor"], ["altro", "Tutti"]]) {
    const ids = p.contenuti.filter((id) => contenuti.has(id) && orientamentoDi(contenuti.get(id)) === chiave);
    if (!ids.length) continue;
    crea("div", { classe: "titolo-striscia", testo: `${titolo} · ${ids.length}` }, sezione);
    const striscia = crea("div", { classe: `striscia ${chiave}` }, sezione);
    ids.forEach((id, posizione) => {
      const x = contenuti.get(id);
      const voce = crea("div", { classe: "voce", draggable: true, title: `${x.nome} — trascina per cambiare l'ordine` }, striscia);
      voce.appendChild(anteprima(x));
      crea("span", { classe: "posizione", testo: String(posizione + 1) }, voce);
      crea("button", { type: "button", classe: "togli", title: "Togli", testo: "✕", onclick: () => togliDallaPromozione(id) }, voce);
      voce.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/futurapro", id); voce.classList.add("trascinata"); });
      voce.addEventListener("dragend", () => voce.classList.remove("trascinata"));
      voce.addEventListener("dragover", (e) => { e.preventDefault(); voce.classList.add("bersaglio"); });
      voce.addEventListener("dragleave", () => voce.classList.remove("bersaglio"));
      voce.addEventListener("drop", (e) => {
        e.preventDefault();
        const spostato = e.dataTransfer.getData("text/futurapro");
        if (!spostato || spostato === id) return;
        const ordine = p.contenuti.filter((v) => v !== spostato);
        ordine.splice(ordine.indexOf(id), 0, spostato);
        p.contenuti = ordine;
        segnaModificata();
        disegnaPannello();
      });
    });
  }
}

function datiCampagna(c) {
  return {
    nome: c.nome.trim(), codice: c.codice || "", colore: c.colore, note: c.note || "",
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
  try {
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

function intervalloCalendario() {
  if (S.vista === "trimestre") {
    const inizio = new Date(S.anno, S.mese, 1);
    const fine = new Date(S.anno, S.mese + 3, 1);
    const mesi = [0, 1, 2].map((k) => new Date(S.anno, S.mese + k, 1));
    return { inizio, fine, mesi, titolo: `${MESI[mesi[0].getMonth()]} – ${MESI[mesi[2].getMonth()]} ${mesi[2].getFullYear()}` };
  }
  const mesi = MESI.map((_, k) => new Date(S.anno, k, 1));
  return { inizio: new Date(S.anno, 0, 1), fine: new Date(S.anno + 1, 0, 1), mesi, titolo: String(S.anno) };
}

function sposta(passo) {
  if (S.vista === "trimestre") {
    const d = new Date(S.anno, S.mese + passo * 3, 1);
    S.anno = d.getFullYear();
    S.mese = d.getMonth();
  } else S.anno += passo;
  disegnaCalendario();
}

const ALTEZZA_CORSIA = 40;

function disegnaCalendario() {
  const box = document.getElementById("calendario");
  box.replaceChildren();
  const { inizio, fine, mesi, titolo } = intervalloCalendario();
  const testa = crea("header", {}, box);
  crea("h2", { testo: "Calendario delle promozioni" }, testa);
  const comandi = crea("div", { classe: "anno" }, testa);
  const viste = crea("div", { classe: "viste" }, comandi);
  for (const [vista, etichetta] of [["anno", "Anno"], ["trimestre", "3 mesi"]]) {
    crea("button", {
      type: "button", classe: `chip${S.vista === vista ? " attivo" : ""}`, testo: etichetta,
      onclick: () => {
        S.vista = vista;
        if (vista === "trimestre") {
          const adesso = new Date();
          S.anno = adesso.getFullYear();
          S.mese = adesso.getMonth();
        }
        disegnaCalendario();
      },
    }, viste);
  }
  crea("button", { type: "button", classe: "leggero", testo: "‹", title: "Indietro", onclick: () => sposta(-1) }, comandi);
  crea("strong", { testo: titolo }, comandi);
  crea("button", { type: "button", classe: "leggero", testo: "›", title: "Avanti", onclick: () => sposta(1) }, comandi);

  const giorni = (fine - inizio) / 86400000;
  const posizione = (d) => Math.min(100, Math.max(0, ((d - inizio) / 86400000 / giorni) * 100));
  const inizioDi = (p) => (p.data_inizio ? new Date(`${p.data_inizio}T00:00:00`) : inizio);
  const fineDi = (p) => (p.data_fine ? new Date(new Date(`${p.data_fine}T00:00:00`).getTime() + 86400000) : fine);

  const tela = crea("div", { classe: `tela vista-${S.vista}` }, box);
  const intestazioneMesi = crea("div", { classe: "mesi" }, tela);
  intestazioneMesi.style.gridTemplateColumns = `repeat(${mesi.length}, 1fr)`;
  for (const m of mesi) crea("span", { testo: S.vista === "trimestre" ? m.toLocaleDateString("it-IT", { month: "long", year: "numeric" }) : MESI[m.getMonth()] }, intestazioneMesi);

  // Una fascia per campagna; dentro, le sue promozioni su corsie se si sovrappongono.
  const spazioNome = giorni * 0.16 * 86400000;
  let fasce = 0;
  for (const campagna of S.campagne) {
    const visibili = campagna.promozioni
      .filter((p) => inizioDi(p) < fine && fineDi(p) > inizio)
      .sort((a, b) => (a.data_inizio || "").localeCompare(b.data_inizio || ""));
    if (!visibili.length) continue;
    fasce += 1;
    const fascia = crea("div", { classe: `fascia${S.campagna?.id === campagna.id ? " aperta" : ""}` }, tela);
    const etichetta = crea("button", { type: "button", classe: "etichetta-fascia", onclick: () => apriCampagna(campagna.id) }, fascia);
    crea("span", { classe: "pallino", style: `background:${campagna.colore}` }, etichetta);
    crea("span", { testo: campagna.nome }, etichetta);
    const righe = crea("div", { classe: "righe" }, fascia);
    righe.style.backgroundSize = `calc(100% / ${mesi.length}) 100%`;
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
        title: `${campagna.nome} · ${p.nome}\n${periodo(p)}\n${STATI[p.stato]?.testo || ""} · ${p.contenuti.length} immagini`,
        onclick: () => apriPromozione(campagna.id, p.id),
      }, righe);
      Object.assign(barra.style, { left: `${sinistra}%`, width: `${larghezza}%`, top: `${corsia * ALTEZZA_CORSIA}px` });
      barra.style.setProperty("--colore", campagna.colore);
      if (stretta) {
        crea("span", { classe: "numeri", testo: String(p.contenuti.length) }, barra);
        const nome = crea("button", { type: "button", classe: "nome-accanto", testo: p.nome, onclick: () => apriPromozione(campagna.id, p.id) }, righe);
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

// --- Importazione CSV ----------------------------------------------------------------------------

const TRACCIATO = [
  ["campagna", "obbligatoria", "Nome della campagna: le righe con lo stesso nome finiscono nella stessa campagna"],
  ["promozione", "obbligatoria", "Nome della promozione: se esiste già nella campagna, viene aggiornata"],
  ["data_inizio", "obbligatoria", "gg/mm/aaaa"],
  ["data_fine", "obbligatoria", "gg/mm/aaaa (compresa)"],
  ["insegne", "", "Della campagna: nomi delle insegne separati da | (es. Tocal|Tocal Express)"],
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
    crea("td", { testo: `${r.campagna}${r.campagna_nuova ? " (nuova)" : ""}` }, tr);
    crea("td", { testo: r.promozione }, tr);
    crea("td", { testo: r.data_inizio ? `${data(r.data_inizio)} → ${data(r.data_fine)}` : "" }, tr);
    crea("td", { testo: [...(r.insegne || []), ...(r.gruppi || []), ...(r.monitor || [])].join(", ") }, tr);
    crea("td", { testo: r.errori.length ? r.errori.join("; ") : r.azione === "crea" ? "Nuova" : "Aggiorna" }, tr);
  }
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
  for (const id of ["al-pannello", "torna"]) document.getElementById(id).href = conCliente("/pannello/");
  try {
    S.io = await api("GET", "/api/io/");
  } catch {
    location.href = `/accesso/?next=${encodeURIComponent(location.pathname + location.search)}`;
    return;
  }
  if (!(await sceltaCliente())) return;
  preparaCaricamento();
  preparaImportazione();
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
