// La sequenza di una promozione, come in un programma di montaggio: una corsia per i
// monitor (orizzontali, con le dirette) e una per i totem (verticali). Ogni voce è un
// blocco lungo quanto resta in onda; si seleziona (anche più d'una), si trascina per
// cambiare l'ordine, si tira il bordo destro per cambiarne la durata, e si prova tutto
// nell'anteprima prima di salvare. I testi che arrivano dai dati passano da textContent.

import { avviaDiretta } from "../player/motore.js";

let H = null; // gli strumenti della pagina (stato, crea, api…), passati da palinsesto.js

const LARGHEZZA_MINIMA = 46; // px: anche una voce brevissima resta afferrabile
const SCALE = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32]; // px per secondo
const CORSIE = [
  { chiave: "orizzontale", titolo: "Monitor", simbolo: "▭", aiuto: "Cosa ripetono i monitor orizzontali: le immagini orizzontali e le dirette, nell'ordine." },
  { chiave: "verticale", titolo: "Totem", simbolo: "▯", aiuto: "Cosa ripetono i totem verticali: le immagini verticali, nell'ordine." },
];
const FORMATO_TRASCINAMENTO = "text/futurapro-sequenza";
export const FORMATO_LIBRERIA = "text/futurapro-libreria";

const Q = {
  promozione: undefined, // di quale promozione sono selezione e storia
  selezione: new Set(),
  ancora: null, // l'ultima voce cliccata, per la selezione con ⇧
  storia: [],
  scala: null, // null: si adatta alla larghezza
  ridotta: false,
  lunghezze: new Map(), // secondi dei video, letti dal browser
};

export function preparaSequenza(strumenti) {
  H = strumenti;
  document.addEventListener("keydown", tastiera);
  const dock = document.getElementById("sequenza");
  // Il resto della pagina non deve finire sotto la timeline.
  new ResizeObserver(() => {
    document.body.style.setProperty("--altezza-dock", `${dock.hidden ? 0 : dock.offsetHeight}px`);
  }).observe(dock);
}

// --- Dati ---------------------------------------------------------------------------------------

const formatoDi = (x) => (x.tipo === "diretta" ? "orizzontale" : x.orientamento || null);

function vociCorsia(chiave) {
  const contenuti = H.perId(H.S.contenuti);
  return H.S.promozione.contenuti.map((id) => contenuti.get(id)).filter((x) => x && (formatoDi(x) === chiave || formatoDi(x) === null));
}

// Quanto resta in onda una voce, come la calcola il server: la sua durata se indicata,
// altrimenti i minuti della diretta, la lunghezza del video, i secondi della campagna.
function durata(x) {
  const propria = H.S.promozione.durate?.[x.id];
  if (propria) return { secondi: propria, propria: true };
  if (x.tipo === "diretta") return { secondi: x.durata || 300 };
  if (x.tipo === "video") {
    const intero = x.durata || Q.lunghezze.get(x.id);
    if (!intero) leggiLunghezza(x);
    return { secondi: intero || 30, intero: true, stimata: !intero };
  }
  return { secondi: H.S.campagna.durata || x.durata || 10 };
}

function leggiLunghezza(x) {
  if (Q.lunghezze.has(x.id)) return;
  Q.lunghezze.set(x.id, null);
  const v = document.createElement("video");
  v.preload = "metadata";
  v.muted = true;
  v.onloadedmetadata = () => {
    if (Number.isFinite(v.duration) && v.duration > 0) {
      Q.lunghezze.set(x.id, Math.round(v.duration));
      ridisegnaPresto();
    }
    v.removeAttribute("src");
  };
  v.src = H.conCliente(`/api/contenuti/${x.id}/file/`);
}

let timerRidisegno = null;
function ridisegnaPresto() {
  clearTimeout(timerRidisegno);
  timerRidisegno = setTimeout(() => disegnaSequenza(), 120);
}

export function testoDurata(secondi) {
  if (secondi < 60) return `${secondi} s`;
  const m = Math.floor(secondi / 60);
  const s = secondi % 60;
  if (m < 60) return s ? `${m} min ${s} s` : `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ""}`.trim();
}

const orologio = (secondi) => `${Math.floor(secondi / 60)}:${String(Math.floor(secondi % 60)).padStart(2, "0")}`;

// Ogni modifica passa da qui: si può annullare (Ctrl+Z) e il pulsante «Salva» si accende.
function modifica(operazione) {
  const p = H.S.promozione;
  Q.storia.push(structuredClone({ contenuti: p.contenuti, durate: p.durate || {}, audio: p.audio || [], ripeti: p.ripeti || {} }));
  if (Q.storia.length > 50) Q.storia.shift();
  operazione(p);
  H.segnaModificata();
  H.aggiorna();
}

function annulla() {
  const precedente = Q.storia.pop();
  if (!precedente) return;
  Object.assign(H.S.promozione, precedente);
  H.segnaModificata();
  H.aggiorna();
}

// Sposta (o inserisce, se vengono dalla libreria) le voci «ids» nella corsia, prima della
// voce che ora sta in posizione «indice» tra quelle che non si spostano.
function colloca(ids, chiave, indice) {
  modifica((p) => {
    const restanti = vociCorsia(chiave).map((x) => x.id).filter((id) => !ids.includes(id));
    const prima = restanti[indice];
    const globale = p.contenuti.filter((id) => !ids.includes(id));
    let posizione = globale.length;
    if (prima) posizione = globale.indexOf(prima);
    else if (restanti.length) posizione = globale.indexOf(restanti[restanti.length - 1]) + 1;
    globale.splice(posizione, 0, ...ids);
    p.contenuti = globale;
  });
}

