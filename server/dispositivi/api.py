from datetime import datetime, time, timedelta

from django.core.files.storage import default_storage
from django.db.models import F, Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework import authentication, exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Abilitazioni, Sede
from contenuti.models import Contenuto
from layout.models import Layout
from clienti.models import Insegna
from core.api import GESTIONE, RiferimentoCliente, VistaConContesto, ViewSetCliente, sedi_visibili
from core.contesto import contesto_cliente
from utenti.models import Ruolo

from . import schermate
from .models import (
    acceso_secondo_orario, orario_del_monitor,
    CredenzialeDispositivo, EventoSchermo, GruppoMonitor, ImpostazioniAllarmi, Monitor, OrarioSchermi, Piattaforma,
    PresenzaSchermo, RichiestaAbbinamento, impronta,
)


class GruppoSerializer(serializers.ModelSerializer):
    class Meta:
        model = GruppoMonitor
        fields = ["id", "nome"]


class GruppiViewSet(ViewSetCliente):
    serializer_class = GruppoSerializer

    def get_queryset(self):
        return GruppoMonitor.objects.all()

    def perform_create(self, serializer):
        registra(self.request.user, "gruppo_creato", serializer.save())

    def perform_update(self, serializer):
        registra(self.request.user, "gruppo_modificato", serializer.save())

    def perform_destroy(self, instance):
        registra(self.request.user, "gruppo_eliminato", instance, nome=instance.nome)
        instance.delete()


def elimina_riserve_orfane(appena_tolta=None):
    """Le riserve caricate per gli schermi che nessuno schermo usa più: via dal server
    (e quindi, al prossimo palinsesto, anche dalla cache dei player). Quelle caricate da
    poco restano un giorno, nel caso stiano per essere assegnate."""
    usate = Monitor.objects.exclude(immagine_riserva__isnull=True).values("immagine_riserva_id")
    orfane = Contenuto.objects.filter(uso="riserva").exclude(id__in=usate)
    vecchie = Q(creato__lt=timezone.now() - timedelta(days=1))
    for contenuto in orfane.filter(vecchie | Q(id=appena_tolta) if appena_tolta else vecchie):
        contenuto.delete()


class MonitorSerializer(serializers.ModelSerializer):
    sede = RiferimentoCliente(Sede)
    gruppi = RiferimentoCliente(GruppoMonitor, many=True, required=False)
    layout = RiferimentoCliente(Layout, required=False, allow_null=True)
    immagine_riserva = RiferimentoCliente(Contenuto, required=False, allow_null=True)
    online = serializers.BooleanField(read_only=True)
    problema = serializers.SerializerMethodField()
    riposo = serializers.SerializerMethodField()

    def get_problema(self, monitor):
        return (monitor.info_dispositivo or {}).get("problema")

    def get_riposo(self, monitor):
        return bool((monitor.info_dispositivo or {}).get("riposo"))

    class Meta:
        model = Monitor
        fields = [
            "id", "nome", "sede", "gruppi", "orientamento", "rotazione", "layout", "immagine_riserva", "piattaforma",
            "versione_player", "ultimo_contatto", "online", "problema", "riposo", "schermata_il", "abbinato_il",
        ]
        read_only_fields = ["piattaforma", "versione_player", "ultimo_contatto", "schermata_il", "abbinato_il"]

    def validate(self, dati):
        orientamento = dati.get("orientamento") or getattr(self.instance, "orientamento", "orizzontale")
        layout = dati["layout"] if "layout" in dati else getattr(self.instance, "layout", None)
        if layout is not None and layout.orientamento != orientamento:
            raise serializers.ValidationError({"layout": f"Il layout è {layout.orientamento}, il monitor {orientamento}."})
        riserva = dati.get("immagine_riserva")
        if riserva is not None and riserva.tipo not in ("immagine", "video"):
            raise serializers.ValidationError({"immagine_riserva": "Dev'essere un'immagine o un video."})
        return dati


class FasciaSerializer(serializers.Serializer):
    giorni = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), min_length=1)
    dalle = serializers.TimeField(format="%H:%M")
    alle = serializers.TimeField(format="%H:%M")

    def validate(self, dati):
        if dati["dalle"] == dati["alle"]:
            raise serializers.ValidationError("Inizio e fine della fascia coincidono.")
        return {"giorni": sorted(set(dati["giorni"])), "dalle": dati["dalle"].strftime("%H:%M"), "alle": dati["alle"].strftime("%H:%M")}


