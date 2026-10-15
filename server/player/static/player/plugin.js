// I plugin Info Prezzo e Info Ingredienti (facoltativi). Un lettore di codici a barre USB
// scrive come una tastiera: cifre velocissime e di solito Invio. Il codice va al servizio
// code del Totem Master, che cerca nel file del negozio; la risposta compare in un riquadro
// sopra lo schermo per qualche secondo. Una nuova lettura sostituisce il riquadro aperto.
// I testi che arrivano dai dati passano sempre da textContent.

const PAUSA_TRA_TASTI = 80; // ms: più lento di così è una persona, non un lettore
const MINIMO_CIFRE = 6;

function crea(tag, classe, genitore) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (genitore) genitore.appendChild(el);
  return el;
}

function numero(valore) {
  if (valore === null || valore === undefined || valore === "") return null;
  const n = typeof valore === "number" ? valore : parseFloat(String(valore).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

const euro = (n) => new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(n);

// Date nel formato del file: 2026-12-31, 31/12/2026 o 20261231. Altrimenti null (non si controlla).
function data(valore) {
  const testo = String(valore ?? "").trim();
  let m = testo.match(/^(\d{4})-?(\d{2})-?(\d{2})/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
  m = testo.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1]);
  return null;
}

const giorno = (d) => d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" });

// Prezzo pieno, prezzo in offerta (se valida oggi) e fine offerta.
export function leggiPrezzo(articolo, oggi = new Date()) {
  if (!articolo) return null;
  const pieno = numero(articolo.prezzo);
  const promo = numero(articolo.prezzo_offerta);
  const dal = data(articolo.offerta_dal);
  const al = data(articolo.offerta_al);
  const inizio = new Date(oggi.getFullYear(), oggi.getMonth(), oggi.getDate());
  const valida = promo !== null && promo > 0 && (pieno === null || promo < pieno)
    && (!dal || dal <= inizio) && (!al || al >= inizio);
  return { pieno, offerta: valida ? promo : null, fino: valida && al ? al : null, unita: articolo.unita ? String(articolo.unita) : "" };
}

// I testi delle bilance arrivano in righe di larghezza fissa (es. 50 caratteri), spezzate anche a
// metà parola: si ricompongono. Riga piena e lettere ai due lati: parola spezzata, si unisce;
// altrimenti era un a capo fra due parole. Una parola in MAIUSCOLO spezzata (es. «LAT|TE») si
// unisce comunque. Il prefisso «INGREDIENTI:» si toglie: c'è già il titolo.
const PAROLE_CORTE = new Set(["a", "e", "i", "o", "è", "di", "da", "in", "su", "al", "il", "la", "lo", "le", "ed", "ad", "se", "un", "si", "ai", "ne", "kg", "gr", "g", "ml", "cl", "dl", "l", "mg", "pz", "uv", "vs", "n", "nr"]);

export function testoEtichetta(testo) {
  const righe = String(testo ?? "").split(/\r?\n/);
  const larga = Math.max(...righe.map((r) => r.length));
  let uscita = righe[0] || "";
  righe.slice(1).forEach((riga, i) => {
    const prima = righe[i];
    const fine = prima.match(/([\p{L}\d]+)$/u)?.[1] || "";
    const inizio = riga.match(/^([\p{L}\d]+)/u)?.[1] || "";
    const maiuscola = (x) => x === x.toUpperCase() && /\p{L}/u.test(x);
    // Un pezzetto che non è una parola (es. «c|aglio», «aromatizza|to») è una parola spezzata.
    const pezzetto = (x, dopo) => x.length <= 2 && !PAROLE_CORTE.has(x.toLowerCase()) && !/^[/.'’]/.test(dopo);
    const minuscola = (x) => x === x.toLowerCase() && /\p{L}/u.test(x);
    // Da minuscolo a MAIUSCOLO cambia la parola (es. «microbico|NATURALMENTE»).
    const cambioScrittura = minuscola(fine) && maiuscola(inizio) && (inizio.length > 1 || riga[1] === ".");
    const spezzata = fine && inizio && !cambioScrittura && !/^\p{L}{1,2}\//u.test(riga) && (
      (prima.length >= larga && prima.length >= 40)
      || (maiuscola(fine) && maiuscola(inizio) && fine.length >= 2 && inizio.length >= 2)
      || pezzetto(fine, "") || pezzetto(inizio, riga.slice(inizio.length))
    );
    uscita += spezzata || /[\s-]$/.test(uscita) || /^[\s,.;:)-]/.test(riga) ? riga : ` ${riga}`;
  });
  return uscita.replace(/^\s*ingr[\p{L}]*\.?\s*:\s*/iu, "").replace(/ {2,}/g, " ").trim();
}

