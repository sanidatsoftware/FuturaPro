// «Controllo Remoto»: la teleassistenza dei PC dei negozi (MeshCentral, vedi teleassistenza/mesh.py).
// Solo SystemAdministrator e Tecnici: inventario dei PC di tutte le aziende, collegamento allo
// schermo con il motivo e la verifica in due passaggi, registro delle sessioni.

let H = null;

export function preparaSchedeRemoto(strumenti) {
  H = strumenti;
}

const quando = (iso) => (iso ? new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "—");
const durata = (da, a) => {
  const minuti = Math.max(0, Math.round(((a ? Date.parse(a) : Date.now()) - Date.parse(da)) / 60000));
  return minuti < 60 ? `${minuti} min` : `${Math.floor(minuti / 60)} h ${minuti % 60} min`;
};
const byte = (n) => (n ? `${(n / 1024 ** 3).toFixed(n > 10 * 1024 ** 3 ? 0 : 1)} GB` : "—");

function nonConfigurato(box, dati) {
  H.crea("p", {
    classe: "messaggio errore",
    testo: dati.errore
      ? `Il Controllo Remoto non risponde: ${dati.errore}`
      : "Il Controllo Remoto non è ancora attivo su questo server: va aggiornato (sudo bash aggiorna.sh), che installa MeshCentral.",
  }, box);
}

// La finestra del collegamento: motivo e (se serve) il codice della verifica in due passaggi.
function chiediCollegamento(pc, io) {
  const { crea, api } = H;
  const finestra = crea("dialog", { classe: "finestra" }, document.body);
  finestra.addEventListener("close", () => finestra.remove());
  crea("button", { "aria-label": "Chiudi", testo: "✕" }, crea("form", { method: "dialog", classe: "chiudi" }, finestra));
  crea("h2", { testo: `🖥 Collegati a ${pc.nome}` }, finestra);
  const dove = pc.monitor ? `${pc.monitor.cliente} › ${pc.monitor.sede} › ${pc.monitor.nome}` : "PC non ancora abbinato a un monitor";
  crea("p", { testo: `${dove}. Sullo schermo del negozio comparirà la barra «Teleassistenza FuturaPro in corso».` }, finestra);
  if (!io.doppio_attivo) {
    crea("p", { classe: "messaggio errore", testo: "Per collegarti serve la verifica in due passaggi: attivala nel tuo Profilo (Impostazioni → Profilo)." }, finestra);
    crea("button", { classe: "primario", testo: "Vai al Profilo", onclick: () => { finestra.close(); H.mostra("profilo"); } }, finestra);
    finestra.showModal();
    return;
  }
  const motivo = crea("input", { placeholder: "es. il monitor non mostra le promozioni", size: 50, maxLength: 300 });
  const codice = crea("input", { inputmode: "numeric", autocomplete: "one-time-code", maxLength: 6, size: 8 });
  const riga = crea("div", { classe: "riga" }, finestra);
  H.campo("Motivo (resta nel registro)", motivo, riga);
  H.campo("Codice dell'app (se richiesto)", codice, riga);
  crea("p", { classe: "tenue", testo: "Il codice si chiede al massimo ogni 12 ore. La sessione si chiude da sola nel registro dopo la durata massima." }, finestra);
  const esito = crea("p", {}, finestra);
  crea("button", {
    classe: "primario", testo: "Collegati",
    onclick: async (e) => {
      e.target.disabled = true;
      try {
        const r = await api("POST", "/api/remoto/sessioni/", { nodo: pc.id, motivo: motivo.value, codice: codice.value });
        // Una finestra a parte per lo schermo del PC (già entrati, senza password).
        window.open(r.indirizzo, `remoto-${pc.id.split("/").pop()}`, "popup,width=1440,height=900");
        finestra.close();
        H.avvisa(`Collegato a ${pc.nome}: lo schermo si è aperto in una finestra: premi «Connetti» in alto a sinistra. Ricordati di chiudere la sessione quando hai finito.`, "ok");
        H.mostra("remoto_dispositivi");
      } catch (errore) {
        esito.className = "messaggio errore";
        esito.textContent = errore.message;
        e.target.disabled = false;
      }
    },
  }, crea("div", { classe: "riga" }, finestra));
  finestra.showModal();
  motivo.focus();
}

