import uuid

from django.db import models

from core.contesto import contesto_attivo, contesto_corrente


class GestoreAudit(models.Manager):
    def get_queryset(self):
        queryset = super().get_queryset()
        contesto = contesto_corrente()
        if contesto.piattaforma:
            return queryset
        return queryset.filter(cliente_id=contesto.cliente_id)


class EventoAudit(models.Model):
    """Una riga del registro: si aggiunge e basta.

    Un trigger in PostgreSQL rifiuta UPDATE e DELETE. L'utente è salvato come
    identificativo e descrizione, non come chiave esterna, così cancellare un
    utente non riscrive il registro. Gli eventi di piattaforma hanno
    ``cliente`` vuoto e li vede solo la piattaforma.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cliente = models.ForeignKey(
        "clienti.Cliente", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quando = models.DateTimeField(auto_now_add=True)
    utente_id = models.UUIDField(null=True, blank=True)
    utente = models.CharField(max_length=200, blank=True)
    ruolo = models.CharField(max_length=20, blank=True)
    # Un utente di piattaforma ha agito sui dati di questo cliente.
    per_conto_piattaforma = models.BooleanField(default=False)
    azione = models.CharField(max_length=60)
    oggetto_tipo = models.CharField(max_length=60, blank=True)
    oggetto_id = models.CharField(max_length=64, blank=True)
    dettagli = models.JSONField(default=dict, blank=True)

    objects = GestoreAudit()

    class Meta:
        ordering = ["-quando"]
        verbose_name_plural = "eventi di audit"


def registra(utente, azione: str, oggetto=None, **dettagli) -> EventoAudit:
    contesto = contesto_attivo()
    cliente_id = contesto.cliente_id if contesto else None
    di_piattaforma = bool(utente and getattr(utente, "di_piattaforma", False))
    return EventoAudit.objects.create(
        cliente_id=cliente_id,
        utente_id=getattr(utente, "id", None),
        utente=getattr(utente, "username", "") or "",
        ruolo=getattr(utente, "ruolo", "") or "",
        per_conto_piattaforma=di_piattaforma and cliente_id is not None,
        azione=azione,
        oggetto_tipo=type(oggetto).__name__ if oggetto is not None else "",
        oggetto_id=str(getattr(oggetto, "pk", "") or ""),
        dettagli=dettagli,
    )
