// «Distribuzione contenuti» (Report & Log): i file del palinsesto sono arrivati agli schermi?
// Per ogni schermo la barra dei file scaricati, il file in corso con la velocità e cosa va in
// onda adesso; per ogni promozione su quanti schermi è già arrivata. L'Administrator vede la
// sua azienda, il SystemAdministrator anche tutte le aziende insieme. Si aggiorna da sola.
// I testi dei dati passano da textContent.

let H = null;

export function preparaSchedeDistribuzione(strumenti) {
  H = strumenti;
}

const OGNI = 10_000;

export const STATI = {
  aggiornato: { testo: "In onda, aggiornato", icona: "✓", aiuto: "Lo schermo ha tutti i file del palinsesto attuale e lo sta mostrando." },
  pronto: { testo: "File arrivati", icona: "⇣", aiuto: "Tutti i file sono sullo schermo: il palinsesto nuovo parte al prossimo controllo (entro 30 secondi)." },
  scaricamento: { testo: "In scaricamento", icona: "⇣", aiuto: "Lo schermo sta scaricando i file nuovi; intanto continua a mostrare il palinsesto precedente." },
  fascia: { testo: "Attende la fascia", icona: "⏰", aiuto: "I file nuovi si scaricano solo nella fascia di download impostata (Impostazioni → Fasce di download). Si può anticipare con «Scarica adesso»." },
  errore: { testo: "Download non riuscito", icona: "!", aiuto: "Alcuni file non sono arrivati: lo schermo riprova da solo ogni 30 secondi. Se resta così, controlla la rete del negozio." },
  in_arrivo: { testo: "In arrivo", icona: "…", aiuto: "C'è un palinsesto nuovo: lo schermo lo chiede al server entro 30 secondi e comincia a scaricare." },
  offline: { testo: "Non in linea", icona: "✕", aiuto: "Lo schermo non si fa sentire da qualche minuto: riceverà i file quando torna in linea." },
  mai_collegato: { testo: "Mai collegato", icona: "○", aiuto: "Lo schermo è in anagrafica ma il player non si è ancora collegato." },
};
const ORDINE = ["scaricamento", "errore", "fascia", "in_arrivo", "pronto", "offline", "mai_collegato", "aggiornato"];

export function peso(byte) {
  if (!byte) return "0 B";
  const unita = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(unita.length - 1, Math.floor(Math.log(byte) / Math.log(1024)));
  return `${(byte / 1024 ** i).toLocaleString("it-IT", { maximumFractionDigits: i >= 2 ? 1 : 0 })} ${unita[i]}`;
}

const ora = (t) => (t ? new Date(t).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }) : "");
function fa(t) {
  if (!t) return "mai";
  const secondi = Math.max(0, Math.round((Date.now() - Date.parse(t)) / 1000));
  if (secondi < 60) return "adesso";
  if (secondi < 3600) return `${Math.floor(secondi / 60)} min fa`;
  if (secondi < 86400) return `${Math.floor(secondi / 3600)} h fa`;
  return new Date(t).toLocaleDateString("it-IT");
}

