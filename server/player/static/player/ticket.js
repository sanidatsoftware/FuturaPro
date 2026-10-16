// Il biglietto stampato secondo il Layout Ticket: elementi in colonna o liberi (logo, intestazione,
// reparto, numero, testo di fine biglietto…), ognuno con carattere, grandezza e allineamento.
// Si disegna come immagine alla risoluzione della stampante (203 dpi, 8 punti per mm): esce
// identico sulla Epson di rete (immagine raster ePOS-Print) e sulla stampante di sistema.
// Lo usano il totem (motore.js) e l'anteprima del pannello.

let caricamentoQr = null;

function libreriaQr() {
  if (window.qrcode) return Promise.resolve();
  caricamentoQr ??= new Promise((ok, ko) => {
    const script = document.createElement("script");
    script.src = new URL("./vendor/qrcode.js", import.meta.url).href;
    script.onload = ok;
    script.onerror = () => ko(new Error("qrcode.js non caricato"));
    document.head.appendChild(script);
  });
  return caricamentoQr;
}

// Le immagini (il logo) si decodificano una volta sola: i biglietti dopo il primo non aspettano.
const immagini = new Map();

function immagine(src) {
  if (!immagini.has(src)) {
    immagini.set(src, new Promise((ok) => {
      const img = new Image();
      img.onload = () => ok(img);
      img.onerror = () => {
        immagini.delete(src);
        ok(null);
      };
      img.src = src;
    }));
  }
  return immagini.get(src);
}

// Prepara in anticipo quello che serve al biglietto (logo e libreria del QR), così al tocco
// del cliente si disegna e basta.
export function preparaTicket(layout) {
  if (layout?.logo) immagine(layout.logo);
  if (layout?.elementi?.some((e) => e.campo === "qr" && e.visibile)) libreriaQr().catch(() => {});
}

// La data e l'ora del biglietto nel formato scelto (es. «15/10/26 10:42», «giovedì 15 ottobre 2026, 10:42»).
function dataDelBiglietto(formato, dati) {
  const istante = dati.istante ? new Date(dati.istante) : null;
  if (!istante) return dati.quando;
  const opzioni = { timeZone: dati.fuso || undefined };
  if (formato === "data") return istante.toLocaleDateString("it-IT", { ...opzioni, dateStyle: "short" });
  if (formato === "ora") return istante.toLocaleTimeString("it-IT", { ...opzioni, hour: "2-digit", minute: "2-digit" });
  if (formato === "esteso") {
    return istante.toLocaleString("it-IT", { ...opzioni, weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  return dati.quando || istante.toLocaleString("it-IT", { ...opzioni, dateStyle: "short", timeStyle: "short" });
}

// Il testo di ogni elemento: i dati del biglietto, o il testo fisso del layout.
function testoDi(el, layout, dati) {
  switch (el.campo) {
    case "intestazione": return layout.intestazione || el.testo;
    case "messaggio": return layout.messaggio || el.testo;
    case "testo": return el.testo;
    case "reparto": return dati.reparto;
    case "numero": return dati.numero === null || dati.numero === undefined ? "" : String(dati.numero);
    case "davanti": return dati.davanti;
    case "data": return dataDelBiglietto(el.formato, dati);
    default: return "";
  }
}

function font(el) {
  const famiglia = el.carattere.includes(" ") ? `"${el.carattere}", sans-serif` : `${el.carattere}, sans-serif`;
  return `${el.corsivo ? "italic " : ""}${el.grassetto ? "bold " : ""}${el.dimensione}px ${famiglia}`;
}

// Le righe del testo dentro la larghezza (a capo sulle parole, e sui ritorni a capo scritti).
function righe(ctx, testo, larghezza) {
  const uscita = [];
  for (const paragrafo of String(testo).split("\n")) {
    let riga = "";
    for (const parola of paragrafo.split(/\s+/).filter(Boolean)) {
      const prova = riga ? `${riga} ${parola}` : parola;
      if (ctx.measureText(prova).width <= larghezza || !riga) riga = prova;
      else {
        uscita.push(riga);
        riga = parola;
      }
    }
    uscita.push(riga);
  }
  return uscita;
}

// La stampante fa solo punti neri: le sfumature del logo diventano una retinatura
// (Floyd-Steinberg), così si vedono anche i colori chiari e l'anteprima è già la stampa.
function retina(ctx, x, y, w, h) {
  const area = ctx.getImageData(x, y, w, h);
  const p = area.data;
  const grigio = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) grigio[i] = p[i * 4] * 0.299 + p[i * 4 + 1] * 0.587 + p[i * 4 + 2] * 0.114;
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const i = r * w + c;
      const nuovo = grigio[i] < 128 ? 0 : 255;
      const errore = grigio[i] - nuovo;
      grigio[i] = nuovo;
      if (c + 1 < w) grigio[i + 1] += (errore * 7) / 16;
      if (r + 1 < h) {
        if (c > 0) grigio[i + w - 1] += (errore * 3) / 16;
        grigio[i + w] += (errore * 5) / 16;
        if (c + 1 < w) grigio[i + w + 1] += errore / 16;
      }
    }
  }
  for (let i = 0; i < w * h; i++) p[i * 4] = p[i * 4 + 1] = p[i * 4 + 2] = grigio[i];
  ctx.putImageData(area, x, y);
}