class OrarioSerializer(serializers.ModelSerializer):
    fasce = FasciaSerializer(many=True, required=False)
    chiusure = serializers.ListField(child=serializers.DateField(), required=False)
    insegne = RiferimentoCliente(Insegna, many=True, required=False)
    gruppi = RiferimentoCliente(GruppoMonitor, many=True, required=False)
    monitor = RiferimentoCliente(Monitor, many=True, required=False)

    class Meta:
        model = OrarioSchermi
        fields = ["id", "nome", "fasce", "chiusure", "attivo", "insegne", "gruppi", "monitor", "modificato"]
        read_only_fields = ["modificato"]

    def validate_chiusure(self, date):
        return sorted({d.isoformat() for d in date})

    def to_representation(self, orario):
        dati = super().to_representation(orario)
        dati["fasce"] = orario.fasce
        dati["chiusure"] = orario.chiusure
        return dati


class OrariViewSet(ViewSetCliente):
    """Gli orari di accensione degli schermi (fuori orario: riposo, schermo nero)."""

    ruoli_scrittura = GESTIONE
    serializer_class = OrarioSerializer

    def get_queryset(self):
        return OrarioSchermi.objects.prefetch_related("insegne", "gruppi", "monitor")

    def perform_create(self, serializer):
        registra(self.request.user, "orario_creato", serializer.save())

    def perform_update(self, serializer):
        registra(self.request.user, "orario_modificato", serializer.save())

    def perform_destroy(self, orario):
        registra(self.request.user, "orario_eliminato", orario, nome=orario.nome)
        orario.delete()


class ImpostazioniAllarmiSerializer(serializers.ModelSerializer):
    email = serializers.ListField(child=serializers.EmailField(), required=False, max_length=20)
    minuti = serializers.IntegerField(min_value=3, max_value=24 * 60, required=False)

    class Meta:
        model = ImpostazioniAllarmi
        fields = ["attivo", "email", "minuti", "solo_in_orario", "avvisa_ritorno"]

    def validate(self, dati):
        attivo = dati.get("attivo", getattr(self.instance, "attivo", False))
        email = dati.get("email", getattr(self.instance, "email", []))
        if attivo and not email:
            raise serializers.ValidationError({"email": "Indica almeno un indirizzo a cui mandare gli allarmi."})
        return dati


