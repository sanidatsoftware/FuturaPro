from .models import Layout, TipoZona
from .zone import valida_configurazione


def layout_del_monitor(monitor):
    """Il layout assegnato, altrimenti il predefinito del suo orientamento, altrimenti nessuno."""
    if monitor.layout_id:
        return monitor.layout
    return Layout.objects.filter(orientamento=monitor.orientamento, predefinito=True).first()


def descrivi(layout, orientamento: str) -> dict:
    """Il layout come lo legge il motore. Senza layout: le slide a tutto schermo."""
    if layout is None:
        return {
            "id": None,
            "nome": "Schermo intero",
            "orientamento": orientamento,
            "sfondo": "#000000",
            "immagine_sfondo": None,
            "carattere": "sans-serif",
            "zone": [
                {"id": None, "tipo": TipoZona.SLIDE.value, "x": 0, "y": 0, "larghezza": 100, "altezza": 100,
                 "livello": 0, "configurazione": valida_configurazione(TipoZona.SLIDE, {})}
            ],
        }
    return {
        "id": str(layout.id),
        "nome": layout.nome,
        "orientamento": layout.orientamento,
        "sfondo": layout.sfondo,
        "immagine_sfondo": layout.immagine_sfondo_id and str(layout.immagine_sfondo_id),
        "carattere": layout.carattere,
        "zone": [
            {
                "id": str(z.id), "tipo": z.tipo, "x": z.x, "y": z.y, "larghezza": z.larghezza,
                "altezza": z.altezza, "livello": z.livello, "configurazione": z.configurazione,
            }
            for z in layout.zone.order_by("livello", "id")
        ],
    }


def riferimenti(descrizione: dict) -> tuple[set[str], set[str]]:
    """Le playlist fisse e le immagini che il layout usa: anche queste vanno al player."""
    playlist, contenuti = set(), set()
    if descrizione["immagine_sfondo"]:
        contenuti.add(descrizione["immagine_sfondo"])
    for zona in descrizione["zone"]:
        configurazione = zona["configurazione"]
        if zona["tipo"] == TipoZona.SLIDE and configurazione["sorgente"] != "palinsesto":
            playlist.add(configurazione["sorgente"])
        elif zona["tipo"] == TipoZona.IMMAGINE:
            contenuti.add(configurazione["contenuto"])
    return playlist, contenuti
