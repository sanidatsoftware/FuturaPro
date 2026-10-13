import hashlib
import secrets
import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.models import ModelloCliente

ONLINE_ENTRO = timedelta(minutes=2)
DURATA_CODICE = timedelta(minutes=15)


def impronta(token: str) -> str:
    # I token sono 32 byte casuali: basta SHA-256, non serve un hash lento.
    return hashlib.sha256(token.encode()).hexdigest()


class Piattaforma(models.TextChoices):
    WINDOWS = "windows", "Windows"
    ANDROID = "android", "Android"


class GruppoMonitor(ModelloCliente):
    nome = models.CharField(max_length=200)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "gruppi di monitor"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="gruppo_nome_unico")]

    def __str__(self):
        return self.nome


class Monitor(ModelloCliente):
    nome = models.CharField(max_length=200)
    sede = models.ForeignKey("clienti.Sede", on_delete=models.PROTECT, related_name="monitor")
    gruppi = models.ManyToManyField(GruppoMonitor, blank=True, related_name="monitor")
    piattaforma = models.CharField(max_length=10, choices=Piattaforma.choices)
    versione_player = models.CharField(max_length=40, blank=True)
    info_dispositivo = models.JSONField(default=dict, blank=True)
    ultimo_contatto = models.DateTimeField(null=True, blank=True)
    abbinato_il = models.DateTimeField(auto_now_add=True)
    orientamento = models.CharField(
        max_length=12, choices=[("orizzontale", "Orizzontale"), ("verticale", "Verticale (totem)")], default="orizzontale"
    )
    # Quanto il player deve ruotare l'immagine: serve quando un televisore orizzontale
    # è montato in verticale; un totem nativo verticale resta a 0.
    rotazione = models.PositiveSmallIntegerField(choices=[(0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")], default=0)
    # Vuoto: il layout predefinito del cliente per il suo orientamento.
    layout = models.ForeignKey("layout.Layout", on_delete=models.SET_NULL, null=True, blank=True, related_name="monitor")

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "monitor"

    def __str__(self):
        return self.nome

    @property
    def online(self) -> bool:
        return self.ultimo_contatto is not None and timezone.now() - self.ultimo_contatto < ONLINE_ENTRO


class RichiestaAbbinamento(models.Model):
    """Un player appena installato che mostra il suo codice e aspetta di essere abbinato.

    Non appartiene ancora a nessun cliente, quindi non è sotto Row-Level
    Security. Il player genera da sé il proprio token e ne manda una copia una
    volta sola: qui resta soltanto l'impronta.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codice = models.CharField(max_length=6, unique=True)
    impronta_token = models.CharField(max_length=64, unique=True)
    piattaforma = models.CharField(max_length=10, choices=Piattaforma.choices)
    info_dispositivo = models.JSONField(default=dict, blank=True)
    creata = models.DateTimeField(auto_now_add=True)
    scade = models.DateTimeField()

    @classmethod
    def nuova(cls, token: str, piattaforma: str, info: dict) -> "RichiestaAbbinamento":
        cls.objects.filter(scade__lt=timezone.now()).delete()
        while True:
            codice = f"{secrets.randbelow(1_000_000):06d}"
            if not cls.objects.filter(codice=codice).exists():
                break
        return cls.objects.create(
            codice=codice,
            impronta_token=impronta(token),
            piattaforma=piattaforma,
            info_dispositivo=info,
            scade=timezone.now() + DURATA_CODICE,
        )

    @property
    def scaduta(self) -> bool:
        return timezone.now() >= self.scade


class CredenzialeDispositivo(models.Model):
    """Chi è il player che si presenta con un certo token, e di quale cliente è.

    Sta fuori dalla Row-Level Security perché va letta prima di conoscere il
    cliente: è proprio lei a dirlo. Contiene solo impronte, mai i token.
    """

    impronta_token = models.CharField(max_length=64, primary_key=True)
    monitor = models.OneToOneField(Monitor, on_delete=models.CASCADE, related_name="credenziale")
    cliente_id = models.UUIDField()
    revocata = models.BooleanField(default=False)
    creata = models.DateTimeField(auto_now_add=True)
