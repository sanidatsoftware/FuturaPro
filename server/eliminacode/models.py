from django.db import models

from core.models import ModelloCliente


def numero_mostrato(totale: int, massimo: int) -> int:
    """Il numero sul biglietto e sui display: gira da 1 a ``massimo``; 0 = nessuno."""
    return (totale - 1) % massimo + 1 if totale > 0 else 0


class Reparto(ModelloCliente):
    """Un banco con la sua coda: salumeria, macelleria, gastronomia…

    I contatori sono totali della giornata e non girano mai; il numero a 1–99
    si ricava da lì. Così «clienti in coda» è una sottrazione, anche dopo il 99.
    Al primo uso di un nuovo giorno la coda riparte da zero.
    """

    sede = models.ForeignKey("clienti.Sede", on_delete=models.CASCADE, related_name="reparti")
    nome = models.CharField(max_length=60)
    colore = models.CharField(max_length=7, default="#e31b23")
    ordine = models.PositiveIntegerField(default=0)
    massimo = models.PositiveIntegerField(default=99)
    attivo = models.BooleanField(default=True)
    azzeramento_automatico = models.BooleanField(default=True)
    # Contatori della giornata.
    giornata = models.DateField(null=True, blank=True)
    chiamati = models.PositiveIntegerField(default=0)
    emessi = models.PositiveIntegerField(default=0)
    # Cambia a ogni chiamata, anche a «ripeti»: i display lampeggiano e annunciano.
    chiamato_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sede", "ordine", "nome"]
        verbose_name_plural = "reparti"
        constraints = [models.UniqueConstraint(fields=["sede", "nome"], name="reparto_nome_unico")]

    def __str__(self):
        return self.nome

    @property
    def numero(self) -> int:
        return numero_mostrato(self.chiamati, self.massimo)

    @property
    def ultimo_emesso(self) -> int:
        return numero_mostrato(self.emessi, self.massimo)

    @property
    def in_coda(self) -> int:
        return max(0, self.emessi - self.chiamati)

    def stato(self) -> dict:
        return {
            "id": str(self.id),
            "nome": self.nome,
            "colore": self.colore,
            "numero": self.numero,
            "in_coda": self.in_coda,
            "ultimo_emesso": self.ultimo_emesso,
            "chiamato_il": self.chiamato_il.isoformat() if self.chiamato_il else None,
        }


class CredenzialePulsante(models.Model):
    """Fuori dalla Row-Level Security come le credenziali dei player: dice di quale cliente è la chiave."""

    impronta_chiave = models.CharField(max_length=64, primary_key=True)
    reparto = models.OneToOneField(Reparto, on_delete=models.CASCADE, related_name="credenziale")
    cliente_id = models.UUIDField()
    creata = models.DateTimeField(auto_now_add=True)
