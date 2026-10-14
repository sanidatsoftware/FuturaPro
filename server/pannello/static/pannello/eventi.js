// Gli eventi straordinari: a data e ora fissa, per una durata, con la precedenza su tutte le
// promozioni (es. la diretta di una partita, lo spot dell'inaugurazione). Il player interrompe la
// playlist, manda l'evento e poi riparte da capo. I numeri delle code continuano, con il loro
// volume. I testi che arrivano dai dati passano da textContent.

let H = null; // strumenti della pagina (stato, crea, api…), passati da palinsesto.js
let eventi = [];
let modulo = null; // l'evento in modifica (copia), o null

const STATI = {
  in_onda: ["In onda ora", "in-onda"],
  programmato: ["Programmato", "programmata"],
  concluso: ["Concluso", "conclusa"],
  sospeso: ["Sospeso", "bozza"],
};

export function preparaEventi(strumenti) {
  H = strumenti;
  document.getElementById("apri-eventi").addEventListener("click", apri);
}

export const eventiCaricati = () => eventi;

export async function caricaEventi() {
  eventi = await H.tutte("/api/eventi/");
  return eventi;
}

export async function apriEventi() {
  return apri();
}

async function apri() {
  const finestra = document.getElementById("eventi");
  modulo = null;
  try {
    await caricaEventi();
  } catch (errore) {
    H.avvisa(errore.message);
    return;
  }
  disegna();
  if (!finestra.open) finestra.showModal();
}

const due = (n) => String(n).padStart(2, "0");
const dataLocale = (d) => `${d.getFullYear()}-${due(d.getMonth() + 1)}-${due(d.getDate())}`;
const oraLocale = (d) => `${due(d.getHours())}:${due(d.getMinutes())}`;

function durataTesto(secondi) {
  const h = Math.floor(secondi / 3600);
  const m = Math.round((secondi % 3600) / 60);
  return [h ? `${h} h` : "", m ? `${m} min` : ""].filter(Boolean).join(" ") || `${secondi} s`;
}

function nuovo() {
  const tra = new Date(Date.now() + 3600_000);
  tra.setMinutes(0, 0, 0);
  return { nome: "", data: dataLocale(tra), ora: oraLocale(tra), ore: 0, minuti: 30, contenuto: "", audio: true, volume: 80, schermo_intero: false, attivo: true, insegne: [], gruppi: [], monitor: [], note: "" };
}

function daModificare(e) {
  const inizio = new Date(e.inizio);
  return {
    ...structuredClone(e), data: dataLocale(inizio), ora: oraLocale(inizio),
    ore: Math.floor(e.durata / 3600), minuti: Math.round((e.durata % 3600) / 60),
  };
}

