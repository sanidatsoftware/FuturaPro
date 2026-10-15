import re

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as ErroreDjango
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import registra
from futurapro.versione import versione as versione_app
from clienti.models import Abilitazioni, Sede
from core.api import GESTIONE, SOLO_ASSOLUTO, RiferimentoCliente, ViewSetCliente
from core.contesto import contesto_cliente, contesto_corrente, contesto_piattaforma

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


def _registra_profilo(utente, azione, **dettagli):
    """Il profilo non ha un cliente scelto: l'evento va nel registro dell'azienda dell'utente
    (o in quello della piattaforma)."""
    with (contesto_cliente(utente.cliente_id) if utente.cliente_id else contesto_piattaforma()):
        registra(utente, azione, utente, **dettagli)


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
                "tema": utente.tema,
                "first_name": utente.first_name,
                "last_name": utente.last_name,
                "email": utente.email,
                "pagina_iniziale": utente.pagina_iniziale,
                "versione_app": versione_app(),
                "apertura": utente.apertura,
            }
        )

    def patch(self, request):
        """Il profilo personale: aspetto delle pagine, nome utente, nome e cognome, email e password.
        Per cambiare nome utente o password serve la password attuale."""
        utente = request.user
        dati = request.data
        campi = []
        if "tema" in dati:
            if dati["tema"] not in ("auto", "chiaro", "scuro"):
                raise ValidationError({"tema": "Scegli auto, chiaro o scuro."})
            utente.tema = dati["tema"]
            campi.append("tema")
        if "pagina_iniziale" in dati:
            pagina = str(dati["pagina_iniziale"] or "")
            if pagina and not re.fullmatch(r"[a-z_]{1,30}", pagina):
                raise ValidationError({"pagina_iniziale": "Pagina non valida."})
            utente.pagina_iniziale = pagina
            campi.append("pagina_iniziale")
        for campo, massimo in (("first_name", 150), ("last_name", 150)):
            if campo in dati:
                setattr(utente, campo, str(dati[campo] or "").strip()[:massimo])
                campi.append(campo)
        if "email" in dati:
            email = str(dati["email"] or "").strip()
            if email:
                try:
                    serializers.EmailField().run_validation(email)
                except serializers.ValidationError:
                    raise ValidationError({"email": "Indirizzo email non valido."})
            utente.email = email
            campi.append("email")
        nuovo_nome = str(dati.get("username") or "").strip()
        nuova_password = dati.get("password") or ""
        if (nuovo_nome and nuovo_nome != utente.username) or nuova_password:
            if not utente.check_password(str(dati.get("password_attuale") or "")):
                raise ValidationError({"password_attuale": "La password attuale non è corretta."})
        if nuovo_nome and nuovo_nome != utente.username:
            campo = Utente._meta.get_field("username")
            try:
                campo.run_validators(nuovo_nome)
            except ErroreDjango as errore:
                raise ValidationError({"username": errore.messages})
            if len(nuovo_nome) > campo.max_length:
                raise ValidationError({"username": f"Al massimo {campo.max_length} caratteri."})
            if Utente.objects.filter(username__iexact=nuovo_nome).exclude(pk=utente.pk).exists():
                raise ValidationError({"username": "Questo nome utente è già usato."})
            _registra_profilo(utente, "nome_utente_cambiato", da=utente.username, a=nuovo_nome)
            utente.username = nuovo_nome
            campi.append("username")
        if nuova_password:
            if len(nuova_password) < 10:
                raise ValidationError({"password": "Almeno 10 caratteri."})
            try:
                password_validation.validate_password(nuova_password, utente)
            except ErroreDjango as errore:
                raise ValidationError({"password": errore.messages})
            utente.set_password(nuova_password)
            campi.append("password")
        if campi:
            utente.save(update_fields=campi)
        if "password" in campi:
            update_session_auth_hash(request, utente)  # resta collegato con la password nuova
            _registra_profilo(utente, "password_cambiata", username=utente.username)
        return self.get(request)


class UtentiClienteViewSet(ViewSetCliente):
    """Gli utenti di un cliente. L'Administrator li gestisce solo se il SystemAdministrator lo consente."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = GESTIONE
    serializer_class = UtenteClienteSerializer

    def get_queryset(self):
        return Utente.objects.filter(cliente_id=contesto_corrente().cliente_id).order_by("username")

    def _verifica_ruolo(self, utente=None, ruolo=None):
        """Solo il SystemAdministrator crea e gestisce gli Administrator; l'Administrator
        gestisce gli User della sua azienda (e sé stesso dal Profilo)."""
        if self.request.user.ruolo == Ruolo.ADMIN_ASSOLUTO:
            return
        if ruolo == Ruolo.ADMIN_CLIENTE or (utente is not None and utente.ruolo == Ruolo.ADMIN_CLIENTE):
            raise PermissionDenied("Solo il SystemAdministrator crea e gestisce gli Administrator.")

    def _verifica_abilitazione(self):
        abilitazioni = Abilitazioni.objects.get()
        if self.request.user.ruolo != Ruolo.ADMIN_ASSOLUTO and not abilitazioni.admin_gestisce_utenti:
            raise PermissionDenied("La gestione utenti non è abilitata per questo cliente.")
        return abilitazioni

    def perform_create(self, serializer):
        abilitazioni = self._verifica_abilitazione()
        self._verifica_ruolo(ruolo=serializer.validated_data.get("ruolo"))
        if self.get_queryset().count() >= abilitazioni.max_utenti:
            raise ValidationError(f"Raggiunto il numero massimo di utenti ({abilitazioni.max_utenti}).")
        utente = serializer.save(cliente_id=contesto_corrente().cliente_id)
        registra(self.request.user, "utente_creato", utente, username=utente.username, ruolo=utente.ruolo)

    def perform_update(self, serializer):
        self._verifica_abilitazione()
        self._verifica_ruolo(serializer.instance, serializer.validated_data.get("ruolo"))
        utente = serializer.save()
        registra(self.request.user, "utente_modificato", utente, username=utente.username)

    def perform_destroy(self, utente):
        self._verifica_abilitazione()
        self._verifica_ruolo(utente)
        if utente.pk == self.request.user.pk:
            raise ValidationError("Non puoi eliminare il tuo stesso utente.")
        registra(self.request.user, "utente_eliminato", utente, username=utente.username)
        utente.delete()


class UtentiPiattaformaViewSet(ViewSetCliente):
    """SystemAdministrator e tecnici di teleassistenza: li designa solo il SystemAdministrator."""

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
        utente = serializer.instance
        if utente.pk == self.request.user.pk and (
            serializer.validated_data.get("is_active") is False
            or serializer.validated_data.get("ruolo", utente.ruolo) != utente.ruolo
        ):
            raise ValidationError("Non puoi disattivare il tuo utente né cambiarne il ruolo.")
        utente = serializer.save()
        registra(self.request.user, "utente_piattaforma_modificato", utente, username=utente.username)

    def perform_destroy(self, utente):
        if utente.pk == self.request.user.pk:
            raise ValidationError("Non puoi eliminare il tuo stesso utente.")
        registra(self.request.user, "utente_piattaforma_eliminato", utente, username=utente.username)
        utente.delete()
