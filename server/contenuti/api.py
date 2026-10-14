from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Sum
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.db import transaction
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
from clienti.models import Insegna
from dispositivi.models import GruppoMonitor, Monitor

from . import palinsesto
from .file import crea_miniatura, impronta_e_dimensione, misure_immagine, riconosci
from . import campagne, dirette
from .models import Campagna, Contenuto, ElementoPlaylist, Playlist, Promozione, Pubblicazione, Tipo, Uso

MB = 1024 * 1024


def _servi(contenuto):
    if not contenuto.file:
        raise exceptions.NotFound()
    # In produzione il file lo servirà nginx (X-Accel-Redirect), dopo questo controllo.
    return FileResponse(contenuto.file.open("rb"), content_type=contenuto.mime)


# --- Contenuti ----------------------------------------------------------------


class ContenutoSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=False)
    orientamento = serializers.CharField(read_only=True)

    class Meta:
        model = Contenuto
        fields = [
            "id", "nome", "tipo", "file", "url", "mime", "dimensione", "sha256", "durata",
            "larghezza", "altezza", "orientamento", "logo_url", "autorizzata_da", "autorizzata_il", "caricato_da", "uso", "creato",
        ]
        read_only_fields = ["tipo", "mime", "dimensione", "sha256", "logo_url", "autorizzata_da", "autorizzata_il", "caricato_da", "creato"]
        extra_kwargs = {
            "nome": {"required": False},
            "durata": {"min_value": 1},
            # Per i video le manda il pannello (le legge il browser); per le immagini vince il server.
            "larghezza": {"min_value": 1, "max_value": 30000},
            "altezza": {"min_value": 1, "max_value": 30000},
        }

    def validate(self, dati):
        if self.instance is not None:
            if "file" in dati or "url" in dati:
                raise serializers.ValidationError("Il file di un contenuto non si sostituisce: caricane uno nuovo.")
            if "uso" in dati and dati["uso"] != self.instance.uso:
                raise serializers.ValidationError({"uso": "Non si cambia dopo il caricamento."})
            return dati
        if dati.get("uso") == Uso.RISERVA and not dati.get("file"):
            raise serializers.ValidationError({"file": "La riserva di uno schermo è un'immagine o un video da caricare."})
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
        if dati.get("uso") == Uso.RISERVA and dati["tipo"] not in (Tipo.IMMAGINE, Tipo.VIDEO):
            raise serializers.ValidationError({"file": "La riserva di uno schermo è un'immagine o un video."})
        dati["sha256"], dati["dimensione"] = impronta_e_dimensione(file)
        if dati["tipo"] == Tipo.IMMAGINE:
            misure = misure_immagine(file)
            if misure:
                dati["larghezza"], dati["altezza"] = misure
        dati["nome"] = dati.get("nome") or file.name
        return dati


