from django.conf import settings
from django.db.models import Sum
from django.http import FileResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Abilitazioni
from core.api import CONTENUTI, TUTTI, RiferimentoCliente, ViewSetCliente, VistaConContesto, sedi_visibili
from core.contesto import contesto_cliente
from dispositivi.api import VistaPlayer, credenziale_dalla_richiesta
from dispositivi.models import GruppoMonitor, Monitor

from . import palinsesto
from .file import impronta_e_dimensione, riconosci
from .models import Contenuto, ElementoPlaylist, Playlist, Pubblicazione, Tipo

MB = 1024 * 1024


def _servi(contenuto):
    if not contenuto.file:
        raise exceptions.NotFound()
    # In produzione il file lo servirà nginx (X-Accel-Redirect), dopo questo controllo.
    return FileResponse(contenuto.file.open("rb"), content_type=contenuto.mime)


# --- Contenuti ----------------------------------------------------------------


class ContenutoSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = Contenuto
        fields = ["id", "nome", "tipo", "file", "url", "mime", "dimensione", "sha256", "durata", "caricato_da", "creato"]
        read_only_fields = ["tipo", "mime", "dimensione", "sha256", "caricato_da", "creato"]
        extra_kwargs = {"nome": {"required": False}, "durata": {"min_value": 1}}

    def validate(self, dati):
        if self.instance is not None:
            if "file" in dati or "url" in dati:
                raise serializers.ValidationError("Il file di un contenuto non si sostituisce: caricane uno nuovo.")
            return dati
        if bool(dati.get("file")) == bool(dati.get("url")):
            raise serializers.ValidationError("Indica un file oppure l'indirizzo di una pagina web.")
        if dati.get("url"):
            if not dati.get("durata"):
                raise serializers.ValidationError({"durata": "Obbligatoria per una pagina web."})
            dati.update(tipo=Tipo.WEB, nome=dati.get("nome") or dati["url"])
            return dati

        file = dati["file"]
        if file.size > settings.FUTURAPRO_MAX_UPLOAD_MB * MB:
            raise serializers.ValidationError({"file": f"Il file supera {settings.FUTURAPRO_MAX_UPLOAD_MB} MB."})
        formato = riconosci(file)
        if formato is None:
            raise serializers.ValidationError({"file": "Formato non supportato: JPEG, PNG, GIF, WebP, MP4, MOV, WebM."})
        abilitazioni = Abilitazioni.objects.get()
        occupato = Contenuto.objects.aggregate(totale=Sum("dimensione"))["totale"] or 0
        if occupato + file.size > abilitazioni.spazio_mb * MB:
            raise serializers.ValidationError({"file": f"Spazio esaurito: il cliente dispone di {abilitazioni.spazio_mb} MB."})
        dati["tipo"], dati["mime"] = formato
        dati["sha256"], dati["dimensione"] = impronta_e_dimensione(file)
        dati["nome"] = dati.get("nome") or file.name
        return dati


class ContenutiViewSet(ViewSetCliente):
    """La libreria del cliente: immagini, video e pagine web. È condivisa da tutti i suoi utenti."""

    ruoli_scrittura = CONTENUTI
    serializer_class = ContenutoSerializer

    def get_queryset(self):
        return Contenuto.objects.all()

    def perform_create(self, serializer):
        contenuto = serializer.save(caricato_da=self.request.user.username)
        registra(self.request.user, "contenuto_caricato", contenuto, nome=contenuto.nome, dimensione=contenuto.dimensione)

    def perform_update(self, serializer):
        registra(self.request.user, "contenuto_modificato", serializer.save())

    def perform_destroy(self, contenuto):
        registra(self.request.user, "contenuto_eliminato", contenuto, nome=contenuto.nome)
        contenuto.delete()

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        return _servi(self.get_object())


# --- Playlist -----------------------------------------------------------------


class ElementoSerializer(serializers.ModelSerializer):
    contenuto = RiferimentoCliente(Contenuto)
    nome = serializers.CharField(source="contenuto.nome", read_only=True)
    tipo = serializers.CharField(source="contenuto.tipo", read_only=True)
    durata = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    class Meta:
        model = ElementoPlaylist
        fields = ["contenuto", "nome", "tipo", "durata"]


def salva_elementi(playlist, elementi):
    """Sostituisce la sequenza: il pannello manda sempre la playlist intera, nell'ordine voluto."""
    ElementoPlaylist.objects.filter(playlist=playlist).delete()
    ElementoPlaylist.objects.bulk_create(
        ElementoPlaylist(
            cliente_id=playlist.cliente_id,
            playlist=playlist,
            contenuto=elemento["contenuto"],
            durata=elemento.get("durata"),
            ordine=posizione,
        )
        for posizione, elemento in enumerate(elementi)
    )


