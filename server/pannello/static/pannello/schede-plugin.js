// Il gruppo «Plugin»: Info Prezzo e Info Ingredienti (facoltativi, abilitati da Sanidat).
// Per ogni negozio il file SQLite sul PC del negozio; dove sono i dati nel file; i prefissi dei
// codici bilancia; l'aspetto del riquadro, con l'anteprima. I testi dei dati passano da textContent.

import { disegnaRiquadro } from "../player/plugin.js";

let H = null;

export function preparaSchedePlugin(strumenti) {
  H = strumenti;
}

const NOMI = { prezzo: "Info Prezzo", ingredienti: "Info Ingredienti" };

const ESEMPI = {
  prezzo: { trovato: true, articolo: { descrizione: "Pasta di semola trafilata al bronzo 500 g", prezzo: 1.29, prezzo_offerta: 0.99, offerta_al: "2099-12-31" } },
  ingredienti: {
    trovato: true,
    articolo: {
      descrizione: "Prosciutto crudo stagionato", ingredienti: "Coscia di suino, sale. Stagionatura minima 14 mesi.",
      allergeni: "Nessuno", conservazione: "Conservare tra 0 e 4 °C",
    },
    prezzo: { prezzo: 32.9, unita: "kg" },
  },
};

function caricaStileRiquadro() {
  if (document.getElementById("stile-plugin")) return;
  const link = document.createElement("link");
  link.id = "stile-plugin";
  link.rel = "stylesheet";
  link.href = new URL("../player/plugin.css", import.meta.url).href;
  document.head.appendChild(link);
}

const quando = (iso) => (iso ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "—");

export const schedaInfoPrezzo = () => schedaPlugin("prezzo");
export const schedaInfoIngredienti = () => schedaPlugin("ingredienti");

