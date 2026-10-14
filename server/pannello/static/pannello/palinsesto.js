// «Creazione palinsesto»: libreria divisa tra verticali (totem) e orizzontali (monitor),
// campagne con date e destinatari, calendario dell'anno e importazione da CSV.
//
// Lavora sulle API del pannello: /api/contenuti/, /api/campagne/, /api/insegne/…
// Una campagna diventa sul server una pubblicazione per orientamento: qui si
// sceglie solo cosa, quando e dove. I testi dei dati passano sempre da textContent.

const parametri = new URLSearchParams(location.search);
let cliente = parametri.get("cliente");
const MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];
const STATI = {
  in_onda: { testo: "In onda", classe: "in-onda" },
  programmata: { testo: "Programmata", classe: "programmata" },
  bozza: { testo: "Bozza", classe: "bozza" },
  conclusa: { testo: "Conclusa", classe: "conclusa" },
};
const FORMATI_ACCETTATI = /\.(jpe?g|png|gif|webp|mp4|webm|mov)$/i;

const S = {
  io: null,
  contenuti: [],
  campagne: [],
  insegne: [],
  gruppi: [],
  monitor: [],
  sedi: [],
  selezione: new Set(),
  campagna: null, // quella aperta nell'editor (copia modificabile)
  modificata: false,
  anno: new Date().getFullYear(),
  mese: new Date().getMonth(),
  vista: "anno",
  cerca: "",
  soloLiberi: false,
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
  if (testo && tipo !== "errore") timerAvviso = setTimeout(() => (box.hidden = true), 5000);
}

const oggi = () => new Date().toISOString().slice(0, 10);
const data = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("it-IT", { day: "numeric", month: "short", year: "numeric" }) : "");
const periodo = (c) => (c.data_inizio || c.data_fine ? `${data(c.data_inizio) || "…"} → ${data(c.data_fine) || "…"}` : "Senza date");
const peso = (byte) => (byte > 1048576 ? `${(byte / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(byte / 1024))} KB`);
const perId = (elenco) => new Map(elenco.map((v) => [v.id, v]));
const orientamentoDi = (c) => c.orientamento || "altro";

// --- Caricamento dei dati ---------------------------------------------------------------

async function caricaTutto() {
  const [contenuti, campagne, insegne, gruppi, monitor, sedi] = await Promise.all([
    tutte("/api/contenuti/"), tutte("/api/campagne/"), tutte("/api/insegne/"),
    tutte("/api/gruppi/"), tutte("/api/monitor/"), tutte("/api/sedi/"),
  ]);
  Object.assign(S, { contenuti, campagne, insegne, gruppi, monitor, sedi });
}

async function ricarica() {
  await caricaTutto();
  if (S.campagna?.id) {
    const aggiornata = S.campagne.find((c) => c.id === S.campagna.id);
    if (aggiornata && !S.modificata) S.campagna = structuredClone(aggiornata);
  }
  disegna();
}

function disegna() {
  disegnaStatistiche();
  disegnaLibreria();
  disegnaCampagna();
  disegnaCalendario();
  disegnaSelezione();
}

// --- Statistiche --------------------------------------------------------------------------

function disegnaStatistiche() {
  const box = document.getElementById("statistiche");
  box.replaceChildren();
  const conta = (stato) => S.campagne.filter((c) => c.stato === stato).length;
  const verticali = S.contenuti.filter((c) => c.orientamento === "verticale").length;
  const orizzontali = S.contenuti.filter((c) => c.orientamento === "orizzontale").length;
  const totem = S.monitor.filter((m) => m.orientamento === "verticale").length;
  for (const [valore, etichetta, classe] of [
    [conta("in_onda"), "campagne in onda", "in-onda"],
    [conta("programmata"), "programmate", "programmata"],
    [conta("bozza"), "bozze da completare", "bozza"],
    [`${verticali} · ${orizzontali}`, "contenuti verticali · orizzontali", ""],
    [`${totem} · ${S.monitor.length - totem}`, "totem · monitor", ""],
  ]) {
    const scheda = crea("div", { classe: `stat ${classe}` }, box);
    crea("strong", { testo: String(valore) }, scheda);
    crea("span", { testo: etichetta }, scheda);
  }
}

// --- Libreria ---------------------------------------------------------------------------------

function usati() {
  const insieme = new Set();
  for (const c of S.campagne) for (const id of c.contenuti) insieme.add(id);
  return insieme;
}

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