class ContenutiViewSet(ViewSetCliente):
    """La libreria del cliente: immagini, video e pagine web. È condivisa da tutti i suoi utenti."""

    ruoli_scrittura = CONTENUTI
    serializer_class = ContenutoSerializer

    def get_queryset(self):
        contenuti = Contenuto.objects.all()
        # ?uso=libreria: solo le immagini delle promozioni; ?uso=riserva: solo i loghi degli schermi.
        uso = self.request.query_params.get("uso")
        return contenuti.filter(uso=uso) if uso in Uso.values else contenuti

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

    @action(detail=False, methods=["post"])
    def m3u(self, request):
        """Legge una lista M3U (da un indirizzo o da un file) e ne restituisce i canali, senza salvarli."""
        file = request.FILES.get("file")
        try:
            if file is not None:
                if file.size > dirette.MASSIMO_LISTA:
                    raise exceptions.ValidationError({"file": "Lista troppo grande."})
                grezzo = file.read()
                testo = grezzo.decode("utf-8-sig", errors="replace")
            else:
                indirizzo = (request.data.get("url") or "").strip()
                if not indirizzo:
                    raise exceptions.ValidationError({"url": "Indica l'indirizzo della lista o scegli un file."})
                testo = dirette.scarica_lista(indirizzo)
                # L'indirizzo è già un canale (.m3u8 HLS), non un elenco: lo si propone così.
                if dirette.e_flusso_hls(testo):
                    nome = indirizzo.rstrip("/").rsplit("/", 2)[-2 if indirizzo.endswith("index.m3u8") else -1][:200]
                    gia = Contenuto.objects.filter(tipo=Tipo.DIRETTA, url=indirizzo).exists()
                    return Response({"canali": [{"nome": nome, "url": indirizzo, "logo": "", "gruppo": "", "presente": gia}]})
        except exceptions.ValidationError:
            raise
        except Exception:
            raise exceptions.ValidationError({"url": "Non riesco a scaricare la lista: controlla l'indirizzo."})
        canali = dirette.leggi_m3u(testo)
        if not canali:
            raise exceptions.ValidationError({"url": "Nessun canale trovato: non sembra una lista M3U."})
        gia = set(Contenuto.objects.filter(tipo=Tipo.DIRETTA).values_list("url", flat=True))
        return Response({"canali": [{**c, "presente": c["url"] in gia} for c in canali]})

    @action(detail=False, methods=["post"])
    def dirette(self, request):
        """Aggiunge canali in diretta alla libreria. Va confermato che la riproduzione è autorizzata."""
        if request.data.get("autorizzazione") is not True:
            raise exceptions.ValidationError({
                "autorizzazione": "Conferma che la riproduzione in pubblico di questi canali è autorizzata "
                                  "(canone RAI speciale, licenze SIAE/SCF, abbonamenti o permessi dell'editore).",
            })
        canali = request.data.get("canali")
        if not isinstance(canali, list) or not canali or len(canali) > 500:
            raise exceptions.ValidationError({"canali": "Scegli da 1 a 500 canali."})
        validi = []
        for canale in canali:
            url = str((canale or {}).get("url", "")).strip()
            if not url.lower().startswith(("http://", "https://")) or len(url) > 1000:
                raise exceptions.ValidationError({"canali": f"Indirizzo non valido: {url[:80]}"})
            logo = str(canale.get("logo") or "")
            validi.append({
                "url": url,
                "nome": str(canale.get("nome") or "").strip()[:200],
                "logo": logo if logo.lower().startswith(("http://", "https://")) else "",
            })
        creati = dirette.crea_dirette(validi, request.user)
        registra(request.user, "dirette_aggiunte", None, canali=len(creati), autorizzazione_confermata=True)
        return Response(ContenutoSerializer(creati, many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get", "post"])
    def pulizia(self, request):
        """I contenuti usati solo da promozioni scadute: GET li elenca, POST li cancella (anche i file)."""
        if sedi_visibili(request.user) is not None:
            raise exceptions.PermissionDenied("La pulizia è riservata a chi gestisce tutto il cliente.")
        scaduti = list(campagne.contenuti_scaduti(timezone.localdate()))
        riepilogo = {"contenuti": len(scaduti), "spazio": sum(c.dimensione for c in scaduti), "id": [c.id for c in scaduti]}
        if request.method == "GET":
            return Response(riepilogo)
        for contenuto in scaduti:
            contenuto.delete()
        registra(request.user, "pulizia_contenuti", None, contenuti=riepilogo["contenuti"], spazio=riepilogo["spazio"])
        return Response(riepilogo)

    @action(detail=True, methods=["get"])
    def miniatura(self, request, pk=None):
        """Una JPEG piccola dell'immagine, creata la prima volta che serve e poi conservata."""
        contenuto = self.get_object()
        if contenuto.tipo != Tipo.IMMAGINE or not contenuto.file:
            raise exceptions.NotFound()
        percorso = contenuto.percorso_miniatura
        if default_storage.exists(percorso):
            with default_storage.open(percorso, "rb") as f:
                dati = f.read()
        else:
            with contenuto.file.open("rb") as originale:
                dati = crea_miniatura(originale)
            if dati is None:
                raise exceptions.NotFound()
            default_storage.save(percorso, ContentFile(dati))
        risposta = HttpResponse(dati, content_type="image/jpeg")
        # Il contenuto non cambia mai (si carica un file nuovo): il browser la tiene a lungo.
        risposta["Cache-Control"] = "private, max-age=604800, immutable"
        return risposta


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
            audio=bool(elemento.get("audio")),
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
            "id", "nome", "playlist", "monitor", "gruppi", "insegne", "orientamento", "promozione",
            "data_inizio", "data_fine", "ora_inizio", "ora_fine", "giorni", "priorita", "attiva", "creata",
        ]
        # Insegne e orientamento si scelgono dalla promozione, che ne è la proprietaria.
        read_only_fields = ["creata", "insegne", "orientamento", "promozione"]


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


# --- Campagne e promozioni -------------------------------------------------------


def verifica_campagna_modificabile(utente, campagna):
    """Un utente limitato a certe sedi lavora solo su campagne dei monitor delle sue sedi."""
    limitate = sedi_visibili(utente)
    if limitate is None:
        return
    if campagna.insegne.exists() or campagna.gruppi.exists() or campagna.monitor.exclude(sede_id__in=limitate).exists():
        raise exceptions.PermissionDenied("La campagna riguarda anche monitor fuori dalle tue sedi.")


class PromozioneSerializer(serializers.ModelSerializer):
    campagna = RiferimentoCliente(Campagna)
    contenuti = RiferimentoCliente(Contenuto, many=True, required=False)
    # Durata propria di alcune voci, in secondi (es. {"<id diretta>": 300}).
    durate = serializers.DictField(child=serializers.IntegerField(min_value=1, max_value=86400), required=False)
    # Le dirette da mandare con l'audio acceso (id dei contenuti).
    audio = serializers.ListField(child=serializers.UUIDField(), required=False)
    giorni = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), required=False)
    data_inizio = serializers.DateField()
    data_fine = serializers.DateField()
    stato = serializers.SerializerMethodField()
    pubblicazioni = serializers.SerializerMethodField()

    class Meta:
        model = Promozione
        fields = [
            "id", "campagna", "nome", "data_inizio", "data_fine", "ora_inizio", "ora_fine", "giorni",
            "contenuti", "durate", "audio", "stato", "pubblicazioni", "creata", "modificata",
        ]
        read_only_fields = ["creata", "modificata"]

    def get_stato(self, promozione):
        return campagne.stato(promozione, timezone.localdate())

    def get_pubblicazioni(self, promozione):
        return [
            {"orientamento": p.orientamento, "contenuti": p.playlist.elementi.count()}
            for p in promozione.pubblicazioni.select_related("playlist")
        ]

    def to_representation(self, promozione):
        dati = super().to_representation(promozione)
        # Nell'ordine della promozione, non in quello del database.
        voci = list(promozione.voci.order_by("ordine"))
        dati["contenuti"] = [str(v.contenuto_id) for v in voci]
        dati["durate"] = {str(v.contenuto_id): v.durata for v in voci if v.durata}
        dati["audio"] = [str(v.contenuto_id) for v in voci if v.audio]
        return dati

    def validate_giorni(self, giorni):
        return sorted(set(giorni))

    def validate(self, dati):
        corrente = self.instance

        def valore(campo):
            return dati[campo] if campo in dati else getattr(corrente, campo, None)

        if valore("data_fine") < valore("data_inizio"):
            raise serializers.ValidationError({"data_fine": "Precede la data di inizio."})
        campagna = valore("campagna")
        # Le date della promozione stanno dentro la validità della sua campagna.
        if campagna.data_inizio and valore("data_inizio") < campagna.data_inizio:
            raise serializers.ValidationError(
                {"data_inizio": f"La campagna «{campagna.nome}» è valida dal {campagna.data_inizio:%d/%m/%Y}."}
            )
        if campagna.data_fine and valore("data_fine") > campagna.data_fine:
            raise serializers.ValidationError(
                {"data_fine": f"La campagna «{campagna.nome}» è valida fino al {campagna.data_fine:%d/%m/%Y}."}
            )
        nome = valore("nome")
        doppione = Promozione.objects.filter(campagna=campagna, nome__iexact=nome)
        if corrente is not None:
            doppione = doppione.exclude(id=corrente.id)
        if doppione.exists():
            raise serializers.ValidationError({"nome": "La campagna ha già una promozione con questo nome."})
        verifica_campagna_modificabile(self.context["request"].user, campagna)
        return dati

    def _salva(self, promozione, contenuti, durate, audio):
        if contenuti is not None or durate is not None or audio is not None:
            voci = list(promozione.voci.select_related("contenuto").order_by("ordine"))
            if contenuti is None:
                contenuti = [v.contenuto for v in voci]
            if durate is None:
                durate = {str(v.contenuto_id): v.durata for v in voci if v.durata}
            if audio is None:
                audio = [v.contenuto_id for v in voci if v.audio]
            campagne.salva_contenuti(promozione, contenuti, durate, audio)
        campagne.sincronizza(promozione)
        return promozione

    def create(self, dati):
        contenuti, durate, audio = dati.pop("contenuti", None), dati.pop("durate", None), dati.pop("audio", None)
        return self._salva(super().create(dati), contenuti, durate, audio)

    def update(self, promozione, dati):
        contenuti, durate, audio = dati.pop("contenuti", None), dati.pop("durate", None), dati.pop("audio", None)
        vecchia_campagna = promozione.campagna
        promozione = self._salva(super().update(promozione, dati), contenuti, durate, audio)
        if vecchia_campagna.id != promozione.campagna_id:
            verifica_campagna_modificabile(self.context["request"].user, vecchia_campagna)
        return promozione


