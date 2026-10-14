// Le schede del gruppo «Code»: tempi d'attesa e coda sul telefono.
// Gli strumenti (api, crea, sezione…) arrivano da pannello.js. I testi dei dati passano da textContent.

import { sezioneInvii } from "./invii.js";

let H = null;

export function preparaSchedeCode(strumenti) {
  H = strumenti;
}

const GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"];
const minuti = (m) => (m === null || m === undefined ? "—" : m < 1 ? "< 1 min" : `${Math.round(m)} min`);
const coloreAttesa = (m) => (m === null ? "var(--linea)" : m < 3 ? "#2e9d57" : m < 6 ? "#9bc53d" : m < 10 ? "#f2b134" : m < 15 ? "#ef7d32" : "#d93a3a");

// --- Tempi d'attesa --------------------------------------------------------------------------

export async function schedaAttese() {
  const { crea, sezione, api } = H;
  const filtro = H.stato.filtroAttese || (H.stato.filtroAttese = { giorni: 30, reparto: "" });
  const al = new Date();
  const dal = new Date(al.getTime() - (filtro.giorni - 1) * 86400000);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const [dati, reparti] = await Promise.all([
    api("GET", `/api/statistiche-code/?dal=${iso(dal)}&al=${iso(al)}${filtro.reparto ? `&reparto=${filtro.reparto}` : ""}`),
    H.tutteLePagine("/api/reparti/"),
  ]);

  const testa = sezione("Tempi d'attesa ai banchi");
  crea("p", {
    classe: "nota",
    testo: "Quanto aspettano i clienti tra il biglietto e la chiamata, reparto per reparto, ora per ora: per decidere i turni del personale. "
      + "I dati partono dai biglietti emessi dal totem (o dal pulsante del server); con il totem arrivano anche se la rete era caduta, appena torna.",
  }, testa);
  const riga = crea("div", { classe: "riga" }, testa);
  const periodo = H.campo("Periodo", H.scelta([[7, "Ultimi 7 giorni"], [30, "Ultimi 30 giorni"], [90, "Ultimi 3 mesi"], [365, "Ultimo anno"]], filtro.giorni), riga);
  const reparto = H.campo("Reparto", H.scelta([["", "Tutti"], ...reparti.map((r) => [r.id, r.nome])], filtro.reparto), riga);
  for (const c of [periodo, reparto]) {
    c.addEventListener("change", () => {
      Object.assign(filtro, { giorni: parseInt(periodo.value, 10), reparto: reparto.value });
      H.mostra("attese");
    });
  }

  const conDati = dati.reparti.filter((r) => r.biglietti || r.serviti);
  if (!conDati.length) {
    crea("p", { classe: "vuoto", testo: "Nessun biglietto nel periodo. Le statistiche si riempiono man mano che il totem emette biglietti e i banchi chiamano." }, testa);
    await sezioneInvii(H, "attese", { nomePredefinito: "Tempi d'attesa" });
    return;
  }

  // Riepilogo per reparto.
  const corpo = H.tabella(["Reparto", "Biglietti", "Serviti", "Attesa media", "9 clienti su 10 entro", "Attesa massima", "Rinunce", "Serviti all'ora"], testa);
  for (const r of conDati) {
    const tr = crea("tr", {}, corpo);
    const nome = crea("td", {}, tr);
    crea("span", { classe: "pallino", style: `background:${r.colore}` }, nome);
    nome.append(` ${r.nome}`);
    crea("small", { classe: "tenue", testo: ` ${r.sede}` }, nome);
    crea("td", { testo: String(r.biglietti) }, tr);
    crea("td", { testo: String(r.serviti) }, tr);
    const media = crea("td", {}, tr);
    crea("span", { classe: "bollino-attesa", testo: minuti(r.attesa_media), style: `background:${coloreAttesa(r.attesa_media)}` }, media);
    crea("td", { testo: minuti(r.attesa_p90) }, tr);
    crea("td", { testo: minuti(r.attesa_massima) }, tr);
    crea("td", { testo: r.biglietti ? `${r.rinunce} (${Math.round((r.rinunce / r.biglietti) * 100)}%)` : "—", title: "Biglietti mai chiamati (clienti andati via o numeri saltati)" }, tr);
    crea("td", { testo: r.serviti_ora ?? "—" }, tr);
  }

  // Mappa giorno × ora.
  const mappa = sezione("Quando si aspetta di più");
  crea("p", { classe: "nota", testo: "Attesa media per giorno della settimana e ora (il numero piccolo è quanti biglietti). Verde: meno di 3 minuti; rosso: più di 15." }, mappa);
  const ore = dati.mappa.map((c) => c.ora);
  const dalle = Math.min(...ore);
  const alle = Math.max(...ore);
  const griglia = crea("div", { classe: "mappa-attese" }, mappa);
  griglia.style.gridTemplateColumns = `90px repeat(${alle - dalle + 1}, minmax(34px, 1fr))`;
  crea("span", {}, griglia);
  for (let h = dalle; h <= alle; h += 1) crea("span", { classe: "ora", testo: `${h}` }, griglia);
  const cella = new Map(dati.mappa.map((c) => [`${c.giorno}-${c.ora}`, c]));
  GIORNI.forEach((nome, g) => {
    crea("span", { classe: "giorno", testo: nome }, griglia);
    for (let h = dalle; h <= alle; h += 1) {
      const c = cella.get(`${g}-${h}`);
      const el = crea("span", { classe: "cella" }, griglia);
      if (!c) continue;
      el.style.background = coloreAttesa(c.attesa_media);
      el.title = `${nome} ${h}–${h + 1}: attesa media ${minuti(c.attesa_media)}, ${c.biglietti} biglietti`;
      crea("b", { testo: c.attesa_media === null ? "—" : String(Math.round(c.attesa_media)) }, el);
      crea("small", { testo: String(c.biglietti) }, el);
    }
  });
  // Le fasce peggiori, con abbastanza biglietti per contare.
  const critiche = dati.mappa.filter((c) => c.attesa_media !== null && c.biglietti >= 5).sort((a, b) => b.attesa_media - a.attesa_media).slice(0, 3);
  if (critiche.length && critiche[0].attesa_media >= 6) {
    const consigli = crea("div", { classe: "consigli-attese" }, mappa);
    crea("strong", { testo: "Fasce da rinforzare" }, consigli);
    for (const c of critiche.filter((x) => x.attesa_media >= 6)) {
      crea("div", { testo: `${GIORNI[c.giorno]} ${c.ora}:00–${c.ora + 1}:00 · attesa media ${minuti(c.attesa_media)} su ${c.biglietti} biglietti: valuta un addetto in più al banco.` }, consigli);
    }
  }

  // Andamento giorno per giorno.
  const andamento = sezione("Giorno per giorno");
  const massimo = Math.max(1, ...dati.giorni.map((g) => g.biglietti));
  const barre = crea("div", { classe: "andamento-attese" }, andamento);
  for (const g of dati.giorni) {
    const colonna = crea("div", { classe: "colonna" }, barre);
    const barra = crea("span", {}, colonna);
    barra.style.height = `${(g.biglietti / massimo) * 100}%`;
    barra.style.background = coloreAttesa(g.attesa_media);
    colonna.title = `${new Date(`${g.giorno}T00:00`).toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" })}: ${g.biglietti} biglietti, attesa media ${minuti(g.attesa_media)}`;
  }
  crea("p", { classe: "tenue", testo: "Altezza: biglietti del giorno. Colore: attesa media." }, andamento);
  await sezioneInvii(H, "attese", { nomePredefinito: "Tempi d'attesa" });
}