class StatoSchermiView(VistaConContesto, APIView):
    """Lo stato di tutti gli schermi, i minuti di collegamento degli ultimi giorni e lo storico
    degli allarmi. Con PUT/POST le impostazioni degli allarmi (solo la gestione)."""

    def _verifica_gestione(self, request):
        if request.user.ruolo not in GESTIONE:
            raise exceptions.PermissionDenied("Solo chi gestisce il cliente cambia gli allarmi.")

    def get(self, request):
        from . import allarmi

        giorni = max(1, min(31, int(request.query_params.get("giorni", 7))))
        oggi = timezone.localdate()
        dal = oggi - timedelta(days=giorni - 1)
        monitor = Monitor.objects.select_related("sede").order_by("sede__nome", "nome")
        limitate = sedi_visibili(request.user)
        if limitate is not None:
            monitor = monitor.filter(sede_id__in=limitate)
        presenze = {}
        for p in PresenzaSchermo.objects.filter(monitor__in=monitor, giorno__gte=dal):
            presenze.setdefault(str(p.monitor_id), {})[p.giorno.isoformat()] = [p.minuti, p.minuti_riposo]
        schermi = []
        for m in monitor:
            orario = orario_del_monitor(m)
            atteso = {}
            for n in range(giorni):
                giorno = dal + timedelta(days=n)
                # Minuti in cui lo schermo doveva essere acceso, a passi di 10 minuti.
                inizio = timezone.make_aware(datetime.combine(giorno, time(0, 0)))
                # Oggi conta solo fino a adesso.
                passi = 144 if giorno < oggi else int((timezone.now() - inizio).total_seconds() // 600)
                atteso[giorno.isoformat()] = sum(
                    10 for passo in range(passi) if acceso_secondo_orario(orario, timezone.localtime(inizio + timedelta(minutes=10 * passo + 5)))
                )
            schermi.append({
                "id": str(m.id), "nome": m.nome, "sede": m.sede.nome, "orientamento": m.orientamento,
                "online": m.online, "riposo": bool((m.info_dispositivo or {}).get("riposo")),
                "ultimo_contatto": m.ultimo_contatto, "versione": m.versione_player,
                "problema": (m.info_dispositivo or {}).get("problema"), "allarme_dal": m.allarme_dal,
                "orario": orario.nome if orario else None,
                "presenze": presenze.get(str(m.id), {}), "atteso": atteso,
                # Prima di questo giorno non ci sono dati (storico appena iniziato o schermo nuovo).
                "dati_dal": min(presenze.get(str(m.id), {}) or [None]) if str(m.id) in presenze else None,
            })
        eventi = EventoSchermo.objects.filter(monitor__in=monitor).select_related("monitor", "monitor__sede")[:50]
        impostazioni = ImpostazioniAllarmi.objects.first()
        return Response({
            "giorni": [(dal + timedelta(days=n)).isoformat() for n in range(giorni)],
            "schermi": schermi,
            "eventi": [
                {"monitor": e.monitor.nome, "sede": e.monitor.sede.nome, "tipo": e.tipo, "quando": e.quando,
                 "dettaglio": e.dettaglio, "email": e.email_inviata}
                for e in eventi
            ],
            "allarmi": ImpostazioniAllarmiSerializer(impostazioni).data if impostazioni else
            {"attivo": False, "email": [], "minuti": 15, "solo_in_orario": True, "avvisa_ritorno": True},
            "email_configurata": allarmi.email_configurata(),
        })

    def put(self, request):
        self._verifica_gestione(request)
        impostazioni = ImpostazioniAllarmi.objects.first()
        dati = ImpostazioniAllarmiSerializer(impostazioni, data=request.data, partial=True)
        dati.is_valid(raise_exception=True)
        salvate = dati.save()
        registra(request.user, "allarmi_modificati", None, attivo=salvate.attivo)
        return Response(ImpostazioniAllarmiSerializer(salvate).data)

    def post(self, request):
        """Una email di prova agli indirizzi indicati."""
        from . import allarmi

        self._verifica_gestione(request)
        if not allarmi.email_configurata():
            raise exceptions.ValidationError("Il server non ha ancora un server email (SMTP): vedi la guida di installazione.")
        prova = ImpostazioniAllarmi(email=request.data.get("email") or [])
        dati = ImpostazioniAllarmiSerializer(data={"email": prova.email})
        dati.is_valid(raise_exception=True)
        prova.email = dati.validated_data["email"]
        if not allarmi.invia(prova, "FuturaPro: email di prova", "Se leggi questo messaggio, gli allarmi degli schermi arriveranno qui."):
            raise exceptions.ValidationError("L'email non è partita: controlla le impostazioni SMTP del server.")
        return Response({"inviata": True})


class AbbinamentoSerializer(serializers.Serializer):
    codice = serializers.RegexField(r"^\d{6}$")
    nome = serializers.CharField(max_length=200)
    sede = RiferimentoCliente(Sede)
    gruppi = RiferimentoCliente(GruppoMonitor, many=True, required=False)


class MonitorViewSet(ViewSetCliente):
    """I monitor del cliente. Si aggiungono solo abbinando il codice mostrato dal player."""

    serializer_class = MonitorSerializer

    def get_queryset(self):
        monitor = Monitor.objects.select_related("sede").prefetch_related("gruppi")
        limitate = sedi_visibili(self.request.user)
        return monitor if limitate is None else monitor.filter(sede_id__in=limitate)

    def create(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed("POST", "Un monitor si aggiunge con l'abbinamento.")

    def _verifica_abilitazione(self):
        abilitazioni = Abilitazioni.objects.get()
        if self.request.user.ruolo != Ruolo.ADMIN_ASSOLUTO and not abilitazioni.admin_gestisce_dispositivi:
            raise exceptions.PermissionDenied("La gestione dei monitor non è abilitata per questo cliente.")
        return abilitazioni

    @action(detail=True, methods=["get", "post"], url_path="schermata")
    def schermata(self, request, pk=None):
        """GET: quando è stata scattata l'ultima fotografia dello schermo. POST: chiedine una nuova.

        Chiunque veda il monitor può chiederla: non cambia nulla di ciò che va in onda.
        """
        monitor = self.get_object()
        if request.method == "POST":
            schermate.richiedi(monitor)
            return Response({"richiesta": True}, status=status.HTTP_202_ACCEPTED)
        return Response({"quando": monitor.schermata_il, "richiesta": schermate.richiesta(monitor)})

    @action(detail=True, methods=["get"], url_path="schermata/immagine")
    def immagine_schermata(self, request, pk=None):
        monitor = self.get_object()
        nome = schermate.percorso(monitor)
        if not monitor.schermata_il or not default_storage.exists(nome):
            raise exceptions.NotFound()
        risposta = FileResponse(default_storage.open(nome, "rb"), content_type="image/jpeg")
        risposta["Cache-Control"] = "no-store"
        return risposta

    def get_permissions(self):
        # Chiedere una fotografia dello schermo è una lettura: lo può fare chiunque veda il monitor.
        if getattr(self, "action", None) == "schermata":
            self.ruoli_scrittura = self.ruoli_lettura
        return super().get_permissions()

    @action(detail=False, methods=["post"])
    def abbina(self, request):
        abilitazioni = self._verifica_abilitazione()
        dati = AbbinamentoSerializer(data=request.data)
        dati.is_valid(raise_exception=True)
        if Monitor.objects.count() >= abilitazioni.max_monitor:
            raise exceptions.ValidationError(f"Raggiunto il numero massimo di monitor ({abilitazioni.max_monitor}).")

        richiesta = (
            RichiestaAbbinamento.objects.select_for_update()
            .filter(codice=dati.validated_data["codice"], scade__gt=timezone.now())
            .first()
        )
        if richiesta is None:
            raise exceptions.ValidationError({"codice": "Codice inesistente o scaduto."})

        monitor = Monitor.objects.create(
            nome=dati.validated_data["nome"],
            sede=dati.validated_data["sede"],
            piattaforma=richiesta.piattaforma,
            info_dispositivo=richiesta.info_dispositivo,
        )
        monitor.gruppi.set(dati.validated_data.get("gruppi", []))
        CredenzialeDispositivo.objects.create(
            impronta_token=richiesta.impronta_token, monitor=monitor, cliente_id=monitor.cliente_id
        )
        richiesta.delete()
        registra(request.user, "monitor_abbinato", monitor, nome=monitor.nome)
        return Response(MonitorSerializer(monitor).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        self._verifica_abilitazione()
        vecchia = serializer.instance.immagine_riserva_id
        registra(self.request.user, "monitor_modificato", serializer.save())
        elimina_riserve_orfane(vecchia)

    def perform_destroy(self, monitor):
        self._verifica_abilitazione()
        vecchia = monitor.immagine_riserva_id
        registra(self.request.user, "monitor_rimosso", monitor, nome=monitor.nome)
        monitor.delete()
        elimina_riserve_orfane(vecchia)


# --- Player -----------------------------------------------------------------
#
# Il player si presenta con "Authorization: Device <token>". Il token lo genera
# lui all'installazione e non lascia mai il dispositivo, salvo la prima volta
# in cui chiede il codice di abbinamento. Nella fase della teleassistenza
# questo meccanismo passa a certificati client emessi dalla CA della
# piattaforma (mTLS); l'impronta resta come identificativo.


def token_dalla_richiesta(request) -> str | None:
    intestazione = authentication.get_authorization_header(request).decode(errors="ignore").split()
    if len(intestazione) == 2 and intestazione[0] == "Device" and len(intestazione[1]) >= 32:
        return intestazione[1]
    return None


def credenziale_dalla_richiesta(request) -> CredenzialeDispositivo:
    """La credenziale valida del player che fa la richiesta; altrimenti 401."""
    token = token_dalla_richiesta(request)
    credenziale = None
    if token is not None:
        credenziale = CredenzialeDispositivo.objects.filter(impronta_token=impronta(token), revocata=False).first()
    if credenziale is None:
        raise exceptions.AuthenticationFailed()
    return credenziale


class VistaPlayer(APIView):
    """Base delle viste chiamate dai player: si autenticano da sé con il token del dispositivo."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        # Senza schema DRF risponderebbe 403; il player deve capire che è un problema di credenziali.
        return "Device"


class SchermataPlayerView(VistaPlayer):
    """Il player chiede se deve fotografare lo schermo (GET) e manda la fotografia (POST, JPEG)."""

    def get(self, request):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            monitor = Monitor.objects.only("schermata_il", "schermata_richiesta").get(id=credenziale.monitor_id)
        return Response({"richiesta": schermate.richiesta(monitor)})

    def post(self, request):
        credenziale = credenziale_dalla_richiesta(request)
        file = request.FILES.get("immagine")
        if file is None or file.size > schermate.MASSIMO_BYTE:
            raise exceptions.ValidationError({"immagine": "Manca la fotografia, o è troppo grande."})
        dati = file.read()
        if not dati.startswith(b"\xff\xd8\xff"):
            raise exceptions.ValidationError({"immagine": "Dev'essere una JPEG."})
        with contesto_cliente(credenziale.cliente_id):
            schermate.salva(Monitor.objects.get(id=credenziale.monitor_id), dati)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ThrottleAbbinamento(AnonRateThrottle):
    scope = "abbinamento"


class RichiestaAbbinamentoView(APIView):
    """Il player appena installato chiede il codice da mostrare a schermo."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ThrottleAbbinamento]

    class Dati(serializers.Serializer):
        token = serializers.CharField(min_length=32, max_length=200)
        piattaforma = serializers.ChoiceField(choices=Piattaforma.choices)
        info = serializers.DictField(required=False)

    def post(self, request):
        dati = self.Dati(data=request.data)
        dati.is_valid(raise_exception=True)
        token = dati.validated_data["token"]
        if (
            CredenzialeDispositivo.objects.filter(impronta_token=impronta(token)).exists()
            or RichiestaAbbinamento.objects.filter(impronta_token=impronta(token)).exists()
        ):
            raise exceptions.ValidationError({"token": "Token già in uso: generane uno nuovo."})
        richiesta = RichiestaAbbinamento.nuova(token, dati.validated_data["piattaforma"], dati.validated_data.get("info", {}))
        return Response({"codice": richiesta.codice, "scade": richiesta.scade}, status=status.HTTP_201_CREATED)


class StatoPlayerView(VistaPlayer):
    """Il player chiede a che punto è: in attesa di abbinamento, oppure abbinato e a chi."""

    def get(self, request):
        token = token_dalla_richiesta(request)
        if token is None:
            raise exceptions.NotAuthenticated()
        chiave = impronta(token)
        credenziale = CredenzialeDispositivo.objects.filter(impronta_token=chiave, revocata=False).first()
        if credenziale is not None:
            with contesto_cliente(credenziale.cliente_id):
                monitor = Monitor.objects.get(id=credenziale.monitor_id)
                return Response({"abbinato": True, "monitor": monitor.id, "nome": monitor.nome})
        richiesta = RichiestaAbbinamento.objects.filter(impronta_token=chiave, scade__gt=timezone.now()).first()
        if richiesta is not None:
            return Response({"abbinato": False, "codice": richiesta.codice, "scade": richiesta.scade})
        raise exceptions.AuthenticationFailed()


class HeartbeatView(VistaPlayer):
    """Segnale periodico del player: aggiorna l'ultimo contatto e la versione."""

    def post(self, request):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            monitor = Monitor.objects.get(id=credenziale.monitor_id)
            adesso = timezone.now()
            # Un segnale ogni minuto: ognuno vale un minuto di collegamento nello storico.
            if monitor.ultimo_contatto is None or adesso - monitor.ultimo_contatto >= timedelta(seconds=45):
                presenza, _ = PresenzaSchermo.objects.get_or_create(
                    monitor=monitor, giorno=timezone.localdate(), defaults={"cliente_id": monitor.cliente_id}
                )
                PresenzaSchermo.objects.filter(id=presenza.id).update(
                    minuti=F("minuti") + 1, minuti_riposo=F("minuti_riposo") + (1 if request.data.get("riposo") is True else 0)
                )
            monitor.ultimo_contatto = adesso
            monitor.versione_player = str(request.data.get("versione", ""))[:40]
            monitor.manifest_ricevuto = str(request.data.get("manifest", ""))[:64]
            # Un problema che il player vuole far sapere (es. una diretta che non parte).
            problema = request.data.get("problema")
            info = dict(monitor.info_dispositivo or {})
            if isinstance(problema, dict) and problema.get("testo"):
                info["problema"] = {"testo": str(problema["testo"])[:300], "quando": str(problema.get("quando", ""))[:40]}
            else:
                info.pop("problema", None)
            # Fuori orario lo schermo riposa: non è un guasto.
            info["riposo"] = request.data.get("riposo") is True
            monitor.info_dispositivo = info
            monitor.save(update_fields=["ultimo_contatto", "versione_player", "manifest_ricevuto", "info_dispositivo"])
        return Response(status=status.HTTP_204_NO_CONTENT)
