import secrets

from django.http import FileResponse
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Sede
from core.api import CONTENUTI, GESTIONE, RiferimentoCliente, ViewSetCliente, VistaConContesto, sedi_visibili
from core.contesto import contesto_cliente
from dispositivi.api import VistaPlayer, credenziale_dalla_richiesta
from dispositivi.models import Monitor, impronta
from layout.manifest import layout_del_monitor

from . import annunci, registro, servizi
from .models import Biglietto, CredenzialePulsante, FileAnnuncio, ImpostazioniTelefono, Reparto, SerieAnnunci

# Operazioni del banco: le fa anche lo User, che non gestisce i reparti.
AZIONI_BANCO = {"avanti", "indietro", "ripeti", "azzera", "imposta", "emetti"}


class RepartoSerializer(serializers.ModelSerializer):
    sede = RiferimentoCliente(Sede)
    colore = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)
    colore_testo = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)
    massimo = serializers.IntegerField(min_value=9, max_value=999, required=False)
    numero = serializers.IntegerField(read_only=True)
    in_coda = serializers.IntegerField(read_only=True)
    ultimo_emesso = serializers.IntegerField(read_only=True)
    ha_chiave = serializers.SerializerMethodField()
    # Se la sede ha un totem, numeri e chiamate stanno lì e non sul server.
    totem = serializers.CharField(source="sede.indirizzo_totem", read_only=True)
    annunci = RiferimentoCliente(SerieAnnunci, required=False, allow_null=True)

    class Meta:
        model = Reparto
        fields = [
            "id", "sede", "nome", "colore", "colore_testo", "ordine", "massimo", "attivo", "azzeramento_automatico",
            "numero", "in_coda", "ultimo_emesso", "chiamato_il", "ha_chiave", "totem", "annunci",
        ]
        read_only_fields = ["chiamato_il"]

    def get_ha_chiave(self, reparto):
        return hasattr(reparto, "credenziale")


def verifica_code_sul_server(reparto):
    """Con il totem le code stanno lì: il server non deve dare numeri paralleli."""
    if reparto.sede.indirizzo_totem:
        raise exceptions.ValidationError(
            f"Le code di questa sede sono gestite dal totem ({reparto.sede.indirizzo_totem}): "
            f"usa http://{reparto.sede.indirizzo_totem}:8090/banco/ con il collegamento del reparto."
        )


class RepartiViewSet(ViewSetCliente):
    """I reparti con la loro coda. Configurarli è della gestione; chiamare i numeri è del banco."""

    serializer_class = RepartoSerializer

    @property
    def ruoli_scrittura(self):
        return CONTENUTI if self.action in AZIONI_BANCO else GESTIONE

    def get_queryset(self):
        reparti = Reparto.objects.select_related("sede", "credenziale")
        limitate = sedi_visibili(self.request.user)
        return reparti if limitate is None else reparti.filter(sede_id__in=limitate)

    def perform_create(self, serializer):
        self._verifica_sede(serializer.validated_data.get("sede"))
        registra(self.request.user, "reparto_creato", serializer.save())

    def perform_update(self, serializer):
        self._verifica_sede(serializer.validated_data.get("sede"))
        registra(self.request.user, "reparto_modificato", serializer.save())

    def perform_destroy(self, reparto):
        registra(self.request.user, "reparto_eliminato", reparto, nome=reparto.nome)
        reparto.delete()

    def _verifica_sede(self, sede):
        limitate = sedi_visibili(self.request.user)
        if sede is not None and limitate is not None and sede.id not in limitate:
            raise exceptions.ValidationError({"sede": "Sede inesistente."})

    def _esegui(self, operazione, *argomenti):
        reparto = self.get_object()
        verifica_code_sul_server(reparto)
        try:
            reparto = operazione(reparto.id, *argomenti)
        except servizi.RepartoChiuso:
            raise exceptions.ValidationError("Il reparto è chiuso.")
        return Response(RepartoSerializer(reparto).data)

    @action(detail=True, methods=["post"])
    def avanti(self, request, pk=None):
        return self._esegui(servizi.avanti)

    @action(detail=True, methods=["post"])
    def indietro(self, request, pk=None):
        return self._esegui(servizi.indietro)

    @action(detail=True, methods=["post"])
    def ripeti(self, request, pk=None):
        return self._esegui(servizi.ripeti)

    @action(detail=True, methods=["post"])
    def azzera(self, request, pk=None):
        verifica_code_sul_server(self.get_object())
        registra(request.user, "coda_azzerata", self.get_object())
        return self._esegui(servizi.azzera)

    @action(detail=True, methods=["post"])
    def imposta(self, request, pk=None):
        campo = serializers.IntegerField(min_value=0, max_value=self.get_object().massimo)
        try:
            numero = campo.run_validation(request.data.get("numero"))
        except serializers.ValidationError as errore:
            raise exceptions.ValidationError({"numero": errore.detail})
        return self._esegui(servizi.imposta, numero)

    @action(detail=True, methods=["post"])
    def emetti(self, request, pk=None):
        """Un biglietto dal banco (per esempio per un cliente al telefono)."""
        return self._esegui(servizi.emetti)

    @action(detail=True, methods=["post", "delete"])
    def chiave(self, request, pk=None):
        """Una chiave nuova per pulsantiere e bilance (la vecchia smette di valere); DELETE la revoca.

        La chiave si vede solo adesso: il server ne conserva l'impronta.
        """
        reparto = self.get_object()
        CredenzialePulsante.objects.filter(reparto=reparto).delete()
        if request.method == "DELETE":
            registra(request.user, "chiave_pulsante_revocata", reparto)
            return Response(status=status.HTTP_204_NO_CONTENT)
        chiave = secrets.token_urlsafe(24)
        CredenzialePulsante.objects.create(impronta_chiave=impronta(chiave), reparto=reparto, cliente_id=reparto.cliente_id)
        registra(request.user, "chiave_pulsante_creata", reparto)
        return Response({"chiave": chiave}, status=status.HTTP_201_CREATED)


