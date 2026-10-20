"""
Vendite per fasce orarie, per punto vendita o per reparto, dal database Statistiche.

Si leggono le viste del programma delle statistiche (View_StatVenditeFasceOrarieNegozi e
View_StatFascieOrarieReparti) e si raggruppa per ora intera, qualunque sia l'ampiezza delle
fasce (orarie o al quarto d'ora). I clienti di più reparti non si sommano (lo stesso cliente
compra in più reparti): nella vista per reparto il totale clienti viene dalla vista dei negozi.
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from html import escape

from .cassa_centrale import NON_CONFIGURATO, configurazione, esegui

MISURE = OrderedDict([("valore", "Valore venduto"), ("pezzi", "Pezzi"), ("clienti", "Clienti")])
VISTE = OrderedDict([("negozi", "Per punto vendita"), ("reparti", "Per reparto")])

QUERY_NEGOZI = """
SELECT v.NumNegozio, MAX(v.NomeNegozio), DATEPART(hour, v.OraInizioFasciaOraria),
       SUM(v.ValoreVendite), SUM(v.Pezzi), SUM(v.Clienti), COUNT(DISTINCT v.DataFasciaOraria)
  FROM Statistiche.dbo.View_StatVenditeFasceOrarieNegozi AS v
 WHERE v.DataFasciaOraria >= %s AND v.DataFasciaOraria < %s
   {filtro_pv}
 GROUP BY v.NumNegozio, DATEPART(hour, v.OraInizioFasciaOraria)
"""

QUERY_REPARTI = """
SELECT v.CodRepartoVenditeReparto, MAX(v.DescrizioneReparto), DATEPART(hour, v.OraInizioFasciaOraria),
       SUM(v.ValoreVendite), SUM(v.Pezzi), SUM(v.Clienti), COUNT(DISTINCT v.DataVenditeReparto)
  FROM Statistiche.dbo.View_StatFascieOrarieReparti AS v
 WHERE v.DataVenditeReparto >= %s AND v.DataVenditeReparto < %s
   {filtro_pv}
   {filtro_reparti}
 GROUP BY v.CodRepartoVenditeReparto, DATEPART(hour, v.OraInizioFasciaOraria)
"""

QUERY_ELENCO_REPARTI = """
SELECT r.Reparto, MAX(r.Descrizione)
  FROM Statistiche.dbo.DescrizioneReparti AS r
 WHERE 1 = 1 {filtro_pv}
 GROUP BY r.Reparto
 ORDER BY r.Reparto
