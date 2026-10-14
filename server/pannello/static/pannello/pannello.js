// Il pannello di FuturaPro: una pagina sola sulle API del server.
// Ogni testo che arriva dai dati passa da textContent, mai da innerHTML.

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

const SCHEDE = {
  clienti: { titolo: "Clienti", visibile: () => stato.io.ruolo === "admin_assoluto", serveCliente: false, mostra: schedaClienti },
  monitor: { titolo: "Monitor", visibile: () => true, mostra: schedaMonitor },
  contenuti: { titolo: "Contenuti e pubblicazioni", visibile: () => stato.io.ruolo !== "tecnico", mostra: schedaContenuti },
  reparti: { titolo: "Reparti ed eliminacode", visibile: () => stato.io.ruolo !== "tecnico", mostra: schedaReparti },
  layout: { titolo: "Layout", visibile: ruoloGestione, collegamento: () => conCliente("/editor/") },
  banco: { titolo: "Banco", visibile: () => stato.io.ruolo !== "tecnico", collegamento: () => conCliente("/banco/") },
  sedi: { titolo: "Sedi e gruppi", visibile: ruoloGestione, mostra: schedaSedi },
  utenti: { titolo: "Utenti", visibile: ruoloGestione, mostra: schedaUtenti },
  aspetto: { titolo: "Aspetto", visibile: () => stato.io.ruolo === "admin_assoluto", serveCliente: false, mostra: schedaAspetto },
};

function disegnaSchede() {
  const nav = document.getElementById("schede");
  nav.replaceChildren();
  for (const [chiave, scheda] of Object.entries(SCHEDE)) {
    if (!scheda.visibile()) continue;
    if (scheda.collegamento) {
      crea("a", { href: scheda.collegamento(), testo: `${scheda.titolo} ↗`, target: "_blank", classe: "scheda" }, nav);
    } else {
      crea("button", { testo: scheda.titolo, classe: `scheda${stato.scheda === chiave ? " attiva" : ""}`, onclick: () => mostra(chiave) }, nav);
    }
  }
}

async function mostra(chiave) {
  stato.scheda = chiave;
  disegnaSchede();
  contenuto.replaceChildren();
  const scheda = SCHEDE[chiave];
  if (scheda.serveCliente !== false && stato.io.di_piattaforma && !stato.cliente) {
    crea("p", { classe: "vuoto", testo: "Scegli il cliente in alto." }, contenuto);
    return;
  }
  try {
    await scheda.mostra();
  } catch (errore) {
    avvisa(errore.message);
  }
}

// --- Clienti (solo Administrator Assoluto) ----------------------------------------------

