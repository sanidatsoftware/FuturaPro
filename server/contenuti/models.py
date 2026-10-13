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
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creato"]
        verbose_name_plural = "contenuti"

    def __str__(self):
        return self.nome

    def delete(self, *args, **kwargs):
        file = self.file
        risultato = super().delete(*args, **kwargs)
        if file:
            # Il file sparisce solo se la cancellazione nel database va a buon fine.
            transaction.on_commit(lambda: file.storage.delete(file.name))
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
