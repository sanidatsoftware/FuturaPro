"""Fotografie dello schermo: il pannello le chiede, il player le scatta e le manda.

La richiesta è un'ora sul monitor: il player la vede alla sua domanda successiva,
ogni pochi secondi, e vale due minuti. L'ultima fotografia di ogni monitor sta nei
file del suo cliente e sostituisce la precedente.
"""

from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

VALIDITA_RICHIESTA = timedelta(minutes=2)
MASSIMO_BYTE = 3 * 1024 * 1024


def percorso(monitor) -> str:
    return f"clienti/{monitor.cliente_id}/schermate/{monitor.id}.jpg"


def richiedi(monitor) -> None:
    monitor.schermata_richiesta = timezone.now()
    monitor.save(update_fields=["schermata_richiesta"])


def richiesta(monitor) -> bool:
    """C'è una richiesta recente a cui il player non ha ancora risposto?"""
    chiesta = monitor.schermata_richiesta
    if chiesta is None or timezone.now() - chiesta > VALIDITA_RICHIESTA:
        return False
    return monitor.schermata_il is None or monitor.schermata_il < chiesta


def salva(monitor, dati: bytes) -> None:
    nome = percorso(monitor)
    if default_storage.exists(nome):
        default_storage.delete(nome)
    default_storage.save(nome, ContentFile(dati))
    monitor.schermata_il = timezone.now()
    monitor.save(update_fields=["schermata_il"])