// L'anello della percentuale (SVG): verde quando è tutto arrivato.
export function anello(percentuale, genitore, { grande = false, aiuto = "" } = {}) {
  const lato = grande ? 148 : 58;
  const spessore = grande ? 14 : 7;
  const r = (lato - spessore) / 2;
  const giro = 2 * Math.PI * r;
  const ns = "http://www.w3.org/2000/svg";
  const box = H.crea("div", { classe: `anello ${grande ? "grande" : ""} ${percentuale >= 100 ? "pieno" : ""}`, "data-aiuto": aiuto }, genitore);
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${lato} ${lato}`);
  for (const [classe, tratto] of [["fondo", giro], ["valore", (giro * Math.max(0, Math.min(100, percentuale ?? 0))) / 100]]) {
    const c = document.createElementNS(ns, "circle");
    Object.entries({ cx: lato / 2, cy: lato / 2, r, "stroke-width": spessore, "stroke-dasharray": `${tratto} ${giro}`, class: classe })
      .forEach(([k, v]) => c.setAttribute(k, v));
    c.setAttribute("transform", `rotate(-90 ${lato / 2} ${lato / 2})`);
    svg.appendChild(c);
  }
  box.appendChild(svg);
  H.crea("span", { classe: "cifra", testo: percentuale == null ? "–" : `${percentuale}%` }, box);
  return box;
}

export function barra(percentuale, genitore, { classe = "", aiuto = "" } = {}) {
  const b = H.crea("div", { classe: `barra-avanzamento ${classe}`, "data-aiuto": aiuto }, genitore);
  const riempi = H.crea("div", { classe: "riempimento" }, b);
  riempi.style.width = `${Math.max(0, Math.min(100, percentuale ?? 0))}%`;
  return b;
}

// La barra a colori degli stati: quanti schermi in ogni stato.
export function barraStati(stati, totale, genitore) {
  const b = H.crea("div", { classe: "barra-stati" }, genitore);
  for (const chiave of [...ORDINE].reverse()) {
    if (!stati[chiave]) continue;
    const pezzo = H.crea("span", { classe: `stato-${chiave}`, "data-aiuto": `${STATI[chiave].testo}: ${stati[chiave]} schermi. ${STATI[chiave].aiuto}` }, b);
    pezzo.style.flex = String(stati[chiave] / Math.max(1, totale));
  }
  return b;
}

function cartellini(dati, genitore) {
  const box = H.crea("div", { classe: "cartellini" }, genitore);
  const voci = [
    ["Schermi", dati.schermi, "", "Tutti gli schermi e i totem in anagrafica."],
    ["Aggiornati", dati.stati.aggiornato, "aggiornato", STATI.aggiornato.aiuto],
    ["In scaricamento", dati.stati.scaricamento + dati.stati.pronto + dati.stati.in_arrivo, "scaricamento", "Stanno ricevendo un palinsesto nuovo (compresi quelli che lo stanno per chiedere o che lo hanno appena finito)."],
    ["Attendono la fascia", dati.stati.fascia, "fascia", STATI.fascia.aiuto],
    ["Con errori", dati.stati.errore, "errore", STATI.errore.aiuto],
    ["Non in linea", dati.stati.offline + dati.stati.mai_collegato, "offline", "Schermi spenti, scollegati o mai collegati."],
  ];
  for (const [titolo, numero, stato, aiuto] of voci) {
    const c = H.crea("div", { classe: `cartellino ${stato ? `stato-${stato}` : ""}`, "data-aiuto": aiuto }, box);
    H.crea("strong", { testo: String(numero) }, c);
    H.crea("span", { testo: titolo }, c);
  }
  return box;
}

// La testata: anello grande, cartellini e banda degli stati.
function testata(dati, titolo, genitore) {
  const box = H.crea("section", { classe: "riquadro testata-distribuzione" }, genitore);
  anello(dati.percentuale, box, { grande: true, aiuto: "La quota di schermi che stanno mostrando l'ultimo palinsesto con tutti i suoi file." });
  const destra = H.crea("div", { classe: "destra" }, box);
  H.crea("h2", { testo: titolo }, destra);
  const sotto = H.crea("p", { classe: "nota" }, destra);
  sotto.textContent = `${dati.online} di ${dati.schermi} in linea · file presenti ${peso(dati.byte_presenti)} di ${peso(dati.byte_totali)}`
    + (dati.velocita ? ` · in arrivo a ${peso(dati.velocita)}/s` : "");
  cartellini(dati, destra);
  barraStati(dati.stati, dati.schermi, destra);
  return box;
}

function miniatura(voce, cliente, genitore) {
  const vetro = H.crea("div", { classe: "vetro" }, genitore);
  if (voce?.tipo === "immagine") {
    const url = cliente ? `/api/contenuti/${voce.contenuto}/miniatura/?cliente=${cliente}` : H.conCliente(`/api/contenuti/${voce.contenuto}/miniatura/`);
    H.crea("img", { src: url, alt: voce.nome, loading: "lazy" }, vetro);
  } else {
    const icone = { video: "🎬", diretta: "📡", web: "🌐" };
    H.crea("span", { classe: "icona-vetro", testo: voce ? icone[voce.tipo] || "🖼" : "—" }, vetro);
  }
  return vetro;
}

function tesseraSchermo(s, cliente, genitore) {
  const info = STATI[s.stato];
  const t = H.crea("article", { classe: `tessera-schermo stato-${s.stato}` }, genitore);
  const cornice = H.crea("div", {
    classe: `cornice ${s.orientamento === "verticale" ? "verticale" : ""}`,
    "data-aiuto": s.in_onda.length ? "Cosa sta mostrando adesso lo schermo (riferito dal player meno di un minuto fa)." : "Niente da mostrare adesso: schermo spento, fuori orario o senza contenuti in onda.",
  }, t);
  const inOnda = s.in_onda.find((v) => !v.riserva) || s.in_onda[0];
  miniatura(inOnda, cliente, cornice);
  if (s.riposo) H.crea("span", { classe: "riposo", testo: "😴 fuori orario" }, cornice);
  H.crea("span", { classe: `led ${s.online ? "acceso" : ""}` }, cornice);

  const corpo = H.crea("div", { classe: "corpo" }, t);
  const testa = H.crea("div", { classe: "testa" }, corpo);
  H.crea("strong", { testo: s.nome }, testa);
  H.crea("span", { classe: `chip stato-${s.stato}`, testo: `${info.icona} ${info.testo}`, "data-aiuto": info.aiuto }, testa);

  const percentuale = s.percentuale ?? 0;
  barra(percentuale, corpo, {
    classe: s.stato === "scaricamento" ? "animata" : s.stato === "aggiornato" || s.stato === "pronto" ? "completa" : "",
    aiuto: "I file del palinsesto attuale già sullo schermo (in byte).",
  });
  const cifre = H.crea("div", { classe: "cifre" }, corpo);
  if (s.file_presenti == null) cifre.textContent = `${s.file_totali} file · ${peso(s.byte_totali)} da ricevere`;
  else cifre.textContent = `${s.file_presenti}/${s.file_totali} file · ${peso(s.byte_presenti)} di ${peso(s.byte_totali)} · ${percentuale}%`;

  if (s.in_corso) {
    const r = H.crea("div", { classe: "in-corso", "data-aiuto": "Il file che lo schermo sta scaricando adesso e la velocità media." }, corpo);
    H.crea("span", { classe: "nome", testo: `⇣ ${s.in_corso.nome || "file"}` }, r);
    H.crea("span", { testo: `${s.in_corso.percentuale}%${s.velocita ? ` · ${peso(s.velocita)}/s` : ""}` }, r);
    barra(s.in_corso.percentuale, corpo, { classe: "sottile animata" });
  }
  if (s.stato === "fascia" && s.fascia) H.crea("div", { classe: "nota", testo: `Scarica dalle ${s.fascia.dalle} alle ${s.fascia.alle}${s.fascia.kbps ? `, al massimo ${s.fascia.kbps} KB/s` : ""}.` }, corpo);
  if (s.falliti) H.crea("div", { classe: "nota errore", testo: `${s.falliti} file non arrivati all'ultimo tentativo: riprova da solo.` }, corpo);

  for (const v of s.in_onda.slice(0, 2)) {
    const r = H.crea("div", { classe: "in-onda", "data-aiuto": "In onda adesso: contenuto, promozione e campagna (e da che ora)." }, corpo);
    const punto = H.crea("span", { classe: "punto" }, r);
    if (v.colore) punto.style.background = v.colore;
    H.crea("span", { classe: "nome", testo: v.evento ? `⚡ ${v.evento}: ${v.nome}` : v.riserva ? `Default: ${v.nome}` : v.nome }, r);
    if (v.promozione) H.crea("span", { classe: "tenue", testo: `${v.promozione}${v.campagna ? ` · ${v.campagna}` : ""}` }, r);
    if (v.da) H.crea("span", { classe: "tenue", testo: `dalle ${ora(v.da)}` }, r);
  }
  const piede = H.crea("div", { classe: "piede" }, corpo);
  piede.textContent = `Ultimo segnale ${fa(s.ultimo_contatto)}`;
  return t;
}

