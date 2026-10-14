from pathlib import Path

from django.db import models, transaction

from core.models import ModelloCliente

DURATA_IMMAGINE = 10  # secondi, se non indicata


class Tipo(models.TextChoices):
    IMMAGINE = "immagine", "Immagine"
    VIDEO = "video", "Video"
    WEB = "web", "Pagina web"


def percorso_file(contenuto, nome_originale):
    # Un percorso per cliente, e un nome che non dipende da quello caricato.
    if contenuto.cliente_id is None:
        raise ValueError("Il contenuto non ha ancora un cliente: il file finirebbe fuori dalla sua cartella.")
    return f"clienti/{contenuto.cliente_id}/contenuti/{contenuto.id}{Path(nome_originale).suffix.lower()}"


class Contenuto(ModelloCliente):
    nome = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    file = models.FileField(upload_to=percorso_file, blank=True)
    url = models.URLField(blank=True, help_text="Solo per le pagine web.")
    mime = models.CharField(max_length=100, blank=True)
    dimensione = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    # Vuota: le immagini restano DURATA_IMMAGINE secondi, i video vanno fino alla fine.
    durata = models.PositiveIntegerField(null=True, blank=True)
    caricato_da = models.CharField(max_length=150, blank=True)
    # Misure in pixel: le immagini le legge il server, i video le manda il pannello.
    larghezza = models.PositiveIntegerField(null=True, blank=True)
    altezza = models.PositiveIntegerField(null=True, blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creato"]
        verbose_name_plural = "contenuti"

    def __str__(self):
        return self.nome

    @property
    def orientamento(self) -> str | None:
        """«verticale» per i totem, «orizzontale» per i monitor; None se le misure mancano."""
        if not self.larghezza or not self.altezza:
            return None
        return "verticale" if self.altezza > self.larghezza else "orizzontale"

    @property
    def percorso_miniatura(self) -> str:
        return f"clienti/{self.cliente_id}/miniature/{self.id}.jpg"

    def delete(self, *args, **kwargs):
        file = self.file
        miniatura = self.percorso_miniatura
        risultato = super().delete(*args, **kwargs)
        if file:
            # Il file sparisce solo se la cancellazione nel database va a buon fine.
            def cancella():
                file.storage.delete(file.name)
                file.storage.delete(miniatura)

            transaction.on_commit(cancella)
        return risultato


class Playlist(ModelloCliente):
    nome = models.CharField(max_length=200)
    descrizione = models.CharField(max_length=500, blank=True)
    creata = models.DateTimeField(auto_now_add=True)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "playlist"

    def __str__(self):
        return self.nome


class ElementoPlaylist(ModelloCliente):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="elementi")
    contenuto = models.ForeignKey(Contenuto, on_delete=models.CASCADE, related_name="+")
    ordine = models.PositiveIntegerField()
    # Vuota: vale la durata del contenuto.
    durata = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["playlist", "ordine"]


class Orientamento(models.TextChoices):
    ORIZZONTALE = "orizzontale", "Monitor (orizzontale)"
    VERTICALE = "verticale", "Totem (verticale)"


class Campagna(ModelloCliente):
    """Un insieme di promozioni (es. «Autunno 2026» con i volantini di ottobre e novembre).

    Tiene ciò che le promozioni hanno in comune: destinatari, colore, priorità e
    secondi per immagine. Le date sono di ogni promozione.
    """

    nome = models.CharField(max_length=200)
    codice = models.CharField(max_length=50, blank=True, help_text="Riferimento interno.")
    colore = models.CharField(max_length=7, default="#3d6fb6")
    note = models.CharField(max_length=500, blank=True)
    priorita = models.IntegerField(default=0)
    # Secondi per ogni immagine; i video vanno fino alla fine.
    durata = models.PositiveIntegerField(null=True, blank=True)
    insegne = models.ManyToManyField("clienti.Insegna", blank=True, related_name="campagne")
    gruppi = models.ManyToManyField("dispositivi.GruppoMonitor", blank=True, related_name="campagne")
    monitor = models.ManyToManyField("dispositivi.Monitor", blank=True, related_name="campagne")
    creata = models.DateTimeField(auto_now_add=True)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "campagne"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="campagna_nome_unico")]

    def __str__(self):
        return self.nome


class Promozione(ModelloCliente):
    """Una promozione di una campagna (es. «Volantino 6-19 ottobre»): le sue date e le sue immagini.

    Diventa una pubblicazione per orientamento: le immagini verticali vanno ai totem,
    quelle orizzontali ai monitor (``contenuti.campagne``).
    """

    campagna = models.ForeignKey(Campagna, on_delete=models.CASCADE, related_name="promozioni")
    nome = models.CharField(max_length=200)
    data_inizio = models.DateField(null=True, blank=True)
    data_fine = models.DateField(null=True, blank=True)
    ora_inizio = models.TimeField(null=True, blank=True)
    ora_fine = models.TimeField(null=True, blank=True)
    giorni = models.JSONField(default=list, blank=True)
    contenuti = models.ManyToManyField(Contenuto, through="ContenutoPromozione", blank=True, related_name="promozioni")
    creata = models.DateTimeField(auto_now_add=True)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_inizio", "nome"]
        verbose_name_plural = "promozioni"
        constraints = [models.UniqueConstraint(fields=["campagna", "nome"], name="promozione_nome_unico")]

    def __str__(self):
        return self.nome


class ContenutoPromozione(ModelloCliente):
    promozione = models.ForeignKey(Promozione, on_delete=models.CASCADE, related_name="voci")
    contenuto = models.ForeignKey(Contenuto, on_delete=models.CASCADE, related_name="+")
    ordine = models.PositiveIntegerField()

    class Meta:
        ordering = ["promozione", "ordine"]


class Pubblicazione(ModelloCliente):
    """Una playlist pubblicata su certi monitor, con le sue regole di calendario.

    Le regole vanno tutte al player, che le valuta da solo: così continua a
    seguire il palinsesto anche quando la rete manca. ``contenuti.palinsesto``
    le valuta allo stesso modo per l'anteprima nel pannello.
    """

    nome = models.CharField(max_length=200)
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="pubblicazioni")
    monitor = models.ManyToManyField("dispositivi.Monitor", blank=True, related_name="pubblicazioni")
    gruppi = models.ManyToManyField("dispositivi.GruppoMonitor", blank=True, related_name="pubblicazioni")
    # Tutti i monitor delle sedi di queste insegne.
    insegne = models.ManyToManyField("clienti.Insegna", blank=True, related_name="pubblicazioni")
    # Vuoto: tutti i destinatari; altrimenti solo i monitor di questo orientamento.
    orientamento = models.CharField(max_length=12, choices=Orientamento.choices, blank=True)
    # Le pubblicazioni di una promozione le crea e aggiorna la promozione stessa.
    promozione = models.ForeignKey(Promozione, on_delete=models.CASCADE, null=True, blank=True, related_name="pubblicazioni")
    data_inizio = models.DateField(null=True, blank=True)
    data_fine = models.DateField(null=True, blank=True)
    ora_inizio = models.TimeField(null=True, blank=True)
    ora_fine = models.TimeField(null=True, blank=True)
    # 0 = lunedì … 6 = domenica; vuoto = tutti i giorni.
    giorni = models.JSONField(default=list, blank=True)
    priorita = models.IntegerField(default=0)
    attiva = models.BooleanField(default=True)
    creata = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priorita", "creata"]
        verbose_name_plural = "pubblicazioni"

    def __str__(self):
        return self.nome
