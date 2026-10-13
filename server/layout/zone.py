"""Configurazione di ogni tipo di zona, e i layout pronti da cui partire.

Il motore di rendering (player/static/player/motore.js) legge esattamente
questi campi: chi ne aggiunge uno lo aggiunge anche lì.
"""

from rest_framework import serializers

from contenuti.models import Contenuto, Playlist, Tipo

from .models import TipoZona

COLORE = r"^#[0-9a-fA-F]{6}$"
TRANSIZIONI = ["nessuna", "dissolvenza", "scorri_sinistra", "scorri_alto", "zoom"]
ADATTAMENTI = ["adatta", "riempi"]  # contain / cover
ALLINEAMENTI = ["sinistra", "centro", "destra"]


class Colore(serializers.RegexField):
    def __init__(self, predefinito, **kwargs):
        super().__init__(COLORE, required=False, default=predefinito, **kwargs)


class Slide(serializers.Serializer):
    # "palinsesto": quello che si pubblica sul monitor; altrimenti l'id di una playlist fissa.
    sorgente = serializers.CharField(required=False, default="palinsesto")
    transizione = serializers.ChoiceField(TRANSIZIONI, required=False, default="dissolvenza")
    durata_transizione = serializers.IntegerField(min_value=0, max_value=5000, required=False, default=800)
    adattamento = serializers.ChoiceField(ADATTAMENTI, required=False, default="adatta")

    def validate_sorgente(self, sorgente):
        if sorgente == "palinsesto":
            return sorgente
        if not Playlist.objects.filter(id=_uuid(sorgente)).exists():
            raise serializers.ValidationError("Playlist inesistente.")
        return sorgente


class Orologio(serializers.Serializer):
    secondi = serializers.BooleanField(required=False, default=False)
    mostra_data = serializers.BooleanField(required=False, default=True)
    colore = Colore("#ffffff")
    allineamento = serializers.ChoiceField(ALLINEAMENTI, required=False, default="centro")


class Meteo(serializers.Serializer):
    localita = serializers.CharField(max_length=100)
    latitudine = serializers.FloatField(min_value=-90, max_value=90)
    longitudine = serializers.FloatField(min_value=-180, max_value=180)
    colore = Colore("#ffffff")


class Notizie(serializers.Serializer):
    feed = serializers.ListField(
        child=serializers.URLField(max_length=500), required=False, default=list, max_length=5
    )
    # Messaggi propri, che scorrono insieme alle notizie (o da soli).
    messaggi = serializers.ListField(
        child=serializers.CharField(max_length=300), required=False, default=list, max_length=30
    )
    velocita = serializers.IntegerField(min_value=20, max_value=400, required=False, default=80)
    aggiornamento_minuti = serializers.IntegerField(min_value=5, max_value=240, required=False, default=15)
    colore = Colore("#ffffff")
    sfondo = Colore("#b00020")

    def validate_feed(self, feed):
        for url in feed:
            if not url.startswith(("http://", "https://")):
                raise serializers.ValidationError("Solo indirizzi http o https.")
        return feed

    def validate(self, dati):
        if not dati["feed"] and not dati["messaggi"]:
            raise serializers.ValidationError("Indica almeno un feed di notizie o un messaggio.")
        return dati


class Testo(serializers.Serializer):
    testo = serializers.CharField(max_length=500)
    # Altezza del carattere in percentuale dell'altezza della zona.
    dimensione = serializers.IntegerField(min_value=5, max_value=100, required=False, default=50)
    colore = Colore("#ffffff")
    sfondo = serializers.RegexField(COLORE, required=False, allow_blank=True, default="")
    allineamento = serializers.ChoiceField(ALLINEAMENTI, required=False, default="centro")


class Immagine(serializers.Serializer):
    contenuto = serializers.UUIDField()
    adattamento = serializers.ChoiceField(ADATTAMENTI, required=False, default="adatta")

    def validate_contenuto(self, contenuto):
        if not Contenuto.objects.filter(id=contenuto, tipo=Tipo.IMMAGINE).exists():
            raise serializers.ValidationError("Immagine inesistente.")
        return str(contenuto)


CONFIGURAZIONI = {
    TipoZona.SLIDE: Slide,
    TipoZona.OROLOGIO: Orologio,
    TipoZona.METEO: Meteo,
    TipoZona.NOTIZIE: Notizie,
    TipoZona.TESTO: Testo,
    TipoZona.IMMAGINE: Immagine,
}


def _uuid(valore):
    from uuid import UUID

    try:
        return UUID(str(valore))
    except ValueError:
        raise serializers.ValidationError("Playlist inesistente.")


def valida_configurazione(tipo, configurazione):
    serializer = CONFIGURAZIONI[tipo](data=configurazione or {})
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


# --- Layout pronti ----------------------------------------------------------
# Coordinate in percentuale: (x, y, larghezza, altezza).

MODELLI = {
    "schermo_intero": {
        "nome": "Schermo intero",
        "orientamento": "orizzontale",
        "zone": [("slide", (0, 0, 100, 100), {})],
    },
    "orizzontale_informativo": {
        "nome": "Orizzontale con ora, meteo e notizie",
        "orientamento": "orizzontale",
        "zone": [
            ("slide", (0, 0, 75, 88), {}),
            ("orologio", (75, 0, 25, 22), {}),
            ("meteo", (75, 22, 25, 66), None),
            ("notizie", (0, 88, 100, 12), None),
        ],
    },
    "totem_verticale": {
        "nome": "Totem verticale",
        "orientamento": "verticale",
        "zone": [
            ("orologio", (0, 0, 50, 8), {}),
            ("meteo", (50, 0, 50, 8), None),
            ("slide", (0, 8, 100, 84), {}),
            ("notizie", (0, 92, 100, 8), None),
        ],
    },
}
