// Le schede «Listini» (gruppo Contenuti) e «Messa in onda» (gruppo Report & Log) del pannello.
// Gli strumenti (api, crea, sezione…) arrivano da pannello.js. I testi dei dati passano da textContent.

import { sezioneInvii } from "./invii.js";

let H = null;

export function preparaSchedeContenuti(strumenti) {
  H = strumenti;
}

const UNITA = ["al kg", "all'etto", "al pezzo", "alla confezione", "al litro", "a porzione"];

// --- Listini ------------------------------------------------------------------------------------

export async function schedaListini() {
  const { crea, sezione, api, prova } = H;
  const listini = await H.tutteLePagine("/api/listini/");
  const scelto = H.stato.listino && listini.find((l) => l.id === H.stato.listino);

  const intro = sezione("Listini prezzi");
  crea("p", {
    classe: "nota",
    testo: "Facoltativi. Un listino è una tabella di prodotti e prezzi (es. banco salumi, panetteria, pescheria) che gli schermi mostrano con la zona «Listino prezzi» del layout, a pagine se le righe sono tante. "
      + "Si compila qui, si importa da Excel (CSV) o arriva da solo dal gestionale. Quando cambi un prezzo gli schermi lo mostrano entro un minuto, e lo tengono anche senza rete.",
  }, intro);
  const riga = crea("div", { classe: "riga" }, intro);
  const nome = H.campo("Nuovo listino", crea("input", { placeholder: "es. Banco salumi", maxLength: 200 }), riga);
  crea("button", {
    classe: "primario", testo: "Crea",
    onclick: () => prova(async () => {
      const nuovo = await api("POST", "/api/listini/", { nome: nome.value, righe: [] });
      H.stato.listino = nuovo.id;
    }, "Listino creato: aggiungi le righe o importa un CSV."),
  }, riga);
  if (listini.length) {
    const schede = crea("div", { classe: "schede-listini" }, intro);
    for (const l of listini) {
      crea("button", {
        type: "button", classe: `scheda-listino${scelto?.id === l.id ? " attiva" : ""}`, testo: `${l.nome} · ${l.righe.length}`,
        onclick: () => { H.stato.listino = l.id; H.mostra("listini"); },
      }, schede);
    }
  }
  if (scelto) disegnaListino(scelto);
  else if (listini.length) crea("p", { classe: "tenue", testo: "Scegli un listino per modificarlo." }, intro);
}

