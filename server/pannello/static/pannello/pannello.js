// Il pannello di FuturaPro: una pagina sola sulle API del server.
// Ogni testo che arriva dai dati passa da textContent, mai da innerHTML.

import { attivaAiuti } from "./aiuto.js";
import { VOCI, clienteRicordato, disegnaMenu, ricordaCliente } from "./menu.js";
import { preparaSchedeImpostazioni, schedaEmail } from "./schede-impostazioni.js";
import { preparaSchedePlugin, schedaInfoIngredienti, schedaInfoPrezzo } from "./schede-plugin.js";
import { preparaSchedeTicket, schedaLayoutTicket } from "./schede-ticket.js";
import { osservaAiuti } from "./aiuti-campi.js";
import { apriRiquadro, paginaIncorporata } from "./riquadro.js";
import { preparaSchedeReport, schedaRegistro, schedaStoricoAllarmi } from "./schede-report.js";
import { preparaSchedeCode, schedaAttese, schedaTelefono } from "./schede-code.js";
import { preparaSchedeContenuti, schedaListini, schedaMessaInOnda } from "./schede-contenuti.js";
import { preparaSchedeSchermi, schedaAccensione, schedaDownload, schedaStampanti, schedaStato } from "./schede-schermi.js";

const stato = { io: null, cliente: null, clienti: [], scheda: null };

// --- Strumenti -------------------------------------------------------------------

function cookie(nome) {
  const trovato = document.cookie.split("; ").find((c) => c.startsWith(`${nome}=`));
  return trovato ? decodeURIComponent(trovato.split("=")[1]) : "";
}

async function api(metodo, url, dati) {
  const intestazioni = { "X-CSRFToken": cookie("csrftoken") };
  if (stato.cliente && !url.startsWith("/api/piattaforma/")) intestazioni["X-Cliente"] = stato.cliente;
  let corpo;
  if (dati instanceof FormData) corpo = dati;
  else if (dati !== undefined) {
    corpo = JSON.stringify(dati);
    intestazioni["Content-Type"] = "application/json";
  }
  const risposta = await fetch(url, { method: metodo, headers: intestazioni, body: corpo, credentials: "same-origin" });
  const contenuto = risposta.status === 204 ? null : await risposta.json().catch(() => null);
  if (!risposta.ok) throw Object.assign(new Error(spiega(contenuto) || `Errore ${risposta.status}`), { stato: risposta.status });
  return contenuto;
}

const elenco = async (url) => (await api("GET", url)).results;

// Tutte le pagine di un elenco lungo (la libreria può superare le 100 voci).
async function tutteLePagine(url) {
  const risultati = [];
  for (let prossima = url; prossima; ) {
    const pagina = await api("GET", prossima);
    risultati.push(...pagina.results);
    prossima = pagina.next ? new URL(pagina.next).pathname + new URL(pagina.next).search : null;
  }
  return risultati;
}

// Gli errori di validazione del server, in una riga leggibile.
function spiega(corpo) {
  if (!corpo) return "";
  if (typeof corpo === "string") return corpo;
  if (Array.isArray(corpo)) return corpo.map(spiega).join(" ");
  return Object.entries(corpo)
    .map(([campo, v]) => (["detail", "non_field_errors"].includes(campo) ? spiega(v) : `${campo}: ${spiega(v)}`))
    .join(" · ");
}

function crea(tag, attributi = {}, genitore = null) {
  const el = document.createElement(tag);
  for (const [chiave, valore] of Object.entries(attributi)) {
    if (chiave === "testo") el.textContent = valore;
    else if (chiave === "classe") el.className = valore;
    else if (chiave.startsWith("on")) el.addEventListener(chiave.slice(2), valore);
    else if (chiave in el) el[chiave] = valore;
    else el.setAttribute(chiave, valore);
  }
  if (genitore) genitore.appendChild(el);
  return el;
}

function avvisa(testo, tipo = "errore") {
  const box = document.getElementById("messaggio");
  box.hidden = !testo;
  box.className = `messaggio ${tipo}`;
  box.textContent = testo || "";
  if (testo && tipo === "ok") setTimeout(() => (box.hidden = true), 4000);
}

// Esegue un'operazione, mostra l'esito e ridisegna la scheda.
async function prova(operazione, conferma) {
  try {
    await operazione();
    if (conferma) avvisa(conferma, "ok");
    await mostra(stato.scheda);
  } catch (errore) {
    avvisa(errore.message);
  }
}

function sezione(titolo, genitore = contenuto) {
  const s = crea("section", { classe: "riquadro" }, genitore);
  if (titolo) crea("h2", { testo: titolo }, s);
  return s;
}

function campo(etichetta, controllo, genitore) {
  const l = crea("label", { classe: "campo" }, genitore);
  crea("span", { testo: etichetta }, l);
  l.appendChild(controllo);
  return controllo;
}

function scelta(opzioni, valore) {
  const s = crea("select");
  for (const [v, t] of opzioni) crea("option", { value: v, testo: t, selected: String(v) === String(valore) }, s);
  return s;
}

function spunte(opzioni, scelti, genitore) {
  const box = crea("div", { classe: "spunte" }, genitore);
  const valori = new Set(scelti);
  for (const [v, t] of opzioni) {
    const l = crea("label", {}, box);
    crea("input", { type: "checkbox", checked: valori.has(v), onchange: (e) => (e.target.checked ? valori.add(v) : valori.delete(v)) }, l);
    l.append(` ${t}`);
  }
  return () => [...valori];
}

function tabella(intestazioni, genitore) {
  const t = crea("table", {}, genitore);
  const riga = crea("tr", {}, crea("thead", {}, t));
  for (const testo of intestazioni) crea("th", { testo }, riga);
  return crea("tbody", {}, t);
}

const ruoloGestione = () => ["admin_assoluto", "admin_cliente"].includes(stato.io.ruolo);
const conCliente = (url) => (stato.cliente ? `${url}${url.includes("?") ? "&" : "?"}cliente=${stato.cliente}` : url);
const contenuto = document.getElementById("contenuto");

// --- Schede --------------------------------------------------------------------------

// Le schede del pannello; titoli, visibilità e spiegazioni sono in menu.js.
const SCHEDE = {
  clienti: schedaClienti,
  monitor: schedaMonitor,
  accensione: schedaAccensione,
  stato: schedaStato,
  download: schedaDownload,
  stampanti: schedaStampanti,
  layout_ticket: schedaLayoutTicket,
  info_prezzo: schedaInfoPrezzo,
  info_ingredienti: schedaInfoIngredienti,
  listini: schedaListini,
  messa_in_onda: schedaMessaInOnda,
  email: schedaEmail,
  registro: schedaRegistro,
  storico_allarmi: schedaStoricoAllarmi,
  attese: schedaAttese,
  telefono: schedaTelefono,
  reparti: schedaReparti,
  sedi: schedaSedi,
  utenti: schedaUtenti,
  aspetto: schedaAspetto,
  // Pagine a sé (editor dei layout, banco) mostrate dentro il pannello, sotto il menu.
  layout: () => paginaIncorporata(contenuto, conCliente("/editor/"), "Layout Video"),
  banco: () => paginaIncorporata(contenuto, conCliente("/banco/"), "Banchi Code"),
};

function disegnaSchede() {
  disegnaMenu(document.getElementById("schede"), { io: stato.io, attiva: stato.scheda, cliente: stato.cliente, mostra });
}

