// Il gruppo «Plugin»: Info Prezzo e Info Ingredienti (facoltativi, abilitati dal SystemAdministrator).
// Per ogni negozio il file SQLite sul PC del negozio; dove sono i dati nel file; i prefissi dei
// codici bilancia; l'aspetto del riquadro, con l'anteprima. I testi dei dati passano da textContent.

import { disegnaRiquadro } from "../player/plugin.js";

let H = null;
let attesaProva = null;

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
  const contenitoreAttivo = crea("div", {}, intro);
  const l = crea("label", { classe: "spunta interruttore" }, contenitoreAttivo);
  l.append(attivo, ` ${NOMI[tipo]} attivo`);
  // La spunta si salva subito (prima si salvava solo con il pulsante in fondo alla pagina).
  const esitoAttivo = crea("span", { classe: "tenue" }, contenitoreAttivo);
  attivo.addEventListener("change", async () => {
    esitoAttivo.className = "tenue";
    esitoAttivo.textContent = " Salvo…";
    try {
      await api("PUT", `/api/plugin/${tipo}/`, { attivo: attivo.checked });
      esitoAttivo.textContent = attivo.checked ? " ✓ Attivato: gli schermi lo ricevono entro un minuto." : " ✓ Disattivato.";
    } catch (errore) {
      attivo.checked = !attivo.checked;
      esitoAttivo.className = "errore";
      esitoAttivo.textContent = ` Non attivato: ${errore.message}`;
    }
  });
  const riga = crea("div", { classe: "riga" }, intro);
  const timeout = campo("Il riquadro resta per (secondi)", crea("input", { type: "number", min: 2, max: 120, value: p.timeout, classe: "corto" }), riga);
  let mostraPrezzo = null;
  if (tipo === "ingredienti") {
    mostraPrezzo = crea("input", { type: "checkbox", checked: p.mostra_prezzo });
    const lp = crea("label", { classe: "spunta" }, riga);
    lp.append(mostraPrezzo, " Mostra anche il prezzo (da Info Prezzo)");
    if (!p.prezzo_attivo) crea("span", { classe: "tenue", testo: "Info Prezzo non è attivo: il prezzo non comparirà." }, riga);
    if (!(p.prefissi || []).length) {
      crea("p", { classe: "nota", testo: "Senza prefissi della bilancia (più sotto, es. 21 = Macelleria) le etichette lette con il lettore, senza toccare lo schermo, "
        + "mostrano il prezzo e non gli ingredienti. Con il pulsante «Info Ingredienti» sul totem la ricerca funziona comunque, anche passando il prodotto sul lettore." }, intro);
    }
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
  let inAttesa = false;
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
    // Prova accesso: salva i dati scritti e chiede al Totem Master di provare cartella e file.
    const led = crea("div", { classe: "prova-accesso" }, azioni);
    const prova_ = f?.prova || { stato: "mai" };
    const colore = { ok: "acceso", errore: "guasto", in_attesa: "attesa", senza_risposta: "guasto" }[prova_.stato];
    if (colore) {
      crea("span", { classe: `pallino ${colore}` }, led);
      led.append(` ${prova_.stato === "in_attesa" ? "Prova in corso sul Totem Master…" : prova_.messaggio || ""}`);
      if (prova_.stato === "in_attesa") inAttesa = true;
    }
    crea("button", {
      testo: "🔌 Prova accesso",
      "data-aiuto": "Salva i dati e fa provare al Totem Master del negozio la cartella condivisa, l'utente e la password e il file: LED verde se riesce, rosso con il motivo se no. Ci vogliono pochi secondi.",
      disabled: !n.master_online && !!n.indirizzo_totem,
      onclick: () => prova(async () => {
        const salvata = f ? await api("PATCH", `/api/fonti-plugin/${f.id}/`, dati()) : await api("POST", "/api/fonti-plugin/", dati());
        await api("POST", `/api/fonti-plugin/${salvata.id}/prova/`);
      }, "Prova chiesta: il Totem Master risponde entro pochi secondi."),
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

  // Finché un Totem Master deve rispondere alla prova di accesso, la scheda si aggiorna da sola.
  clearTimeout(attesaProva);
  if (inAttesa) attesaProva = setTimeout(() => { if (H.stato.scheda === `info_${tipo}`) H.mostra(`info_${tipo}`); }, 3000);

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
      + "Parametri: :codice (il codice letto), :codice_corto (senza zeri iniziali), :plu e :reparto (codici bilancia), :adesso (data e ora del totem, «AAAA-MM-GG hh:mm:ss»: usala al posto di datetime('now','localtime'), che sui totem Windows non funziona). Il file è aperto in sola lettura.",
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

// --- Filtro contenuti: niente nudo sugli schermi (immagini, video, dirette) -----------------------

const TIPI_FILTRO = [
  ["immagini", "Immagini", "JPEG, PNG, GIF, WebP: controllate al caricamento. Un'immagine vietata non si carica: in coda va la successiva."],
  ["video", "Video", "MP4, MOV, WebM: controllati al caricamento su tutta la durata. Il video si carica, ma i tratti vietati sullo schermo restano coperti dall'immagine di riserva, senza audio."],
  ["dirette", "Dirette streaming", "Bollino del canale all'importazione, poi sorveglianza continua mentre sono in onda. Una diretta bloccata è sostituita dall'immagine di riserva."],
];
const NOMI_SEVERITA = { bassa: "Bassa", media: "Media", alta: "Alta" };
const STATI_DIRETTA = { attesa: "⏳ In verifica", ok: "✅ Verificata", bloccata: "⛔ Bloccata", irraggiungibile: "⚠️ Non verificabile" };
const percento = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

function spiegaSeverita(tipo, s) {
  if (tipo === "immagini") return `blocca da ${s.soglia}% di probabilità di nudo`;
  if (tipo === "video") return `blocca da ${s.soglia}%; un fotogramma ogni ${s.ogni_secondi} s`;
  return `blocca da ${s.soglia}%; in onda ricontrollata ogni ${s.ricontrollo} min (${s.fotogrammi_diretta} fotogrammi)`;
}

export async function schedaFiltroContenuti() {
  const { crea, sezione, api, prova, campo, scelta, tabella } = H;
  const f = await api("GET", "/api/plugin/filtro-contenuti/");

  const intro = sezione("Filtro contenuti");
  crea("p", {
    classe: "nota",
    testo: "Impedisce che sugli schermi vada nudo o contenuto esplicito. Il riconoscimento gira sul vostro server (nessuna immagine esce): "
      + "distingue il nudo da intimo, costumi e abiti, che restano ammessi. Quello che il filtro riconosce come vietato non va in onda e nessuno lo può sbloccare: "
      + "un'immagine non si carica, i tratti di un video e le dirette bloccate sono coperti dall'immagine di riserva dello schermo (quella mostrata quando non ci sono promozioni). "
      + "Vale per i contenuti nuovi; quelli già caricati restano come sono.",
  }, intro);
  crea("p", {
    classe: f.disponibile ? "nota" : "messaggio errore",
    testo: f.disponibile
      ? "✅ Modello di riconoscimento pronto."
      : "⚠️ Il modello di riconoscimento non è installato su questo server: con il filtro attivo i contenuti di quel tipo non si possono caricare. Va rilanciato l'aggiornamento del server (scarica il modello).",
  }, intro);
  crea("p", {
    classe: "tenue",
    testo: f.database_canali
      ? `Database dei canali (iptv-org): ${f.database_canali.canali.toLocaleString("it-IT")} canali, aggiornato ${quando(f.database_canali.aggiornato)}. Si aggiorna da solo ogni giorno.`
      : "Database dei canali (iptv-org): si scarica al primo uso del filtro per le dirette.",
  }, intro);

  // --- Attivazione per tipo, con la severità ---
  const impostazioni = sezione("Cosa controllare");
  const corpo = tabella(["Tipo", "Attivo", "Severità", ""], impostazioni);
  const controlli = {};
  for (const [chiave, titolo, descrizione] of TIPI_FILTRO) {
    const riga = crea("tr", {}, corpo);
    const nome = crea("td", {}, riga);
    crea("strong", { testo: titolo }, nome);
    crea("div", { classe: "tenue", testo: descrizione }, nome);
    const attivo = crea("input", { type: "checkbox", checked: f[chiave], disabled: !H.ruoloGestione() }, crea("label", { classe: "spunta interruttore" }, crea("td", {}, riga)));
    const severita = scelta(Object.entries(NOMI_SEVERITA), f[`severita_${chiave}`]);
    severita.disabled = !H.ruoloGestione();
    crea("td", {}, riga).appendChild(severita);
    const spiega = crea("td", { classe: "tenue" }, riga);
    const aggiorna = () => { spiega.textContent = spiegaSeverita(chiave, f.severita[severita.value]); };
    severita.addEventListener("change", aggiorna);
    aggiorna();
    controlli[chiave] = { attivo, severita };
  }
  crea("p", {
    classe: "tenue",
    testo: "Bassa: blocca solo il nudo evidente. Media: l'equilibrio consigliato. Alta: blocca anche i casi dubbi (qualche quadro o foto artistica in più). "
      + "Nelle dirette un fotogramma dubbio da solo non basta per bloccarle: ne servono due di fila, o uno quasi certo.",
  }, impostazioni);
  crea("button", {
    classe: "primario", testo: "Salva",
    onclick: () => {
      const dati = {};
      for (const [chiave, c] of Object.entries(controlli)) Object.assign(dati, { [chiave]: c.attivo.checked, [`severita_${chiave}`]: c.severita.value });
      prova(() => api("PUT", "/api/plugin/filtro-contenuti/", dati), "Filtro contenuti salvato.");
    },
  }, crea("div", { classe: "riga" }, impostazioni));

  // --- Prova: un file o una diretta, senza salvare ---
  const sezioneProva = sezione("Prova il filtro");
  crea("p", { classe: "nota", testo: "Scegli un'immagine o un video, oppure incolla l'indirizzo di una diretta: il filtro dice cosa farebbe, senza salvare nulla." }, sezioneProva);
  const rigaProva = crea("div", { classe: "riga" }, sezioneProva);
  const file = campo("Immagine o video", crea("input", { type: "file", accept: "image/*,video/*" }), rigaProva);
  const url = campo("…oppure indirizzo della diretta", crea("input", { placeholder: "https://…/playlist.m3u8", size: 40 }), rigaProva);
  const severitaProva = campo("Severità", scelta(Object.entries(NOMI_SEVERITA), "media"), rigaProva);
  const esito = crea("div", { classe: "esito-filtro" }, sezioneProva);
  crea("button", {
    classe: "primario", testo: "▶ Prova",
    onclick: async (e) => {
      const dati = new FormData();
      if (file.files[0]) dati.append("file", file.files[0]);
      else dati.append("url", url.value.trim());
      dati.append("severita", severitaProva.value);
      e.target.disabled = true;
      esito.replaceChildren(crea("p", { classe: "tenue", testo: "Controllo in corso… (un video o una diretta possono richiedere fino a un minuto)" }));
      try {
        const r = await api("POST", "/api/plugin/filtro-contenuti/", dati);
        esito.replaceChildren();
        crea("p", {
          classe: `messaggio ${r.vietato ? "errore" : "ok"}`,
          testo: !r.vietato
            ? `✅ Ammesso: nudo al massimo al ${percento(r.punteggio)}.`
            : r.tipo === "video"
              ? `🛡 Il video si caricherebbe con ${r.coperture.length} ${r.coperture.length === 1 ? "tratto coperto" : "tratti coperti"}: ${r.coperture.map(([da, a]) => `${Math.round(da)}–${Math.round(a)} s`).join(", ")}.`
              : r.tipo === "diretta"
                ? `⛔ Vietata: nudo al ${percento(r.punteggio)}. Andrebbe bloccata e sostituita dall'immagine di riserva.`
                : `⛔ Vietata: nudo al ${percento(r.punteggio)}. Non si caricherebbe.`,
        }, esito);
        const c = r.categorie || {};
        crea("p", { classe: "tenue", testo: `Fotogramma peggiore: nudo ${percento(c.nudo)} · intimo/costume ${percento(c.intimo)} · vestito ${percento(c.vestito)} · altro ${percento(c.altro)} · fotogrammi guardati: ${r.fotogrammi}` }, esito);
      } catch (errore) {
        esito.replaceChildren(crea("p", { classe: "messaggio errore", testo: errore.message }));
      } finally {
        e.target.disabled = false;
      }
    },
  }, crea("div", { classe: "riga" }, sezioneProva));

  // --- Dirette controllate ---
  const sezioneDirette = sezione("Dirette sotto controllo");
  if (!f.dirette_controllate.length) {
    crea("p", { classe: "vuoto", testo: "Nessuna: le dirette aggiunte con il filtro attivo per le dirette compaiono qui." }, sezioneDirette);
  } else {
    crea("p", { classe: "nota", testo: "In onda va solo una diretta «Verificata». Una diretta bloccata non torna più in onda; una non verificabile (il server non la raggiunge) si riprova ogni qualche ora." }, sezioneDirette);
    const corpoDirette = tabella(["Canale", "Bollino", "Stato", "Ultimo controllo", "Nudo (max)"], sezioneDirette);
    for (const d of f.dirette_controllate) {
      const riga = crea("tr", {}, corpoDirette);
      const nome = crea("td", {}, riga);
      crea("strong", { testo: d.nome }, nome);
      crea("div", { classe: "tenue", testo: d.url }, nome);
      const canale = d.esito?.canale;
      crea("td", { testo: canale ? `${{ riconosciuto: "🟢", sconosciuto: "🟡", vietato: "🔴" }[canale.bollino] || ""} ${canale.motivo}` : "—" }, riga);
      crea("td", { testo: STATI_DIRETTA[d.controllo] || d.stato, title: d.esito?.errore || "" }, riga);
      crea("td", { testo: quando(d.controllo_il) }, riga);
      crea("td", { testo: d.esito?.punteggio != null ? percento(d.esito.punteggio) : "—" }, riga);
    }
  }

  // --- Ultimi rifiuti ---
  const sezioneRifiuti = sezione("Ultimi blocchi");
  if (!f.rifiuti.length) {
    crea("p", { classe: "vuoto", testo: "Nessun contenuto bloccato finora." }, sezioneRifiuti);
  } else {
    const corpoRifiuti = tabella(["Quando", "Chi", "Cosa", "Nome", "Nudo / coperto"], sezioneRifiuti);
    for (const r of f.rifiuti) {
      const riga = crea("tr", {}, corpoRifiuti);
      crea("td", { testo: quando(r.quando) }, riga);
      crea("td", { testo: r.utente || "controllo automatico" }, riga);
      crea("td", { testo: { diretta_bloccata_filtro: "Diretta bloccata", video_coperto_filtro: "Video con tratti coperti" }[r.azione] || "Immagine rifiutata" }, riga);
      crea("td", { testo: r.nome }, riga);
      crea("td", { testo: r.azione === "video_coperto_filtro" ? `${r.secondi} s coperti` : percento(r.punteggio) }, riga);
    }
    crea("p", { classe: "tenue", testo: "L'elenco completo è nel Registro operazioni." }, sezioneRifiuti);
  }
}
