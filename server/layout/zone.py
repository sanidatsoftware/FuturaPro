"""Configurazione di ogni tipo di zona, e i layout pronti da cui partire.

Il motore di rendering (player/static/player/motore.js) legge esattamente
questi campi: chi ne aggiunge uno lo aggiunge anche lì.
"""

from rest_framework import serializers

from contenuti.models import Contenuto, Playlist, Tipo

from .models import TipoZona

COLORE = r"^#[0-9a-fA-F]{6}$"
TRANSIZIONI = ["nessuna", "dissolvenza", "scorri_sinistra", "scorri_alto", "zoom"]
# adatta: intera (contain); riempi: taglia i bordi (cover); sfondo: intera, con la stessa
# immagine sfocata a riempire le bande; allunga: riempie deformando (fill).
ADATTAMENTI = ["adatta", "riempi", "sfondo", "allunga"]
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


class Sfondo(serializers.RegexField):
    """Colore di fondo facoltativo: vuoto = trasparente, si vede lo sfondo del layout."""

    def __init__(self, predefinito="", **kwargs):
        super().__init__(COLORE, required=False, allow_blank=True, default=predefinito, **kwargs)


class Orologio(serializers.Serializer):
    secondi = serializers.BooleanField(required=False, default=False)
    mostra_data = serializers.BooleanField(required=False, default=True)
    colore = Colore("#ffffff")
    sfondo = Sfondo()
    allineamento = serializers.ChoiceField(ALLINEAMENTI, required=False, default="centro")


class Meteo(serializers.Serializer):
    localita = serializers.CharField(max_length=100)
    latitudine = serializers.FloatField(min_value=-90, max_value=90)
    longitudine = serializers.FloatField(min_value=-180, max_value=180)
    colore = Colore("#ffffff")
    sfondo = Sfondo()


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
    sfondo = Sfondo()
    allineamento = serializers.ChoiceField(ALLINEAMENTI, required=False, default="centro")


class Immagine(serializers.Serializer):
    contenuto = serializers.UUIDField()
    adattamento = serializers.ChoiceField(ADATTAMENTI, required=False, default="adatta")

    def validate_contenuto(self, contenuto):
        if not Contenuto.objects.filter(id=contenuto, tipo=Tipo.IMMAGINE).exists():
            raise serializers.ValidationError("Immagine inesistente.")
        return str(contenuto)


class Reparti(serializers.ListField):
    """Reparti scelti; vuoto = tutti i reparti attivi della sede del monitor."""

    def __init__(self, **kwargs):
        super().__init__(child=serializers.UUIDField(), required=False, default=list, max_length=12, **kwargs)

    def to_internal_value(self, dati):
        from eliminacode.models import Reparto

        scelti = [str(r) for r in super().to_internal_value(dati)]
        if scelti and Reparto.objects.filter(id__in=scelti).count() != len(set(scelti)):
            raise serializers.ValidationError("Reparto inesistente.")
        return scelti


class Aspetto(serializers.Serializer):
    """Come appare un reparto in questa zona, se diverso dall'anagrafica del reparto."""

    etichetta = serializers.CharField(max_length=40, required=False)
    colore = serializers.RegexField(COLORE, required=False)
    colore_testo = serializers.RegexField(COLORE, required=False)


class Personalizza(serializers.DictField):
    """{id del reparto: aspetto}: la stessa salumeria può essere un pulsante verde sul
    totem e un riquadro rosa sul display."""

    def __init__(self, **kwargs):
        super().__init__(child=Aspetto(), required=False, default=dict, **kwargs)

    def to_internal_value(self, dati):
        from eliminacode.models import Reparto

        valori = super().to_internal_value(dati)
        if valori and Reparto.objects.filter(id__in=list(valori)).count() != len(valori):
            raise serializers.ValidationError("Reparto inesistente.")
        return {chiave: {k: v for k, v in aspetto.items()} for chiave, aspetto in valori.items()}


ANNUNCI = ["nessuno", "suono", "voce"]
DISPOSIZIONI = ["automatica", "colonna", "riga", "griglia"]


class Coda(serializers.Serializer):
    """I riquadri con il numero servito in ogni reparto (i display sopra i banchi)."""

    reparti = Reparti()
    personalizza = Personalizza()
    disposizione = serializers.ChoiceField(DISPOSIZIONI, required=False, default="automatica")
    # {n} diventa il numero di clienti in coda; vuoto = non mostrarlo.
    testo_coda = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    bordo = serializers.BooleanField(required=False, default=True)
    # Solo un monitor per negozio dovrebbe annunciare, per non sentire l'eco.
    annuncio = serializers.ChoiceField(ANNUNCI, required=False, default="suono")
    # Il volume degli annunci dei numeri: a parte da quello di video e dirette.
    volume_annunci = serializers.IntegerField(min_value=0, max_value=100, required=False, default=100)


