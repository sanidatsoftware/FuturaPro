"""Riconoscimento dei file caricati dal loro contenuto, non dal nome o da ciò che dichiara il browser."""

import hashlib

# (tipo, mime, verifica sui primi byte)
FORMATI = [
    ("immagine", "image/jpeg", lambda t: t.startswith(b"\xff\xd8\xff")),
    ("immagine", "image/png", lambda t: t.startswith(b"\x89PNG\r\n\x1a\n")),
    ("immagine", "image/gif", lambda t: t[:6] in (b"GIF87a", b"GIF89a")),
    ("immagine", "image/webp", lambda t: t[:4] == b"RIFF" and t[8:12] == b"WEBP"),
    ("video", "video/mp4", lambda t: t[4:8] == b"ftyp" and t[8:11] != b"qt "),
    ("video", "video/quicktime", lambda t: t[4:12] == b"ftypqt  "),
    ("video", "video/webm", lambda t: t.startswith(b"\x1a\x45\xdf\xa3")),
]


def riconosci(file) -> tuple[str, str] | None:
    file.seek(0)
    testa = file.read(32)
    file.seek(0)
    for tipo, mime, verifica in FORMATI:
        if verifica(testa):
            return tipo, mime
    return None


def impronta_e_dimensione(file) -> tuple[str, int]:
    h = hashlib.sha256()
    dimensione = 0
    file.seek(0)
    for blocco in file.chunks():
        h.update(blocco)
        dimensione += len(blocco)
    file.seek(0)
    return h.hexdigest(), dimensione
