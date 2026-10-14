from django.db import transaction
from rest_framework import generics, mixins, serializers, viewsets

from audit.models import registra
from core.api import GESTIONE, SOLO_ASSOLUTO, TELEASSISTENZA, RiferimentoCliente, ViewSetCliente, VistaConContesto, sedi_visibili

from .models import Abilitazioni, Cliente, Insegna, Sede


class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ["id", "nome", "ragione_sociale", "partita_iva", "attivo", "creato"]


class ClientiViewSet(
    VistaConContesto,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Anagrafica clienti: la vede solo la piattaforma. Un cliente non si cancella, si disattiva."""

    ambito = "piattaforma"
    ruoli_lettura = TELEASSISTENZA
    ruoli_scrittura = SOLO_ASSOLUTO
    serializer_class = ClienteSerializer

    def get_queryset(self):
        return Cliente.objects.all()

    @transaction.atomic
    def perform_create(self, serializer):
        cliente = serializer.save()
        Abilitazioni.objects.create(cliente=cliente)
        registra(self.request.user, "cliente_creato", cliente, nome=cliente.nome)

    def perform_update(self, serializer):
        cliente = serializer.save()
        registra(self.request.user, "cliente_modificato", cliente, dati=self.request.data)


class AbilitazioniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Abilitazioni
        fields = ["max_monitor", "max_utenti", "spazio_mb", "admin_gestisce_utenti", "admin_gestisce_dispositivi", "admin_gestisce_layout"]


class AbilitazioniView(VistaConContesto, generics.RetrieveUpdateAPIView):
    """Cosa è concesso al cliente: l'Administrator lo legge, solo il SystemAdministrator lo cambia."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = SOLO_ASSOLUTO
    serializer_class = AbilitazioniSerializer

    def get_object(self):
        return Abilitazioni.objects.get()

    def perform_update(self, serializer):
        abilitazioni = serializer.save()
        registra(self.request.user, "abilitazioni_modificate", abilitazioni, dati=serializer.data)


class InsegnaSerializer(serializers.ModelSerializer):
    colore = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)

    class Meta:
        model = Insegna
        fields = ["id", "nome", "colore"]


class InsegneViewSet(ViewSetCliente):
    serializer_class = InsegnaSerializer

    def get_queryset(self):
        return Insegna.objects.all()

    def perform_create(self, serializer):
        registra(self.request.user, "insegna_creata", serializer.save())

    def perform_update(self, serializer):
        registra(self.request.user, "insegna_modificata", serializer.save())

    def perform_destroy(self, instance):
        registra(self.request.user, "insegna_eliminata", instance, nome=instance.nome)
        instance.delete()


class SedeSerializer(serializers.ModelSerializer):
    # Solo l'host: niente protocollo, porta o percorso (le porte del totem sono fisse).
    indirizzo_totem = serializers.RegexField(r"^[A-Za-z0-9.-]{1,100}$", required=False, allow_blank=True)
    insegna = RiferimentoCliente(Insegna, required=False, allow_null=True)

    class Meta:
        model = Sede
        fields = ["id", "nome", "indirizzo", "insegna", "indirizzo_totem"]


class SediViewSet(ViewSetCliente):
    serializer_class = SedeSerializer

    def get_queryset(self):
        sedi = Sede.objects.all()
        limitate = sedi_visibili(self.request.user)
        return sedi if limitate is None else sedi.filter(id__in=limitate)

    def perform_create(self, serializer):
        registra(self.request.user, "sede_creata", serializer.save())

    def perform_update(self, serializer):
        registra(self.request.user, "sede_modificata", serializer.save())

    def perform_destroy(self, instance):
        registra(self.request.user, "sede_eliminata", instance, nome=instance.nome)
        instance.delete()