async function mostraDettagli(pc) {
  const { crea, api } = H;
  const finestra = crea("dialog", { classe: "finestra" }, document.body);
  finestra.addEventListener("close", () => finestra.remove());
  crea("button", { "aria-label": "Chiudi", testo: "✕" }, crea("form", { method: "dialog", classe: "chiudi" }, finestra));
  crea("h2", { testo: `ℹ ${pc.nome}` }, finestra);
  const corpo = crea("div", {}, finestra);
  crea("p", { classe: "tenue", testo: "Lettura dell'inventario dal PC…" }, corpo);
  finestra.showModal();
  try {
    const info = await api("GET", `/api/remoto/dispositivi/?nodo=${encodeURIComponent(pc.id)}`);
    corpo.replaceChildren();
    const righe = [
      ["Azienda / negozio / monitor", pc.monitor ? `${pc.monitor.cliente} › ${pc.monitor.sede} › ${pc.monitor.nome}` : "non abbinato"],
      ["Nome del PC", pc.host || pc.nome], ["Indirizzo IP", pc.ip || "—"], ["Sistema", info.sistema || pc.sistema || "—"],
      ["Versione", info.versione || "—"], ["Produttore / modello", [info.produttore, info.modello].filter(Boolean).join(" ") || "—"],
      ["Processore", info.processore || "—"], ["Memoria", byte(info.memoria)],
      ...(info.dischi || []).map((d) => [`Disco ${d.unita}`, `${byte(d.libero)} liberi su ${byte(d.totale)}`]),
    ];
    const corpoTabella = H.tabella(["", ""], corpo);
    for (const [nome, valore] of righe) {
      const tr = crea("tr", {}, corpoTabella);
      crea("th", { testo: nome }, tr);
      crea("td", { testo: valore }, tr);
    }
  } catch (errore) {
    corpo.replaceChildren(crea("p", { classe: "messaggio errore", testo: errore.message }));
  }
}

export async function schedaRemotoDispositivi() {
  const { crea, sezione, api, tabella, prova } = H;
  const [dati, io] = await Promise.all([api("GET", "/api/remoto/"), api("GET", "/api/io/")]);

  if (dati.sessioni_aperte.length) {
    const aperte = sezione("🔴 Sessioni aperte");
    const corpo = tabella(["PC", "Monitor", "Tecnico", "Da", "Motivo", ""], aperte);
    for (const s of dati.sessioni_aperte) {
      const tr = crea("tr", {}, corpo);
      crea("td", { testo: s.nome_pc }, tr);
      crea("td", { testo: s.nome_monitor ? `${s.nome_cliente} › ${s.nome_monitor}` : "—" }, tr);
      crea("td", { testo: s.tecnico }, tr);
      crea("td", { testo: durata(s.iniziata) }, tr);
      crea("td", { testo: s.motivo }, tr);
      crea("button", { testo: "Chiudi sessione", onclick: () => prova(() => api("POST", `/api/remoto/sessioni/${s.id}/chiudi/`), "Sessione chiusa nel registro.") }, crea("td", {}, tr));
    }
    crea("p", { classe: "tenue", testo: "«Chiudi sessione» la chiude nel registro; chiudi anche la finestra dello schermo remoto." }, aperte);
  }

  const box = sezione("🖥 Dispositivi");
  if (!dati.configurato || dati.errore) {
    nonConfigurato(box, dati);
    return;
  }
  const inLinea = dati.dispositivi.filter((d) => d.in_linea).length;
  crea("p", {
    classe: "nota",
    testo: `${dati.dispositivi.length} PC con l'agente del Controllo Remoto, ${inLinea} in linea. Il collegamento funziona in rete locale e da internet: è l'agente del PC a collegarsi al server, nei negozi non si apre nessuna porta.`,
  }, box);
  const filtri = crea("div", { classe: "riga" }, box);
  const aziende = [...new Set(dati.dispositivi.map((d) => d.monitor?.cliente || "— non abbinati —"))].sort();
  const azienda = H.campo("Azienda", H.scelta([["", "Tutte"], ...aziende.map((a) => [a, a])], ""), filtri);
  const cerca = H.campo("Cerca", crea("input", { type: "search", placeholder: "PC, negozio, monitor, IP…" }), filtri);
  const soloInLinea = crea("input", { type: "checkbox" });
  const etichetta = crea("label", { classe: "spunta" }, filtri);
  etichetta.append(soloInLinea, " solo in linea");
  const corpo = tabella(["", "PC", "Azienda › negozio › monitor", "Sistema", "IP", "Ultimo contatto", ""], box);
  const disegna = () => {
    corpo.replaceChildren();
    const testo = cerca.value.trim().toLowerCase();
    for (const pc of dati.dispositivi) {
      const dove = pc.monitor ? `${pc.monitor.cliente} › ${pc.monitor.sede} › ${pc.monitor.nome}` : "non abbinato";
      if (azienda.value && (pc.monitor?.cliente || "— non abbinati —") !== azienda.value) continue;
      if (soloInLinea.checked && !pc.in_linea) continue;
      if (testo && ![pc.nome, pc.host, dove, pc.ip].join(" ").toLowerCase().includes(testo)) continue;
      const tr = crea("tr", {}, corpo);
      crea("span", { classe: `pallino ${pc.in_linea ? "acceso" : "spento"}`, title: pc.in_linea ? "In linea" : "Spento o scollegato" }, crea("td", {}, tr));
      crea("td", { testo: pc.nome }, tr);
      crea("td", { testo: dove, classe: pc.monitor ? "" : "tenue" }, tr);
      crea("td", { testo: pc.sistema || "—" }, tr);
      crea("td", { testo: pc.ip || "—" }, tr);
      crea("td", { testo: pc.in_linea ? "adesso" : quando(pc.ultimo_contatto ? new Date(pc.ultimo_contatto).toISOString() : null) }, tr);
      const azioni = crea("td", { classe: "azioni" }, tr);
      crea("button", { classe: "primario senza-a-capo", testo: "🖥 Collegati", disabled: !pc.in_linea, title: pc.in_linea ? "" : "Il PC non è in linea.", onclick: () => chiediCollegamento(pc, io) }, azioni);
      crea("button", { testo: "ℹ Dettagli", disabled: !pc.in_linea, onclick: () => mostraDettagli(pc) }, azioni);
    }
    if (!corpo.children.length) crea("td", { colSpan: 7, classe: "vuoto", testo: dati.dispositivi.length ? "Nessun PC con questi filtri." : "Nessun PC ancora: l'agente si installa con il comando di installazione dei monitor e dei totem." }, crea("tr", {}, corpo));
  };
  for (const c of [azienda, cerca, soloInLinea]) c.addEventListener(c === cerca ? "input" : "change", disegna);
  disegna();
}

