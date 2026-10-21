"""
Stato della giornata di un negozio scelto dalla sede (Lavorato, Non lavorato, Giornata chiusura), separato
per Chiusure Fiscali e Gestione Versamenti. Vale per l'intera giornata del negozio: le scansioni seguono lo
stesso «lavorato» in Baserow (il flag dei versamenti per i versamenti), così il negozio non può più
cancellarle e gli elenchi «solo da lavorare» restano coerenti.
"""

import logging

from ..models import GiornataLavorazione
from .baserow_primanota import aggiorna_lavorato, elenco_scansioni

log = logging.getLogger(__name__)


def stato(negozio_id, giorno, righe=None, con_scansioni=False, sezione=GiornataLavorazione.CHIUSURE):
    """
    {"stato", "modificato_da", "modificato_il"}: lo stato scelto per la giornata o quello predefinito
    (giornata chiusura per il pregresso senza scansioni, altrimenti non lavorato). righe: GiornataLavorazione.mappa()
    già letta per la stessa sezione; con_scansioni: il negozio ha inviato qualcosa per quella giornata.
    """
    g = righe.get((negozio_id, giorno)) if righe is not None else \
        GiornataLavorazione.objects.filter(negozio_id=negozio_id, data=giorno, sezione=sezione).first()
    if g:
        return {"stato": g.stato, "modificato_da": g.modificato_da, "modificato_il": g.modificato_il}
    return {"stato": GiornataLavorazione.stato_predefinito(giorno, con_scansioni), "modificato_da": "", "modificato_il": None}


def imposta(user, negozio_id, giorno, nuovo, nome="", sezione=GiornataLavorazione.CHIUSURE):
    """
    Salva lo stato della sezione e allinea il «lavorato» delle sue scansioni. «Giornata chiusura» vale per
    entrambe le sezioni: se il negozio era chiuso non ci sono né chiusure né versamenti da lavorare.
    """
    sezioni = [s for s, _ in GiornataLavorazione.SEZIONI] if nuovo == GiornataLavorazione.CHIUSURA else [sezione]
    for s in sezioni:
        GiornataLavorazione.objects.update_or_create(negozio_id=negozio_id, data=giorno, sezione=s,
                                                     defaults={"stato": nuovo, "modificato_da": nome})
    if nuovo == GiornataLavorazione.CHIUSURA:
        return []
    lavorato = nuovo == GiornataLavorazione.LAVORATO
    versamenti = sezione == GiornataLavorazione.VERSAMENTI
    errori = []
    for s in elenco_scansioni(negozio_id=negozio_id, data_da=giorno.isoformat(), data_a=giorno.isoformat()):
        attuale = s["versamento_lavorato"] if versamenti else s["lavorato"]
        if s["versamento"] != versamenti or attuale == lavorato:
            continue
        try:
            risultato = aggiorna_lavorato(user, s["id"], lavorato, versamento=versamenti)
        except RuntimeError as exc:
            risultato = {"error": str(exc)}
        if "error" in risultato:
            log.warning("Lavorato della scansione %s non aggiornato: %s", s["id"], risultato["error"])
            errori.append(f"{s['tipo_documento']}: {risultato['error']}")
    return errori
