// «Profilo» (ognuno il suo: nome utente, nome, email, password) e «Utenti di piattaforma»
// (solo il SystemAdministrator: altri SystemAdministrator e tecnici di teleassistenza).

import { GRUPPI, VOCI } from "./menu.js";

let H = null;

export function preparaSchedeProfilo(strumenti) {
  H = strumenti;
}

const RUOLI = { admin_assoluto: "SystemAdministrator", tecnico: "Tecnico Teleassistenza", admin_cliente: "Administrator", user_cliente: "User" };

export async function schedaProfilo() {
  const { crea, sezione, campo, api, prova } = H;
  const io = await api("GET", "/api/io/");

  const dati = sezione("👤 Il mio profilo");
  crea("p", { classe: "nota", testo: `Ruolo: ${RUOLI[io.ruolo]}. Nome utente e password li cambi solo tu, confermando con la password attuale.` }, dati);
  const riga = crea("div", { classe: "riga" }, dati);
  const nome = campo("Nome", crea("input", { value: io.first_name || "", autocomplete: "given-name", "data-aiuto": "Il tuo nome, come compare nel registro delle operazioni." }), riga);
  const cognome = campo("Cognome", crea("input", { value: io.last_name || "", autocomplete: "family-name", "data-aiuto": "Il tuo cognome." }), riga);
  const ruolo = { admin_assoluto: "Panoramica", admin_cliente: "Panoramica", tecnico: "Stato e allarmi", user_cliente: "Creazione palinsesto" }[io.ruolo];
  const voci = VOCI.filter((v) => v.visibile(io)).sort((a, b) => GRUPPI.indexOf(a.gruppo) - GRUPPI.indexOf(b.gruppo));
  const iniziale = campo("Pagina iniziale", H.scelta([["", `Quella consigliata per il ruolo (${ruolo})`], ...voci.map((v) => [v.chiave, v.gruppo ? `${v.gruppo} · ${v.titolo}` : v.titolo])], io.pagina_iniziale), riga);
  iniziale.dataset.aiuto = "La pagina che si apre dopo l'accesso.";
  const email = campo("Email", crea("input", { type: "email", value: io.email || "", size: 30, autocomplete: "email", "data-aiuto": "Il tuo indirizzo email (facoltativo)." }), riga);
  crea("button", {
    classe: "primario", testo: "Salva", "data-aiuto": "Salva nome, cognome, pagina iniziale ed email.",
    onclick: () => prova(() => api("PATCH", "/api/io/", { first_name: nome.value, last_name: cognome.value, email: email.value, pagina_iniziale: iniziale.value }), "Profilo salvato."),
  }, dati);

  const accesso = sezione("🔑 Nome utente e password");
  const r1 = crea("div", { classe: "riga" }, accesso);
  const utente = campo("Nome utente", crea("input", { value: io.username, autocomplete: "username", "data-aiuto": "Il nome con cui entri nel pannello. Lettere, numeri e @ . + - _" }), r1);
  const nuova = campo("Nuova password (almeno 10 caratteri)", crea("input", { type: "password", autocomplete: "new-password", "data-aiuto": "Lascia vuoto per non cambiarla. Almeno 10 caratteri, non troppo simile al nome utente né troppo comune." }), r1);
  const ripeti = campo("Ripeti la nuova password", crea("input", { type: "password", autocomplete: "new-password", "data-aiuto": "Scrivila di nuovo, per evitare errori di battitura." }), r1);
  const r2 = crea("div", { classe: "riga" }, accesso);
  const attuale = campo("Password attuale", crea("input", { type: "password", autocomplete: "current-password", "data-aiuto": "Serve a confermare che sei proprio tu." }), r2);
  crea("button", {
    classe: "primario", testo: "Cambia", "data-aiuto": "Cambia nome utente e/o password. Resti collegato.",
    onclick: () => prova(async () => {
      if (nuova.value !== ripeti.value) throw new Error("Le due password nuove non coincidono.");
      const corpo = { password_attuale: attuale.value };
      if (utente.value.trim() !== io.username) corpo.username = utente.value.trim();
      if (nuova.value) corpo.password = nuova.value;
      if (!corpo.username && !corpo.password) throw new Error("Non hai cambiato né il nome utente né la password.");
      const aggiornato = await api("PATCH", "/api/io/", corpo);
      H.stato.io.username = aggiornato.username;
      document.getElementById("utente").textContent = `${aggiornato.username} · ${RUOLI[aggiornato.ruolo].replace(" Teleassistenza", "")}`;
    }, "Fatto."),
  }, r2);
}

