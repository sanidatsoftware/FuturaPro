import uuid

from django.db import models

from core.models import ModelloCliente


class Stato(models.TextChoices):
    RICHIESTA = "richiesta", "Richiesta"
    ATTIVA = "attiva", "Attiva"
    CHIUSA = "chiusa", "Chiusa"


class SessioneTeleassistenza(ModelloCliente):
    """Una sessione remota su un player.

    La aprono solo il SystemAdministrator e i tecnici che designa; l'Administrator
    la vede nel registro ma non può avviarla. Il collegamento vero (segnalazione
    WebRTC, relay TURN, certificati dei dispositivi) arriva nella fase dedicata:
    qui ci sono i permessi e il registro, che non cambieranno.
    """

    monitor = models.ForeignKey("dispositivi.Monitor", on_delete=models.CASCADE, related_name="sessioni")
    tecnico_id = models.UUIDField()
    tecnico = models.CharField(max_length=200)
    motivo = models.CharField(max_length=300)
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.RICHIESTA)
    iniziata = models.DateTimeField(auto_now_add=True)
    chiusa = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-iniziata"]
        verbose_name_plural = "sessioni di teleassistenza"


# --- Controllo Remoto (MeshCentral, vedi mesh.py) ----------------------------------------------
# Tabelle della piattaforma, fuori dalla Row-Level Security: il Controllo Remoto è solo di
# SystemAdministrator e Tecnici, e un PC può non essere ancora abbinato a nessuna azienda.


class ConfigurazioneRemota(models.Model):
    """Una sola riga: il gruppo dei PC in MeshCentral e le regole delle sessioni."""

    gruppo = models.CharField(max_length=200, blank=True)
    # Quanto può durare una sessione prima di chiudersi da sola nel registro (minuti).
    durata_massima = models.PositiveIntegerField(default=60)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "configurazione remota"

    @classmethod
    def attuale(cls) -> "ConfigurazioneRemota":
        return cls.objects.order_by("id").first() or cls.objects.create()


class AccountRemoto(models.Model):
    """L'account MeshCentral di un tecnico (lo crea FuturaPro; si entra solo con i suoi gettoni)."""

    utente = models.OneToOneField("utenti.Utente", on_delete=models.CASCADE, related_name="account_remoto")
    nome = models.CharField(max_length=64, unique=True)
    gruppo = models.CharField(max_length=200, blank=True)
    diritti = models.PositiveIntegerField(default=0)
    creato = models.DateTimeField(auto_now_add=True)


class SessioneRemota(models.Model):
    """Un collegamento di un tecnico allo schermo di un PC: chi, dove, quando, perché, per quanto."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nodo = models.CharField(max_length=200)
    nome_pc = models.CharField(max_length=200, blank=True)
    # Il monitor FuturaPro abbinato al PC (se c'è) e la sua azienda, al momento del collegamento.
    monitor_id = models.UUIDField(null=True, blank=True)
    nome_monitor = models.CharField(max_length=200, blank=True)
    cliente_id = models.UUIDField(null=True, blank=True)
    nome_cliente = models.CharField(max_length=200, blank=True)
    tecnico_id = models.UUIDField()
    tecnico = models.CharField(max_length=200)
    motivo = models.CharField(max_length=300)
    indirizzo_ip = models.GenericIPAddressField(null=True, blank=True)
    iniziata = models.DateTimeField(auto_now_add=True)
    chiusa = models.DateTimeField(null=True, blank=True)
    # Chiusa da chi (tecnico, altro tecnico) o «scaduta» dopo la durata massima.
    chiusa_da = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-iniziata"]
        verbose_name_plural = "sessioni remote"
