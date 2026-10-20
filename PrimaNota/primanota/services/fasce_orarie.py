"""
Vendite per fasce orarie, per punto vendita o per reparto, dal database Statistiche.

Si leggono le tabelle con le fasce di un quarto d'ora (FasceOrarie2): VenditeFasceOrarie2 per i
punti vendita e VenditeReparto2 per i reparti. Le fasce si possono limitare a un orario
(dalle–alle) e raggruppare a 15, 30 o 60 minuti. I clienti di più reparti non si sommano
(lo stesso cliente compra in più reparti): nella vista per reparto il totale clienti viene
dai punti vendita.
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from html import escape

from .cassa_centrale import NON_CONFIGURATO, configurazione, esegui

MISURE = OrderedDict([("valore", "Valore venduto"), ("pezzi", "Pezzi"), ("clienti", "Clienti")])
VISTE = OrderedDict([("negozi", "Per punto vendita"), ("reparti", "Per reparto")])
PASSI = OrderedDict([(15, "15 minuti"), (30, "30 minuti"), (60, "1 ora")])

# Minuto del giorno di inizio fascia (08:15 → 495), dalla tabella delle fasce di un quarto d'ora.
MINUTO = "(DATEPART(hour, f.OraInizioFasciaOraria) * 60 + DATEPART(minute, f.OraInizioFasciaOraria))"

QUERY_NEGOZI = f"""
SELECT v.NumNegozio, MAX(n.NomeNegozio), {MINUTO}, v.TipoClienteFasciaOraria,
       SUM(v.ValoreVendutoFasciaOraria), SUM(v.ArticoliVendutiFasciaOraria), SUM(v.ClientiFasciaOraria),
       COUNT(DISTINCT v.DataFasciaOraria)
  FROM Statistiche.dbo.VenditeFasceOrarie2 AS v
  JOIN Statistiche.dbo.FasceOrarie2 AS f ON f.NumeroFasciaOraria = v.NumeroFasciaOraria
  LEFT JOIN Statistiche.dbo.Negozi AS n ON n.CodiceNegozio = v.NumNegozio
 WHERE v.DataFasciaOraria >= %s AND v.DataFasciaOraria < %s
   {{filtro_pv}}
 GROUP BY v.NumNegozio, {MINUTO}, v.TipoClienteFasciaOraria
"""

QUERY_REPARTI = f"""
SELECT r.CodRepartoVenditeReparto, MAX(d.Descrizione), {MINUTO}, r.TipoClienteVenditeReparto,
       SUM(r.ValArticoliVenditeReparto), SUM(r.QtaArticoliVenditeReparto), SUM(r.NumClientiVenditeReparto),
       COUNT(DISTINCT r.DataVenditeReparto)
  FROM Statistiche.dbo.VenditeReparto2 AS r
  JOIN Statistiche.dbo.FasceOrarie2 AS f ON f.NumeroFasciaOraria = r.FasciaOraVenditeReparto
  LEFT JOIN Statistiche.dbo.DescrizioneReparti AS d ON d.Negozio = r.NumNegozio AND d.Reparto = r.CodRepartoVenditeReparto
 WHERE r.DataVenditeReparto >= %s AND r.DataVenditeReparto < %s
   {{filtro_pv}}
   {{filtro_reparti}}
 GROUP BY r.CodRepartoVenditeReparto, {MINUTO}, r.TipoClienteVenditeReparto
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
COLONNE_PER_TABELLA_PDF = 16


def _in(colonna, valori):
    return f"AND {colonna} IN ({', '.join(['%s'] * len(valori))})" if valori else ""