// --- Coda sul telefono ----------------------------------------------------------------------

export async function schedaTelefono() {
  const { crea, sezione, api, prova } = H;
  const t = await api("GET", "/api/coda-telefono/");
  const box = sezione("Coda sul telefono");
  crea("p", {
    classe: "nota",
    testo: "Facoltativa. Sul biglietto del totem si stampa un QR: il cliente lo inquadra con il telefono e segue la coda dalla sua rete dati (4G/5G), senza app e senza registrarsi. "
      + "La pagina mostra il suo numero, quello servito, quanti ne ha davanti e l'attesa stimata, e suona e vibra quando si avvicina il suo turno. Nessun dato personale.",
  }, box);
  const stato = crea("div", { classe: t.url_pubblico ? "nota" : "attenzione" }, box);
  if (t.url_pubblico) stato.textContent = `Indirizzo pubblico del server: ${t.url_pubblico} — i QR portano a ${t.url_pubblico.replace(/\/$/, "")}/b/…`;
  else {
    stato.textContent = "Manca l'indirizzo pubblico del server: i telefoni dei clienti arrivano da internet, non dalla rete del negozio. "
      + "Serve un nome (es. coda.miodominio.it) che punti al server, con la porta 443 aperta verso internet, e la riga FP_URL_PUBBLICO=https://coda.miodominio.it nel file .env del server. "
      + "Finché manca, i biglietti escono senza QR.";
  }
  const attivo = crea("input", { type: "checkbox", checked: t.attivo });
  const l = crea("label", { classe: "spunta interruttore" }, crea("div", {}, box));
  l.append(attivo, " QR sul biglietto e pagina della coda attivi");
  const riga = crea("div", { classe: "riga" }, box);
  const testo = H.campo("Testo sotto il QR", crea("input", { value: t.testo, maxLength: 80, size: 36 }), riga);
  const avviso = H.campo("Avvisa quando mancano", H.scelta([[1, "1 numero"], [2, "2 numeri"], [3, "3 numeri"], [5, "5 numeri"], [8, "8 numeri"]], t.avviso_a), riga);
  const azioni = crea("div", { classe: "riga" }, box);
  crea("button", {
    classe: "primario", testo: "Salva",
    onclick: () => prova(() => api("PUT", "/api/coda-telefono/", { attivo: attivo.checked, testo: testo.value, avviso_a: parseInt(avviso.value, 10) }), "Salvato: i totem stampano il QR dal prossimo biglietto."),
  }, azioni);
  crea("a", { classe: "pulsante", testo: "Guarda la pagina di prova", href: "/b/prova", target: "_blank" }, azioni);
  for (const c of [attivo, testo, avviso]) c.disabled = !H.ruoloGestione();

  const come = sezione("Come funziona senza il Wi-Fi del negozio");
  for (const frase of [
    "Il telefono usa la sua rete dati: la pagina arriva dal server via internet, non dalla rete del negozio.",
    "Con il totem le code stanno nel negozio: il totem manda al server biglietti e chiamate ogni pochi secondi.",
    "Se la linea del negozio cade, la coda in negozio continua (totem, bilance, monitor); il telefono mostra l'ultimo numero noto e invita a guardare i monitor.",
    "Il codice del QR è casuale e vale solo per la giornata: non si può indovinare quello di un altro cliente.",
  ]) crea("p", { classe: "nota", testo: `• ${frase}` }, come);
}
