from datetime import timedelta

from ..models import DocumentoSysSpy, Emergenza, FileSysSpy, RegolaDocumento
from .baserow_primanota import FATTURE_SPESE, TIPI_DOCUMENTO

# Che cosa deve contenere la giornata perché la regola "solo se la giornata ne contiene" chieda la scansione.
SYSSPY_PER_TIPO = {"Resi": DocumentoSysSpy.RESO, "Transazioni abortite": DocumentoSysSpy.ABORTITO,
                   "Chiusura fiscale": "CASSA", "Chiusure POS bancari": "CASSA",
                   FATTURE_SPESE: "SPESE_FATTURA"}
# Da dove arriva quel dato: finché la fonte non c'è (SysSpy non arrivato, prima nota non registrata)
# la scansione si può caricare ma non è obbligatoria.
FONTE_PER_TIPO = {FATTURE_SPESE: "PRIMA_NOTA"}

# Stato di un genere di scansione in una giornata del negozio.
OBBLIGATORIA = "obbligatoria"
NON_RICHIESTA = "non_richiesta"   # facoltativa per regola, o il SysSpy non ne contiene: voce disabilitata
IN_ATTESA = "in_attesa"           # dipende dal SysSpy, che non è ancora arrivato: si può caricare


def obbligatoria(regola, presente_nel_sysspy):
    """Se la scansione di un genere va caricata, secondo la regola decisa da Amministratore o Direttore."""
    if regola == RegolaDocumento.SEMPRE:
        return True
    if regola == RegolaDocumento.SE_SYSSPY:
        return presente_nel_sysspy
    return False


def segni_prima_nota(presenze, codice, giorno):
    """«PRIMA_NOTA» se la giornata ha movimenti in prima nota, «SPESE_FATTURA» se ha spese con fattura."""
    p = (presenze or {}).get((str(codice), giorno))
    if not p:
        return set()
    return {"PRIMA_NOTA"} | ({"SPESE_FATTURA"} if p["fatture"] else set())


def presenti_nel_sysspy(negozio_id, dal, al):
    """{giorno: {"CASSA", "RESO", "ABORTITO", "PRIMA_NOTA", "SPESE_FATTURA"}} da SysSpy archiviati e prima nota."""
    from .accesso import negozio
    from .prima_nota import presenze
    out = {}
    for d in FileSysSpy.objects.filter(negozio_id=negozio_id, data__range=(dal, al)).values_list("data", flat=True):
        out.setdefault(d, set()).add("CASSA")
    for d, tipo in DocumentoSysSpy.da_scansionare().filter(
            file__negozio_id=negozio_id, file__data__range=(dal, al),
            tipo__in=[DocumentoSysSpy.RESO, DocumentoSysSpy.ABORTITO]).values_list("file__data", "tipo").distinct():
        out.setdefault(d, set()).add(tipo)
    codice = (negozio(negozio_id) or {}).get("codice")
    if codice:
        p = presenze(dal, al, [codice])
        for (pv, giorno) in (p or {}):
            out.setdefault(giorno, set()).update(segni_prima_nota(p, pv, giorno))
    return out


def stato_giornate(negozio_id, dal, al, caricate):
    """
    Per ogni giorno da dal ad al e per ogni genere: stato secondo le regole, scansioni già caricate
    e se manca (obbligatoria e non ancora caricata). caricate: scansioni del negozio nel periodo.
    """
    regole = RegolaDocumento.mappa()
    presenti = presenti_nel_sysspy(negozio_id, dal, al)
    emergenze = {giorno for _, giorno in Emergenza.giorni(dal, al, negozio_id)}
    conteggio = {}
    for s in caricate:
        chiave = (s["data_documento"], s["tipo_documento"])
        conteggio[chiave] = conteggio.get(chiave, 0) + 1
    out = {}
    d = dal
    while d <= al:
        spy = presenti.get(d, set())
        voci = []
        for t in TIPI_DOCUMENTO:
            regola = regole.get(t["id"])
            if regola == RegolaDocumento.SE_SYSSPY and (
                    d in emergenze or FONTE_PER_TIPO.get(t["id"], "CASSA") not in spy):
                # In Emergenza (prima nota non disponibile) non si sa cosa contiene la giornata: tutto caricabile.
                stato = IN_ATTESA
            elif obbligatoria(regola, SYSSPY_PER_TIPO.get(t["id"]) in spy):
                stato = OBBLIGATORIA
            else:
                stato = NON_RICHIESTA
            n = conteggio.get((d.isoformat(), t["id"]), 0)
            voci.append({"tipo": t, "stato": stato, "caricate": n, "manca": stato == OBBLIGATORIA and not n})
        out[d] = voci
        d += timedelta(days=1)
    return out