class PlaylistSerializer(serializers.ModelSerializer):
    elementi = ElementoSerializer(many=True, required=False)

    class Meta:
        model = Playlist
        fields = ["id", "nome", "descrizione", "elementi", "creata", "modificata"]
        read_only_fields = ["creata", "modificata"]

    def create(self, dati):
        elementi = dati.pop("elementi", [])
        playlist = super().create(dati)
        salva_elementi(playlist, elementi)
        return playlist

    def update(self, playlist, dati):
        elementi = dati.pop("elementi", None)
        playlist = super().update(playlist, dati)
        if elementi is not None:
            salva_elementi(playlist, elementi)
        return playlist


class PlaylistViewSet(ViewSetCliente):
    ruoli_scrittura = CONTENUTI
    serializer_class = PlaylistSerializer

    def get_queryset(self):
        return Playlist.objects.prefetch_related("elementi__contenuto")

    def perform_create(self, serializer):
        registra(self.request.user, "playlist_creata", serializer.save())

    def perform_update(self, serializer):
        registra(self.request.user, "playlist_modificata", serializer.save())

    def perform_destroy(self, playlist):
        registra(self.request.user, "playlist_eliminata", playlist, nome=playlist.nome)
        playlist.delete()


# --- Pubblicazioni ------------------------------------------------------------


class RegoleSerializer(serializers.Serializer):
    """Destinatari e calendario: comuni alla pubblicazione completa e a «Pubblica»."""

    monitor = RiferimentoCliente(Monitor, many=True, required=False)
    gruppi = RiferimentoCliente(GruppoMonitor, many=True, required=False)
    data_inizio = serializers.DateField(required=False, allow_null=True)
    data_fine = serializers.DateField(required=False, allow_null=True)
    ora_inizio = serializers.TimeField(required=False, allow_null=True)
    ora_fine = serializers.TimeField(required=False, allow_null=True)
    giorni = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), required=False)
    priorita = serializers.IntegerField(required=False, min_value=-100, max_value=100)

    def validate_giorni(self, giorni):
        return sorted(set(giorni))

    def validate(self, dati):
        dati = super().validate(dati)
        corrente = self.instance

        def valore(campo):
            return dati[campo] if campo in dati else getattr(corrente, campo, None)

        if valore("data_inizio") and valore("data_fine") and valore("data_fine") < valore("data_inizio"):
            raise serializers.ValidationError({"data_fine": "Precede la data di inizio."})
        monitor = dati["monitor"] if "monitor" in dati else (list(corrente.monitor.all()) if corrente else [])
        gruppi = dati["gruppi"] if "gruppi" in dati else (list(corrente.gruppi.all()) if corrente else [])
        if not monitor and not gruppi:
            raise serializers.ValidationError("Scegli almeno un monitor o un gruppo.")
        verifica_destinatari(self.context["request"].user, monitor, gruppi)
        return dati


def verifica_destinatari(utente, monitor, gruppi):
    """Un utente limitato a certe sedi pubblica solo sui monitor di quelle sedi, e non sui gruppi."""
    limitate = sedi_visibili(utente)
    if limitate is None:
        return
    if gruppi:
        raise exceptions.PermissionDenied("Puoi pubblicare solo sui singoli monitor delle tue sedi.")
    if any(m.sede_id not in limitate for m in monitor):
        raise exceptions.ValidationError({"monitor": "Monitor inesistente."})


class PubblicazioneSerializer(RegoleSerializer, serializers.ModelSerializer):
    playlist = RiferimentoCliente(Playlist)

    class Meta:
        model = Pubblicazione
        fields = [
            "id", "nome", "playlist", "monitor", "gruppi", "data_inizio", "data_fine",
            "ora_inizio", "ora_fine", "giorni", "priorita", "attiva", "creata",
        ]
        read_only_fields = ["creata"]


class PubblicazioniViewSet(ViewSetCliente):
    ruoli_scrittura = CONTENUTI
    serializer_class = PubblicazioneSerializer

    def get_queryset(self):
        pubblicazioni = Pubblicazione.objects.prefetch_related("monitor", "gruppi")
        limitate = sedi_visibili(self.request.user)
        if limitate is None:
            return pubblicazioni
        return pubblicazioni.filter(monitor__sede_id__in=limitate).distinct()

    def _modificabile(self, pubblicazione):
        verifica_destinatari(self.request.user, list(pubblicazione.monitor.all()), list(pubblicazione.gruppi.all()))

    def perform_create(self, serializer):
        registra(self.request.user, "pubblicazione_creata", serializer.save())

    def perform_update(self, serializer):
        self._modificabile(serializer.instance)
        registra(self.request.user, "pubblicazione_modificata", serializer.save())

    def perform_destroy(self, pubblicazione):
        self._modificabile(pubblicazione)
        registra(self.request.user, "pubblicazione_eliminata", pubblicazione, nome=pubblicazione.nome)
        pubblicazione.delete()


