// Le pagine di prova e le anteprime si aprono in un riquadro sopra la pagina, non in una
// scheda nuova del browser: si chiude con ✕, con Esc o con un clic fuori.

export function apriRiquadro(titolo, indirizzo, { larghezza = "min(1100px, 94vw)", altezza = "min(820px, 88vh)" } = {}) {
  chiudiRiquadro();
  const sfondo = document.createElement("div");
  sfondo.className = "riquadro-sfondo";
  sfondo.id = "riquadro-aperto";
  const box = document.createElement("div");
  box.className = "riquadro-finestra";
  Object.assign(box.style, { width: larghezza, height: altezza });
  const testa = document.createElement("div");
  testa.className = "riquadro-testa";
  const nome = document.createElement("strong");
  nome.textContent = titolo;
  const chiudi = document.createElement("button");
  chiudi.type = "button";
  chiudi.textContent = "✕";
  chiudi.className = "riquadro-chiudi";
  chiudi.dataset.aiuto = "Chiude il riquadro (anche con Esc o con un clic fuori).";
  chiudi.addEventListener("click", chiudiRiquadro);
  testa.append(nome, chiudi);
  const cornice = document.createElement("iframe");
  cornice.src = indirizzo;
  cornice.title = titolo;
  box.append(testa, cornice);
  sfondo.appendChild(box);
  sfondo.addEventListener("click", (e) => { if (e.target === sfondo) chiudiRiquadro(); });
  document.body.appendChild(sfondo);
  document.addEventListener("keydown", tastoEsc);
  chiudi.focus();
}

function tastoEsc(e) {
  if (e.key === "Escape") chiudiRiquadro();
}

export function chiudiRiquadro() {
  document.getElementById("riquadro-aperto")?.remove();
  document.removeEventListener("keydown", tastoEsc);
}

// Una pagina intera (es. l'editor dei layout) dentro il pannello, sotto il menu, alta fino in fondo.
export function paginaIncorporata(contenuto, indirizzo, titolo) {
  contenuto.classList.add("pieno");
  const cornice = document.createElement("iframe");
  cornice.className = "pagina-incorporata";
  cornice.src = indirizzo;
  cornice.title = titolo;
  contenuto.appendChild(cornice);
  const adatta = () => {
    if (!cornice.isConnected) return window.removeEventListener("resize", adatta);
    cornice.style.height = `${Math.max(400, window.innerHeight - cornice.getBoundingClientRect().top - 10)}px`;
  };
  window.addEventListener("resize", adatta);
  requestAnimationFrame(adatta);
}
