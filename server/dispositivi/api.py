from django.utils import timezone
from rest_framework import authentication, exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Abilitazioni, Sede
from core.api import RiferimentoCliente, ViewSetCliente, sedi_visibili
from core.contesto import contesto_cliente
from utenti.models import Ruolo

from .models import CredenzialeDispositivo, GruppoMonitor, Monitor, Piattaforma, RichiestaAbbinamento, impronta


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


class MonitorSerializer(serializers.ModelSerializer):
    sede = RiferimentoCliente(Sede)
    gruppi = RiferimentoCliente(GruppoMonitor, many=True, required=False)
    online = serializers.BooleanField(read_only=True)

    class Meta:
        model = Monitor
        fields = [
            "id", "nome", "sede", "gruppi", "piattaforma", "versione_player",
            "ultimo_contatto", "online", "abbinato_il",
        ]
        read_only_fields = ["piattaforma", "versione_player", "ultimo_contatto", "abbinato_il"]


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
        registra(self.request.user, "monitor_modificato", serializer.save())

    def perform_destroy(self, monitor):
        self._verifica_abilitazione()
        registra(self.request.user, "monitor_rimosso", monitor, nome=monitor.nome)
        monitor.delete()


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


class StatoPlayerView(APIView):
    """Il player chiede a che punto è: in attesa di abbinamento, oppure abbinato e a chi."""

    authentication_classes = []
    permission_classes = [AllowAny]

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


class HeartbeatView(APIView):
    """Segnale periodico del player: aggiorna l'ultimo contatto e la versione."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = token_dalla_richiesta(request)
        credenziale = None
        if token is not None:
            credenziale = CredenzialeDispositivo.objects.filter(impronta_token=impronta(token), revocata=False).first()
        if credenziale is None:
            raise exceptions.AuthenticationFailed()
        with contesto_cliente(credenziale.cliente_id):
            Monitor.objects.filter(id=credenziale.monitor_id).update(
                ultimo_contatto=timezone.now(),
                versione_player=str(request.data.get("versione", ""))[:40],
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