async function mostra(chiave) {
  const voce = VOCI.find((v) => v.chiave === chiave && v.visibile(stato.io) && SCHEDE[v.chiave]);
  if (!voce) return;
  stato.scheda = chiave;
  // La scheda resta nell'indirizzo: ricaricando, o tornando dal palinsesto, si riapre.
  history.replaceState(null, "", `${location.pathname}${location.search}#${chiave}`);
  disegnaSchede();
  contenuto.replaceChildren();
  contenuto.classList.remove("pieno");
  if (voce.serveCliente !== false && stato.io.di_piattaforma && !stato.cliente) {
    crea("p", { classe: "vuoto", testo: "Scegli il cliente in alto." }, contenuto);
    return;
  }
  try {
    await SCHEDE[chiave]();
  } catch (errore) {
    avvisa(errore.message);
  }
}

// --- Clienti (solo SystemAdministrator) ----------------------------------------------

async function schedaClienti() {
  const nuovo = sezione("Nuovo cliente");
  const nome = campo("Nome", crea("input", { required: true }), nuovo);
  const ragione = campo("Ragione sociale", crea("input"), nuovo);
  const piva = campo("Partita IVA", crea("input"), nuovo);
  crea("h3", { testo: "Primo Administrator" }, nuovo);
  const utente = campo("Nome utente", crea("input"), nuovo);
  const password = campo("Password (almeno 10 caratteri)", crea("input", { type: "password", autocomplete: "new-password" }), nuovo);
  crea("button", {
    classe: "primario", testo: "Crea cliente",
    onclick: () => prova(async () => {
      const cliente = await api("POST", "/api/piattaforma/clienti/", { nome: nome.value, ragione_sociale: ragione.value, partita_iva: piva.value });
      if (utente.value) {
        const precedente = stato.cliente;
        stato.cliente = cliente.id;
        try {
          await api("POST", "/api/utenti/", { username: utente.value, password: password.value, ruolo: "admin_cliente" });
        } finally {
          stato.cliente = precedente;
        }
      }
      await caricaClienti();
    }, "Cliente creato."),
  }, nuovo);

  const tutti = sezione("Clienti");
  const corpo = tabella(["Nome", "Attivo", "Abilitazioni", ""], tutti);
  for (const c of stato.clienti) {
    const riga = crea("tr", {}, corpo);
    crea("td", { testo: c.nome }, riga);
    const attivo = crea("input", { type: "checkbox", checked: c.attivo }, crea("td", {}, riga));
    attivo.addEventListener("change", () => prova(() => api("PATCH", `/api/piattaforma/clienti/${c.id}/`, { attivo: attivo.checked }), "Salvato."));
    const cella = crea("td", {}, riga);
    crea("button", { testo: "Modifica", onclick: () => abilitazioni(c, cella) }, cella);
    crea("button", { testo: "Apri", onclick: () => scegliCliente(c.id, "monitor") }, crea("td", {}, riga));
  }
}

async function abilitazioni(cliente, cella) {
  const precedente = stato.cliente;
  stato.cliente = cliente.id;
  try {
    const a = await api("GET", "/api/abilitazioni/");
    cella.replaceChildren();
    const box = crea("div", { classe: "riquadro-interno" }, cella);
    const numeri = Object.fromEntries(
      [["max_monitor", "Monitor max"], ["max_utenti", "Utenti max"], ["spazio_mb", "Spazio (MB)"]].map(([k, t]) => [k, campo(t, crea("input", { type: "number", value: a[k] }), box)]),
    );
    const flag = Object.fromEntries(
      [["admin_gestisce_utenti", "L'Administrator gestisce gli utenti"], ["admin_gestisce_dispositivi", "…i monitor"], ["admin_gestisce_layout", "…i layout"], ["plugin_prezzo", "Plugin Info Prezzo"], ["plugin_ingredienti", "Plugin Info Ingredienti"]]
        .map(([k, t]) => {
          const l = crea("label", { classe: "spunta" }, box);
          const c = crea("input", { type: "checkbox", checked: a[k] }, l);
          l.append(` ${t}`);
          return [k, c];
        }),
    );
    crea("button", {
      classe: "primario", testo: "Salva",
      onclick: () => {
        stato.cliente = cliente.id;
        const dati = Object.fromEntries([...Object.entries(numeri).map(([k, c]) => [k, parseInt(c.value, 10)]), ...Object.entries(flag).map(([k, c]) => [k, c.checked])]);
        prova(() => api("PATCH", "/api/abilitazioni/", dati).finally(() => (stato.cliente = precedente)), "Abilitazioni salvate.");
      },
    }, box);
  } finally {
    stato.cliente = precedente;
  }
}

// --- Monitor ----------------------------------------------------------------------------