function disegnaListino(l) {
  const { crea, sezione, api, prova } = H;
  const righe = structuredClone(l.righe);
  let modificato = false;
  const box = sezione(`Listino «${l.nome}»`);
  if (l.errore_fonte) crea("p", { classe: "attenzione", testo: l.errore_fonte }, box);
  crea("p", { classe: "tenue", testo: `${righe.length} righe${l.aggiornato_il ? ` · aggiornato ${new Date(l.aggiornato_il).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" })}` : ""}${l.fonte_url ? " · dal gestionale/indirizzo: le modifiche fatte qui vengono sostituite al prossimo aggiornamento" : ""}` }, box);

  const tabella = crea("table", { classe: "tabella-listino" }, box);
  const testa = crea("tr", {}, crea("thead", {}, tabella));
  for (const t of ["", "Prodotto", "Prezzo €", "Unità", "Nota (es. OFFERTA)", "★", "Visibile", ""]) crea("th", { testo: t }, testa);
  const corpo = crea("tbody", {}, tabella);
  const lista = crea("datalist", { id: "unita-listino" }, box);
  for (const u of UNITA) crea("option", { value: u }, lista);
  const salva = crea("button", { classe: "primario", testo: "Salva il listino", disabled: true });
  const segna = () => { modificato = true; salva.disabled = false; salva.classList.add("attenzione"); };

  const disegnaRighe = () => {
    corpo.replaceChildren();
    righe.forEach((r, i) => {
      const tr = crea("tr", { classe: r.evidenza ? "evidenza" : "" }, corpo);
      crea("td", { classe: "tenue", testo: String(i + 1) }, tr);
      const campo = (chiave, { list, ...attributi }) => {
        const input = crea("input", { value: r[chiave] ?? "", ...attributi }, crea("td", {}, tr));
        if (list) input.setAttribute("list", list);
        input.addEventListener("input", () => { r[chiave] = input.value; segna(); });
        return input;
      };
      campo("prodotto", { maxLength: 120, placeholder: "es. Prosciutto crudo" });
      const prezzo = campo("prezzo", { inputMode: "decimal", classe: "corto", placeholder: "0,00", value: r.prezzo ? r.prezzo.replace(".", ",") : "" });
      prezzo.addEventListener("change", () => { r.prezzo = prezzo.value.replace(",", "."); });
      campo("unita", { list: "unita-listino", classe: "medio", maxLength: 30 });
      campo("nota", { classe: "medio", maxLength: 60 });
      const stella = crea("button", { type: "button", classe: `stella${r.evidenza ? " accesa" : ""}`, testo: "★", title: "In evidenza (fondo colorato)" }, crea("td", {}, tr));
      stella.addEventListener("click", () => { r.evidenza = !r.evidenza; segna(); disegnaRighe(); });
      const visibile = crea("input", { type: "checkbox", checked: r.visibile !== false }, crea("td", {}, tr));
      visibile.addEventListener("change", () => { r.visibile = visibile.checked; segna(); });
      const azioni = crea("td", { classe: "azioni" }, tr);
      crea("button", { type: "button", testo: "↑", title: "Sposta su", disabled: i === 0, onclick: () => { [righe[i - 1], righe[i]] = [righe[i], righe[i - 1]]; segna(); disegnaRighe(); } }, azioni);
      crea("button", { type: "button", testo: "↓", title: "Sposta giù", disabled: i === righe.length - 1, onclick: () => { [righe[i + 1], righe[i]] = [righe[i], righe[i + 1]]; segna(); disegnaRighe(); } }, azioni);
      crea("button", { type: "button", classe: "pericolo", testo: "✕", title: "Togli", onclick: () => { righe.splice(i, 1); segna(); disegnaRighe(); } }, azioni);
    });
  };
  disegnaRighe();
  const piede = crea("div", { classe: "riga" }, box);
  crea("button", {
    testo: "＋ Riga",
    onclick: () => { righe.push({ prodotto: "", prezzo: "", unita: "al kg", nota: "", evidenza: false, visibile: true }); segna(); disegnaRighe(); corpo.lastChild?.querySelector("input")?.focus(); },
  }, piede);
  piede.appendChild(salva);
  salva.addEventListener("click", () => prova(
    () => api("PATCH", `/api/listini/${l.id}/`, { righe: righe.filter((r) => r.prodotto.trim()).map((r) => ({ ...r, prezzo: String(r.prezzo || "").replace(",", ".") })) }),
    "Listino salvato: gli schermi lo mostrano entro un minuto.",
  ));
  window.onbeforeunload = () => (modificato ? true : undefined);

  // Excel / CSV
  const csv = sezione("Da Excel (CSV)");
  crea("p", {
    classe: "nota",
    testo: "Una riga per prodotto con le colonne: prodotto; prezzo; unità; nota; evidenza (sì per metterlo in risalto). L'intestazione è facoltativa, il separatore può essere ; o , e il prezzo «12,90» o «€ 12.90». L'importazione sostituisce tutte le righe.",
  }, csv);
  const rigaCsv = crea("div", { classe: "riga" }, csv);
  const file = crea("input", { type: "file", accept: ".csv,text/csv,.txt", hidden: true }, rigaCsv);
  crea("button", { testo: "Importa un file CSV", onclick: () => file.click() }, rigaCsv);
  file.addEventListener("change", () => {
    if (!file.files[0]) return;
    const dati = new FormData();
    dati.append("file", file.files[0]);
    prova(async () => {
      const esito = await api("POST", `/api/listini/${l.id}/importa/`, dati);
      if (esito.avvisi?.length) H.avvisa(`Importate ${esito.righe.length} righe. ${esito.avvisi.join(" ")}`, "ok");
    }, "Listino importato.");
  });
  const esporta = crea("a", { classe: "pulsante", testo: "Scarica come CSV", href: H.conCliente(`/api/listini/${l.id}/esporta/`) }, rigaCsv);
  esporta.setAttribute("download", `${l.nome}.csv`);

  // Dal gestionale
  const gestionale = sezione("Dal gestionale (automatico)");
  crea("p", {
    classe: "nota",
    testo: "Due modi, a scelta. 1) Il gestionale pubblica il CSV a un indirizzo internet: il server lo rilegge da solo ogni tanti minuti. "
      + "2) Il gestionale è nella rete locale: dopo ogni esportazione invia il CSV al server con la chiave del listino (il server non va a leggere nella rete interna, per sicurezza).",
  }, gestionale);
  const rigaUrl = crea("div", { classe: "riga" }, gestionale);
  const url = H.campo("Indirizzo del CSV (internet)", crea("input", { type: "url", value: l.fonte_url, placeholder: "https://…/listino.csv", size: 48 }), rigaUrl);
  const minuti = H.campo("Rileggi ogni", H.scelta([[5, "5 minuti"], [15, "15 minuti"], [30, "30 minuti"], [60, "1 ora"], [240, "4 ore"], [1440, "1 giorno"]], l.aggiorna_minuti), rigaUrl);
  crea("button", { testo: "Salva", onclick: () => prova(() => api("PATCH", `/api/listini/${l.id}/`, { fonte_url: url.value.trim(), aggiorna_minuti: parseInt(minuti.value, 10) }), url.value.trim() ? "Indirizzo salvato e letto." : "Indirizzo tolto.") }, rigaUrl);
  if (l.fonte_url) crea("button", { testo: "Rileggi adesso", onclick: () => prova(() => api("POST", `/api/listini/${l.id}/aggiorna/`), "Listino riletto.") }, rigaUrl);

  const rigaChiave = crea("div", { classe: "chiave" }, gestionale);
  crea("button", {
    testo: l.ha_chiave ? "Nuova chiave per il gestionale" : "Crea la chiave per il gestionale",
    onclick: async () => {
      if (l.ha_chiave && !confirm("La chiave attuale smetterà di funzionare. Continuare?")) return;
      try {
        const { chiave } = await api("POST", `/api/listini/${l.id}/chiave/`);
        rigaChiave.replaceChildren();
        crea("p", { classe: "nota", testo: "Copiala ora: non sarà più mostrata. Esempio di invio dopo l'esportazione (Windows, PowerShell o curl):" }, rigaChiave);
        crea("input", { readOnly: true, classe: "link", value: `curl -X POST -H "Authorization: Listino ${chiave}" --data-binary @listino.csv https://${location.host}/api/listini/carica/`, onfocus: (e) => e.target.select() }, rigaChiave);
      } catch (errore) {
        H.avvisa(errore.message);
      }
    },
  }, rigaChiave);
  if (l.ha_chiave) crea("button", { testo: "Revoca la chiave", classe: "pericolo", onclick: () => prova(() => api("DELETE", `/api/listini/${l.id}/chiave/`), "Chiave revocata.") }, rigaChiave);

  const fine = sezione("");
  crea("button", {
    testo: `Elimina il listino «${l.nome}»`, classe: "pericolo",
    onclick: () => confirm(`Eliminare il listino «${l.nome}»? Le zone che lo mostrano resteranno vuote.`) && prova(async () => {
      await api("DELETE", `/api/listini/${l.id}/`);
      H.stato.listino = null;
    }, "Listino eliminato."),
  }, fine);
}

// --- Messa in onda -----------------------------------------------------------------------------

const RAGGRUPPA = [["campagna", "Campagna"], ["promozione", "Promozione"], ["fornitore", "Fornitore"], ["contenuto", "Contenuto (immagine o video)"], ["sede", "Negozio"], ["monitor", "Schermo"], ["giorno", "Giorno"]];
const ore = (secondi) => (secondi >= 3600 ? `${Math.floor(secondi / 3600)} h ${Math.round((secondi % 3600) / 60)} min` : `${Math.round(secondi / 60)} min`);
const isoData = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export async function schedaMessaInOnda() {
  const { crea, sezione, api } = H;
  const f = H.stato.filtroOnda || (H.stato.filtroOnda = {
    dal: isoData(new Date(Date.now() - 29 * 86400000)), al: isoData(new Date()), raggruppa: "campagna", campagna: "", fornitore: "", sede: "",
  });
  const query = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const [dati, sedi] = await Promise.all([api("GET", `/api/messa-in-onda/?${query}`), H.tutteLePagine("/api/sedi/")]);

  const filtri = sezione("Messa in onda");
  filtri.classList.add("non-stampare");
  crea("p", {
    classe: "nota",
    testo: "Cosa è andato davvero sugli schermi, non solo cosa era programmato: ogni player annota ogni passaggio (anche senza rete, e lo manda appena può). "
      + "Utile per i fornitori che pagano lo spazio: scegli il periodo e il fornitore, poi stampa o scarica il rapporto.",
  }, filtri);
  const riga = crea("div", { classe: "riga" }, filtri);
  const dal = H.campo("Dal", crea("input", { type: "date", value: f.dal }), riga);
  const al = H.campo("Al", crea("input", { type: "date", value: f.al }), riga);
  const raggruppa = H.campo("Raggruppa per", H.scelta(RAGGRUPPA, f.raggruppa), riga);
  const campagna = H.campo("Campagna", H.scelta([["", "Tutte"], ...dati.scelte.campagne.map((c) => [c.id, c.nome])], f.campagna), riga);
  const fornitore = H.campo("Fornitore", H.scelta([["", "Tutti"], ...dati.scelte.fornitori.map((x) => [x, x])], f.fornitore), riga);
  const sede = H.campo("Negozio", H.scelta([["", "Tutti"], ...sedi.map((x) => [x.id, x.nome])], f.sede), riga);
  for (const [campo, controllo] of Object.entries({ dal, al, raggruppa, campagna, fornitore, sede })) {
    controllo.addEventListener("change", () => { f[campo] = controllo.value; H.mostra("messa_in_onda"); });
  }
  const azioni = crea("div", { classe: "riga" }, filtri);
  crea("a", { classe: "pulsante", testo: "Scarica per Excel (CSV)", href: H.conCliente(`/api/messa-in-onda/?${query}&formato=csv`) }, azioni);
  crea("button", { testo: "🖨 Stampa o salva in PDF", onclick: () => window.print() }, azioni);

  const rapporto = sezione("");
  rapporto.classList.add("rapporto-stampa");
  const intestazione = crea("div", { classe: "intestazione-rapporto" }, rapporto);
  crea("h2", { testo: "Rapporto di messa in onda" }, intestazione);
  const descrizione = [`Dal ${new Date(`${dati.dal}T00:00`).toLocaleDateString("it-IT")} al ${new Date(`${dati.al}T00:00`).toLocaleDateString("it-IT")}`];
  if (f.fornitore) descrizione.push(`fornitore ${f.fornitore}`);
  if (f.campagna) descrizione.push(`campagna ${dati.scelte.campagne.find((c) => c.id === f.campagna)?.nome || ""}`);
  if (f.sede) descrizione.push(`negozio ${sedi.find((x) => x.id === f.sede)?.nome || ""}`);
  crea("p", { classe: "tenue", testo: descrizione.join(" · ") }, intestazione);

  const t = dati.totale;
  const tessere = crea("div", { classe: "tessere-stato" }, rapporto);
  for (const [valore, testo] of [[t.passaggi.toLocaleString("it-IT"), "passaggi"], [ore(t.secondi), "in onda in totale"], [String(t.negozi), "negozi"], [String(t.schermi), "schermi"], [String(t.giorni), "giorni"]]) {
    const el = crea("div", { classe: "tessera ok" }, tessere);
    crea("strong", { testo: valore }, el);
    crea("span", { testo }, el);
  }
  if (!dati.righe.length) {
    crea("p", { classe: "vuoto", testo: "Nessun passaggio nel periodo. Il registro parte dall'aggiornamento dei player: i giorni precedenti non ci sono." }, rapporto);
    await invii(dati, sedi, f);
    return;
  }
  const massimo = Math.max(...dati.righe.map((r) => r.secondi), 1);
  const corpo = H.tabella([RAGGRUPPA.find(([k]) => k === dati.raggruppa)[1], "Passaggi", "In onda", "", "Negozi", "Schermi", "Giorni"], rapporto);
  for (const r of dati.righe) {
    const tr = crea("tr", {}, corpo);
    crea("td", { testo: dati.raggruppa === "giorno" ? new Date(`${r.nome}T00:00`).toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" }) : r.nome }, tr);
    crea("td", { testo: r.passaggi.toLocaleString("it-IT") }, tr);
    crea("td", { testo: ore(r.secondi) }, tr);
    const barra = crea("span", { classe: "barra-onda" }, crea("td", { classe: "cella-barra" }, tr));
    barra.style.width = `${(r.secondi / massimo) * 100}%`;
    crea("td", { testo: String(r.negozi) }, tr);
    crea("td", { testo: String(r.schermi) }, tr);
    crea("td", { testo: String(r.giorni) }, tr);
  }
  crea("p", { classe: "tenue", testo: `Generato il ${new Date().toLocaleString("it-IT")} da ${document.title.split("·").pop().trim() || "FuturaPro"}: dati registrati dagli schermi durante la messa in onda.` }, rapporto);
  await invii(dati, sedi, f);
}

function invii(dati, sedi, f) {
  return sezioneInvii(H, "messa_in_onda", {
    nomePredefinito: f.fornitore ? `Messa in onda ${f.fornitore}` : "Messa in onda",
    filtriAttuali: f,
    filtri: [
      { chiave: "raggruppa", etichetta: "Raggruppa per", scelte: RAGGRUPPA },
      { chiave: "fornitore", etichetta: "Solo il fornitore", scelte: [["", "Tutti"], ...dati.scelte.fornitori.map((x) => [x, x])] },
      { chiave: "campagna", etichetta: "Solo la campagna", scelte: [["", "Tutte"], ...dati.scelte.campagne.map((c) => [c.id, c.nome])], testo: (v) => dati.scelte.campagne.find((c) => c.id === v)?.nome || v },
      { chiave: "sede", etichetta: "Solo il negozio", scelte: [["", "Tutti"], ...sedi.map((x) => [x.id, x.nome])], testo: (v) => sedi.find((x) => x.id === v)?.nome || v },
    ],
  });
}