function togli(ids) {
  if (!ids.length) return;
  modifica((p) => {
    p.contenuti = p.contenuti.filter((id) => !ids.includes(id));
  });
  for (const id of ids) Q.selezione.delete(id);
}

function impostaDurata(ids, secondi) {
  modifica((p) => {
    p.durate ??= {};
    for (const id of ids) {
      if (secondi) p.durate[id] = Math.max(1, Math.min(86400, Math.round(secondi)));
      else delete p.durate[id];
    }
  });
}

function sceltiInOrdine(chiave) {
  return vociCorsia(chiave).map((x) => x.id).filter((id) => Q.selezione.has(id));
}

// --- Disegno ------------------------------------------------------------------------------------

// Apre la timeline della sequenza (anche se era ridotta) e la porta in vista.
export function apriSequenza() {
  Q.ridotta = false;
  disegnaSequenza();
  document.getElementById("sequenza")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

export function disegnaSequenza() {
  const dock = document.getElementById("sequenza");
  const p = H.S.promozione;
  if (!p || !H.S.campagna) {
    dock.hidden = true;
    dock.replaceChildren();
    document.body.style.setProperty("--altezza-dock", "0px");
    return;
  }
  const chiave = p.id || "nuova";
  if (Q.promozione !== chiave) {
    Q.promozione = chiave;
    Q.selezione.clear();
    Q.storia = [];
    Q.ancora = null;
  }
  const contenuti = new Set(p.contenuti);
  for (const id of [...Q.selezione]) if (!contenuti.has(id)) Q.selezione.delete(id);

  const scorrimento = dock.querySelector(".scorrimento")?.scrollLeft || 0;
  dock.hidden = false;
  dock.classList.toggle("ridotta", Q.ridotta);
  dock.replaceChildren();
  const crea = H.crea;

  const testa = crea("header", { classe: "testa-sequenza" }, dock);
  crea("button", {
    type: "button", classe: "riduci", testo: Q.ridotta ? "▴" : "▾", "aria-label": Q.ridotta ? "Apri la timeline" : "Riduci la timeline",
    onclick: () => { Q.ridotta = !Q.ridotta; disegnaSequenza(); },
  }, testa);
  const titolo = crea("div", { classe: "titolo-sequenza" }, testa);
  crea("strong", { testo: "🎬 Sequenza" }, titolo);
  crea("span", { testo: `«${p.nome || "nuova promozione"}»` }, titolo);
  const corsie = CORSIE.map((c) => ({ ...c, voci: vociCorsia(c.chiave) }));
  for (const c of corsie) {
    c.durate = c.voci.map(durata);
    c.totale = c.durate.reduce((somma, d) => somma + d.secondi, 0);
  }
  const riassunto = crea("div", { classe: "riassunto-sequenza" }, testa);
  for (const c of corsie) {
    if (c.voci.length) crea("span", { classe: "chip", testo: `${c.simbolo} ${c.titolo}: ${c.voci.length} · giro ${testoDurata(c.totale)}` }, riassunto);
  }
  crea("span", { classe: "spazio" }, testa);
  if (!Q.ridotta) {
    const lente = crea("div", { classe: "lente-sequenza", "data-aiuto": "Ingrandisci o rimpicciolisci la timeline (anche con Ctrl + rotella)." }, testa);
    crea("button", { type: "button", testo: "−", "aria-label": "Rimpicciolisci", onclick: () => zoom(-1) }, lente);
    crea("button", { type: "button", testo: "Adatta", classe: Q.scala ? "" : "attivo", onclick: () => { Q.scala = null; disegnaSequenza(); } }, lente);
    crea("button", { type: "button", testo: "+", "aria-label": "Ingrandisci", onclick: () => zoom(1) }, lente);
  }
  crea("button", {
    type: "button", classe: "leggero", testo: "↶ Annulla", disabled: !Q.storia.length,
    "data-aiuto": "Annulla l'ultima modifica alla sequenza (Ctrl+Z).", onclick: annulla,
  }, testa);
  crea("button", {
    type: "button", classe: "primario", testo: "▶ Anteprima", disabled: !p.contenuti.length,
    "data-aiuto": "Guarda la sequenza come la vedranno gli schermi, con le durate vere, prima di salvarla.",
    onclick: () => apriAnteprima(),
  }, testa);
  if (Q.ridotta) return;

  disegnaIspettore(crea("div", { classe: "ispettore" }, dock), corsie);

  // Le corsie che servono: quelle con delle voci, e quelle degli schermi della campagna.
  const raggiunti = H.destinatari(H.S.campagna);
  const visibili = corsie.filter((c) => c.voci.length || raggiunti.some((m) => m.orientamento === c.chiave) || !raggiunti.length);
  const area = crea("div", { classe: "scorrimento" }, dock);
  const larghezza = Math.max(320, (dock.clientWidth || window.innerWidth) - 190);
  const scala = Q.scala || adattata(visibili, larghezza);
  for (const c of visibili) disegnaCorsia(area, c, scala);
  area.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    zoom(e.deltaY < 0 ? 1 : -1);
  }, { passive: false });
  area.scrollLeft = scorrimento;
}

function adattata(corsie, larghezza) {
  // La scala più grande con cui la corsia più lunga entra tutta (tenendo conto dei minimi).
  for (let i = SCALE.length - 1; i >= 0; i -= 1) {
    if (corsie.every((c) => c.durate.reduce((somma, d) => somma + Math.max(LARGHEZZA_MINIMA, d.secondi * SCALE[i]) + 4, 0) <= larghezza)) return SCALE[i];
  }
  return SCALE[0];
}

