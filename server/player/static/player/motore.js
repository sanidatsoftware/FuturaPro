// Il motore di rendering: disegna il layout del manifest e fa girare le zone.
//
// Non sa da dove arrivano i dati: glieli passa una "fonte" con tre metodi,
//   file(id, voce) -> Promise<url utilizzabile in <img>/<video>, oppure null>
//   dati(zonaId)   -> Promise<{meteo} | {notizie}>
// così lo stesso codice serve il player e l'anteprima del pannello.
// Ogni testo che arriva da fuori (titoli, nomi) passa da textContent, mai da innerHTML.

import { inOnda, istanteNelFuso } from "./regole.js";

const RISOLUZIONE = { orizzontale: [1920, 1080], verticale: [1080, 1920] };
const ATTESA_SE_VUOTO = 5000;

function crea(tag, classe, genitore) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (genitore) genitore.appendChild(el);
  return el;
}

const attendi = (ms) => new Promise((ok) => setTimeout(ok, ms));

export class Motore {
  constructor(radice, fonte) {
    this.radice = radice;
    this.fonte = fonte;
    this.zone = [];
    this.manifest = null;
    window.addEventListener("resize", () => this.adatta());
  }

  // Un manifest nuovo: se il layout è lo stesso le zone continuano (cambia solo il
  // palinsesto, letto a ogni passaggio di slide); se cambia, si ridisegna tutto.
  mostra(manifest) {
    const firma = JSON.stringify([manifest.layout, manifest.schermo]);
    this.manifest = manifest;
    if (firma === this.firma) return;
    this.firma = firma;
    this.zone.forEach((z) => z.ferma());
    this.radice.replaceChildren();

    const layout = manifest.layout;
    const [larghezza, altezza] = RISOLUZIONE[layout.orientamento] || RISOLUZIONE.orizzontale;
    this.palco = crea("div", "palco", this.radice);
    Object.assign(this.palco.style, {
      width: `${larghezza}px`, height: `${altezza}px`,
      background: layout.sfondo, fontFamily: layout.carattere,
    });
    this.dimensioni = { larghezza, altezza };
    if (layout.immagine_sfondo) {
      const voce = manifest.contenuti[layout.immagine_sfondo];
      this.fonte.file(layout.immagine_sfondo, voce).then((url) => {
        if (url) Object.assign(this.palco.style, { backgroundImage: `url("${url}")`, backgroundSize: "cover" });
      });
    }

    this.zone = layout.zone.map((zona) => {
      const el = crea("div", `zona zona-${zona.tipo}`, this.palco);
      Object.assign(el.style, {
        left: `${zona.x}%`, top: `${zona.y}%`, width: `${zona.larghezza}%`, height: `${zona.altezza}%`,
        zIndex: zona.livello,
      });
      const px = { larghezza: (zona.larghezza / 100) * larghezza, altezza: (zona.altezza / 100) * altezza };
      const Classe = TIPI[zona.tipo];
      const istanza = new Classe(el, zona, px, this);
      istanza.avvia();
      return istanza;
    });
    this.adatta();
  }

  // Il palco ha una risoluzione fissa (1920x1080 o 1080x1920): lo si scala e, se
  // lo schermo è montato ruotato, lo si ruota.
  adatta() {
    if (!this.palco) return;
    const rotazione = this.manifest.schermo?.rotazione || 0;
    const { larghezza, altezza } = this.dimensioni;
    const ruotato = rotazione === 90 || rotazione === 270;
    const [w, h] = ruotato ? [altezza, larghezza] : [larghezza, altezza];
    const scala = Math.min(window.innerWidth / w, window.innerHeight / h);
    this.palco.style.transform = `translate(-50%, -50%) rotate(${rotazione}deg) scale(${scala})`;
  }

  get fuso() {
    return this.manifest.fuso_orario;
  }
}

// --- Slide ---------------------------------------------------------------------

