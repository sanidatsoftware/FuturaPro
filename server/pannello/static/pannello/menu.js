// Il menu comune al pannello e alla «Creazione palinsesto»: stesse voci, stesse regole
// di visibilità, e per ognuna la spiegazione che compare al passaggio del mouse.

const gestione = (io) => ["admin_assoluto", "admin_cliente"].includes(io.ruolo);
const nonTecnico = (io) => io.ruolo !== "tecnico";

// pagina: un'altra pagina, nella stessa finestra; incorporata: una pagina mostrata dentro il
// pannello, sotto il menu; le altre sono schede del pannello.
export const GRUPPI = ["Hardware", "Contenuti", "Code", "Plugin", "Report & Log", "Impostazioni"];

export const VOCI = [
  { chiave: "clienti", titolo: "Clienti", visibile: (io) => io.ruolo === "admin_assoluto", serveCliente: false,
    aiuto: "Le aziende clienti: crearle, abilitarne le funzioni (monitor, utenti, spazio) e il loro primo amministratore." },
  { chiave: "monitor", gruppo: "Hardware", titolo: "Anagrafica Dispositivi Video", visibile: () => true,
    aiuto: "Gli schermi e i totem: abbinarne di nuovi con il codice, sede, gruppi, layout (anche diverso per ogni schermo), rotazione, il Totem Master delle code, la stampante dei biglietti, cosa è in onda e se sono in linea." },
  { chiave: "stampanti", gruppo: "Hardware", titolo: "Anagrafica Stampanti Ticket", visibile: (io) => io.ruolo !== "user_cliente",
    aiuto: "L'elenco delle stampanti dei biglietti dei negozi (Epson di rete o di sistema), con la stampa di prova. Ai totem si abbinano in «Anagrafica Dispositivi Video»." },
  { chiave: "palinsesto", gruppo: "Contenuti", titolo: "Creazione palinsesto", visibile: nonTecnico, pagina: "/palinsesto/",
    aiuto: "Carica le immagini, raggruppale in promozioni con le loro date e decidi con le campagne dove vanno in onda. C'è anche il calendario e l'importazione da CSV." },
  { chiave: "listini", gruppo: "Contenuti", titolo: "Listini", visibile: nonTecnico,
    aiuto: "Tabelle di prodotti e prezzi (es. banco salumi, panetteria) da mostrare sugli schermi con la zona «Listino»; si compilano qui, da Excel o dal gestionale." },
  { chiave: "info_prezzo", gruppo: "Plugin", titolo: "Info Prezzo", visibile: gestione,
    aiuto: "Facoltativo: passando un prodotto davanti al lettore di codici a barre, lo schermo mostra descrizione e prezzo, con il banner «Offerta» se è in offerta." },
  { chiave: "info_ingredienti", gruppo: "Plugin", titolo: "Info Ingredienti", visibile: gestione,
    aiuto: "Facoltativo: passando l'etichetta di un prodotto della bilancia, lo schermo mostra ingredienti, allergeni e (se vuoi) il prezzo." },
  { chiave: "stato", gruppo: "Report & Log", titolo: "Stato e allarmi", visibile: () => true,
    aiuto: "Quali schermi sono in linea, da quanto sono spenti o scollegati, la disponibilità degli ultimi giorni e gli avvisi via email." },
  { chiave: "distribuzione", gruppo: "Report & Log", titolo: "Distribuzione contenuti", visibile: () => true, serveCliente: false,
    aiuto: "Dal vivo: se i file del palinsesto e delle promozioni sono arrivati a ogni schermo, cosa stanno scaricando (con le barre di avanzamento) e cosa va in onda adesso. Il SystemAdministrator vede anche tutte le aziende insieme." },
  { chiave: "messa_in_onda", gruppo: "Report & Log", titolo: "Messa in onda", visibile: nonTecnico,
    aiuto: "Cosa è andato davvero in onda, dove e per quanto: rapporti per promozione, campagna, fornitore e negozio, da stampare o esportare." },
  { chiave: "attese", gruppo: "Report & Log", titolo: "Tempi d'attesa", visibile: nonTecnico,
    aiuto: "Quanto aspettano i clienti a ogni banco, per ora e per giorno: per decidere i turni del personale." },
  { chiave: "registro", gruppo: "Report & Log", titolo: "Registro operazioni", visibile: gestione,
    aiuto: "Chi ha fatto cosa e quando: promozioni, schermi, utenti, impostazioni. Non si modifica e si può scaricare per Excel." },
  { chiave: "storico_allarmi", gruppo: "Report & Log", titolo: "Storico allarmi", visibile: () => true,
    aiuto: "Quando gli schermi si sono scollegati e sono tornati in linea, e per quanto sono rimasti fuori." },
  { chiave: "reparti", gruppo: "Code", titolo: "Reparti ed eliminacode", visibile: nonTecnico,
    aiuto: "I reparti con il «prendi il numero»: nomi, colori, ordine, annunci registrati e i collegamenti per bilance e pulsantiere." },
  { chiave: "telefono", gruppo: "Code", titolo: "Coda sul telefono", visibile: gestione,
    aiuto: "Il QR sul biglietto: il cliente segue la coda dal suo telefono e viene avvisato quando tocca a lui." },
  { chiave: "layout", gruppo: "Impostazioni", titolo: "Layout Video", visibile: gestione, incorporata: "/editor/",
    aiuto: "L'editor grafico: come si divide lo schermo tra slide, orologio, meteo, notizie, listini, numeri dei reparti e pulsanti del totem." },
  { chiave: "layout_ticket", gruppo: "Impostazioni", titolo: "Layout Ticket", visibile: (io) => io.ruolo !== "user_cliente",
    aiuto: "Com'è fatto il biglietto stampato dal totem: logo, intestazione, reparto, numero e testo di fine biglietto, con carattere e grandezza di ogni elemento. Si sceglie per ogni stampante." },
  { chiave: "sedi", gruppo: "Impostazioni", titolo: "Sedi e gruppi", visibile: gestione,
    aiuto: "I punti vendita con la loro insegna e il totem delle code, e i gruppi di schermi usati per pubblicare." },
  { chiave: "utenti", gruppo: "Impostazioni", titolo: "Utenti", visibile: gestione,
    aiuto: "Chi accede al pannello del cliente, con quale ruolo ed eventualmente limitato ad alcune sedi. L'Administrator crea gli User della sua azienda; gli Administrator li crea il SystemAdministrator." },
  { chiave: "utenti_piattaforma", gruppo: "Impostazioni", titolo: "Utenti di piattaforma", visibile: (io) => io.ruolo === "admin_assoluto", serveCliente: false,
    aiuto: "Gli altri SystemAdministrator e i tecnici di teleassistenza: li crea e li gestisce solo il SystemAdministrator." },
  { chiave: "profilo", gruppo: "Impostazioni", titolo: "Profilo", visibile: () => true, serveCliente: false,
    aiuto: "Il tuo profilo: nome utente, nome, email e password (per cambiarli serve la password attuale)." },
  { chiave: "email", gruppo: "Impostazioni", titolo: "Email (server di posta)", visibile: gestione,
    aiuto: "Il server di posta dell'azienda da cui partono allarmi e rapporti: ogni azienda usa il suo dominio e la sua casella." },
  { chiave: "accensione", gruppo: "Impostazioni", titolo: "Accensione e spegnimento", visibile: nonTecnico,
    aiuto: "Gli orari in cui gli schermi sono accesi, per giorno della settimana, e i giorni di chiusura (es. festivi)." },
  { chiave: "download", gruppo: "Impostazioni", titolo: "Fasce di download", visibile: gestione,
    aiuto: "Quando e a quale velocità gli schermi scaricano i file nuovi, per non rallentare la rete del negozio (es. casse)." },
  { chiave: "banco", gruppo: "Impostazioni", titolo: "Banchi Code", visibile: nonTecnico, incorporata: "/banco/",
    aiuto: "La pagina per chiamare i numeri dal banco (Avanti, Indietro, Ripeti), la stessa che usano le bilance." },
  { chiave: "aspetto", gruppo: "Impostazioni", titolo: "Aspetto interfaccia", visibile: () => true, serveCliente: false,
    aiuto: "Tema chiaro, scuro o automatico delle pagine. Il SystemAdministrator qui sceglie anche nome e logo della piattaforma." },
];

