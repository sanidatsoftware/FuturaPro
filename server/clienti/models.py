import uuid

from django.db import models

from core.contesto import contesto_corrente
from core.models import ModelloCliente


class GestoreClienti(models.Manager):
    def get_queryset(self):
        queryset = super().get_queryset()
        contesto = contesto_corrente()
        if contesto.piattaforma:
            return queryset
        return queryset.filter(id=contesto.cliente_id)


class Cliente(models.Model):
    """Un'azienda cliente. Vede soltanto se stessa, anche a livello di database."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=200)
    ragione_sociale = models.CharField(max_length=200, blank=True)
    partita_iva = models.CharField(max_length=20, blank=True)
    attivo = models.BooleanField(default=True)
    creato = models.DateTimeField(auto_now_add=True)

    objects = GestoreClienti()

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "clienti"

    def __str__(self):
        return self.nome


class Abilitazioni(ModelloCliente):
    """Cosa l'Administrator Assoluto concede al cliente.

    L'AdminCliente la legge ma non la modifica: amministra il proprio parco
    dentro questi limiti.
    """

    max_monitor = models.PositiveIntegerField(default=10)
    max_utenti = models.PositiveIntegerField(default=5)
    spazio_mb = models.PositiveIntegerField(default=10_240)
    admin_gestisce_utenti = models.BooleanField(
        default=True, help_text="L'AdminCliente può creare e modificare gli utenti del cliente."
    )
    admin_gestisce_dispositivi = models.BooleanField(
        default=True, help_text="L'AdminCliente può abbinare, rinominare e rimuovere monitor."
    )
    admin_gestisce_layout = models.BooleanField(
        default=True, help_text="L'AdminCliente può creare e modificare i layout grafici."
    )

    class Meta:
        verbose_name_plural = "abilitazioni"
        constraints = [models.UniqueConstraint(fields=["cliente"], name="abilitazioni_una_per_cliente")]


class Insegna(ModelloCliente):
    """Il marchio con cui si presenta un negozio: un'azienda può averne più d'uno
    (es. «Insegna A» e «Insegna B»). Facoltativa: serve a pubblicare per insegna."""

    nome = models.CharField(max_length=100)
    colore = models.CharField(max_length=7, default="#ec6a1f")

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "insegne"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="insegna_nome_unico")]

    def __str__(self):
        return self.nome


class Sede(ModelloCliente):
    nome = models.CharField(max_length=200)
    indirizzo = models.CharField(max_length=300, blank=True)
    insegna = models.ForeignKey(Insegna, on_delete=models.SET_NULL, null=True, blank=True, related_name="sedi")
    # IP (o nome) in rete locale del totem che gestisce le code del negozio. Se c'è,
    # numeri e biglietti li tiene il totem e il negozio va avanti anche senza server
    # centrale; se manca, le code le tiene il server.
    indirizzo_totem = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "sedi"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="sede_nome_unico")]

    def __str__(self):
        return self.nome