const TRANSIZIONI = {
  nessuna: null,
  dissolvenza: { entra: { opacity: 0 }, esce: { opacity: 0 } },
  scorri_sinistra: { entra: { transform: "translateX(100%)" }, esce: { transform: "translateX(-100%)" } },
  scorri_alto: { entra: { transform: "translateY(100%)" }, esce: { transform: "translateY(-100%)" } },
  zoom: { entra: { transform: "scale(1.15)", opacity: 0 }, esce: { opacity: 0 } },
};
const NEUTRO = { opacity: 1, transform: "none" };

class ZonaSlide {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, zona, motore, config: zona.configurazione });
    this.attivo = false;
    this.strato = null;
    this.corrente = null;
  }

  avvia() {
    this.attivo = true;
    this.ciclo();
  }

  ferma() {
    this.attivo = false;
    this.strato?.querySelector("video")?.pause();
  }

  // La sequenza si ricalcola a ogni passaggio: le regole del palinsesto valgono
  // subito, senza interrompere la slide in corso.
  sequenza() {
    const m = this.motore.manifest;
    if (this.config.sorgente && this.config.sorgente !== "palinsesto") {
      return m.playlist[this.config.sorgente] || [];
    }
    const inSequenza = inOnda(m.pubblicazioni, istanteNelFuso(m.fuso_orario)).flatMap((p) => m.playlist[p.playlist] || []);
    // Niente in onda: l'immagine di riserva dello schermo (es. il logo), se c'è.
    if (!inSequenza.length && m.riserva && m.contenuti[m.riserva]) return [{ contenuto: m.riserva, durata: 30 }];
    return inSequenza;
  }

  async ciclo() {
    let indice = 0;
    while (this.attivo) {
      const sequenza = this.sequenza();
      if (!sequenza.length) {
        this.svuota();
        await attendi(ATTESA_SE_VUOTO);
        continue;
      }
      indice %= sequenza.length;
      const elemento = sequenza[indice++];
      const voce = this.motore.manifest.contenuti[elemento.contenuto];
      // Un'immagine sola resta ferma: niente transizione su se stessa.
      if (sequenza.length === 1 && this.corrente === elemento.contenuto && voce.tipo !== "video") {
        await attendi((elemento.durata || 10) * 1000);
        continue;
      }
      const mostrato = voce && (await this.mostraElemento(elemento, voce));
      if (!mostrato) {
        await attendi(1000); // file non ancora disponibile: si passa al successivo
        continue;
      }
      await mostrato.fine;
    }
  }

  svuota() {
    this.strato?.remove();
    this.strato = null;
    this.corrente = null;
  }

  // Prepara il nuovo elemento e lo fa entrare con la transizione. Restituisce
  // { fine }, una promessa che si risolve quando è ora di passare al successivo
  // (dentro un oggetto: restituita da sola, la funzione async la aspetterebbe).
  async mostraElemento(elemento, voce) {
    const strato = crea("div", "strato");
    let media;
    if (voce.tipo === "web") {
      media = crea("iframe", "media", strato);
      media.setAttribute("sandbox", "allow-scripts allow-same-origin");
      media.src = voce.url;
    } else {
      const url = await this.motore.fonte.file(elemento.contenuto, voce);
      if (!url) return null;
      media = crea(voce.tipo === "video" ? "video" : "img", "media", strato);
      adatta(media, this.config.adattamento, url);
      if (voce.tipo === "video") Object.assign(media, { muted: true, playsInline: true, preload: "auto" });
      media.src = url;
      const pronto = voce.tipo === "video" ? "canplay" : "load";
      const caricato = await Promise.race([
        new Promise((ok) => media.addEventListener(pronto, () => ok(true), { once: true })),
        new Promise((ok) => media.addEventListener("error", () => ok(false), { once: true })),
        attendi(15000).then(() => false),
      ]);
      if (!caricato || !this.attivo) return null;
    }

    this.entra(strato);
    this.corrente = elemento.contenuto;

    if (voce.tipo === "video") {
      media.currentTime = 0;
      media.play().catch(() => {});
      const fine = Promise.race([
        new Promise((ok) => media.addEventListener("ended", ok, { once: true })),
        new Promise((ok) => media.addEventListener("error", ok, { once: true })),
        // Durata indicata: taglia il video; altrimenti un limite di sicurezza.
        attendi((elemento.durata || 3600) * 1000),
      ]);
      return { fine };
    }
    return { fine: attendi((elemento.durata || 10) * 1000) };
  }

  entra(nuovo) {
    const vecchio = this.strato;
    const transizione = vecchio ? TRANSIZIONI[this.config.transizione] : null;
    const durata = this.config.durata_transizione;
    this.strato = nuovo;
    if (!transizione || !durata) {
      this.el.appendChild(nuovo);
      vecchio?.remove();
      return;
    }
    Object.assign(nuovo.style, transizione.entra);
    this.el.appendChild(nuovo);
    nuovo.getBoundingClientRect(); // fa partire la transizione dallo stato iniziale
    const stile = `opacity ${durata}ms ease, transform ${durata}ms ease`;
    nuovo.style.transition = stile;
    vecchio.style.transition = stile;
    Object.assign(nuovo.style, NEUTRO);
    Object.assign(vecchio.style, transizione.esce);
    setTimeout(() => {
      vecchio.querySelector("video")?.pause();
      vecchio.remove();
    }, durata + 50);
  }
}

