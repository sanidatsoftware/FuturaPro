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

# Le stampanti conosciute: la larghezza stampabile (in punti a 203 dpi) per ogni carta, e come
# si collegano. TM-T20IV: 48 colonne da 12 punti su 80 mm (576 punti, 72 mm), 35 su 58 mm
# (420 punti); con la scheda di rete parla ePOS-Print, in USB usa il driver Windows (APD).
MODELLI = {
    "TM-T20IV": {
        "nome": "Epson TM-T20IV", "carte": {80: 576, 58: 420}, "collegamenti": ["epson", "browser"],
        "note": "203 dpi, taglierina. Ethernet: «Epson di rete» (ePOS-Print, IP fisso). USB: «Stampante di sistema» con il driver Epson APD come predefinita.",
    },
    "generica": {
        "nome": "Altra stampante termica (203 dpi)", "carte": {80: 576, 58: 384}, "collegamenti": ["epson", "browser"],
        "note": "Larghezze standard: 72 mm su carta da 80 mm, 48 mm su carta da 58 mm.",
    },
}


def punti_stampante(modello: str, carta: int) -> int:
    voce = MODELLI.get(modello) or MODELLI["generica"]
    return voce["carte"].get(carta) or PUNTI.get(carta, 576)


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


def per_il_player(layout, punti: int | None = None) -> dict | None:
    """Il layout per il totem; «punti»: la larghezza stampabile della stampante che lo usa."""
    if layout is None:
        return None
    return {
        "id": str(layout.id), "nome": layout.nome, "punti": punti or PUNTI.get(layout.carta, 576), "carta": layout.carta,
        "elementi": layout.elementi, "logo": f"data:image/png;base64,{layout.logo}" if layout.logo else "",
    }