function zoom(passo) {
  const dock = document.getElementById("sequenza");
  const attuale = Q.scala || parseFloat(dock.querySelector(".pista")?.dataset.scala || "4");
  const i = SCALE.findIndex((s) => s >= attuale);
  Q.scala = SCALE[Math.max(0, Math.min(SCALE.length - 1, (i < 0 ? SCALE.length - 1 : i) + passo))];
  disegnaSequenza();
}

function disegnaIspettore(box, corsie) {
  const crea = H.crea;
  const p = H.S.promozione;
  const contenuti = H.perId(H.S.contenuti);
  const scelti = [...Q.selezione].map((id) => contenuti.get(id)).filter(Boolean);
  if (!scelti.length) {
    crea("span", {
      classe: "suggerimento-sequenza",
      testo: p.contenuti.length
        ? "Clic per scegliere una voce · Ctrl o ⇧ per sceglierne più d'una · trascina per spostarle · tira il bordo destro per la durata · Canc per toglierle"
        : "Trascina qui le immagini dalla libreria (o selezionale e premi «Aggiungi»): poi mettile in ordine e scegli quanto restano in onda.",
    }, box);
    const vuote = corsie.find((c) => c.voci.some((x) => x.tipo === "diretta")) && corsie.find((c) => c.chiave === "orizzontale")?.voci.every((x) => x.tipo === "diretta");
    if (vuote) crea("span", { classe: "manca", testo: "⚠ Per i monitor c'è solo la diretta: resta in onda di continuo." }, box);
    return;
  }
  const uno = scelti.length === 1 ? scelti[0] : null;
  const etichetta = crea("strong", { testo: uno ? uno.nome : `${scelti.length} voci selezionate` }, box);
  etichetta.title = etichetta.textContent;
  if (uno) crea("span", { classe: "tenue", testo: { immagine: "immagine", video: "video", diretta: "diretta", web: "pagina web" }[uno.tipo] || "" }, box);

  // Durata: in secondi per immagini e video, in minuti per le dirette.
  const tutteDirette = scelti.every((x) => x.tipo === "diretta");
  const valori = new Set(scelti.map((x) => durata(x).secondi));
  const comune = valori.size === 1 ? [...valori][0] : null;
  const campo = crea("label", { classe: "durata-scelta", "data-aiuto": tutteDirette ? "Minuti di diretta a ogni giro." : "Secondi in onda a ogni giro. Per un video: taglialo prima della fine." }, box);
  campo.append("Durata ");
  const input = crea("input", {
    type: "number", min: 1, max: tutteDirette ? 1440 : 86400, step: 1,
    value: comune ? (tutteDirette ? Math.max(1, Math.round(comune / 60)) : comune) : "", placeholder: "misto",
  }, campo);
  campo.append(tutteDirette ? " min" : " s");
  let applicata = false; // Invio e poi l'uscita dal campo: una modifica sola
  const applica = () => {
    const valore = parseInt(input.value, 10);
    if (applicata || !valore || valore < 1) return;
    applicata = true;
    impostaDurata(scelti.map((x) => x.id), tutteDirette ? valore * 60 : valore);
  };
  input.addEventListener("change", applica);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); applica(); } });

  const proprie = scelti.filter((x) => p.durate?.[x.id]);
  if (proprie.length) {
    crea("button", {
      type: "button", classe: "leggero", testo: scelti.some((x) => x.tipo === "video") ? "↺ Video intero / durata standard" : "↺ Durata standard",
      "data-aiuto": `Torna alla durata standard: ${H.S.campagna.durata || 10} s per le immagini (dalla campagna), i video fino alla fine.`,
      onclick: () => impostaDurata(proprie.map((x) => x.id), null),
    }, box);
  }
  const dirette = scelti.filter((x) => x.tipo === "diretta");
  if (dirette.length) {
    const accese = dirette.every((x) => (p.audio || []).includes(x.id));
    crea("button", {
      type: "button", classe: `leggero${accese ? " attivo" : ""}`, testo: accese ? "🔊 Audio acceso" : "🔇 Audio spento",
      "data-aiuto": "Solo l'audio della diretta: gli altri suoni del monitor (es. il din-don dei numeri) restano come sono.",
      onclick: () => modifica((q) => {
        const ids = dirette.map((x) => x.id);
        q.audio = accese ? (q.audio || []).filter((id) => !ids.includes(id)) : [...new Set([...(q.audio || []), ...ids])];
      }),
    }, box);
  }
  // Quando ripetere la diretta: al suo posto, ogni N immagini, ogni N minuti o a certe ore.
  if (dirette.length === 1 && scelti.length === 1) {
    const d = dirette[0];
    const regola = p.ripeti?.[d.id] || { modo: "sequenza" };
    const ripeti = crea("label", { classe: "durata-scelta", "data-aiuto": "Quando va in onda la diretta. «Ogni N immagini» e «ogni N minuti» la ripetono nella sequenza; «alle ore» interrompe le slide a quell'ora per la durata della diretta, poi le slide riprendono." }, box);
    ripeti.append("Ripeti ");
    const modo = crea("select", {}, ripeti);
    for (const [v, t] of [["sequenza", "una volta, al suo posto"], ["ogni_slide", "ogni N immagini"], ["ogni_minuti", "ogni N minuti"], ["orari", "alle ore…"]]) {
      crea("option", { value: v, testo: t, selected: regola.modo === v }, modo);
    }
    const valore = crea("input", { type: regola.modo === "orari" ? "text" : "number", min: 1, max: regola.modo === "ogni_minuti" ? 240 : 200 }, ripeti);
    const aggiornaCampo = () => {
      const m = modo.value;
      valore.hidden = m === "sequenza";
      valore.type = m === "orari" ? "text" : "number";
      valore.placeholder = m === "orari" ? "es. 12:00, 18:30" : m === "ogni_minuti" ? "minuti" : "immagini";
      valore.size = m === "orari" ? 16 : 4;
      valore.value = m === regola.modo ? (m === "orari" ? (regola.orari || []).join(", ") : regola.ogni || "") : (m === "orari" ? "" : m === "ogni_minuti" ? 15 : 10);
    };
    aggiornaCampo();
    let salvata = false; // Invio e poi l'uscita dal campo: una modifica sola
    const salvaRegola = () => {
      if (salvata) return;
      const m = modo.value;
      let nuova = null;
      if (m === "ogni_slide" || m === "ogni_minuti") {
        const n = parseInt(valore.value, 10);
        if (!n || n < 1) return;
        nuova = { modo: m, ogni: n };
      } else if (m === "orari") {
        const orari = valore.value.split(/[,;\s]+/).map((o) => o.trim()).filter(Boolean).map((o) => (/^\d{1,2}$/.test(o) ? `${o}:00` : o)).map((o) => o.replace(/^(\d):/, "0$1:"));
        if (!orari.length) return;
        if (!orari.every((o) => /^([01]\d|2[0-3]):[0-5]\d$/.test(o))) {
          H.avvisa("Orari della diretta non validi: scrivili come 12:00, 18:30.");
          return;
        }
        nuova = { modo: "orari", orari: [...new Set(orari)].sort() };
      }
      salvata = true;
      modifica((q) => {
        q.ripeti = { ...(q.ripeti || {}) };
        if (nuova) q.ripeti[d.id] = nuova;
        else delete q.ripeti[d.id];
      });
    };
    modo.addEventListener("change", () => { aggiornaCampo(); if (modo.value === "sequenza" || valore.value) salvaRegola(); });
    valore.addEventListener("change", salvaRegola);
    valore.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); salvaRegola(); } });
  }
  crea("span", { classe: "spazio" }, box);
  const corsia = corsie.find((c) => c.voci.some((x) => Q.selezione.has(x.id)));
  if (corsia) {
    crea("button", { type: "button", classe: "leggero", testo: "◀", "aria-label": "Sposta prima", "data-aiuto": "Sposta prima (←)", onclick: () => passo(corsia.chiave, -1) }, box);
    crea("button", { type: "button", classe: "leggero", testo: "▶", "aria-label": "Sposta dopo", "data-aiuto": "Sposta dopo (→)", onclick: () => passo(corsia.chiave, 1) }, box);
    crea("button", {
      type: "button", classe: "leggero", testo: "▷ Anteprima da qui",
      onclick: () => apriAnteprima(corsia.chiave, corsia.voci.findIndex((x) => Q.selezione.has(x.id))),
    }, box);
  }
  crea("button", { type: "button", classe: "pericolo", testo: "Togli", "data-aiuto": "Toglie dalla promozione (Canc): le immagini restano nella libreria.", onclick: () => togli([...Q.selezione]) }, box);
}

