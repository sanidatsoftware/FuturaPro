// «Impostazioni → Layout Ticket»: com'è fatto il biglietto stampato. Elementi in colonna
// (logo, intestazione, reparto, numero, testo di fine biglietto…): si trascinano per cambiare
// l'ordine, si clicca un elemento (nell'elenco o nell'anteprima) per sceglierne carattere,
// grandezza e allineamento. L'anteprima è disegnata come la stamperà il totem.

import { disegnaTicket } from "../player/ticket.js";

let H = null;
let scelto = null; // il layout aperto nell'editor

export function preparaSchedeTicket(strumenti) {
  H = strumenti;
}

const ESEMPIO = {
  reparto: "Salumeria", numero: 27, davanti: "Persone prima di te: 3",
  quando: new Date().toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }), istante: Date.now(),
  qr: "https://esempio.it/b/ab12cd34ef", testo_qr: "Segui la coda dal telefono",
};

async function urlLogo(layout) {
  if (!layout.ha_logo) return "";
  const intestazioni = H.stato.cliente ? { "X-Cliente": H.stato.cliente } : {};
  const risposta = await fetch(`/api/layout-ticket/${layout.id}/logo/?v=${encodeURIComponent(layout.modificato)}`, { headers: intestazioni, credentials: "same-origin" });
  if (!risposta.ok) return "";
  const blob = await risposta.blob();
  return new Promise((ok) => {
    const lettore = new FileReader();
    lettore.onload = () => ok(lettore.result);
    lettore.readAsDataURL(blob);
  });
}