class CampagnaSerializer(serializers.ModelSerializer):
    insegne = RiferimentoCliente(Insegna, many=True, required=False)
    gruppi = RiferimentoCliente(GruppoMonitor, many=True, required=False)
    monitor = RiferimentoCliente(Monitor, many=True, required=False)
    colore = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)
    promozioni = serializers.SerializerMethodField()
    stato = serializers.SerializerMethodField()
    data_inizio = serializers.DateField(required=False, allow_null=True)
    data_fine = serializers.DateField(required=False, allow_null=True)

    class Meta:
        model = Campagna
        fields = [
            "id", "nome", "data_inizio", "data_fine", "codice", "colore", "note", "priorita", "durata",
            "insegne", "gruppi", "monitor", "stato", "promozioni", "creata", "modificata",
        ]
        read_only_fields = ["creata", "modificata"]
        extra_kwargs = {"durata": {"min_value": 1, "max_value": 3600}, "priorita": {"min_value": -100, "max_value": 100}}

    def _promozioni(self, campagna):
        if not hasattr(campagna, "_promo_serializzate"):
            campagna._promo_serializzate = PromozioneSerializer(
                campagna.promozioni.order_by("data_inizio", "nome"), many=True, context=self.context
            ).data
        return campagna._promo_serializzate

    def get_promozioni(self, campagna):
        return self._promozioni(campagna)

    def get_stato(self, campagna):
        return campagne.stato_campagna([p["stato"] for p in self._promozioni(campagna)])

    def validate(self, dati):
        corrente = self.instance

        def valore(campo):
            return dati[campo] if campo in dati else getattr(corrente, campo, None)

        nome = valore("nome")
        doppione = Campagna.objects.filter(nome__iexact=nome)
        if corrente is not None:
            doppione = doppione.exclude(id=corrente.id)
        if nome and doppione.exists():
            raise serializers.ValidationError({"nome": f"Esiste già una campagna «{nome}»."})
        inizio, fine = valore("data_inizio"), valore("data_fine")
        if corrente is None and (not inizio or not fine):
            raise serializers.ValidationError("Indica la validità della campagna: dal … al ….")
        if inizio and fine and fine < inizio:
            raise serializers.ValidationError({"data_fine": "Precede la data di inizio."})
        if corrente is not None:
            # Non si stringe la validità lasciando fuori promozioni che già ci sono.
            fuori = corrente.promozioni.all()
            fuori = [
                p for p in fuori
                if (inizio and p.data_inizio and p.data_inizio < inizio) or (fine and p.data_fine and p.data_fine > fine)
            ]
            if fuori:
                nomi = ", ".join(f"«{p.nome}»" for p in fuori[:3])
                raise serializers.ValidationError(
                    {"data_inizio": f"Con queste date restano fuori delle promozioni: {nomi}. Cambia prima le loro date."}
                )
        utente = self.context["request"].user
        limitate = sedi_visibili(utente)
        if limitate is not None:
            if dati.get("insegne") or dati.get("gruppi"):
                raise exceptions.PermissionDenied("Puoi pubblicare solo sui singoli monitor delle tue sedi.")
            verifica_destinatari(utente, dati.get("monitor", []), [])
        return dati

    def update(self, campagna, dati):
        campagna = super().update(campagna, dati)
        # Destinatari, priorità o durata cambiati: le pubblicazioni di tutte le promozioni si allineano.
        campagne.sincronizza_campagna(campagna)
        return campagna


