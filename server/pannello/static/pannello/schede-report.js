// Le schede di «Report & Log» oltre a messa in onda e tempi d'attesa: il registro delle
// operazioni e lo storico degli allarmi. I testi dei dati passano da textContent.

let H = null;

export function preparaSchedeReport(strumenti) {
  H = strumenti;
}

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const quando = (t) => new Date(t).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "medium" });
const durata = (minuti) => (minuti < 60 ? `${minuti} min` : minuti < 2880 ? `${Math.floor(minuti / 60)} h ${minuti % 60} min` : `${Math.floor(minuti / 1440)} giorni`);
const RUOLI = { admin_assoluto: "SystemAdministrator", tecnico: "Tecnico", admin_cliente: "Administrator", user_cliente: "User" };

// «campagna_creata» → «Campagna creata»
const azione = (codice) => codice.charAt(0).toUpperCase() + codice.slice(1).replaceAll("_", " ");

// I dettagli più utili in una riga: nome, username, conteggi…
function dettagli(d) {
  if (!d || typeof d !== "object") return "";
  return Object.entries(d)
    .filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .map(([k, v]) => (["nome", "username"].includes(k) ? String(v) : `${k.replaceAll("_", " ")}: ${v === true ? "sì" : v === false ? "no" : v}`))
    .join(" · ");
}

// --- Registro operazioni ---------------------------------------------------------------------

export async function schedaRegistro() {
  const { crea, sezione, api } = H;
  const assoluto = H.stato.io.ruolo === "admin_assoluto";
  const f = H.stato.filtroRegistro || (H.stato.filtroRegistro = {
    dal: iso(new Date(Date.now() - 6 * 86400000)), al: iso(new Date()), utente: "", cerca: "", tutta: false, pagina: 1,
  });
  const base = f.tutta && assoluto ? "/api/piattaforma/audit/" : "/api/audit/";
  const query = new URLSearchParams(Object.entries({ dal: f.dal, al: f.al, utente: f.utente, cerca: f.cerca }).filter(([, v]) => v)).toString();
  const dati = await api("GET", `${base}?${query}&page=${f.pagina}`);

  const box = sezione("Registro operazioni");
  crea("p", {
    classe: "nota",
    testo: "Chi ha fatto cosa e quando: promozioni, campagne, schermi, utenti, impostazioni. Il registro non si può modificare né cancellare. "
      + "Le operazioni fatte dalla piattaforma per conto dell'azienda sono segnate.",
  }, box);
  const riga = crea("div", { classe: "riga" }, box);
  const dal = H.campo("Dal", crea("input", { type: "date", value: f.dal }), riga);
  const al = H.campo("Al", crea("input", { type: "date", value: f.al }), riga);
  const utente = H.campo("Utente", H.scelta([["", "Tutti"], ...(dati.utenti || []).map((u) => [u, u])], f.utente), riga);
  const cerca = H.campo("Cerca", crea("input", { value: f.cerca, placeholder: "es. promozione, nome di un monitor…", size: 26 }), riga);
  const applica = () => { Object.assign(f, { dal: dal.value, al: al.value, utente: utente.value, cerca: cerca.value.trim(), pagina: 1 }); H.mostra("registro"); };
  for (const c of [dal, al, utente]) c.addEventListener("change", applica);
  cerca.addEventListener("keydown", (e) => { if (e.key === "Enter") applica(); });
  if (assoluto) {
    const tutta = crea("input", { type: "checkbox", checked: f.tutta });
    const l = crea("label", { classe: "spunta" }, riga);
    l.append(tutta, " Tutta la piattaforma (tutte le aziende)");
    tutta.addEventListener("change", () => { f.tutta = tutta.checked; f.pagina = 1; H.mostra("registro"); });
  }
  const azioni = crea("div", { classe: "riga" }, box);
  crea("a", { classe: "pulsante", testo: "Scarica per Excel (CSV)", href: H.conCliente(`${base}?${query}&formato=csv`) }, azioni);
  crea("span", { classe: "tenue", testo: `${dati.count} operazioni` }, azioni);

  if (!dati.results.length) {
    crea("p", { classe: "vuoto", testo: "Nessuna operazione nel periodo." }, box);
    return;
  }
  const colonne = ["Quando", "Utente", "Operazione", "Dettagli"];
  if (f.tutta && assoluto) colonne.splice(2, 0, "Azienda");
  const corpo = H.tabella(colonne, box);
  for (const e of dati.results) {
    const tr = crea("tr", {}, corpo);
    crea("td", { testo: quando(e.quando), classe: "tenue" }, tr);
    const chi = crea("td", {}, tr);
    chi.append(e.utente || "—");
    crea("small", { classe: "tenue", testo: ` ${RUOLI[e.ruolo] || e.ruolo}` }, chi);
    if (e.per_conto_piattaforma) crea("span", { classe: "etichetta-tenue", testo: "per conto della piattaforma", title: "Un utente della piattaforma ha agito sui dati dell'azienda." }, chi);
    if (f.tutta && assoluto) crea("td", { testo: e.cliente_nome || "piattaforma" }, tr);
    crea("td", { testo: azione(e.azione) }, tr);
    crea("td", { testo: dettagli(e.dettagli), classe: "dettagli-registro" }, tr);
  }
  const pagine = crea("div", { classe: "riga" }, box);
  crea("button", { testo: "‹ Più recenti", disabled: !dati.previous, onclick: () => { f.pagina -= 1; H.mostra("registro"); } }, pagine);
  crea("span", { classe: "tenue", testo: `Pagina ${f.pagina} di ${Math.max(1, Math.ceil(dati.count / 100))}` }, pagine);
  crea("button", { testo: "Più vecchie ›", disabled: !dati.next, onclick: () => { f.pagina += 1; H.mostra("registro"); } }, pagine);
}

