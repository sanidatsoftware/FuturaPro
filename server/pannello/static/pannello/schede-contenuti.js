// Le schede del gruppo «Contenuti» nel pannello: listini prezzi e messa in onda.
// Gli strumenti (api, crea, sezione…) arrivano da pannello.js. I testi dei dati passano da textContent.

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