async function schedaPlugin(tipo) {
  const { crea, sezione, api, prova, campo, scelta, tabella } = H;
  caricaStileRiquadro();
  let p;
  try {
    p = await api("GET", `/api/plugin/${tipo}/`);
  } catch (errore) {
    const box = sezione(NOMI[tipo]);
    crea("p", { classe: "nota", testo: errore.message }, box);
    crea("p", { classe: "tenue", testo: "Il SystemAdministrator lo abilita in «Clienti», nelle abilitazioni dell'azienda." }, box);
    return;
  }

  // --- Attivazione ---
  const intro = sezione(NOMI[tipo]);
  crea("p", {
    classe: "nota",
    testo: tipo === "prezzo"
      ? "Il cliente passa un prodotto davanti al lettore di codici a barre (USB) collegato a un totem o a un monitor: lo schermo mostra descrizione e prezzo, con il banner «Offerta» e il prezzo che lampeggia se è in offerta. "
      : "Il cliente passa l'etichetta di un prodotto della bilancia (codice con prefisso, es. 20, 21…): lo schermo mostra ingredienti, allergeni e conservazione, e se vuoi anche il prezzo (serve Info Prezzo attivo). ",
  }, intro);
  crea("p", {
    classe: "tenue",
    testo: "I dati stanno in un file SQLite (.db) su un PC del negozio, in una cartella condivisa. Il Totem Master del negozio lo copia ogni tot minuti (solo se è cambiato) e risponde ai dispositivi del negozio: "
      + "funziona anche senza internet e il file non passa dal server. Serve il Totem Master (Sedi e gruppi, Anagrafica Dispositivi Video).",
  }, intro);
  const attivo = crea("input", { type: "checkbox", checked: p.attivo });
  const l = crea("label", { classe: "spunta interruttore" }, crea("div", {}, intro));
  l.append(attivo, ` ${NOMI[tipo]} attivo`);
  const riga = crea("div", { classe: "riga" }, intro);
  const timeout = campo("Il riquadro resta per (secondi)", crea("input", { type: "number", min: 2, max: 120, value: p.timeout, classe: "corto" }), riga);
  let mostraPrezzo = null;
  if (tipo === "ingredienti") {
    mostraPrezzo = crea("input", { type: "checkbox", checked: p.mostra_prezzo });
    const lp = crea("label", { classe: "spunta" }, riga);
    lp.append(mostraPrezzo, " Mostra anche il prezzo (da Info Prezzo)");
    if (!p.prezzo_attivo) crea("span", { classe: "tenue", testo: "Info Prezzo non è attivo: il prezzo non comparirà." }, riga);
  }

  // --- Negozi e file ---
  const negozi = sezione("Negozi: il file sul PC del negozio");
  crea("p", {
    classe: "tenue",
    testo: "Percorso: la cartella condivisa e il file, come in \\\\192.168.1.20\\Dati\\Prezzi\\articoli.db → indirizzo «192.168.1.20», percorso «Dati\\Prezzi\\articoli.db». "
      + "Utente e password sono quelli per aprire la cartella condivisa (vuoti se è aperta a tutti). La password resta cifrata e va solo al Totem Master. "
      + "Il file si copia solo se è cambiato; per i file grandi che cambiano a ogni pesata (bilancia) meglio uno o due orari fissi, e «Aggiorna adesso» quando servono subito le modifiche. Sul totem serve spazio libero per due volte il file.",
  }, negozi);
  const corpo = tabella(["Negozio", "Totem Master", "File", "Utente", "Quando copiarlo", "Ultima copia", ""], negozi);
  for (const n of p.negozi) {
    const r = crea("tr", {}, corpo);
    crea("td", { testo: n.nome }, r);
    const master = crea("td", {}, r);
    if (!n.indirizzo_totem) master.append("⚠️ manca l'IP del totem nella sede");
    else if (!n.master) master.append("⚠️ nessun Totem Master");
    else {
      crea("span", { classe: `pallino ${n.master_online ? "acceso" : "spento"}` }, master);
      master.append(` ${n.master}`);
    }
    const f = n.fonte;
    const indirizzo = crea("input", { value: f?.indirizzo || "", placeholder: "192.168.1.20", size: 13, "data-aiuto": "L'indirizzo IP (o il nome) del PC del negozio che ha il file, es. 192.168.1.20." });
    const percorso = crea("input", { value: f?.percorso || "", placeholder: "Dati\\Prezzi\\articoli.db", size: 24, "data-aiuto": "La cartella condivisa e il file .db, es. Utility\\DigiProject\\DigiProject.db (la prima parte è il nome della condivisione)." });
    const cellaFile = crea("td", { classe: "file-plugin" }, r);
    cellaFile.append("\\\\", indirizzo, "\\", percorso);
    const cellaUtente = crea("td", {}, r);
    const utente = crea("input", { value: f?.utente || "", placeholder: "utente", size: 10, autocomplete: "off", "data-aiuto": "L'utente Windows che può leggere la cartella condivisa (es. PCNEGOZIO\\utente). Vuoto se la cartella è aperta a tutti." }, cellaUtente);
    const password = crea("input", { type: "password", placeholder: f?.ha_password ? "•••••• (invariata)" : "password", size: 10, autocomplete: "new-password", "data-aiuto": "La password di quell'utente. Resta cifrata e va solo al Totem Master; lasciala vuota per non cambiarla." }, cellaUtente);
    // Quando copiare: agli orari fissi e/o ogni N minuti, entrambi facoltativi (almeno uno). Il file
    // si copia comunque solo se è cambiato.
    const cellaCopia = crea("td", { classe: "copia-plugin" }, r);
    const conOrari = crea("input", { type: "checkbox", checked: f ? f.orari.length > 0 : tipo === "ingredienti" });
    const orari = crea("input", { value: (f?.orari?.length ? f.orari : ["06:30"]).join(", "), placeholder: "06:30, 13:00", size: 11 });
    const conMinuti = crea("input", { type: "checkbox", checked: f ? f.aggiorna_minuti > 0 : tipo === "prezzo" });
    const minuti = crea("input", { type: "number", min: 1, max: 1440, value: f?.aggiorna_minuti || (tipo === "ingredienti" ? 120 : 15), classe: "corto" });
    const riga1 = crea("label", { classe: "spunta" }, cellaCopia);
    riga1.append(conOrari, " alle ", orari);
    const riga2 = crea("label", { classe: "spunta" }, cellaCopia);
    riga2.append(conMinuti, " ogni ", minuti, " min");
    const aggiornaModo = () => { orari.disabled = !conOrari.checked; minuti.disabled = !conMinuti.checked; };
    conOrari.addEventListener("change", aggiornaModo);
    conMinuti.addEventListener("change", aggiornaModo);
    aggiornaModo();
    const stato = crea("td", {}, r);
    if (!f) stato.textContent = "—";
    else if (!n.stato) stato.textContent = n.master_online ? "in attesa del totem…" : "—";
    else {
      stato.textContent = n.stato.copiato ? quando(n.stato.copiato) : "non ancora copiato";
      if (n.stato.dimensione > 0) stato.append(` · ${(n.stato.dimensione / 1048576).toFixed(0)} MB`);
      if (n.stato.in_corso === "True" || n.stato.in_corso === true) crea("div", { classe: "tenue", testo: "⏳ copia in corso…" }, stato);
      else if (n.stato.prossimo) crea("div", { classe: "tenue", testo: `prossima: ${quando(n.stato.prossimo)}` }, stato);
      if (n.stato.errore) crea("div", { classe: "attenzione", testo: `⚠️ ${n.stato.errore}` }, stato);
    }
    const azioni = crea("td", { classe: "azioni" }, r);
    const dati = () => ({
      tipo, sede: n.sede, indirizzo: indirizzo.value, percorso: percorso.value, utente: utente.value,
      aggiorna_minuti: conMinuti.checked ? parseInt(minuti.value, 10) || 15 : 0,
      orari: conOrari.checked ? orari.value.split(/[,;\s]+/).filter(Boolean) : [],
      ...(password.value ? { password: password.value } : {}),
    });
    crea("button", {
      classe: "primario", testo: f ? "Salva" : "Aggiungi",
      onclick: () => prova(() => (f ? api("PATCH", `/api/fonti-plugin/${f.id}/`, dati()) : api("POST", "/api/fonti-plugin/", dati())), "Salvato: il Totem Master lo riceve entro un minuto."),
    }, azioni);
    if (f) {
      crea("button", {
        testo: "⟳ Aggiorna adesso",
        "data-aiuto": "Il Totem Master ricopia subito il file (per esempio dopo aver cambiato gli ingredienti), senza aspettare l'orario.",
        onclick: () => prova(() => api("POST", `/api/fonti-plugin/${f.id}/aggiorna/`), "Richiesta inviata: il Totem Master ricopia il file entro un minuto."),
      }, azioni);
      crea("button", {
        testo: "Togli", classe: "pericolo",
        onclick: () => confirm(`Togliere il file di «${n.nome}»? In quel negozio ${NOMI[tipo]} non risponderà più.`) && prova(() => api("DELETE", `/api/fonti-plugin/${f.id}/`), "Tolto."),
      }, azioni);
    }
  }

  // --- Dove sono i dati nel file ---
  const dove = sezione("Dove sono i dati nel file");
  crea("p", {
    classe: "tenue",
    testo: "Il nome della tabella e delle colonne nel file .db (come le mostra un programma come «DB Browser for SQLite»). "
      + "Per i file con una struttura particolare si può scrivere la query a mano: in quel caso la mappatura non serve.",
  }, dove);
  const formato = campo("Gestionale", scelta([["", "Altro: indico tabella e colonne (o la query)"], ...p.preimpostazioni.map((x) => [x.chiave, x.nome])], p.formato), crea("div", { classe: "riga" }, dove));
  const personalizzato = crea("div", {}, dove);
  const griglia = crea("div", { classe: "riga" }, personalizzato);
  const colonne = {};
  for (const c of p.campi) {
    colonne[c.chiave] = campo(`${c.etichetta}${c.obbligatoria ? " *" : ""}`, crea("input", { value: p.mappatura[c.chiave] || "", size: 16 }), griglia);
  }
  const avanzata = crea("details", {}, personalizzato);
  crea("summary", { testo: "Query scritta a mano (avanzato)" }, avanzata);
  crea("p", {
    classe: "tenue",
    testo: `Una SELECT che restituisca al massimo una riga, con le colonne chiamate ${p.uscite.join(", ")}. `
      + "Parametri: :codice (il codice letto), :codice_corto (senza zeri iniziali), :plu e :reparto (codici bilancia). Il file è aperto in sola lettura.",
  }, avanzata);
  const query = crea("textarea", { rows: 4, cols: 90, value: p.query, placeholder: "SELECT descr AS descrizione, prezzo FROM articoli WHERE ean = :codice" }, avanzata);
  if (p.query_generata) {
    const usata = crea("details", {}, dove);
    crea("summary", { testo: p.formato ? "La query del gestionale (pronta)" : "La query che viene usata ora (dalla mappatura)" }, usata);
    crea("pre", { classe: "query-plugin", testo: p.query_generata }, usata);
  }
  if (p.query) avanzata.open = true;
  const aggiornaFormato = () => (personalizzato.hidden = Boolean(formato.value));
  formato.addEventListener("change", aggiornaFormato);
  aggiornaFormato();

  // --- Codici bilancia ---
  let prefissi = null, pluInizio = null, pluLunghezza = null;
  if (tipo === "ingredienti") {
    const bil = sezione("Codici bilancia (prefissi)");
    crea("p", {
      classe: "tenue",
      testo: "Ogni prefisso è un banco: lo stesso PLU può esistere in banchi diversi, e il prefisso dice quale. Il «codice nel file» è come il banco è scritto nella colonna reparto (vuoto = il prefisso stesso). "
        + "Esempio EAN-13 «20 00123 01234 5»: prefisso 20, PLU dalla 3ª cifra per 5 cifre.",
    }, bil);
    const rigaPlu = crea("div", { classe: "riga" }, bil);
    pluInizio = campo("Il PLU inizia dalla cifra", crea("input", { type: "number", min: 1, max: 12, value: p.plu_inizio, classe: "corto" }), rigaPlu);
    pluLunghezza = campo("Lunghezza del PLU (cifre)", crea("input", { type: "number", min: 1, max: 7, value: p.plu_lunghezza, classe: "corto" }), rigaPlu);
    const corpoPref = tabella(["Prefisso", "Banco / reparto (si mostra)", "Codice nel file", ""], bil);
    const righe = [];
    const aggiungi = (v = {}) => {
      const r = crea("tr", {}, corpoPref);
      const voce = {
        prefisso: crea("input", { value: v.prefisso || "", size: 4, maxLength: 3, placeholder: "20", "data-aiuto": "Le prime cifre delle etichette della bilancia (es. 21): un codice che inizia così cerca gli ingredienti invece del prezzo." }, crea("td", {}, r)),
        reparto: crea("input", { value: v.reparto || "", size: 18, maxLength: 40, placeholder: "Salumeria", "data-aiuto": "Il nome del banco da mostrare nel riquadro, se il file non lo indica già (con DIGI il banco arriva dal file)." }, crea("td", {}, r)),
        codice: crea("input", { value: v.codice || "", size: 8, maxLength: 20, "data-aiuto": "Come il banco è scritto nella colonna reparto del file. Vuoto: il prefisso stesso. Con EvoPos e DIGI non serve." }, crea("td", {}, r)),
      };
      crea("button", { testo: "✕", onclick: () => { r.remove(); righe.splice(righe.indexOf(voce), 1); } }, crea("td", {}, r));
      righe.push(voce);
    };
    (p.prefissi.length ? p.prefissi : [{}]).forEach(aggiungi);
    crea("button", { testo: "+ Prefisso", onclick: () => aggiungi() }, bil);
    prefissi = () => righe.filter((v) => v.prefisso.value.trim()).map((v) => ({ prefisso: v.prefisso.value.trim(), reparto: v.reparto.value, codice: v.codice.value }));
  }

  // --- Aspetto, con l'anteprima ---
  const vista = sezione("Aspetto del riquadro");
  const a = p.aspetto;
  const controlli = crea("div", { classe: "riga" }, vista);
  const valori = {};
  const colore = (k, t) => (valori[k] = campo(t, crea("input", { type: "color", value: a[k] }), controlli));
  valori.carattere = campo("Carattere", scelta(["sans-serif", "serif", "Arial", "Verdana", "Tahoma", "Georgia", "Roboto", "Montserrat", "Oswald"].map((x) => [x, x]), a.carattere), controlli);
  valori.dimensione = campo("Grandezza testo (%)", crea("input", { type: "number", min: 50, max: 250, step: 10, value: a.dimensione, classe: "corto" }), controlli);
  valori.larghezza = campo("Larghezza (% schermo)", crea("input", { type: "number", min: 30, max: 100, step: 5, value: a.larghezza, classe: "corto" }), controlli);
  valori.posizione = campo("Posizione", scelta([["centro", "Al centro"], ["alto", "In alto"], ["basso", "In basso"]], a.posizione), controlli);
  colore("sfondo", "Sfondo");
  colore("testo", "Testo");
  colore("colore_prezzo", "Prezzo");
  colore("colore_offerta", "Prezzo in offerta");
  if (tipo === "ingredienti") colore("colore_allergeni", "Allergeni");
  const banner = crea("div", { classe: "riga" }, vista);
  valori.banner_testo = campo("Testo del banner", crea("input", { value: a.banner_testo, maxLength: 30, size: 14 }), banner);
  valori.banner_sfondo = campo("Sfondo banner", crea("input", { type: "color", value: a.banner_sfondo }), banner);
  valori.banner_colore = campo("Testo banner", crea("input", { type: "color", value: a.banner_colore }), banner);
  const spunta = (k, t) => {
    const s = crea("input", { type: "checkbox", checked: a[k] });
    const lab = crea("label", { classe: "spunta" }, banner);
    lab.append(s, ` ${t}`);
    valori[k] = s;
  };
  spunta("lampeggia", "Prezzo in offerta lampeggiante");
  spunta("mostra_prezzo_pieno", "Mostra il prezzo pieno barrato");
  const aspetto = () => Object.fromEntries(Object.entries(valori).map(([k, c]) => [k, c.type === "checkbox" ? c.checked : c.type === "number" ? parseInt(c.value, 10) : c.value]));

  const schermo = crea("div", { classe: "anteprima-plugin" }, vista);
  const palco = crea("div", { classe: "palco-plugin" }, schermo);
  const disegna = () => {
    palco.replaceChildren();
    disegnaRiquadro(palco, {
      tipo, esito: ESEMPI[tipo], aspetto: aspetto(), dimensioni: { larghezza: 1920, altezza: 1080 },
      reparto: tipo === "ingredienti" ? (prefissi?.()[0]?.reparto || "Salumeria") : "", mostraPrezzo: mostraPrezzo ? mostraPrezzo.checked : false,
    });
    palco.style.transform = `scale(${schermo.clientWidth / 1920})`;
  };
  vista.addEventListener("input", disegna);
  vista.addEventListener("change", disegna);
  mostraPrezzo?.addEventListener("change", disegna);
  requestAnimationFrame(disegna);
  crea("p", { classe: "tenue", testo: "Anteprima con dati di esempio, su uno schermo orizzontale." }, vista);

  // --- Salva ---
  const fine = sezione("");
  crea("button", {
    classe: "primario", testo: `Salva ${NOMI[tipo]}`,
    onclick: () => prova(() => api("PUT", `/api/plugin/${tipo}/`, {
      attivo: attivo.checked, timeout: parseInt(timeout.value, 10) || 8, query: query.value, formato: formato.value,
      mappatura: Object.fromEntries(Object.entries(colonne).map(([k, c]) => [k, c.value.trim()])),
      aspetto: aspetto(),
      ...(tipo === "ingredienti" ? {
        mostra_prezzo: mostraPrezzo.checked, prefissi: prefissi(),
        plu_inizio: parseInt(pluInizio.value, 10), plu_lunghezza: parseInt(pluLunghezza.value, 10),
      } : {}),
    }), "Salvato: gli schermi lo ricevono entro un minuto."),
  }, fine);
}