function conCliente(url, cliente) {
  return cliente ? `${url}${url.includes("?") ? "&" : "?"}cliente=${encodeURIComponent(cliente)}` : url;
}

// Disegna il menu in «nav». Dentro il pannello «mostra(chiave)» cambia scheda; fuori
// (nella pagina del palinsesto) le schede del pannello diventano collegamenti.
export function disegnaMenu(nav, { io, attiva, cliente, mostra }) {
  nav.replaceChildren();
  const voce = (v) => {
    let el;
    if (v.pagina) {
      el = document.createElement("a");
      el.href = conCliente(v.pagina, cliente);
      el.textContent = v.titolo;
    } else if (mostra) {
      el = document.createElement("button");
      el.type = "button";
      el.textContent = v.titolo;
      el.addEventListener("click", () => { chiudiTendine(nav); mostra(v.chiave); });
    } else {
      el = document.createElement("a");
      el.href = `${conCliente("/pannello/", cliente)}#${v.chiave}`;
      el.textContent = v.titolo;
    }
    el.className = `scheda${attiva === v.chiave ? " attiva" : ""}`;
    el.dataset.aiuto = v.aiuto;
    return el;
  };
  const visibili = VOCI.filter((v) => v.visibile(io));
  // Prima le voci senza gruppo, poi un menu a tendina per gruppo.
  for (const v of visibili.filter((x) => !x.gruppo)) nav.appendChild(voce(v));
  for (const gruppo of GRUPPI) {
    const voci = visibili.filter((x) => x.gruppo === gruppo);
    if (!voci.length) continue;
    const scelta = voci.find((v) => v.chiave === attiva);
    const box = document.createElement("div");
    box.className = `gruppo-menu${scelta ? " attivo" : ""}`;
    const titolo = document.createElement("button");
    titolo.type = "button";
    titolo.className = `scheda titolo-gruppo${scelta ? " attiva" : ""}`;
    titolo.setAttribute("aria-haspopup", "true");
    titolo.textContent = scelta ? `${gruppo} · ${scelta.titolo}` : gruppo;
    const tendina = document.createElement("div");
    tendina.className = "tendina";
    for (const v of voci) tendina.appendChild(voce(v));
    titolo.addEventListener("click", (e) => {
      e.stopPropagation();
      const aperta = box.classList.contains("aperto");
      chiudiTendine(nav);
      box.classList.toggle("aperto", !aperta);
    });
    box.append(titolo, tendina);
    nav.appendChild(box);
  }
  if (!nav.dataset.ascolta) {
    nav.dataset.ascolta = "1";
    document.addEventListener("click", (e) => { if (!nav.contains(e.target)) chiudiTendine(nav); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") chiudiTendine(nav); });
  }
}

function chiudiTendine(nav) {
  for (const aperto of nav.querySelectorAll(".gruppo-menu.aperto")) aperto.classList.remove("aperto");
}

// Il cliente scelto da un utente di piattaforma: dall'indirizzo, altrimenti l'ultimo usato.
export function clienteRicordato() {
  const daIndirizzo = new URLSearchParams(location.search).get("cliente");
  if (daIndirizzo) return daIndirizzo;
  try {
    return localStorage.getItem("futurapro.pannello.cliente") || null;
  } catch {
    return null;
  }
}

export function ricordaCliente(id) {
  try {
    if (id) localStorage.setItem("futurapro.pannello.cliente", id);
    else localStorage.removeItem("futurapro.pannello.cliente");
  } catch {
    // Archivio del browser non disponibile: si sceglierà di nuovo.
  }
}
