"""Rigenera ``clip_classi.npy`` da ``frasi.json`` (solo in sviluppo, se si cambiano le frasi).

Serve la parte di testo di CLIP e il suo tokenizer, che sul server non servono:
    pip install tokenizers
    (scaricare onnx/text_model.onnx e tokenizer.json dalla stessa revisione di scarica_modello.py)
    python plugin/modello/prepara_classi.py text_model.onnx tokenizer.json
Per ogni classe si fa la media delle frasi (normalizzate): il filtro confronta ogni immagine con
queste quattro direzioni.
"""

import json
import sys
from pathlib import Path

import numpy
import onnxruntime
from tokenizers import Tokenizer

CARTELLA = Path(__file__).resolve().parent


def principale(modello_testo: str, tokenizer: str) -> None:
    frasi = json.loads((CARTELLA / "frasi.json").read_text())
    sessione, tok = onnxruntime.InferenceSession(modello_testo), Tokenizer.from_file(tokenizer)

    def vettore(testo):
        e = sessione.run(None, {"input_ids": numpy.array([tok.encode(testo).ids], dtype=numpy.int64)})[0][0]
        return e / numpy.linalg.norm(e)

    righe = []
    for classe in ("nudo", "intimo", "vestito", "altro"):
        media = numpy.mean([vettore(f) for f in frasi[classe]], axis=0)
        righe.append(media / numpy.linalg.norm(media))
    numpy.save(CARTELLA / "clip_classi.npy", numpy.stack(righe).astype(numpy.float32))


if __name__ == "__main__":
    principale(*sys.argv[1:3])
