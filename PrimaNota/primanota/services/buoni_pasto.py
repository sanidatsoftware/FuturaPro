"""
Buoni pasto per emettitore: incassi in buoni pasto (causali 18-25 della cassa centrale)
per punto vendita ed emettitore, dal database SQL Server delle statistiche.

È la stessa consultazione del programma in Visual Basic; i punti vendita scelti passano
come parametri della query, non dentro il testo SQL.
"""

from collections import OrderedDict
from decimal import Decimal
from html import escape

from django.conf import settings

QUERY = """
SELECT r.pv AS PuntoVendita,
       n.NomeNegozio,
       r.Causale AS Causale,
       caus.descr AS Emettitore,
       SUM(r.importo) AS Importo
  FROM WEBNETSRV.newdis.dbo.ONLCassaCentrale AS r
  LEFT JOIN WEBNETSRV.newdis.dbo.TBCausCC AS caus ON caus.codice = r.Causale
  LEFT JOIN Statistiche.dbo.Negozi AS n ON n.CodiceNegozio = r.pv
 WHERE r.Causale BETWEEN 18 AND 25
   AND r.segn = 1
   AND r.flag_gen IN ('C','E')
   AND r.data BETWEEN %s AND %s
   {filtro_pv}
 GROUP BY r.pv, n.NomeNegozio, r.Causale, caus.descr
 ORDER BY r.pv, r.Causale
"""


def configurazione():
    """
    {"host", "database", "user", "password"}: quella salvata nel portale (Buoni Pasto > Collegamento),
    altrimenti settings.BUONI_PASTO_DB; None se manca.
    """
    from ..models import CollegamentoBuoniPasto
    from .importazione import decifra

    c = CollegamentoBuoniPasto.objects.first()
    if c and c.host and c.utente:
        return {"host": c.host, "database": c.database or "Scontrini", "user": c.utente,
                "password": decifra(c.password_cifrata)}
    c = getattr(settings, "BUONI_PASTO_DB", None)
    return c if c and c.get("host") else None


def _pymssql():
    try:
        import pymssql
    except ImportError:
        raise RuntimeError("Manca il modulo pymssql: rieseguire l'installazione.")
    return pymssql


def _esegui(c, sql, parametri=()):
    """Esegue la query e restituisce tutte le righe; RuntimeError con il motivo se non riesce."""
    pymssql = _pymssql()
    try:
        with pymssql.connect(server=c["host"], user=c.get("user", ""), password=c.get("password", ""),
                             database=c.get("database") or "Scontrini", login_timeout=15, timeout=300) as cn:
            with cn.cursor() as cur:
                cur.execute(sql, parametri)
                return cur.fetchall()
    except pymssql.Error as exc:
        raise RuntimeError(f"Database dei buoni pasto non raggiungibile o query non riuscita: {exc}")


def prova(c):
    """Prova il collegamento con i dati indicati (SELECT 1)."""
    _esegui(c, "SELECT 1")


def interroga(data_da, data_a, punti_vendita=()):
    """Righe (pv, nome, causale, emettitore, importo). Date ISO; la query le vuole come yyyymmdd."""
    c = configurazione()
    if not c:
        raise RuntimeError("Collegamento al database dei buoni pasto non configurato "
                           "(Buoni Pasto per Emettitore > Collegamento, a cura di Direttore o Amministratore).")
    punti_vendita = [str(p).strip() for p in punti_vendita if str(p).strip()]
    filtro = f"AND r.pv IN ({', '.join(['%s'] * len(punti_vendita))})" if punti_vendita else ""
    parametri = (data_da.replace("-", ""), data_a.replace("-", ""), *punti_vendita)
    return [(str(pv).strip(), (nome or "").strip(), causale, (emettitore or "").strip(), Decimal(str(importo or 0)))
            for pv, nome, causale, emettitore, importo in _esegui(c, QUERY.format(filtro_pv=filtro), parametri)]