// Il canvas del biglietto. dati: reparto, numero, davanti, quando, qr (indirizzo), testo_qr.
// Disposizione «guidata»: elementi in colonna, uno sotto l'altro, ognuno con il suo allineamento.
// «libera»: ogni elemento nel suo riquadro (x, y e larghezza w, in punti), dove lo si è messo;
// il testo va a capo dentro il riquadro e vi si allinea. Il biglietto è lungo quanto serve.
export async function disegnaTicket(layout, dati) {
  const W = layout.punti || 576;
  const margine = 8;
  const utile = W - 2 * margine;
  const libera = layout.disposizione === "libera";
  const misura = document.createElement("canvas").getContext("2d");
  const logo = layout.logo ? await immagine(layout.logo) : null;
  let qr = null;
  if (dati.qr && layout.elementi.some((e) => e.campo === "qr" && e.visibile)) {
    try {
      await libreriaQr();
      qr = window.qrcode(0, "M");
      qr.addData(dati.qr);
      qr.make();
    } catch {
      qr = null; // senza QR il biglietto esce lo stesso
    }
  }

  // Primo passo: i blocchi con il loro riquadro (x, w; l'altezza h; y dopo).
  const blocchi = [];
  for (const [indice, el] of layout.elementi.entries()) {
    if (!el.visibile) continue;
    // Il riquadro libero, tenuto dentro la carta.
    const lx = libera ? Math.max(0, Math.min(W - 16, el.x ?? margine)) : 0;
    const lw = libera ? Math.max(16, Math.min(W - lx, el.w ?? utile)) : 0;
    const allinea = (w) => (el.allineamento === "sinistra" ? margine : el.allineamento === "destra" ? W - margine - w : Math.round((W - w) / 2));
    let b = null;
    if (el.campo === "logo") {
      if (!logo) continue;
      const w = libera ? lw : Math.min(logo.width, Math.round((utile * el.larghezza) / 100));
      b = { tipo: "logo", x: libera ? lx : allinea(w), w, h: Math.round((logo.height * w) / logo.width) };
    } else if (el.campo === "qr") {
      if (!qr) continue;
      const lato = libera ? lw : Math.round((utile * el.larghezza) / 100);
      const sotto = dati.testo_qr ? Math.round(lato * 0.12) : 0;
      b = { tipo: "qr", x: libera ? lx : allinea(lato), w: lato, h: lato + (sotto ? sotto * 1.6 : 0), sotto };
    } else if (el.campo === "linea") {
      b = { tipo: "linea", x: libera ? lx : margine, w: libera ? lw : utile, h: Math.max(2, Math.round(el.dimensione / 10)) };
    } else {
      let testo = testoDi(el, layout, dati);
      if (!testo) continue;
      if (el.maiuscolo) testo = testo.toLocaleUpperCase("it-IT");
      misura.font = font(el);
      const larga = libera ? lw : utile;
      const linee = righe(misura, testo, larga - (el.inverso ? 16 : 0));
      const passo = Math.round(el.dimensione * 1.15);
      b = { tipo: "testo", x: libera ? lx : margine, w: larga, linee, passo, h: linee.length * passo + (el.inverso ? 12 : 0) };
    }
    blocchi.push({ el, indice, ...b });
  }
  // Le quote: una sotto l'altra, oppure dove le ha messe chi ha composto il biglietto.
  let quota = 8;
  for (const b of blocchi) {
    if (libera) b.y = Math.max(0, b.el.y ?? quota);
    else b.y = quota;
    quota = (libera ? Math.max(quota, b.y + b.h) : b.y + b.h + b.el.spazio);
  }
  const H = Math.max(40, libera ? Math.max(0, ...blocchi.map((b) => b.y + b.h)) + 16 : quota + 8);

  // Secondo passo: il disegno, nero su bianco.
  const tela = document.createElement("canvas");
  tela.width = W;
  tela.height = H;
  const ctx = tela.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#000";
  ctx.textBaseline = "top";
  // Dove sta ogni elemento (per sceglierlo, spostarlo e ridimensionarlo nell'anteprima del pannello).
  tela.blocchi = [];
  for (const b of blocchi) {
    const { el, x, y } = b;
    tela.blocchi.push({ indice: b.indice, x, y, w: b.w, h: b.h, tipo: b.tipo });
    if (b.tipo === "logo") {
      ctx.drawImage(logo, x, y, b.w, b.h);
      retina(ctx, x, y, Math.min(b.w, W - x), Math.min(b.h, H - y));
    } else if (b.tipo === "qr") {
      const moduli = qr.getModuleCount();
      const lato = b.w / moduli;
      for (let r = 0; r < moduli; r++) {
        for (let c = 0; c < moduli; c++) if (qr.isDark(r, c)) ctx.fillRect(Math.floor(x + c * lato), Math.floor(y + r * lato), Math.ceil(lato), Math.ceil(lato));
      }
      if (b.sotto) {
        ctx.font = `${b.sotto}px sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(dati.testo_qr, libera ? x + b.w / 2 : W / 2, y + b.w + b.sotto * 0.3, libera ? Math.max(b.w, 120) : utile);
      }
    } else if (b.tipo === "linea") {
      ctx.fillRect(x, y, b.w, b.h);
    } else {
      ctx.font = font(el);
      if (el.inverso) {
        ctx.fillRect(x, y, b.w, b.h);
        ctx.fillStyle = "#fff";
      }
      const rientro = el.inverso ? 8 : 0;
      ctx.textAlign = el.allineamento === "sinistra" ? "left" : el.allineamento === "destra" ? "right" : "center";
      const tx = el.allineamento === "sinistra" ? x + rientro : el.allineamento === "destra" ? x + b.w - rientro : x + b.w / 2;
      b.linee.forEach((linea, i) => ctx.fillText(linea, tx, y + (el.inverso ? 6 : 0) + i * b.passo + Math.round(el.dimensione * 0.07)));
      ctx.fillStyle = "#000";
    }
  }
  return tela;
}

// I punti neri di una striscia del canvas, 1 bit per punto (riga per riga, da sinistra).
function bitDellaStriscia(ctx, W, inizio, h) {
  const pixel = ctx.getImageData(0, inizio, W, h).data;
  const perRiga = Math.ceil(W / 8);
  const byte = new Uint8Array(perRiga * h);
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < W; c++) {
      const i = (r * W + c) * 4;
      const luce = pixel[i] * 0.299 + pixel[i + 1] * 0.587 + pixel[i + 2] * 0.114;
      if (luce < 128) byte[r * perRiga + (c >> 3)] |= 0x80 >> (c & 7);
    }
  }
  return { byte, perRiga };
}

// Il canvas come immagine ePOS-Print (1 bit per punto, a strisce): da mettere in <epos-print>.
export function immagineEpson(tela) {
  const W = tela.width;
  const ctx = tela.getContext("2d");
  const parti = [];
  const STRISCIA = 240;
  for (let inizio = 0; inizio < tela.height; inizio += STRISCIA) {
    const h = Math.min(STRISCIA, tela.height - inizio);
    const { byte, perRiga } = bitDellaStriscia(ctx, W, inizio, h);
    let binario = "";
    for (let k = 0; k < byte.length; k += 0x8000) binario += String.fromCharCode.apply(null, byte.subarray(k, k + 0x8000));
    parti.push(`<image width="${perRiga * 8}" height="${h}" color="color_1" mode="mono">${btoa(binario)}</image>`);
  }
  return `${parti.join("")}<feed line="1"/><cut type="feed"/>`;
}

// Il canvas come comandi ESC/POS (immagine raster «GS v 0» a strisce, avanzamento e taglio):
// li capisce qualunque stampante termica Epson TM, e compatibile, sulla porta 9100.
export function comandiEscPos(tela) {
  const W = tela.width;
  const ctx = tela.getContext("2d");
  const parti = [Uint8Array.of(0x1b, 0x40)]; // ESC @: stampante come all'accensione
  const STRISCIA = 128;
  for (let inizio = 0; inizio < tela.height; inizio += STRISCIA) {
    const h = Math.min(STRISCIA, tela.height - inizio);
    const { byte, perRiga } = bitDellaStriscia(ctx, W, inizio, h);
    parti.push(Uint8Array.of(0x1d, 0x76, 0x30, 0x00, perRiga & 0xff, perRiga >> 8, h & 0xff, h >> 8), byte);
  }
  parti.push(Uint8Array.of(0x1b, 0x64, 0x04)); // ESC d 4: avanti di 4 righe, oltre la taglierina
  parti.push(Uint8Array.of(0x1d, 0x56, 0x42, 0x00)); // GS V B 0: taglio parziale
  const totale = new Uint8Array(parti.reduce((n, p) => n + p.length, 0));
  let posizione = 0;
  for (const p of parti) {
    totale.set(p, posizione);
    posizione += p.length;
  }
  return totale;
}