class CampagneViewSet(ViewSetCliente):
    """Le campagne: ognuna raggruppa più promozioni con gli stessi destinatari."""

    ruoli_scrittura = CONTENUTI
    serializer_class = CampagnaSerializer

    def get_queryset(self):
        campagne_ = Campagna.objects.prefetch_related("insegne", "gruppi", "monitor")
        limitate = sedi_visibili(self.request.user)
        if limitate is None:
            return campagne_
        return campagne_.filter(monitor__sede_id__in=limitate).distinct()

    def perform_create(self, serializer):
        registra(self.request.user, "campagna_creata", serializer.save())

    def perform_update(self, serializer):
        verifica_campagna_modificabile(self.request.user, serializer.instance)
        registra(self.request.user, "campagna_modificata", serializer.save())

    def perform_destroy(self, campagna):
        verifica_campagna_modificabile(self.request.user, campagna)
        registra(self.request.user, "campagna_eliminata", campagna, nome=campagna.nome)
        for promozione in campagna.promozioni.all():
            campagne.elimina_promozione(promozione)
        campagna.delete()

    @action(detail=False, methods=["get"])
    def modello(self, request):
        """Il tracciato del CSV, con righe d'esempio da sostituire."""
        risposta = HttpResponse("\ufeff" + campagne.MODELLO, content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = 'attachment; filename="promozioni-futurapro.csv"'
        return risposta

    @action(detail=False, methods=["post"])
    def importa(self, request):
        """Carica campagne e promozioni da un CSV (una riga per promozione).

        Con ``prova=1`` controlla soltanto e mostra l'esito riga per riga. Tutto o
        niente: se una riga ha un errore non si salva nulla.
        """
        if sedi_visibili(request.user) is not None:
            raise exceptions.PermissionDenied("L'importazione è riservata a chi gestisce tutto il cliente.")
        file = request.FILES.get("file")
        if file is None:
            raise exceptions.ValidationError({"file": "Scegli il file CSV."})
        if file.size > 2 * MB:
            raise exceptions.ValidationError({"file": "File troppo grande (massimo 2 MB)."})
        grezzo = file.read()
        try:
            testo = grezzo.decode("utf-8")
        except UnicodeDecodeError:
            testo = grezzo.decode("cp1252")  # Excel italiano
        try:
            righe = campagne.leggi_csv(testo, Insegna.objects.all(), GruppoMonitor.objects.all(), Monitor.objects.all())
        except campagne.ErroreRiga as errore:
            raise exceptions.ValidationError({"file": str(errore)})
        except Exception:
            raise exceptions.ValidationError({"file": "Il file non è un CSV leggibile."})
        promozioni_esistenti = {
            (c.casefold(), p.casefold())
            for c, p in Promozione.objects.values_list("campagna__nome", "nome")
        }
        campagne_esistenti = {c.casefold() for c in Campagna.objects.values_list("nome", flat=True)}
        esito = []
        for r in righe:
            voce = {"riga": r["riga"], "campagna": r["campagna"], "promozione": r["promozione"], "errori": r["errori"]}
            if r["errori"]:
                voce["azione"] = "errore"
            else:
                chiave = (r["campagna"].casefold(), r["promozione"].casefold())
                voce["azione"] = "aggiorna" if chiave in promozioni_esistenti else "crea"
                voce["campagna_nuova"] = r["campagna"].casefold() not in campagne_esistenti
                voce.update(
                    data_inizio=r["promo"]["data_inizio"], data_fine=r["promo"]["data_fine"],
                    campagna_dal=r["validita"][0] if r["validita"] else None,
                    campagna_al=r["validita"][1] if r["validita"] else None,
                    insegne=[i.nome for i in r["insegne"]], gruppi=[g.nome for g in r["gruppi"]],
                    monitor=[m.nome for m in r["monitor"]],
                )
            esito.append(voce)
        valido = bool(righe) and not any(r["errori"] for r in righe)
        prova = request.data.get("prova") in ("1", "true", True)
        if prova or not valido:
            codice = status.HTTP_200_OK if valido or prova else status.HTTP_400_BAD_REQUEST
            return Response({"righe": esito, "valido": valido, "salvate": 0}, status=codice)
        with transaction.atomic():
            numero_campagne, numero_promozioni = campagne.importa(righe)
        registra(request.user, "promozioni_importate", None, campagne=numero_campagne, promozioni=numero_promozioni)
        return Response(
            {"righe": esito, "valido": True, "salvate": numero_promozioni, "campagne": numero_campagne},
            status=status.HTTP_201_CREATED,
        )


class PromozioniViewSet(ViewSetCliente):
    """Le promozioni: date e immagini. I destinatari sono quelli della loro campagna."""

    ruoli_scrittura = CONTENUTI
    serializer_class = PromozioneSerializer

    def get_queryset(self):
        promozioni = Promozione.objects.select_related("campagna")
        limitate = sedi_visibili(self.request.user)
        if limitate is None:
            return promozioni
        return promozioni.filter(campagna__monitor__sede_id__in=limitate).distinct()

    def perform_create(self, serializer):
        registra(self.request.user, "promozione_creata", serializer.save())

    def perform_update(self, serializer):
        verifica_campagna_modificabile(self.request.user, serializer.instance.campagna)
        registra(self.request.user, "promozione_modificata", serializer.save())

    def perform_destroy(self, promozione):
        verifica_campagna_modificabile(self.request.user, promozione.campagna)
        registra(self.request.user, "promozione_eliminata", promozione, nome=promozione.nome)
        campagne.elimina_promozione(promozione)


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
        # Il player ha già l'ultima versione? (la dichiara a ogni segnale periodico)
        aggiornato = bool(monitor.manifest_ricevuto) and monitor.manifest_ricevuto == palinsesto.manifest(monitor)["versione"]
        riserva = monitor.immagine_riserva_id
        return Response({"monitor": monitor.id, "quando": istante, "sequenza": sequenza, "riserva": riserva, "aggiornato": aggiornato})


class AnteprimaManifestView(VistaConContesto, APIView):
    """Il manifest di un monitor come lo riceve il player, per l'anteprima grafica nel pannello."""

    ruoli_lettura = TUTTI

    def get(self, request, monitor_id):
        monitor = Monitor.objects.filter(id=monitor_id)
        limitate = sedi_visibili(request.user)
        if limitate is not None:
            monitor = monitor.filter(sede_id__in=limitate)
        monitor = monitor.first()
        if monitor is None:
            raise exceptions.NotFound()
        return Response(palinsesto.manifest(monitor))


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
