"""Scarica il modello del Filtro contenuti (CLIP ViT-B/32, parte delle immagini, quantizzata).

Lo usa il Dockerfile durante la costruzione dell'immagine e, se lì non è riuscito, l'avvio del
container (nella cartella dei dati, che resta tra un aggiornamento e l'altro). In sviluppo:
    python plugin/modello/scarica_modello.py
Il file è controllato con lo SHA-256: se non corrisponde, non si salva.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

REVISIONE = "d15189d7028b43f1d3e65039190477f6af591c2a"
URL = f"https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/{REVISIONE}/onnx/vision_model_quantized.onnx"
SHA256 = "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299"
NOME = "clip_visione.onnx"
DESTINAZIONE = Path(__file__).resolve().parent / NOME


def scarica(destinazione: Path = DESTINAZIONE) -> bool:
    if destinazione.exists() and hashlib.sha256(destinazione.read_bytes()).hexdigest() == SHA256:
        print("Filtro contenuti: modello già presente.")
        return True
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_suffix(".parziale")
    impronta = hashlib.sha256()
    try:
        with urllib.request.urlopen(URL, timeout=60) as risposta, open(temporaneo, "wb") as uscita:
            while blocco := risposta.read(1 << 20):
                impronta.update(blocco)
                uscita.write(blocco)
    except OSError as errore:
        temporaneo.unlink(missing_ok=True)
        print(f"Filtro contenuti: modello NON scaricato ({errore}). Il filtro resterà non disponibile.", file=sys.stderr)
        return False
    if impronta.hexdigest() != SHA256:
        temporaneo.unlink(missing_ok=True)
        print("Filtro contenuti: il modello scaricato non corrisponde (SHA-256): scartato.", file=sys.stderr)
        return False
    temporaneo.replace(destinazione)
    print("Filtro contenuti: modello scaricato.")
    return True


if __name__ == "__main__":
    # Non blocca né la costruzione dell'immagine né l'avvio: senza modello il pannello lo segnala e,
    # con il filtro attivo, i contenuti non si possono caricare (nessuno passa senza controllo).
    # Con un percorso (avvio del container) si riprova lì, solo se il modello non c'è ancora.
    if len(sys.argv) > 1:
        if not DESTINAZIONE.exists():
            scarica(Path(sys.argv[1]) / NOME)
    else:
        scarica()