async function schedaMonitor() {
  const [monitor, sedi, gruppi, layout, riserve, stampanti] = await Promise.all([
    elenco("/api/monitor/"), elenco("/api/sedi/"), elenco("/api/gruppi/"), elenco("/api/layout/"), tutteLePagine("/api/contenuti/?uso=riserva"),
    elenco("/api/stampanti/").catch(() => []),
  ]);
  // Le riserve assegnate prima che si caricassero a parte (dalla libreria): restano scelte.
  const note = new Set(riserve.map((c) => c.id));
  for (const id of new Set(monitor.map((m) => m.immagine_riserva).filter((id) => id && !note.has(id)))) {
    const vecchia = await api("GET", `/api/contenuti/${id}/`).catch(() => null);
    if (vecchia) riserve.push(vecchia);
  }
  const sceltaRiserva = (orientamento, valore, alCambio) => sceltaFileRiserva(riserve, orientamento, valore, alCambio);
  const gestione = ruoloGestione();

  if (gestione) {
    const abbina = sezione("Abbina uno schermo");
    if (!sedi.length) crea("p", { classe: "nota", testo: "Prima crea una sede, in «Sedi e gruppi»." }, abbina);
    crea("p", { classe: "nota", testo: "Accendi il monitor o il totem: mostra un codice di 6 cifre. Inseriscilo qui." }, abbina);
    const riga = crea("div", { classe: "riga" }, abbina);
    const codice = campo("Codice", crea("input", { inputMode: "numeric", maxLength: 7, placeholder: "123 456" }), riga);
    const nome = campo("Nome", crea("input", { placeholder: "es. Ingresso" }), riga);
    const sede = campo("Sede", scelta(sedi.map((s) => [s.id, s.nome])), riga);
    const orientamento = campo("Tipo", scelta([["orizzontale", "Monitor orizzontale"], ["verticale", "Totem verticale"]]), riga);
    if (gruppi.length) crea("span", { classe: "etichetta", testo: "Gruppi (ricevono le pubblicazioni fatte sul gruppo)" }, abbina);
    const scegliGruppi = spunte(gruppi.map((g) => [g.id, g.nome]), [], abbina);
    crea("button", {
      classe: "primario", testo: "Abbina", "data-aiuto": "Collega lo schermo che mostra questo codice: da quel momento riceve layout e promozioni.",
      onclick: () => prova(async () => {
        const m = await api("POST", "/api/monitor/abbina/", { codice: codice.value.replace(/\s/g, ""), nome: nome.value, sede: sede.value, gruppi: scegliGruppi() });
        if (orientamento.value === "verticale") await api("PATCH", `/api/monitor/${m.id}/`, { orientamento: "verticale" });
      }, "Schermo abbinato: entro pochi secondi mostra i contenuti."),
    }, abbina);
  }

  if (gestione && monitor.length) {
    const riserva = sezione("Immagine o video di riserva");
    crea("p", {
      classe: "nota",
      testo: "Quello che mostrano le slide quando non c'è nessuna promozione in onda (es. tra un volantino e l'altro): di solito il logo del negozio o un breve video istituzionale. Si sceglie dal computer ed è conservato a parte: non compare nella libreria delle promozioni e non viene cancellato quando le promozioni scadono. Quando nessuno schermo lo usa più, sparisce dal server e dai player.",
    }, riserva);
    const riga = crea("div", { classe: "riga" }, riserva);
    const perTotem = campo("Per tutti i totem", sceltaRiserva("verticale", ""), riga);
    const perMonitor = campo("Per tutti i monitor", sceltaRiserva("orizzontale", ""), riga);
    crea("button", {
      classe: "primario", testo: "Applica a tutti",
      "data-aiuto": "Imposta la riserva scelta su tutti i totem e su tutti i monitor del cliente.",
      onclick: () => prova(async () => {
        for (const m of monitor) {
          const valore = m.orientamento === "verticale" ? perTotem.value : perMonitor.value;
          await api("PATCH", `/api/monitor/${m.id}/`, { immagine_riserva: valore || null });
        }
      }, "Riserva impostata: gli schermi la ricevono entro un minuto."),
    }, riga);
  }

  const tutti = sezione("Schermi");
  if (!monitor.length) crea("p", { classe: "vuoto", testo: "Nessuno schermo abbinato." }, tutti);
  const corpo = tabella(["Anteprima", "Nome", "Sede", "Stato", "In onda", "Gruppi", "Orientamento", "Rotazione", "Layout", "Totem: code e stampante", "Se non c'è nulla in onda", ""], tutti);
  for (const m of monitor) {
    const riga = crea("tr", {}, corpo);
    const schermo = schermoInMiniatura(m, crea("td", { classe: "cella-schermo" }, riga));
    crea("td", { testo: m.nome }, riga);
    crea("td", { testo: sedi.find((s) => s.id === m.sede)?.nome || "" }, riga);
    const statoCella = crea("td", {}, riga);
    crea("span", { classe: `pallino ${m.online ? "acceso" : "spento"}` }, statoCella);
    statoCella.append(m.online ? (m.riposo ? " A riposo (fuori orario)" : " Online") : m.ultimo_contatto ? ` Offline da ${new Date(m.ultimo_contatto).toLocaleString("it-IT")}` : " Mai collegato");
    const salva = (dati) => prova(() => api("PATCH", `/api/monitor/${m.id}/`, dati), "Salvato.");
    const orientamento = scelta([["orizzontale", "Orizzontale"], ["verticale", "Verticale (totem)"]], m.orientamento);
    const rotazione = scelta([[0, "0°"], [90, "90°"], [180, "180°"], [270, "270°"]], m.rotazione);
    const riservaDelMonitor = sceltaRiserva(m.orientamento, m.immagine_riserva || "", (valore) => salva({ immagine_riserva: valore || null }));
    const sceltaLayout = scelta(
      [["", "Predefinito"], ...layout.filter((l) => l.orientamento === m.orientamento).map((l) => [l.id, l.nome])],
      m.layout || "",
    );
    // Cosa va in onda adesso: se è vuoto, al monitor non arriva nessuna pubblicazione.
    const inOnda = crea("td", { testo: "…" }, riga);
    api("GET", `/api/anteprima/${m.id}/`).then(({ sequenza, riserva, aggiornato }) => {
      const tipoRiserva = riserve.find((c) => c.id === riserva)?.tipo || "immagine";
      schermo.primo(sequenza[0] || (riserva ? { tipo: tipoRiserva, contenuto: riserva } : null));
      inOnda.textContent = sequenza.length ? `${sequenza.length} contenut${sequenza.length === 1 ? "o" : "i"}` : riserva ? (tipoRiserva === "video" ? "Video di riserva" : "Immagine di riserva") : "Niente";
      if (!sequenza.length && !riserva) {
        inOnda.className = "attenzione";
        inOnda.title = "Nessuna pubblicazione valida adesso per questo schermo o per i suoi gruppi.";
      }
      // Il player ha segnalato un problema (es. una diretta che non parte): lo si mostra qui.
      if (m.problema) {
        crea("div", { classe: "problema-schermo", testo: `⚠ ${m.problema.testo}`, title: `Segnalato il ${new Date(m.problema.quando).toLocaleString("it-IT")}` }, inOnda);
      }
      // Online ma con un palinsesto vecchio: non ha ancora scaricato le ultime modifiche.
      if (m.online && aggiornato === false) {
        inOnda.append(m.attesa_download ? " · aspetta la fascia di download" : " · non aggiornato");
        inOnda.className = "attenzione";
        inOnda.title = m.attesa_download
          ? "Il palinsesto nuovo è arrivato: i suoi file si scaricano nella fascia di download (Schermi → Fasce di download, «Scarica adesso» per non aspettare)."
          : "Lo schermo non ha ancora ricevuto (o scaricato) l'ultimo palinsesto.";
      }
    }).catch(() => (inOnda.textContent = "?"));
    const cellaGruppi = crea("td", {}, riga);
    const gruppiScelti = new Set(m.gruppi);
    for (const g of gruppi) {
      const l = crea("label", { classe: "spunta" }, cellaGruppi);
      crea("input", {
        type: "checkbox", checked: gruppiScelti.has(g.id), disabled: !gestione,
        onchange: (e) => {
          e.target.checked ? gruppiScelti.add(g.id) : gruppiScelti.delete(g.id);
          salva({ gruppi: [...gruppiScelti] });
        },
      }, l);
      l.append(` ${g.nome}`);
    }
    if (!gruppi.length) cellaGruppi.textContent = "—";
    for (const [controllo, chiave] of [[orientamento, "orientamento"], [rotazione, "rotazione"], [sceltaLayout, "layout"]]) {
      controllo.disabled = !gestione;
      controllo.addEventListener("change", () => {
        // Cambiando orientamento il layout assegnato non vale più: si torna al predefinito.
        const dati = { [chiave]: chiave === "rotazione" ? parseInt(controllo.value, 10) : controllo.value || null };
        if (chiave === "orientamento") dati.layout = null;
        salva(dati);
      });
      crea("td", {}, riga).appendChild(controllo);
    }
    // Totem: chi detiene i turni delle code della sede (uno solo) e la stampante dei biglietti.
    const cellaTotem = crea("td", { classe: "cella-totem" }, riga);
    const etichettaMaster = crea("label", {
      classe: "spunta", "data-aiuto": "Il Totem Master (server code) detiene i turni delle code della sede: gli altri totem e i monitor prendono i numeri da lui. Uno solo per sede: sceglierne un altro toglie il segno a questo.",
    }, cellaTotem);
    crea("input", {
      type: "checkbox", checked: m.totem_master, disabled: !gestione,
      onchange: (e) => prova(() => api("PATCH", `/api/monitor/${m.id}/`, { totem_master: e.target.checked }),
        e.target.checked ? `«${m.nome}» è il Totem Master (server code) della sede.` : "Salvato."),
    }, etichettaMaster);
    etichettaMaster.append(m.totem_master ? " ★ Totem Master (server code)" : " Totem Master (server code)");
    if (m.totem_master) etichettaMaster.classList.add("master");
    const dellaSede = stampanti.filter((st) => st.sede === m.sede || st.id === m.stampante);
    const sceltaStampante = scelta([["", "— stampante dal layout —"], ...dellaSede.map((st) => [st.id, `🖨 ${st.nome}`])], m.stampante || "");
    sceltaStampante.disabled = !gestione;
    sceltaStampante.title = "La stampante dei biglietti di questo totem (Hardware · Anagrafica Stampanti Ticket).";
    sceltaStampante.addEventListener("change", () => salva({ stampante: sceltaStampante.value || null }));
    cellaTotem.appendChild(sceltaStampante);
    riservaDelMonitor.disabled = !gestione;
    crea("td", {}, riga).appendChild(riservaDelMonitor);
    const azioni = crea("td", { classe: "azioni" }, riga);
    if (gestione) {
      crea("button", {
        testo: "Rimuovi", classe: "pericolo",
        onclick: () => confirm(`Rimuovere «${m.nome}»? Lo schermo tornerà a mostrare il codice di abbinamento.`) && prova(() => api("DELETE", `/api/monitor/${m.id}/`), "Rimosso."),
      }, azioni);
    }
  }
}

