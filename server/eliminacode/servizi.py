"""Le operazioni sulla coda. Ognuna blocca la riga del reparto: due banchi o due
totem che premono insieme non ottengono mai lo stesso numero."""

from django.db import transaction
from django.utils import timezone

from .models import Reparto


class RepartoChiuso(Exception):
    pass


def _bloccato(reparto_id) -> Reparto:
    reparto = Reparto.objects.select_for_update().get(id=reparto_id)
    oggi = timezone.localdate()
    if reparto.azzeramento_automatico and reparto.giornata != oggi:
        reparto.chiamati = reparto.emessi = 0
        reparto.chiamato_il = None
        reparto.giornata = oggi
    return reparto


def _salva(reparto, chiamata=False) -> Reparto:
    if chiamata:
        reparto.chiamato_il = timezone.now()
    reparto.save(update_fields=["giornata", "chiamati", "emessi", "chiamato_il"])
    return reparto


@transaction.atomic
def avanti(reparto_id) -> Reparto:
    # Come nel sistema attuale si può avanzare anche senza biglietti emessi:
    # molti negozi non hanno il totem e i numeri arrivano da un distributore a rotolo.
    reparto = _bloccato(reparto_id)
    reparto.chiamati += 1
    return _salva(reparto, chiamata=True)


@transaction.atomic
def indietro(reparto_id) -> Reparto:
    reparto = _bloccato(reparto_id)
    reparto.chiamati = max(0, reparto.chiamati - 1)
    return _salva(reparto, chiamata=True)


@transaction.atomic
def ripeti(reparto_id) -> Reparto:
    return _salva(_bloccato(reparto_id), chiamata=True)


@transaction.atomic
def azzera(reparto_id) -> Reparto:
    reparto = _bloccato(reparto_id)
    reparto.chiamati = reparto.emessi = 0
    reparto.chiamato_il = None
    return _salva(reparto)


@transaction.atomic
def imposta(reparto_id, numero: int) -> Reparto:
    """Il banco riparte dal numero indicato (da 0 a ``massimo``), che viene chiamato; chi era in coda resta in coda."""
    reparto = _bloccato(reparto_id)
    in_coda = reparto.in_coda
    # Il totale che fa comparire proprio quel numero: lo 0 è la prima chiamata.
    reparto.chiamati = numero + 1
    reparto.emessi = reparto.chiamati + in_coda
    return _salva(reparto, chiamata=True)


@transaction.atomic
def emetti(reparto_id) -> Reparto:
    """Un biglietto nuovo dal totem: il numero è ``reparto.ultimo_emesso``."""
    reparto = _bloccato(reparto_id)
    if not reparto.attivo:
        raise RepartoChiuso(reparto.nome)
    # Se il banco è andato avanti senza biglietti, il primo biglietto parte da lì.
    reparto.emessi = max(reparto.emessi, reparto.chiamati) + 1
    return _salva(reparto)