// --- Orologio ------------------------------------------------------------------

class ZonaOrologio {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, motore, config: zona.configurazione });
    el.style.color = this.config.colore;
    el.style.background = this.config.sfondo || "transparent";
    el.style.textAlign = { sinistra: "left", centro: "center", destra: "right" }[this.config.allineamento];
    const misura = Math.min(px.altezza * (this.config.mostra_data ? 0.5 : 0.75), px.larghezza / (this.config.secondi ? 4.6 : 3));
    this.ora = crea("div", "ora", el);
    this.ora.style.fontSize = `${misura}px`;
    if (this.config.mostra_data) {
      this.data = crea("div", "data", el);
      this.data.style.fontSize = `${Math.min(misura * 0.36, px.larghezza / 11)}px`;
    }
  }

  avvia() {
    const aggiorna = () => {
      const adesso = new Date();
      const fuso = this.motore.fuso;
      this.ora.textContent = adesso.toLocaleTimeString("it-IT", {
        timeZone: fuso, hour: "2-digit", minute: "2-digit", ...(this.config.secondi ? { second: "2-digit" } : {}),
      });
      if (this.data) {
        this.data.textContent = adesso.toLocaleDateString("it-IT", {
          timeZone: fuso, weekday: "long", day: "numeric", month: "long",
        });
      }
    };
    aggiorna();
    this.timer = setInterval(aggiorna, 1000);
  }

  ferma() {
    clearInterval(this.timer);
  }
}

// --- Meteo ---------------------------------------------------------------------

// Icone semplici disegnate qui: i box Android spesso non hanno emoji a colori.
const SOLE = '<circle cx="32" cy="32" r="12" fill="#ffc83d"/><g stroke="#ffc83d" stroke-width="4" stroke-linecap="round"><path d="M32 6v8M32 50v8M6 32h8M50 32h8M13.6 13.6l5.7 5.7M44.7 44.7l5.7 5.7M13.6 50.4l5.7-5.7M44.7 19.3l5.7-5.7"/></g>';
const NUVOLA = '<path d="M20 50h26a11 11 0 0 0 0-22 15 15 0 0 0-29-2 10 10 0 0 0 3 24z" fill="#e6ecf2"/>';
const ICONE = {
  sole: SOLE,
  sole_nuvole: '<g transform="translate(-8 -8) scale(.8)">' + SOLE + "</g>" + NUVOLA,
  nuvole: NUVOLA,
  pioggia: NUVOLA + '<g stroke="#5fb4ff" stroke-width="4" stroke-linecap="round"><path d="M24 54l-3 7M34 54l-3 7M44 54l-3 7"/></g>',
  neve: NUVOLA + '<g fill="#fff"><circle cx="23" cy="58" r="3"/><circle cx="33" cy="60" r="3"/><circle cx="43" cy="58" r="3"/></g>',
  temporale: NUVOLA + '<path d="M34 50l-8 10h7l-4 9 11-13h-7l4-6z" fill="#ffc83d"/>',
  nebbia: '<g stroke="#e6ecf2" stroke-width="5" stroke-linecap="round"><path d="M12 24h40M8 34h48M14 44h36"/></g>',
};
const AGGIORNA_METEO = 10 * 60 * 1000;