export async function schedaUtentiPiattaforma() {
  const { crea, sezione, campo, scelta, tabella, api, prova, elenco } = H;
  const utenti = await elenco("/api/piattaforma/utenti/");

  const nuovo = sezione("Nuovo utente di piattaforma");
  crea("p", {
    classe: "nota",
    testo: "Gli utenti di piattaforma non appartengono a un'azienda: il SystemAdministrator gestisce tutto (aziende, Administrator, aspetto); "
      + "il Tecnico Teleassistenza vede gli schermi di tutte le aziende per l'assistenza. Gli Administrator di un'azienda si creano in «Utenti», scegliendo l'azienda in alto.",
  }, nuovo);
  const riga = crea("div", { classe: "riga" }, nuovo);
  const nome = campo("Nome utente", crea("input", { autocomplete: "off", "data-aiuto": "Il nome con cui entrerà nel pannello." }), riga);
  const password = campo("Password (almeno 10 caratteri)", crea("input", { type: "password", autocomplete: "new-password", "data-aiuto": "La password iniziale: potrà cambiarla dal suo Profilo." }), riga);
  const ruolo = campo("Ruolo", scelta([["admin_assoluto", "SystemAdministrator"], ["tecnico", "Tecnico Teleassistenza"]]), riga);
  ruolo.dataset.aiuto = "SystemAdministrator: tutti i poteri. Tecnico Teleassistenza: vede e assiste gli schermi, non gestisce aziende e utenti.";
  crea("button", {
    classe: "primario", testo: "Crea utente", "data-aiuto": "Crea l'utente di piattaforma.",
    onclick: () => prova(async () => {
      await api("POST", "/api/piattaforma/utenti/", { username: nome.value.trim(), password: password.value, ruolo: ruolo.value });
    }, "Utente creato."),
  }, nuovo);

  const box = sezione("Utenti di piattaforma");
  const corpo = tabella(["Utente", "Ruolo", "Attivo", ""], box);
  for (const u of utenti) {
    const io = u.id === H.stato.io.id;
    const r = crea("tr", {}, corpo);
    crea("td", { testo: io ? `${u.username} (tu)` : u.username }, r);
    const sceltaRuolo = scelta([["admin_assoluto", "SystemAdministrator"], ["tecnico", "Tecnico Teleassistenza"]], u.ruolo);
    sceltaRuolo.disabled = io;
    sceltaRuolo.dataset.aiuto = io ? "Il tuo ruolo non lo puoi cambiare da solo." : "Cambia il ruolo di questo utente.";
    sceltaRuolo.addEventListener("change", () => prova(() => api("PATCH", `/api/piattaforma/utenti/${u.id}/`, { ruolo: sceltaRuolo.value }), "Ruolo cambiato."));
    crea("td", {}, r).appendChild(sceltaRuolo);
    const attivo = crea("input", { type: "checkbox", checked: u.is_active, disabled: io, "data-aiuto": "Un utente disattivato non può più entrare (ma resta nel registro)." }, crea("td", {}, r));
    attivo.addEventListener("change", () => prova(() => api("PATCH", `/api/piattaforma/utenti/${u.id}/`, { is_active: attivo.checked }), "Salvato."));
    const azioni = crea("td", { classe: "azioni" }, r);
    if (io) {
      crea("button", { testo: "Il mio profilo", "data-aiuto": "Il tuo nome utente e la tua password si cambiano dal Profilo.", onclick: () => H.mostra("profilo") }, azioni);
      continue;
    }
    crea("button", {
      testo: "Nuova password", "data-aiuto": "Imposta una nuova password per questo utente (ad es. se l'ha dimenticata).",
      onclick: () => {
        const nuova = prompt(`Nuova password per ${u.username} (almeno 10 caratteri):`);
        if (nuova) prova(() => api("PATCH", `/api/piattaforma/utenti/${u.id}/`, { password: nuova }), "Password cambiata.");
      },
    }, azioni);
    crea("button", {
      testo: "Elimina", classe: "pericolo", "data-aiuto": "Elimina l'utente di piattaforma.",
      onclick: () => confirm(`Eliminare ${u.username}?`) && prova(() => api("DELETE", `/api/piattaforma/utenti/${u.id}/`), "Eliminato."),
    }, azioni);
  }
}