export async function schedaLayoutTicket() {
  const { crea, sezione, api, prova, campo, scelta } = H;
  const [elenco, base, modelli] = await Promise.all([
    H.elenco("/api/layout-ticket/"), api("GET", "/api/layout-ticket/predefiniti/"), api("GET", "/api/stampanti/modelli/"),
  ]);
  const modifica = H.ruoloGestione() || H.stato.io.ruolo === "tecnico";

  const intro = sezione("Layout Ticket");
  crea("p", {
    classe: "nota",
    testo: "Com'è fatto il biglietto che esce dal totem: logo, intestazione, reparto (il tasto toccato), numero, testo di fine biglietto e altri elementi, ognuno con il suo carattere e la sua grandezza. "
      + "Ogni stampante (Hardware · Anagrafica Stampanti Ticket) può avere il suo layout. Il totem stampa il biglietto come immagine: esce uguale all'anteprima sia sulla Epson di rete sia sulla stampante di sistema.",
  }, intro);
  const lista = crea("div", { classe: "elenco-ticket" }, intro);
  for (const l of elenco) {
    crea("button", {
      classe: `scheda-ticket${scelto === l.id ? " attiva" : ""}`,
      testo: `🧾 ${l.nome} · ${l.carta} mm${l.stampanti.length ? ` · ${l.stampanti.length} stampant${l.stampanti.length === 1 ? "e" : "i"}` : ""}`,
      onclick: () => { scelto = l.id; H.mostra("layout_ticket"); },
    }, lista);
  }
  if (modifica) {
    const riga = crea("div", { classe: "riga" }, intro);
    const nome = campo("Nuovo layout", crea("input", { placeholder: "es. Biglietto standard", maxLength: 100 }), riga);
    const carta = campo("Carta", scelta([[80, "80 mm"], [58, "58 mm"]], 80), riga);
    crea("button", {
      classe: "primario", testo: "Crea",
      onclick: () => prova(async () => {
        const nuovo = await api("POST", "/api/layout-ticket/", { nome: nome.value.trim(), carta: parseInt(carta.value, 10) });
        scelto = nuovo.id;
      }, "Layout creato: ora componilo."),
    }, riga);
  }
  const layout = elenco.find((l) => l.id === scelto) || elenco[0];
  if (!layout) {
    crea("p", { classe: "vuoto", testo: "Nessun layout ticket: creane uno. Senza layout le stampanti stampano il biglietto semplice." }, intro);
    return;
  }
  scelto = layout.id;
  const elementi = structuredClone(layout.elementi);
  let selezionato = 0;
  const logo = await urlLogo(layout);

  const editor = sezione(`Componi «${layout.nome}»`);
  const testa = crea("div", { classe: "riga" }, editor);
  const nomeLayout = campo("Nome", crea("input", { value: layout.nome, maxLength: 100 }), testa);
  const carta = campo("Carta di riferimento", scelta([[80, "80 mm"], [58, "58 mm"]], layout.carta), testa);
  // L'anteprima alla larghezza di una stampante vera (il totem usa quella della sua stampante).
  const misure = [];
  for (const m of modelli) for (const [c, punti] of Object.entries(m.carte)) misure.push([`${m.chiave}|${c}`, `${m.nome} · ${c} mm (${punti} punti)`, punti]);
  const anteprimaSu = campo("Anteprima su", scelta(misure.map(([k, t]) => [k, t]), `TM-T20IV|${layout.carta}`), testa);
  const puntiAnteprima = () => misure.find(([k]) => k === anteprimaSu.value)?.[2] || 576;
  carta.addEventListener("change", () => { anteprimaSu.value = `TM-T20IV|${carta.value}`; ridisegna(); });
  anteprimaSu.addEventListener("change", () => ridisegna());
  if (layout.stampanti.length) crea("span", { classe: "tenue", testo: `Usato da: ${layout.stampanti.join(", ")}` }, testa);

  const area = crea("div", { classe: "editor-ticket" }, editor);
  const colElenco = crea("div", { classe: "colonna-elementi" }, area);
  const colProprieta = crea("div", { classe: "colonna-proprieta" }, area);
  const colAnteprima = crea("div", { classe: "colonna-anteprima" }, area);
  const carta_ = crea("div", { classe: "carta-ticket" }, colAnteprima);
  crea("p", { classe: "tenue", testo: "Anteprima con dati di esempio. Clicca un elemento per modificarlo." }, colAnteprima);

  const ridisegna = async () => {
    const tela = await disegnaTicket({ punti: puntiAnteprima(), elementi, logo }, ESEMPIO);
    tela.classList.add("tela-ticket");
    // L'elemento scelto, evidenziato.
    const blocco = tela.blocchi.find((b) => b.indice === selezionato);
    carta_.replaceChildren(tela);
    if (blocco) {
      const segno = crea("div", { classe: "segno-ticket" }, carta_);
      const scala = tela.getBoundingClientRect().height / tela.height || 0.6;
      Object.assign(segno.style, { top: `${blocco.y * scala}px`, height: `${blocco.h * scala}px` });
    }
    tela.addEventListener("click", (e) => {
      const scala = tela.height / tela.getBoundingClientRect().height;
      const y = (e.clientY - tela.getBoundingClientRect().top) * scala;
      const trovato = tela.blocchi.find((b) => y >= b.y && y <= b.y + b.h);
      if (trovato) { selezionato = trovato.indice; disegnaTutto(); }
    });
  };

  const nomeCampo = (el) => base.campi[el.campo] + (el.campo === "testo" && el.testo ? `: ${el.testo.slice(0, 18)}` : "");

  const disegnaElenco = () => {
    colElenco.replaceChildren();
    crea("div", { classe: "etichetta", testo: "Elementi (trascina per spostarli)" }, colElenco);
    elementi.forEach((el, i) => {
      const voce = crea("div", { classe: `voce-ticket${i === selezionato ? " scelta" : ""}${el.visibile ? "" : " nascosta"}`, draggable: modifica }, colElenco);
      crea("span", { classe: "maniglia", testo: "⠿" }, voce);
      crea("span", { classe: "nome", testo: nomeCampo(el) }, voce);
      crea("button", {
        testo: el.visibile ? "👁" : "🚫", title: el.visibile ? "Nascondi" : "Mostra", disabled: !modifica,
        onclick: (e) => { e.stopPropagation(); el.visibile = !el.visibile; disegnaTutto(); },
      }, voce);
      voce.addEventListener("click", () => { selezionato = i; disegnaTutto(); });
      voce.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", String(i)); voce.classList.add("trascinata"); });
      voce.addEventListener("dragend", () => voce.classList.remove("trascinata"));
      voce.addEventListener("dragover", (e) => { e.preventDefault(); voce.classList.add("sopra"); });
      voce.addEventListener("dragleave", () => voce.classList.remove("sopra"));
      voce.addEventListener("drop", (e) => {
        e.preventDefault();
        const da = parseInt(e.dataTransfer.getData("text/plain"), 10);
        if (Number.isNaN(da) || da === i) return;
        const [mosso] = elementi.splice(da, 1);
        elementi.splice(i, 0, mosso);
        selezionato = i;
        disegnaTutto();
      });
    });
    if (!modifica) return;
    const presenti = new Set(elementi.map((e) => e.campo));
    const aggiungibili = Object.entries(base.campi).filter(([k]) => k === "testo" || k === "linea" || !presenti.has(k));
    const riga = crea("div", { classe: "riga" }, colElenco);
    const nuovo = scelta(aggiungibili.map(([k, t]) => [k, t]), "testo");
    riga.appendChild(nuovo);
    crea("button", {
      testo: "+ Aggiungi",
      onclick: () => {
        const modello = base.elementi.find((e) => e.campo === nuovo.value) || { ...base.elementi[1], campo: nuovo.value, testo: nuovo.value === "testo" ? "Testo" : "" };
        elementi.push(structuredClone({ ...modello, visibile: true }));
        selezionato = elementi.length - 1;
        disegnaTutto();
      },
    }, riga);
  };

  const disegnaProprieta = () => {
    colProprieta.replaceChildren();
    const el = elementi[selezionato];
    if (!el) return;
    crea("div", { classe: "etichetta", testo: base.campi[el.campo] }, colProprieta);
    const cambia = (chiave, valore) => { el[chiave] = valore; ridisegna(); disegnaElenco(); };
    const numero = (t, chiave, min, max, passo = 1) => {
      const input = campo(t, crea("input", { type: "number", min, max, step: passo, value: el[chiave], classe: "corto", disabled: !modifica }), colProprieta);
      input.addEventListener("input", () => cambia(chiave, Math.max(min, Math.min(max, parseInt(input.value, 10) || min))));
    };
    const spunta = (t, chiave) => {
      const l = crea("label", { classe: "spunta" }, colProprieta);
      const c = crea("input", { type: "checkbox", checked: el[chiave], disabled: !modifica }, l);
      l.append(` ${t}`);
      c.addEventListener("change", () => cambia(chiave, c.checked));
    };
    if (["intestazione", "messaggio", "testo"].includes(el.campo)) {
      const t = campo(el.campo === "testo" ? "Testo" : "Testo (la stampante può averne uno suo)", crea("textarea", { rows: 3, cols: 26, value: el.testo, maxLength: 300, disabled: !modifica }), colProprieta);
      t.addEventListener("input", () => cambia("testo", t.value));
    }
    if (["logo", "qr"].includes(el.campo)) {
      numero("Larghezza (% della carta)", "larghezza", 10, 100, 5);
      if (el.campo === "logo" && modifica) {
        crea("p", { classe: "tenue", testo: layout.ha_logo ? "Logo caricato." : "Nessun logo: caricane uno (PNG o JPG; diventa in bianco e nero)." }, colProprieta);
        const file = crea("input", { type: "file", accept: "image/*" }, colProprieta);
        file.addEventListener("change", () => {
          if (!file.files[0]) return;
          const dati = new FormData();
          dati.append("file", file.files[0]);
          prova(() => api("POST", `/api/layout-ticket/${layout.id}/logo/`, dati), "Logo caricato.");
        });
        if (layout.ha_logo) crea("button", { testo: "Togli il logo", classe: "pericolo", onclick: () => prova(() => api("DELETE", `/api/layout-ticket/${layout.id}/logo/`), "Logo tolto.") }, colProprieta);
      }
      if (el.campo === "qr") crea("p", { classe: "tenue", testo: "Compare solo con la Coda sul telefono attiva." }, colProprieta);
    } else if (el.campo === "linea") {
      numero("Spessore (decimi della grandezza)", "dimensione", 10, 80, 5);
    } else {
      const car = campo("Carattere", scelta(base.caratteri.map((c) => [c, c]), el.carattere), colProprieta);
      car.disabled = !modifica;
      car.addEventListener("change", () => cambia("carattere", car.value));
      numero("Grandezza (punti: 8 = 1 mm)", "dimensione", 10, 400, 2);
      if (el.campo === "data") {
        const formato = campo("Formato", scelta([["data_ora", "Data e ora (15/10/26 10:42)"], ["data", "Solo la data"], ["ora", "Solo l'ora"], ["esteso", "Esteso (giovedì 15 ottobre 2026, 10:42)"]], el.formato || "data_ora"), colProprieta);
        formato.disabled = !modifica;
        formato.addEventListener("change", () => cambia("formato", formato.value));
      }
      const all = campo("Allineamento", scelta([["sinistra", "A sinistra"], ["centro", "Al centro"], ["destra", "A destra"]], el.allineamento), colProprieta);
      all.disabled = !modifica;
      all.addEventListener("change", () => cambia("allineamento", all.value));
      spunta("Grassetto", "grassetto");
      spunta("Corsivo", "corsivo");
      spunta("Tutto maiuscolo", "maiuscolo");
      spunta("Bianco su nero", "inverso");
    }
    numero("Spazio sotto (punti)", "spazio", 0, 200, 2);
    if (modifica && (el.campo === "testo" || el.campo === "linea")) {
      crea("button", { testo: "Elimina elemento", classe: "pericolo", onclick: () => { elementi.splice(selezionato, 1); selezionato = 0; disegnaTutto(); } }, colProprieta);
    }
  };

  const disegnaTutto = () => { disegnaElenco(); disegnaProprieta(); ridisegna(); };
  disegnaTutto();

  if (modifica) {
    const azioni = crea("div", { classe: "riga" }, editor);
    crea("button", {
      classe: "primario", testo: "Salva layout",
      onclick: () => prova(() => api("PATCH", `/api/layout-ticket/${layout.id}/`, { nome: nomeLayout.value.trim(), carta: parseInt(carta.value, 10), elementi }), "Salvato: i totem lo ricevono entro un minuto."),
    }, azioni);
    crea("button", {
      testo: "Ripristina gli elementi di partenza",
      onclick: () => { elementi.splice(0, elementi.length, ...structuredClone(base.elementi)); selezionato = 0; disegnaTutto(); },
    }, azioni);
    crea("button", {
      testo: "Elimina layout", classe: "pericolo",
      onclick: () => confirm(`Eliminare «${layout.nome}»?${layout.stampanti.length ? " Le stampanti che lo usano torneranno al biglietto semplice." : ""}`)
        && prova(async () => { await api("DELETE", `/api/layout-ticket/${layout.id}/`); scelto = null; }, "Eliminato."),
    }, azioni);
  }
}