class ZonaMeteo {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, zona, motore, config: zona.configurazione });
    el.style.color = this.config.colore;
    el.style.background = this.config.sfondo || "transparent";
    const orizzontale = px.larghezza > px.altezza * 1.6;
    el.classList.add(orizzontale ? "in-riga" : "in-colonna");
    const base = orizzontale ? Math.min(px.altezza, px.larghezza / 4) : Math.min(px.larghezza / 2.4, px.altezza / 3.2);
    this.icona = crea("div", "icona", el);
    Object.assign(this.icona.style, { width: `${base * 0.9}px`, height: `${base * 0.9}px` });
    const testi = crea("div", "testi", el);
    this.temperatura = crea("div", "temperatura", testi);
    this.temperatura.style.fontSize = `${base * 0.55}px`;
    this.dettagli = crea("div", "dettagli", testi);
    this.dettagli.style.fontSize = `${base * 0.17}px`;
    this.localita = crea("div", "localita", testi);
    this.localita.style.fontSize = `${base * 0.17}px`;
    this.localita.textContent = this.config.localita;
  }

  avvia() {
    const aggiorna = async () => {
      try {
        const { meteo } = await this.motore.fonte.dati(this.zona.id);
        if (!meteo) return;
        this.icona.innerHTML = `<svg viewBox="0 0 64 70">${ICONE[meteo.icona] || NUVOLA}</svg>`;
        this.temperatura.textContent = `${meteo.temperatura}°`;
        this.dettagli.textContent = `${meteo.descrizione} · ${meteo.minima}° / ${meteo.massima}°`;
      } catch {
        // Si tiene l'ultimo dato mostrato.
      }
    };
    aggiorna();
    this.timer = setInterval(aggiorna, AGGIORNA_METEO);
  }

  ferma() {
    clearInterval(this.timer);
  }
}

// --- Notizie -------------------------------------------------------------------

class ZonaNotizie {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, zona, motore, px, config: zona.configurazione });
    Object.assign(el.style, { color: this.config.colore, background: this.config.sfondo });
    this.rullo = crea("div", "rullo", el);
    this.rullo.style.fontSize = `${px.altezza * 0.5}px`;
    this.titoli = [...this.config.messaggi];
    this.attivo = false;
  }

  async avvia() {
    this.attivo = true;
    const aggiorna = async () => {
      try {
        const { notizie } = await this.motore.fonte.dati(this.zona.id);
        if (notizie?.length) this.titoli = notizie;
      } catch {
        // Restano i titoli già scaricati.
      }
    };
    this.timer = setInterval(aggiorna, Math.min(this.config.aggiornamento_minuti, 10) * 60 * 1000);
    // Il primo giro parte con le notizie, se arrivano in fretta; altrimenti con i soli messaggi.
    await Promise.race([aggiorna(), attendi(3000)]);
    this.scorri();
  }

  // Un giro completo alla volta: i titoli nuovi entrano al giro successivo, senza salti.
  scorri() {
    if (!this.attivo) return;
    if (!this.titoli.length) {
      setTimeout(() => this.scorri(), 2000);
      return;
    }
    this.rullo.textContent = this.titoli.join("   •   ");
    const percorso = this.px.larghezza + this.rullo.scrollWidth;
    this.animazione = this.rullo.animate(
      [{ transform: `translateX(${this.px.larghezza}px)` }, { transform: `translateX(${-this.rullo.scrollWidth}px)` }],
      { duration: (percorso / this.config.velocita) * 1000, easing: "linear" },
    );
    this.animazione.onfinish = () => this.scorri();
  }

  ferma() {
    this.attivo = false;
    clearInterval(this.timer);
    this.animazione?.cancel();
  }
}

