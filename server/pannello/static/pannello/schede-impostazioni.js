// «Impostazioni → Email»: il server di posta dell'azienda (ognuna ha il suo dominio e la sua
// casella). Vale per tutte le email del cliente; i destinatari li sceglie ogni funzione.

let H = null;

export function preparaSchedeImpostazioni(strumenti) {
  H = strumenti;
}

export async function schedaEmail() {
  const { crea, sezione, api, prova } = H;
  const e = await api("GET", "/api/email/");
  const box = sezione("Email dell'azienda (server di posta)");
  crea("p", {
    classe: "nota",
    testo: "Il server SMTP e la casella da cui partono le email dell'azienda: allarmi degli schermi, rapporti di messa in onda e tempi d'attesa. "
      + "I destinatari si scelgono in ogni funzione. I dati si trovano nelle impostazioni della posta aziendale (o li dà chi la gestisce).",
  }, box);
  if (e.origine === "server" && !e.attivo) crea("p", { classe: "nota", testo: "Ora le email partono con il server email generale dell'installazione. Impostando qui quello dell'azienda, partiranno dal vostro dominio." }, box);
  const attivo = crea("input", { type: "checkbox", checked: e.attivo });
  const l = crea("label", { classe: "spunta interruttore" }, crea("div", {}, box));
  l.append(attivo, " Usa questo server per le email dell'azienda");
  const riga = crea("div", { classe: "riga" }, box);
  const host = H.campo("Server SMTP", crea("input", { value: e.host, placeholder: "es. smtp.miodominio.it", size: 28 }), riga);
  const porta = H.campo("Porta", crea("input", { type: "number", value: e.porta, min: 1, max: 65535, classe: "corto" }), riga);
  const sicurezza = H.campo("Sicurezza", H.scelta([["starttls", "STARTTLS (porta 587)"], ["ssl", "SSL/TLS (porta 465)"], ["nessuna", "Nessuna (sconsigliato)"]], e.sicurezza), riga);
  const riga2 = crea("div", { classe: "riga" }, box);
  const utente = H.campo("Utente", crea("input", { value: e.utente, placeholder: "es. avvisi@miodominio.it", size: 28, autocomplete: "off" }), riga2);
  const password = H.campo("Password", crea("input", { type: "password", placeholder: e.password_impostata ? "•••••••• (lascia vuoto per non cambiarla)" : "", size: 28, autocomplete: "new-password" }), riga2);
  const mittente = H.campo("Mittente", crea("input", { value: e.mittente, placeholder: "es. Supermercati Esempio <avvisi@miodominio.it>", size: 40 }), riga2);
  sicurezza.addEventListener("change", () => { if (sicurezza.value === "ssl") porta.value = 465; else if (sicurezza.value === "starttls") porta.value = 587; });
  const azioni = crea("div", { classe: "riga" }, box);
  crea("button", {
    classe: "primario", testo: "Salva",
    onclick: () => {
      const dati = { attivo: attivo.checked, host: host.value.trim(), porta: parseInt(porta.value, 10), sicurezza: sicurezza.value, utente: utente.value.trim(), mittente: mittente.value.trim() };
      if (password.value) dati.password = password.value;
      prova(() => api("PUT", "/api/email/", dati), "Impostazioni email salvate.");
    },
  }, azioni);
  const prova_a = crea("input", { type: "email", placeholder: "a chi mandare la prova", value: H.stato.io.email || "" }, azioni);
  crea("button", {
    testo: "Invia un'email di prova",
    onclick: async () => {
      try {
        const esito = await api("POST", "/api/email/", { a: prova_a.value.trim() });
        H.avvisa(`Email di prova inviata a ${esito.inviata}: controlla la casella (anche lo spam).`, "ok");
      } catch (errore) {
        H.avvisa(errore.message);
      }
    },
  }, azioni);
  crea("p", { classe: "tenue", testo: "La password è conservata cifrata e non viene mai mostrata. Per Gmail o Microsoft 365 serve di solito una «password per le app»." }, box);
}