// Lo schermo disegnato con il suo orientamento. Dentro, l'ultima fotografia vera di ciò che
// il monitor mostrava (con l'ora); un clic gliene chiede una nuova, scattata in quell'istante.
// Se non ce ne sono, la prima immagine in onda. Doppio clic: l'anteprima simulata a tutto schermo.
// La riserva di uno schermo: una di quelle già caricate, oppure un file nuovo dal computer.
// «alCambio» riceve l'id scelto ("" = schermo nero); senza, la scelta resta nel menu.
const CARICA = "__carica";

function sceltaFileRiserva(riserve, orientamento, valore, alCambio) {
  const voci = [...riserve].sort((a, b) => (b.orientamento === orientamento) - (a.orientamento === orientamento) || a.nome.localeCompare(b.nome));
  const menu = scelta([
    ["", "— nessuna: schermo nero —"],
    ...voci.map((c) => [c.id, `${c.tipo === "video" ? "▶ " : ""}${c.nome}${c.orientamento && c.orientamento !== orientamento ? ` (${c.orientamento})` : ""}`]),
    [CARICA, "📁 Carica dal computer…"],
  ], valore);
  menu.classList.add("riserva");
  let precedente = menu.value;
  menu.addEventListener("change", () => {
    if (menu.value !== CARICA) {
      precedente = menu.value;
      alCambio?.(menu.value);
      return;
    }
    menu.value = precedente; // finché il file non è caricato, resta la scelta di prima
    const file = crea("input", { type: "file", accept: "image/jpeg,image/png,image/gif,image/webp,video/mp4,video/webm,video/quicktime" });
    file.addEventListener("change", async () => {
      const scelto = file.files[0];
      if (!scelto) return;
      const attesa = crea("option", { value: "", testo: `Caricamento di ${scelto.name}…` });
      menu.prepend(attesa);
      menu.value = "";
      menu.disabled = true;
      try {
        const nuova = await caricaRiserva(scelto);
        riserve.push(nuova);
        const opzione = crea("option", { value: nuova.id, testo: `${nuova.tipo === "video" ? "▶ " : ""}${nuova.nome}` });
        menu.insertBefore(opzione, menu.querySelector(`option[value="${CARICA}"]`));
        menu.value = precedente = nuova.id;
        if (alCambio) alCambio(nuova.id);
        else avvisa("File caricato: premi «Applica a tutti» per usarlo.", "ok");
      } catch (errore) {
        menu.value = precedente;
        avvisa(errore.message);
      } finally {
        attesa.remove();
        menu.disabled = false;
      }
    });
    file.click();
  });
  return menu;
}

async function caricaRiserva(file) {
  const dati = new FormData();
  dati.append("file", file);
  dati.append("nome", file.name.replace(/\.[^.]+$/, ""));
  dati.append("uso", "riserva");
  // Le misure dei video le legge il browser (per le immagini le legge il server).
  if (file.type.startsWith("video/")) {
    const url = URL.createObjectURL(file);
    const misure = await new Promise((ok) => {
      const v = crea("video", { preload: "metadata", muted: true });
      v.onloadedmetadata = () => ok([v.videoWidth, v.videoHeight]);
      v.onerror = () => ok(null);
      setTimeout(() => ok(null), 10000);
      v.src = url;
    });
    URL.revokeObjectURL(url);
    if (misure?.[0]) {
      dati.append("larghezza", misure[0]);
      dati.append("altezza", misure[1]);
    }
  }
  return api("POST", "/api/contenuti/", dati);
}

function schermoInMiniatura(m, cella) {
  const verticale = m.orientamento === "verticale";
  const cornice = crea("button", {
    type: "button", classe: `mini-schermo ${verticale ? "verticale" : "orizzontale"}`,
    "data-aiuto": "Clic: il monitor fotografa il suo schermo in questo istante e la foto compare qui (pochi secondi). Doppio clic: l'anteprima simulata, in un riquadro sopra la pagina.",
  }, cella);
  const vetro = crea("div", { classe: "vetro-schermo" }, cornice);
  crea("span", { classe: "segnaposto", testo: "…" }, vetro);
  crea("span", { classe: `led-schermo ${m.online ? "acceso" : ""}` }, cornice);
  if (!verticale) crea("span", { classe: "piedistallo" }, cornice);
  const didascalia = crea("div", { classe: "ora-schermata" }, cella);
  const indirizzo = conCliente(`/anteprima/${m.id}/`);
  let fotografia = m.schermata_il;

  const mostraFoto = (quando) => {
    vetro.replaceChildren();
    crea("img", { src: conCliente(`/api/monitor/${m.id}/schermata/immagine/?t=${Date.parse(quando)}`), alt: `Schermo di ${m.nome}` }, vetro);
    const ora = new Date(quando);
    const oggi = ora.toDateString() === new Date().toDateString();
    didascalia.textContent = `📸 ${oggi ? ora.toLocaleTimeString("it-IT") : ora.toLocaleString("it-IT")}`;
    cornice.classList.add("con-foto");
  };
  if (fotografia) mostraFoto(fotografia);

  let inAttesa = false;
  cornice.addEventListener("click", async () => {
    if (inAttesa) return;
    if (!m.online) {
      didascalia.textContent = fotografia ? "Monitor non in linea: questa è l'ultima foto" : "Monitor non in linea";
      return;
    }
    inAttesa = true;
    cornice.classList.add("scatto");
    didascalia.textContent = "📸 scatto in corso…";
    try {
      await api("POST", `/api/monitor/${m.id}/schermata/`);
      // Il monitor se ne accorge entro pochi secondi; si aspetta la foto nuova (al massimo 40 s).
      for (let i = 0; i < 20; i += 1) {
        await new Promise((ok) => setTimeout(ok, 2000));
        const { quando } = await api("GET", `/api/monitor/${m.id}/schermata/`);
        if (quando && quando !== fotografia) {
          fotografia = quando;
          mostraFoto(quando);
          return;
        }
      }
      didascalia.textContent = "Nessuna risposta: il player è aggiornato? Riprova tra poco.";
    } catch (errore) {
      didascalia.textContent = errore.message;
    } finally {
      inAttesa = false;
      cornice.classList.remove("scatto");
    }
  });
  cornice.addEventListener("dblclick", () => apriRiquadro(`Anteprima · ${m.nome}`, indirizzo, { larghezza: "min(1500px, 96vw)", altezza: "min(900px, 92vh)" }));
  return {
    primo(voce) {
      if (fotografia) return;
      vetro.replaceChildren();
      if (voce && voce.tipo === "immagine") crea("img", { src: conCliente(`/api/contenuti/${voce.contenuto}/miniatura/`), alt: "" }, vetro);
      else crea("span", { classe: "segnaposto", testo: voce ? ({ video: "▶ video", diretta: "📡 diretta" }[voce.tipo] || "🌐") : "nessun contenuto" }, vetro);
      didascalia.textContent = "in onda (clic per la foto)";
    },
  };
}