// --- Testo e immagine ----------------------------------------------------------

class ZonaTesto {
  constructor(el, zona, px) {
    const c = zona.configurazione;
    Object.assign(el.style, {
      color: c.colore, background: c.sfondo || "transparent", fontSize: `${(px.altezza * c.dimensione) / 100}px`,
      justifyContent: { sinistra: "flex-start", centro: "center", destra: "flex-end" }[c.allineamento],
      textAlign: { sinistra: "left", centro: "center", destra: "right" }[c.allineamento],
    });
    crea("div", "testo", el).textContent = c.testo;
  }

  avvia() {}

  ferma() {}
}

const OBJECT_FIT = { adatta: "contain", sfondo: "contain", riempi: "cover", allunga: "fill" };

// Applica l'adattamento a un'immagine o a un video. «sfondo» mette dietro la stessa
// immagine ingrandita e sfocata, così le bande vuote prendono i suoi colori
// (per i video solo «adatta»: sfocare un video costa troppo ai player deboli).
function adatta(media, modo, url) {
  media.style.objectFit = OBJECT_FIT[modo] || "contain";
  if (modo !== "sfondo" || media.tagName !== "IMG") return;
  const dietro = crea("img", "media sfocato");
  dietro.alt = "";
  dietro.src = url;
  media.before(dietro);
}

class ZonaImmagine {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, zona, motore });
  }

  async avvia() {
    const id = this.zona.configurazione.contenuto;
    const url = await this.motore.fonte.file(id, this.motore.manifest.contenuti[id]);
    if (!url) return;
    const img = crea("img", "media", this.el);
    adatta(img, this.zona.configurazione.adattamento, url);
    img.src = url;
  }

  ferma() {}
}

// --- Eliminacode -----------------------------------------------------------------

const OGNI_CODA = 2000;

// Il «din-don» degli eliminacode, sintetizzato: nessun file audio da distribuire.
let audio = null;
function dinDon() {
  try {
    audio = audio || new AudioContext();
    const adesso = audio.currentTime;
    [[784, 0], [622, 0.45]].forEach(([frequenza, ritardo]) => {
      const oscillatore = audio.createOscillator();
      const volume = audio.createGain();
      oscillatore.frequency.value = frequenza;
      volume.gain.setValueAtTime(0.0001, adesso + ritardo);
      volume.gain.exponentialRampToValueAtTime(0.5, adesso + ritardo + 0.02);
      volume.gain.exponentialRampToValueAtTime(0.0001, adesso + ritardo + 1.2);
      oscillatore.connect(volume).connect(audio.destination);
      oscillatore.start(adesso + ritardo);
      oscillatore.stop(adesso + ritardo + 1.3);
    });
  } catch {
    // Nessun audio disponibile: resta il lampeggio.
  }
}

// «Salumeria, numero 27» con la voce italiana del sistema, se c'è (Windows e Android ne hanno una).
function annuncia(tipo, nome, numero) {
  if (tipo === "nessuno") return;
  dinDon();
  if (tipo !== "voce" || !("speechSynthesis" in window)) return;
  const voce = speechSynthesis.getVoices().find((v) => v.lang?.toLowerCase().startsWith("it"));
  if (!voce) return;
  const frase = new SpeechSynthesisUtterance(`${nome}, numero ${numero}`);
  Object.assign(frase, { voice: voce, lang: voce.lang, rate: 0.95 });
  setTimeout(() => speechSynthesis.speak(frase), 1300);
}

// Il reparto come appare in questa zona: anagrafica più le personalizzazioni della zona.
function aspetto(coda, config) {
  const proprio = config.personalizza?.[coda.id] || {};
  return {
    ...coda,
    nome: proprio.etichetta || coda.nome,
    colore: proprio.colore || coda.colore,
    colore_testo: proprio.colore_testo || coda.colore_testo || "#ffffff",
  };
}

