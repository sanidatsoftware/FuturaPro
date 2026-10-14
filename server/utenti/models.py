import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q


class Ruolo(models.TextChoices):
    ADMIN_ASSOLUTO = "admin_assoluto", "Administrator Assoluto"
    TECNICO = "tecnico", "Tecnico Teleassistenza"
    ADMIN_CLIENTE = "admin_cliente", "AdminCliente"
    USER_CLIENTE = "user_cliente", "UserCliente"


RUOLI_PIATTAFORMA = {Ruolo.ADMIN_ASSOLUTO, Ruolo.TECNICO}
RUOLI_CLIENTE = {Ruolo.ADMIN_CLIENTE, Ruolo.USER_CLIENTE}


class Utente(AbstractUser):
    """Gli utenti di piattaforma non hanno cliente; quelli di un cliente sì, sempre.

    La tabella non è sotto Row-Level Security perché il login la legge prima
    di sapere chi è l'utente: le viste la filtrano per cliente (vedi
    ``utenti.api``) e i test di isolamento lo verificano.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ruolo = models.CharField(max_length=20, choices=Ruolo.choices)
    cliente = models.ForeignKey(
        "clienti.Cliente", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # Facoltativo: un UserCliente con sedi assegnate vede solo quelle.
    sedi_consentite = models.ManyToManyField("clienti.Sede", blank=True, related_name="+")
    # Aspetto delle pagine (pannello, editor, palinsesto): «auto» segue il sistema operativo.
    tema = models.CharField(
        max_length=6, choices=[("auto", "Automatico"), ("chiaro", "Chiaro"), ("scuro", "Scuro")], default="auto"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="cliente_coerente_col_ruolo",
                condition=(
                    Q(ruolo__in=sorted(r.value for r in RUOLI_PIATTAFORMA), cliente__isnull=True)
                    | Q(ruolo__in=sorted(r.value for r in RUOLI_CLIENTE), cliente__isnull=False)
                ),
            )
        ]

    @property
    def di_piattaforma(self) -> bool:
        return self.ruolo in RUOLI_PIATTAFORMA

    @property
    def puo_teleassistenza(self) -> bool:
        return self.ruolo in RUOLI_PIATTAFORMA
