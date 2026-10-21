"""
Stato della giornata di un negozio scelto dalla sede (Lavorato, Non lavorato, Giornata chiusura).
Vale per l'intera pagina del negozio: le scansioni della giornata seguono lo stesso «lavorato» in Baserow,
così il negozio non può più cancellarle e l'elenco «solo da lavorare» resta coerente.
"""

import logging

from ..models import GiornataLavorazione
from .baserow_primanota import aggiorna_lavorato, elenco_scansioni

log = logging.getLogger(__name__)


def stato(negozio_id, giorno, righe=None, con_scansioni=False):
    """
    {"stato", "modificato_da", "modificato_il"}: lo stato scelto per la giornata o quello predefinito
    (giornata chiusura per il pregresso senza scansioni, altrimenti non lavorato). righe: GiornataLavorazione.mappa()
    già letta; con_scansioni: il negozio ha inviato qualcosa per quella giornata.
    """
    g = righe.get((negozio_id, giorno)) if righe is not None else \
        GiornataLavorazione.objects.filter(negozio_id=negozio_id, data=giorno).first()
    if g:
        return {"stato": g.stato, "modificato_da": g.modificato_da, "modificato_il": g.modificato_il}
    return {"stato": GiornataLavorazione.stato_predefinito(giorno, con_scansioni), "modificato_da": "", "modificato_il": None}


def imposta(user, negozio_id, giorno, nuovo, nome=""):
    """Salva lo stato e allinea il «lavorato» delle scansioni (esclusi i versamenti, che hanno il loro flag)."""
    GiornataLavorazione.objects.update_or_create(negozio_id=negozio_id, data=giorno,
                                                 defaults={"stato": nuovo, "modificato_da": nome})
    if nuovo == GiornataLavorazione.CHIUSURA:
        return []
    lavorato = nuovo == GiornataLavorazione.LAVORATO
    errori = []
    for s in elenco_scansioni(negozio_id=negozio_id, data_da=giorno.isoformat(), data_a=giorno.isoformat()):
        if s["versamento"] or s["lavorato"] == lavorato:
            continue
        try:
            risultato = aggiorna_lavorato(user, s["id"], lavorato)
        except RuntimeError as exc:
            risultato = {"error": str(exc)}
        if "error" in risultato:
            log.warning("Lavorato della scansione %s non aggiornato: %s", s["id"], risultato["error"])
            errori.append(f"{s['tipo_documento']}: {risultato['error']}")
    return errori