class PubblicaSerializer(RegoleSerializer):
    contenuti = RiferimentoCliente(Contenuto, many=True, required=False)
    playlist = RiferimentoCliente(Playlist, required=False)
    nome = serializers.CharField(max_length=200, required=False)
    durata = serializers.IntegerField(min_value=1, required=False, help_text="Secondi per ciascun contenuto.")

    def validate(self, dati):
        dati = super().validate(dati)
        if bool(dati.get("contenuti")) == bool(dati.get("playlist")):
            raise serializers.ValidationError("Indica dei contenuti oppure una playlist.")
        return dati


class PubblicaView(VistaConContesto, APIView):
    """Il percorso semplice: questi contenuti, su questi monitor, da adesso.

    Con i contenuti crea una playlist nuova; con una playlist esistente la
    pubblica e basta. Calendario e priorità sono facoltativi.
    """

    ruoli_lettura = CONTENUTI
    ruoli_scrittura = CONTENUTI

    def post(self, request):
        dati = PubblicaSerializer(data=request.data, context={"request": request})
        dati.is_valid(raise_exception=True)
        regole = dict(dati.validated_data)
        monitor = regole.pop("monitor", [])
        gruppi = regole.pop("gruppi", [])
        contenuti = regole.pop("contenuti", None)
        durata = regole.pop("durata", None)
        nome = regole.pop("nome", None) or f"Pubblicazione del {timezone.localtime():%d/%m/%Y %H:%M}"

        playlist = regole.pop("playlist", None)
        if playlist is None:
            playlist = Playlist.objects.create(nome=nome)
            salva_elementi(playlist, [{"contenuto": c, "durata": durata} for c in contenuti])

        pubblicazione = Pubblicazione.objects.create(nome=nome, playlist=playlist, **regole)
        pubblicazione.monitor.set(monitor)
        pubblicazione.gruppi.set(gruppi)
        registra(request.user, "pubblicato", pubblicazione, monitor=len(monitor), gruppi=len(gruppi))
        return Response(PubblicazioneSerializer(pubblicazione).data, status=status.HTTP_201_CREATED)


class AnteprimaView(VistaConContesto, APIView):
    """Cosa va in onda su un monitor adesso, o nell'istante indicato in ``?quando=``."""

    ruoli_lettura = TUTTI

    def get(self, request, monitor_id):
        monitor = Monitor.objects.filter(id=monitor_id)
        limitate = sedi_visibili(request.user)
        if limitate is not None:
            monitor = monitor.filter(sede_id__in=limitate)
        monitor = monitor.first()
        if monitor is None:
            raise exceptions.NotFound()

        quando = request.query_params.get("quando")
        istante = parse_datetime(quando) if quando else timezone.now()
        if istante is None:
            raise exceptions.ValidationError({"quando": "Data e ora non valide."})
        if timezone.is_naive(istante):
            istante = timezone.make_aware(istante)
        istante = timezone.localtime(istante)

        in_onda = palinsesto.in_onda(palinsesto.pubblicazioni_del_monitor(monitor), istante)
        sequenza = []
        for pubblicazione in in_onda:
            for elemento in pubblicazione.playlist.elementi.select_related("contenuto"):
                sequenza.append(
                    {
                        "pubblicazione": pubblicazione.nome,
                        "contenuto": elemento.contenuto_id,
                        "nome": elemento.contenuto.nome,
                        "tipo": elemento.contenuto.tipo,
                        "durata": palinsesto.durata_effettiva(elemento),
                    }
                )
        return Response({"monitor": monitor.id, "quando": istante, "sequenza": sequenza})


# --- Player -------------------------------------------------------------------


class PalinsestoPlayerView(VistaPlayer):
    """Il manifest completo per il player. Con If-None-Match uguale alla versione risponde 304."""

    def get(self, request):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            corpo = palinsesto.manifest(Monitor.objects.get(id=credenziale.monitor_id))
        etichetta = f'"{corpo["versione"]}"'
        if request.headers.get("If-None-Match") == etichetta:
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etichetta})
        return Response(corpo, headers={"ETag": etichetta})


class FilePlayerView(VistaPlayer):
    """Un file del palinsesto. Il player scarica solo ciò che è pubblicato su di lui."""

    def get(self, request, contenuto_id):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            # Lo stesso calcolo del manifest: palinsesto, playlist fisse e immagini del layout.
            ammessi = palinsesto.manifest(Monitor.objects.get(id=credenziale.monitor_id))["contenuti"]
            if str(contenuto_id) not in ammessi:
                raise exceptions.NotFound()
            return _servi(Contenuto.objects.get(id=contenuto_id))