// --- Reparti ----------------------------------------------------------------------------------

async function schedaReparti() {
  const [reparti, sedi, serie] = await Promise.all([elenco("/api/reparti/"), elenco("/api/sedi/"), tutteLePagine("/api/annunci/")]);
  const gestione = ruoloGestione();

  if (gestione) {
    const nuovo = sezione("Nuovo reparto");
    const riga = crea("div", { classe: "riga" }, nuovo);
    const nome = campo("Nome", crea("input", { placeholder: "es. Salumeria" }), riga);
    const sede = campo("Sede", scelta(sedi.map((s) => [s.id, s.nome])), riga);
    const colore = campo("Colore", crea("input", { type: "color", value: "#e31b23" }), riga);
    const testo = campo("Testo", crea("input", { type: "color", value: "#ffffff" }), riga);
    crea("button", {
      classe: "primario", testo: "Crea",
      onclick: () => prova(() => api("POST", "/api/reparti/", { nome: nome.value, sede: sede.value, colore: colore.value, colore_testo: testo.value, ordine: reparti.length }), "Reparto creato."),
    }, nuovo);
  }

  const tutti = sezione("Reparti");
  crea("p", { classe: "nota", testo: "Numeri da 0 a 99; la coda riparte ogni giorno. Il collegamento per bilancia o pulsantiera si apre una volta sul dispositivo, che lo ricorda." }, tutti);
  const corpo = tabella(["Nome", "Sede", "Colori", "Ordine", "Attivo", "Ora", "Annunci (mp3)", "Bilancia / pulsantiera", ""], tutti);
  for (const r of reparti) {
    const riga = crea("tr", {}, corpo);
    const nome = crea("input", { value: r.nome, disabled: !gestione }, crea("td", {}, riga));
    crea("td", { testo: sedi.find((s) => s.id === r.sede)?.nome || "" }, riga);
    const colori = crea("td", {}, riga);
    const colore = crea("input", { type: "color", value: r.colore, disabled: !gestione, title: "Fondo" }, colori);
    const testo = crea("input", { type: "color", value: r.colore_testo, disabled: !gestione, title: "Testo" }, colori);
    const ordine = crea("input", { type: "number", value: r.ordine, min: 0, disabled: !gestione, classe: "corto" }, crea("td", {}, riga));
    const attivo = crea("input", { type: "checkbox", checked: r.attivo, disabled: !gestione }, crea("td", {}, riga));
    // Con il totem i numeri stanno lì: il server non li conosce.
    crea("td", { testo: r.totem ? `sul totem ${r.totem}` : `${r.numero ?? "–"} · ${r.in_coda} in coda` }, riga);
    // Quale serie di file audio fa sentire il numero chiamato su questo reparto.
    const annunci = scelta([["", "— din-don —"], ...serie.map((x) => [x.id, `${x.nome} (${Object.keys(x.numeri).length})`])], r.annunci || "");
    annunci.disabled = !gestione;
    annunci.title = "Alla chiamata i monitor fanno sentire il file del numero di questa serie.";
    annunci.addEventListener("change", () => prova(() => api("PATCH", `/api/reparti/${r.id}/`, { annunci: annunci.value || null }), "Annunci del reparto aggiornati: i monitor li ricevono entro un minuto."));
    crea("td", {}, riga).appendChild(annunci);
    const chiave = crea("td", { classe: "chiave" }, riga);
    if (gestione) {
      crea("button", {
        testo: r.ha_chiave ? "Nuovo collegamento" : "Crea collegamento",
        "data-aiuto": "Crea l'indirizzo da aprire sulla bilancia o sulla pulsantiera per chiamare i numeri di questo reparto. Uno nuovo disattiva il precedente.",
        onclick: async () => {
          if (r.ha_chiave && !confirm("Il collegamento attuale smetterà di funzionare. Continuare?")) return;
          try {
            const { chiave: segreto } = await api("POST", `/api/reparti/${r.id}/chiave/`);
            chiave.replaceChildren();
            crea("p", { classe: "nota", testo: "Copialo ora: non sarà più mostrato. Aprilo sulla bilancia (indirizzo della pagina iniziale del browser)." }, chiave);
            // Con il totem la bilancia parla direttamente con lui, nella rete del negozio.
            const indirizzi = r.totem
              ? [`http://${r.totem}:8090`, `https://${r.totem}:8443`]
              : [`https://${location.host}`, `http://${location.host}`];
            for (const base of indirizzi) {
              crea("input", { readOnly: true, value: `${base}/banco/#chiave=${segreto}`, classe: "link", onfocus: (e) => e.target.select() }, chiave);
            }
            crea("p", {
              classe: "nota",
              testo: r.totem
                ? "Il totem riceve la chiave entro mezzo minuto. Per le bilance usa il primo (http)."
                : "La versione http funziona solo dalla rete del negozio, se abilitata all'installazione. Per i pulsanti: deploy/installa/pulsante.py.",
            }, chiave);
          } catch (errore) {
            avvisa(errore.message);
          }
        },
      }, chiave);
      if (r.ha_chiave) crea("button", { testo: "Revoca", classe: "pericolo", onclick: () => prova(() => api("DELETE", `/api/reparti/${r.id}/chiave/`), "Collegamento revocato.") }, chiave);
    } else {
      chiave.textContent = r.ha_chiave ? "collegato" : "—";
    }
    const azioni = crea("td", { classe: "azioni" }, riga);
    if (gestione) {
      crea("button", {
        testo: "Salva", classe: "primario",
        onclick: () => prova(() => api("PATCH", `/api/reparti/${r.id}/`, { nome: nome.value, colore: colore.value, colore_testo: testo.value, ordine: parseInt(ordine.value, 10), attivo: attivo.checked }), "Salvato."),
      }, azioni);
      crea("button", { testo: "Elimina", classe: "pericolo", onclick: () => confirm(`Eliminare «${r.nome}»?`) && prova(() => api("DELETE", `/api/reparti/${r.id}/`), "Eliminato.") }, azioni);
    }
  }
  if (!reparti.length) crea("p", { classe: "vuoto", testo: "Nessun reparto." }, tutti);
  sezioneAnnunci(serie, reparti, sedi, gestione);
}

// --- Annunci dei numeri: un file audio per numero (es. «SALUMERIA_27.mp3») -----------------------

const PER_INVIO = 40; // file per richiesta: una cartella intera parte a pezzi

