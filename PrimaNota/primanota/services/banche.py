"""
Raggruppamenti Banche: spaccato delle causali 4 (Bancomat) e 5 (Carte di credito) della prima nota per
tipologia di transazione, dalle chiusure POS dei SysSpy di tutte le casse del punto vendita, come per i
Buoni Pasto nella colonna Evidenze. Le tipologie si assegnano alle causali per istituto di credito
(Impostazioni › Raggruppamenti Banche) e l'istituto al punto vendita.
"""

from decimal import Decimal

from .. import sysspy
from ..models import FileSysSpy, IstitutoNegozio

CAUSALI_POS = [(5, "CARTE DI CREDITO"), (4, "BANCOMAT")]
ZERO = Decimal("0")


def _chiave(testo):
    return " ".join(str(testo).split()).upper()


def circuiti_giornata(codice_pv, giorno):
    """{tipologia: importo} della giornata, sommando le chiusure POS di tutte le casse; None se non ce ne sono."""
    out, nomi, trovate = {}, {}, False
    for testo in FileSysSpy.objects.filter(codice_negozio=str(codice_pv), data=giorno).exclude(
            chiusura_pos="").values_list("chiusura_pos", flat=True):
        trovate = True
        for nome, importo in sysspy.circuiti_pos(testo).items():
            k = _chiave(nome)
            nomi.setdefault(k, nome)
            out[k] = out.get(k, ZERO) + importo
    return {nomi[k]: v for k, v in out.items()} if trovate else None


def configurazione():
    """{codice_pv: (istituto, {tipologia normalizzata: causale})}."""
    out = {}
    for a in IstitutoNegozio.objects.select_related("istituto").prefetch_related("istituto__tipologie"):
        out[a.codice_negozio] = (a.istituto, {_chiave(t.descrizione): t.causale for t in a.istituto.tipologie.all()})
    return out


def applica(giornate):
    """
    Aggiunge alle giornate di prima nota lo spaccato POS: per le causali 4 e 5 «spaccato» [(tipologia, importo)]
    da mostrare in Evidenze («colonna_pos») e «controllo» {prima_nota, pos, differenza}; per la giornata
    «pos_avviso» e «pos_non_assegnate».
    """
    config = configurazione()
    for g in giornate:
        g["pos_avviso"], g["pos_non_assegnate"] = "", []
        istituto, mappa = config.get(str(g["pv"]), (None, {}))
        if not istituto:
            g["pos_avviso"] = ("Spaccato POS non disponibile: punto vendita non associato a un istituto di credito "
                               "(Impostazioni › Raggruppamenti Banche).")
            continue
        circuiti = circuiti_giornata(g["pv"], g["data"]) if g.get("data") else None
        if circuiti is None:
            g["pos_avviso"] = f"{istituto.nome}: nessuna chiusura POS nei SysSpy archiviati di questa giornata."
            circuiti = {}
        g["pos_istituto"] = istituto.nome
        per_causale = {codice: [] for codice, _ in CAUSALI_POS}
        for nome, importo in circuiti.items():
            causale = mappa.get(_chiave(nome))
            if causale in per_causale:
                if importo:
                    per_causale[causale].append((nome, importo))
            elif importo:
                g["pos_non_assegnate"].append((nome, importo))
        for c in g["causali"]:
            if c["codice"] not in per_causale:
                continue
            c["spaccato"] = per_causale[c["codice"]]
            # Lo spaccato è la contropartita in Evidenze; il confronto usa l'importo della causale nella colonna
            # in cui è registrata in prima nota (di norma Uscite).
            c["colonna_pos"] = "evidenze"
            registrata = next((col for col in ("uscite", "entrate", "evidenze") if c.get(col) is not None), None)
            pos = sum((i for _, i in c["spaccato"]), ZERO)
            prima_nota = c.get(registrata) or ZERO
            c["controllo"] = {"prima_nota": prima_nota, "pos": pos, "differenza": prima_nota - pos}
    return giornate