// «… FATTORI ALLERGENI: GLUTINE, LATTE» → ingredienti e allergeni separati.
export function separaAllergeni(testo) {
  const m = testo.match(/^(.*?)[\s.;-]*(?:fattori\s+)?allergeni\s*:\s*(.+)$/is);
  return m ? [m[1].trim(), m[2].trim()] : [testo, ""];
}

// Le parole in MAIUSCOLO (in un testo scritto in minuscolo) sono gli allergeni: si evidenziano.
function conEvidenza(genitore, testo, colore) {
  const lettere = testo.replace(/[^\p{L}]/gu, "");
  const maiuscole = lettere.replace(/[^\p{Lu}]/gu, "").length;
  if (!lettere || maiuscole / lettere.length > 0.5) {
    genitore.textContent = testo;
    return;
  }
  for (const pezzo of testo.split(/(\b[\p{Lu}]{3,}(?:\s+[\p{Lu}]{2,})*\b)/u)) {
    if (!pezzo) continue;
    if (/^[\p{Lu}\s]{3,}$/u.test(pezzo)) {
      const forte = crea("strong", "plugin-evidenza", genitore);
      forte.textContent = pezzo;
      forte.style.color = colore;
    } else genitore.append(pezzo);
  }
}

// Codice bilancia? Prefisso dichiarato (es. 20 = Salumeria) e il PLU nella sua posizione.
export function codiceBilancia(codice, config) {
  if (!config || codice.length !== 13) return null;
  const prefisso = (config.prefissi || []).find((p) => codice.startsWith(p.prefisso));
  if (!prefisso) return null;
  const plu = codice.substr((config.plu_inizio || 3) - 1, config.plu_lunghezza || 5);
  return { plu, reparto: prefisso.codice || prefisso.prefisso, nomeReparto: prefisso.reparto || "" };
}

// Il riquadro, disegnato in «contenitore» (il palco dello schermo, o l'anteprima del pannello).
export function disegnaRiquadro(contenitore, { tipo, esito, aspetto, dimensioni, reparto, mostraPrezzo }) {
  const a = aspetto || {};
  const base = Math.min(dimensioni.larghezza, dimensioni.altezza) * 0.045 * ((a.dimensione || 100) / 100);
  const box = crea("div", `plugin-riquadro posizione-${a.posizione || "centro"}`, contenitore);
  Object.assign(box.style, {
    width: `${a.larghezza || 70}%`, background: a.sfondo || "#fff", color: a.testo || "#1d2330",
    fontFamily: a.carattere || "sans-serif", fontSize: `${base}px`,
  });
  if (esito.errore || !esito.trovato) {
    box.classList.add("vuoto");
    crea("div", "plugin-titolo", box).textContent = esito.errore ? "Servizio non disponibile" : "Articolo non trovato";
    crea("div", "plugin-nota", box).textContent = esito.errore ? "Riprova tra poco o chiedi al personale." : `Codice ${esito.codice || ""}`;
    return box;
  }
  const articolo = esito.articolo || {};
  const daBilancia = articolo.prezzo_bilancia !== undefined && articolo.prezzo_bilancia !== null
    ? { prezzo: articolo.prezzo_bilancia, unita: articolo.unita } : null;
  const prezzo = leggiPrezzo(tipo === "prezzo" ? articolo : mostraPrezzo ? (esito.prezzo || daBilancia) : null);
  if (prezzo?.offerta !== null && prezzo?.offerta !== undefined) {
    const banner = crea("div", "plugin-banner", box);
    banner.textContent = a.banner_testo || "OFFERTA";
    Object.assign(banner.style, { background: a.banner_sfondo || "#d32f2f", color: a.banner_colore || "#fff" });
  }
  const nomeReparto = articolo.reparto || reparto;
  if (nomeReparto) crea("div", "plugin-reparto", box).textContent = nomeReparto;
  crea("div", "plugin-titolo", box).textContent = articolo.descrizione || "";
  if (tipo === "ingredienti") {
    const colore = a.colore_allergeni || "#b71c1c";
    const testo = crea("div", "plugin-ingredienti", box);
    let [ingredienti, allergeni] = separaAllergeni(testoEtichetta(articolo.ingredienti));
    if (articolo.allergeni) allergeni = testoEtichetta(articolo.allergeni);
    if (ingredienti) {
      crea("div", "plugin-etichetta", testo).textContent = "Ingredienti";
      conEvidenza(crea("div", "plugin-testo", testo), ingredienti, colore);
    }
    if (allergeni) {
      crea("div", "plugin-etichetta", testo).textContent = "Allergeni";
      const riga = crea("div", "plugin-testo plugin-allergeni", testo);
      riga.textContent = allergeni;
      riga.style.color = colore;
    }
    if (!ingredienti && !allergeni) crea("div", "plugin-nota", testo).textContent = "Ingredienti non indicati per questo prodotto: chiedi al banco.";
    for (const [chiave, titolo] of [["conservazione", "Conservazione"], ["note", "Note"]]) {
      if (!articolo[chiave]) continue;
      crea("div", "plugin-etichetta", testo).textContent = titolo;
      crea("div", "plugin-testo", testo).textContent = testoEtichetta(articolo[chiave]);
    }
  }
  if (prezzo && (prezzo.pieno !== null || prezzo.offerta !== null)) {
    const riga = crea("div", "plugin-prezzi", box);
    const unita = prezzo.unita ? ` / ${prezzo.unita}` : "";
    if (prezzo.offerta !== null) {
      if (a.mostra_prezzo_pieno !== false && prezzo.pieno !== null) crea("span", "plugin-pieno", riga).textContent = euro(prezzo.pieno);
      const offerta = crea("span", `plugin-prezzo${a.lampeggia !== false ? " lampeggia" : ""}`, riga);
      offerta.textContent = euro(prezzo.offerta);
      if (unita) crea("small", "plugin-unita", offerta).textContent = unita;
      offerta.style.color = a.colore_offerta || "#d32f2f";
      if (prezzo.fino) crea("div", "plugin-nota", box).textContent = `Offerta valida fino al ${giorno(prezzo.fino)}`;
    } else {
      const pieno = crea("span", "plugin-prezzo", riga);
      pieno.textContent = euro(prezzo.pieno);
      if (unita) crea("small", "plugin-unita", pieno).textContent = unita;
      pieno.style.color = a.colore_prezzo || "#1f4e79";
    }
  }
  // Il prezzo stampato sull'etichetta della bilancia: quello di questa confezione.
  const confezione = numero(articolo.prezzo_etichetta);
  if ((tipo === "prezzo" || mostraPrezzo) && confezione) {
    crea("div", "plugin-confezione", box).textContent = `Questa confezione: ${euro(confezione)}`;
  }
  return box;
}