function sezioneAnnunci(serie, reparti, sedi, gestione) {
  const box = sezione("🔊 Annunci dei numeri (file audio)");
  crea("p", {
    classe: "nota",
    testo: "Quando il banco chiama un numero, i monitor fanno sentire il file audio di quel numero (es. «Salumeria, numero 27»). "
      + "Carica l'intera cartella dei file: il nome decide tutto, come «SALUMERIA_27.mp3» → serie «SALUMERIA», numero 27. "
      + "Le serie con lo stesso nome di un reparto gli vengono collegate da sole; le altre (es. «foodcop») si collegano dalla colonna «Annunci (mp3)» qui sopra. "
      + "Un file senza numero (es. «DEFAULT.mp3»), caricato dentro una serie, vale per i numeri che non hanno il loro. Senza file si sente il din-don.",
  }, box);
  if (gestione) {
    const pulsanti = crea("div", { classe: "riga" }, box);
    const cartella = crea("input", { type: "file", multiple: true, hidden: true, webkitdirectory: true }, pulsanti);
    const file = crea("input", { type: "file", multiple: true, hidden: true, accept: ".mp3,.wav,.ogg,audio/*" }, pulsanti);
    crea("button", { classe: "primario", testo: "📁 Carica una cartella", "data-aiuto": "Scegli la cartella con tutti i file (es. «audio»): vengono caricati e divisi per serie in base al nome.", onclick: () => cartella.click() }, pulsanti);
    crea("button", { testo: "Scegli file", onclick: () => file.click() }, pulsanti);
    const esito = crea("div", { classe: "esito-annunci" }, box);
    for (const input of [cartella, file]) input.addEventListener("change", () => caricaAnnunci([...input.files], null, esito));
  }
  if (!serie.length) {
    crea("p", { classe: "vuoto", testo: "Nessun file audio caricato." }, box);
    return;
  }
  for (const x of serie) {
    const collegati = reparti.filter((r) => x.reparti.includes(r.id));
    const massimo = Math.max(99, ...collegati.map((r) => r.massimo), ...Object.keys(x.numeri).map(Number));
    const presenti = Object.keys(x.numeri).length;
    const scheda = crea("details", { classe: "serie-annunci" }, box);
    const titolo = crea("summary", {}, scheda);
    crea("strong", { testo: x.nome }, titolo);
    const mancanti = massimo + 1 - presenti;
    crea("span", { classe: mancanti && !x.predefinito ? "attenzione" : "tenue", testo: ` · ${presenti} numeri${mancanti > 0 ? ` (${mancanti} senza file${x.predefinito ? ": suona il predefinito" : ""})` : ""}${x.predefinito ? " · predefinito ✓" : ""}` }, titolo);
    crea("span", {
      classe: collegati.length ? "tenue" : "attenzione",
      testo: collegati.length ? ` · ${collegati.map((r) => `${r.nome} (${sedi.find((q) => q.id === r.sede)?.nome || ""})`).join(", ")}` : " · non collegata a nessun reparto",
    }, titolo);

    if (gestione) {
      const azioni = crea("div", { classe: "riga" }, scheda);
      const aggiungi = crea("input", { type: "file", multiple: true, hidden: true, accept: ".mp3,.wav,.ogg,audio/*" }, azioni);
      const esito = crea("div", { classe: "esito-annunci" }, scheda);
      aggiungi.addEventListener("change", () => caricaAnnunci([...aggiungi.files], x.id, esito));
      crea("button", { testo: "Aggiungi o sostituisci file", "data-aiuto": "File di questa serie: il numero si legge dal nome; un file senza numero diventa il predefinito.", onclick: () => aggiungi.click() }, azioni);
      const nome = crea("input", { value: x.nome, maxLength: 60, "aria-label": "Nome della serie" }, azioni);
      crea("button", { testo: "Rinomina", onclick: () => prova(() => api("PATCH", `/api/annunci/${x.id}/`, { nome: nome.value }), "Serie rinominata.") }, azioni);
      crea("button", {
        testo: "Elimina la serie", classe: "pericolo",
        onclick: () => confirm(`Eliminare la serie «${x.nome}» e tutti i suoi file? I reparti collegati torneranno al din-don.`) && prova(() => api("DELETE", `/api/annunci/${x.id}/`), "Serie eliminata."),
      }, azioni);
    }
    // Un tasto per numero: verde se c'è il file (clic: si ascolta), grigio se manca.
    const griglia = crea("div", { classe: "griglia-annunci" }, scheda);
    const voci = [["predefinito", x.predefinito, "★"], ...Array.from({ length: massimo + 1 }, (_, n) => [n, x.numeri[String(n)], String(n)])];
    for (const [numero, id, etichetta] of voci) {
      const tasto = crea("button", {
        type: "button", classe: `numero-annuncio${id ? " presente" : ""}${numero === "predefinito" ? " predefinito" : ""}`, testo: etichetta,
        title: id ? `${numero === "predefinito" ? "Predefinito" : `Numero ${numero}`}: clic per ascoltare${gestione ? ", Alt+clic per togliere" : ""}` : `Numero ${numero}: nessun file`,
      }, griglia);
      if (!id) continue;
      tasto.addEventListener("click", (e) => {
        if (e.altKey && gestione) {
          if (!confirm(`Togliere il file ${numero === "predefinito" ? "predefinito" : `del numero ${numero}`}?`)) return;
          prova(() => api("POST", `/api/annunci/${x.id}/togli/`, numero === "predefinito" ? { predefinito: true } : { numeri: [numero] }), "File tolto.");
          return;
        }
        tasto.classList.add("suona");
        const audio = new Audio(conCliente(`/api/annunci/ascolta/${id}/`));
        audio.addEventListener("ended", () => tasto.classList.remove("suona"));
        audio.addEventListener("error", () => { tasto.classList.remove("suona"); avvisa("Il file non si riesce a riprodurre."); });
        audio.play().catch(() => tasto.classList.remove("suona"));
      });
    }
  }
}

async function caricaAnnunci(scelti, serie, esito) {
  const audio = scelti.filter((f) => /\.(mp3|wav|ogg)$/i.test(f.name));
  if (!audio.length) {
    avvisa("Nessun file audio (mp3, wav, ogg) tra quelli scelti.");
    return;
  }
  const totale = { caricati: 0, uguali: 0, scartati: [], serie: new Map() };
  esito.replaceChildren();
  const avanzamento = crea("p", { classe: "nota" }, esito);
  try {
    for (let i = 0; i < audio.length; i += PER_INVIO) {
      avanzamento.textContent = `Caricamento ${Math.min(i + PER_INVIO, audio.length)} di ${audio.length}…`;
      const dati = new FormData();
      for (const f of audio.slice(i, i + PER_INVIO)) dati.append("file", f, f.name);
      if (serie) dati.append("serie", serie);
      const parziale = await api("POST", "/api/annunci/importa/", dati);
      totale.caricati += parziale.caricati;
      totale.uguali += parziale.uguali;
      totale.scartati.push(...parziale.scartati);
      for (const s of parziale.serie) {
        const somma = totale.serie.get(s.id) || { nome: s.nome, file: 0, collegati: [] };
        somma.file += s.file;
        somma.collegati.push(...s.collegati);
        totale.serie.set(s.id, somma);
      }
    }
  } catch (errore) {
    avvisa(errore.message);
    avanzamento.textContent = "Caricamento interrotto.";
    return;
  }
  const righe = [...totale.serie.values()].map((s) => `${s.nome}: ${s.file} file${s.collegati.length ? ` → collegata a ${s.collegati.join(", ")}` : ""}`);
  avvisa(`Annunci caricati: ${totale.caricati} nuovi${totale.uguali ? `, ${totale.uguali} già presenti` : ""}${totale.scartati.length ? `, ${totale.scartati.length} scartati` : ""}.`, "ok");
  await mostra(stato.scheda);
  // Il riepilogo resta visibile dopo il ridisegno.
  const box = document.querySelector(".esito-annunci");
  if (!box) return;
  crea("p", { classe: "nota", testo: righe.join(" · ") }, box);
  if (totale.scartati.length) {
    const dettagli = crea("details", {}, box);
    crea("summary", { testo: `${totale.scartati.length} file non caricati` }, dettagli);
    const elenco = crea("ul", {}, dettagli);
    for (const s of totale.scartati) crea("li", { testo: `${s.file}: ${s.motivo}` }, elenco);
  }
}

