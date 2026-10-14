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