export async function schedaRemotoSessioni() {
  const { crea, sezione, api, tabella } = H;
  const sessioni = await api("GET", "/api/remoto/sessioni/");
  const box = sezione("📋 Sessioni di Controllo Remoto");
  crea("p", { classe: "nota", testo: "Chi si è collegato, a quale PC, quando, da dove, perché e per quanto. Le aziende vedono solo che c'è stato un intervento, nel loro Registro operazioni." }, box);
  if (!sessioni.length) {
    crea("p", { classe: "vuoto", testo: "Nessuna sessione finora." }, box);
    return;
  }
  const corpo = tabella(["Inizio", "Durata", "Tecnico", "PC", "Azienda › monitor", "Motivo", "Dal", "Chiusa da"], box);
  for (const s of sessioni) {
    const tr = crea("tr", {}, corpo);
    crea("td", { testo: quando(s.iniziata) }, tr);
    crea("td", { testo: s.chiusa ? durata(s.iniziata, s.chiusa) : `in corso (${durata(s.iniziata)})` }, tr);
    crea("td", { testo: s.tecnico }, tr);
    crea("td", { testo: s.nome_pc }, tr);
    crea("td", { testo: s.nome_monitor ? `${s.nome_cliente} › ${s.nome_monitor}` : "—" }, tr);
    crea("td", { testo: s.motivo }, tr);
    crea("td", { testo: s.indirizzo_ip || "—" }, tr);
    crea("td", { testo: s.chiusa_da === "scaduta" ? "scaduta (durata massima)" : s.chiusa_da || "—" }, tr);
  }
}

export async function schedaRemotoInstallazione() {
  const { crea, sezione, api } = H;
  const dati = await api("GET", "/api/remoto/");
  const box = sezione("⚙ Installazione del Controllo Remoto");
  if (!dati.configurato || dati.errore) nonConfigurato(box, dati);
  for (const testo of [
    "Sul server: MeshCentral (open source, licenza Apache-2.0) si installa da solo con l'aggiornamento di FuturaPro ed è raggiungibile solo sotto https://SERVER/mesh/, con lo stesso certificato del pannello.",
    "Sui PC: il comando di installazione dei monitor e dei totem («Hardware → Anagrafica Dispositivi Video», installazione dei PC) installa anche l'agente, in silenzio, come servizio di Windows. Sui PC già installati basta rilanciare lo stesso comando.",
    "Abbinamento: quando il player del PC manda il suo segnale periodico, il PC si abbina da solo al suo monitor, e quindi all'azienda e al negozio.",
    "Sicurezza: l'agente riconosce solo questo server; i tecnici entrano dal pannello con la verifica in due passaggi; sullo schermo del negozio compare sempre la barra «Teleassistenza FuturaPro in corso»; ogni sessione resta nel registro. Nessuna shell remota.",
    "Da fuori sede: funziona se il server è raggiungibile da internet (nome di dominio con la porta 443 aperta); altrimenti solo dalla rete interna o con una VPN.",
  ]) crea("p", { testo }, box);
  if (dati.console) {
    const console = sezione("🔧 Console di MeshCentral");
    crea("p", { classe: "nota", testo: "Solo per il SystemAdministrator: la console completa di MeshCentral (gruppi, agenti, impostazioni avanzate), già entrati. Il link vale due minuti." }, console);
    crea("button", { testo: "Apri la console", onclick: () => window.open(dati.console, "console-mesh", "popup,width=1440,height=900") }, console);
  }
}
