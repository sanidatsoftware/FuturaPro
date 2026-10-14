// Le spiegazioni al passaggio del mouse: ogni elemento con data-aiuto="…" mostra un
// riquadro con il testo, dopo un attimo di sosta. Funziona anche con la tastiera (focus).
// Il testo passa da textContent.

const RITARDO = 450;
let riquadro = null;
let timer = null;
let corrente = null;

function prepara() {
  if (riquadro) return;
  riquadro = document.createElement("div");
  riquadro.className = "aiuto-mouse";
  riquadro.setAttribute("role", "tooltip");
  riquadro.hidden = true;
  document.body.appendChild(riquadro);
}

function posiziona(el) {
  const r = el.getBoundingClientRect();
  const margine = 8;
  riquadro.style.left = "0px";
  riquadro.style.top = "0px";
  const b = riquadro.getBoundingClientRect();
  let x = r.left + r.width / 2 - b.width / 2;
  x = Math.max(margine, Math.min(x, window.innerWidth - b.width - margine));
  // Sotto l'elemento; se non c'è spazio, sopra.
  let y = r.bottom + margine;
  riquadro.classList.toggle("sopra", y + b.height > window.innerHeight - margine);
  if (y + b.height > window.innerHeight - margine) y = r.top - b.height - margine;
  riquadro.style.left = `${Math.round(x)}px`;
  riquadro.style.top = `${Math.round(Math.max(margine, y))}px`;
}

function mostra(el) {
  prepara();
  corrente = el;
  riquadro.textContent = el.dataset.aiuto;
  riquadro.hidden = false;
  riquadro.classList.remove("visibile");
  posiziona(el);
  requestAnimationFrame(() => riquadro.classList.add("visibile"));
}

function nascondi() {
  clearTimeout(timer);
  corrente = null;
  if (riquadro) {
    riquadro.classList.remove("visibile");
    riquadro.hidden = true;
  }
}

function bersaglio(evento) {
  return evento.target instanceof Element ? evento.target.closest("[data-aiuto]") : null;
}

export function attivaAiuti() {
  document.addEventListener("mouseover", (e) => {
    const el = bersaglio(e);
    if (el === corrente) return;
    nascondi();
    if (el && el.dataset.aiuto) timer = setTimeout(() => mostra(el), RITARDO);
  });
  document.addEventListener("focusin", (e) => {
    const el = bersaglio(e);
    nascondi();
    if (el && el.dataset.aiuto && el.matches(":focus-visible")) timer = setTimeout(() => mostra(el), RITARDO);
  });
  for (const evento of ["mousedown", "scroll", "keydown", "focusout"]) document.addEventListener(evento, nascondi, true);
}