def riepilogo(righe):
    """Righe raggruppate per punto vendita (con subtotale), totali per emettitore e totale generale."""
    gruppi = OrderedDict()
    emettitori = OrderedDict()
    for pv, nome, causale, emettitore, importo in righe:
        g = gruppi.setdefault(pv, {"pv": pv, "nome": nome, "righe": [], "totale": Decimal("0")})
        g["righe"].append({"causale": causale, "emettitore": emettitore or f"Causale {causale}", "importo": importo})
        g["totale"] += importo
        chiave = (causale, emettitore or f"Causale {causale}")
        emettitori[chiave] = emettitori.get(chiave, Decimal("0")) + importo
    totale = sum((g["totale"] for g in gruppi.values()), Decimal("0"))
    per_emettitore = [{"causale": c, "emettitore": e, "importo": v,
                       "quota": float(v / totale * 100) if totale else 0}
                      for (c, e), v in sorted(emettitori.items(), key=lambda x: -x[1])]
    return {"gruppi": list(gruppi.values()), "per_emettitore": per_emettitore, "totale": totale}


def csv(risultato):
    """Per Excel: separatore «;», virgola decimale, BOM UTF-8 per gli accenti."""
    righe = ["PuntoVendita;NomeNegozio;Causale;Emettitore;Importo"]
    for g in risultato["gruppi"]:
        for r in g["righe"]:
            righe.append(";".join([g["pv"], g["nome"].replace(";", ","), str(r["causale"]),
                                   r["emettitore"].replace(";", ","), f"{r['importo']:.2f}".replace(".", ",")]))
    return "\ufeff" + "\r\n".join(righe) + "\r\n"


CSS_PDF = """
td.c, th.c { text-align: center; }
tr.a td { background-color: #ffffff; }
tr.b td { background-color: #eef1f4; }
tr.sub td { font-weight: bold; background-color: #dde3ea; }
tr.tot td { font-weight: bold; background-color: #2d4055; color: #ffffff; }
"""


def pdf(risultato, periodo, descrizione_pv, nome):
    """Totale per emettitore e dettaglio per punto vendita, con le fasce alternate per PV come nel programma."""
    from .statistiche_pdf import documento_pdf, euro

    def quota(v):
        return f"{v:.1f}".replace(".", ",") + "%"

    emettitori = "".join(
        f"<tr><td class='c'>{e['causale']}</td><td>{escape(e['emettitore'])}</td>"
        f"<td class='n'>{euro(e['importo'])}</td><td class='n'>{quota(e['quota'])}</td></tr>"
        for e in risultato["per_emettitore"])
    dettaglio = "".join(
        "".join(f"<tr class='{'b' if i % 2 else 'a'}'><td class='c'>{escape(g['pv'])}</td><td>{escape(g['nome'])}</td>"
                f"<td class='c'>{r['causale']}</td><td>{escape(r['emettitore'])}</td><td class='n'>{euro(r['importo'])}</td></tr>"
                for r in g["righe"])
        + f"<tr class='sub'><td></td><td colspan='3'>Totale {escape(g['pv'])} {escape(g['nome'])}</td>"
          f"<td class='n'>{euro(g['totale'])}</td></tr>"
        for i, g in enumerate(risultato["gruppi"]))
    html = (
        f"<h1>Buoni pasto per emettitore</h1><p class='sotto'>{escape(periodo)} · {escape(descrizione_pv)}</p>"
        "<h2>Totale per emettitore</h2><table><tr><th class='c'>Causale</th><th>Emettitore</th>"
        "<th class='n'>Importo</th><th class='n'>Quota</th></tr>"
        f"{emettitori}<tr class='tot'><td></td><td>Totale</td><td class='n'>{euro(risultato['totale'])}</td>"
        "<td class='n'>100%</td></tr></table>"
        "<h2>Dettaglio per punto vendita</h2><table><tr><th class='c'>PV</th><th>Nome negozio</th>"
        "<th class='c'>Causale</th><th>Emettitore</th><th class='n'>Importo</th></tr>"
        f"{dettaglio}<tr class='tot'><td></td><td colspan='3'>Totale generale</td>"
        f"<td class='n'>{euro(risultato['totale'])}</td></tr></table>")
    return documento_pdf(html, "Buoni pasto per emettitore", periodo, nome, css=CSS_PDF)
