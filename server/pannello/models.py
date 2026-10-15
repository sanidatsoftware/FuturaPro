from django.db import models

from core.models import ModelloCliente


class Aspetto(models.Model):
    """Nome e logo della piattaforma: pagina di accesso, pannello, titoli delle pagine.

    Uno solo per installazione, di nessun cliente: lo cambia il SystemAdministrator.
    """

    nome_app = models.CharField(max_length=60, default="FuturaPro")
    sottotitolo = models.CharField(max_length=120, default="Videocomunicazione per il punto vendita")
    colore = models.CharField(max_length=7, default="#1f4e79")
    logo = models.FileField(upload_to="piattaforma/", blank=True)
    # L'icona: barra del pannello e scheda del browser (.ico, oppure PNG/WebP quadrato). Il logo
    # resta per la pagina di accesso; senza icona la barra mostra il logo.
    icona = models.FileField(upload_to="piattaforma/", blank=True)
    # La pagina di accesso composta (posizione e grandezza del logo, righe di testo): vedi «accesso».
    accesso = models.JSONField(default=dict, blank=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "aspetto"

    @classmethod
    def attuale(cls) -> "Aspetto":
        aspetto = cls.objects.order_by("id").first()
        return aspetto or cls(id=1)


class ImpostazioniEmail(ModelloCliente):
    """Il server email (SMTP) e il mittente dell'azienda: ognuna ha il suo dominio e la sua
    casella. Lo imposta chi gestisce il cliente; vale per tutte le sue email (allarmi, rapporti…),
    mentre i destinatari li sceglie ogni funzione. Senza, valgono (se ci sono) le variabili
    FUTURAPRO_EMAIL_… del server."""

    class Sicurezza(models.TextChoices):
        STARTTLS = "starttls", "STARTTLS (di solito porta 587)"
        SSL = "ssl", "SSL/TLS (di solito porta 465)"
        NESSUNA = "nessuna", "Nessuna (sconsigliato)"

    attivo = models.BooleanField(default=False)
    host = models.CharField(max_length=200, blank=True)
    porta = models.PositiveIntegerField(default=587)
    sicurezza = models.CharField(max_length=10, choices=Sicurezza.choices, default=Sicurezza.STARTTLS)
    utente = models.CharField(max_length=200, blank=True)
    # Cifrata con una chiave derivata da SECRET_KEY: non si legge dal database né dall'API.
    password_cifrata = models.TextField(blank=True)
    mittente = models.CharField(max_length=200, blank=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "impostazioni email"
        constraints = [models.UniqueConstraint(fields=["cliente"], name="email_una_per_cliente")]


class InvioRapporto(ModelloCliente):
    """Un rapporto mandato da solo per email (facoltativo), con i suoi destinatari.

    Esempi: la messa in onda della settimana al fornitore, i tempi d'attesa del mese ai
    responsabili, la disponibilità degli schermi al tecnico. Il server email è quello generale.
    """

    class Tipo(models.TextChoices):
        MESSA_IN_ONDA = "messa_in_onda", "Messa in onda"
        ATTESE = "attese", "Tempi d'attesa"
        SCHERMI = "schermi", "Disponibilità degli schermi"

    class Frequenza(models.TextChoices):
        GIORNALIERA = "giornaliera", "Ogni mattina (il giorno prima)"
        SETTIMANALE = "settimanale", "Ogni lunedì (la settimana prima)"
        MENSILE = "mensile", "Il primo del mese (il mese prima)"

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    nome = models.CharField(max_length=120)
    attivo = models.BooleanField(default=True)
    email = models.JSONField(default=list)
    frequenza = models.CharField(max_length=12, choices=Frequenza.choices, default=Frequenza.SETTIMANALE)
    # Filtri del rapporto, es. {"raggruppa": "sede", "fornitore": "…"} per la messa in onda.
    filtri = models.JSONField(default=dict, blank=True)
    # L'ultimo periodo mandato (es. «2026-W41»): ogni periodo parte una volta sola.
    ultimo_periodo = models.CharField(max_length=20, blank=True)
    ultimo_invio = models.DateTimeField(null=True, blank=True)
    ultimo_errore = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["tipo", "nome"]
        verbose_name_plural = "invii dei rapporti"
