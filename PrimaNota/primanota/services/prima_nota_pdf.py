"""
Stampa della prima nota: una pagina A4 verticale per punto vendita e giorno, come l'«Elenco
movimenti modello: PRIMA NOTA» del gestionale, ma con le note intere. Se i movimenti non
stanno in una pagina il carattere si riduce; solo oltre il minimo si passa a una seconda pagina.
"""

import io
from datetime import datetime
from html import escape

import pymupdf

from .statistiche_pdf import CSS as CSS_BASE, _numero

PAGINA = pymupdf.paper_rect("a4")
MARGINE = 30
CORPO = PAGINA + (MARGINE, MARGINE, -MARGINE, -MARGINE - 12)
GRANDEZZE = [9, 8.5, 8, 7.5, 7, 6.5, 6]   # pt, dal più leggibile al minimo

CSS = CSS_BASE + """
h1 { font-size: 13pt; text-align: center; font-style: italic; margin: 0; }
p.sotto { text-align: center; margin: 1pt 0 8pt 0; }
th, td { font-size: 1em; }   /* segue la grandezza scelta per far stare la giornata in una pagina */
th { text-align: center; }
td { vertical-align: top; border: 0.5pt solid #b9c3cf; }
td.causale { font-weight: bold; }
table.riepilogo { margin-top: 10pt; }
table.riepilogo td { font-weight: normal; }
td.etichetta { font-weight: bold; }
td.spaccato { background-color: #fff8d6; font-style: italic; }
td.controllo { font-weight: bold; }
td.ok { color: #167a3d; font-weight: bold; }
td.ko { color: #b42318; font-weight: bold; }
p.avviso { color: #b42318; margin: 0 0 6pt 0; }
"""


def _euro(v):
    return _numero(v) if v is not None else ""


# Larghezze delle colonne (pagina utile 535 pt): MuPDF le rispetta solo se messe su tutte le celle.
# Senza i margini interni delle celle (circa 9 pt l'una): in tutto 535 - 7 × 9.
LARGHEZZE = [80, 74, 58, 42, 42, 42, 122]   # causale, descrizione, documento, entrate, uscite, evidenze, note


def _riga(celle, classi=None, tag="td"):
    classi = classi or [""] * len(celle)
    return "<tr>" + "".join(
        f"<{tag} class='{classi[i]}'" + (f" style='width:{LARGHEZZE[i]}px'" if i < len(LARGHEZZE) else "") + f">{c}</{tag}>"
        for i, c in enumerate(celle)) + "</tr>"