function disegnaCorsia(area, corsia, scala) {
  const crea = H.crea;
  const riga = crea("div", { classe: `corsia ${corsia.chiave}` }, area);
  const testa = crea("div", { classe: "testa-corsia", "data-aiuto": corsia.aiuto }, riga);
  crea("span", { classe: "simbolo", testo: corsia.simbolo }, testa);
  const testi = crea("div", {}, testa);
  crea("strong", { testo: corsia.titolo }, testi);
  crea("small", { testo: corsia.voci.length ? `${corsia.voci.length} voci · ${testoDurata(corsia.totale)}` : "vuota" }, testi);

  const pista = crea("div", { classe: "pista" }, riga);
  pista.dataset.scala = String(scala);
  const righello = crea("div", { classe: "righello" }, pista);
  const blocchi = crea("div", { classe: "blocchi" }, pista);
  const linea = crea("div", { classe: "punto-inserimento", hidden: true }, pista);

  let x = 0;
  let inizio = 0;
  const posizioni = [];
  corsia.voci.forEach((voce, i) => {
    const d = corsia.durate[i];
    const larghezza = Math.max(LARGHEZZA_MINIMA, d.secondi * scala);
    posizioni.push({ x, larghezza, inizio, secondi: d.secondi });
    blocchi.appendChild(blocco(voce, d, i, larghezza, corsia, scala));
    x += larghezza + 4;
    inizio += d.secondi;
  });
  if (!corsia.voci.length) crea("div", { classe: "pista-vuota", testo: `Trascina qui le immagini ${corsia.chiave === "verticale" ? "verticali (totem)" : "orizzontali e le dirette (monitor)"}` }, blocchi);
  const fine = Math.max(x, 200);
  pista.style.width = `${fine + 60}px`;

  // Il righello segue i blocchi: un segno ogni tot secondi, dove cade davvero.
  const totale = inizio;
  const passo = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800].find((s) => s * scala >= 70) || 3600;
  const xDi = (t) => {
    const p = posizioni.find((q) => t >= q.inizio && t < q.inizio + q.secondi) || posizioni[posizioni.length - 1];
    return p ? p.x + ((t - p.inizio) / p.secondi) * p.larghezza : 0;
  };
  for (let t = 0; t <= totale; t += passo) {
    const segno = crea("span", { classe: "segno", testo: orologio(t) }, righello);
    segno.style.left = `${t === totale && posizioni.length ? x - 4 : xDi(t)}px`;
  }
  if (totale && totale % passo) {
    const segno = crea("span", { classe: "segno fine", testo: orologio(totale) }, righello);
    segno.style.left = `${x - 4}px`;
  }
  const giro = crea("span", { classe: "da-capo", testo: "↻ da capo" }, blocchi);
  giro.hidden = !corsia.voci.length;

  // Trascinamento: da questa corsia (spostare) o dalla libreria (aggiungere).
  const indiceDa = (clientX) => {
    const sinistra = blocchi.getBoundingClientRect().left;
    const fermi = posizioni.filter((_, i) => !trascinate.has(corsia.voci[i].id));
    const xRel = clientX - sinistra;
    let indice = 0;
    for (const q of fermi) if (xRel > q.x + q.larghezza / 2) indice += 1;
    const dopo = fermi[indice];
    const prima = fermi[indice - 1];
    linea.style.left = `${dopo ? dopo.x - 3 : prima ? prima.x + prima.larghezza + 1 : 0}px`;
    return indice;
  };
  pista.addEventListener("dragover", (e) => {
    const tipi = e.dataTransfer.types;
    if (!tipi.includes(FORMATO_TRASCINAMENTO) && !tipi.includes(FORMATO_LIBRERIA)) return;
    if (tipi.includes(FORMATO_TRASCINAMENTO) && trascinamento.corsia !== corsia.chiave) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = tipi.includes(FORMATO_LIBRERIA) ? "copy" : "move";
    linea.hidden = false;
    pista.classList.add("sopra");
    indiceDa(e.clientX);
  });
  pista.addEventListener("dragleave", (e) => {
    if (pista.contains(e.relatedTarget)) return;
    linea.hidden = true;
    pista.classList.remove("sopra");
  });
  pista.addEventListener("drop", (e) => {
    e.preventDefault();
    linea.hidden = true;
    pista.classList.remove("sopra");
    const indice = indiceDa(e.clientX);
    const daLibreria = e.dataTransfer.getData(FORMATO_LIBRERIA);
    if (daLibreria) {
      const contenuti = H.perId(H.S.contenuti);
      let ids = JSON.parse(daLibreria).filter((id) => contenuti.has(id));
      const fuori = ids.filter((id) => ![corsia.chiave, null].includes(formatoDi(contenuti.get(id))));
      ids = ids.filter((id) => !fuori.includes(id));
      if (fuori.length) H.avvisa(`${fuori.length === 1 ? "Una voce è" : `${fuori.length} voci sono`} di un altro formato: ${corsia.chiave === "verticale" ? "i totem mostrano le immagini verticali" : "i monitor mostrano le immagini orizzontali e le dirette"}.`);
      if (!ids.length || !H.confermaDirette(ids.filter((id) => !H.S.promozione.contenuti.includes(id)))) return;
      colloca(ids, corsia.chiave, indice);
      Q.selezione = new Set(ids);
      return;
    }
    const ids = e.dataTransfer.getData(FORMATO_TRASCINAMENTO);
    if (ids) colloca(JSON.parse(ids), corsia.chiave, indice);
  });
}

