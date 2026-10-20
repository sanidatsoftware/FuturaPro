"""
PDF A4 orizzontale delle statistiche: indicatori, grafici (con il tipo scelto nella pagina)
e tabelle. I grafici si disegnano con PyMuPDF e si inseriscono come immagini ad alta risoluzione.
"""

import io
import math
import re
from datetime import date
from decimal import Decimal
from html import escape

import pymupdf

PAGINA = pymupdf.paper_rect("a4-l")
MARGINE = 36
DPI_GRAFICI = 200

# Stessi colori della pagina: serie singola in blu, categorie nell'ordine fisso della palette.
BLU = (0x2a / 255, 0x78 / 255, 0xd6 / 255)
BLU_CHIARO = (0xcd / 255, 0xe2 / 255, 0xfb / 255)
GRIGLIA = (0.90, 0.91, 0.93)
TESTO_2 = (0.40, 0.44, 0.52)
CATEGORIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MAX_SPICCHI = 8   # oltre, le voci più piccole vanno in «Altri»

FONT = pymupdf.Font("helv")
TIPI_ANDAMENTO = {"linea", "area", "colonne"}
TIPI_CATEGORIE = {"barre", "torta"}


def _rgb(esadecimale):
    return tuple(int(esadecimale[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _numero(valore, decimali=2):
    testo = f"{Decimal(str(valore or 0)):,.{decimali}f}"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".")


def euro(valore):
    return f"{_numero(valore)} €"


def nome_file(negozio, data_da, data_a):
    parti = ["Statistiche", negozio or "Tutti i negozi", data_da if data_da == data_a else f"dal {data_da} al {data_a}"]
    return "_".join(re.sub(r"[^\w-]+", "_", p.replace(" - ", " ")).strip("_") for p in parti) + ".pdf"


def _scrivi(p, x, y, testo, size=7.5, colore=(0, 0, 0), destra=False, centro=False, grassetto=False):
    """Testo Unicode (anche €) con TextWriter: insert_text usa una codifica senza l'euro."""
    font = pymupdf.Font("hebo") if grassetto else FONT
    w = font.text_length(testo, size)
    if destra:
        x -= w
    elif centro:
        x -= w / 2
    tw = pymupdf.TextWriter(p.rect, color=colore)
    tw.append((x, y), testo, font=font, fontsize=size)
    tw.write_text(p)


def _immagine(larghezza, altezza, disegna):
    """Disegna su una pagina vettoriale e la restituisce come PNG (per la Story)."""
    doc = pymupdf.open()
    pagina = doc.new_page(width=larghezza, height=altezza)
    disegna(pagina, larghezza, altezza)
    return pagina.get_pixmap(dpi=DPI_GRAFICI).tobytes("png")


def _tetto(massimo):
    massimo = max(massimo, 1)
    passo = 10 ** (len(str(int(massimo))) - 1)
    return -(-massimo // passo) * passo


def _andamento(giorni, tipo):
    def disegna(p, L, H):
        sx, dx, alto, basso = 62, 10, 10, 24
        valori = [g["valore"] for g in giorni]
        tetto = _tetto(max(valori or [0]))
        n = len(giorni)
        larghezza = L - sx - dx
        y = lambda v: alto + (H - alto - basso) * (1 - v / tetto)
        for k in range(5):
            v = tetto * k / 4
            p.draw_line((sx, y(v)), (L - dx, y(v)), color=GRIGLIA, width=0.6)
            _scrivi(p, sx - 6, y(v) + 2.5, _numero(v, 2 if tetto < 10 else 0), 7, TESTO_2, destra=True)
        if not n:
            return
        if tipo == "colonne":
            passo = larghezza / n
            x = lambda i: sx + passo * (i + 0.5)
            barra = min(40.0, max(1.0, passo - 2))   # 2 pt di spazio tra le colonne
            for i, v in enumerate(valori):
                if v > 0:
                    p.draw_rect(pymupdf.Rect(x(i) - barra / 2, y(v), x(i) + barra / 2, y(0)), color=None, fill=BLU)
        else:
            x = lambda i: sx + (larghezza / 2 if n == 1 else i * larghezza / (n - 1))
            punti = [pymupdf.Point(x(i), y(v)) for i, v in enumerate(valori)]
            if tipo == "area":
                p.draw_polyline([pymupdf.Point(x(0), y(0))] + punti + [pymupdf.Point(x(n - 1), y(0))],
                                color=None, fill=BLU_CHIARO, closePath=True)
            if n == 1:
                p.draw_circle(punti[0], 2.5, color=None, fill=BLU)
            else:
                p.draw_polyline(punti, color=BLU, width=1.6, lineJoin=1)
        ogni = max(1, -(-n // 16))
        for i, g in enumerate(giorni):
            if i % ogni == 0:
                _scrivi(p, x(i), H - 8, g["etichetta"], 7, TESTO_2, centro=True)
    return disegna


def _raggruppa(voci):
    """Al massimo 8 categorie: le più piccole insieme in «Altri»."""
    voci = sorted(voci, key=lambda v: -v[1])
    if len(voci) <= MAX_SPICCHI:
        return voci
    return voci[:MAX_SPICCHI - 1] + [("Altri", sum(v for _, v in voci[MAX_SPICCHI - 1:]))]


def _categorie(p, area, titolo, voci, tipo):
    """voci: [(etichetta, valore)] nel riquadro area. Barre orizzontali o torta (ciambella) con legenda e quote."""
    _scrivi(p, area.x0, area.y0 + 11, titolo, 11, (0x2d / 255, 0x40 / 255, 0x55 / 255), grassetto=True)
    area = pymupdf.Rect(area.x0, area.y0 + 22, area.x1, area.y1)
    totale = sum(v for _, v in voci) or 1
    if not any(v for _, v in voci):
        _scrivi(p, area.x0, area.y0 + 12, "Nessun dato nel periodo.", 8, TESTO_2)
        return
    if tipo == "torta":
        dati = _raggruppa(voci)
        r = min(area.height / 2 - 4, 85, 11 * MAX_SPICCHI)
        centro = pymupdf.Point(area.x0 + r + 4, area.y0 + area.height / 2)
        inizio = -90.0
        for i, (_, v) in enumerate(dati):
            angolo = 360 * v / totale
            if angolo <= 0:
                continue
            if angolo >= 359.99:
                p.draw_circle(centro, r, color=None, fill=_rgb(CATEGORIE[i]))
            else:
                a = math.radians(inizio)
                bordo = pymupdf.Point(centro.x + r * math.cos(a), centro.y + r * math.sin(a))
                # Angolo negativo = senso orario sullo schermo; bordo bianco come spazio tra gli spicchi.
                p.draw_sector(centro, bordo, -angolo, color=(1, 1, 1), fill=_rgb(CATEGORIE[i]), width=1.5)
            inizio += angolo
        p.draw_circle(centro, r * 0.55, color=None, fill=(1, 1, 1))
        # Legenda: nome e, sotto, importo e quota (i colori chiari non bastano da soli).
        x0, y0 = centro.x + r + 20, centro.y - (len(dati) - 1) * 11 + 3
        for i, (nome, v) in enumerate(dati):
            yy = y0 + i * 22
            p.draw_rect(pymupdf.Rect(x0, yy - 8, x0 + 9, yy + 1), color=None, fill=_rgb(CATEGORIE[i]))
            _scrivi(p, x0 + 15, yy, nome[:40], 8)
            _scrivi(p, x0 + 15, yy + 9.5, f"{euro(v)} · {_numero(v / totale * 100, 1)}%", 7.5, TESTO_2)
        return
    massimo = max(v for _, v in voci) or 1
    riga = min(18, area.height / max(1, len(voci)))
    nome_l, valore_l = 140, 120
    traccia = area.width - nome_l - valore_l - 8
    for i, (nome, v) in enumerate(voci[:int(area.height // riga)]):
        yy = area.y0 + i * riga
        _scrivi(p, area.x0, yy + riga * 0.65, nome[:30], 8)
        w = max(1.5, traccia * v / massimo)
        p.draw_rect(pymupdf.Rect(area.x0 + nome_l, yy + 3, area.x0 + nome_l + w, yy + riga - 3), color=None, fill=BLU)
        _scrivi(p, area.x1, yy + riga * 0.65, f"{euro(v)} · {_numero(v / totale * 100, 1)}%", 8, TESTO_2, destra=True)


def _due_categorie(negozi, tipo_negozi, pagamenti, tipo_pagamenti):
    """Negozi e mezzi di pagamento affiancati in un'unica immagine."""
    def disegna(p, L, H):
        meta = (L - 24) / 2
        _categorie(p, pymupdf.Rect(0, 0, meta, H), "Corrispettivi per negozio", negozi, tipo_negozi)
        _categorie(p, pymupdf.Rect(meta + 24, 0, L, H), "Mezzi di pagamento", pagamenti, tipo_pagamenti)
    return disegna


CSS = """
* { font-family: sans-serif; }
body { font-size: 9pt; color: #263238; }
h1 { font-size: 16pt; color: #2d4055; margin: 0 0 2pt 0; }
h2 { font-size: 11.5pt; color: #2d4055; margin: 12pt 0 4pt 0; }
p.sotto { color: #667085; margin: 0 0 8pt 0; }
table { border-collapse: collapse; width: 100%; }
th { background-color: #2d4055; color: #ffffff; text-align: left; padding: 3pt 4pt; font-size: 8pt; }
td { border-bottom: 0.5pt solid #e1e7ee; padding: 2.5pt 4pt; font-size: 8pt; }
td.n, th.n { text-align: right; }
table.kpi td { border: 0.5pt solid #e1e7ee; padding: 5pt; }
table.kpi b { font-size: 12.5pt; color: #2d4055; }
table.kpi span { font-size: 7pt; color: #667085; }
p.nota { font-size: 7.5pt; color: #667085; }
"""


def _tabella(intestazioni, righe):
    th = "".join(f'<th class="{"n" if n else ""}">{escape(t)}</th>' for t, n in intestazioni)
    corpo = "".join("<tr>" + "".join(f'<td class="{"n" if intestazioni[i][1] else ""}">{escape(str(c))}</td>'
                                      for i, c in enumerate(r)) + "</tr>" for r in righe)
    return f"<table><tr>{th}</tr>{corpo}</table>"


def genera_pdf(dati, titolo, sottotitolo, nome, andamento="linea", negozi="barre", pagamenti="barre", giorni=None):
    """giorni: i giorni del grafico dell'andamento (la vista ingrandita nella pagina), altrimenti tutto il periodo."""
    andamento = andamento if andamento in TIPI_ANDAMENTO else "linea"
    negozi = negozi if negozi in TIPI_CATEGORIE else "barre"
    pagamenti = pagamenti if pagamenti in TIPI_CATEGORIE else "barre"
    giorni = giorni if giorni is not None else dati["giorni"]
    utile = PAGINA.width - 2 * MARGINE
    archivio = pymupdf.Archive()
    archivio.add(_immagine(utile, 165, _andamento(giorni, andamento)), "andamento.png")
    voci_negozi = [(r["etichetta"], float(r["totale"])) for r in dati["negozi"]]
    voci_pagamenti = [(r["voce"], float(r["importo"])) for r in dati["pagamenti"]]
    righe = max(len(voci_negozi) if negozi == "barre" else 10, len(voci_pagamenti) if pagamenti == "barre" else 10)
    alt_categorie = max(80, min(330, 18 * righe + 30))
    archivio.add(_immagine(utile, alt_categorie, _due_categorie(voci_negozi, negozi, voci_pagamenti, pagamenti)),
                 "categorie.png")

    k = dati["kpi"]
    kpi = [(euro(k["totale"]), "CORRISPETTIVI"), (_numero(k["scontrini"], 0), "SCONTRINI"),
           (euro(k["medio"]), "SCONTRINO MEDIO"), (f"{_numero(k['elettronico'], 1)}%", "PAGATO CON CARTE E BANCOMAT"),
           (euro(k["annulli"]), "ANNULLI (CORREZIONI)"), (f"{k['abortite']} · {k['resi']}", "ABORTITE · RESI")]
    periodo = ""
    if giorni and giorni != dati["giorni"]:
        periodo = f" (dal {giorni[0]['etichetta']} al {giorni[-1]['etichetta']})"
    html = (
        f"<h1>{escape(titolo)}</h1><p class='sotto'>{escape(sottotitolo)}</p>"
        "<table class='kpi'><tr>" + "".join(f"<td style='width:16.6%'><b>{escape(v)}</b><br/><span>{t}</span></td>" for v, t in kpi) + "</tr></table>"
        f"<h2>Andamento dei corrispettivi{escape(periodo)}</h2><img src='andamento.png' width='{utile:.0f}'/>"
        f"<p></p><img src='categorie.png' width='{utile:.0f}'/>"
        "<h2>Correzioni, transazioni abortite e resi per negozio</h2>"
        + _tabella([("Negozio", False), ("Casse", True), ("Scontrini", True), ("Medio", True), ("Annulli (chiusura fiscale)", True),
                    ("Righe corrette", True), ("Importo corretto", True), ("Abortite", True), ("Importo abortite", True),
                    ("Resi", True), ("Importo resi", True)],
                   [(r["etichetta"], r["casse"], _numero(r["scontrini"], 0), euro(r["medio"]), euro(r["annulli"]),
                     _numero(r["correzioni"], 0), euro(r["correzioni_euro"]), _numero(r["abortite"], 0),
                     euro(r["abortite_euro"]), _numero(r["resi"], 0), euro(r["resi_euro"])) for r in dati["negozi"]])
        + "<p class='nota'>«Righe corrette»: articoli stornati o annullati dentro gli scontrini; il «Totale annulli» della chiusura "
          "fiscale comprende queste righe più gli articoli degli scontrini annullati per richiesta del cliente.</p>"
        "<h2>Produttività per cassiere</h2>"
        + _tabella([("Negozio", False), ("Cassiere", False), ("Giorni", True), ("Scontrini", True), ("Al giorno", True),
                    ("Incassato", True), ("Medio", True), ("Righe corrette", True), ("Importo corretto", True), ("Abortite", True)],
                   [(c["negozio"], f"{c['nome']} ({c['codice']})", c["giorni"], _numero(c["scontrini"], 0),
                     _numero(c["per_giorno"], 1), euro(c["totale"]), euro(c["medio"]), _numero(c["correzioni"], 0),
                     euro(c["correzioni_euro"]), _numero(c["abortite"], 0)) for c in dati["cassieri"]])
    )

    return documento_pdf(html, titolo, sottotitolo, nome, archivio)


def documento_pdf(html, titolo, sottotitolo, nome, archivio=None, css=""):
    """HTML → PDF A4 orizzontale su più pagine, con piè di pagina (titolo, periodo, pagina n di m)."""
    uscita = io.BytesIO()
    story = pymupdf.Story(html=html, user_css=CSS + css, archive=archivio)
    writer = pymupdf.DocumentWriter(uscita)
    corpo = PAGINA + (MARGINE, MARGINE, -MARGINE, -MARGINE - 14)
    altro = True
    while altro:
        dispositivo = writer.begin_page(PAGINA)
        altro, _ = story.place(corpo)
        story.draw(dispositivo)
        writer.end_page()
    writer.close()

    doc = pymupdf.open("pdf", uscita.getvalue())
    for i, pagina in enumerate(doc):
        piede = f"{titolo} · {sottotitolo} · stampato il {date.today():%d/%m/%Y} · pagina {i + 1} di {doc.page_count}"
        pagina.insert_text((MARGINE, PAGINA.height - MARGINE + 6), piede, fontsize=7, color=TESTO_2)
    doc.set_metadata({"title": nome.removesuffix(".pdf"), "author": "Documenti Amministrativi - TO.CAL"})
    return doc.tobytes(garbage=3, deflate=True)
