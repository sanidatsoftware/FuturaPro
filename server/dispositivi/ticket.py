"""Il layout del biglietto stampato (``LayoutTicket``): elementi, controlli, logo.

Gli elementi sono in colonna, dall'alto in basso, come esce la carta. I testi fissi
(intestazione, fine biglietto, testi liberi) stanno nel layout; reparto, numero, persone in
coda, data e QR li mette il totem al momento della stampa. Le grandezze sono in punti della
stampante (203 dpi: 8 punti per millimetro).
"""

import base64
import io

from rest_framework import serializers

CAMPI = {
    "logo": "Logo",
    "intestazione": "Intestazione",
    "reparto": "Reparto (il tasto toccato)",
    "numero": "Numero",
    "davanti": "Persone in coda",
    "messaggio": "Testo di fine biglietto",
    "data": "Data e ora",
    "qr": "QR della coda sul telefono",
    "testo": "Testo libero",
    "linea": "Linea di separazione",
}
UNICI = {"logo", "intestazione", "reparto", "numero", "davanti", "messaggio", "data", "qr"}
CON_TESTO = {"intestazione", "messaggio", "testo"}
CARATTERI = ["sans-serif", "serif", "monospace", "Arial", "Arial Black", "Verdana", "Tahoma", "Trebuchet MS",
             "Georgia", "Times New Roman", "Courier New", "Impact", "Segoe UI", "Roboto"]
ALLINEAMENTI = ["sinistra", "centro", "destra"]
PUNTI = {80: 576, 58: 384}


def elemento(campo, **valori):
    base = {"campo": campo, "visibile": True, "carattere": "sans-serif", "dimensione": 28, "grassetto": False,
            "corsivo": False, "maiuscolo": False, "inverso": False, "allineamento": "centro", "spazio": 8,
            "larghezza": 60, "testo": ""}
    base.update(valori)
    return base


def predefiniti() -> list:
    return [
        elemento("logo", larghezza=60, spazio=12),
        elemento("intestazione", testo="", dimensione=30, grassetto=True),
        elemento("reparto", dimensione=44, grassetto=True, maiuscolo=True, inverso=True, spazio=4),
        elemento("numero", dimensione=180, grassetto=True, spazio=4),
        elemento("davanti", dimensione=26),
        elemento("messaggio", testo="Attendi il tuo turno, grazie!", dimensione=26, spazio=10),
        elemento("data", dimensione=22),
        elemento("qr", larghezza=45),
    ]


def valida_elementi(valore) -> list:
    if not isinstance(valore, list) or not 1 <= len(valore) <= 30:
        raise serializers.ValidationError("Da 1 a 30 elementi.")
    puliti, visti = [], set()
    for grezzo in valore:
        if not isinstance(grezzo, dict) or grezzo.get("campo") not in CAMPI:
            raise serializers.ValidationError("Elemento non valido.")
        campo = grezzo["campo"]
        if campo in UNICI and campo in visti:
            raise serializers.ValidationError(f"«{CAMPI[campo]}» compare due volte.")
        visti.add(campo)

        def numero(chiave, minimo, massimo, predefinito):
            try:
                return max(minimo, min(massimo, int(grezzo.get(chiave, predefinito))))
            except (TypeError, ValueError):
                return predefinito

        puliti.append({
            "campo": campo,
            "visibile": bool(grezzo.get("visibile", True)),
            "carattere": grezzo.get("carattere") if grezzo.get("carattere") in CARATTERI else "sans-serif",
            "dimensione": numero("dimensione", 10, 400, 28),
            "grassetto": bool(grezzo.get("grassetto")),
            "corsivo": bool(grezzo.get("corsivo")),
            "maiuscolo": bool(grezzo.get("maiuscolo")),
            "inverso": bool(grezzo.get("inverso")),
            "allineamento": grezzo.get("allineamento") if grezzo.get("allineamento") in ALLINEAMENTI else "centro",
            "spazio": numero("spazio", 0, 200, 8),
            "larghezza": numero("larghezza", 10, 100, 60),
            "testo": str(grezzo.get("testo") or "")[:300] if campo in CON_TESTO else "",
        })
    return puliti


def prepara_logo(file, carta: int) -> str:
    """Il logo caricato come PNG in scala di grigi, largo al massimo quanto la carta (base64)."""
    from PIL import Image, ImageOps

    if file.size > 5 * 1024 * 1024:
        raise serializers.ValidationError("Il logo è troppo grande (massimo 5 MB).")
    try:
        immagine = Image.open(file)
        immagine.load()
    except Exception:
        raise serializers.ValidationError("Il file non è un'immagine (PNG, JPG…).")
    immagine = ImageOps.exif_transpose(immagine)
    if immagine.mode in ("RGBA", "LA", "P"):
        # Le parti trasparenti diventano bianche, come la carta.
        immagine = immagine.convert("RGBA")
        fondo = Image.new("RGBA", immagine.size, (255, 255, 255, 255))
        immagine = Image.alpha_composite(fondo, immagine)
    immagine = immagine.convert("L")
    larghezza = PUNTI.get(carta, 576)
    if immagine.width > larghezza:
        immagine = immagine.resize((larghezza, max(1, round(immagine.height * larghezza / immagine.width))), Image.LANCZOS)
    if immagine.height > 1200:
        immagine = immagine.resize((max(1, round(immagine.width * 1200 / immagine.height)), 1200), Image.LANCZOS)
    uscita = io.BytesIO()
    immagine.save(uscita, "PNG", optimize=True)
    return base64.b64encode(uscita.getvalue()).decode()


def per_il_player(layout) -> dict | None:
    if layout is None:
        return None
    return {
        "id": str(layout.id), "nome": layout.nome, "punti": PUNTI.get(layout.carta, 576), "carta": layout.carta,
        "elementi": layout.elementi, "logo": f"data:image/png;base64,{layout.logo}" if layout.logo else "",
    }
