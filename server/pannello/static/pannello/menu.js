// Il menu comune al pannello e alla «Creazione palinsesto»: stesse voci, stesse regole
// di visibilità, e per ognuna la spiegazione che compare al passaggio del mouse.

const gestione = (io) => ["admin_assoluto", "admin_cliente"].includes(io.ruolo);
const nonTecnico = (io) => io.ruolo !== "tecnico";

// pagina: un'altra pagina, nella stessa finestra; esterna: si apre in una scheda nuova;
// le altre sono schede del pannello.
export const VOCI = [
  { chiave: "clienti", titolo: "Clienti", visibile: (io) => io.ruolo === "admin_assoluto", serveCliente: false,
    aiuto: "Le aziende clienti: crearle, abilitarne le funzioni (monitor, utenti, spazio) e il loro primo amministratore." },
  { chiave: "monitor", titolo: "Monitor", visibile: () => true,
    aiuto: "Gli schermi e i totem: abbinarne di nuovi con il codice, sede, gruppi, layout, rotazione, cosa è in onda e se sono in linea." },
  { chiave: "palinsesto", titolo: "Creazione palinsesto", visibile: nonTecnico, pagina: "/palinsesto/",
    aiuto: "Carica le immagini, raggruppale in promozioni con le loro date e decidi con le campagne dove vanno in onda. C'è anche il calendario e l'importazione da CSV." },
  { chiave: "reparti", titolo: "Reparti ed eliminacode", visibile: nonTecnico,
    aiuto: "I reparti con il «prendi il numero»: nomi, colori, ordine, e i collegamenti per bilance e pulsantiere." },
  { chiave: "layout", titolo: "Layout", visibile: gestione, esterna: "/editor/",
    aiuto: "L'editor grafico: come si divide lo schermo tra slide, orologio, meteo, notizie, numeri dei reparti e pulsanti del totem." },
  { chiave: "banco", titolo: "Banco", visibile: nonTecnico, esterna: "/banco/",
    aiuto: "La pagina per chiamare i numeri dal banco (Avanti, Indietro, Ripeti), la stessa che usano le bilance." },
  { chiave: "sedi", titolo: "Sedi e gruppi", visibile: gestione,
    aiuto: "I punti vendita con la loro insegna e il totem delle code, e i gruppi di schermi usati per pubblicare." },
  { chiave: "utenti", titolo: "Utenti", visibile: gestione,
    aiuto: "Chi accede al pannello del cliente, con quale ruolo ed eventualmente limitato ad alcune sedi." },
  { chiave: "aspetto", titolo: "Aspetto interfaccia", visibile: () => true, serveCliente: false,
    aiuto: "Tema chiaro, scuro o automatico delle pagine. L'Administrator Assoluto qui sceglie anche nome e logo della piattaforma." },
];

function conCliente(url, cliente) {
  return cliente ? `${url}${url.includes("?") ? "&" : "?"}cliente=${encodeURIComponent(cliente)}` : url;
}

// Disegna il menu in «nav». Dentro il pannello «mostra(chiave)» cambia scheda; fuori
// (nella pagina del palinsesto) le schede del pannello diventano collegamenti.
export function disegnaMenu(nav, { io, attiva, cliente, mostra }) {
  nav.replaceChildren();
  for (const voce of VOCI) {
    if (!voce.visibile(io)) continue;
    let el;
    if (voce.esterna) {
      el = document.createElement("a");
      el.href = conCliente(voce.esterna, cliente);
      el.target = "_blank";
      el.textContent = `${voce.titolo} ↗`;
    } else if (voce.pagina) {
      el = document.createElement("a");
      el.href = conCliente(voce.pagina, cliente);
      el.textContent = voce.titolo;
    } else if (mostra) {
      el = document.createElement("button");
      el.type = "button";
      el.textContent = voce.titolo;
      el.addEventListener("click", () => mostra(voce.chiave));
    } else {
      el = document.createElement("a");
      el.href = `${conCliente("/pannello/", cliente)}#${voce.chiave}`;
      el.textContent = voce.titolo;
    }
    el.className = `scheda${attiva === voce.chiave ? " attiva" : ""}`;
    el.dataset.aiuto = voce.aiuto;
    nav.appendChild(el);
  }
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
