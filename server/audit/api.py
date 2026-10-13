from rest_framework import serializers, viewsets

from core.api import GESTIONE, SOLO_ASSOLUTO, VistaConContesto

from .models import EventoAudit


class EventoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventoAudit
        fields = [
            "id", "quando", "utente", "ruolo", "per_conto_piattaforma",
            "azione", "oggetto_tipo", "oggetto_id", "dettagli",
        ]


class AuditClienteViewSet(VistaConContesto, viewsets.ReadOnlyModelViewSet):
    """Il registro del cliente, comprese le azioni fatte dalla piattaforma per suo conto."""

    ruoli_lettura = GESTIONE
    serializer_class = EventoSerializer

    def get_queryset(self):
        return EventoAudit.objects.all()


class AuditPiattaformaViewSet(VistaConContesto, viewsets.ReadOnlyModelViewSet):
    ambito = "piattaforma"
    ruoli_lettura = SOLO_ASSOLUTO
    serializer_class = EventoSerializer

    def get_queryset(self):
        return EventoAudit.objects.all()
