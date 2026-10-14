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


def misure_immagine(file) -> tuple[int, int] | None:
    """Larghezza e altezza di un'immagine, lette dall'intestazione (senza decodificarla tutta)."""
    from PIL import Image

    file.seek(0)
    try:
        with Image.open(file) as immagine:
            # Le foto dei telefoni salvano la rotazione a parte (EXIF): conta quella vera.
            orientamento = immagine.getexif().get(0x0112, 1)
            larghezza, altezza = immagine.size
            if orientamento in (5, 6, 7, 8):
                larghezza, altezza = altezza, larghezza
            return larghezza, altezza
    except Exception:
        return None
    finally:
        file.seek(0)


LATO_MINIATURA = 480


def crea_miniatura(file) -> bytes | None:
    """Una JPEG piccola per la libreria del pannello: le originali possono pesare decine di MB."""
    import io

    from PIL import Image, ImageOps

    try:
        with Image.open(file) as immagine:
            immagine.draft("RGB", (LATO_MINIATURA * 2, LATO_MINIATURA * 2))
            immagine = ImageOps.exif_transpose(immagine)
            immagine.thumbnail((LATO_MINIATURA, LATO_MINIATURA))
            if immagine.mode not in ("RGB", "L"):
                sfondo = Image.new("RGB", immagine.size, "white")
                sfondo.paste(immagine, mask=immagine.convert("RGBA").getchannel("A"))
                immagine = sfondo
            uscita = io.BytesIO()
            immagine.convert("RGB").save(uscita, "JPEG", quality=82, optimize=True)
            return uscita.getvalue()
    except Exception:
        return None
