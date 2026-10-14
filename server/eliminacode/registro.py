"""Il registro delle code: biglietti emessi e chiamate del banco.

Serve ai tempi d'attesa (statistiche) e alla coda sul telefono. Con le code sul server lo
scrivono le operazioni stesse (servizi.py); con il totem lo scrive il servizio code del
totem, e il player del totem lo inoltra qui (``registra_dal_totem``) appena c'è rete.
"""

from datetime import timedelta
from statistics import median

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Biglietto, ChiamataCoda, ImpostazioniTelefono, numero_mostrato

# Le operazioni che chiamano un numero (avanti e imposta): segnano il biglietto come servito.
CHIAMA = {"avanti", "imposta"}


def registra_emissione(reparto, quando=None, codice=None) -> Biglietto:
    dati = dict(
        cliente_id=reparto.cliente_id, reparto=reparto, giornata=timezone.localdate(quando) if quando else reparto.giornata or timezone.localdate(),
        progressivo=reparto.emessi, numero=reparto.ultimo_emesso or 0, emesso_il=quando or timezone.now(),
    )
    if codice:
        dati["codice"] = codice
    return Biglietto.objects.create(**dati)


def _segna_chiamato(reparto_id, giornata, progressivo, quando):
    biglietto = (
        Biglietto.objects.filter(reparto_id=reparto_id, giornata=giornata, progressivo=progressivo, chiamato_il__isnull=True)
        .order_by("-emesso_il").first()
    )
    if biglietto is not None and biglietto.emesso_il <= quando:
        biglietto.chiamato_il = quando
        biglietto.save(update_fields=["chiamato_il"])


def registra_chiamata(reparto, operazione, quando=None) -> ChiamataCoda:
    quando = quando or timezone.now()
    giornata = reparto.giornata or timezone.localdate()
    chiamata = ChiamataCoda.objects.create(
        cliente_id=reparto.cliente_id, reparto=reparto, giornata=giornata, quando=quando,
        operazione=operazione, progressivo=reparto.chiamati, numero=reparto.numero,
    )
    if operazione in CHIAMA and reparto.chiamati:
        _segna_chiamato(reparto.id, giornata, reparto.chiamati, quando)
    return chiamata


def registra_dal_totem(reparti_ammessi: dict, eventi: list) -> int:
    """Gli eventi del servizio code del totem: {tipo, reparto, progressivo, massimo?, quando, codice?}.
    Si possono rimandare: quelli già registrati non si duplicano."""
    registrati = 0
    for e in eventi[:2000]:
        reparto = reparti_ammessi.get(str(e.get("reparto", "")))
        quando = parse_datetime(str(e.get("quando", "")))
        tipo = str(e.get("tipo", ""))
        try:
            progressivo = max(0, int(e.get("progressivo", 0)))
        except (TypeError, ValueError):
            continue
        if reparto is None or quando is None:
            continue
        if timezone.is_naive(quando):
            quando = timezone.make_aware(quando)
        giornata = timezone.localdate(quando)
        numero = numero_mostrato(progressivo, reparto.massimo)
        if tipo == "emesso":
            codice = str(e.get("codice", ""))[:16]
            if not codice or Biglietto.objects.filter(codice=codice).exists():
                continue
            Biglietto.objects.create(
                cliente_id=reparto.cliente_id, reparto=reparto, giornata=giornata, progressivo=progressivo,
                numero=numero or 0, emesso_il=quando, codice=codice,
            )
        elif tipo in ("avanti", "indietro", "ripeti", "imposta", "azzera"):
            if ChiamataCoda.objects.filter(reparto=reparto, quando=quando, operazione=tipo).exists():
                continue
            ChiamataCoda.objects.create(
                cliente_id=reparto.cliente_id, reparto=reparto, giornata=giornata, quando=quando,
                operazione=tipo, progressivo=progressivo, numero=numero,
            )
            if tipo in CHIAMA and progressivo:
                _segna_chiamato(reparto.id, giornata, progressivo, quando)
        else:
            continue
        registrati += 1
    return registrati


def ritmo(reparto, adesso=None) -> float | None:
    """Secondi medi tra una chiamata e l'altra nell'ultima mezz'ora (la mediana: una pausa
    lunga non falsa la stima); None se il banco non ha chiamato abbastanza."""
    adesso = adesso or timezone.now()
    istanti = list(
        ChiamataCoda.objects.filter(reparto=reparto, operazione="avanti", quando__gte=adesso - timedelta(minutes=30))
        .order_by("quando").values_list("quando", flat=True)
    )
    if len(istanti) < 3:
        return None
    return median((b - a).total_seconds() for a, b in zip(istanti, istanti[1:]))


def stato_biglietto(biglietto, adesso=None) -> dict:
    """Cosa vede il cliente sul telefono."""
    adesso = adesso or timezone.now()
    reparto = biglietto.reparto
    impostazioni = ImpostazioniTelefono.objects.first()
    ultima = ChiamataCoda.objects.filter(reparto=reparto, giornata=biglietto.giornata).order_by("-quando").first()
    servito = ultima.progressivo if ultima else 0
    # Un azzeramento dopo il biglietto lo rende scaduto.
    azzerato = ultima is not None and ultima.operazione == "azzera" and ultima.quando > biglietto.emesso_il
    if biglietto.giornata < timezone.localdate(adesso) or azzerato:
        stato, davanti = "scaduto", 0
    elif servito == biglietto.progressivo:
        stato, davanti = "tocca_a_te", 0
    elif servito > biglietto.progressivo or biglietto.chiamato_il:
        stato, davanti = "passato", 0
    else:
        stato, davanti = "in_attesa", biglietto.progressivo - servito - 1
    secondi = ritmo(reparto, adesso)
    attesa = round((davanti + 1) * secondi / 60) if secondi and stato == "in_attesa" else None
    return {
        "reparto": reparto.nome, "colore": reparto.colore, "colore_testo": reparto.colore_testo,
        "numero": biglietto.numero, "servito": ultima.numero if ultima else None,
        "davanti": davanti, "stato": stato, "attesa_minuti": attesa,
        "avviso_a": impostazioni.avviso_a if impostazioni else 3,
        "aggiornato": (ultima.quando if ultima else biglietto.emesso_il).isoformat(),
        "emesso_il": biglietto.emesso_il.isoformat(),
    }


def telefono_per_manifest() -> dict | None:
    """Per il player del totem: se e come stampare il QR sul biglietto."""
    impostazioni = ImpostazioniTelefono.objects.first()
    base = getattr(settings, "FUTURAPRO_URL_PUBBLICO", "")
    if not impostazioni or not impostazioni.attivo or not base:
        return None
    return {"url": f"{base.rstrip('/')}/b/", "testo": impostazioni.testo}