// Le promozioni: su quanti schermi sono arrivate tutte le immagini.
function sezionePromozioni(promozioni, genitore) {
  if (!promozioni.length) return;
  const box = H.sezione("📦 Promozioni: dove sono arrivate", genitore);
  H.crea("p", { classe: "nota", testo: "Per ogni promozione pubblicata, su quanti schermi destinatari sono già arrivati tutti i suoi file. Quelle non ancora complete sono in cima." }, box);
  const griglia = H.crea("div", { classe: "griglia-promozioni" }, box);
  for (const p of promozioni) {
    const c = H.crea("div", { classe: "carta-promozione", "data-aiuto": `${p.nome}: ${p.file} file (${peso(p.byte)}), completi su ${p.completi} schermi su ${p.schermi}.` }, griglia);
    c.style.borderLeftColor = p.colore || "var(--primario)";
    const testa = H.crea("div", { classe: "testa" }, c);
    H.crea("strong", { testo: p.nome }, testa);
    if (p.in_onda_su) H.crea("span", { classe: "chip stato-aggiornato", testo: `● in onda su ${p.in_onda_su}` }, testa);
    if (p.campagna) H.crea("div", { classe: "tenue", testo: `${p.campagna}${p.fino_al ? ` · fino al ${new Date(p.fino_al).toLocaleDateString("it-IT")}` : ""}` }, c);
    barra(p.percentuale, c, { classe: p.percentuale >= 100 ? "completa" : "animata" });
    H.crea("div", { classe: "cifre", testo: `Arrivata su ${p.completi} di ${p.schermi} schermi · ${p.file} file · ${peso(p.byte)}` }, c);
  }
}