# --- Annunci registrati ----------------------------------------------------------


class SerieAnnunciSerializer(serializers.ModelSerializer):
    numeri = serializers.SerializerMethodField()
    predefinito = serializers.SerializerMethodField()
    reparti = serializers.SerializerMethodField()

    class Meta:
        model = SerieAnnunci
        fields = ["id", "nome", "numeri", "predefinito", "reparti", "creata"]
        read_only_fields = ["creata"]

    def get_numeri(self, serie):
        # numero -> id del file, per ascoltarlo dal pannello
        return {str(f.numero): str(f.id) for f in serie.file.all() if f.numero is not None}

    def get_predefinito(self, serie):
        return next((str(f.id) for f in serie.file.all() if f.numero is None), None)

    def get_reparti(self, serie):
        return [str(r.id) for r in serie.reparti.all()]

    def validate_nome(self, nome):
        nome = nome.strip()
        doppione = SerieAnnunci.objects.filter(nome__iexact=nome)
        if self.instance is not None:
            doppione = doppione.exclude(id=self.instance.id)
        if doppione.exists():
            raise serializers.ValidationError("Esiste già una serie con questo nome.")
        return nome


class SerieAnnunciViewSet(ViewSetCliente):
    """Gli annunci dei numeri (es. «SALUMERIA_27.mp3»), in serie collegate ai reparti."""

    ruoli_scrittura = GESTIONE
    serializer_class = SerieAnnunciSerializer

    def get_queryset(self):
        return SerieAnnunci.objects.prefetch_related("file", "reparti")

    def perform_destroy(self, serie):
        registra(self.request.user, "annunci_eliminati", serie, nome=serie.nome)
        for f in serie.file.all():
            f.delete()
        serie.delete()

    @action(detail=False, methods=["post"])
    def importa(self, request):
        """Molti file insieme (anche una cartella intera): serie e numero dai nomi dei file.
        Con ``serie`` (id) vanno tutti in quella serie."""
        files = request.FILES.getlist("file")
        if not files:
            raise exceptions.ValidationError({"file": "Scegli i file audio."})
        serie = None
        if request.data.get("serie"):
            serie = SerieAnnunci.objects.filter(id=request.data["serie"]).first()
            if serie is None:
                raise exceptions.ValidationError({"serie": "Serie inesistente."})
        esito = annunci.importa(files, serie)
        registra(request.user, "annunci_caricati", serie, file=esito["caricati"], scartati=len(esito["scartati"]))
        return Response(esito, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def togli(self, request, pk=None):
        """Toglie i file di alcuni numeri (``numeri``) e/o il predefinito (``predefinito: true``)."""
        serie = self.get_object()
        numeri = [int(n) for n in request.data.get("numeri") or [] if str(n).isdigit()]
        tolti = list(serie.file.filter(numero__in=numeri))
        if request.data.get("predefinito") is True:
            tolti += list(serie.file.filter(numero__isnull=True))
        for f in tolti:
            f.delete()
        return Response(SerieAnnunciSerializer(SerieAnnunci.objects.get(id=serie.id)).data)

    @action(detail=False, methods=["get"], url_path=r"ascolta/(?P<file_id>[0-9a-f-]{36})")
    def ascolta(self, request, file_id=None):
        f = FileAnnuncio.objects.filter(id=file_id).first()
        if f is None:
            raise exceptions.NotFound()
        return _audio(f)


def _audio(f):
    tipo = {".wav": "audio/wav", ".ogg": "audio/ogg"}.get(f.file.name[-4:], "audio/mpeg")
    return FileResponse(f.file.open("rb"), content_type=tipo)


class AnnuncioPlayerView(VistaPlayer):
    """Il file di un annuncio, per i player della sede dei reparti che lo usano."""

    def get(self, request, file_id):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            monitor = Monitor.objects.get(id=credenziale.monitor_id)
            f = FileAnnuncio.objects.filter(id=file_id, serie__reparti__sede_id=monitor.sede_id).first()
            if f is None:
                raise exceptions.NotFound()
            return _audio(f)


# --- Pulsantiere, bilance, script -----------------------------------------------
#
# Sostituiscono gli script py/*.py del sistema attuale:
#   curl -X POST -H "Authorization: Pulsante <chiave>" https://server/api/eliminacode/pulsante/avanti/
# La chiave vale per un solo reparto e solo per le operazioni del banco (come le
# pagine per le bilance del sistema attuale: avanti, indietro, azzera, imposta).

OPERAZIONI_PULSANTE = {
    "avanti": servizi.avanti,
    "indietro": servizi.indietro,
    "ripeti": servizi.ripeti,
    "azzera": servizi.azzera,
    "imposta": servizi.imposta,
}


class PulsanteView(VistaPlayer):
    def get_authenticate_header(self, request):
        return "Pulsante"

    def _credenziale(self, request):
        parti = request.headers.get("Authorization", "").split()
        if len(parti) == 2 and parti[0] == "Pulsante":
            credenziale = CredenzialePulsante.objects.filter(impronta_chiave=impronta(parti[1])).first()
            if credenziale is not None:
                return credenziale
        raise exceptions.AuthenticationFailed()

    def get(self, request, operazione=None):
        credenziale = self._credenziale(request)
        with contesto_cliente(credenziale.cliente_id):
            return Response(Reparto.objects.get(id=credenziale.reparto_id).stato())

    def post(self, request, operazione):
        credenziale = self._credenziale(request)
        if operazione not in OPERAZIONI_PULSANTE:
            raise exceptions.NotFound()
        with contesto_cliente(credenziale.cliente_id):
            verifica_code_sul_server(Reparto.objects.select_related("sede").get(id=credenziale.reparto_id))
            argomenti = []
            if operazione == "imposta":
                massimo = Reparto.objects.get(id=credenziale.reparto_id).massimo
                campo = serializers.IntegerField(min_value=0, max_value=massimo)
                try:
                    argomenti = [campo.run_validation(request.data.get("numero"))]
                except serializers.ValidationError as errore:
                    raise exceptions.ValidationError({"numero": errore.detail})
            return Response(OPERAZIONI_PULSANTE[operazione](credenziale.reparto_id, *argomenti).stato())


# --- Zone dei player ------------------------------------------------------------


def reparti_della_zona(configurazione, monitor=None):
    """Quelli scelti nella zona; se nessuno, tutti i reparti attivi della sede del monitor.

    Così un solo layout va bene per tutti i negozi: ognuno mostra i suoi banchi.
    """
    scelti = configurazione.get("reparti") or []
    reparti = Reparto.objects.filter(attivo=True)
    if scelti:
        per_id = {str(r.id): r for r in reparti.filter(id__in=scelti)}
        return [per_id[i] for i in scelti if i in per_id]
    if monitor is not None:
        reparti = reparti.filter(sede_id=monitor.sede_id)
    return list(reparti.order_by("ordine", "nome"))


class EmettiPlayerView(VistaPlayer):
    """Il cliente tocca un reparto sul totem: nuovo biglietto, che il player stampa."""

    def post(self, request, zona_id):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            monitor = Monitor.objects.get(id=credenziale.monitor_id)
            layout = layout_del_monitor(monitor)
            zona = layout and layout.zone.filter(id=zona_id, tipo="prendi_numero").first()
            if not zona:
                raise exceptions.NotFound()
            ammessi = {str(r.id) for r in reparti_della_zona(zona.configurazione, monitor)}
            reparto_id = str(request.data.get("reparto", ""))
            if reparto_id not in ammessi:
                raise exceptions.ValidationError({"reparto": "Reparto non disponibile su questo totem."})
            if monitor.sede.indirizzo_totem:
                raise exceptions.ValidationError({"reparto": "Le code di questa sede sono gestite dal totem."})
            try:
                reparto = servizi.emetti(reparto_id)
            except servizi.RepartoChiuso:
                raise exceptions.ValidationError({"reparto": "Il reparto è chiuso."})
            return Response(
                {"reparto_id": str(reparto.id), "reparto": reparto.nome, "colore": reparto.colore,
                 "colore_testo": reparto.colore_testo, "numero": reparto.ultimo_emesso,
                 "davanti": reparto.in_coda - 1, "sede": monitor.sede.nome, "codice": reparto.biglietto.codice},
                status=status.HTTP_201_CREATED,
            )


class EventiCodaPlayerView(VistaPlayer):
    """Il player del totem inoltra il registro del servizio code (biglietti e chiamate)."""

    def post(self, request):
        credenziale = credenziale_dalla_richiesta(request)
        eventi = request.data.get("eventi")
        if not isinstance(eventi, list):
            raise exceptions.ValidationError({"eventi": "Elenco mancante."})
        with contesto_cliente(credenziale.cliente_id):
            monitor = Monitor.objects.get(id=credenziale.monitor_id)
            ammessi = {str(r.id): r for r in Reparto.objects.filter(sede_id=monitor.sede_id)}
            registrati = registro.registra_dal_totem(ammessi, eventi)
        return Response({"registrati": registrati})


# --- Coda sul telefono -----------------------------------------------------------


class LimitePerBiglietto(SimpleRateThrottle):
    """Per codice, non per indirizzo: i telefoni con la rete dati escono spesso dallo stesso IP."""

    scope = "biglietto"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": view.kwargs.get("codice", "")}


class BigliettoPubblicoView(APIView):
    """Lo stato di un biglietto per la pagina sul telefono: chi ha il codice (dal QR) lo vede."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [LimitePerBiglietto]

    def get(self, request, codice):
        from core.contesto import contesto_piattaforma

        if codice == "prova":
            # Per vedere com'è la pagina prima di attivarla: un biglietto inventato.
            return Response({
                "reparto": "Salumeria", "colore": "#c62828", "colore_testo": "#ffffff", "numero": 27, "servito": 23,
                "davanti": 3, "stato": "in_attesa", "attesa_minuti": 6, "avviso_a": 3, "aggiornato": None, "emesso_il": None,
            })
        with contesto_piattaforma():
            trovato = Biglietto.objects.filter(codice=codice).values_list("id", "cliente_id").first()
        if trovato is None:
            raise exceptions.NotFound()
        with contesto_cliente(trovato[1]):
            impostazioni = ImpostazioniTelefono.objects.first()
            if impostazioni is None or not impostazioni.attivo:
                raise exceptions.NotFound()
            biglietto = Biglietto.objects.select_related("reparto").get(id=trovato[0])
            risposta = Response(registro.stato_biglietto(biglietto))
        risposta["Cache-Control"] = "no-store"
        return risposta


class ImpostazioniTelefonoSerializer(serializers.ModelSerializer):
    avviso_a = serializers.IntegerField(min_value=1, max_value=10, required=False)

    class Meta:
        model = ImpostazioniTelefono
        fields = ["attivo", "testo", "avviso_a"]


class TelefonoView(VistaConContesto, APIView):
    """Le impostazioni della coda sul telefono, con l'indirizzo pubblico del server (se c'è)."""

    def _risposta(self, impostazioni):
        from django.conf import settings

        dati = ImpostazioniTelefonoSerializer(impostazioni).data
        dati["url_pubblico"] = settings.FUTURAPRO_URL_PUBBLICO
        return Response(dati)

    def get(self, request):
        return self._risposta(ImpostazioniTelefono.objects.first() or ImpostazioniTelefono())

    def put(self, request):
        impostazioni = ImpostazioniTelefono.objects.first()
        dati = ImpostazioniTelefonoSerializer(impostazioni, data=request.data, partial=True)
        dati.is_valid(raise_exception=True)
        salvate = dati.save()
        registra(request.user, "coda_telefono_modificata", None, attivo=salvate.attivo)
        return self._risposta(salvate)


class StatisticheCodeView(VistaConContesto, APIView):
    """I tempi d'attesa: ?dal=AAAA-MM-GG&al=…&reparto=<id> (facoltativo)."""

    def get(self, request):
        from datetime import date, timedelta

        from django.utils import timezone

        from . import statistiche

        try:
            al = date.fromisoformat(request.query_params.get("al") or timezone.localdate().isoformat())
            dal = date.fromisoformat(request.query_params.get("dal") or (al - timedelta(days=29)).isoformat())
        except ValueError:
            raise exceptions.ValidationError("Date non valide.")
        if dal > al or (al - dal).days > 366:
            raise exceptions.ValidationError("Periodo non valido (al massimo un anno).")
        reparti = Reparto.objects.select_related("sede").order_by("sede__nome", "ordine", "nome")
        limitate = sedi_visibili(request.user)
        if limitate is not None:
            reparti = reparti.filter(sede_id__in=limitate)
        if request.query_params.get("reparto"):
            reparti = reparti.filter(id=request.query_params["reparto"])
        return Response({"dal": dal, "al": al, **statistiche.calcola(list(reparti), dal, al)})
