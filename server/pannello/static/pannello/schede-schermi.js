// Le schede degli schermi oltre all'anagrafica: accensione e spegnimento, stato e allarmi,
// fasce di download, anagrafica delle stampanti ticket. Gli strumenti (api, crea, sezione…) arrivano da pannello.js.
// I testi che arrivano dai dati passano sempre da textContent.

import { sezioneInvii } from "./invii.js";

let H = null;

export function preparaSchedeSchermi(strumenti) {
  H = strumenti;
}

const GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

// «Lun–Sab 07:30–21:00» da una fascia.
function descriviFascia(f) {
  const g = [...f.giorni].sort();
  let giorni;
  if (g.length === 7) giorni = "Tutti i giorni";
  else if (g.length > 2 && g.every((x, i) => i === 0 || x === g[i - 1] + 1)) giorni = `${GIORNI[g[0]]}–${GIORNI[g[g.length - 1]]}`;
  else giorni = g.map((x) => GIORNI[x]).join(", ");
  return `${giorni} ${f.dalle}–${f.alle}${f.alle < f.dalle ? " (fino al giorno dopo)" : ""}`;
}

// Le festività nazionali italiane di un anno (Pasquetta compresa).
function festivita(anno) {
  // Pasqua: algoritmo di Gauss/Meeus.
  const a = anno % 19, b = Math.floor(anno / 100), c = anno % 100, d = Math.floor(b / 4), e = b % 4;
  const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const mese = Math.floor((h + l - 7 * m + 114) / 31);
  const giorno = ((h + l - 7 * m + 114) % 31) + 1;
  const pasquetta = new Date(anno, mese - 1, giorno + 1);
  const iso = (d2) => `${d2.getFullYear()}-${String(d2.getMonth() + 1).padStart(2, "0")}-${String(d2.getDate()).padStart(2, "0")}`;
  return [
    `${anno}-01-01`, `${anno}-01-06`, iso(pasquetta), `${anno}-04-25`, `${anno}-05-01`, `${anno}-06-02`,
    `${anno}-08-15`, `${anno}-11-01`, `${anno}-12-08`, `${anno}-12-25`, `${anno}-12-26`,
  ];
}

// Una settimana disegnata: 7 righe da 24 ore, verde quando lo schermo è acceso.
function settimana(fasce, genitore) {
  const crea = H.crea;
  const box = crea("div", { classe: "settimana-orari" }, genitore);
  const minuti = (t) => parseInt(t.slice(0, 2), 10) * 60 + parseInt(t.slice(3, 5), 10);
  const ore = crea("div", { classe: "ore-settimana" }, box);
  crea("span", {}, ore);
  const scala = crea("div", { classe: "scala-ore" }, ore);
  for (const h of [0, 6, 12, 18, 24]) {
    const s = crea("span", { testo: `${h}` }, scala);
    s.style.left = `${(h / 24) * 100}%`;
  }
  GIORNI.forEach((nome, giorno) => {
    const riga = crea("div", { classe: "giorno-settimana" }, box);
    crea("span", { testo: nome }, riga);
    const barra = crea("div", { classe: "barra-giorno" }, riga);
    const pezzo = (da, a) => {
      const p = crea("span", { classe: "acceso" }, barra);
      Object.assign(p.style, { left: `${(da / 1440) * 100}%`, width: `${((a - da) / 1440) * 100}%` });
    };
    for (const f of fasce) {
      const da = minuti(f.dalle);
      const a = minuti(f.alle);
      if (da < a) { if (f.giorni.includes(giorno)) pezzo(da, a); }
      else {
        if (f.giorni.includes(giorno)) pezzo(da, 1440);
        if (f.giorni.includes((giorno + 6) % 7)) pezzo(0, a);
      }
    }
  });
  return box;
}

function destinatariTesto(o, dati) {
  const parti = [];
  for (const [campo, elenco, etichetta] of [["insegne", dati.insegne, "insegna"], ["gruppi", dati.gruppi, "gruppo"], ["monitor", dati.monitor, "schermo"]]) {
    for (const id of o[campo]) {
      const v = elenco.find((x) => x.id === id);
      if (v) parti.push(`${etichetta} ${v.nome}`);
    }
  }
  return parti.join(" · ") || "nessuno schermo";
}