"""

# Scala sequenziale a una tinta (dal chiaro allo scuro) per l'intensità delle celle.
SCALA = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SCURE = 3   # dal livello 3 il testo diventa bianco


def _in(colonna, valori):
    return f"AND {colonna} IN ({', '.join(['%s'] * len(valori))})" if valori else ""


def _num(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def _ordine(codice):
    """Codici reparto e negozio in ordine numerico quando sono numeri."""
    t = str(codice).strip()
    return (0, int(t), "") if t.isdigit() else (1, 0, t)


def elenco_reparti(punti_vendita=()):
    c = configurazione()
    if not c:
        return []
    pv = [str(p) for p in punti_vendita]
    righe = esegui(c, QUERY_ELENCO_REPARTI.format(filtro_pv=_in("r.Negozio", pv)), tuple(pv))
    return sorted(((str(r).strip(), (d or "").strip()) for r, d in righe), key=lambda x: _ordine(x[0]))


def interroga(data_da, data_a, vista="negozi", punti_vendita=(), reparti=()):
    """Righe aggregate: (codice, descrizione, ora, valore, pezzi, clienti, giorni) per negozio o reparto."""
    c = configurazione()
    if not c:
        raise RuntimeError(NON_CONFIGURATO)
    pv = [str(p).strip() for p in punti_vendita if str(p).strip()]
    rep = [str(r).strip() for r in reparti if str(r).strip()]
    fine = (date.fromisoformat(data_a) + timedelta(days=1)).strftime("%Y%m%d")   # fino a fine giornata
    parametri = (data_da.replace("-", ""), fine, *pv)
    if vista == "reparti":
        sql = QUERY_REPARTI.format(filtro_pv=_in("v.NumNegozio", pv), filtro_reparti=_in("v.CodRepartoVenditeReparto", rep))
        righe = esegui(c, sql, parametri + tuple(rep))
        # Clienti del negozio per ora: il totale dei clienti non si ricava sommando i reparti.
        clienti = esegui(c, QUERY_NEGOZI.format(filtro_pv=_in("v.NumNegozio", pv)), parametri)
    else:
        righe = esegui(c, QUERY_NEGOZI.format(filtro_pv=_in("v.NumNegozio", pv)), parametri)
        clienti = None
    return righe, clienti


def componi(righe, clienti_negozi=None):
    """
    {"ore", "righe": [{codice, etichetta, celle {ora: {valore, pezzi, clienti}}, totale, giorni}],
     "per_ora", "totale", "giorni", "ora_di_punta"}.
    """
    entita = OrderedDict()
    ore = set()
    for codice, descrizione, ora, valore, pezzi, clienti, giorni in righe:
        if ora is None:
            continue
        codice, ora = str(codice).strip(), int(ora)
        ore.add(ora)
        e = entita.setdefault(codice, {"codice": codice, "descrizione": (descrizione or "").strip(), "celle": {}, "giorni": 0})
        cella = e["celle"].setdefault(ora, {"valore": Decimal("0"), "pezzi": 0, "clienti": 0})
        cella["valore"] += _num(valore)
        cella["pezzi"] += int(pezzi or 0)
        cella["clienti"] += int(clienti or 0)
        e["giorni"] = max(e["giorni"], int(giorni or 0))
    per_ora = {o: {"valore": Decimal("0"), "pezzi": 0, "clienti": 0} for o in ore}
    for e in entita.values():
        e["etichetta"] = f"{e['codice']} {e['descrizione']}".strip()
        e["totale"] = {k: sum((c[k] for c in e["celle"].values()), Decimal("0") if k == "valore" else 0)
                       for k in ("valore", "pezzi", "clienti")}
        for o, c in e["celle"].items():
            for k in c:
                per_ora[o][k] += c[k]
    if clienti_negozi is not None:   # vista per reparto: clienti dalla vista dei negozi
        for o in per_ora:
            per_ora[o]["clienti"] = 0
        for _, _, ora, _, _, clienti, _ in clienti_negozi:
            if ora is not None and int(ora) in per_ora:
                per_ora[int(ora)]["clienti"] += int(clienti or 0)
    totale = {k: sum((c[k] for c in per_ora.values()), Decimal("0") if k == "valore" else 0) for k in ("valore", "pezzi", "clienti")}
    ore = sorted(ore)
    punta = max(ore, key=lambda o: per_ora[o]["valore"]) if ore else None
    return {"ore": ore, "righe": sorted(entita.values(), key=lambda e: _ordine(e["codice"])), "per_ora": per_ora,
            "totale": totale, "giorni": max((e["giorni"] for e in entita.values()), default=0), "ora_di_punta": punta}


def etichetta_ora(ora):
    return f"{ora:02d}-{(ora + 1) % 24:02d}"


def tabella(risultato, misura="valore", media=False):
    """La matrice da mostrare: righe con celle (valore, livello di colore), totali di riga e di colonna."""
    def valore(cella, giorni):
        v = (cella or {}).get(misura, 0) or 0
        return Decimal(str(v)) / giorni if media and giorni else Decimal(str(v))

    righe = []
    massimo = Decimal("0")
    for e in risultato["righe"]:
        celle = [valore(e["celle"].get(o), e["giorni"]) for o in risultato["ore"]]
        massimo = max([massimo] + celle)
        righe.append({"etichetta": e["etichetta"], "celle": celle, "totale": valore(e["totale"], e["giorni"]), "giorni": e["giorni"]})
    for r in righe:
        r["celle"] = [(v, _livello(v, massimo)) for v in r["celle"]]
    giorni = risultato["giorni"]
    colonne = [valore(risultato["per_ora"][o], giorni) for o in risultato["ore"]]
    totale_colonne = sum(colonne, Decimal("0"))
    return {"ore": [etichetta_ora(o) for o in risultato["ore"]], "righe": righe, "colonne": colonne,
            "totale": valore(risultato["totale"], giorni), "quote": [float(v / totale_colonne * 100) if totale_colonne else 0
                                                                       for v in colonne]}


def _livello(v, massimo):
    if not v or not massimo:
        return None
    return min(len(SCALA) - 1, int(v / massimo * len(SCALA)))


def formato(v, misura):
    if misura == "valore":
        testo = f"{v:,.2f}"
    else:
        testo = f"{v:,.1f}" if v != v.to_integral_value() else f"{v:,.0f}"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".")


def csv(risultato, misura, media, vista):
    t = tabella(risultato, misura, media)
    intestazione = ["Punto vendita" if vista == "negozi" else "Reparto"] + t["ore"] + ["Totale"]
    righe = [";".join(intestazione)]
    for r in t["righe"]:
        righe.append(";".join([r["etichetta"].replace(";", ",")] + [formato(v, misura) for v, _ in r["celle"]]
                              + [formato(r["totale"], misura)]))
    righe.append(";".join(["Totale"] + [formato(v, misura) for v in t["colonne"]] + [formato(t["totale"], misura)]))
    return "﻿" + "\r\n".join(righe) + "\r\n"


def pdf(risultato, misura, media, vista, titolo, sottotitolo, nome):
    from .statistiche_pdf import documento_pdf

    t = tabella(risultato, misura, media)
    n = len(t["ore"]) + 2
    piccolo = "font-size: 6.5pt;" if n > 18 else ""

    def cella(v, livello):
        if livello is None:
            return f"<td class='n'>{formato(v, misura) if v else ''}</td>"
        colore = "#ffffff" if livello >= SCURE else "#0b0b0b"
        return f"<td class='n' style='background-color:{SCALA[livello]};color:{colore}'>{formato(v, misura)}</td>"

    corpo = "".join(
        f"<tr><td>{escape(r['etichetta'])}</td>" + "".join(cella(v, l) for v, l in r["celle"])
        + f"<td class='n'><b>{formato(r['totale'], misura)}</b></td></tr>" for r in t["righe"])
    html = (
        f"<h1>{escape(titolo)}</h1><p class='sotto'>{escape(sottotitolo)}</p>"
        f"<table style='{piccolo}'><tr><th>{'Punto vendita' if vista == 'negozi' else 'Reparto'}</th>"
        + "".join(f"<th class='n'>{o}</th>" for o in t["ore"]) + "<th class='n'>Totale</th></tr>" + corpo
        + "<tr><td><b>Totale</b></td>" + "".join(f"<td class='n'><b>{formato(v, misura)}</b></td>" for v in t["colonne"])
        + f"<td class='n'><b>{formato(t['totale'], misura)}</b></td></tr>"
        + "<tr><td>% sul totale</td>" + "".join(f"<td class='n'>{q:.1f}%</td>".replace(".", ",") for q in t["quote"])
        + "<td class='n'>100%</td></tr></table>")
    return documento_pdf(html, titolo, sottotitolo, nome)