// Nel player: ascolta il lettore e mostra le risposte. «indirizzo()» è il servizio code da usare.
export function preparaLettore({ motore, indirizzo }) {
  let cifre = "";
  let ultimo = 0;
  let timerFine = null;
  let riquadro = null;
  let timerChiudi = null;
  let richiesta = 0;

  const chiudi = () => {
    clearTimeout(timerChiudi);
    riquadro?.remove();
    riquadro = null;
  };

  async function cerca(codice) {
    const plugin = motore.manifest?.plugin;
    const servizio = indirizzo();
    if (!plugin || !servizio) return;
    const bilancia = codiceBilancia(codice, plugin.ingredienti);
    const tipo = bilancia ? "ingredienti" : plugin.prezzo ? "prezzo" : null;
    if (!tipo) return;
    const config = plugin[tipo];
    const questa = ++richiesta;
    const parametri = new URLSearchParams({ codice });
    if (bilancia) {
      parametri.set("plu", bilancia.plu);
      parametri.set("reparto", bilancia.reparto);
      if (config.mostra_prezzo) parametri.set("prezzo", "1");
    }
    let esito;
    const controllo = new AbortController();
    const limite = setTimeout(() => controllo.abort(), 5000);
    try {
      const risposta = await fetch(`${servizio}/plugin/${tipo}?${parametri}`, { signal: controllo.signal, cache: "no-store" });
      esito = risposta.ok ? await risposta.json() : { errore: true };
    } catch {
      esito = { errore: true };
    } finally {
      clearTimeout(limite);
    }
    if (questa !== richiesta || !motore.palco) return; // nel frattempo è arrivata un'altra lettura
    chiudi();
    riquadro = disegnaRiquadro(motore.palco, {
      tipo, esito: { ...esito, codice }, aspetto: config.aspetto, dimensioni: motore.dimensioni,
      reparto: bilancia?.nomeReparto, mostraPrezzo: Boolean(config.mostra_prezzo),
    });
    riquadro.addEventListener("click", chiudi);
    const secondi = esito.trovato ? config.timeout || 8 : Math.min(config.timeout || 8, 4);
    timerChiudi = setTimeout(chiudi, secondi * 1000);
  }

  const lettura = () => {
    clearTimeout(timerFine);
    const codice = cifre;
    cifre = "";
    if (codice.length >= MINIMO_CIFRE) cerca(codice);
  };

  document.addEventListener("keydown", (e) => {
    if (!motore.manifest?.plugin) return;
    const adesso = performance.now();
    if (adesso - ultimo > PAUSA_TRA_TASTI) cifre = "";
    ultimo = adesso;
    if (e.key === "Enter" || e.key === "Tab") {
      if (cifre.length >= MINIMO_CIFRE) e.preventDefault();
      lettura();
      return;
    }
    if (/^[0-9]$/.test(e.key)) {
      cifre += e.key;
      // Lettori senza Invio finale: la lettura finisce quando le cifre smettono di arrivare.
      clearTimeout(timerFine);
      timerFine = setTimeout(lettura, 150);
    }
  }, true);
}