// --- Sedi e gruppi -------------------------------------------------------------------------------

async function schedaSedi() {
  const [sedi, gruppi, insegne] = await Promise.all([elenco("/api/sedi/"), elenco("/api/gruppi/"), elenco("/api/insegne/")]);

  // Facoltative: servono a pubblicare per insegna quando l'azienda ha più marchi.
  const boxInsegne = sezione("Insegne");
  crea("p", {
    classe: "nota",
    testo: "Facoltative: se l'azienda ha negozi con insegne diverse, assegna l'insegna a ogni sede e potrai pubblicare le campagne per insegna.",
  }, boxInsegne);
  const nuovaInsegna = crea("div", { classe: "riga" }, boxInsegne);
  const nomeInsegna = campo("Nome", crea("input", { placeholder: "es. Nome insegna" }), nuovaInsegna);
  const coloreInsegna = campo("Colore", crea("input", { type: "color", value: "#ec6a1f" }), nuovaInsegna);
  crea("button", {
    classe: "primario", testo: "Aggiungi",
    onclick: () => prova(() => api("POST", "/api/insegne/", { nome: nomeInsegna.value, colore: coloreInsegna.value }), "Insegna aggiunta."),
  }, nuovaInsegna);
  const corpoInsegne = tabella(["Insegna", "Sedi", ""], boxInsegne);
  for (const i of insegne) {
    const r = crea("tr", {}, corpoInsegne);
    const nome = crea("td", {}, r);
    crea("span", { classe: "pallino", style: `background:${i.colore}` }, nome);
    nome.append(` ${i.nome}`);
    crea("td", { testo: String(sedi.filter((s) => s.insegna === i.id).length) }, r);
    crea("button", {
      testo: "Elimina", classe: "pericolo",
      onclick: () => confirm(`Eliminare l'insegna «${i.nome}»? Le sedi restano, senza insegna.`) && prova(() => api("DELETE", `/api/insegne/${i.id}/`), "Eliminata."),
    }, crea("td", {}, r));
  }

  const boxSediInsegne = sezione("Insegna di ogni sede");
  const corpoSediInsegne = tabella(["Sede", "Insegna", ""], boxSediInsegne);
  for (const sede of sedi) {
    const riga = crea("tr", {}, corpoSediInsegne);
    crea("td", { testo: sede.nome }, riga);
    const scelta_ = scelta([["", "— nessuna —"], ...insegne.map((i) => [i.id, i.nome])], sede.insegna || "");
    crea("td", {}, riga).appendChild(scelta_);
    crea("button", {
      testo: "Salva", classe: "primario",
      onclick: () => prova(() => api("PATCH", `/api/sedi/${sede.id}/`, { insegna: scelta_.value || null }), "Insegna della sede salvata."),
    }, crea("td", {}, riga));
  }

  const totem = sezione("Totem Master (server code)");
  crea("p", {
    classe: "nota",
    testo: "L'IP fisso del Totem Master della sede, quello che detiene i turni delle code: numeri e biglietti li tiene lui, anche senza server centrale; gli altri totem gli chiedono i numeri. "
      + "Quale totem è il master si sceglie in «Anagrafica Dispositivi Video». Vuoto: le code le tiene il server.",
  }, totem);
  const corpoTotem = tabella(["Sede", "IP del Totem Master", ""], totem);
  for (const sede of sedi) {
    const riga = crea("tr", {}, corpoTotem);
    crea("td", { testo: sede.nome }, riga);
    const ip = crea("input", { value: sede.indirizzo_totem || "", placeholder: "es. 192.168.1.70" }, crea("td", {}, riga));
    crea("button", {
      testo: "Salva", classe: "primario",
      onclick: () => prova(() => api("PATCH", `/api/sedi/${sede.id}/`, { indirizzo_totem: ip.value.trim() }), "Salvato: monitor e totem lo ricevono entro mezzo minuto."),
    }, crea("td", {}, riga));
  }

  for (const [titolo, voci, url, segnaposto] of [
    ["Sedi", sedi, "/api/sedi/", "es. Punto vendita centro"],
    ["Gruppi di schermi", gruppi, "/api/gruppi/", "es. Tutti, Casse, Reparto freschi"],
  ]) {
    const s = sezione(titolo);
    const riga = crea("div", { classe: "riga" }, s);
    const nome = campo("Nome", crea("input", { placeholder: segnaposto }), riga);
    crea("button", { classe: "primario", testo: "Aggiungi", onclick: () => prova(() => api("POST", url, { nome: nome.value }), "Aggiunto.") }, riga);
    const corpo = tabella(["Nome", ""], s);
    for (const v of voci) {
      const r = crea("tr", {}, corpo);
      crea("td", { testo: v.nome }, r);
      crea("button", { testo: "Elimina", classe: "pericolo", onclick: () => confirm(`Eliminare «${v.nome}»?`) && prova(() => api("DELETE", `${url}${v.id}/`), "Eliminato.") }, crea("td", {}, r));
    }
  }
}

// --- Aspetto della piattaforma ---------------------------------------------------------------------

const TEMI = [
  ["chiaro", "Chiaro", "Fondo chiaro, come un documento."],
  ["scuro", "Scuro", "Fondo scuro, riposante e d'effetto."],
  ["auto", "Automatico", "Segue l'impostazione chiaro/scuro del computer."],
];

async function schedaAspetto() {
  const box = sezione("Tema delle pagine");
  crea("p", { classe: "nota", testo: "Vale per te, su pannello, editor dei layout e creazione palinsesto, da qualunque computer accedi." }, box);
  const temi = crea("div", { classe: "temi" }, box);
  for (const [valore, titolo, descrizione] of TEMI) {
    const scelta = crea("button", {
      type: "button", classe: `tema${stato.io.tema === valore ? " scelto" : ""}`,
      onclick: async () => {
        try {
          stato.io = await api("PATCH", "/api/io/", { tema: valore });
          document.documentElement.dataset.tema = valore;
          avvisa(`Tema ${titolo.toLowerCase()} impostato.`, "ok");
          await mostra("aspetto");
        } catch (errore) {
          avvisa(errore.message);
        }
      },
    }, temi);
    const provino = crea("div", { classe: `provino ${valore}` }, scelta);
    crea("div", { classe: "t" }, provino);
    const corpo = crea("div", { classe: "c" }, provino);
    crea("i", {}, corpo);
    crea("i", {}, corpo);
    crea("strong", { testo: `${stato.io.tema === valore ? "✓ " : ""}${titolo}` }, scelta);
    crea("span", { testo: descrizione }, scelta);
  }
  if (stato.io.ruolo === "admin_assoluto") await sezioneMarchio();
}

