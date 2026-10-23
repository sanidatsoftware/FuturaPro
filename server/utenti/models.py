import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q


class Ruolo(models.TextChoices):
    ADMIN_ASSOLUTO = "admin_assoluto", "SystemAdministrator"
    TECNICO = "tecnico", "Tecnico Teleassistenza"
    ADMIN_CLIENTE = "admin_cliente", "Administrator"
    USER_CLIENTE = "user_cliente", "User"


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
    # Facoltativo: un User con sedi assegnate vede solo quelle.
    sedi_consentite = models.ManyToManyField("clienti.Sede", blank=True, related_name="+")
    # Aspetto delle pagine (pannello, editor, palinsesto): «auto» segue il sistema operativo.
    tema = models.CharField(
        max_length=6, choices=[("auto", "Automatico"), ("chiaro", "Chiaro"), ("scuro", "Scuro")], default="auto"
    )
    # La pagina che si apre dopo l'accesso (una voce del menu); vuota: quella del ruolo.
    pagina_iniziale = models.CharField(max_length=30, blank=True)
    # Verifica in due passaggi (utenti.doppio): il segreto cifrato, se è attiva, e l'ultimo codice
    # usato (un codice non vale due volte). Obbligatoria per il Controllo Remoto.
    doppio_segreto = models.TextField(blank=True)
    doppio_attivo = models.BooleanField(default=False)
    doppio_ultimo_passo = models.BigIntegerField(default=0)

    @property
    def apertura(self) -> str:
        """La voce del menu da aprire dopo l'accesso: la scelta nel Profilo, o quella del ruolo.
        SystemAdministrator e Administrator: la «Panoramica», il colpo d'occhio su schermi,
        contenuti, palinsesto, code e le cose da guardare; Tecnico: «Stato e allarmi»; User: la
        Creazione palinsesto, dove lavora."""
        if self.pagina_iniziale:
            return self.pagina_iniziale
        return {Ruolo.TECNICO: "stato", Ruolo.USER_CLIENTE: "palinsesto"}.get(self.ruolo, "panoramica")

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
