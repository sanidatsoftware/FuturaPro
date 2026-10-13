from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Abilitazioni, Sede
from core.api import GESTIONE, SOLO_ASSOLUTO, RiferimentoCliente, ViewSetCliente
from core.contesto import contesto_corrente

from .models import RUOLI_CLIENTE, RUOLI_PIATTAFORMA, Ruolo, Utente

CAMPI = ["id", "username", "first_name", "last_name", "email", "ruolo", "is_active", "password"]


class UtenteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=10)
    ruoli_ammessi: set = set()

    class Meta:
        model = Utente
        fields = CAMPI

    def validate_ruolo(self, ruolo):
        if ruolo not in self.ruoli_ammessi:
            raise ValidationError("Ruolo non ammesso qui.")
        return ruolo

    def create(self, dati):
        password = dati.pop("password", None)
        if not password:
            raise ValidationError({"password": "Obbligatoria per un nuovo utente."})
        sedi = dati.pop("sedi_consentite", None)
        utente = Utente(**dati)
        utente.set_password(password)
        utente.save()
        if sedi is not None:
            utente.sedi_consentite.set(sedi)
        return utente

    def update(self, utente, dati):
        password = dati.pop("password", None)
        utente = super().update(utente, dati)
        if password:
            utente.set_password(password)
            utente.save(update_fields=["password"])
        return utente


class UtenteClienteSerializer(UtenteSerializer):
    ruoli_ammessi = RUOLI_CLIENTE
    sedi_consentite = RiferimentoCliente(Sede, many=True, required=False)

    class Meta(UtenteSerializer.Meta):
        fields = CAMPI + ["sedi_consentite"]


class UtentePiattaformaSerializer(UtenteSerializer):
    ruoli_ammessi = RUOLI_PIATTAFORMA


class IoView(APIView):
    """Chi sono: il pannello lo usa per decidere cosa mostrare (selettore clienti, teleassistenza)."""

    def get(self, request):
        utente = request.user
        return Response(
            {
                "id": utente.id,
                "username": utente.username,
                "ruolo": utente.ruolo,
                "cliente": utente.cliente_id,
                "di_piattaforma": utente.di_piattaforma,
                "teleassistenza": utente.puo_teleassistenza,
            }
        )


class UtentiClienteViewSet(ViewSetCliente):
    """Gli utenti di un cliente. L'AdminCliente li gestisce solo se l'Administrator Assoluto lo consente."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = GESTIONE
    serializer_class = UtenteClienteSerializer

    def get_queryset(self):
        return Utente.objects.filter(cliente_id=contesto_corrente().cliente_id).order_by("username")

    def _verifica_abilitazione(self):
        abilitazioni = Abilitazioni.objects.get()
        if self.request.user.ruolo != Ruolo.ADMIN_ASSOLUTO and not abilitazioni.admin_gestisce_utenti:
            raise PermissionDenied("La gestione utenti non è abilitata per questo cliente.")
        return abilitazioni

    def perform_create(self, serializer):
        abilitazioni = self._verifica_abilitazione()
        if self.get_queryset().count() >= abilitazioni.max_utenti:
            raise ValidationError(f"Raggiunto il numero massimo di utenti ({abilitazioni.max_utenti}).")
        utente = serializer.save(cliente_id=contesto_corrente().cliente_id)
        registra(self.request.user, "utente_creato", utente, username=utente.username, ruolo=utente.ruolo)

    def perform_update(self, serializer):
        self._verifica_abilitazione()
        utente = serializer.save()
        registra(self.request.user, "utente_modificato", utente, username=utente.username)

    def perform_destroy(self, utente):
        self._verifica_abilitazione()
        if utente.pk == self.request.user.pk:
            raise ValidationError("Non puoi eliminare il tuo stesso utente.")
        registra(self.request.user, "utente_eliminato", utente, username=utente.username)
        utente.delete()


class UtentiPiattaformaViewSet(ViewSetCliente):
    """Administrator Assoluti e tecnici di teleassistenza: li designa solo l'Administrator Assoluto."""

    ambito = "piattaforma"
    ruoli_lettura = SOLO_ASSOLUTO
    ruoli_scrittura = SOLO_ASSOLUTO
    serializer_class = UtentePiattaformaSerializer

    def get_queryset(self):
        return Utente.objects.filter(cliente__isnull=True).order_by("username")

    def perform_create(self, serializer):
        utente = serializer.save()
        registra(self.request.user, "utente_piattaforma_creato", utente, username=utente.username, ruolo=utente.ruolo)

    def perform_update(self, serializer):
        utente = serializer.save()
        registra(self.request.user, "utente_piattaforma_modificato", utente, username=utente.username)

    def perform_destroy(self, utente):
        if utente.pk == self.request.user.pk:
            raise ValidationError("Non puoi eliminare il tuo stesso utente.")
        registra(self.request.user, "utente_piattaforma_eliminato", utente, username=utente.username)
        utente.delete()
