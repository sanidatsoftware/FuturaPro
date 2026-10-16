"""Le stampanti dei biglietti (Anagrafica Stampanti Ticket) e il loro abbinamento ai totem.

Un totem senza stampante abbinata stampa come dice la zona «prendi il numero» del layout; con
una stampante abbinata, tipo e indirizzo sono quelli della stampante (intestazione e messaggio
anche, se compilati). La stampa di prova la fa un totem abbinato: il server non vede la rete
del negozio. La richiesta è un'ora sulla stampante, come per le fotografie dello schermo, e
vale due minuti.
"""

from datetime import timedelta

from django.utils import timezone

VALIDITA_PROVA = timedelta(minutes=2)


def per_il_player(stampante) -> dict | None:
    if stampante is None:
        return None
    from .ticket import per_il_player as ticket
    from .ticket import punti_stampante, semplice

    punti = punti_stampante(stampante.modello, stampante.carta)
    disegno = ticket(stampante.layout, punti)
    # Windows e rete stampano sempre un'immagine: senza layout, quella del biglietto semplice.
    if disegno is None and stampante.tipo in ("windows", "rete"):
        disegno = semplice(punti, stampante.carta)
    return {
        "id": str(stampante.id), "nome": stampante.nome, "stampa": stampante.tipo,
        "stampante": stampante.indirizzo, "intestazione": stampante.intestazione, "messaggio": stampante.messaggio,
        "punti": punti, "ticket": ticket_con_testi(disegno, stampante),
    }


def ticket_con_testi(layout: dict | None, stampante) -> dict | None:
    """Intestazione e messaggio scritti sulla stampante valgono sopra quelli del layout ticket."""
    if layout is None:
        return None
    return {**layout, "intestazione": stampante.intestazione, "messaggio": stampante.messaggio}


def applica(monitor, configurazione: dict) -> dict:
    """La configurazione della zona «prendi il numero» con la stampante abbinata sopra."""
    dati = per_il_player(monitor.stampante) if monitor.stampante_id else None
    if dati is None:
        return configurazione
    nuova = {**configurazione, "stampa": dati["stampa"], "stampante": dati["stampante"], "ticket": dati["ticket"]}
    for campo in ("intestazione", "messaggio"):
        if dati[campo]:
            nuova[campo] = dati[campo]
    return nuova


def richiedi_prova(stampante, monitor) -> None:
    stampante.prova_richiesta = timezone.now()
    stampante.prova_monitor = monitor
    stampante.prova_esito = {}
    stampante.save(update_fields=["prova_richiesta", "prova_monitor", "prova_esito"])


def in_attesa(stampante) -> bool:
    chiesta = stampante.prova_richiesta
    return chiesta is not None and timezone.now() - chiesta <= VALIDITA_PROVA and not stampante.prova_esito


def prova_per_il_monitor(monitor_id):
    """La stampante su cui questo schermo deve fare adesso una stampa di prova, o None."""
    from .models import StampanteTicket

    return StampanteTicket.objects.filter(
        prova_monitor_id=monitor_id, prova_esito={}, prova_richiesta__gt=timezone.now() - VALIDITA_PROVA
    ).first()


def salva_esito(stampante, ok: bool, messaggio: str) -> None:
    stampante.prova_esito = {"ok": ok, "messaggio": messaggio[:300], "quando": timezone.now().isoformat()}
    stampante.save(update_fields=["prova_esito"])


def stato_prova(stampante) -> dict:
    totem = stampante.prova_monitor.nome if stampante.prova_monitor_id and stampante.prova_monitor else ""
    if in_attesa(stampante):
        return {"stato": "in_attesa", "chiesta": stampante.prova_richiesta, "totem": totem}
    esito = stampante.prova_esito or {}
    if esito:
        return {"stato": "riuscita" if esito.get("ok") else "fallita", "totem": totem, **esito}
    if stampante.prova_richiesta:
        return {"stato": "senza_risposta", "chiesta": stampante.prova_richiesta, "totem": totem}
    return {"stato": "mai"}
