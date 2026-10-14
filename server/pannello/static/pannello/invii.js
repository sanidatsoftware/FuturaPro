// «Invio automatico per email»: il riquadro comune ai rapporti (messa in onda, tempi d'attesa,
// disponibilità degli schermi). Ogni invio ha i suoi destinatari; server e mittente sono quelli
// dell'azienda (Impostazioni → Email). I testi dei dati passano da textContent.

const FREQUENZE = [["giornaliera", "Ogni mattina (il giorno prima)"], ["settimanale", "Ogni lunedì (la settimana prima)"], ["mensile", "Il primo del mese (il mese prima)"]];

export async function sezioneInvii(H, tipo, { nomePredefinito, filtri = [], filtriAttuali = {} } = {}) {
  const { crea, api, prova } = H;
  const gestione = H.ruoloGestione();
  const [invii, email] = await Promise.all([
    H.tutteLePagine(`/api/invii-rapporti/?tipo=${tipo}`),
    gestione ? api("GET", "/api/email/").catch(() => null) : Promise.resolve(null),
  ]);
  const box = H.sezione("📧 Invio automatico per email");
  box.classList.add("non-stampare");
  crea("p", {
    classe: "nota",
    testo: "Facoltativo. Il rapporto parte da solo alle 7 del mattino, con il file per Excel allegato, agli indirizzi scelti qui. Server e mittente sono quelli dell'azienda.",
  }, box);
  if (email && email.origine === "nessuna") {
    const avviso = crea("p", { classe: "attenzione", testo: "L'azienda non ha ancora un server email: impostalo in «Impostazioni → Email». " }, box);
    crea("button", { testo: "Vai alle impostazioni email", onclick: () => H.mostra("email") }, avviso);
  }
  for (const i of invii) {
    const riga = crea("div", { classe: `invio${i.attivo ? "" : " spento"}` }, box);
    crea("strong", { testo: i.nome }, riga);
    crea("span", { classe: "tenue", testo: ` · ${FREQUENZE.find(([k]) => k === i.frequenza)?.[1] || i.frequenza} · a ${i.email.join(", ")}` }, riga);
    const filtriTesto = Object.entries(i.filtri || {}).map(([k, v]) => `${k}: ${filtri.find((f) => f.chiave === k)?.testo?.(v) || v}`).join(", ");
    if (filtriTesto) crea("span", { classe: "tenue", testo: ` · ${filtriTesto}` }, riga);
    const stato = crea("div", { classe: "tenue" }, riga);
    stato.textContent = i.ultimo_errore
      ? `⚠ Ultimo tentativo non riuscito: ${i.ultimo_errore}`
      : i.ultimo_invio ? `Ultimo invio: ${new Date(i.ultimo_invio).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" })}` : "Non ancora inviato.";
    if (i.ultimo_errore) stato.className = "attenzione";
    if (!gestione) continue;
    const azioni = crea("div", { classe: "riga" }, riga);
    crea("button", {
      testo: "Invia adesso",
      onclick: async () => {
        try {
          const esito = await api("POST", `/api/invii-rapporti/${i.id}/invia/`);
          H.avvisa(`Inviato a ${i.email.join(", ")} (dal ${new Date(`${esito.dal}T00:00`).toLocaleDateString("it-IT")} al ${new Date(`${esito.al}T00:00`).toLocaleDateString("it-IT")}).`, "ok");
        } catch (errore) {
          H.avvisa(errore.message);
        }
      },
    }, azioni);
    crea("button", { testo: i.attivo ? "Sospendi" : "Riattiva", onclick: () => prova(() => api("PATCH", `/api/invii-rapporti/${i.id}/`, { attivo: !i.attivo }), "Salvato.") }, azioni);
    crea("button", { classe: "pericolo", testo: "Elimina", onclick: () => confirm(`Eliminare l'invio «${i.nome}»?`) && prova(() => api("DELETE", `/api/invii-rapporti/${i.id}/`), "Invio eliminato.") }, azioni);
  }
  if (!gestione) {
    if (!invii.length) crea("p", { classe: "vuoto", testo: "Nessun invio automatico." }, box);
    return;
  }
  const nuovo = crea("details", { classe: "nuovo-invio" }, box);
  crea("summary", { testo: "＋ Nuovo invio automatico" }, nuovo);
  const riga = crea("div", { classe: "riga" }, nuovo);
  const nome = H.campo("Nome", crea("input", { value: nomePredefinito || "", maxLength: 120, size: 30 }), riga);
  const indirizzi = H.campo("Destinatari (separati da virgola)", crea("input", { placeholder: "es. marketing@fornitore.it, direzione@azienda.it", size: 44 }), riga);
  const frequenza = H.campo("Quando", H.scelta(FREQUENZE, "settimanale"), riga);
  const controlli = {};
  if (filtri.length) {
    const rigaFiltri = crea("div", { classe: "riga" }, nuovo);
    for (const f of filtri) controlli[f.chiave] = H.campo(f.etichetta, H.scelta(f.scelte, filtriAttuali[f.chiave] || ""), rigaFiltri);
  }
  crea("button", {
    classe: "primario", testo: "Crea l'invio",
    onclick: () => prova(() => api("POST", "/api/invii-rapporti/", {
      tipo, nome: nome.value.trim() || nomePredefinito, frequenza: frequenza.value, attivo: true,
      email: indirizzi.value.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean),
      filtri: Object.fromEntries(Object.entries(controlli).map(([k, c]) => [k, c.value]).filter(([, v]) => v)),
    }), "Invio creato: parte da solo al prossimo periodo (o premi «Invia adesso»)."),
  }, nuovo);
}
