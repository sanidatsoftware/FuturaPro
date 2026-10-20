"""
Stampa delle chiusure (fiscali o POS): scansioni caricate ed estratti SysSpy impaginati
in una griglia su fogli A4, in un PDF da stampare sulla stampante predefinita o salvare.
"""

from datetime import date

import pymupdf
import requests

from ..models import FileSysSpy
from .accesso import etichetta_negozio, negozi_attivi_ordinati
from .baserow_primanota import CHIUSURA_FISCALE, CHIUSURA_POS, elenco_scansioni

SEZIONI = {
    "fiscale": {"tipo": CHIUSURA_FISCALE, "campo": "chiusura_fiscale", "titolo": "Chiusure fiscali"},
    "pos": {"tipo": CHIUSURA_POS, "campo": "chiusura_pos", "titolo": "Chiusure POS"},
}
# Documenti per foglio -> (colonne, righe) su A4 verticale.
GRIGLIE = {1: (1, 1), 2: (2, 1), 4: (2, 2), 6: (2, 3), 8: (2, 4), 9: (3, 3)}
A4 = pymupdf.paper_rect("a4")
MARGINE = 24
DIDASCALIA = 11
MAX_ELEMENTI = 400


def _scarica(url):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "")


def elementi(sezione, negozio_id=None, data_da="", data_a="", contenuto="tutto"):
    """[(didascalia, tipo, dati)] con tipo 'testo', 'pdf' (documento, pagina) o 'immagine' (byte)."""
    conf = SEZIONI[sezione]
    negozi = {n["id"]: n for n in negozi_attivi_ordinati()}
    chiave_negozio = {nid: i for i, nid in enumerate(negozi)}
    gruppi = {}

    if contenuto in ("tutto", "sysspy"):
        files = FileSysSpy.objects.filter(data__range=(data_da, data_a)).only(
            "negozio_id", "data", "cassa", conf["campo"], "totale_giornaliero", "scontrini_trovati").order_by("cassa")
        if negozio_id:
            files = files.filter(negozio_id=negozio_id)
        for f in files:
            testo = getattr(f, conf["campo"])
            if testo and not f.cassa_vuota:
                gruppi.setdefault((f.negozio_id, f.data.isoformat()), []).append(
                    (f"Cassa {f.cassa} - SysSpy", "testo", testo))

    if contenuto in ("tutto", "scansioni"):
        for s in elenco_scansioni(negozio_id=negozio_id, data_da=data_da, data_a=data_a):
            if s["tipo_documento"] != conf["tipo"] or not s["anteprima"]:
                continue
            etichetta = f"Cassa {s['cassa']} - scansione" if s["cassa"] else "Scansione"
            elenco = gruppi.setdefault((s["negozio_id"], s["data_documento"]), [])
            try:
                dati, tipo_mime = _scarica(s["anteprima"]["url"])
                if dati[:4] == b"%PDF" or "pdf" in tipo_mime:
                    doc = pymupdf.open(stream=dati, filetype="pdf")
                    for n in range(doc.page_count):
                        elenco.append((f"{etichetta} pag. {n + 1}" if doc.page_count > 1 else etichetta, "pdf", (doc, n)))
                else:
                    elenco.append((etichetta, "immagine", dati))
            except Exception as exc:  # un allegato non scaricabile non blocca la stampa
                elenco.append((etichetta, "testo", f"Allegato non disponibile:\n{exc}"))

    out = []
    for (nid, giorno) in sorted(gruppi, key=lambda k: (k[1], chiave_negozio.get(k[0], 9999))):
        nome = etichetta_negozio(negozi.get(nid)) or str(nid)
        data_fmt = date.fromisoformat(giorno).strftime("%d/%m/%Y")
        for didascalia, tipo, dati in gruppi[(nid, giorno)]:
            out.append((f"{nome}  {data_fmt}  {didascalia}", tipo, dati))
    return out[:MAX_ELEMENTI]


def _testo(pagina, rect, testo):
    """Testo a colonne fisse (Courier), rimpicciolito quanto basta per stare nel riquadro."""
    righe = []
    for r in testo.expandtabs().splitlines():
        # Le righe vuote consecutive si riducono a una: sulla stampa di cassa sono solo spazio.
        if r.strip() or (righe and righe[-1].strip()):
            righe.append(r)
    righe = righe or [""]
    # Si toglie il rientro comune, così il testo usa tutta la larghezza.
    rientro = min((len(r) - len(r.lstrip()) for r in righe if r.strip()), default=0)
    righe = [r[rientro:] for r in righe]
    larghezza = max(len(r) for r in righe) or 1
    corpo = min(11, (rect.width - 8) / (larghezza * 0.6), (rect.height - 8) / (len(righe) * 1.15))
    corpo = max(corpo, 3.5)
    y = rect.y0 + 4 + corpo
    for r in righe:
        if y > rect.y1 - 2:
            break
        pagina.insert_text((rect.x0 + 4, y), r, fontname="cour", fontsize=corpo)
        y += corpo * 1.15


def genera_pdf(voci, per_pagina=4, titolo=""):
    colonne, righe_griglia = GRIGLIE.get(per_pagina, GRIGLIE[4])
    doc = pymupdf.open()
    larghezza = (A4.width - 2 * MARGINE) / colonne
    altezza = (A4.height - 2 * MARGINE - 14) / righe_griglia
    if not voci:
        pagina = doc.new_page(width=A4.width, height=A4.height)
        pagina.insert_text((MARGINE, MARGINE + 20), f"{titolo}: nessun documento nel periodo scelto.",
                           fontname="helv", fontsize=11)
        return doc.tobytes()
    per_foglio = colonne * righe_griglia
    for i, (didascalia, tipo, dati) in enumerate(voci):
        posto = i % per_foglio
        if posto == 0:
            pagina = doc.new_page(width=A4.width, height=A4.height)
            pagina.insert_text((MARGINE, MARGINE), f"{titolo}  -  foglio {i // per_foglio + 1}",
                               fontname="helv", fontsize=8, color=(0.4, 0.4, 0.4))
        c, r = posto % colonne, posto // colonne
        cella = pymupdf.Rect(MARGINE + c * larghezza, MARGINE + 14 + r * altezza,
                             MARGINE + (c + 1) * larghezza, MARGINE + 14 + (r + 1) * altezza)
        interno = pymupdf.Rect(cella.x0 + 4, cella.y0 + 4, cella.x1 - 4, cella.y1 - 4)
        pagina.draw_rect(interno, color=(0.75, 0.75, 0.75), width=0.5)
        pagina.insert_text((interno.x0 + 3, interno.y0 + 8), didascalia[:110], fontname="helv", fontsize=7)
        area = pymupdf.Rect(interno.x0 + 2, interno.y0 + DIDASCALIA, interno.x1 - 2, interno.y1 - 2)
        try:
            if tipo == "testo":
                _testo(pagina, area, dati)
            elif tipo == "pdf":
                sorgente, numero = dati
                pagina.show_pdf_page(area, sorgente, numero, keep_proportion=True)
            else:
                pagina.insert_image(area, stream=dati, keep_proportion=True)
        except Exception as exc:
            _testo(pagina, area, f"Impossibile impaginare il documento:\n{exc}")
    return doc.tobytes(garbage=3, deflate=True)