// I negozi, con la griglia dei loro schermi.
function sezioneSedi(sedi, filtro, cliente, genitore) {
  for (const sede of sedi) {
    const schermi = sede.schermi.filter(filtro).sort((a, b) => ORDINE.indexOf(a.stato) - ORDINE.indexOf(b.stato) || a.nome.localeCompare(b.nome));
    if (!schermi.length) continue;
    const box = H.crea("section", { classe: "riquadro sede-distribuzione" }, genitore);
    const testa = H.crea("div", { classe: "testa-sede" }, box);
    anello(sede.percentuale, testa, { aiuto: "I file del palinsesto già arrivati agli schermi di questo negozio (in byte)." });
    const titolo = H.crea("div", {}, testa);
    H.crea("h2", { testo: `🏬 ${sede.nome}` }, titolo);
    H.crea("p", { classe: "nota", testo: `${sede.aggiornati} di ${sede.schermi.length} schermi aggiornati` }, titolo);
    const griglia = H.crea("div", { classe: "griglia-schermi" }, box);
    for (const s of schermi) tesseraSchermo(s, cliente, griglia);
  }
}

function filtri(f, genitore, ridisegna) {
  const riga = H.crea("div", { classe: "riga filtri-distribuzione" }, genitore);
  const scelte = [
    ["tutti", "Tutti", "Mostra tutti gli schermi."],
    ["da_completare", "Da completare", "Solo gli schermi che non hanno ancora tutti i file del palinsesto attuale."],
    ["non_in_linea", "Non in linea", "Solo gli schermi spenti o scollegati."],
  ];
  for (const [chiave, testo, aiuto] of scelte) {
    crea("button", { type: "button", classe: `pillola ${f.vista === chiave ? "attiva" : ""}`, testo, "data-aiuto": aiuto, onclick: () => { f.vista = chiave; ridisegna(); } }, riga);
  }
  const cerca = H.crea("input", { type: "search", value: f.cerca, placeholder: "Cerca schermo o negozio…", "data-aiuto": "Filtra per nome dello schermo o del negozio." }, riga);
  cerca.addEventListener("input", () => { f.cerca = cerca.value; ridisegna(true); });
  return riga;
}

function crea(...a) {
  return H.crea(...a);
}

function filtroDa(f) {
  const testo = f.cerca.trim().toLowerCase();
  return (s) => (f.vista === "da_completare" ? s.stato !== "aggiornato" : f.vista === "non_in_linea" ? !s.online : true)
    && (!testo || s.nome.toLowerCase().includes(testo) || s.sede.toLowerCase().includes(testo));
}