// Ciò che si sta trascinando dentro la timeline (dragover non può leggere i dati).
let trascinate = new Set();
const trascinamento = { corsia: null };

function blocco(x, d, indice, larghezza, corsia, scala) {
  const crea = H.crea;
  const el = crea("div", {
    classe: `blocco ${x.tipo}${Q.selezione.has(x.id) ? " scelto" : ""}${d.propria ? " propria" : ""}`,
    draggable: true, tabIndex: 0,
  });
  el.style.width = `${larghezza}px`;
  el.dataset.id = x.id;
  el.title = `${x.nome} · ${testoDurata(d.secondi)}${d.intero ? (d.stimata ? " (video: lunghezza in lettura)" : " (video intero)") : d.propria ? "" : " (durata standard)"}`;
  if (x.tipo === "immagine") {
    // Come una pellicola: la miniatura si ripete per tutta la lunghezza del blocco.
    el.style.backgroundImage = `url("${H.conCliente(`/api/contenuti/${x.id}/miniatura/`)}")`;
  } else if (x.tipo === "video") {
    el.appendChild(H.anteprima(x, "fotogramma"));
  } else if (x.tipo === "diretta") {
    const segno = crea("div", { classe: "segno-diretta" }, el);
    if (x.logo_url) {
      const logo = crea("img", { src: x.logo_url, alt: "", referrerPolicy: "no-referrer", draggable: false }, segno);
      logo.addEventListener("error", () => logo.remove());
    }
    crea("span", { classe: "live", testo: "LIVE" }, segno);
  } else {
    crea("span", { classe: "segno-diretta", testo: "🌐" }, el);
  }
  crea("span", { classe: "numero", testo: String(indice + 1) }, el);
  const piede = crea("div", { classe: "piede-blocco" }, el);
  crea("span", { classe: "nome", testo: x.nome }, piede);
  const badge = crea("span", { classe: "durata", testo: `${x.tipo === "video" ? "▶ " : x.tipo === "diretta" ? "📡 " : ""}${testoDurata(d.secondi)}${d.stimata ? "?" : ""}` }, piede);
  if (x.tipo === "diretta" && (H.S.promozione.audio || []).includes(x.id)) crea("span", { classe: "audio", testo: "🔊" }, el);
  // La regola di ripetizione della diretta, ben visibile sul blocco.
  const regola = x.tipo === "diretta" ? H.S.promozione.ripeti?.[x.id] : null;
  if (regola) {
    crea("span", {
      classe: "ripeti",
      testo: regola.modo === "orari" ? `🕒 ${regola.orari.join(" · ")}` : `🔁 ogni ${regola.ogni} ${regola.modo === "ogni_minuti" ? "min" : "imm."}`,
    }, el);
  }

  // Selezione: clic, Ctrl/⌘ + clic (aggiungi o togli), ⇧ + clic (da… a…).
  el.addEventListener("click", (e) => {
    const ordine = corsia.voci.map((v) => v.id);
    if (e.shiftKey && Q.ancora && ordine.includes(Q.ancora)) {
      const [a, b] = [ordine.indexOf(Q.ancora), indice].sort((m, n) => m - n);
      if (!e.ctrlKey && !e.metaKey) Q.selezione.clear();
      for (const id of ordine.slice(a, b + 1)) Q.selezione.add(id);
    } else if (e.ctrlKey || e.metaKey) {
      Q.selezione.has(x.id) ? Q.selezione.delete(x.id) : Q.selezione.add(x.id);
      Q.ancora = x.id;
    } else {
      Q.selezione = new Set([x.id]);
      Q.ancora = x.id;
    }
    disegnaSequenza();
    document.querySelector(`#sequenza .blocco[data-id="${x.id}"]`)?.focus({ preventScroll: true });
  });
  el.addEventListener("dblclick", () => H.apriVisore(x));

  el.addEventListener("dragstart", (e) => {
    if (!Q.selezione.has(x.id)) {
      Q.selezione = new Set([x.id]);
      Q.ancora = x.id;
    }
    const ids = sceltiInOrdine(corsia.chiave);
    trascinate = new Set(ids);
    trascinamento.corsia = corsia.chiave;
    e.dataTransfer.setData(FORMATO_TRASCINAMENTO, JSON.stringify(ids));
    e.dataTransfer.effectAllowed = "move";
    if (ids.length > 1) {
      const pacco = crea("div", { classe: "pacco-trascinato", testo: `${ids.length} voci` }, document.body);
      e.dataTransfer.setDragImage(pacco, 20, 20);
      setTimeout(() => pacco.remove());
    }
    requestAnimationFrame(() => {
      for (const b of document.querySelectorAll("#sequenza .blocco")) if (trascinate.has(b.dataset.id)) b.classList.add("trascinato");
    });
  });
  el.addEventListener("dragend", () => {
    trascinate = new Set();
    trascinamento.corsia = null;
    for (const b of document.querySelectorAll("#sequenza .blocco.trascinato")) b.classList.remove("trascinato");
  });

  // Il bordo destro cambia la durata: le dirette a passi di 30 s, il resto di 1 s.
  const maniglia = crea("span", { classe: "maniglia", title: "Tira per cambiare la durata" }, el);
  maniglia.draggable = false;
  maniglia.addEventListener("dragstart", (e) => e.preventDefault());
  maniglia.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    el.draggable = false;
    maniglia.setPointerCapture(e.pointerId);
    const partenza = e.clientX;
    const passo = x.tipo === "diretta" ? 30 : 1;
    let secondi = d.secondi;
    el.classList.add("in-durata");
    const muovi = (m) => {
      const grezzi = d.secondi + (m.clientX - partenza) / scala;
      secondi = Math.max(passo, Math.round(grezzi / passo) * passo);
      el.style.width = `${Math.max(LARGHEZZA_MINIMA, secondi * scala)}px`;
      badge.textContent = testoDurata(secondi);
    };
    const lascia = () => {
      maniglia.removeEventListener("pointermove", muovi);
      maniglia.removeEventListener("pointerup", lascia);
      maniglia.removeEventListener("pointercancel", lascia);
      el.draggable = true;
      el.classList.remove("in-durata");
      if (secondi !== d.secondi) impostaDurata([x.id], secondi);
    };
    maniglia.addEventListener("pointermove", muovi);
    maniglia.addEventListener("pointerup", lascia);
    maniglia.addEventListener("pointercancel", lascia);
  });
  maniglia.addEventListener("click", (e) => e.stopPropagation());
  return el;
}

