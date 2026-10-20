"""
Statistiche dai SysSpy archiviati, per periodo e (facoltativo) negozio: corrispettivi,
mezzi di pagamento, correzioni, transazioni abortite, resi e produttività dei cassieri.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from ..models import FileSysSpy
from .accesso import etichetta_negozio, negozi_attivi_ordinati

ZERO = Decimal("0")
# Voci dei mezzi di pagamento come compaiono negli scontrini, nell'ordine in cui mostrarle.
ORDINE_PAGAMENTI = ["Contanti", "Carta Credito", "Bancomat", "Buoni Pasto", "Credito", "Buoni Sconto"]


def _d(valore):
    return Decimal(str(valore)) if valore not in (None, "") else ZERO


def calcola(data_da, data_a, negozio_id=None):
    files = (FileSysSpy.objects.filter(data__range=(data_da, data_a))
             .only("negozio_id", "codice_negozio", "data", "cassa", "totale_giornaliero", "totale_scontrini",
                   "scontrini_trovati", "totale_annulli", "pagamenti", "elenco_scontrini", "cassieri"))
    if negozio_id:
        files = files.filter(negozio_id=negozio_id)

    negozi = {n["id"]: n for n in negozi_attivi_ordinati()}
    ordine_negozi = {nid: i for i, nid in enumerate(negozi)}
    per_giorno = defaultdict(lambda: ZERO)
    per_negozio = defaultdict(lambda: {"totale": ZERO, "scontrini": 0, "annulli": ZERO, "correzioni": 0,
                                       "correzioni_euro": ZERO, "abortite": 0, "abortite_euro": ZERO,
                                       "resi": 0, "resi_euro": ZERO, "casse": set()})
    pagamenti = defaultdict(lambda: ZERO)
    cassieri = defaultdict(lambda: {"nome": "", "scontrini": 0, "totale": ZERO, "correzioni": 0,
                                    "correzioni_euro": ZERO, "abortite": 0, "giorni": set()})
    versione_vecchia = 0

    for f in files:
        if f.scontrini_trovati == 0 and not f.totale_giornaliero:
            continue   # cassa non usata
        totale = _d(f.totale_giornaliero if f.totale_giornaliero is not None else f.totale_scontrini)
        per_giorno[f.data] += totale
        n = per_negozio[f.negozio_id]
        n["totale"] += totale
        n["annulli"] += _d(f.totale_annulli)
        n["casse"].add(f.cassa)
        for voce, valore in (f.pagamenti or {}).items():
            pagamenti[voce] += _d(valore)
        if f.elenco_scontrini and len(f.elenco_scontrini[0]) < 9:
            versione_vecchia += 1
        for riga in f.elenco_scontrini or []:
            if len(riga) < 9:
                riga = list(riga) + [""] * (9 - len(riga))
            _, _, importo, _, abortito, cassiere, reso, correzioni, correzioni_euro = riga[:9]
            importo = _d(importo)
            if abortito:
                n["abortite"] += 1
                n["abortite_euro"] += importo
            elif reso:
                n["resi"] += 1
                n["resi_euro"] += importo
            else:
                n["scontrini"] += 1
            n["correzioni"] += correzioni or 0
            n["correzioni_euro"] += _d(correzioni_euro)
            if cassiere:
                c = cassieri[(f.negozio_id, cassiere)]
                c["nome"] = c["nome"] or (f.cassieri or {}).get(cassiere, "")
                c["giorni"].add(f.data)
                c["correzioni"] += correzioni or 0
                c["correzioni_euro"] += _d(correzioni_euro)
                if abortito:
                    c["abortite"] += 1
                elif not reso:
                    c["scontrini"] += 1
                    c["totale"] += importo

    totale = sum(per_giorno.values(), ZERO)
    scontrini = sum(n["scontrini"] for n in per_negozio.values())
    elettronico = pagamenti.get("Carta Credito", ZERO) + pagamenti.get("Bancomat", ZERO)
    somma_pagamenti = sum(pagamenti.values(), ZERO)

    giorni = []
    g = date.fromisoformat(data_da)
    while g <= date.fromisoformat(data_a):
        giorni.append({"data": g.isoformat(), "etichetta": g.strftime("%d/%m"), "valore": float(per_giorno.get(g, 0))})
        g += timedelta(days=1)

    righe_negozi = []
    for nid, v in sorted(per_negozio.items(), key=lambda x: -x[1]["totale"]):
        righe_negozi.append({
            "negozio_id": nid, "etichetta": etichetta_negozio(negozi.get(nid)) or str(nid),
            "codice": str((negozi.get(nid) or {}).get("codice", nid)),
            "ordine": ordine_negozi.get(nid, 9999), **{k: v[k] for k in v if k != "casse"}, "casse": len(v["casse"]),
            "medio": (v["totale"] / v["scontrini"]).quantize(Decimal("0.01")) if v["scontrini"] else ZERO,
        })

    voci = [v for v in ORDINE_PAGAMENTI if v in pagamenti] + sorted(v for v in pagamenti if v not in ORDINE_PAGAMENTI)
    righe_pagamenti = [{"voce": v, "importo": pagamenti[v],
                        "quota": float(pagamenti[v] / somma_pagamenti * 100) if somma_pagamenti else 0} for v in voci]

    righe_cassieri = []
    for (nid, codice), c in cassieri.items():
        righe_cassieri.append({
            "negozio": str((negozi.get(nid) or {}).get("codice", nid)), "codice": codice,
            "nome": c["nome"] or f"Cassiere {codice}", "giorni": len(c["giorni"]), "scontrini": c["scontrini"],
            "totale": c["totale"], "correzioni": c["correzioni"], "correzioni_euro": c["correzioni_euro"],
            "abortite": c["abortite"],
            "medio": (c["totale"] / c["scontrini"]).quantize(Decimal("0.01")) if c["scontrini"] else ZERO,
            "per_giorno": round(c["scontrini"] / len(c["giorni"]), 1) if c["giorni"] else 0,
        })
    righe_cassieri.sort(key=lambda r: -r["totale"])

    return {
        "kpi": {
            "totale": totale, "scontrini": scontrini,
            "medio": (totale / scontrini).quantize(Decimal("0.01")) if scontrini else ZERO,
            "elettronico": float(elettronico / somma_pagamenti * 100) if somma_pagamenti else 0,
            "abortite": sum(n["abortite"] for n in per_negozio.values()),
            "resi": sum(n["resi"] for n in per_negozio.values()),
            "annulli": sum((n["annulli"] for n in per_negozio.values()), ZERO),
        },
        "giorni": giorni,
        "negozi": righe_negozi,
        "pagamenti": righe_pagamenti,
        "cassieri": righe_cassieri,
        # File letti prima dell'aggiornamento: senza cassiere finché la rielaborazione non li rifà.
        "da_rielaborare": versione_vecchia,
    }