async function sezioneMarchio() {
  const aspetto = await api("GET", "/api/piattaforma/aspetto/");
  const box = sezione("Nome e logo della piattaforma");
  crea("p", { classe: "nota", testo: "Compaiono nella pagina di accesso, nella barra del pannello e nei titoli delle pagine. Valgono per tutti i clienti." }, box);
  const riga = crea("div", { classe: "riga" }, box);
  const nome = campo("Nome dell'applicazione", crea("input", { value: aspetto.nome_app, maxLength: 60 }), riga);
  const sottotitolo = campo("Frase della pagina di accesso", crea("input", { value: aspetto.sottotitolo, maxLength: 120, size: 50 }), riga);
  const colore = campo("Colore", crea("input", { type: "color", value: aspetto.colore }), riga);
  const rigaLogo = crea("div", { classe: "riga" }, box);
  if (aspetto.ha_logo) crea("img", { src: `/aspetto/logo/?v=${Date.parse(aspetto.modificato)}`, classe: "anteprima-logo", alt: "Logo attuale" }, rigaLogo);
  const logo = campo("Logo (PNG, JPEG o WebP, fino a 2 MB; meglio con fondo trasparente)", crea("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" }), rigaLogo);
  const azioni = crea("div", { classe: "riga" }, box);
  crea("button", {
    classe: "primario", testo: "Salva",
    onclick: () => prova(async () => {
      const dati = new FormData();
      dati.append("nome_app", nome.value.trim());
      dati.append("sottotitolo", sottotitolo.value.trim());
      dati.append("colore", colore.value);
      if (logo.files[0]) dati.append("logo", logo.files[0]);
      await api("PATCH", "/api/piattaforma/aspetto/", dati);
      setTimeout(() => location.reload(), 600);
    }, "Salvato: la pagina si ricarica con il nuovo aspetto."),
  }, azioni);
  if (aspetto.ha_logo) {
    crea("button", {
      classe: "pericolo", testo: "Togli il logo",
      onclick: () => prova(async () => {
        await api("PATCH", "/api/piattaforma/aspetto/", { logo: null });
        setTimeout(() => location.reload(), 600);
      }, "Logo tolto."),
    }, azioni);
  }
  crea("button", { type: "button", testo: "Vedi la pagina di accesso", "data-aiuto": "Mostra in un riquadro come appare la pagina di accesso con nome, frase, colore e logo salvati.", onclick: () => apriRiquadro("Pagina di accesso", "/accesso/?anteprima=1") }, azioni);
}

// --- Utenti --------------------------------------------------------------------------------------

async function schedaUtenti() {
  const [utenti, sedi] = await Promise.all([elenco("/api/utenti/"), elenco("/api/sedi/")]);
  const nuovo = sezione("Nuovo utente");
  const riga = crea("div", { classe: "riga" }, nuovo);
  const nome = campo("Nome utente", crea("input", { autocomplete: "off" }), riga);
  const password = campo("Password (almeno 10 caratteri)", crea("input", { type: "password", autocomplete: "new-password" }), riga);
  const ruolo = campo("Ruolo", scelta([["user_cliente", "User (contenuti e banco)"], ["admin_cliente", "Administrator"]]), riga);
  crea("span", { classe: "etichetta", testo: "Limitato alle sedi (nessuna = tutte)" }, nuovo);
  const sediScelte = spunte(sedi.map((s) => [s.id, s.nome]), [], nuovo);
  crea("button", {
    classe: "primario", testo: "Crea utente",
    onclick: () => prova(() => api("POST", "/api/utenti/", { username: nome.value, password: password.value, ruolo: ruolo.value, sedi_consentite: sediScelte() }), "Utente creato."),
  }, nuovo);

  const tutti = sezione("Utenti del cliente");
  const corpo = tabella(["Utente", "Ruolo", "Attivo", ""], tutti);
  for (const u of utenti) {
    const r = crea("tr", {}, corpo);
    crea("td", { testo: u.username }, r);
    crea("td", { testo: u.ruolo === "admin_cliente" ? "Administrator" : "User" }, r);
    const attivo = crea("input", { type: "checkbox", checked: u.is_active, disabled: u.id === stato.io.id }, crea("td", {}, r));
    attivo.addEventListener("change", () => prova(() => api("PATCH", `/api/utenti/${u.id}/`, { is_active: attivo.checked }), "Salvato."));
    const azioni = crea("td", { classe: "azioni" }, r);
    crea("button", {
      testo: "Nuova password",
      onclick: () => {
        const nuova = prompt(`Nuova password per ${u.username} (almeno 10 caratteri):`);
        if (nuova) prova(() => api("PATCH", `/api/utenti/${u.id}/`, { password: nuova }), "Password cambiata.");
      },
    }, azioni);
    if (u.id !== stato.io.id) crea("button", { testo: "Elimina", classe: "pericolo", onclick: () => confirm(`Eliminare ${u.username}?`) && prova(() => api("DELETE", `/api/utenti/${u.id}/`), "Eliminato.") }, azioni);
  }
}

// --- Avvio ---------------------------------------------------------------------------------------

async function caricaClienti() {
  stato.clienti = await elenco("/api/piattaforma/clienti/");
  const select = document.getElementById("cliente");
  select.replaceChildren();
  crea("option", { value: "", testo: "— scegli —" }, select);
  for (const c of stato.clienti) crea("option", { value: c.id, testo: c.nome, selected: c.id === stato.cliente }, select);
}

function scegliCliente(id, scheda) {
  stato.cliente = id || null;
  ricordaCliente(stato.cliente);
  const url = new URL(location.href);
  if (stato.cliente) url.searchParams.set("cliente", stato.cliente);
  else url.searchParams.delete("cliente");
  history.replaceState(null, "", url);
  document.getElementById("cliente").value = stato.cliente || "";
  mostra(scheda || stato.scheda);
}

async function avvia() {
  stato.io = await api("GET", "/api/io/");
  const ruoli = { admin_assoluto: "SystemAdministrator", tecnico: "Tecnico", admin_cliente: "Administrator", user_cliente: "User" };
  document.getElementById("utente").textContent = `${stato.io.username} · ${ruoli[stato.io.ruolo]}`;
  if (stato.io.di_piattaforma) {
    document.getElementById("scelta-cliente").hidden = false;
    stato.cliente = clienteRicordato();
    await caricaClienti();
    if (!stato.clienti.some((c) => c.id === stato.cliente)) stato.cliente = null;
    document.getElementById("cliente").value = stato.cliente || "";
    document.getElementById("cliente").addEventListener("change", (e) =>
      scegliCliente(e.target.value, stato.scheda === "clienti" && e.target.value ? "monitor" : undefined));
  }
  attivaAiuti();
  const strumenti = { stato, api, elenco, tutteLePagine, crea, avvisa, prova, sezione, campo, scelta, tabella, ruoloGestione, conCliente, mostra };
  preparaSchedeSchermi(strumenti);
  preparaSchedeContenuti(strumenti);
  preparaSchedeCode(strumenti);
  preparaSchedeImpostazioni(strumenti);
  preparaSchedeReport(strumenti);
  preparaSchedePlugin(strumenti);
  preparaSchedeTicket(strumenti);
  osservaAiuti(contenuto, () => stato.scheda);
  const richiesta = location.hash.slice(1);
  const visibile = VOCI.some((v) => v.chiave === richiesta && SCHEDE[richiesta] && v.visibile(stato.io));
  await mostra(visibile ? richiesta : stato.io.ruolo === "admin_assoluto" && !stato.cliente ? "clienti" : "monitor");
}

avvia().catch((errore) => avvisa(errore.message));