function passo(chiave, verso) {
  const ids = sceltiInOrdine(chiave);
  if (!ids.length) return;
  const ordine = vociCorsia(chiave).map((x) => x.id);
  const primo = ordine.indexOf(ids[0]);
  const ultimo = ordine.indexOf(ids[ids.length - 1]);
  if ((verso < 0 && primo === 0) || (verso > 0 && ultimo === ordine.length - 1)) return;
  // Posizione tra le voci che restano ferme.
  const restanti = ordine.filter((id) => !ids.includes(id));
  const prima = verso < 0 ? restanti.indexOf(ordine[primo - 1]) : restanti.indexOf(ordine[ultimo + 1]) + 1;
  colloca(ids, chiave, prima);
}

function tastiera(e) {
  const dock = document.getElementById("sequenza");
  if (!H?.S.promozione || dock.hidden) return;
  if (document.querySelector("dialog[open]")) return;
  const bersaglio = e.target;
  if (bersaglio instanceof HTMLElement && (bersaglio.closest("input, textarea, select, [contenteditable]"))) return;
  const nelDock = dock.contains(bersaglio);
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && (nelDock || bersaglio === document.body)) {
    e.preventDefault();
    annulla();
    return;
  }
  if (!nelDock) return;
  const corsia = CORSIE.find((c) => vociCorsia(c.chiave).some((x) => Q.selezione.has(x.id)))?.chiave;
  if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    togli([...Q.selezione]);
  } else if (e.key === "Escape") {
    Q.selezione.clear();
    disegnaSequenza();
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
    e.preventDefault();
    const chiave = bersaglio.closest?.(".corsia")?.classList.contains("verticale") ? "verticale" : corsia || "orizzontale";
    Q.selezione = new Set(vociCorsia(chiave).map((x) => x.id));
    disegnaSequenza();
  } else if (corsia && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
    e.preventDefault();
    passo(corsia, e.key === "ArrowLeft" ? -1 : 1);
    const primo = sceltiInOrdine(corsia)[0];
    requestAnimationFrame(() => document.querySelector(`#sequenza .blocco[data-id="${primo}"]`)?.focus({ preventScroll: false }));
  }
}