function disegna() {
  const crea = H.crea;
  const corpo = document.getElementById("eventi-corpo");
  corpo.replaceChildren();
  if (modulo) {
    disegnaModulo(corpo);
    return;
  }
  const testa = crea("div", { classe: "testa-eventi" }, corpo);
  crea("p", {
    classe: "nota",
    testo: "All'ora indicata gli schermi scelti interrompono la playlist e mandano l'evento (una diretta, un video o un'immagine) per tutta la sua durata; poi la playlist riparte da capo. I numeri delle code restano sullo schermo e si sentono con il loro volume.",
  }, testa);
  crea("button", { type: "button", classe: "primario", testo: "＋ Nuovo evento", onclick: () => { modulo = nuovo(); disegna(); } }, testa);

  const contenuti = H.perId(H.S.contenuti);
  const ordinati = [...eventi].sort((a, b) => (a.stato === "concluso") - (b.stato === "concluso") || Date.parse(a.inizio) - Date.parse(b.inizio));
  if (!ordinati.length) crea("p", { classe: "vuoto", testo: "Nessun evento straordinario programmato." }, corpo);
  const elenco = crea("div", { classe: "elenco-eventi" }, corpo);
  for (const e of ordinati) {
    const [testoStato, classeStato] = STATI[e.stato] || STATI.programmato;
    const riga = crea("article", { classe: `evento ${e.stato}` }, elenco);
    const quando = crea("div", { classe: "quando-evento" }, riga);
    const inizio = new Date(e.inizio);
    crea("strong", { testo: inizio.toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" }) }, quando);
    crea("span", { testo: `${oraLocale(inizio)} – ${oraLocale(new Date(e.fine))}` }, quando);
    const testi = crea("div", { classe: "testi-evento" }, riga);
    const titolo = crea("div", {}, testi);
    crea("strong", { testo: e.nome }, titolo);
    crea("span", { classe: `stato ${classeStato}`, testo: testoStato }, titolo);
    const c = contenuti.get(e.contenuto);
    const raggiunti = H.destinatari(e).length;
    crea("small", {
      testo: [
        c ? `${c.tipo === "diretta" ? "📡" : c.tipo === "video" ? "▶" : "🖼"} ${c.nome}` : "contenuto non in libreria",
        durataTesto(e.durata),
        e.audio ? `🔊 ${e.volume}%` : "🔇 senza audio",
        e.schermo_intero ? "a tutto schermo" : "nella zona delle slide",
        `${raggiunti} schermi`,
      ].join(" · "),
    }, testi);
    const azioni = crea("div", { classe: "azioni-evento" }, riga);
    crea("button", { type: "button", testo: "Modifica", onclick: () => { modulo = daModificare(e); disegna(); } }, azioni);
    if (e.stato !== "concluso") {
      crea("button", {
        type: "button", classe: "leggero", testo: e.attivo ? "Sospendi" : "Riattiva",
        onclick: () => salvaParziale(e, { attivo: !e.attivo }, e.attivo ? "Evento sospeso: non va in onda." : "Evento riattivato."),
      }, azioni);
    }
    crea("button", {
      type: "button", classe: "pericolo", testo: "Elimina",
      onclick: async () => {
        if (!confirm(`Eliminare l'evento «${e.nome}»?${e.stato === "in_onda" ? " È in onda: gli schermi tornano alla playlist entro un minuto." : ""}`)) return;
        try {
          await H.api("DELETE", `/api/eventi/${e.id}/`);
          await caricaEventi();
          disegna();
          H.aggiorna();
        } catch (errore) {
          H.avvisa(errore.message);
        }
      },
    }, azioni);
  }
}

async function salvaParziale(e, dati, messaggio) {
  try {
    await H.api("PATCH", `/api/eventi/${e.id}/`, dati);
    await caricaEventi();
    H.avvisa(messaggio, "ok");
    disegna();
    H.aggiorna();
  } catch (errore) {
    H.avvisa(errore.message);
  }
}

function disegnaModulo(corpo) {
  const crea = H.crea;
  const m = modulo;
  crea("button", { type: "button", classe: "torna", testo: "← Tutti gli eventi", onclick: () => { modulo = null; disegna(); } }, corpo);
  crea("h3", { testo: m.id ? `Modifica «${m.nome}»` : "Nuovo evento straordinario" }, corpo);
  const campi = crea("div", { classe: "campi campi-evento" }, corpo);
  const campo = (etichetta, controllo, classe = "", aiuto = null) => {
    const l = crea("label", { classe: `campo ${classe}`, "data-aiuto": aiuto }, campi);
    crea("span", { testo: etichetta }, l);
    l.appendChild(controllo);
    return controllo;
  };
  const nome = campo("Nome", crea("input", { value: m.nome, placeholder: "es. Finale di campionato, Inaugurazione", maxLength: 200 }), "largo");
  nome.addEventListener("input", () => (m.nome = nome.value));
  const data = campo("Giorno", crea("input", { type: "date", value: m.data, required: true }));
  data.addEventListener("change", () => (m.data = data.value));
  const ora = campo("Ora di inizio", crea("input", { type: "time", value: m.ora, required: true }), "", "All'ora esatta gli schermi interrompono quello che stanno mostrando.");
  ora.addEventListener("change", () => (m.ora = ora.value));
  const durata = crea("div", { classe: "durata-evento" });
  const ore = crea("input", { type: "number", min: 0, max: 24, value: m.ore }, durata);
  durata.append(" ore ");
  const minuti = crea("input", { type: "number", min: 0, max: 59, value: m.minuti }, durata);
  durata.append(" min");
  campo("Durata", durata, "", "Per quanto tempo l'evento resta in onda. Un video più corto ricomincia finché dura l'evento.");
  ore.addEventListener("input", () => (m.ore = parseInt(ore.value, 10) || 0));
  minuti.addEventListener("input", () => (m.minuti = parseInt(minuti.value, 10) || 0));

  // Cosa va in onda: dirette e video prima, poi le immagini.
  const scelte = H.S.contenuti
    .filter((c) => ["diretta", "video", "immagine"].includes(c.tipo))
    .sort((a, b) => ["diretta", "video", "immagine"].indexOf(a.tipo) - ["diretta", "video", "immagine"].indexOf(b.tipo) || a.nome.localeCompare(b.nome));
  const contenuto = crea("select");
  crea("option", { value: "", testo: "— scegli una diretta, un video o un'immagine —" }, contenuto);
  for (const [tipo, etichetta] of [["diretta", "📡 Dirette"], ["video", "▶ Video"], ["immagine", "🖼 Immagini"]]) {
    const gruppo = crea("optgroup", { label: etichetta }, contenuto);
    for (const c of scelte.filter((x) => x.tipo === tipo)) crea("option", { value: c.id, testo: c.nome, selected: c.id === m.contenuto }, gruppo);
  }
  campo("Cosa va in onda", contenuto, "largo", "Una diretta della libreria (📡 Dirette), un video o un'immagine. Per un video nuovo: «Carica un video».");
  contenuto.addEventListener("change", () => (m.contenuto = contenuto.value));
  const carica = crea("input", { type: "file", accept: "video/mp4,video/webm,video/quicktime,image/*", hidden: true }, campi);
  crea("button", { type: "button", classe: "leggero", testo: "⇪ Carica un video", onclick: () => carica.click() }, campi);
  carica.addEventListener("change", async () => {
    const file = carica.files[0];
    if (!file) return;
    try {
      H.avvisa(`Caricamento di ${file.name}…`, "ok");
      const nuovo = await H.caricaFile(file);
      m.contenuto = nuovo.id;
      disegna();
      H.avvisa(`«${nuovo.nome}» caricato.`, "ok");
    } catch (errore) {
      H.avvisa(errore.message);
    }
  });

  // Audio e volume dell'evento: a parte dal volume degli annunci delle code.
  const audioBox = crea("div", { classe: "audio-evento" }, corpo);
  const conAudio = crea("label", { classe: "spunta-evento" }, audioBox);
  const audio = crea("input", { type: "checkbox", checked: m.audio }, conAudio);
  conAudio.append(" Con l'audio del video o della diretta");
  const volumeBox = crea("label", { classe: "volume-evento", "data-aiuto": "Il volume dell'evento. Gli annunci dei numeri delle code hanno il loro volume, nel layout (zona code)." }, audioBox);
  volumeBox.append("Volume ");
  const volume = crea("input", { type: "range", min: 0, max: 100, step: 5, value: m.volume, disabled: !m.audio }, volumeBox);
  const valore = crea("output", { testo: `${m.volume}%` }, volumeBox);
  audio.addEventListener("change", () => { m.audio = audio.checked; volume.disabled = !m.audio; });
  volume.addEventListener("input", () => { m.volume = parseInt(volume.value, 10); valore.textContent = `${m.volume}%`; });
  const interoBox = crea("label", { classe: "spunta-evento", "data-aiuto": "Sopra tutte le zone del layout. Senza: nella zona delle slide, con i numeri delle code sempre visibili." }, audioBox);
  const intero = crea("input", { type: "checkbox", checked: m.schermo_intero }, interoBox);
  interoBox.append(" A tutto schermo (i numeri delle code si sentono ma non si vedono)");
  intero.addEventListener("change", () => (m.schermo_intero = intero.checked));

  const destinatari = crea("div", {}, corpo);
  const ridisegnaDestinatari = () => {
    destinatari.replaceChildren();
    H.disegnaDestinatari(destinatari, m, {
      titolo: "Su quali schermi", modificata: () => {}, ridisegna: ridisegnaDestinatari,
      vuoto: "Scegli almeno un'insegna, un gruppo o uno schermo.",
    });
  };
  ridisegnaDestinatari();

  crea("p", { classe: "nota", testo: "Una diretta o un video in un locale aperto al pubblico vanno autorizzati (canone RAI speciale, licenze SIAE/SCF, abbonamenti o permessi dell'editore)." }, corpo);
  const piede = crea("div", { classe: "azioni" }, corpo);
  crea("button", { type: "button", classe: "leggero", testo: "Annulla", onclick: () => { modulo = null; disegna(); } }, piede);
  crea("button", { type: "button", classe: "primario", testo: m.id ? "Salva l'evento" : "Programma l'evento", onclick: salva }, piede);
}

async function salva() {
  const m = modulo;
  const secondi = (m.ore || 0) * 3600 + (m.minuti || 0) * 60;
  if (!m.nome.trim()) return H.avvisa("Dai un nome all'evento.");
  if (!m.data || !m.ora) return H.avvisa("Indica giorno e ora di inizio.");
  if (secondi < 60) return H.avvisa("La durata è di almeno un minuto.");
  if (!m.contenuto) return H.avvisa("Scegli cosa va in onda.");
  const inizio = new Date(`${m.data}T${m.ora}:00`);
  if (!m.id && inizio.getTime() + secondi * 1000 < Date.now()) return H.avvisa("L'evento finirebbe nel passato: controlla giorno e ora.");
  if (!H.confermaDirette([m.contenuto])) return;
  const dati = {
    nome: m.nome.trim(), inizio: inizio.toISOString(), durata: secondi, contenuto: m.contenuto,
    audio: m.audio, volume: m.volume, schermo_intero: m.schermo_intero, attivo: m.attivo,
    insegne: m.insegne, gruppi: m.gruppi, monitor: m.monitor, note: m.note || "",
  };
  try {
    await (m.id ? H.api("PATCH", `/api/eventi/${m.id}/`, dati) : H.api("POST", "/api/eventi/", dati));
    await caricaEventi();
    modulo = null;
    disegna();
    H.avvisa(`Evento ${m.id ? "salvato" : "programmato"}: gli schermi lo ricevono entro un minuto e lo mandano in onda all'ora esatta, anche senza rete.`, "ok");
    H.aggiorna();
  } catch (errore) {
    H.avvisa(errore.message);
  }
}
