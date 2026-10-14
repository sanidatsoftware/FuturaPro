from django.db import models


class Aspetto(models.Model):
    """Nome e logo della piattaforma: pagina di accesso, pannello, titoli delle pagine.

    Uno solo per installazione, di nessun cliente: lo cambia l'Administrator Assoluto.
    """

    nome_app = models.CharField(max_length=60, default="FuturaPro")
    sottotitolo = models.CharField(max_length=120, default="Videocomunicazione per il punto vendita")
    colore = models.CharField(max_length=7, default="#1f4e79")
    logo = models.FileField(upload_to="piattaforma/", blank=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "aspetto"

    @classmethod
    def attuale(cls) -> "Aspetto":
        aspetto = cls.objects.order_by("id").first()
        return aspetto or cls(id=1)