export async function schedaAccensione() {
  const { crea, sezione, api, prova } = H;
  const [orari, insegne, gruppi, monitor] = await Promise.all([
    H.tutteLePagine("/api/orari/"), H.tutteLePagine("/api/insegne/"), H.tutteLePagine("/api/gruppi/"), H.tutteLePagine("/api/monitor/"),
  ]);
  const dati = { insegne, gruppi, monitor };
  const gestione = H.ruoloGestione();

  const intro = sezione("Accensione e spegnimento");
  crea("p", {
    classe: "nota",
    testo: "Fuori dagli orari scelti gli schermi vanno a riposo: schermo nero, senza audio, senza dirette. All'ora di apertura ripartono da soli, anche senza rete. "
      + "Uno schermo senza orario resta sempre acceso. Se più orari valgono per lo stesso schermo vince il più preciso: quello scelto per lo schermo, poi per il suo gruppo, poi per l'insegna. "
      + "Un evento straordinario accende lo schermo anche fuori orario.",
  }, intro);
  crea("p", {
    classe: "nota",
    testo: "Per spegnere davvero il monitor (e non solo mostrare il nero) imposta nel computer del monitor «Spegni lo schermo dopo 5 minuti»: a riposo il player lascia che il sistema lo spenga. Provalo prima su un solo monitor, per verificare che al mattino si riaccenda.",
  }, intro);
  if (gestione) crea("button", { classe: "primario", testo: "＋ Nuovo orario", onclick: () => modulo({ nome: "", fasce: [{ giorni: [0, 1, 2, 3, 4, 5], dalle: "07:30", alle: "21:00" }], chiusure: [], attivo: true, insegne: [], gruppi: [], monitor: [] }) }, intro);
  const editor = crea("div", {}, intro);

  const elenco = sezione("Orari");
  if (!orari.length) crea("p", { classe: "vuoto", testo: "Nessun orario: tutti gli schermi restano sempre accesi." }, elenco);
  for (const o of orari) {
    const scheda = crea("article", { classe: `orario${o.attivo ? "" : " spento"}` }, elenco);
    const testa = crea("div", { classe: "testa-orario" }, scheda);
    crea("strong", { testo: o.nome }, testa);
    if (!o.attivo) crea("span", { classe: "etichetta-tenue", testo: "sospeso" }, testa);
    crea("span", { classe: "tenue", testo: destinatariTesto(o, dati) }, testa);
    crea("div", { classe: "fasce-orario", testo: o.fasce.map(descriviFascia).join(" · ") || "Nessuna fascia: sempre spento" }, scheda);
    if (o.chiusure.length) {
      const prossime = o.chiusure.filter((d) => d >= new Date().toISOString().slice(0, 10));
      crea("div", { classe: "tenue", testo: `Chiuso: ${prossime.slice(0, 6).map((d) => new Date(`${d}T00:00`).toLocaleDateString("it-IT", { day: "numeric", month: "short" })).join(", ")}${prossime.length > 6 ? ` e altri ${prossime.length - 6} giorni` : ""}` }, scheda);
    }
    settimana(o.fasce, scheda);
    if (gestione) {
      const azioni = crea("div", { classe: "riga" }, scheda);
      crea("button", { testo: "Modifica", onclick: () => modulo(structuredClone(o)) }, azioni);
      crea("button", { testo: o.attivo ? "Sospendi" : "Riattiva", onclick: () => prova(() => api("PATCH", `/api/orari/${o.id}/`, { attivo: !o.attivo }), "Salvato: gli schermi lo ricevono entro un minuto.") }, azioni);
      crea("button", { testo: "Elimina", classe: "pericolo", onclick: () => confirm(`Eliminare l'orario «${o.nome}»? Gli schermi interessati resteranno sempre accesi.`) && prova(() => api("DELETE", `/api/orari/${o.id}/`), "Orario eliminato.") }, azioni);
    }
  }
  const senza = monitor.filter((m) => !orari.some((o) => o.attivo && (o.monitor.includes(m.id) || m.gruppi.some((g) => o.gruppi.includes(g)))));
  if (orari.length && senza.length && !orari.some((o) => o.insegne.length)) {
    crea("p", { classe: "nota", testo: `Sempre accesi (nessun orario): ${senza.map((m) => m.nome).join(", ")}.` }, elenco);
  }

  function modulo(o) {
    editor.replaceChildren();
    const box = crea("div", { classe: "modulo-orario" }, editor);
    crea("h3", { testo: o.id ? `Modifica «${o.nome}»` : "Nuovo orario" }, box);
    const nome = H.campo("Nome", crea("input", { value: o.nome, placeholder: "es. Orario negozi", maxLength: 200 }), box);
    nome.addEventListener("input", () => (o.nome = nome.value));

    crea("h4", { testo: "Quando è acceso" }, box);
    const fasce = crea("div", {}, box);
    const anteprima = crea("div", {}, box);
    const ridisegna = () => {
      fasce.replaceChildren();
      o.fasce.forEach((f, i) => {
        const riga = crea("div", { classe: "riga fascia" }, fasce);
        GIORNI.forEach((g, n) => {
          crea("button", {
            type: "button", classe: `giorno${f.giorni.includes(n) ? " scelto" : ""}`, testo: g,
            onclick: () => { f.giorni = f.giorni.includes(n) ? f.giorni.filter((x) => x !== n) : [...f.giorni, n].sort(); ridisegna(); },
          }, riga);
        });
        const dalle = crea("input", { type: "time", value: f.dalle }, riga);
        riga.append(" – ");
        const alle = crea("input", { type: "time", value: f.alle }, riga);
        dalle.addEventListener("change", () => { f.dalle = dalle.value; ridisegna(); });
        alle.addEventListener("change", () => { f.alle = alle.value; ridisegna(); });
        crea("button", { type: "button", classe: "pericolo", testo: "✕", title: "Togli la fascia", onclick: () => { o.fasce.splice(i, 1); ridisegna(); } }, riga);
      });
      anteprima.replaceChildren();
      settimana(o.fasce.filter((f) => f.giorni.length && f.dalle && f.alle), anteprima);
    };
    ridisegna();
    const pronti = crea("div", { classe: "riga" }, box);
    crea("button", { type: "button", testo: "＋ Fascia", onclick: () => { o.fasce.push({ giorni: [0, 1, 2, 3, 4, 5], dalle: "08:00", alle: "20:00" }); ridisegna(); } }, pronti);
    crea("button", { type: "button", classe: "leggero", testo: "Lun–Sab 8–21, Dom 9–13", onclick: () => { o.fasce = [{ giorni: [0, 1, 2, 3, 4, 5], dalle: "08:00", alle: "21:00" }, { giorni: [6], dalle: "09:00", alle: "13:00" }]; ridisegna(); } }, pronti);
    crea("button", { type: "button", classe: "leggero", testo: "Con pausa pranzo 13–16", onclick: () => { o.fasce = [{ giorni: [0, 1, 2, 3, 4, 5], dalle: "08:00", alle: "13:00" }, { giorni: [0, 1, 2, 3, 4, 5], dalle: "16:00", alle: "20:30" }]; ridisegna(); } }, pronti);

    crea("h4", { testo: "Giorni di chiusura (tutto il giorno spento)" }, box);
    const chiusure = crea("div", { classe: "chiusure" }, box);
    const disegnaChiusure = () => {
      chiusure.replaceChildren();
      for (const d of o.chiusure) {
        const chip = crea("span", { classe: "chip-data", testo: new Date(`${d}T00:00`).toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short", year: "numeric" }) }, chiusure);
        crea("button", { type: "button", testo: "✕", "aria-label": "Togli", onclick: () => { o.chiusure = o.chiusure.filter((x) => x !== d); disegnaChiusure(); } }, chip);
      }
      if (!o.chiusure.length) crea("span", { classe: "tenue", testo: "Nessuna." }, chiusure);
    };
    disegnaChiusure();
    const aggiungi = crea("div", { classe: "riga" }, box);
    const data = crea("input", { type: "date" }, aggiungi);
    crea("button", { type: "button", testo: "Aggiungi", onclick: () => { if (data.value && !o.chiusure.includes(data.value)) { o.chiusure = [...o.chiusure, data.value].sort(); disegnaChiusure(); } } }, aggiungi);
    const anno = new Date().getFullYear();
    for (const a of [anno, anno + 1]) {
      crea("button", {
        type: "button", classe: "leggero", testo: `Festività ${a}`,
        "data-aiuto": "Aggiunge Capodanno, Epifania, Pasquetta, 25 aprile, 1° maggio, 2 giugno, Ferragosto, Ognissanti, Immacolata, Natale e Santo Stefano. Togli quelle in cui il negozio è aperto.",
        onclick: () => { o.chiusure = [...new Set([...o.chiusure, ...festivita(a)])].sort(); disegnaChiusure(); },
      }, aggiungi);
    }

    crea("h4", { testo: "Per quali schermi" }, box);
    const scelte = crea("div", {}, box);
    const chips = (titolo, voci, campo) => {
      if (!voci.length) return;
      const riga = crea("div", { classe: "riga" }, scelte);
      crea("span", { classe: "etichetta", testo: titolo }, riga);
      for (const v of voci) {
        crea("button", {
          type: "button", classe: `giorno${o[campo].includes(v.id) ? " scelto" : ""}`, testo: v.nome,
          onclick: (e) => { o[campo] = o[campo].includes(v.id) ? o[campo].filter((x) => x !== v.id) : [...o[campo], v.id]; e.target.classList.toggle("scelto"); },
        }, riga);
      }
    };
    chips("Insegne", insegne, "insegne");
    chips("Gruppi", gruppi, "gruppi");
    chips("Schermi", monitor, "monitor");

    const piede = crea("div", { classe: "riga" }, box);
    crea("button", { type: "button", testo: "Annulla", onclick: () => editor.replaceChildren() }, piede);
    crea("button", {
      type: "button", classe: "primario", testo: o.id ? "Salva l'orario" : "Crea l'orario",
      onclick: () => {
        if (!o.nome.trim()) return H.avvisa("Dai un nome all'orario.");
        if (!o.insegne.length && !o.gruppi.length && !o.monitor.length) return H.avvisa("Scegli per quali schermi vale.");
        const corpo = { nome: o.nome.trim(), fasce: o.fasce.filter((f) => f.giorni.length), chiusure: o.chiusure, attivo: o.attivo, insegne: o.insegne, gruppi: o.gruppi, monitor: o.monitor };
        prova(() => (o.id ? api("PATCH", `/api/orari/${o.id}/`, corpo) : api("POST", "/api/orari/", corpo)), "Orario salvato: gli schermi lo ricevono entro un minuto.");
      },
    }, piede);
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// --- Stato e allarmi ------------------------------------------------------------------------

function daQuanto(iso) {
  const minuti = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (minuti < 60) return `${minuti} min`;
  if (minuti < 48 * 60) return `${Math.floor(minuti / 60)} h ${minuti % 60} min`;
  return `${Math.floor(minuti / 1440)} giorni`;
}

export async function schedaStato() {
  const { crea, sezione, api, prova } = H;
  const dati = await api("GET", "/api/stato-schermi/?giorni=7");
  const gestione = H.ruoloGestione();

  const riepilogo = sezione("Stato degli schermi");
  const conta = (f) => dati.schermi.filter(f).length;
  const tessere = crea("div", { classe: "tessere-stato" }, riepilogo);
  for (const [n, testo, classe] of [
    [conta((s) => s.online && !s.riposo), "in linea", "ok"],
    [conta((s) => s.online && s.riposo), "a riposo (fuori orario)", "riposo"],
    [conta((s) => !s.online && s.ultimo_contatto), "scollegati", "male"],
    [conta((s) => !s.ultimo_contatto), "mai collegati", "tenue"],
  ]) {
    const t = crea("div", { classe: `tessera ${classe}` }, tessere);
    crea("strong", { testo: String(n) }, t);
    crea("span", { testo: testo }, t);
  }

  const corpo = H.tabella(["", "Schermo", "Sede", "Stato", "Orario", "Disponibilità ultimi 7 giorni", "Player"], riepilogo);
  for (const s of dati.schermi) {
    const riga = crea("tr", {}, corpo);
    crea("span", { classe: `pallino ${s.online ? (s.riposo ? "riposo" : "acceso") : "spento"}` }, crea("td", {}, riga));
    crea("td", { testo: s.nome }, riga);
    crea("td", { testo: s.sede }, riga);
    const stato = crea("td", {}, riga);
    stato.textContent = s.online ? (s.riposo ? "A riposo" : "In linea") : s.ultimo_contatto ? `Scollegato da ${daQuanto(s.ultimo_contatto)}` : "Mai collegato";
    if (!s.online && s.ultimo_contatto) stato.className = "attenzione";
    if (s.problema) crea("div", { classe: "problema-schermo", testo: `⚠ ${s.problema.testo}` }, stato);
    crea("td", { testo: s.orario || "sempre acceso" }, riga);
    // Una barretta per giorno: la parte verde è il tempo in linea sul tempo in cui doveva essere acceso.
    const cella = crea("td", {}, riga);
    const barre = crea("div", { classe: "barre-disponibilita" }, cella);
    let somma = 0;
    let attesi = 0;
    for (const giorno of dati.giorni) {
      const [minuti, riposo] = s.presenze[giorno] || [0, 0];
      const atteso = s.atteso[giorno] || 0;
      const senzaDati = !s.dati_dal || giorno < s.dati_dal;
      const quota = atteso && !senzaDati ? Math.min(1, (minuti - riposo) / atteso) : null;
      if (quota !== null) { somma += Math.min(atteso, minuti - riposo); attesi += atteso; }
      const barra = crea("span", { classe: senzaDati ? "nessuno" : quota === null ? "chiuso" : quota > 0.95 ? "pieno" : quota > 0.6 ? "medio" : "basso" }, barre);
      barra.style.setProperty("--quota", quota === null ? "100%" : `${Math.max(4, quota * 100)}%`);
      barra.title = `${new Date(`${giorno}T00:00`).toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" })}: `
        + (senzaDati ? "nessun dato" : atteso ? `in linea ${Math.round((minuti - riposo) / 60 * 10) / 10} h su ${Math.round(atteso / 60 * 10) / 10} h previste` : "spento per orario");
    }
    crea("span", { classe: "percentuale", testo: attesi ? `${Math.round((somma / attesi) * 100)}%` : "—" }, cella);
    // La versione del player che gira davvero; se non è l'ultima, si aggiorna da solo al prossimo segnale.
    const versione = crea("td", { testo: s.versione || "—", classe: "tenue" }, riga);
    if (s.versione && dati.versione_attuale && s.versione !== dati.versione_attuale) {
      crea("div", {
        classe: "attenzione", testo: "⟳ da aggiornare",
        "data-aiuto": `L'ultima versione è ${dati.versione_attuale}. Lo schermo si aggiorna da solo entro un minuto dal prossimo segnale; un player di una versione precedente alla 1.5 va riavviato una volta a mano.`,
      }, versione);
    } else if (s.versione) versione.dataset.aiuto = "La versione del player che gira su questo schermo: è l'ultima.";
  }

  const allarmi = sezione("🔔 Allarmi via email");
  crea("p", {
    classe: "nota",
    testo: "Facoltativi. Se uno schermo non risponde per più dei minuti scelti, parte una email (una sola per scollegamento) e, se vuoi, un'altra quando torna in linea. "
      + "Fuori dal suo orario di accensione uno schermo spento non è un guasto.",
  }, allarmi);
  if (!dati.email_configurata) {
    const avviso = crea("p", { classe: "attenzione", testo: "L'azienda non ha ancora un server email: gli allarmi restano nello storico qui sotto ma le email non partono. " }, allarmi);
    crea("button", { testo: "Imposta il server email", onclick: () => H.mostra("email") }, avviso);
  }
  const a = dati.allarmi;
  const attivo = crea("input", { type: "checkbox", checked: a.attivo, disabled: !gestione });
  const l1 = crea("label", { classe: "spunta interruttore" }, crea("div", {}, allarmi)); l1.append(attivo, " Allarmi attivi");
  const riga = crea("div", { classe: "riga" }, allarmi);
  const email = H.campo("Email (separate da virgola)", crea("input", { value: a.email.join(", "), placeholder: "es. tecnico@azienda.it, negozio@azienda.it", disabled: !gestione, size: 44 }), riga);
  const minuti = H.campo("Dopo", H.scelta([[5, "5 minuti"], [10, "10 minuti"], [15, "15 minuti"], [30, "30 minuti"], [60, "1 ora"], [120, "2 ore"]], a.minuti), riga);
  minuti.disabled = !gestione;
  const riga2 = crea("div", { classe: "riga" }, allarmi);
  const orario = crea("input", { type: "checkbox", checked: a.solo_in_orario, disabled: !gestione });
  const l2 = crea("label", { classe: "spunta" }, riga2); l2.append(orario, " Solo negli orari di accensione");
  const ritorno = crea("input", { type: "checkbox", checked: a.avvisa_ritorno, disabled: !gestione });
  const l3 = crea("label", { classe: "spunta" }, riga2); l3.append(ritorno, " Avvisa anche quando torna in linea");
  const indirizzi = () => email.value.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
  if (gestione) {
    const azioni = crea("div", { classe: "riga" }, allarmi);
    crea("button", {
      classe: "primario", testo: "Salva",
      onclick: () => prova(() => api("PUT", "/api/stato-schermi/", { attivo: attivo.checked, email: indirizzi(), minuti: parseInt(minuti.value, 10), solo_in_orario: orario.checked, avvisa_ritorno: ritorno.checked }), "Allarmi salvati."),
    }, azioni);
    crea("button", {
      testo: "Invia un'email di prova", disabled: !dati.email_configurata,
      onclick: async () => {
        try {
          await api("POST", "/api/stato-schermi/", { email: indirizzi() });
          H.avvisa("Email di prova inviata: controlla la casella (anche lo spam).", "ok");
        } catch (errore) {
          H.avvisa(errore.message);
        }
      },
    }, azioni);
  }

  await sezioneInvii(H, "schermi", { nomePredefinito: "Disponibilità degli schermi" });

  const storico = sezione("Storico");
  crea("p", { classe: "nota", testo: `${dati.eventi.length ? `Ultimo allarme: ${dati.eventi[0].monitor}, ${new Date(dati.eventi[0].quando).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" })}. ` : "Nessun allarme finora. "}Lo storico completo, con il tempo fuori linea di ogni schermo, è in «Report & Log → Storico allarmi».` }, storico);
  crea("button", { testo: "Apri lo storico allarmi", onclick: () => H.mostra("storico_allarmi") }, storico);
}

// --- Fasce di download ------------------------------------------------------------------------

export async function schedaDownload() {
  const { crea, sezione, api, prova } = H;
  const d = await api("GET", "/api/download/");
  const box = sezione("Fasce di download");
  crea("p", {
    classe: "nota",
    testo: "Facoltative. Per non rallentare la rete del negozio (casse, bilance) gli schermi possono scaricare i file nuovi solo in una fascia oraria, per esempio di notte, e a una velocità massima. "
      + "Intanto restano in onda le promozioni già scaricate; quelle nuove partono appena i loro file sono arrivati. "
      + "Uno schermo appena installato scarica subito, e i file degli eventi straordinari delle prossime 24 ore non aspettano la fascia.",
  }, box);
  const attivo = crea("input", { type: "checkbox", checked: d.attivo });
  const l = crea("label", { classe: "spunta interruttore" }, crea("div", {}, box));
  l.append(attivo, " Scarica solo nella fascia");
  const riga = crea("div", { classe: "riga" }, box);
  const dalle = H.campo("Dalle", crea("input", { type: "time", value: d.dalle }), riga);
  const alle = H.campo("Alle", crea("input", { type: "time", value: d.alle }), riga);
  const kbps = H.campo("Velocità massima per schermo", H.scelta([
    [0, "Senza limite"], [128, "128 KB/s (≈1 Mbit/s)"], [256, "256 KB/s (≈2 Mbit/s)"], [512, "512 KB/s (≈4 Mbit/s)"],
    [1024, "1 MB/s (≈8 Mbit/s)"], [2048, "2 MB/s (≈16 Mbit/s)"],
  ], d.kbps), riga);
  crea("p", { classe: "tenue", testo: "La velocità vale anche fuori fascia: con «Senza limite» uno schermo usa tutta la banda libera mentre scarica." }, box);
  const azioni = crea("div", { classe: "riga" }, box);
  crea("button", {
    classe: "primario", testo: "Salva",
    onclick: () => prova(() => api("PUT", "/api/download/", { attivo: attivo.checked, dalle: dalle.value, alle: alle.value, kbps: parseInt(kbps.value, 10) }), "Salvato: gli schermi lo ricevono entro un minuto."),
  }, azioni);
  crea("button", {
    testo: "⚡ Scarica adesso (per 2 ore)",
    "data-aiuto": "Per le urgenze: per due ore gli schermi scaricano subito, senza aspettare la fascia.",
    onclick: () => prova(() => api("POST", "/api/download/"), "Per le prossime due ore gli schermi scaricano subito."),
  }, azioni);
  if (d.subito_fino && Date.parse(d.subito_fino) > Date.now()) {
    crea("p", { classe: "nota", testo: `«Scarica adesso» attivo fino alle ${new Date(d.subito_fino).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}.` }, box);
  }
  for (const c of [attivo, dalle, alle, kbps]) c.disabled = !H.ruoloGestione();
}

// --- Anagrafica Stampanti Ticket (Hardware) -------------------------------------------
// Solo l'elenco delle stampanti dei negozi: l'abbinamento ai totem si fa in «Anagrafica
// Dispositivi Video». La stampa di prova la esegue un totem abbinato e in linea.

export const TIPI_STAMPANTE = [
  ["epson", "Epson di rete (ePOS-Print)"],
  ["browser", "Stampante di sistema del PC del totem"],
];

function esitoProva(p) {
  const ora = (iso) => new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  const dove = p.totem ? ` (da «${p.totem}»)` : "";
  if (p.stato === "in_attesa") return [`⏳ Prova in corso${dove}…`, "tenue"];
  if (p.stato === "riuscita") return [`✅ ${ora(p.quando)}${dove}: ${p.messaggio}`, "ok"];
  if (p.stato === "fallita") return [`❌ ${ora(p.quando)}${dove}: ${p.messaggio}`, "errore"];
  if (p.stato === "senza_risposta") return [`⚠️ Il totem${dove} non ha risposto: spento o scollegato?`, "errore"];
  return ["—", "tenue"];
}

let attesaProva = null;

export async function schedaStampanti() {
  const { crea, sezione, api, prova, campo, scelta, tabella, avvisa } = H;
  clearTimeout(attesaProva);
  const [stampanti, sedi, layoutTicket, modelli] = await Promise.all([
    H.elenco("/api/stampanti/"), H.elenco("/api/sedi/"), H.elenco("/api/layout-ticket/").catch(() => []), api("GET", "/api/stampanti/modelli/"),
  ]);
  const nomeModello = (k) => modelli.find((m) => m.chiave === k)?.nome || "Altra stampante";
  const modifica = H.ruoloGestione() || H.stato.io.ruolo === "tecnico";
  const nomeSede = (id) => sedi.find((s) => s.id === id)?.nome || "";

  // Il modulo serve sia per aggiungere sia per modificare (st = la stampante da modificare).
  const modulo = (box, st = null) => {
    const riga = crea("div", { classe: "riga" }, box);
    const nome = campo("Nome", crea("input", { value: st?.nome || "", placeholder: "es. Epson banco salumi", maxLength: 100 }), riga);
    const sede = campo("Sede", scelta(sedi.map((x) => [x.id, x.nome]), st?.sede), riga);
    const tipo = campo("Tipo", scelta(TIPI_STAMPANTE, st?.tipo || "epson"), riga);
    const indirizzo = campo("Indirizzo IP (Epson di rete)", crea("input", { value: st?.indirizzo || "", placeholder: "es. 192.168.1.50", maxLength: 100 }), riga);
    const modello = campo("Modello", scelta(modelli.map((m) => [m.chiave, m.nome]), modelli.some((m) => m.chiave === st?.modello) ? st.modello : "TM-T20IV"), riga);
    const carta = campo("Carta", scelta([[80, "80 mm"], [58, "58 mm"]], st?.carta || 80), riga);
    const larghezza = crea("p", { classe: "tenue" }, box);
    const descriviModello = () => {
      const m = modelli.find((x) => x.chiave === modello.value);
      const punti = m?.carte[carta.value] || 576;
      larghezza.textContent = `Larghezza stampabile: ${(punti / 8).toFixed(1).replace(".", ",")} mm (${punti} punti a 203 dpi). ${m?.note || ""}`;
    };
    modello.addEventListener("change", descriviModello);
    carta.addEventListener("change", descriviModello);
    descriviModello();
    const layout = campo("Layout ticket", scelta([["", "— biglietto semplice —"], ...layoutTicket.map((l) => [l.id, `🧾 ${l.nome} (${l.carta} mm)`])], st?.layout || ""), riga);
    const riga2 = crea("div", { classe: "riga" }, box);
    const intestazione = campo("Intestazione (vuoto = dal layout)", crea("input", { value: st?.intestazione || "", maxLength: 60, size: 28 }), riga2);
    const messaggio = campo("Messaggio in fondo (vuoto = dal layout)", crea("input", { value: st?.messaggio || "", maxLength: 120, size: 34 }), riga2);
    const note = campo("Note", crea("input", { value: st?.note || "", maxLength: 200, size: 28 }), riga2);
    const aggiorna = () => (indirizzo.closest("label").hidden = tipo.value !== "epson");
    tipo.addEventListener("change", aggiorna);
    aggiorna();
    return () => ({
      nome: nome.value.trim(), sede: sede.value, tipo: tipo.value, indirizzo: tipo.value === "epson" ? indirizzo.value : "",
      modello: modello.value, carta: parseInt(carta.value, 10), layout: layout.value || null, intestazione: intestazione.value, messaggio: messaggio.value, note: note.value,
    });
  };

  const intro = sezione("Anagrafica Stampanti Ticket");
  crea("p", {
    classe: "nota",
    testo: "L'elenco delle stampanti dei biglietti dei negozi, ognuna con il suo Layout Ticket (Impostazioni · Layout Ticket). Ogni totem si abbina alla sua stampante in «Anagrafica Dispositivi Video» (colonna «Totem»). "
      + "Un totem senza stampante abbinata stampa come indicato nella zona «prendi il numero» del layout.",
  }, intro);
  crea("p", {
    classe: "tenue",
    testo: "Epson di rete (es. TM-T20IV con scheda Ethernet): indirizzo IP fisso e ePOS-Print attivo; se il totem usa il player in HTTPS, il certificato della stampante va accettato una volta dal browser del totem. "
      + "Stampante di sistema: quella predefinita di Windows sul PC del totem (Chrome con --kiosk-printing).",
  }, intro);
  if (modifica) {
    if (!sedi.length) crea("p", { classe: "nota", testo: "Prima crea una sede, in «Sedi e gruppi»." }, intro);
    else {
      const valori = modulo(intro);
      crea("button", { classe: "primario", testo: "Aggiungi stampante", onclick: () => prova(() => api("POST", "/api/stampanti/", valori()), "Stampante aggiunta.") }, intro);
    }
  }

  const box = sezione("Stampanti");
  if (!stampanti.length) {
    crea("p", { classe: "vuoto", testo: "Nessuna stampante in anagrafica." }, box);
    return;
  }
  const corpo = tabella(["Nome", "Sede", "Tipo", "Indirizzo", "Modello", "Layout ticket", "Abbinata ai totem", "Ultima prova", ""], box);
  let inAttesa = false;
  for (const st of stampanti) {
    const riga = crea("tr", {}, corpo);
    crea("td", { testo: st.nome, title: st.note || "" }, riga);
    crea("td", { testo: nomeSede(st.sede) }, riga);
    crea("td", { testo: TIPI_STAMPANTE.find(([v]) => v === st.tipo)?.[1] || st.tipo }, riga);
    crea("td", { testo: st.indirizzo || "—" }, riga);
    crea("td", { testo: `${nomeModello(st.modello)} · ${st.carta} mm (${st.punti} punti)` }, riga);
    crea("td", { testo: layoutTicket.find((l) => l.id === st.layout)?.nome || "biglietto semplice" }, riga);
    const abbinati = crea("td", {}, riga);
    if (!st.abbinata_a.length) abbinati.append("— nessuno —");
    for (const m of st.abbinata_a) {
      const d = crea("div", {}, abbinati);
      crea("span", { classe: `pallino ${m.online ? "acceso" : "spento"}` }, d);
      d.append(` ${m.nome}`);
    }
    const [testo, classe] = esitoProva(st.prova);
    crea("td", { classe: `esito-prova ${classe}`, testo }, riga);
    if (st.prova.stato === "in_attesa") inAttesa = true;
    const azioni = crea("td", { classe: "azioni" }, riga);
    crea("button", {
      testo: "🖨 Prova",
      "data-aiuto": "Un totem abbinato e in linea stampa un biglietto «PROVA STAMPA» (non consuma numeri); l'esito compare qui.",
      disabled: !st.abbinata_a.some((m) => m.online),
      onclick: () => prova(() => api("POST", `/api/stampanti/${st.id}/prova/`), "Prova chiesta al totem."),
    }, azioni);
    if (modifica) {
      crea("button", {
        testo: "Modifica",
        onclick: () => {
          const dettaglio = crea("tr", {}, null);
          const cella = crea("td", { colSpan: 9 }, dettaglio);
          riga.after(dettaglio);
          const valori = modulo(cella, st);
          const pulsanti = crea("div", { classe: "riga" }, cella);
          crea("button", { classe: "primario", testo: "Salva", onclick: () => prova(() => api("PATCH", `/api/stampanti/${st.id}/`, valori()), "Salvato: i totem abbinati lo ricevono entro un minuto.") }, pulsanti);
          crea("button", { testo: "Annulla", onclick: () => dettaglio.remove() }, pulsanti);
        },
      }, azioni);
      crea("button", {
        testo: "Elimina", classe: "pericolo",
        onclick: () => confirm(`Eliminare «${st.nome}»?${st.abbinata_a.length ? " I totem abbinati torneranno a stampare come dice il layout." : ""}`)
          && prova(() => api("DELETE", `/api/stampanti/${st.id}/`), "Eliminata."),
      }, azioni);
    }
  }
  // Finché un totem deve rispondere alla prova, la scheda si aggiorna da sola.
  if (inAttesa) {
    attesaProva = setTimeout(() => { if (H.stato.scheda === "stampanti") H.mostra("stampanti").catch((err) => avvisa(err.message)); }, 3000);
  }
}