async function schedaClienti() {
  const nuovo = sezione("Nuovo cliente");
  const nome = campo("Nome", crea("input", { required: true }), nuovo);
  const ragione = campo("Ragione sociale", crea("input"), nuovo);
  const piva = campo("Partita IVA", crea("input"), nuovo);
  crea("h3", { testo: "Primo AdminCliente" }, nuovo);
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
      [["admin_gestisce_utenti", "L'AdminCliente gestisce gli utenti"], ["admin_gestisce_dispositivi", "…i monitor"], ["admin_gestisce_layout", "…i layout"]]
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
  const [monitor, sedi, gruppi, layout] = await Promise.all([elenco("/api/monitor/"), elenco("/api/sedi/"), elenco("/api/gruppi/"), elenco("/api/layout/")]);
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
      classe: "primario", testo: "Abbina",
      onclick: () => prova(async () => {
        const m = await api("POST", "/api/monitor/abbina/", { codice: codice.value.replace(/\s/g, ""), nome: nome.value, sede: sede.value, gruppi: scegliGruppi() });
        if (orientamento.value === "verticale") await api("PATCH", `/api/monitor/${m.id}/`, { orientamento: "verticale" });
      }, "Schermo abbinato: entro pochi secondi mostra i contenuti."),
    }, abbina);
  }

  const tutti = sezione("Schermi");
  if (!monitor.length) crea("p", { classe: "vuoto", testo: "Nessuno schermo abbinato." }, tutti);
  const corpo = tabella(["Nome", "Sede", "Stato", "In onda", "Gruppi", "Orientamento", "Rotazione", "Layout", ""], tutti);
  for (const m of monitor) {
    const riga = crea("tr", {}, corpo);
    crea("td", { testo: m.nome }, riga);
    crea("td", { testo: sedi.find((s) => s.id === m.sede)?.nome || "" }, riga);
    const statoCella = crea("td", {}, riga);
    crea("span", { classe: `pallino ${m.online ? "acceso" : "spento"}` }, statoCella);
    statoCella.append(m.online ? " Online" : m.ultimo_contatto ? ` Offline da ${new Date(m.ultimo_contatto).toLocaleString("it-IT")}` : " Mai collegato");
    const salva = (dati) => prova(() => api("PATCH", `/api/monitor/${m.id}/`, dati), "Salvato.");
    const orientamento = scelta([["orizzontale", "Orizzontale"], ["verticale", "Verticale (totem)"]], m.orientamento);
    const rotazione = scelta([[0, "0°"], [90, "90°"], [180, "180°"], [270, "270°"]], m.rotazione);
    const sceltaLayout = scelta(
      [["", "Predefinito"], ...layout.filter((l) => l.orientamento === m.orientamento).map((l) => [l.id, l.nome])],
      m.layout || "",
    );
    // Cosa va in onda adesso: se è vuoto, al monitor non arriva nessuna pubblicazione.
    const inOnda = crea("td", { testo: "…" }, riga);
    api("GET", `/api/anteprima/${m.id}/`).then(({ sequenza, aggiornato }) => {
      inOnda.textContent = sequenza.length ? `${sequenza.length} contenut${sequenza.length === 1 ? "o" : "i"}` : "Niente";
      if (!sequenza.length) {
        inOnda.className = "attenzione";
        inOnda.title = "Nessuna pubblicazione valida adesso per questo schermo o per i suoi gruppi.";
      }
      // Online ma con un palinsesto vecchio: non ha ancora scaricato le ultime modifiche.
      if (m.online && aggiornato === false) {
        inOnda.append(" · non aggiornato");
        inOnda.className = "attenzione";
        inOnda.title = "Lo schermo non ha ancora ricevuto (o scaricato) l'ultimo palinsesto.";
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
    const azioni = crea("td", { classe: "azioni" }, riga);
    crea("a", { href: conCliente(`/anteprima/${m.id}/`), target: "_blank", testo: "Anteprima" }, azioni);
    if (gestione) {
      crea("button", {
        testo: "Rimuovi", classe: "pericolo",
        onclick: () => confirm(`Rimuovere «${m.nome}»? Lo schermo tornerà a mostrare il codice di abbinamento.`) && prova(() => api("DELETE", `/api/monitor/${m.id}/`), "Rimosso."),
      }, azioni);
    }
  }
}

// --- Contenuti e pubblicazioni --------------------------------------------------------------

async function schedaContenuti() {
  const [contenuti, monitor, gruppi, pubblicazioni] = await Promise.all([
    elenco("/api/contenuti/"), elenco("/api/monitor/"), elenco("/api/gruppi/"), elenco("/api/pubblicazioni/"),
  ]);

  const carica = sezione("Carica");
  const file = campo("Immagini o video (JPEG, PNG, GIF, WebP, MP4, MOV, WebM)", crea("input", { type: "file", multiple: true, accept: "image/*,video/*" }), carica);
  const durata = campo("Durata in secondi (vuoto: 10 s per le immagini, i video fino alla fine)", crea("input", { type: "number", min: 1 }), carica);
  const avanzamento = crea("p", { classe: "nota" }, carica);
  crea("button", {
    classe: "primario", testo: "Carica",
    onclick: () => prova(async () => {
      const elenco = [...file.files];
      for (const [i, f] of elenco.entries()) {
        avanzamento.textContent = `Caricamento ${i + 1} di ${elenco.length}: ${f.name}…`;
        const dati = new FormData();
        dati.append("file", f);
        if (durata.value) dati.append("durata", durata.value);
        await api("POST", "/api/contenuti/", dati);
      }
    }, "Caricato."),
  }, carica);
  const web = crea("details", {}, carica);
  crea("summary", { testo: "Aggiungi una pagina web" }, web);
  const url = campo("Indirizzo", crea("input", { type: "url", placeholder: "https://…" }), web);
  const durataWeb = campo("Durata (secondi)", crea("input", { type: "number", min: 1, value: 30 }), web);
  crea("button", { testo: "Aggiungi", onclick: () => prova(() => api("POST", "/api/contenuti/", { url: url.value, durata: parseInt(durataWeb.value, 10) }), "Aggiunta.") }, web);

  const libreria = sezione("Libreria");
  crea("p", { classe: "nota", testo: "Spunta i contenuti da pubblicare, poi scegli gli schermi qui sotto." }, libreria);
  const scelti = new Set();
  const griglia = crea("div", { classe: "griglia" }, libreria);
  for (const c of contenuti) {
    const scheda = crea("div", { classe: "contenuto-scheda" }, griglia);
    const anteprima = crea("div", { classe: "miniatura" }, scheda);
    if (c.tipo === "immagine") crea("img", { src: conCliente(`/api/contenuti/${c.id}/file/`), loading: "lazy", alt: "" }, anteprima);
    else crea("span", { testo: c.tipo === "video" ? "▶ video" : "🌐 web" }, anteprima);
    const etichetta = crea("label", { classe: "spunta" }, scheda);
    crea("input", { type: "checkbox", onchange: (e) => (e.target.checked ? scelti.add(c.id) : scelti.delete(c.id)) }, etichetta);
    etichetta.append(` ${c.nome}`);
    crea("button", {
      testo: "Elimina", classe: "piccolo pericolo",
      onclick: () => confirm(`Eliminare «${c.nome}»? Sparirà anche dalle playlist.`) && prova(() => api("DELETE", `/api/contenuti/${c.id}/`), "Eliminato."),
    }, scheda);
  }
  if (!contenuti.length) crea("p", { classe: "vuoto", testo: "Nessun contenuto." }, griglia);

  const pubblica = sezione("Pubblica");
  const nome = campo("Nome (facoltativo)", crea("input", { placeholder: "es. Offerte settimana" }), pubblica);
  crea("span", { classe: "etichetta", testo: "Schermi" }, pubblica);
  const sceltiMonitor = spunte(monitor.map((m) => [m.id, m.nome]), [], pubblica);
  if (gruppi.length) {
    crea("span", { classe: "etichetta", testo: "Gruppi" }, pubblica);
  }
  const sceltiGruppi = spunte(gruppi.map((g) => [g.id, `${g.nome} (gruppo)`]), [], pubblica);
  const opzioni = crea("details", {}, pubblica);
  crea("summary", { testo: "Calendario e priorità (facoltativi)" }, opzioni);
  const riga = crea("div", { classe: "riga" }, opzioni);
  const dal = campo("Dal", crea("input", { type: "date" }), riga);
  const al = campo("Al", crea("input", { type: "date" }), riga);
  const dalle = campo("Dalle", crea("input", { type: "time" }), riga);
  const alle = campo("Alle", crea("input", { type: "time" }), riga);
  const priorita = campo("Priorità (più alta = sostituisce le altre)", crea("input", { type: "number", value: 0 }), riga);
  const giorni = spunte(["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"].map((g, i) => [i, g]), [], opzioni);
  crea("button", {
    classe: "primario", testo: "Pubblica",
    onclick: () => prova(() => api("POST", "/api/pubblica/", {
      contenuti: [...scelti], monitor: sceltiMonitor(), gruppi: sceltiGruppi(), nome: nome.value || undefined,
      data_inizio: dal.value || null, data_fine: al.value || null, ora_inizio: dalle.value || null, ora_fine: alle.value || null,
      giorni: giorni(), priorita: parseInt(priorita.value || "0", 10),
    }), "Pubblicato: gli schermi lo ricevono entro mezzo minuto."),
  }, pubblica);

  const attive = sezione("Pubblicazioni");
  const corpo = tabella(["Nome", "Schermi", "Quando", "Attiva", ""], attive);
  for (const p of pubblicazioni) {
    const riga = crea("tr", {}, corpo);
    crea("td", { testo: p.nome }, riga);
    const destinatari = [...p.monitor.map((id) => monitor.find((m) => m.id === id)?.nome), ...p.gruppi.map((id) => gruppi.find((g) => g.id === id)?.nome)];
    crea("td", { testo: destinatari.filter(Boolean).join(", ") }, riga);
    const quando = [p.data_inizio && `dal ${p.data_inizio}`, p.data_fine && `al ${p.data_fine}`, p.ora_inizio && `${p.ora_inizio.slice(0, 5)}–${(p.ora_fine || "").slice(0, 5)}`, p.priorita ? `priorità ${p.priorita}` : ""];
    crea("td", { testo: quando.filter(Boolean).join(" ") || "sempre" }, riga);
    const attiva = crea("input", { type: "checkbox", checked: p.attiva }, crea("td", {}, riga));
    attiva.addEventListener("change", () => prova(() => api("PATCH", `/api/pubblicazioni/${p.id}/`, { attiva: attiva.checked }), "Salvato."));
    crea("button", { testo: "Elimina", classe: "pericolo", onclick: () => confirm(`Eliminare «${p.nome}»?`) && prova(() => api("DELETE", `/api/pubblicazioni/${p.id}/`), "Eliminata.") }, crea("td", {}, riga));
  }
}

// --- Reparti ----------------------------------------------------------------------------------

async function schedaReparti() {
  const [reparti, sedi] = await Promise.all([elenco("/api/reparti/"), elenco("/api/sedi/")]);
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
  const corpo = tabella(["Nome", "Sede", "Colori", "Ordine", "Attivo", "Ora", "Bilancia / pulsantiera", ""], tutti);
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
    const chiave = crea("td", { classe: "chiave" }, riga);
    if (gestione) {
      crea("button", {
        testo: r.ha_chiave ? "Nuovo collegamento" : "Crea collegamento",
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
  const nomeInsegna = campo("Nome", crea("input", { placeholder: "es. Tocal Express" }), nuovaInsegna);
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

  const totem = sezione("Totem delle code");
  crea("p", {
    classe: "nota",
    testo: "L'IP fisso del totem che gestisce le code della sede: numeri e biglietti li tiene il totem, che funziona anche senza server centrale. Vuoto: le code le tiene il server.",
  }, totem);
  const corpoTotem = tabella(["Sede", "IP del totem", ""], totem);
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
    ["Sedi", sedi, "/api/sedi/", "es. Catania via Etnea"],
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

async function schedaAspetto() {
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
  crea("a", { href: "/accesso/?anteprima=1", target: "_blank", testo: "Vedi la pagina di accesso ↗" }, azioni);
}

// --- Utenti --------------------------------------------------------------------------------------

async function schedaUtenti() {
  const [utenti, sedi] = await Promise.all([elenco("/api/utenti/"), elenco("/api/sedi/")]);
  const nuovo = sezione("Nuovo utente");
  const riga = crea("div", { classe: "riga" }, nuovo);
  const nome = campo("Nome utente", crea("input", { autocomplete: "off" }), riga);
  const password = campo("Password (almeno 10 caratteri)", crea("input", { type: "password", autocomplete: "new-password" }), riga);
  const ruolo = campo("Ruolo", scelta([["user_cliente", "UserCliente (contenuti e banco)"], ["admin_cliente", "AdminCliente"]]), riga);
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
    crea("td", { testo: u.ruolo === "admin_cliente" ? "AdminCliente" : "UserCliente" }, r);
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
  try {
    localStorage.setItem("futurapro.pannello.cliente", stato.cliente || "");
  } catch {
    // Solo una comodità.
  }
  document.getElementById("cliente").value = stato.cliente || "";
  mostra(scheda || stato.scheda);
}

async function avvia() {
  stato.io = await api("GET", "/api/io/");
  const ruoli = { admin_assoluto: "Administrator Assoluto", tecnico: "Tecnico", admin_cliente: "AdminCliente", user_cliente: "UserCliente" };
  document.getElementById("utente").textContent = `${stato.io.username} · ${ruoli[stato.io.ruolo]}`;
  if (stato.io.di_piattaforma) {
    document.getElementById("scelta-cliente").hidden = false;
    try {
      stato.cliente = localStorage.getItem("futurapro.pannello.cliente") || null;
    } catch {
      stato.cliente = null;
    }
    await caricaClienti();
    if (!stato.clienti.some((c) => c.id === stato.cliente)) stato.cliente = null;
    document.getElementById("cliente").value = stato.cliente || "";
    document.getElementById("cliente").addEventListener("change", (e) =>
      scegliCliente(e.target.value, stato.scheda === "clienti" && e.target.value ? "monitor" : undefined));
  }
  await mostra(stato.io.ruolo === "admin_assoluto" && !stato.cliente ? "clienti" : "monitor");
}

avvia().catch((errore) => avvisa(errore.message));
