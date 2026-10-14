// Le schede del gruppo «Schermi» oltre a «Monitor»: accensione e spegnimento, stato e
// allarmi, fasce di download. Gli strumenti (api, crea, sezione…) arrivano da pannello.js.
// I testi che arrivano dai dati passano sempre da textContent.

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