// --- Anteprima ----------------------------------------------------------------------------------
//
// Riproduce la sequenza di una corsia come farà lo schermo: stesse durate, stesso ordine,
// poi da capo. Si può accelerare (2×, 4×) e saltare a una voce cliccando la barra.

const R = { corsia: "orizzontale", indice: 0, velocita: 1, pausa: false, timer: null, avvio: 0, trascorso: 0, diretta: null, giro: 0 };

export function apriAnteprima(corsia, indice = 0) {
  const finestra = document.getElementById("anteprima-sequenza");
  const disponibili = CORSIE.filter((c) => vociCorsia(c.chiave).length);
  if (!disponibili.length) return;
  R.corsia = disponibili.some((c) => c.chiave === corsia) ? corsia : disponibili[0].chiave;
  R.indice = Math.max(0, indice);
  R.pausa = false;
  disegnaAnteprima();
  if (!finestra.open) finestra.showModal();
  finestra.addEventListener("close", fermaAnteprima, { once: true });
  vaiA(R.indice);
}

function fermaAnteprima() {
  clearTimeout(R.timer);
  cancelAnimationFrame(R.animazione);
  R.diretta?.chiudi();
  R.diretta = null;
  const palco = document.querySelector("#anteprima-sequenza .palco-anteprima");
  for (const v of palco?.querySelectorAll("video") || []) v.pause();
}

function disegnaAnteprima() {
  const crea = H.crea;
  const finestra = document.getElementById("anteprima-sequenza");
  finestra.replaceChildren();
  const p = H.S.promozione;
  const chiudi = crea("form", { method: "dialog", classe: "chiudi" }, finestra);
  crea("button", { "aria-label": "Chiudi", testo: "✕" }, chiudi);
  const testa = crea("div", { classe: "testa-anteprima" }, finestra);
  crea("h2", { testo: `Anteprima · «${p.nome || "nuova promozione"}»` }, testa);
  const schede = crea("div", { classe: "schede-anteprima" }, testa);
  for (const c of CORSIE) {
    if (!vociCorsia(c.chiave).length) continue;
    crea("button", {
      type: "button", classe: `chip${R.corsia === c.chiave ? " attivo" : ""}`, testo: `${c.simbolo} ${c.titolo}`,
      onclick: () => { fermaAnteprima(); R.corsia = c.chiave; R.indice = 0; disegnaAnteprima(); vaiA(0); },
    }, schede);
  }
  const cornice = crea("div", { classe: `cornice-anteprima ${R.corsia}` }, finestra);
  crea("div", { classe: "palco-anteprima" }, cornice);
  crea("div", { classe: "nome-anteprima" }, cornice);
  if (R.corsia === "orizzontale") crea("span", { classe: "piedistallo-anteprima" }, finestra);

  const comandi = crea("div", { classe: "comandi-anteprima" }, finestra);
  crea("button", { type: "button", testo: "⏮", "aria-label": "Precedente", onclick: () => vaiA(R.indice - 1) }, comandi);
  crea("button", { type: "button", classe: "pausa", testo: "⏸", "aria-label": "Pausa", onclick: () => pausa(!R.pausa) }, comandi);
  crea("button", { type: "button", testo: "⏭", "aria-label": "Successiva", onclick: () => vaiA(R.indice + 1) }, comandi);
  crea("span", { classe: "tempo-anteprima", testo: "0:00" }, comandi);
  const velocita = crea("div", { classe: "velocita", "data-aiuto": "Accelera l'anteprima per vedere in fretta un giro lungo. Le dirette e i video restano alla loro velocità." }, comandi);
  for (const v of [1, 2, 4, 10]) {
    crea("button", {
      type: "button", classe: `chip${R.velocita === v ? " attivo" : ""}`, testo: `${v}×`,
      onclick: () => {
        R.velocita = v;
        for (const b of velocita.children) b.classList.toggle("attivo", b.textContent === `${v}×`);
        vaiA(R.indice, true);
      },
    }, velocita);
  }

  // La barra: un segmento per voce, lungo quanto la sua durata. Clic: si salta lì.
  const voci = vociCorsia(R.corsia);
  const durate = voci.map((x) => durata(x).secondi);
  const totale = durate.reduce((a, b) => a + b, 0) || 1;
  const barra = crea("div", { classe: "barra-anteprima" }, finestra);
  voci.forEach((x, i) => {
    const segmento = crea("button", { type: "button", classe: `segmento ${x.tipo}`, title: `${i + 1}. ${x.nome} · ${testoDurata(durate[i])}`, onclick: () => vaiA(i) }, barra);
    segmento.style.flexGrow = String(durate[i] / totale);
    crea("span", { classe: "riempimento" }, segmento);
  });

  const piede = crea("div", { classe: "piede-anteprima" }, finestra);
  crea("span", { classe: "nota", testo: `Un giro: ${testoDurata(totale)} · poi ricomincia da capo. Le immagini qui sono adattate allo schermo; sul monitor vale l'adattamento scelto nel layout.` }, piede);
  crea("span", { classe: "spazio" }, piede);
  if (H.S.modificata) {
    crea("button", {
      type: "button", classe: "primario", testo: p.id ? "✓ Conferma e salva" : "✓ Conferma e crea",
      onclick: async () => { finestra.close(); await H.salva(); },
    }, piede);
  }
}

