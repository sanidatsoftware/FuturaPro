from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.models import registra
from core.api import TELEASSISTENZA, RiferimentoCliente, VistaConContesto
from dispositivi.models import Monitor
from utenti.models import Ruolo

from .models import SessioneTeleassistenza, Stato


class SessioneSerializer(serializers.ModelSerializer):
    monitor = RiferimentoCliente(Monitor)

    class Meta:
        model = SessioneTeleassistenza
        fields = ["id", "monitor", "tecnico", "motivo", "stato", "iniziata", "chiusa"]
        read_only_fields = ["tecnico", "stato", "iniziata", "chiusa"]


class SessioniViewSet(
    VistaConContesto,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Sessioni remote sui player del cliente selezionato.

    Le aprono e le chiudono solo il SystemAdministrator e i tecnici; l'Administrator
    vede il registro (chi, quando, su quale monitor e perché) ma non può avviarle.
    """

    ruoli_lettura = TELEASSISTENZA | {Ruolo.ADMIN_CLIENTE}
    ruoli_scrittura = TELEASSISTENZA
    serializer_class = SessioneSerializer

    def get_queryset(self):
        return SessioneTeleassistenza.objects.select_related("monitor")

    def perform_create(self, serializer):
        utente = self.request.user
        if not utente.puo_teleassistenza:
            raise PermissionDenied()
        sessione = serializer.save(tecnico_id=utente.id, tecnico=utente.username)
        registra(utente, "teleassistenza_richiesta", sessione, monitor=str(sessione.monitor_id), motivo=sessione.motivo)

    @action(detail=True, methods=["post"])
    def chiudi(self, request, pk=None):
        sessione = self.get_object()
        if sessione.stato == Stato.CHIUSA:
            raise ValidationError("La sessione è già chiusa.")
        sessione.stato = Stato.CHIUSA
        sessione.chiusa = timezone.now()
        sessione.save(update_fields=["stato", "chiusa"])
        registra(request.user, "teleassistenza_chiusa", sessione)
        return Response(self.get_serializer(sessione).data)