export async function schedaDistribuzione() {
  const piattaforma = H.stato.io.di_piattaforma;
  const f = H.stato.filtroDistribuzione || (H.stato.filtroDistribuzione = { vista: "tutti", cerca: "", globale: !H.stato.cliente, aperte: new Set() });
  if (!piattaforma) f.globale = false;
  if (piattaforma && !H.stato.cliente) f.globale = true;
  const contenuto = document.getElementById("contenuto");
  const radice = crea("div", { classe: "distribuzione" }, contenuto);
  let dati = null;
  let aggiornato = null;

  const ridisegna = (soloElenco = false) => {
    if (!dati) return;
    const cerca = soloElenco ? document.activeElement : null;
    radice.replaceChildren();
    const capo = crea("div", { classe: "riga capo-distribuzione" }, radice);
    crea("span", { classe: "vivo", testo: "● dal vivo", "data-aiuto": `La pagina si aggiorna da sola ogni ${OGNI / 1000} secondi; mentre scaricano, gli schermi riferiscono ogni 10 secondi.` }, capo);
    crea("span", { classe: "tenue", testo: `aggiornata alle ${new Date(aggiornato).toLocaleTimeString("it-IT")}` }, capo);
    if (piattaforma) {
      const scelta = crea("div", { classe: "interruttore", "data-aiuto": "Tutte le aziende della piattaforma insieme, oppure solo quella scelta in alto." }, capo);
      crea("button", { type: "button", classe: `pillola ${f.globale ? "attiva" : ""}`, testo: "🌐 Tutte le aziende", onclick: () => { f.globale = true; carica(); } }, scelta);
      crea("button", {
        type: "button", classe: `pillola ${!f.globale ? "attiva" : ""}`, testo: "🏢 Azienda scelta", disabled: !H.stato.cliente,
        "data-aiuto": H.stato.cliente ? "Solo l'azienda scelta in alto." : "Scegli prima un'azienda in alto.",
        onclick: () => { f.globale = false; carica(); },
      }, scelta);
    }
    if (f.globale) disegnaGlobale(dati, f, radice, () => ridisegna());
    else {
      testata(dati, "Distribuzione contenuti", radice);
      sezionePromozioni(dati.promozioni, radice);
      filtri(f, radice, ridisegna);
      sezioneSedi(dati.sedi, filtroDa(f), null, radice);
      if (!dati.schermi) crea("p", { classe: "vuoto", testo: "Nessuno schermo in anagrafica." }, radice);
    }
    if (cerca?.type === "search") {
      const nuovo = radice.querySelector('input[type="search"]');
      nuovo?.focus();
      nuovo?.setSelectionRange(nuovo.value.length, nuovo.value.length);
    }
  };

  let timer = null;
  const carica = async () => {
    clearTimeout(timer);
    try {
      dati = await H.api("GET", f.globale ? "/api/piattaforma/distribuzione/" : "/api/distribuzione/");
      aggiornato = Date.now();
      // Mentre si scrive nella ricerca non si ridisegna sotto le dita.
      if (!(document.activeElement?.type === "search" && radice.contains(document.activeElement))) ridisegna();
    } catch (errore) {
      H.avvisa(errore.message);
    }
    // Si continua solo finché la scheda è aperta.
    if (radice.isConnected && H.stato.scheda === "distribuzione") timer = setTimeout(carica, OGNI);
  };
  await carica();
}

// Il SystemAdministrator: tutte le aziende, ognuna con la sua barra; un clic apre i suoi negozi.
function disegnaGlobale(dati, f, genitore, ridisegna) {
  testata(dati, "Distribuzione contenuti · tutta la piattaforma", genitore);
  filtri(f, genitore, ridisegna);
  const filtro = filtroDa(f);
  const box = H.sezione("🏢 Aziende", genitore);
  H.crea("p", { classe: "nota", testo: "Una riga per azienda: quota di schermi aggiornati, schermi per stato e byte arrivati. Clic su un'azienda per vedere negozi, schermi e promozioni." }, box);
  for (const a of dati.aziende) {
    const schermi = a.sedi.flatMap((s) => s.schermi).filter(filtro);
    if (f.vista !== "tutti" || f.cerca.trim()) {
      if (!schermi.length) continue;
    }
    const aperta = f.aperte.has(a.id);
    const riga = crea("div", { classe: `azienda-distribuzione ${aperta ? "aperta" : ""}` }, box);
    const testa = crea("button", {
      type: "button", classe: "testa-azienda", "data-aiuto": aperta ? "Chiudi il dettaglio dell'azienda." : "Apri negozi, schermi e promozioni di questa azienda.",
      onclick: () => { aperta ? f.aperte.delete(a.id) : f.aperte.add(a.id); ridisegna(); },
    }, riga);
    anello(a.percentuale, testa);
    const centro = crea("div", { classe: "centro" }, testa);
    crea("strong", { testo: a.nome }, centro);
    crea("span", { classe: "tenue", testo: `${a.stati.aggiornato}/${a.schermi} aggiornati · ${a.online} in linea · ${peso(a.byte_presenti)} di ${peso(a.byte_totali)}${a.velocita ? ` · ⇣ ${peso(a.velocita)}/s` : ""}` }, centro);
    barraStati(a.stati, a.schermi, centro);
    crea("span", { classe: "freccia", testo: aperta ? "▾" : "▸" }, testa);
    if (!aperta) continue;
    const dettaglio = crea("div", { classe: "dettaglio-azienda" }, riga);
    sezionePromozioni(a.promozioni, dettaglio);
    sezioneSedi(a.sedi, filtro, a.id, dettaglio);
    if (!a.schermi) crea("p", { classe: "vuoto", testo: "Nessuno schermo in anagrafica." }, dettaglio);
  }
  if (!dati.aziende.length) crea("p", { classe: "vuoto", testo: "Nessuna azienda attiva." }, box);
}