function pausa(ferma) {
  R.pausa = ferma;
  const pulsante = document.querySelector("#anteprima-sequenza .pausa");
  if (pulsante) pulsante.textContent = ferma ? "▶" : "⏸";
  const video = document.querySelector("#anteprima-sequenza .palco-anteprima .strato:last-child video");
  if (ferma) {
    clearTimeout(R.timer);
    R.trascorso += (performance.now() - R.avvio) * R.velocita;
    video?.pause();
  } else {
    R.avvio = performance.now();
    video?.play().catch(() => {});
    programma();
  }
}

async function vaiA(indice, stessa = false) {
  const voci = vociCorsia(R.corsia);
  if (!voci.length) return;
  clearTimeout(R.timer);
  R.indice = ((indice % voci.length) + voci.length) % voci.length;
  const x = voci[R.indice];
  const d = durata(x);
  R.secondi = d.secondi;
  R.trascorso = stessa ? R.trascorso : 0;
  R.avvio = performance.now();
  const giro = ++R.giro;
  const palco = document.querySelector("#anteprima-sequenza .palco-anteprima");
  if (!palco) return;
  const nome = document.querySelector("#anteprima-sequenza .nome-anteprima");
  nome.textContent = `${R.indice + 1}/${voci.length} · ${x.nome} · ${testoDurata(d.secondi)}`;
  for (const [i, s] of [...document.querySelectorAll("#anteprima-sequenza .segmento")].entries()) {
    s.classList.toggle("passato", i < R.indice);
    s.classList.toggle("corrente", i === R.indice);
  }
  if (!stessa) await mostra(palco, x, d, giro);
  if (giro !== R.giro) return;
  if (!R.pausa) programma();
  aggiornaTempo();
}

function programma() {
  clearTimeout(R.timer);
  // Video e dirette scorrono alla loro velocità: l'accelerazione vale solo per le immagini.
  const voce = vociCorsia(R.corsia)[R.indice];
  const velocita = voce && voce.tipo === "immagine" ? R.velocita : 1;
  const resto = Math.max(0, R.secondi * 1000 - R.trascorso) / velocita;
  R.velocitaCorrente = velocita;
  R.timer = setTimeout(() => vaiA(R.indice + 1), resto);
}

function aggiornaTempo() {
  cancelAnimationFrame(R.animazione);
  const passo = () => {
    const finestra = document.getElementById("anteprima-sequenza");
    if (!finestra.open) return;
    const trascorso = Math.min(R.secondi * 1000, R.trascorso + (R.pausa ? 0 : (performance.now() - R.avvio) * (R.velocitaCorrente || 1)));
    const tempo = finestra.querySelector(".tempo-anteprima");
    if (tempo) tempo.textContent = `${orologio(trascorso / 1000)} / ${orologio(R.secondi)}`;
    const corrente = finestra.querySelector(".segmento.corrente .riempimento");
    if (corrente) corrente.style.width = `${(trascorso / (R.secondi * 1000)) * 100}%`;
    R.animazione = requestAnimationFrame(passo);
  };
  passo();
}

async function mostra(palco, x, d, giro) {
  const crea = H.crea;
  R.diretta?.chiudi();
  R.diretta = null;
  const strato = crea("div", { classe: "strato" });
  if (x.tipo === "immagine") {
    const img = crea("img", { src: H.conCliente(`/api/contenuti/${x.id}/file/`), alt: x.nome }, strato);
    await new Promise((ok) => { img.onload = ok; img.onerror = ok; setTimeout(ok, 4000); });
  } else if (x.tipo === "video") {
    const v = crea("video", { src: H.conCliente(`/api/contenuti/${x.id}/file/`), muted: true, playsInline: true, autoplay: true }, strato);
    v.addEventListener("ended", () => { if (giro === R.giro) vaiA(R.indice + 1); }, { once: true });
  } else if (x.tipo === "diretta") {
    const v = crea("video", { muted: true, playsInline: true, autoplay: true }, strato);
    const cartello = crea("div", { classe: "cartello-diretta" }, strato);
    crea("strong", { testo: `📡 ${x.nome}` }, cartello);
    const stato = crea("span", { testo: "collegamento alla diretta…" }, cartello);
    entra(palco, strato);
    const diretta = await avviaDiretta(v, x.url);
    if (giro !== R.giro) { diretta.chiudi(); return; }
    R.diretta = diretta;
    const esito = await diretta.pronta;
    if (giro !== R.giro) return;
    if (esito.ok) {
      cartello.classList.add("in-onda");
      stato.textContent = `in diretta per ${testoDurata(d.secondi)}`;
      v.play().catch(() => {});
    } else {
      stato.textContent = `Qui non parte (${esito.motivo}). Sullo schermo resta in onda per ${testoDurata(d.secondi)}, se lo schermo la riceve.`;
    }
    return;
  } else {
    const cartello = crea("div", { classe: "cartello-diretta" }, strato);
    crea("strong", { testo: `🌐 ${x.nome}` }, cartello);
  }
  if (giro !== R.giro) return;
  entra(palco, strato);
}

function entra(palco, strato) {
  const vecchi = [...palco.children];
  palco.appendChild(strato);
  requestAnimationFrame(() => strato.classList.add("visibile"));
  setTimeout(() => {
    for (const v of vecchi) {
      v.querySelector("video")?.pause();
      v.remove();
    }
  }, 450);
}