class ListinoZona(serializers.Serializer):
    """Un listino prezzi (contenuti.Listino), a pagine se le righe non entrano tutte."""

    listino = serializers.UUIDField()
    titolo = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    colore = Colore("#1d2330")
    sfondo = Sfondo("#ffffff")
    colore_titolo = Colore("#ffffff")
    sfondo_titolo = Colore("#c62828")
    colore_prezzo = Colore("#c62828")
    colore_evidenza = Colore("#fff3c4")
    # 0: quante ne entrano con un testo ben leggibile.
    righe_per_pagina = serializers.IntegerField(min_value=0, max_value=40, required=False, default=0)
    secondi_pagina = serializers.IntegerField(min_value=3, max_value=120, required=False, default=10)
    mostra_unita = serializers.BooleanField(required=False, default=True)
    mostra_nota = serializers.BooleanField(required=False, default=True)

    def validate_listino(self, listino):
        from contenuti.models import Listino

        if not Listino.objects.filter(id=listino).exists():
            raise serializers.ValidationError("Listino inesistente.")
        return str(listino)


STAMPE = ["nessuna", "browser", "epson"]


class PrendiNumero(serializers.Serializer):
    """Il totem touch: il cliente tocca il reparto e riceve il biglietto."""

    reparti = Reparti()
    personalizza = Personalizza()
    titolo = serializers.CharField(max_length=60, required=False, allow_blank=True, default="PRENDI QUI IL TUO NUMERO")
    colore = Colore("#ffffff")
    sfondo = Colore("#ec6a1f")
    # Area dei pulsanti.
    sfondo_pulsanti = Colore("#ffffff")
    colonne = serializers.IntegerField(min_value=0, max_value=4, required=False, default=0)  # 0 = automatico
    arrotondamento = serializers.IntegerField(min_value=0, max_value=60, required=False, default=14)
    testo_coda = serializers.CharField(max_length=60, required=False, allow_blank=True, default="Clienti in coda: {n}")
    # browser: stampa di sistema (Chrome con --kiosk-printing stampa senza finestre);
    # epson: stampante di rete Epson TM con ePOS-Print, all'indirizzo indicato.
    stampa = serializers.ChoiceField(STAMPE, required=False, default="nessuna")
    stampante = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    intestazione = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    messaggio = serializers.CharField(max_length=120, required=False, default="Attendi il tuo turno, grazie!")

    def validate(self, dati):
        if dati["stampa"] == "epson" and not dati["stampante"]:
            raise serializers.ValidationError({"stampante": "Indica l'indirizzo della stampante Epson."})
        return dati


CONFIGURAZIONI = {
    TipoZona.SLIDE: Slide,
    TipoZona.OROLOGIO: Orologio,
    TipoZona.METEO: Meteo,
    TipoZona.NOTIZIE: Notizie,
    TipoZona.TESTO: Testo,
    TipoZona.IMMAGINE: Immagine,
    TipoZona.LISTINO: ListinoZona,
    TipoZona.CODA: Coda,
    TipoZona.PRENDI_NUMERO: PrendiNumero,
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
    # I tre seguenti ricalcano gli schermi dei supermercati: offerte a sinistra,
    # colonna con ora, meteo e reparti a destra, rullo notizie in basso.
    "supermercato_ora_meteo_reparti": {
        "nome": "Supermercato: offerte, ora, meteo e reparti",
        "orientamento": "orizzontale",
        "sfondo": "#ffffff",
        "zone": [
            ("slide", (0, 0, 78, 86), {}),
            ("orologio", (78, 0, 22, 17), {"sfondo": "#1f4e79"}),
            ("meteo", (78, 17, 22, 13), {"sfondo": "#1f4e79"}),
            ("coda", (78, 30, 22, 56), {}),
            ("notizie", (0, 86, 100, 14), {"sfondo": "#ec6a1f"}),
        ],
    },
    "supermercato_reparti": {
        "nome": "Supermercato: offerte e reparti",
        "orientamento": "orizzontale",
        "sfondo": "#ffffff",
        "zone": [
            ("slide", (0, 0, 78, 86), {}),
            ("coda", (78, 0, 22, 86), {}),
            ("notizie", (0, 86, 100, 14), {"sfondo": "#ec6a1f"}),
        ],
    },
    "totem_eliminacode": {
        "nome": "Totem eliminacode",
        "orientamento": "verticale",
        "sfondo": "#ffffff",
        "zone": [
            ("slide", (0, 0, 100, 60), {}),
            ("notizie", (0, 60, 100, 7), {"sfondo": "#ec6a1f"}),
            ("prendi_numero", (0, 67, 100, 33), {}),
        ],
    },
}