def _num(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def _ordine(codice):
    """Codici reparto e negozio in ordine numerico quando sono numeri."""
    t = str(codice).strip()
    return (0, int(t), "") if t.isdigit() else (1, 0, t)


def minuti(orario, predefinito):
    """'08:30' → 510; fuori formato il valore predefinito."""
    try:
        ore, mm = str(orario).split(":")[:2]
        valore = int(ore) * 60 + int(mm)
        return valore if 0 <= valore <= 24 * 60 else predefinito
    except ValueError:
        return predefinito


def orario(m):
    return f"{m // 60:02d}:{m % 60:02d}" if m < 24 * 60 else "24:00"


def etichetta_fascia(inizio, passo):
    return f"{orario(inizio)}-{orario(inizio + passo)}"


def elenco_reparti(punti_vendita=()):
    c = configurazione()
    if not c:
        return []
    pv = [str(p) for p in punti_vendita]
    righe = esegui(c, QUERY_ELENCO_REPARTI.format(filtro_pv=_in("r.Negozio", pv)), tuple(pv))
    return sorted(((str(r).strip(), (d or "").strip()) for r, d in righe), key=lambda x: _ordine(x[0]))


def interroga(data_da, data_a, vista="negozi", punti_vendita=(), reparti=()):
    """Righe (codice, descrizione, minuto, tipo cliente, valore, pezzi, clienti, giorni) per negozio o reparto."""
    c = configurazione()
    if not c:
        raise RuntimeError(NON_CONFIGURATO)
    pv = [str(p).strip() for p in punti_vendita if str(p).strip()]
    rep = [str(r).strip() for r in reparti if str(r).strip()]
    fine = (date.fromisoformat(data_a) + timedelta(days=1)).strftime("%Y%m%d")   # fino a fine giornata
    parametri = (data_da.replace("-", ""), fine, *pv)
    negozi = esegui(c, QUERY_NEGOZI.format(filtro_pv=_in("v.NumNegozio", pv)), parametri)
    if vista != "reparti":
        return negozi, None
    sql = QUERY_REPARTI.format(filtro_pv=_in("r.NumNegozio", pv), filtro_reparti=_in("r.CodRepartoVenditeReparto", rep))
    # Clienti dei punti vendita per fascia: il totale dei clienti non si ricava sommando i reparti.
    return esegui(c, sql, parametri + tuple(rep)), negozi


def componi(righe, clienti_negozi=None, dalle=0, alle=24 * 60, passo=15):
    """
    {"fasce" (minuti di inizio), "passo", "righe": [{codice, etichetta, celle {inizio: {valore, pezzi, clienti}},
     totale, giorni}], "per_fascia", "totale", "giorni", "di_punta", "per_tipo"}: solo le fasce tra dalle e alle,
    raggruppate ogni «passo» minuti.
    """
    def fascia(minuto):
        if minuto is None:
            return None
        minuto = int(minuto)
        if minuto < dalle or minuto + 15 > alle:
            return None
        return dalle + (minuto - dalle) // passo * passo

    vuota = lambda: {"valore": Decimal("0"), "pezzi": 0, "clienti": 0}
    entita = OrderedDict()
    fasce = set()
    per_tipo = OrderedDict()
    for codice, descrizione, minuto, tipo, valore, pezzi, clienti, giorni in righe:
        f = fascia(minuto)
        if f is None:
            continue
        codice = str(codice).strip()
        fasce.add(f)
        e = entita.setdefault(codice, {"codice": codice, "descrizione": (descrizione or "").strip(), "celle": {}, "giorni": 0})
        cella = e["celle"].setdefault(f, vuota())
        cella["valore"] += _num(valore)
        cella["pezzi"] += int(pezzi or 0)
        cella["clienti"] += int(clienti or 0)
        e["giorni"] = max(e["giorni"], int(giorni or 0))
        t = per_tipo.setdefault(tipo, vuota())
        t["valore"] += _num(valore)
        t["pezzi"] += int(pezzi or 0)
    per_fascia = {f: vuota() for f in fasce}
    for e in entita.values():
        e["etichetta"] = f"{e['codice']} {e['descrizione']}".strip()
        e["totale"] = {k: sum((c[k] for c in e["celle"].values()), Decimal("0") if k == "valore" else 0)
                       for k in ("valore", "pezzi", "clienti")}
        for f, c in e["celle"].items():
            for k in c:
                per_fascia[f][k] += c[k]
    if clienti_negozi is not None:   # vista per reparto: clienti dai punti vendita
        for f in per_fascia:
            per_fascia[f]["clienti"] = 0
        for _, _, minuto, _, _, _, clienti, _ in clienti_negozi:
            f = fascia(minuto)
            if f in per_fascia:
                per_fascia[f]["clienti"] += int(clienti or 0)
    totale = {k: sum((c[k] for c in per_fascia.values()), Decimal("0") if k == "valore" else 0)
              for k in ("valore", "pezzi", "clienti")}
    fasce = sorted(fasce)
    punta = max(fasce, key=lambda f: per_fascia[f]["valore"]) if fasce else None
    return {"fasce": fasce, "passo": passo, "righe": sorted(entita.values(), key=lambda e: _ordine(e["codice"])),
            "per_fascia": per_fascia, "totale": totale, "giorni": max((e["giorni"] for e in entita.values()), default=0),
            "di_punta": etichetta_fascia(punta, passo) if punta is not None else "",
            "per_tipo": [{"tipo": t, **v} for t, v in per_tipo.items()]}


def tabella(risultato, misura="valore", media=False):
    """La matrice da mostrare: righe con celle (valore, livello di colore), totali di riga e di colonna."""
    def valore(cella, giorni):
        v = (cella or {}).get(misura, 0) or 0
        return Decimal(str(v)) / giorni if media and giorni else Decimal(str(v))

    righe = []
    massimo = Decimal("0")
    for e in risultato["righe"]:
        celle = [valore(e["celle"].get(f), e["giorni"]) for f in risultato["fasce"]]
        massimo = max([massimo] + celle)
        righe.append({"etichetta": e["etichetta"], "celle": celle, "totale": valore(e["totale"], e["giorni"]), "giorni": e["giorni"]})
    for r in righe:
        r["celle"] = [(v, _livello(v, massimo)) for v in r["celle"]]
    giorni = risultato["giorni"]
    colonne = [valore(risultato["per_fascia"][f], giorni) for f in risultato["fasce"]]
    totale_colonne = sum(colonne, Decimal("0"))
    return {"fasce": [etichetta_fascia(f, risultato["passo"]) for f in risultato["fasce"]], "righe": righe,
            "colonne": colonne, "totale": valore(risultato["totale"], giorni),
            "quote": [float(v / totale_colonne * 100) if totale_colonne else 0 for v in colonne]}


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
    intestazione = ["Punto vendita" if vista == "negozi" else "Reparto"] + t["fasce"] + ["Totale"]
    righe = [";".join(intestazione)]
    for r in t["righe"]:
        righe.append(";".join([r["etichetta"].replace(";", ",")] + [formato(v, misura) for v, _ in r["celle"]]
                              + [formato(r["totale"], misura)]))
    righe.append(";".join(["Totale"] + [formato(v, misura) for v in t["colonne"]] + [formato(t["totale"], misura)]))
    return "﻿" + "\r\n".join(righe) + "\r\n"


def pdf(risultato, misura, media, vista, titolo, sottotitolo, nome):
    """Le fasce in blocchi di 16 colonne (una tabella per blocco), così restano leggibili anche al quarto d'ora."""
    from .statistiche_pdf import documento_pdf

    t = tabella(risultato, misura, media)

    def cella(v, livello):
        if livello is None:
            return f"<td class='n'>{formato(v, misura) if v else ''}</td>"
        colore = "#ffffff" if livello >= SCURE else "#0b0b0b"
        return f"<td class='n' style='background-color:{SCALA[livello]};color:{colore}'>{formato(v, misura)}</td>"

    prima_colonna = "Punto vendita" if vista == "negozi" else "Reparto"
    blocchi = list(range(0, len(t["fasce"]), COLONNE_PER_TABELLA_PDF)) or [0]
    tabelle = []
    for n, inizio in enumerate(blocchi):
        fine = inizio + COLONNE_PER_TABELLA_PDF
        ultimo = n == len(blocchi) - 1
        coda_titolo = "<th class='n'>Totale</th>" if ultimo else ""
        righe = "".join(
            f"<tr><td>{escape(r['etichetta'])}</td>" + "".join(cella(v, l) for v, l in r["celle"][inizio:fine])
            + (f"<td class='n'><b>{formato(r['totale'], misura)}</b></td>" if ultimo else "") + "</tr>" for r in t["righe"])
        tabelle.append(
            f"<table style='font-size:7pt;margin-bottom:8pt'><tr><th>{prima_colonna}</th>"
            + "".join(f"<th class='n'>{f}</th>" for f in t["fasce"][inizio:fine]) + coda_titolo + "</tr>" + righe
            + "<tr><td><b>Totale</b></td>" + "".join(f"<td class='n'><b>{formato(v, misura)}</b></td>" for v in t["colonne"][inizio:fine])
            + (f"<td class='n'><b>{formato(t['totale'], misura)}</b></td>" if ultimo else "") + "</tr>"
            + "<tr><td>% sul totale</td>" + "".join(f"<td class='n'>{q:.1f}%</td>".replace(".", ",") for q in t["quote"][inizio:fine])
            + ("<td class='n'>100%</td>" if ultimo else "") + "</tr></table>")
    html = f"<h1>{escape(titolo)}</h1><p class='sotto'>{escape(sottotitolo)}</p>" + "".join(tabelle)
    return documento_pdf(html, titolo, sottotitolo, nome)