// --- Storico allarmi ---------------------------------------------------------------------------

export async function schedaStoricoAllarmi() {
  const { crea, sezione, api } = H;
  const f = H.stato.filtroAllarmi || (H.stato.filtroAllarmi = { dal: iso(new Date(Date.now() - 29 * 86400000)), al: iso(new Date()), monitor: "" });
  const query = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const dati = await api("GET", `/api/storico-allarmi/?${query}`);

  const box = sezione("Storico allarmi degli schermi");
  crea("p", {
    classe: "nota",
    testo: "Quando gli schermi si sono scollegati e quando sono tornati in linea, e per quanto sono rimasti fuori. Gli allarmi si attivano in «Schermi → Stato e allarmi»; lo storico si riempie anche senza email.",
  }, box);
  const riga = crea("div", { classe: "riga" }, box);
  const dal = H.campo("Dal", crea("input", { type: "date", value: f.dal }), riga);
  const al = H.campo("Al", crea("input", { type: "date", value: f.al }), riga);
  const monitor = H.campo("Schermo", H.scelta([["", "Tutti"], ...dati.schermi.map((m) => [m.id, m.nome])], f.monitor), riga);
  for (const [k, c] of Object.entries({ dal, al, monitor })) c.addEventListener("change", () => { f[k] = c.value; H.mostra("storico_allarmi"); });
  crea("a", { classe: "pulsante", testo: "Scarica per Excel (CSV)", href: H.conCliente(`/api/storico-allarmi/?${query}&formato=csv`) }, crea("div", { classe: "riga" }, box));

  if (!dati.eventi.length) {
    crea("p", { classe: "vuoto", testo: "Nessun allarme nel periodo: gli schermi sono rimasti collegati (o gli allarmi non sono attivi)." }, box);
    return;
  }
  const riepilogo = sezione("Per schermo");
  const corpoR = H.tabella(["Schermo", "Negozio", "Scollegamenti", "Tempo fuori linea"], riepilogo);
  for (const r of dati.riepilogo) {
    const tr = crea("tr", {}, corpoR);
    crea("td", { testo: r.monitor }, tr);
    crea("td", { testo: r.sede }, tr);
    crea("td", { testo: String(r.scollegamenti) }, tr);
    crea("td", { testo: `${durata(r.minuti)}${r.ancora_fuori ? " (ancora scollegato)" : ""}`, classe: r.ancora_fuori ? "attenzione" : "" }, tr);
  }
  const elenco = sezione("Eventi");
  const corpo = H.tabella(["Quando", "Schermo", "Negozio", "", "Email"], elenco);
  for (const e of dati.eventi) {
    const tr = crea("tr", {}, corpo);
    crea("td", { testo: quando(e.quando), classe: "tenue" }, tr);
    crea("td", { testo: e.monitor }, tr);
    crea("td", { testo: e.sede }, tr);
    crea("td", { testo: `${e.tipo === "scollegato" ? "🔴 Scollegato" : "🟢 Di nuovo in linea"} · ${e.dettaglio}` }, tr);
    crea("td", { testo: e.email ? "inviata" : "—", classe: "tenue" }, tr);
  }
}
