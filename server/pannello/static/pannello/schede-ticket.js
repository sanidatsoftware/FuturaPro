// «Impostazioni → Layout Ticket»: com'è fatto il biglietto stampato (logo, intestazione,
// reparto, numero, testo di fine biglietto…). Due disposizioni: «guidata», elementi in colonna
// che si trascinano per cambiare l'ordine e l'allineamento; «libera», ogni elemento si sposta
// dove si vuole. In entrambe l'elemento scelto ha le maniglie per ridimensionarlo col mouse.
// L'anteprima è disegnata come la stamperà il totem.

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
  let disposizione = layout.disposizione || "guidata";
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

  // Guidata o libera: come si mettono gli elementi sul biglietto.
  const modo = crea("div", { classe: "interruttore-ticket" }, testa);
  const pulsantiModo = {};
  for (const [chiave, testo, aiuto] of [
    ["guidata", "⇅ Guidata", "Gli elementi stanno in colonna, uno sotto l'altro: si trascinano per cambiare l'ordine e (a sinistra, al centro, a destra) l'allineamento."],
    ["libera", "✥ Libera", "Ogni elemento si sposta dove vuoi trascinandolo, anche affiancato ad altri. Si aggancia alla griglia di 1 mm e al centro: tieni premuto Alt per muoverlo senza aggancio; le frecce lo spostano di un punto (Maiusc: 1 mm)."],
  ]) {
    pulsantiModo[chiave] = crea("button", {
      type: "button", classe: `pillola${disposizione === chiave ? " attiva" : ""}`, testo, "data-aiuto": aiuto, disabled: !modifica,
      onclick: () => cambiaDisposizione(chiave),
    }, modo);
  }

  const area = crea("div", { classe: "editor-ticket" }, editor);
  const colElenco = crea("div", { classe: "colonna-elementi" }, area);
  const colProprieta = crea("div", { classe: "colonna-proprieta" }, area);
  const colAnteprima = crea("div", { classe: "colonna-anteprima" }, area);
  const carta_ = crea("div", { classe: "carta-ticket", tabIndex: 0 }, colAnteprima);
  const spiegazione = crea("p", { classe: "tenue" }, colAnteprima);
  // Il riquadro dell'elemento scelto, con le maniglie: resta lo stesso mentre il biglietto si ridisegna.
  const segno = crea("div", { classe: "segno-ticket", hidden: true }, carta_);
  const misuraSegno = crea("span", { classe: "misura-ticket" }, segno);
  const maniglie = {};
  for (const [verso, aiuto] of [
    ["e", "Trascina per allargare o stringere l'elemento."],
    ["s", "Trascina per ingrandire o rimpicciolire (testi: la grandezza del carattere; linee: lo spessore)."],
    ["se", "Trascina per ridimensionare l'elemento."],
  ]) maniglie[verso] = crea("span", { classe: `maniglia-ticket ${verso}`, "data-aiuto": aiuto }, segno);

  let tela = null;
  const W = () => puntiAnteprima();
  const utile = () => W() - 16;
  const scala = () => (tela ? tela.getBoundingClientRect().width / tela.width : 0.6);
  const mm = (punti) => `${(punti / 8).toLocaleString("it-IT", { maximumFractionDigits: 1 })} mm`;

  // Il riquadro libero di ogni elemento: preso da dove sta adesso nella disposizione guidata.
  const fissaRiquadri = () => {
    let fondo = 8;
    for (const b of tela?.blocchi || []) {
      Object.assign(elementi[b.indice], { x: b.x, y: b.y, w: b.w });
      fondo = Math.max(fondo, b.y + b.h + 8);
    }
    for (const el of elementi) {
      if (el.x === undefined || el.y === undefined || el.w === undefined) {
        Object.assign(el, { x: 8, y: fondo, w: utile() });
        fondo += 40;
      }
    }
  };
  const cambiaDisposizione = (nuova) => {
    if (nuova === disposizione) return;
    if (nuova === "libera") fissaRiquadri();
    disposizione = nuova;
    for (const [k, b] of Object.entries(pulsantiModo)) b.classList.toggle("attiva", k === disposizione);
    disegnaTutto();
  };

  const posizionaSegno = () => {
    const blocco = tela?.blocchi.find((b) => b.indice === selezionato);
    segno.hidden = !blocco;
    if (!blocco) return;
    const k = scala();
    Object.assign(segno.style, {
      left: `${tela.offsetLeft + blocco.x * k}px`, top: `${tela.offsetTop + blocco.y * k}px`,
      width: `${Math.max(6, blocco.w * k)}px`, height: `${Math.max(6, blocco.h * k)}px`,
    });
    segno.classList.toggle("libero", disposizione === "libera" && modifica);
    const el = elementi[selezionato];
    // Le maniglie che servono: la larghezza ha senso per logo e QR, e per tutto nella libera.
    const larghezza = disposizione === "libera" || ["logo", "qr"].includes(el.campo);
    maniglie.e.hidden = !modifica || !larghezza;
    maniglie.s.hidden = !modifica || ["logo", "qr"].includes(el.campo);
    maniglie.se.hidden = !modifica;
    misuraSegno.textContent = disposizione === "libera"
      ? `${mm(blocco.x)} · ${mm(blocco.y)} — ${mm(blocco.w)} × ${mm(blocco.h)}`
      : `${mm(blocco.w)} × ${mm(blocco.h)}`;
  };

  // Il biglietto si ridisegna anche mentre si trascina: un disegno alla volta, l'ultimo vince.
  let inDisegno = false;
  let ancora = false;
  const ridisegna = async () => {
    if (inDisegno) { ancora = true; return; }
    inDisegno = true;
    try {
      do {
        ancora = false;
        const nuova = await disegnaTicket({ punti: puntiAnteprima(), disposizione, elementi, logo }, ESEMPIO);
        nuova.classList.add("tela-ticket");
        if (tela?.isConnected) tela.replaceWith(nuova);
        else carta_.prepend(nuova);
        tela = nuova;
        collegaTela(nuova);
        posizionaSegno();
      } while (ancora);
    } finally {
      inDisegno = false;
    }
  };

  const puntoSu = (e) => {
    const r = tela.getBoundingClientRect();
    return { x: ((e.clientX - r.left) * tela.width) / r.width, y: ((e.clientY - r.top) * tela.height) / r.height, fx: (e.clientX - r.left) / r.width };
  };
  // L'elemento sotto il puntatore (quello disegnato per ultimo, se si sovrappongono).
  const sotto = (p) => [...tela.blocchi].reverse().find((b) => p.y >= b.y && p.y <= b.y + b.h && (disposizione === "guidata" || (p.x >= b.x && p.x <= b.x + b.w)));
  const aggancia = (valore, e, passo = 8) => (e.altKey ? Math.round(valore) : Math.round(valore / passo) * passo);

  // Spostare un elemento nella disposizione libera.
  const sposta = (e, indice) => {
    const el = elementi[indice];
    const inizio = { px: e.clientX, py: e.clientY, x: el.x ?? 8, y: el.y ?? 8 };
    return (m) => {
      const k = scala();
      const blocco = tela.blocchi.find((b) => b.indice === indice);
      const w = blocco?.w ?? el.w;
      let x = aggancia(inizio.x + (m.clientX - inizio.px) / k, m);
      // Al centro della carta si aggancia da solo.
      if (!m.altKey && Math.abs(x + w / 2 - W() / 2) < 10) x = Math.round(W() / 2 - w / 2);
      el.x = Math.max(0, Math.min(W() - Math.min(w, W()), x));
      el.y = Math.max(0, aggancia(inizio.y + (m.clientY - inizio.py) / k, m));
      carta_.classList.toggle("al-centro", Math.round(el.x + w / 2) === Math.round(W() / 2));
      ridisegna();
    };
  };

  // Ridimensionare con le maniglie: «e» la larghezza, «s» la grandezza, «se» entrambe come serve.
  const ridimensiona = (e, verso) => {
    const el = elementi[selezionato];
    const blocco = tela.blocchi.find((b) => b.indice === selezionato);
    if (!blocco) return null;
    const inizio = { px: e.clientX, py: e.clientY, w: blocco.w, h: blocco.h, dimensione: el.dimensione, larghezza: el.larghezza };
    const libera = disposizione === "libera";
    const immagine = ["logo", "qr"].includes(el.campo);
    return (m) => {
      const k = scala();
      const dx = (m.clientX - inizio.px) / k;
      const dy = (m.clientY - inizio.py) / k;
      const w = Math.max(24, inizio.w + (verso === "s" ? 0 : dx));
      if (immagine) {
        // Logo e QR restano proporzionati: conta la larghezza (o l'altezza, con la maniglia d'angolo).
        const nuova = verso === "se" ? Math.max(24, inizio.w * Math.max((inizio.w + dx) / inizio.w, (inizio.h + dy) / inizio.h)) : w;
        if (libera) el.w = Math.min(W() - (el.x ?? 0), aggancia(nuova, m, 4));
        else el.larghezza = Math.max(10, Math.min(100, Math.round((nuova / utile()) * 100)));
      } else {
        if (verso !== "s" && libera) el.w = Math.max(24, Math.min(W() - (el.x ?? 0), aggancia(w, m, 4)));
        if (verso !== "e") {
          const h = Math.max(4, inizio.h + dy);
          el.dimensione = el.campo === "linea"
            ? Math.max(10, Math.min(80, Math.round(h * 10)))
            : Math.max(10, Math.min(400, Math.round((inizio.dimensione * h) / inizio.h)));
        }
      }
      ridisegna();
      disegnaProprieta();
    };
  };

  // Un trascinamento con il puntatore: muovi(e) a ogni passo, fine() al rilascio.
  const trascina = (bersaglio, e, muovi, fine) => {
    bersaglio.setPointerCapture(e.pointerId);
    let mosso = false;
    const passo = (m) => {
      if (!mosso && Math.abs(m.clientX - e.clientX) + Math.abs(m.clientY - e.clientY) < 4) return;
      mosso = true;
      carta_.classList.add("trascina");
      muovi(m);
    };
    const stop = (m) => {
      bersaglio.removeEventListener("pointermove", passo);
      bersaglio.removeEventListener("pointerup", stop);
      bersaglio.removeEventListener("pointercancel", stop);
      carta_.classList.remove("trascina", "al-centro");
      fine?.(mosso, m);
    };
    bersaglio.addEventListener("pointermove", passo);
    bersaglio.addEventListener("pointerup", stop);
    bersaglio.addEventListener("pointercancel", stop);
  };

  for (const [verso, maniglia] of Object.entries(maniglie)) {
    maniglia.addEventListener("pointerdown", (e) => {
      if (!modifica) return;
      e.preventDefault();
      e.stopPropagation();
      const muovi = ridimensiona(e, verso);
      if (muovi) trascina(maniglia, e, muovi, () => disegnaTutto());
    });
  }
  // Nella libera si prende l'elemento scelto anche dal suo riquadro.
  segno.addEventListener("pointerdown", (e) => {
    if (!modifica || disposizione !== "libera" || e.target !== segno) return;
    e.preventDefault();
    trascina(segno, e, sposta(e, selezionato), () => disegnaTutto());
  });
  // Le frecce spostano l'elemento scelto (nella libera).
  carta_.addEventListener("keydown", (e) => {
    const el = elementi[selezionato];
    const passi = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!passi || !el || !modifica || disposizione !== "libera") return;
    e.preventDefault();
    const n = e.shiftKey ? 8 : 1;
    el.x = Math.max(0, (el.x ?? 0) + passi[0] * n);
    el.y = Math.max(0, (el.y ?? 0) + passi[1] * n);
    ridisegna();
    disegnaProprieta();
  });

  // Sul biglietto: clic per scegliere un elemento. Guidata: trascinandolo in alto o in basso
  // cambia posto, a sinistra, al centro o a destra cambia allineamento. Libera: va dove lo lasci.
  const collegaTela = (t) => {
    t.addEventListener("pointerdown", (e) => {
      const trovato = sotto(puntoSu(e));
      carta_.focus({ preventScroll: true });
      if (!trovato) return;
      const indice = trovato.indice;
      if (disposizione === "libera") {
        if (indice !== selezionato) { selezionato = indice; disegnaElenco(); disegnaProprieta(); posizionaSegno(); }
        if (!modifica) return;
        // Il trascinamento continua sul riquadro (la tela si ridisegna mentre si sposta).
        trascina(segno, e, sposta(e, indice), () => disegnaTutto());
        return;
      }
      trascina(t, e, (m) => {
        if (!modifica) return;
        const { y } = puntoSu(m);
        // La linea dove andrà l'elemento.
        const dopo = tela.blocchi.filter((b) => b.y + b.h / 2 < y).pop();
        const quota = dopo ? dopo.y + dopo.h : 0;
        let linea = carta_.querySelector(".linea-ticket");
        if (!linea) linea = crea("div", { classe: "linea-ticket" }, carta_);
        linea.style.top = `${tela.offsetTop + quota * scala() - 1}px`;
      }, (mosso, m) => {
        carta_.querySelector(".linea-ticket")?.remove();
        if (!mosso || !modifica) { selezionato = indice; disegnaTutto(); return; }
        const { fx, y } = puntoSu(m);
        const el = elementi[indice];
        // Allineamento secondo dove lo si lascia (per i testi, il logo e il QR).
        if (el.campo !== "linea") el.allineamento = fx < 0.34 ? "sinistra" : fx > 0.66 ? "destra" : "centro";
        // Nuovo posto: dopo l'ultimo elemento che sta sopra il punto di rilascio.
        const sopra = tela.blocchi.filter((b) => b.indice !== indice && b.y + b.h / 2 < y).pop();
        const [spostato] = elementi.splice(indice, 1);
        // Tolto l'elemento, quelli che venivano dopo scalano di un posto.
        const dove = sopra ? (sopra.indice > indice ? sopra.indice - 1 : sopra.indice) + 1 : 0;
        elementi.splice(dove, 0, spostato);
        selezionato = dove;
        disegnaTutto();
      });
    });
  };

  const nomeCampo = (el) => base.campi[el.campo] + (el.campo === "testo" && el.testo ? `: ${el.testo.slice(0, 18)}` : "");

  const disegnaElenco = () => {
    colElenco.replaceChildren();
    crea("div", { classe: "etichetta", testo: disposizione === "libera" ? "Elementi (più in basso = disegnato sopra)" : "Elementi (trascina per spostarli)" }, colElenco);
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
        const aggiunto = structuredClone({ ...modello, visibile: true });
        // Nella libera il nuovo elemento va in fondo al biglietto, largo quanto la carta.
        if (disposizione === "libera") Object.assign(aggiunto, { x: 8, y: tela ? tela.height - 8 : 8, w: utile() });
        elementi.push(aggiunto);
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
    if (disposizione === "libera") {
      crea("div", { classe: "tenue", testo: "Riquadro (punti: 8 = 1 mm)" }, colProprieta);
      const riga = crea("div", { classe: "riga riquadro-ticket" }, colProprieta);
      for (const [t, chiave, max] of [["X", "x", 1000], ["Y", "y", 6000], ["Largh.", "w", 1000]]) {
        const input = campo(t, crea("input", { type: "number", min: chiave === "w" ? 16 : 0, max, value: el[chiave] ?? 0, classe: "corto", disabled: !modifica,
          "data-aiuto": { x: "Distanza dal bordo sinistro della carta.", y: "Distanza dall'inizio del biglietto.", w: "Larghezza del riquadro: il testo va a capo e si allinea dentro di lui." }[chiave] }), riga);
        input.addEventListener("input", () => { el[chiave] = Math.max(chiave === "w" ? 16 : 0, Math.min(max, parseInt(input.value, 10) || 0)); ridisegna(); });
      }
    }
    if (["logo", "qr"].includes(el.campo)) {
      if (disposizione !== "libera") numero("Larghezza (% della carta)", "larghezza", 10, 100, 5);
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
    if (disposizione !== "libera") numero("Spazio sotto (punti)", "spazio", 0, 200, 2);
    if (modifica && (el.campo === "testo" || el.campo === "linea")) {
      crea("button", { testo: "Elimina elemento", classe: "pericolo", onclick: () => { elementi.splice(selezionato, 1); selezionato = 0; disegnaTutto(); } }, colProprieta);
    }
  };

  const disegnaTutto = () => {
    spiegazione.textContent = disposizione === "libera"
      ? "Anteprima con dati di esempio. Trascina un elemento dove vuoi (Alt: senza aggancio; frecce: un punto alla volta); le maniglie blu lo ridimensionano."
      : "Anteprima con dati di esempio. Clic su un elemento per modificarlo; trascinalo in alto o in basso per cambiargli posto, a sinistra, al centro o a destra per allinearlo; le maniglie blu lo ridimensionano.";
    disegnaElenco();
    disegnaProprieta();
    ridisegna();
  };
  disegnaTutto();

  if (modifica) {
    const azioni = crea("div", { classe: "riga" }, editor);
    crea("button", {
      classe: "primario", testo: "Salva layout",
      onclick: () => prova(() => api("PATCH", `/api/layout-ticket/${layout.id}/`, { nome: nomeLayout.value.trim(), carta: parseInt(carta.value, 10), disposizione, elementi }), "Salvato: i totem lo ricevono entro un minuto."),
    }, azioni);
    crea("button", {
      testo: "Ripristina gli elementi di partenza",
      onclick: () => { elementi.splice(0, elementi.length, ...structuredClone(base.elementi)); selezionato = 0; cambiaDisposizione("guidata"); disegnaTutto(); },
    }, azioni);
    crea("button", {
      testo: "Elimina layout", classe: "pericolo",
      onclick: () => confirm(`Eliminare «${layout.nome}»?${layout.stampanti.length ? " Le stampanti che lo usano torneranno al biglietto semplice." : ""}`)
        && prova(async () => { await api("DELETE", `/api/layout-ticket/${layout.id}/`); scelto = null; }, "Eliminato."),
    }, azioni);
  }
}
