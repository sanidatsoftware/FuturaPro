import uuid

from django.db import models

from .contesto import contesto_corrente


class GestoreCliente(models.Manager):
    """Restituisce solo le righe del cliente del contesto; senza contesto si rifiuta."""

    def get_queryset(self):
        queryset = super().get_queryset()
        contesto = contesto_corrente()
        if contesto.piattaforma:
            return queryset
        return queryset.filter(cliente_id=contesto.cliente_id)


class ModelloCliente(models.Model):
    """Base di ogni dato che appartiene a un cliente.

    La tabella va protetta anche con Row-Level Security: ogni migrazione che
    la crea aggiunge ``core.rls.proteggi(...)``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cliente = models.ForeignKey("clienti.Cliente", on_delete=models.CASCADE, editable=False)

    objects = GestoreCliente()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        contesto = contesto_corrente()
        if not contesto.piattaforma:
            if self.cliente_id is None:
                self.cliente_id = contesto.cliente_id
            elif self.cliente_id != contesto.cliente_id:
                raise PermissionError("Il dato appartiene a un altro cliente.")
        super().save(*args, **kwargs)