function disegnaLibreria() {
  const box = document.getElementById("gallerie");
  box.replaceChildren();
  const giaUsati = usati();
  const nellaCampagna = new Set(S.campagna?.contenuti || []);
  const filtro = S.cerca.trim().toLowerCase();
  const visibili = S.contenuti.filter(
    (c) => (!filtro || c.nome.toLowerCase().includes(filtro)) && (!S.soloLiberi || !giaUsati.has(c.id)),
  );

  const gruppi = [
    ["verticale", "Verticali", "per i totem", "▯"],
    ["orizzontale", "Orizzontali", "per i monitor", "▭"],
    ["altro", "Altri contenuti", "pagine web e video senza misure: vanno a tutti", "◇"],
  ];
  for (const [chiave, titolo, sottotitolo, simbolo] of gruppi) {
    const elementi = visibili.filter((c) => orientamentoDi(c) === chiave);
    if (chiave === "altro" && !elementi.length) continue;
    const sezione = crea("section", { classe: `galleria ${chiave}` }, box);
    const testa = crea("header", {}, sezione);
    const titoli = crea("div", { classe: "titoli" }, testa);
    crea("span", { classe: "simbolo", testo: simbolo }, titoli);
    crea("h2", { testo: titolo }, titoli);
    crea("span", { classe: "conteggio", testo: String(elementi.length) }, titoli);
    crea("span", { classe: "sottotitolo", testo: sottotitolo }, titoli);
    const tuttiScelti = elementi.length > 0 && elementi.every((c) => S.selezione.has(c.id));
    crea("button", {
      type: "button", classe: "leggero", testo: tuttiScelti ? "Deseleziona tutti" : "Seleziona tutti", disabled: !elementi.length,
      onclick: () => {
        for (const c of elementi) (tuttiScelti ? S.selezione.delete(c.id) : S.selezione.add(c.id));
        disegnaLibreria();
        disegnaSelezione();
      },
    }, testa);

    const griglia = crea("div", { classe: "griglia" }, sezione);
    if (!elementi.length) {
      crea("p", { classe: "vuoto", testo: filtro ? "Nessun contenuto con questo nome." : "Ancora nessun contenuto: trascinali qui sopra." }, griglia);
    }
    for (const c of elementi) {
      const scheda = crea("article", {
        classe: `media${S.selezione.has(c.id) ? " scelta" : ""}${nellaCampagna.has(c.id) ? " in-campagna" : ""}`,
        tabIndex: 0, title: c.nome,
      }, griglia);
      const cornice = crea("div", { classe: "cornice" }, scheda);
      cornice.appendChild(anteprima(c));
      crea("span", { classe: "spunta", testo: "✓" }, cornice);
      if (nellaCampagna.has(c.id)) crea("span", { classe: "etichetta-campagna", testo: "nella campagna" }, cornice);
      else if (giaUsati.has(c.id)) crea("span", { classe: "etichetta-usato", testo: "in uso" }, cornice);
      const azioni = crea("div", { classe: "azioni-media" }, cornice);
      crea("button", {
        type: "button", title: "Ingrandisci", testo: "⤢",
        onclick: (e) => { e.stopPropagation(); apriVisore(c); },
      }, azioni);
      if (S.campagna) {
        crea("button", {
          type: "button", title: nellaCampagna.has(c.id) ? "Togli dalla campagna" : "Aggiungi alla campagna",
          testo: nellaCampagna.has(c.id) ? "−" : "+",
          onclick: (e) => { e.stopPropagation(); nellaCampagna.has(c.id) ? togliDallaCampagna(c.id) : aggiungiAllaCampagna([c.id]); },
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
  crea("strong", { testo: `${scelti.length} ${scelti.length === 1 ? "contenuto selezionato" : "contenuti selezionati"}` }, barra);
  if (S.campagna) {
    crea("button", {
      type: "button", classe: "primario", testo: `Aggiungi a «${S.campagna.nome || "nuova campagna"}»`,
      onclick: () => { aggiungiAllaCampagna(scelti); S.selezione.clear(); disegnaLibreria(); disegnaSelezione(); },
    }, barra);
  }
  crea("button", {
    type: "button", classe: S.campagna ? "" : "primario", testo: "Nuova campagna con questi",
    onclick: () => { nuovaCampagna({ contenuti: scelti }); S.selezione.clear(); disegna(); document.getElementById("nome-campagna")?.focus(); },
  }, barra);
  crea("button", {
    type: "button", classe: "pericolo", testo: "Elimina dalla libreria",
    onclick: async () => {
      if (!confirm(`Eliminare ${scelti.length} contenuti dalla libreria? Spariranno anche dalle campagne e dalle playlist.`)) return;
      try {
        for (const id of scelti) await api("DELETE", `/api/contenuti/${id}/`);
        S.selezione.clear();
        avvisa("Contenuti eliminati.", "ok");
        await ricarica();
      } catch (errore) {
        avvisa(errore.message);
        await ricarica();
      }
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

function invia(file, misure, avanzamento) {
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
    xhr.upload.onprogress = (e) => e.lengthComputable && avanzamento(e.loaded / e.total);
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
        caricati.push(await invia(f, await misura(f), () => {}));
      } catch (errore) {
        errori.push(`${f.name}: ${errore.message}`);
      }
      fatti += 1;
      aggiorna();
    }
  }));
  box.hidden = true;
  await ricarica();
  for (const c of caricati) S.selezione.add(c.id);
  disegnaLibreria();
  disegnaSelezione();
  if (errori.length) avvisa(`Non caricati: ${errori.join(" · ")}`);
  else avvisa(`${caricati.length} contenuti caricati${scartati ? ` (${scartati} file ignorati)` : ""}: sono già selezionati.`, "ok");
  if (cartella && caricati.length && !S.campagna) {
    // Una cartella è quasi sempre una campagna: la si propone già pronta.
    nuovaCampagna({ nome: cartella, contenuti: caricati.map((c) => c.id) });
    S.selezione.clear();
    disegna();
    avvisa(`Cartella «${cartella}» caricata: ho preparato la campagna con i suoi ${caricati.length} contenuti. Scegli date e destinatari, poi salva.`, "ok");
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
      const tutte_ = [];
      const prossime = () => lettore.readEntries(async (blocco) => {
        if (!blocco.length) { await Promise.all(tutte_.map(leggi)); ok(); return; }
        tutte_.push(...blocco);
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

// --- Campagna: editor -----------------------------------------------------------------------

function nuovaCampagna(valori = {}) {
  if (S.modificata && !confirm("Le modifiche alla campagna aperta non sono salvate. Continuare?")) return;
  const inizio = new Date();
  const fine = new Date(inizio.getTime() + 13 * 86400000);
  S.campagna = {
    nome: "", codice: "", colore: "#ec6a1f", note: "",
    data_inizio: inizio.toISOString().slice(0, 10), data_fine: fine.toISOString().slice(0, 10),
    ora_inizio: null, ora_fine: null, giorni: [], priorita: 0, durata: 10,
    insegne: [], gruppi: [], monitor: [], contenuti: [], stato: "bozza",
    ...valori,
  };
  S.modificata = Boolean(valori.contenuti?.length);
}

function apriCampagna(id) {
  if (S.campagna?.id === id) return;
  if (S.modificata && !confirm("Le modifiche alla campagna aperta non sono salvate. Continuare?")) return;
  const trovata = S.campagne.find((c) => c.id === id);
  if (!trovata) return;
  S.campagna = structuredClone(trovata);
  S.modificata = false;
  disegna();
  document.getElementById("campagna").scrollIntoView({ behavior: "smooth", block: "start" });
}

function segnaModificata() {
  S.modificata = true;
  document.getElementById("salva-campagna")?.classList.add("pulsa");
}

function aggiungiAllaCampagna(ids) {
  if (!S.campagna) nuovaCampagna();
  const presenti = new Set(S.campagna.contenuti);
  for (const id of ids) if (!presenti.has(id)) S.campagna.contenuti.push(id);
  segnaModificata();
  disegnaLibreria();
  disegnaCampagna();
}

function togliDallaCampagna(id) {
  S.campagna.contenuti = S.campagna.contenuti.filter((c) => c !== id);
  segnaModificata();
  disegnaLibreria();
  disegnaCampagna();
}

// Chi riceve davvero la campagna: monitor scelti, quelli dei gruppi e quelli delle sedi delle insegne.
function destinatari(campagna) {
  const sediInsegne = new Set(S.sedi.filter((s) => s.insegna && campagna.insegne.includes(s.insegna)).map((s) => s.id));
  const gruppi = new Set(campagna.gruppi);
  const scelti = new Set(campagna.monitor);
  return S.monitor.filter((m) => scelti.has(m.id) || m.gruppi.some((g) => gruppi.has(g)) || sediInsegne.has(m.sede));
}

function disegnaCampagna() {
  const box = document.getElementById("campagna");
  box.replaceChildren();

  // Scelta della campagna da modificare.
  const testa = crea("div", { classe: "testa-campagna" }, box);
  const scelta = crea("select", { "aria-label": "Campagna" }, testa);
  crea("option", { value: "", testo: S.campagna && !S.campagna.id ? "Nuova campagna (non salvata)" : "— scegli una campagna —" }, scelta);
  for (const [stato, info] of Object.entries(STATI)) {
    const delloStato = S.campagne.filter((c) => c.stato === stato);
    if (!delloStato.length) continue;
    const gruppo = crea("optgroup", { label: info.testo }, scelta);
    for (const c of delloStato) crea("option", { value: c.id, testo: `${c.nome} · ${periodo(c)}`, selected: c.id === S.campagna?.id }, gruppo);
  }
  scelta.addEventListener("change", () => scelta.value && apriCampagna(scelta.value));
  crea("button", { type: "button", classe: "primario", testo: "+ Nuova", onclick: () => { nuovaCampagna(); disegna(); document.getElementById("nome-campagna")?.focus(); } }, testa);

  if (!S.campagna) {
    const vuoto = crea("div", { classe: "invito" }, box);
    crea("div", { classe: "illustrazione", testo: "▭ ▯ ▭" }, vuoto);
    crea("h3", { testo: "Componi una campagna" }, vuoto);
    crea("p", { testo: "Seleziona i contenuti nella libreria (o trascina una cartella), poi «Nuova campagna con questi». Oppure apri una campagna dal calendario qui sotto." }, vuoto);
    return;
  }
  const c = S.campagna;

  const stato = STATI[c.stato] || STATI.bozza;
  const intestazione = crea("div", { classe: "intestazione" }, box);
  crea("span", { classe: `stato ${stato.classe}`, testo: c.id ? stato.testo : "Nuova" }, intestazione);
  crea("span", { classe: "periodo", testo: periodo(c) }, intestazione);

  const campi = crea("div", { classe: "campi" }, box);
  const campo = (etichetta, controllo, classe = "") => {
    const l = crea("label", { classe: `campo ${classe}` }, campi);
    crea("span", { testo: etichetta }, l);
    l.appendChild(controllo);
    return controllo;
  };
  const nome = campo("Nome della campagna", crea("input", { id: "nome-campagna", value: c.nome, placeholder: "es. Volantino 6-19 ottobre", maxLength: 200 }), "largo");
  nome.addEventListener("input", () => { c.nome = nome.value; segnaModificata(); });
  const dal = campo("Dal", crea("input", { type: "date", value: c.data_inizio || "" }));
  dal.addEventListener("change", () => { c.data_inizio = dal.value || null; segnaModificata(); });
  const al = campo("Al", crea("input", { type: "date", value: c.data_fine || "" }));
  al.addEventListener("change", () => { c.data_fine = al.value || null; segnaModificata(); });
  const colore = campo("Colore", crea("input", { type: "color", value: c.colore || "#ec6a1f" }), "stretto");
  colore.addEventListener("input", () => { c.colore = colore.value; segnaModificata(); });
  const durata = campo("Secondi per immagine", crea("input", { type: "number", min: 1, max: 3600, value: c.durata || "", placeholder: "10" }), "stretto");
  durata.addEventListener("change", () => { c.durata = parseInt(durata.value, 10) || null; segnaModificata(); });

  // Opzioni avanzate: fasce orarie, giorni, priorità, codice.
  const avanzate = crea("details", { classe: "avanzate", open: Boolean(c.ora_inizio || c.ora_fine || c.giorni.length || c.priorita || c.codice) }, box);
  crea("summary", { testo: "Orari, giorni, priorità e codice" }, avanzate);
  const griglia = crea("div", { classe: "campi" }, avanzate);
  const campoA = (etichetta, controllo) => {
    const l = crea("label", { classe: "campo" }, griglia);
    crea("span", { testo: etichetta }, l);
    l.appendChild(controllo);
    return controllo;
  };
  const dalle = campoA("Dalle", crea("input", { type: "time", value: c.ora_inizio?.slice(0, 5) || "" }));
  dalle.addEventListener("change", () => { c.ora_inizio = dalle.value || null; segnaModificata(); });
  const alle = campoA("Alle", crea("input", { type: "time", value: c.ora_fine?.slice(0, 5) || "" }));
  alle.addEventListener("change", () => { c.ora_fine = alle.value || null; segnaModificata(); });
  const priorita = campoA("Priorità", crea("input", { type: "number", min: -100, max: 100, value: c.priorita || 0, title: "Con priorità più alta, sostituisce le altre campagne nello stesso periodo" }));
  priorita.addEventListener("change", () => { c.priorita = parseInt(priorita.value, 10) || 0; segnaModificata(); });
  const codice = campoA("Codice", crea("input", { value: c.codice || "", placeholder: "es. V41", maxLength: 50 }));
  codice.addEventListener("input", () => { c.codice = codice.value; segnaModificata(); });
  const giorni = crea("div", { classe: "giorni" }, avanzate);
  crea("span", { testo: "Giorni (nessuno = tutti)" }, giorni);
  GIORNI.forEach((g, i) => {
    const attivo = c.giorni.includes(i);
    crea("button", {
      type: "button", classe: `chip${attivo ? " attivo" : ""}`, testo: g,
      onclick: (e) => {
        c.giorni = attivo ? c.giorni.filter((x) => x !== i) : [...c.giorni, i].sort();
        segnaModificata();
        e.currentTarget.classList.toggle("attivo");
        disegnaCampagna();
      },
    }, giorni);
  });

  disegnaDestinatari(box, c);
  disegnaContenutiCampagna(box, c);

  const piede = crea("div", { classe: "piede-campagna" }, box);
  crea("button", { type: "button", id: "salva-campagna", classe: `primario grande${S.modificata ? " pulsa" : ""}`, testo: c.id ? "Salva le modifiche" : "Crea la campagna", onclick: salvaCampagna }, piede);
  if (c.id) {
    crea("button", {
      type: "button", classe: "pericolo", testo: "Elimina",
      onclick: async () => {
        if (!confirm(`Eliminare la campagna «${c.nome}»? I contenuti restano nella libreria.`)) return;
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
  crea("button", {
    type: "button", classe: "leggero", testo: "Chiudi",
    onclick: () => {
      if (S.modificata && !confirm("Le modifiche non salvate andranno perse. Chiudere?")) return;
      S.campagna = null;
      S.modificata = false;
      disegna();
    },
  }, piede);
}

function disegnaDestinatari(box, c) {
  const sezione = crea("section", { classe: "destinatari" }, box);
  crea("h3", { testo: "Dove va in onda" }, sezione);

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
        disegnaCampagna();
      });
    }
  };
  chips("Insegne", S.insegne, "insegne", "Tutti i monitor e i totem dei negozi di queste insegne");
  chips("Gruppi", S.gruppi, "gruppi", "Tutti i monitor e i totem di questi gruppi");

  const sedi = perId(S.sedi);
  for (const [orientamento, titolo] of [["verticale", "Totem"], ["orizzontale", "Monitor"]]) {
    const elenco = S.monitor.filter((m) => m.orientamento === orientamento);
    if (!elenco.length) continue;
    const blocco = crea("details", { classe: "singoli", open: elenco.some((m) => c.monitor.includes(m.id)) }, sezione);
    const scelti = elenco.filter((m) => c.monitor.includes(m.id)).length;
    crea("summary", { testo: `${titolo} singoli${scelti ? ` · ${scelti} scelti` : ""}` }, blocco);
    const lista = crea("div", { classe: "lista-schermi" }, blocco);
    for (const m of elenco) {
      const voce = crea("label", { classe: "schermo" }, lista);
      crea("input", {
        type: "checkbox", checked: c.monitor.includes(m.id),
        onchange: (e) => {
          c.monitor = e.target.checked ? [...c.monitor, m.id] : c.monitor.filter((x) => x !== m.id);
          segnaModificata();
          disegnaCampagna();
        },
      }, voce);
      crea("span", { classe: `led${m.online ? " acceso" : ""}`, title: m.online ? "In linea" : "Non in linea" }, voce);
      crea("span", { testo: m.nome }, voce);
      crea("small", { testo: sedi.get(m.sede)?.nome || "" }, voce);
    }
  }

  // Riepilogo: quanti schermi e quanti contenuti per ciascuno.
  const raggiunti = destinatari(c);
  const totem = raggiunti.filter((m) => m.orientamento === "verticale").length;
  const monitor = raggiunti.length - totem;
  const contenuti = perId(S.contenuti);
  const scelti = c.contenuti.map((id) => contenuti.get(id)).filter(Boolean);
  const vert = scelti.filter((x) => x.orientamento === "verticale").length;
  const oriz = scelti.filter((x) => x.orientamento === "orizzontale").length;
  const altri = scelti.length - vert - oriz;
  const riepilogo = crea("div", { classe: `riepilogo${raggiunti.length ? "" : " attenzione"}` }, sezione);
  if (!raggiunti.length) {
    riepilogo.textContent = "Nessuno schermo scelto: la campagna resta in bozza e non va in onda.";
    return;
  }
  const righe = [];
  if (totem) righe.push(`${totem} totem ricevono ${vert + altri} contenuti${vert === 0 && altri === 0 ? " — mancano immagini verticali!" : ""}`);
  if (monitor) righe.push(`${monitor} monitor ricevono ${oriz + altri} contenuti${oriz === 0 && altri === 0 ? " — mancano immagini orizzontali!" : ""}`);
  for (const r of righe) crea("div", { testo: r, classe: r.includes("mancano") ? "manca" : "" }, riepilogo);
}

function disegnaContenutiCampagna(box, c) {
  const sezione = crea("section", { classe: "contenuti-campagna" }, box);
  crea("h3", { testo: `Contenuti (${c.contenuti.length})` }, sezione);
  if (!c.contenuti.length) {
    crea("p", { classe: "vuoto", testo: "Seleziona i contenuti nella libreria e premi «Aggiungi», o usa il + su ogni immagine." }, sezione);
    return;
  }
  const contenuti = perId(S.contenuti);
  for (const [chiave, titolo] of [["verticale", "Totem"], ["orizzontale", "Monitor"], ["altro", "Tutti"]]) {
    const ids = c.contenuti.filter((id) => contenuti.has(id) && orientamentoDi(contenuti.get(id)) === chiave);
    if (!ids.length) continue;
    crea("div", { classe: "titolo-striscia", testo: `${titolo} · ${ids.length}` }, sezione);
    const striscia = crea("div", { classe: `striscia ${chiave}` }, sezione);
    ids.forEach((id, posizione) => {
      const x = contenuti.get(id);
      const voce = crea("div", { classe: "voce", draggable: true, title: `${x.nome} — trascina per cambiare l'ordine` }, striscia);
      voce.appendChild(anteprima(x));
      crea("span", { classe: "posizione", testo: String(posizione + 1) }, voce);
      crea("button", { type: "button", classe: "togli", title: "Togli", testo: "✕", onclick: () => togliDallaCampagna(id) }, voce);
      voce.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/futurapro", id); voce.classList.add("trascinata"); });
      voce.addEventListener("dragend", () => voce.classList.remove("trascinata"));
      voce.addEventListener("dragover", (e) => { e.preventDefault(); voce.classList.add("bersaglio"); });
      voce.addEventListener("dragleave", () => voce.classList.remove("bersaglio"));
      voce.addEventListener("drop", (e) => {
        e.preventDefault();
        const spostato = e.dataTransfer.getData("text/futurapro");
        if (!spostato || spostato === id) return;
        const ordine = c.contenuti.filter((v) => v !== spostato);
        ordine.splice(ordine.indexOf(id), 0, spostato);
        c.contenuti = ordine;
        segnaModificata();
        disegnaCampagna();
      });
    });
  }
}

async function salvaCampagna() {
  const c = S.campagna;
  if (!c.nome.trim()) {
    avvisa("Dai un nome alla campagna.");
    document.getElementById("nome-campagna")?.focus();
    return;
  }
  const dati = {
    nome: c.nome.trim(), codice: c.codice || "", colore: c.colore, note: c.note || "",
    data_inizio: c.data_inizio || null, data_fine: c.data_fine || null,
    ora_inizio: c.ora_inizio || null, ora_fine: c.ora_fine || null, giorni: c.giorni,
    priorita: c.priorita || 0, durata: c.durata || null,
    insegne: c.insegne, gruppi: c.gruppi, monitor: c.monitor, contenuti: c.contenuti,
  };
  try {
    const salvata = c.id ? await api("PATCH", `/api/campagne/${c.id}/`, dati) : await api("POST", "/api/campagne/", dati);
    S.campagna = structuredClone(salvata);
    S.modificata = false;
    const info = STATI[salvata.stato];
    avvisa(
      salvata.stato === "bozza"
        ? "Campagna salvata come bozza: aggiungi contenuti e destinatari per mandarla in onda."
        : `Campagna salvata · ${info.testo.toLowerCase()}. Gli schermi la ricevono entro un minuto.`,
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

function disegnaCalendario() {
  const box = document.getElementById("calendario");
  box.replaceChildren();
  const { inizio, fine, mesi, titolo } = intervalloCalendario();
  const testa = crea("header", {}, box);
  crea("h2", { testo: "Calendario delle campagne" }, testa);
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

  const tela = crea("div", { classe: `tela vista-${S.vista}` }, box);
  const intestazioneMesi = crea("div", { classe: "mesi" }, tela);
  intestazioneMesi.style.gridTemplateColumns = `repeat(${mesi.length}, 1fr)`;
  for (const m of mesi) crea("span", { testo: S.vista === "trimestre" ? m.toLocaleDateString("it-IT", { month: "long", year: "numeric" }) : MESI[m.getMonth()] }, intestazioneMesi);

  const visibili = S.campagne
    .filter((c) => c.data_inizio || c.data_fine)
    .filter((c) => {
      const i = c.data_inizio ? new Date(`${c.data_inizio}T00:00:00`) : inizio;
      const f = c.data_fine ? new Date(`${c.data_fine}T23:59:59`) : fine;
      return i < fine && f >= inizio;
    })
    .sort((a, b) => (a.data_inizio || "").localeCompare(b.data_inizio || ""));

  const righe = crea("div", { classe: "righe" }, tela);
  righe.style.backgroundSize = `calc(100% / ${mesi.length}) 100%`;
  if (!visibili.length) crea("p", { classe: "vuoto", testo: `Nessuna campagna in questo periodo. Creane una, o importale tutte da CSV.` }, righe);
  // Le campagne si dispongono su corsie: una nuova corsia solo se si sovrappongono.
  // Le barre strette hanno il nome accanto, che occupa spazio anche lui.
  const spazioNome = (giorni * 0.16) * 86400000;
  const corsie = [];
  for (const c of visibili) {
    const i = c.data_inizio ? new Date(`${c.data_inizio}T00:00:00`) : inizio;
    const f = c.data_fine ? new Date(new Date(`${c.data_fine}T00:00:00`).getTime() + 86400000) : fine;
    const sinistra = posizione(i);
    const larghezza = Math.max(0.6, posizione(f) - sinistra);
    const stretta = larghezza < 12;
    const occupa = stretta ? new Date(Math.max(f, i.getTime() + spazioNome)) : f;
    let corsia = corsie.findIndex((termine) => termine <= i);
    if (corsia === -1) { corsia = corsie.length; corsie.push(occupa); } else corsie[corsia] = occupa;
    const barra = crea("button", {
      type: "button", classe: `barra-campagna ${STATI[c.stato]?.classe || ""}${S.campagna?.id === c.id ? " aperta" : ""}`,
      title: `${c.nome}\n${periodo(c)}\n${STATI[c.stato]?.testo || ""} · ${c.contenuti.length} contenuti`,
      onclick: () => apriCampagna(c.id),
    }, righe);
    Object.assign(barra.style, { left: `${sinistra}%`, width: `${larghezza}%`, top: `${corsia * 40}px` });
    barra.style.setProperty("--colore", c.colore);
    if (stretta) {
      crea("span", { classe: "numeri", testo: `${c.contenuti.length}` }, barra);
      const etichetta = crea("button", { type: "button", classe: "nome-accanto", testo: c.nome, onclick: () => apriCampagna(c.id) }, righe);
      // Verso il bordo destro il nome va a sinistra della barra, per non uscire dal calendario.
      if (sinistra + larghezza > 78) {
        Object.assign(etichetta.style, { right: `calc(${100 - sinistra}% + 6px)`, top: `${corsia * 40}px`, textAlign: "right" });
      } else {
        Object.assign(etichetta.style, { left: `calc(${sinistra + larghezza}% + 6px)`, top: `${corsia * 40}px` });
      }
    } else {
      crea("span", { classe: "nome", testo: c.nome }, barra);
      crea("span", { classe: "numeri", testo: `${c.contenuti.length}` }, barra);
    }
  }
  righe.style.height = `${Math.max(1, corsie.length) * 40 + 8}px`;

  const adesso = new Date();
  if (adesso >= inizio && adesso < fine) {
    const linea = crea("div", { classe: "oggi", title: "Oggi" }, tela);
    linea.style.left = `${posizione(adesso)}%`;
  }

  const senzaDate = S.campagne.filter((c) => !c.data_inizio && !c.data_fine);
  if (senzaDate.length) {
    const altre = crea("div", { classe: "senza-date" }, box);
    crea("span", { testo: "Senza date:" }, altre);
    for (const c of senzaDate) crea("button", { type: "button", classe: "chip", testo: c.nome, onclick: () => apriCampagna(c.id) }, altre);
  }
}

// --- Importazione CSV ----------------------------------------------------------------------------

const TRACCIATO = [
  ["nome", "obbligatoria", "Nome della campagna: se esiste già, viene aggiornata"],
  ["codice", "", "Riferimento interno, es. numero del volantino"],
  ["data_inizio", "obbligatoria", "gg/mm/aaaa"],
  ["data_fine", "obbligatoria", "gg/mm/aaaa (compresa)"],
  ["insegne", "", "Nomi delle insegne separati da | (es. Tocal|Tocal Express)"],
  ["gruppi", "", "Nomi dei gruppi di schermi separati da |"],
  ["monitor", "", "Nomi di singoli monitor o totem separati da |"],
  ["ora_inizio", "", "hh:mm, se va in onda solo in una fascia"],
  ["ora_fine", "", "hh:mm"],
  ["giorni", "", "lun|mar|mer|gio|ven|sab|dom — vuoto: tutti"],
  ["priorita", "", "Numero da -100 a 100: la più alta vince sulle altre nello stesso periodo"],
  ["durata", "", "Secondi per immagine (vuoto: 10)"],
  ["colore", "", "Colore nel calendario, es. #ec6a1f"],
  ["note", "", "Testo libero"],
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
  crea("p", { classe: "nota", testo: "Separatore: punto e virgola (Excel italiano) o virgola. Prima riga: i nomi delle colonne. Insegne, gruppi e monitor devono esistere già." }, tracciato);

  document.getElementById("apri-importa").addEventListener("click", () => {
    fileCsv.value = "";
    esito.replaceChildren();
    conferma.disabled = true;
    finestra.showModal();
  });
  document.getElementById("scarica-modello").href = conCliente("/api/campagne/modello/");

  const invia = async (prova) => {
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
      const risposta = await invia(true);
      mostraEsito(esito, risposta);
      const nuove = risposta.righe.filter((r) => r.azione === "crea").length;
      const aggiornate = risposta.righe.filter((r) => r.azione === "aggiorna").length;
      conferma.disabled = !risposta.valido;
      conferma.textContent = risposta.valido ? `Importa: ${nuove} nuove, ${aggiornate} aggiornate` : "Correggi gli errori e riprova";
    } catch (errore) {
      crea("p", { classe: "errore", testo: errore.message }, esito);
    }
  });

  conferma.addEventListener("click", async () => {
    conferma.disabled = true;
    try {
      const risposta = await invia(false);
      finestra.close();
      avvisa(`${risposta.salvate} campagne importate. Ora aggiungi i contenuti a ciascuna, quando sono pronti.`, "ok");
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
    testo: errori ? `${errori} righe con errori: nessuna campagna verrà salvata finché non le correggi.` : `${risposta.righe.length} righe corrette.`,
  }, box);
  const t = crea("table", { classe: "esito" }, box);
  const testa = crea("tr", {}, crea("thead", {}, t));
  for (const h of ["Riga", "Campagna", "Periodo", "Destinatari", "Esito"]) crea("th", { testo: h }, testa);
  const corpo = crea("tbody", {}, t);
  for (const r of risposta.righe) {
    const tr = crea("tr", { classe: r.errori.length ? "con-errori" : "" }, corpo);
    crea("td", { testo: String(r.riga) }, tr);
    crea("td", { testo: r.nome }, tr);
    crea("td", { testo: r.data_inizio ? `${data(r.data_inizio)} → ${data(r.data_fine)}` : "" }, tr);
    crea("td", { testo: [...(r.insegne || []), ...(r.gruppi || []), ...(r.monitor || [])].join(", ") || (r.errori.length ? "" : "— (bozza)") }, tr);
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
  document.getElementById("solo-liberi").addEventListener("change", (e) => { S.soloLiberi = e.target.checked; disegnaLibreria(); });
  window.addEventListener("beforeunload", (e) => { if (S.modificata) e.preventDefault(); });
  try {
    await caricaTutto();
    disegna();
  } catch (errore) {
    avvisa(errore.message);
  }
}

avvia();
