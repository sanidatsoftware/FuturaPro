from django.db import models
from django.db.models import Q

from core.models import ModelloCliente


class Orientamento(models.TextChoices):
    ORIZZONTALE = "orizzontale", "Orizzontale (16:9)"
    VERTICALE = "verticale", "Verticale (9:16, totem)"


class Layout(ModelloCliente):
    """Come si divide lo schermo: zone con slide, orologio, meteo, notizie, testi, immagini.

    Ogni cliente ha i suoi. Un monitor usa il layout che gli è assegnato; se
    non ne ha, quello predefinito del suo orientamento; se manca anche
    quello, le slide a tutto schermo.
    """

    nome = models.CharField(max_length=200)
    orientamento = models.CharField(max_length=12, choices=Orientamento.choices, default=Orientamento.ORIZZONTALE)
    sfondo = models.CharField(max_length=7, default="#000000")
    immagine_sfondo = models.ForeignKey(
        "contenuti.Contenuto", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    carattere = models.CharField(max_length=40, default="sans-serif")
    # Formato in pixel delle immagini che il cliente prepara di solito (es. volantini
    # A4 a 300 dpi: 2480×3508). L'editor lo usa per dare alle zone le stesse proporzioni.
    formato_larghezza = models.PositiveIntegerField(null=True, blank=True)
    formato_altezza = models.PositiveIntegerField(null=True, blank=True)
    predefinito = models.BooleanField(default=False)
    creato = models.DateTimeField(auto_now_add=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "layout"
        constraints = [
            models.UniqueConstraint(
                fields=["cliente", "orientamento"],
                condition=Q(predefinito=True),
                name="un_predefinito_per_orientamento",
            )
        ]

    def __str__(self):
        return self.nome


class TipoZona(models.TextChoices):
    SLIDE = "slide", "Slide"
    OROLOGIO = "orologio", "Orologio"
    METEO = "meteo", "Meteo"
    NOTIZIE = "notizie", "Notizie (rullo)"
    TESTO = "testo", "Testo"
    IMMAGINE = "immagine", "Immagine fissa"
    CODA = "coda", "Eliminacode: numeri dei reparti"
    PRENDI_NUMERO = "prendi_numero", "Eliminacode: prendi il numero (totem touch)"


class Zona(ModelloCliente):
    """Un rettangolo del layout, in percentuale dello schermo: vale per ogni risoluzione.

    ``configurazione`` dipende dal tipo ed è validata in ``layout.zone``.
    """

    layout = models.ForeignKey(Layout, on_delete=models.CASCADE, related_name="zone")
    tipo = models.CharField(max_length=20, choices=TipoZona.choices)
    nome = models.CharField(max_length=100, blank=True)
    x = models.FloatField()
    y = models.FloatField()
    larghezza = models.FloatField()
    altezza = models.FloatField()
    livello = models.PositiveIntegerField(default=0)
    configurazione = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["layout", "livello", "id"]
        verbose_name_plural = "zone"