def _html(g, grandezza):
    righe = []
    for c in g["causali"]:
        for m in c["movimenti"]:
            valori = {col: (_euro(m["importo"]) if m["colonna"] == col else "") for col in ("entrate", "uscite", "evidenze")}
            righe.append(_riga([f"{c['codice']} {escape(c['descrizione'])}", escape(m["descrizione"]), escape(m["documento"]),
                                valori["entrate"], valori["uscite"], valori["evidenze"], escape(m["note"])],
                               ["causale", "", "", "n", "n", "n", ""]))
        if c.get("controllo"):
            # Spaccato per tipologia dalle chiusure POS (Raggruppamenti Banche) e confronto con la prima nota.
            for nome, importo in c["spaccato"]:
                valori = {col: (_euro(importo) if c["colonna_pos"] == col else "") for col in ("entrate", "uscite", "evidenze")}
                righe.append(_riga([f"{c['codice']} {escape(c['descrizione'])}", f"{escape(nome)} (chiusure POS)", "",
                                    valori["entrate"], valori["uscite"], valori["evidenze"], ""],
                                   ["causale spaccato", "spaccato", "", "n spaccato", "n spaccato", "n spaccato", ""]))
            # In stampa la riga di controllo c'è solo se gli importi non coincidono.
            k = c["controllo"]
            if k["differenza"]:
                righe.append(_riga([f"{c['codice']} {escape(c['descrizione'])}", "Confronto con Importo da Prima Nota", "",
                                    "", "", "", f"Prima nota {_euro(k['prima_nota'])} · chiusure POS {_euro(k['pos'])} · "
                                               f"DIFFERENZA {_euro(k['differenza'])}"],
                                   ["causale", "controllo", "", "", "", "", "ko"]))
    riepilogo = "".join(
        f"<tr><td class='etichetta'>{etichetta}</td><td>{r['data']:%d/%m/%Y}</td><td class='n'>{_euro(r['entrate'])}</td>"
        f"<td class='n'>{_euro(r['uscite'])}</td><td class='n'>{_euro(r['evidenze'])}</td>"
        f"<td class='n'>{_numero(r['movimenti'], 0)}</td></tr>"
        for etichetta, r in (("Ripresa", g["ripresa"]), ("Periodo", g["periodo"]), ("Progressivo", g["progressivo"]))
        if r.get("data"))
    nome = f"{g['pv']} {g['nome']}".strip()
    return (
        f"<body style='font-size:{grandezza}pt'>"
        "<h1>Elenco movimenti modello: PRIMA NOTA</h1>"
        f"<p class='sotto'>Punto vendita: <b>{escape(nome)}</b> del <b>{g['data']:%d/%m/%Y}</b></p>"
        + (f"<p class='avviso'>{escape(g['pos_avviso'])}</p>" if g.get("pos_avviso") else "")
        + ("<p class='avviso'>Tipologie della chiusura POS non assegnate: "
           + ", ".join(f"{escape(n)} {_euro(i)}" for n, i in g["pos_non_assegnate"]) + "</p>" if g.get("pos_non_assegnate") else "") +
        "<table>" + _riga(["Causale", "Descrizione", "Doc. riferimento", "Entrate", "Uscite", "Evidenze", "Note"], tag="th")
        + "".join(righe) + "</table>"
        "<table class='riepilogo'><tr><th></th><th>Data</th><th>Entrate</th><th>Uscite</th><th>Evidenze</th><th>Movimenti</th></tr>"
        + riepilogo + "</table></body>")


def _sta_in_una_pagina(html):
    more, _ = pymupdf.Story(html=html, user_css=CSS).place(CORPO)
    return not more


def genera_pdf(giornate, titolo, nome):
    uscita = io.BytesIO()
    writer = pymupdf.DocumentWriter(uscita)
    testate = []   # per ogni pagina: punto vendita e giorno, per il piè di pagina
    for g in giornate:
        grandezza = next((s for s in GRANDEZZE if _sta_in_una_pagina(_html(g, s))), GRANDEZZE[-1])
        story = pymupdf.Story(html=_html(g, grandezza), user_css=CSS)
        altro = True
        while altro:
            dispositivo = writer.begin_page(PAGINA)
            altro, _ = story.place(CORPO)
            story.draw(dispositivo)
            writer.end_page()
            testate.append(f"{g['pv']} {g['nome']} del {g['data']:%d/%m/%Y}".replace("  ", " "))
    if not giornate:
        story = pymupdf.Story(html=f"<h1>{escape(titolo)}</h1><p>Nessun movimento per i giorni e i punti vendita scelti.</p>",
                              user_css=CSS)
        dispositivo = writer.begin_page(PAGINA)
        story.place(CORPO)
        story.draw(dispositivo)
        writer.end_page()
        testate.append("")
    writer.close()

    doc = pymupdf.open("pdf", uscita.getvalue())
    stampato = datetime.now().strftime("%d/%m/%Y %H:%M")
    for i, pagina in enumerate(doc):
        pagina.insert_text((MARGINE, PAGINA.height - MARGINE + 4), f"Stampato il {stampato} · {testate[i]}",
                           fontsize=7, color=(0.4, 0.44, 0.52))
        testo = f"Pag. {i + 1} di {doc.page_count}"
        pagina.insert_text((PAGINA.width - MARGINE - pymupdf.get_text_length(testo, fontsize=7), PAGINA.height - MARGINE + 4),
                           testo, fontsize=7, color=(0.4, 0.44, 0.52))
    doc.set_metadata({"title": nome.removesuffix(".pdf"), "author": "Documenti Amministrativi - TO.CAL"})
    return doc.tobytes(garbage=3, deflate=True)
