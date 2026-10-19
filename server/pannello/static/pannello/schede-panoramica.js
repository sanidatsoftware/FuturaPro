// «Panoramica»: la pagina iniziale. In cima le cose da guardare (schermi spenti, download che non
// riescono, promozioni che finiscono senza seguito, plugin in errore, spazio), poi una scheda per
// argomento con i numeri essenziali e il collegamento alla pagina di dettaglio. Il
// SystemAdministrator vede anche tutte le aziende, prima quelle con qualcosa che non va.
// Si aggiorna da sola ogni 30 secondi. I testi dei dati passano da textContent.

import { STATI, anello, barra, barraStati, peso } from "./schede-distribuzione.js";

let H = null;

export function preparaSchedePanoramica(strumenti) {
  H = strumenti;
}

const OGNI = 30_000;
const NOMI_PLUGIN = { prezzo: "Info Prezzo", ingredienti: "Info Ingredienti" };
const data = (d) => (d ? new Date(d).toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" }) : "");
const ora = (t) => new Date(t).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

function saluto(nome) {
  const h = new Date().getHours();
  return `${h < 13 ? "Buongiorno" : h < 18 ? "Buon pomeriggio" : "Buonasera"}${nome ? `, ${nome}` : ""}`;
}

const quanti = (n, uno, tanti) => `${n} ${n === 1 ? uno : tanti}`;

// La legenda dei colori della barra degli stati (solo gli stati presenti).
function legenda(stati, genitore) {
  const box = H.crea("div", { classe: "legenda-stati" }, genitore);
  for (const [chiave, n] of Object.entries(stati)) {
    if (!n) continue;
    const voce = H.crea("span", { classe: `stato-${chiave}`, "data-aiuto": STATI[chiave].aiuto }, box);
    H.crea("i", {}, voce);
    voce.append(`${STATI[chiave].testo} ${n}`);
  }
}

// Una scheda della griglia: titolo, contenuto e «Apri …» verso la pagina di dettaglio.
function carta(genitore, titolo, scheda, testoApri, aiuto) {
  const c = H.crea("section", { classe: "carta-panoramica", "data-aiuto": aiuto }, genitore);
  const testa = H.crea("div", { classe: "testa" }, c);
  H.crea("h3", { testo: titolo }, testa);
  if (scheda) H.crea("button", { type: "button", classe: "apri", testo: `${testoApri} →`, "data-aiuto": `Apri «${testoApri}».`, onclick: () => apri(scheda) }, testa);
  return H.crea("div", { classe: "corpo" }, c);
}

function apri(scheda) {
  if (scheda === "palinsesto") location.href = H.conCliente("/palinsesto/");
  else H.mostra(scheda);
}

function vuoto(genitore, testo) {
  H.crea("p", { classe: "tenue vuoto-carta", testo }, genitore);
}

// Le cose da guardare: rosse le critiche, gialle quelle da tenere d'occhio; un clic apre la pagina giusta.
function avvisi(lista, genitore) {
  const box = H.crea("section", { classe: `avvisi-panoramica ${lista.length ? "" : "tutto-ok"}` }, genitore);
  if (!lista.length) {
    H.crea("span", { classe: "icona", testo: "✓" }, box);
    H.crea("strong", { testo: "Tutto in ordine: niente da guardare." }, box);
    return;
  }
  H.crea("strong", { classe: "titolo", testo: `Da guardare (${lista.length})` }, box);
  const elenco = H.crea("div", { classe: "elenco" }, box);
  for (const a of lista.slice(0, 8)) {
    H.crea("button", {
      type: "button", classe: `avviso ${a.livello}`, "data-aiuto": "Apri la pagina dove si sistema.",
      testo: `${a.livello === "critico" ? "⛔" : "⚠"} ${a.testo}`, onclick: () => apri(a.scheda),
    }, elenco);
  }
  if (lista.length > 8) H.crea("span", { classe: "tenue", testo: `e altri ${lista.length - 8}` }, elenco);
}

function disegnaAzienda(d, radice) {
  const { crea } = H;
  avvisi(d.avvisi, radice);
  const griglia = crea("div", { classe: "griglia-panoramica" }, radice);

  // Schermi.
  const s = d.schermi;
  const cs = carta(griglia, "🖥 Schermi", "stato", "Stato", "Quanti schermi sono in linea; quelli spenti o scollegati, e da quanto.");
  const rigaS = crea("div", { classe: "riga-anello" }, cs);
  anello(s.totale ? Math.round((s.online * 100) / s.totale) : null, rigaS, { aiuto: "La quota di schermi in linea." });
  const numS = crea("div", {}, rigaS);
  crea("strong", { classe: "numero", testo: `${s.online}/${s.totale}` }, numS);
  crea("div", { classe: "tenue", testo: `in linea${s.riposo ? ` · ${s.riposo} fuori orario` : ""}${s.in_allarme ? ` · ${s.in_allarme} in allarme` : ""}` }, numS);
  if (s.spenti.length) {
    const l = crea("ul", { classe: "lista-panoramica" }, cs);
    for (const x of s.spenti) {
      const li = crea("li", {}, l);
      crea("span", { classe: "punto critico" }, li);
      crea("span", { testo: `${x.nome} · ${x.sede}` }, li);
      crea("span", { classe: "tenue", testo: x.da }, li);
    }
  } else if (s.totale) vuoto(cs, "Nessuno schermo spento.");
  else vuoto(cs, "Nessuno schermo in anagrafica.");

  // Contenuti (distribuzione).
  const di = d.distribuzione;
  const cd = carta(griglia, "⇣ Contenuti sugli schermi", "distribuzione", "Distribuzione", "Quanti schermi hanno già tutti i file del palinsesto attuale, e le promozioni non ancora arrivate dappertutto.");
  const rigaD = crea("div", { classe: "riga-anello" }, cd);
  anello(di.schermi ? di.percentuale : null, rigaD, { aiuto: "La quota di schermi aggiornati." });
  const numD = crea("div", {}, rigaD);
  crea("strong", { classe: "numero", testo: `${di.stati.aggiornato}/${di.schermi}` }, numD);
  crea("div", { classe: "tenue", testo: `aggiornati${di.velocita ? ` · in arrivo a ${peso(di.velocita)}/s` : ""}` }, numD);
  if (di.schermi) {
    barraStati(di.stati, di.schermi, cd);
    legenda(di.stati, cd);
  }
  if (di.incomplete.length) {
    crea("div", { classe: "sottotitolo", testo: "Promozioni non ancora arrivate dappertutto" }, cd);
    for (const p of di.incomplete) {
      const r = crea("div", { classe: "promo-barra" }, cd);
      crea("span", { testo: `${p.nome} · ${p.completi}/${p.schermi}` }, r);
      barra(p.percentuale, r, { classe: "animata" });
    }
  }

  // Palinsesto.
  const pa = d.palinsesto;
  const cp = carta(griglia, "📅 Palinsesto", "palinsesto", "Palinsesto", "Le promozioni in onda adesso, quelle che partono nei prossimi 7 giorni e quelle che finiscono nei prossimi 3.");
  const blocco = (titolo, voci, testo, classe) => {
    crea("div", { classe: "sottotitolo", testo: titolo }, cp);
    if (!voci.length) { vuoto(cp, "—"); return; }
    const l = crea("ul", { classe: "lista-panoramica" }, cp);
    for (const v of voci) {
      const li = crea("li", {}, l);
      const punto = crea("span", { classe: `punto ${classe || ""}` }, li);
      if (v.colore) punto.style.background = v.colore;
      crea("span", { testo: v.nome }, li);
      crea("span", { classe: "tenue", testo: testo(v) }, li);
    }
  };
  blocco("In onda adesso", pa.in_onda, (v) => `su ${v.in_onda_su} schermi`);
  blocco("Partono nei prossimi 7 giorni", pa.partenza, (v) => `dal ${data(v.dal)}`);
  blocco("Finiscono nei prossimi 3 giorni", pa.scadenza, (v) => `fino al ${data(v.al)}`);

  // Code.
  const cc = carta(griglia, "🎫 Code di oggi", "attese", "Attese", "Biglietti emessi e chiamati oggi per reparto, quanti sono ancora in coda e l'attesa media.");
  if (!d.code.length) vuoto(cc, "Nessun biglietto oggi.");
  else {
    const t = crea("table", { classe: "tabella-panoramica" }, cc);
    const intest = crea("tr", {}, crea("thead", {}, t));
    for (const x of ["Reparto", "Biglietti", "In coda", "Attesa media"]) crea("th", { testo: x }, intest);
    const corpo = crea("tbody", {}, t);
    for (const r of d.code) {
      const riga = crea("tr", {}, corpo);
      const nome = crea("td", {}, riga);
      const punto = crea("span", { classe: "punto" }, nome);
      punto.style.background = r.colore;
      nome.append(` ${r.reparto}`);
      crea("td", { testo: String(r.emessi) }, riga);
      crea("td", { testo: String(r.in_coda) }, riga);
      crea("td", { testo: r.attesa_media === null ? "—" : `${r.attesa_media.toLocaleString("it-IT")} min` }, riga);
    }
  }

  // Plugin (solo se ce ne sono).
  if (d.plugin.length) {
    const cg = carta(griglia, "🔎 Plugin", null, "", "Le copie dei file di Info Prezzo e Info Ingredienti sul Totem Master e l'esito dell'ultima prova di accesso.");
    const l = crea("ul", { classe: "lista-panoramica" }, cg);
    for (const p of d.plugin) {
      const li = crea("li", { classe: "cliccabile", onclick: () => apri(`info_${p.tipo}`), "data-aiuto": "Apri le impostazioni del plugin." }, l);
      const stato = p.errore || p.prova === "errore" ? "critico" : p.copiato ? "ok" : "attesa";
      crea("span", { classe: `punto ${stato}` }, li);
      crea("span", { testo: `${NOMI_PLUGIN[p.tipo]} · ${p.sede}` }, li);
      crea("span", { classe: "tenue", testo: p.errore ? "copia non riuscita" : p.copiato ? `copiato ${ora(p.copiato)}` : "non ancora copiato" }, li);
    }
  }

  // Spazio.
  const sp = d.spazio;
  const csp = carta(griglia, "💾 Spazio", null, "", "Lo spazio usato dalle immagini e dai video dell'azienda rispetto a quello disponibile.");
  crea("strong", { classe: "numero", testo: `${sp.percentuale}%` }, csp);
  barra(sp.percentuale, csp, { classe: sp.percentuale >= 90 ? "piena" : "completa" });
  crea("div", { classe: "tenue", testo: `${peso(sp.occupato)} di ${peso(sp.disponibile)}` }, csp);

  // Ultime operazioni (chi gestisce).
  if (d.registro.length) {
    const cr = carta(griglia, "🕑 Ultime operazioni", "registro", "Registro", "Le ultime modifiche fatte nel pannello: chi e quando.");
    const l = crea("ul", { classe: "lista-panoramica registro" }, cr);
    for (const e of d.registro) {
      const li = crea("li", {}, l);
      crea("span", { testo: `${e.azione.charAt(0).toUpperCase()}${e.azione.slice(1).replaceAll("_", " ")}${e.nome ? ` · ${e.nome}` : ""}` }, li);
      crea("span", { classe: "tenue", testo: `${e.utente} · ${ora(e.quando)}` }, li);
    }
  }
}

// Tutta la piattaforma: i totali e una riga per azienda (prima quelle con avvisi critici).
function disegnaPiattaforma(d, radice) {
  const { crea } = H;
  const t = d.totali;
  const box = crea("div", { classe: "cartellini" }, radice);
  for (const [titolo, numero, stato, aiuto] of [
    ["Aziende", t.aziende, "", "Le aziende attive."],
    ["Schermi in linea", `${t.online}/${t.schermi}`, "aggiornato", "Schermi in linea su quelli in anagrafica, in tutte le aziende."],
    ["Aggiornati", `${t.aggiornati}/${t.schermi}`, "scaricamento", "Schermi con tutti i file del palinsesto attuale."],
    ["Critici", t.critici, "errore", "Avvisi critici (es. schermi spenti)."],
    ["Da tenere d'occhio", t.attenzione, "fascia", "Avvisi meno urgenti (download, plugin, palinsesto in scadenza, spazio)."],
    ["Biglietti oggi", t.biglietti, "", "Biglietti delle code emessi oggi in tutte le aziende."],
  ]) {
    const c = crea("div", { classe: `cartellino ${stato ? `stato-${stato}` : ""}`, "data-aiuto": aiuto }, box);
    crea("strong", { testo: String(numero) }, c);
    crea("span", { testo: titolo }, c);
  }
  const elenco = H.sezione("🏢 Aziende", radice);
  crea("p", { classe: "nota", testo: "Prima le aziende con qualcosa che non va. «Apri» sceglie l'azienda e mostra la sua Panoramica." }, elenco);
  const stati = {};
  for (const a of d.aziende) for (const [k, n] of Object.entries(a.distribuzione.stati)) stati[k] = (stati[k] || 0) + n;
  legenda(stati, elenco);
  for (const a of d.aziende) {
    const riga = crea("div", { classe: "azienda-panoramica" }, elenco);
    const critici = a.avvisi.filter((v) => v.livello === "critico").length;
    crea("span", { classe: `semaforo ${critici ? "critico" : a.avvisi.length ? "attenzione" : "ok"}`, "data-aiuto": critici ? "Ci sono avvisi critici." : a.avvisi.length ? "Qualcosa da tenere d'occhio." : "Tutto in ordine." }, riga);
    const centro = crea("div", { classe: "centro" }, riga);
    crea("strong", { testo: a.nome }, centro);
    crea("span", {
      classe: "tenue",
      testo: `${a.schermi.online}/${a.schermi.totale} in linea · ${a.distribuzione.stati.aggiornato}/${a.schermi.totale} aggiornati · ${quanti(a.in_onda, "promozione in onda", "promozioni in onda")}${a.scadenza ? ` · ${a.scadenza} in scadenza` : ""} · ${quanti(a.biglietti, "biglietto oggi", "biglietti oggi")} · spazio ${a.spazio.percentuale}%`,
    }, centro);
    if (a.schermi.totale) barraStati(a.distribuzione.stati, a.schermi.totale, centro);
    if (a.avvisi.length) {
      const l = crea("div", { classe: "avvisi-riga" }, centro);
      for (const v of a.avvisi.slice(0, 3)) crea("span", { classe: `avviso ${v.livello}`, testo: `${v.livello === "critico" ? "⛔" : "⚠"} ${v.testo}` }, l);
      if (a.avvisi.length > 3) crea("span", { classe: "tenue", testo: `e altri ${a.avvisi.length - 3}` }, l);
    }
    crea("button", {
      type: "button", classe: "primario", testo: "Apri", "data-aiuto": "Sceglie questa azienda e mostra la sua Panoramica.",
      onclick: () => { const scelta = document.getElementById("cliente"); scelta.value = a.id; scelta.dispatchEvent(new Event("change")); },
    }, riga);
  }
  if (!d.aziende.length) crea("p", { classe: "vuoto", testo: "Nessuna azienda attiva." }, elenco);
}

export async function schedaPanoramica() {
  const piattaforma = H.stato.io.di_piattaforma;
  const contenuto = document.getElementById("contenuto");
  const radice = H.crea("div", { classe: "distribuzione panoramica" }, contenuto);
  const f = H.stato.filtroPanoramica || (H.stato.filtroPanoramica = { globale: true });
  let timer = null;

  const carica = async () => {
    clearTimeout(timer);
    const globale = piattaforma && (f.globale || !H.stato.cliente);
    try {
      const d = await H.api("GET", globale ? "/api/piattaforma/panoramica/" : "/api/panoramica/");
      radice.replaceChildren();
      const capo = H.crea("div", { classe: "capo-panoramica" }, radice);
      const titoli = H.crea("div", {}, capo);
      H.crea("h1", { testo: saluto(H.stato.io.first_name || H.stato.io.username) }, titoli);
      const azienda = H.stato.clienti?.find((c) => c.id === H.stato.cliente)?.nome;
      H.crea("p", {
        classe: "tenue",
        testo: `${new Date().toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long", year: "numeric" })} · ${globale ? "tutta la piattaforma" : azienda || "la tua azienda"} · aggiornata alle ${new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`,
      }, titoli);
      H.crea("button", { type: "button", testo: "⟳ Aggiorna", "data-aiuto": "Aggiorna subito, senza aspettare i 30 secondi.", onclick: () => carica() }, titoli);
      if (piattaforma) {
        const scelta = H.crea("div", { classe: "interruttore", "data-aiuto": "Tutte le aziende della piattaforma insieme, oppure solo quella scelta in alto." }, capo);
        H.crea("button", { type: "button", classe: `pillola ${globale ? "attiva" : ""}`, testo: "🌐 Tutte le aziende", onclick: () => { f.globale = true; carica(); } }, scelta);
        H.crea("button", {
          type: "button", classe: `pillola ${!globale ? "attiva" : ""}`, testo: "🏢 Azienda scelta", disabled: !H.stato.cliente,
          "data-aiuto": H.stato.cliente ? "Solo l'azienda scelta in alto." : "Scegli prima un'azienda in alto.",
          onclick: () => { f.globale = false; carica(); },
        }, scelta);
      }
      if (globale) disegnaPiattaforma(d, radice);
      else disegnaAzienda(d, radice);
    } catch (errore) {
      H.avvisa(errore.message);
    }
    if (radice.isConnected && H.stato.scheda === "panoramica") timer = setTimeout(carica, OGNI);
  };
  // Scegliendo un'azienda in alto si guarda quella.
  if (piattaforma && H.stato.cliente && f.ultimoCliente !== H.stato.cliente) f.globale = false;
  f.ultimoCliente = H.stato.cliente;
  await carica();
}