const mostraNumero = (numero) => (numero === null || numero === undefined ? "–" : String(numero));
const testoCoda = (modello, n) => (modello ? modello.replace("{n}", n) : "");

class ZonaCoda {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, zona, px, motore, config: zona.configurazione });
    this.chiamate = new Map(); // reparto -> chiamato_il già visto
    this.riquadri = new Map();
  }

  avvia() {
    const aggiorna = async () => {
      try {
        const { code } = await this.motore.fonte.dati(this.zona.id);
        this.mostra((code || []).map((c) => aspetto(c, this.config)));
      } catch {
        // Si tiene l'ultimo stato.
      }
    };
    aggiorna();
    this.timer = setInterval(aggiorna, OGNI_CODA);
  }

  mostra(code) {
    const firma = code.map((c) => `${c.id}:${c.nome}:${c.colore}:${c.colore_testo}`).join("|");
    if (firma !== this.firma) this.costruisci(code, firma);
    for (const coda of code) {
      const riquadro = this.riquadri.get(coda.id);
      riquadro.numero.textContent = mostraNumero(coda.numero);
      if (riquadro.coda) riquadro.coda.textContent = testoCoda(this.config.testo_coda, coda.in_coda);
      const vista = this.chiamate.get(coda.id);
      if (vista !== undefined && coda.chiamato_il && coda.chiamato_il !== vista) {
        riquadro.el.classList.remove("chiamata");
        riquadro.el.getBoundingClientRect();
        riquadro.el.classList.add("chiamata");
        annuncia(this.config.annuncio, coda.nome, coda.numero);
      }
      this.chiamate.set(coda.id, coda.chiamato_il);
    }
  }

  // Righe e colonne: in colonna, in riga, a griglia, oppure secondo la forma della zona.
  griglia(n) {
    const { larghezza, altezza } = this.px;
    switch (this.config.disposizione) {
      case "colonna": return [1, n];
      case "riga": return [n, 1];
      case "griglia": {
        const colonne = Math.ceil(Math.sqrt(n * (larghezza / altezza)));
        return [Math.min(colonne, n), Math.ceil(n / Math.min(colonne, n))];
      }
      default: return altezza >= larghezza ? [1, n] : [n, 1];
    }
  }

  costruisci(code, firma) {
    this.firma = firma;
    this.el.replaceChildren();
    this.riquadri.clear();
    const [colonne, righe] = this.griglia(Math.max(code.length, 1));
    Object.assign(this.el.style, {
      display: "grid",
      gridTemplateColumns: `repeat(${colonne}, 1fr)`,
      gridTemplateRows: `repeat(${righe}, 1fr)`,
    });
    const w = this.px.larghezza / colonne;
    const h = this.px.altezza / righe;
    for (const coda of code) {
      const el = crea("div", "reparto", this.el);
      Object.assign(el.style, { background: coda.colore, color: coda.colore_testo });
      if (!this.config.bordo) el.style.border = "0";
      const nome = crea("div", "nome", el);
      nome.textContent = coda.nome;
      nome.style.fontSize = `${Math.min(h * 0.17, (w / Math.max(coda.nome.length, 6)) * 1.35)}px`;
      const numero = crea("div", "numero", el);
      numero.style.fontSize = `${Math.min(h * 0.5, w * 0.42)}px`;
      let codaEl = null;
      if (this.config.testo_coda) {
        codaEl = crea("div", "in-coda", el);
        codaEl.style.fontSize = `${Math.min(h * 0.09, w / 14)}px`;
      }
      this.riquadri.set(coda.id, { el, numero, coda: codaEl });
    }
  }

  ferma() {
    clearInterval(this.timer);
  }
}

