"""La stampante dei biglietti di ogni totem.

Il layout (zona «prendi il numero») dà le impostazioni di partenza; ogni totem può avere le
sue (``Monitor.stampante``), perché lo stesso layout gira in negozi con stampanti diverse.
La stampa di prova la fa il totem stesso: il server non vede la rete del negozio. La
richiesta è un'ora sul monitor, come per le fotografie dello schermo, e vale due minuti.
"""

from datetime import timedelta

from django.utils import timezone

from layout.manifest import layout_del_monitor
from layout.models import TipoZona

CAMPI = ("stampa", "stampante", "intestazione", "messaggio")
VALIDITA_PROVA = timedelta(minutes=2)


def zone_del_totem(monitor):
    layout = layout_del_monitor(monitor)
    if layout is None:
        return []
    return list(layout.zone.filter(tipo=TipoZona.PRENDI_NUMERO).order_by("livello", "id"))


def dal_layout(zone) -> dict:
    configurazione = zone[0].configurazione if zone else {}
    return {campo: configurazione.get(campo, "") for campo in CAMPI}


def applica(monitor, configurazione: dict) -> dict:
    """La configurazione della zona con le impostazioni del totem sopra (se ne ha)."""
    proprie = monitor.stampante or {}
    if not proprie:
        return configurazione
    return {**configurazione, **{campo: proprie[campo] for campo in CAMPI if campo in proprie}}


def richiedi_prova(monitor) -> None:
    monitor.prova_stampa_richiesta = timezone.now()
    monitor.prova_stampa_esito = {}
    monitor.save(update_fields=["prova_stampa_richiesta", "prova_stampa_esito"])


def prova_in_attesa(monitor) -> bool:
    chiesta = monitor.prova_stampa_richiesta
    if chiesta is None or timezone.now() - chiesta > VALIDITA_PROVA:
        return False
    return not monitor.prova_stampa_esito


def salva_esito(monitor, ok: bool, messaggio: str) -> None:
    monitor.prova_stampa_esito = {"ok": ok, "messaggio": messaggio[:300], "quando": timezone.now().isoformat()}
    monitor.save(update_fields=["prova_stampa_esito"])


def stato_prova(monitor) -> dict:
    if prova_in_attesa(monitor):
        return {"stato": "in_attesa", "chiesta": monitor.prova_stampa_richiesta}
    esito = monitor.prova_stampa_esito or {}
    if esito:
        return {"stato": "riuscita" if esito.get("ok") else "fallita", **esito}
    if monitor.prova_stampa_richiesta:
        return {"stato": "senza_risposta", "chiesta": monitor.prova_stampa_richiesta}
    return {"stato": "mai"}