// Il biglietto per la stampante Epson (ePOS-Print XML, la stessa interfaccia dell'SDK Epson).
function xml(testo) {
  return String(testo).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

async function stampaEpson(indirizzo, biglietto) {
  const corpo =
    '<?xml version="1.0" encoding="utf-8"?>' +
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>' +
    '<epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">' +
    '<text align="center"/>' +
    (biglietto.intestazione ? `<text width="1" height="1" em="true">${xml(biglietto.intestazione)}&#10;</text>` : "") +
    `<text width="2" height="2" em="true">${xml(biglietto.reparto)}&#10;</text>` +
    `<text width="6" height="6" em="true">${xml(biglietto.numero)}&#10;</text>` +
    `<text width="1" height="1" em="false">${xml(biglietto.davanti)}&#10;${xml(biglietto.messaggio)}&#10;${xml(biglietto.quando)}&#10;</text>` +
    '<cut type="feed"/></epos-print></s:Body></s:Envelope>';
  // Stesso protocollo della pagina: su HTTPS la stampante va usata in HTTPS
  // (il suo certificato va accettato una volta sul totem).
  const url = `${location.protocol}//${indirizzo}/cgi-bin/epos/service.cgi?devid=local_printer&timeout=10000`;
  const controllo = new AbortController();
  const limite = setTimeout(() => controllo.abort(), 12000);
  try {
    const risposta = await fetch(url, {
      method: "POST", headers: { "Content-Type": "text/xml; charset=utf-8" }, body: corpo, signal: controllo.signal,
    });
    const testo = await risposta.text();
    const esito = new DOMParser().parseFromString(testo, "text/xml").querySelector("response");
    if (esito?.getAttribute("success") !== "true") throw new Error(esito?.getAttribute("code") || `HTTP ${risposta.status}`);
  } finally {
    clearTimeout(limite);
  }
}

function stampaBrowser(biglietto) {
  // Con Chrome avviato con --kiosk --kiosk-printing esce senza finestre sulla stampante predefinita.
  let foglio = document.getElementById("biglietto");
  if (!foglio) {
    foglio = document.createElement("div");
    foglio.id = "biglietto";
    document.body.appendChild(foglio);
  }
  foglio.replaceChildren();
  for (const [classe, testo] of [
    ["intestazione", biglietto.intestazione], ["reparto", biglietto.reparto], ["numero", biglietto.numero],
    ["riga", biglietto.davanti], ["riga", biglietto.messaggio], ["riga", biglietto.quando],
  ]) {
    if (testo !== "" && testo !== null && testo !== undefined) crea("div", classe, foglio).textContent = testo;
  }
  window.print();
}

class ZonaPrendiNumero {
  constructor(el, zona, px, motore) {
    Object.assign(this, { el, zona, px, motore, config: zona.configurazione });
    el.style.background = this.config.sfondo_pulsanti;
    if (this.config.titolo) {
      const titolo = crea("div", "titolo", el);
      titolo.textContent = this.config.titolo;
      Object.assign(titolo.style, {
        background: this.config.sfondo, color: this.config.colore, fontSize: `${Math.min(px.altezza * 0.07, px.larghezza / 18)}px`,
      });
    }
    this.pulsanti = crea("div", "pulsanti", el);
    this.esito = crea("div", "esito", el);
    this.esito.hidden = true;
    this.occupato = false;
  }

  avvia() {
    const aggiorna = async () => {
      try {
        const { code } = await this.motore.fonte.dati(this.zona.id);
        this.mostra((code || []).map((c) => aspetto(c, this.config)));
      } catch {
        // Si tiene l'ultimo stato.
      }
    };
    aggiorna();
    this.timer = setInterval(aggiorna, OGNI_CODA);
  }

  mostra(code) {
    const firma = code.map((c) => `${c.id}:${c.nome}:${c.colore}:${c.colore_testo}`).join("|");
    if (firma !== this.firma) {
      this.firma = firma;
      this.pulsanti.replaceChildren();
      this.contatori = new Map();
      const colonne = this.config.colonne || (code.length > 1 ? 2 : 1);
      const righe = Math.ceil(code.length / colonne) || 1;
      const altezza = (this.px.altezza * (this.config.titolo ? 0.8 : 0.95)) / righe;
      for (const coda of code) {
        const pulsante = crea("button", "pulsante", this.pulsanti);
        Object.assign(pulsante.style, {
          background: coda.colore, color: coda.colore_testo, borderRadius: `${this.config.arrotondamento}px`,
          width: `${90 / colonne}%`, height: `${altezza * 0.8}px`,
        });
        const nome = crea("div", "nome", pulsante);
        nome.textContent = coda.nome;
        nome.style.fontSize = `${Math.min(altezza * 0.24, this.px.larghezza / colonne / 9)}px`;
        if (this.config.testo_coda) {
          const inCoda = crea("div", "in-coda", pulsante);
          inCoda.style.fontSize = `${Math.min(altezza * 0.13, this.px.larghezza / colonne / 16)}px`;
          this.contatori.set(coda.id, inCoda);
        }
        pulsante.addEventListener("click", () => this.prendi(coda));
      }
    }
    for (const coda of code) {
      const contatore = this.contatori.get(coda.id);
      if (contatore) contatore.textContent = testoCoda(this.config.testo_coda, coda.in_coda);
    }
  }

  async prendi(coda) {
    if (this.occupato) return; // un tocco alla volta: niente biglietti doppi
    this.occupato = true;
    try {
      // Il biglietto prende nome e colori come appaiono sul pulsante.
      const biglietto = aspetto(await this.motore.fonte.emetti(this.zona.id, coda.id), this.config);
      biglietto.reparto = coda.nome;
      biglietto.colore = coda.colore;
      biglietto.colore_testo = coda.colore_testo;
      const quando = new Date().toLocaleString("it-IT", { timeZone: this.motore.fuso, dateStyle: "short", timeStyle: "short" });
      const davanti = biglietto.davanti > 0 ? `Persone prima di te: ${biglietto.davanti}` : "Sei il prossimo!";
      const dati = { ...biglietto, davanti, quando, intestazione: this.config.intestazione, messaggio: this.config.messaggio };
      if (biglietto.anteprima) {
        this.mostraEsito(dati, "Anteprima: biglietto di prova, non conta e non si stampa. I biglietti veri li emette il totem.");
        return;
      }
      let errore = null;
      try {
        if (this.config.stampa === "epson") await stampaEpson(this.config.stampante, dati);
        else if (this.config.stampa === "browser") stampaBrowser(dati);
      } catch (e) {
        errore = `Stampante non raggiungibile o spenta (${e.name === "AbortError" ? "tempo scaduto" : e.message}). Ricorda il tuo numero.`;
      }
      this.mostraEsito(dati, errore);
    } catch {
      this.mostraEsito(null, "Servizio non disponibile, riprova tra poco.");
    }
  }

  mostraEsito(biglietto, errore) {
    this.esito.replaceChildren();
    this.esito.hidden = false;
    const scala = Math.min(this.px.altezza, this.px.larghezza);
    if (biglietto) {
      Object.assign(this.esito.style, { background: biglietto.colore, color: biglietto.colore_testo });
      crea("div", "reparto", this.esito).textContent = biglietto.reparto;
      const numero = crea("div", "numero", this.esito);
      numero.textContent = mostraNumero(biglietto.numero);
      numero.style.fontSize = `${scala * 0.38}px`;
      crea("div", "riga", this.esito).textContent = biglietto.davanti;
    } else {
      Object.assign(this.esito.style, { background: "#5a5a5a", color: "#ffffff" });
    }
    if (errore) crea("div", "errore", this.esito).textContent = errore;
    this.esito.style.fontSize = `${scala * 0.07}px`;
    setTimeout(() => {
      this.esito.hidden = true;
      this.occupato = false;
    }, errore ? 7000 : 4000);
  }

  ferma() {
    clearInterval(this.timer);
  }
}

const TIPI = {
  slide: ZonaSlide,
  orologio: ZonaOrologio,
  meteo: ZonaMeteo,
  notizie: ZonaNotizie,
  testo: ZonaTesto,
  immagine: ZonaImmagine,
  coda: ZonaCoda,
  prendi_numero: ZonaPrendiNumero,
};
