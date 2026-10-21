"""
Monitor trasmissioni Prima Nota: una riga per negozio, una colonna per giorno,
come il Monitor Trasmissioni PV dei carichi. In più ogni cella riporta i SysSpy
archiviati, i versamenti da lavorare e le anomalie aperte.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from django.db.models import Count, Q

from scansioni.services.monitor_trasmissioni import MONTH_LABELS, WEEKDAY_LABELS, _build_days, _month_shift, _safe_int
from scansioni.services.baserow_scansioni import LOCAL_TZ

from ..models import DocumentoSysSpy, Emergenza, FileSysSpy, GiornataLavorazione, Nota, RegolaDocumento
from .giornate import stato as stato_giornata
from .prima_nota import presenze
from .regole import SYSSPY_PER_TIPO, obbligatoria, segni_prima_nota
from .accesso import negozi_attivi_ordinati
from .baserow_primanota import TIPI_DOCUMENTO, VERSAMENTO_CONTANTE, elenco_scansioni

_ESECUTORE = ThreadPoolExecutor(max_workers=4, thread_name_prefix="monitor-baserow")


def _sysspy_per_giorno(dal, al):
    out = {}
    from ..models import GiustificazioneControllo
    from .controlli import quadrato
    giustificati = {}
    for g in GiustificazioneControllo.objects.filter(data__range=(dal, al)):
        giustificati.setdefault((g.negozio_id, g.data, g.cassa), set()).add(g.controllo)
    for f in FileSysSpy.objects.filter(data__range=(dal, al)).defer(
            "elenco_scontrini", "chiusura_pos", "chiusura_fiscale"):
        cella = out.setdefault((f.negozio_id, f.data.isoformat()), {"casse": 0, "squadrate": 0, "tipi": set()})
        cella["casse"] += 1
        if not quadrato(f, giustificati.get((f.negozio_id, f.data, f.cassa), set())):
            cella["squadrate"] += 1
    # Resi e abortite trovati nel SysSpy: servono alle regole "obbligatoria solo se nel SysSpy".
    # Le abortite stampate per una sospensione dello scontrino non chiedono la scansione.
    for r in (DocumentoSysSpy.da_scansionare().filter(file__data__range=(dal, al), tipo__in=[DocumentoSysSpy.RESO, DocumentoSysSpy.ABORTITO])
              .values("file__negozio_id", "file__data", "tipo").distinct()):
        cella = out.setdefault((r["file__negozio_id"], r["file__data"].isoformat()), {"casse": 0, "squadrate": 0, "tipi": set()})
        cella["tipi"].add(r["tipo"])
    return out


def _note_aperte_per_giorno(dal, al, versamento=False):
    out = {}
    for r in (Nota.objects.filter(data__range=(dal, al), chiusa=False, versamento=versamento).values("negozio_id", "data")
              .annotate(n=Count("id"), contatto=Count("id", filter=Q(tipo=Nota.RICHIESTA_CONTATTO)))):
        out[(r["negozio_id"], r["data"].isoformat())] = r
    return out


def build_monitor_versamenti(year=None, month=None, view_mode="month", week_start=None):
    """Lo stesso monitor, solo per i versamenti contante (Direttore e Amministratore)."""
    return build_monitor(year, month, view_mode, week_start, versamenti=True)


def build_monitor(year=None, month=None, view_mode="month", week_start=None, versamenti=False):
    today = datetime.now(LOCAL_TZ).date()
    year = _safe_int(year, today.year)
    month = _safe_int(month, today.month)
    if not 1 <= month <= 12:
        year, month = today.year, today.month
    view_mode = "week" if view_mode == "week" else "month"
    days = _build_days(year, month, view_mode, week_start)

    # Il periodo letto da Baserow comprende anche il mese corrente fino a oggi,
    # che serve al contatore "Senza invio".
    inizio_mese_corrente = date(today.year, today.month, 1)
    dal = min(days[0], inizio_mese_corrente)
    al = max(days[-1], today)
    # Baserow si legge in parallelo a SysSpy e prima nota: sono le attese più lunghe della pagina.
    lettura = _ESECUTORE.submit(elenco_scansioni, data_da=dal.isoformat(), data_a=al.isoformat())
    sysspy = _sysspy_per_giorno(days[0], days[-1])
    emergenze = Emergenza.giorni(days[0], days[-1])
    # La prima nota serve al monitor generale e, per le giornate in Emergenza, anche a quello dei versamenti.
    prima_nota = presenze(days[0], days[-1]) if not versamenti or emergenze else None
    # Il monitor generale esclude i versamenti, che hanno un monitor proprio.
    tutte = lettura.result()
    scansioni = [s for s in tutte if s["versamento"] == versamenti]
    # Giornate in cui il negozio ha inviato qualcosa (anche solo il versamento): se per l'altra sezione non
    # c'era niente di obbligatorio da allegare, la giornata è completa e non «senza invio».
    inviate = {(s["negozio_id"], s["data_documento"]) for s in tutte if s["negozio_id"]}
    tipi = [t for t in TIPI_DOCUMENTO if (t["id"] == VERSAMENTO_CONTANTE) == versamenti]

    aggregato = {}
    for s in scansioni:
        if not s["negozio_id"]:
            continue
        cella = aggregato.setdefault((s["negozio_id"], s["data_documento"]), {
            "total": 0, "worked": 0, "pending": 0, "versamenti_aperti": 0,
            "tipi": {t["id"]: 0 for t in tipi}})
        cella["total"] += 1
        lavorato = s["versamento_lavorato"] if versamenti else s["lavorato"]
        cella["worked" if lavorato else "pending"] += 1
        if s["tipo_documento"] in cella["tipi"]:
            cella["tipi"][s["tipo_documento"]] += 1
        if s["versamento"] and not s["versamento_lavorato"]:
            cella["versamenti_aperti"] += 1

    regole = RegolaDocumento.mappa()
    note = _note_aperte_per_giorno(days[0], days[-1], versamento=versamenti)
    # Stato della giornata scelto dalla sede; il pregresso senza stato è «giornata chiusura».
    sezione = GiornataLavorazione.VERSAMENTI if versamenti else GiornataLavorazione.CHIUSURE
    stati = GiornataLavorazione.mappa(min(days[0], inizio_mese_corrente), max(days[-1], today), sezione=sezione)
    negozi = negozi_attivi_ordinati()

    summary = {"pending": 0, "worked": 0, "documents": 0, "missing_current_month": 0,
               "versamenti_aperti": 0, "anomalie": 0}
    righe = []
    for negozio in negozi:
        negozio_id = _safe_int(negozio.get("id"), 0)
        celle = []
        for day in days:
            iso = day.isoformat()
            valori = aggregato.get((negozio_id, iso))
            spy = sysspy.get((negozio_id, iso), {"casse": 0, "squadrate": 0, "tipi": set()})
            n = note.get((negozio_id, iso), {"n": 0, "contatto": 0})
            inviata = bool(valori) or (negozio_id, iso) in inviate
            giornata = stato_giornata(negozio_id, day, stati, con_scansioni=inviata)["stato"]
            if day > today:
                state = "future"
            elif giornata == GiornataLavorazione.CHIUSURA:
                state = "closed"
            elif not inviata:
                state = "missing"
            else:
                # Lavorato è della giornata intera, non del singolo allegato (anche per i versamenti).
                state = "worked" if giornata == GiornataLavorazione.LAVORATO else "pending"
            # Emergenza dichiarata dal negozio: giallo lampeggiante finché la prima nota non c'è.
            emergenza = emergenze.get((negozio_id, day))
            if emergenza and day <= today and not (prima_nota or {}).get((str(negozio.get("codice") or "").strip(), day)):
                state = "emergency"
            if valori:
                summary["documents"] += valori["total"]
            if inviata and state in ("pending", "worked"):
                summary[state] += 1
            valori = valori or {"total": 0, "worked": 0, "pending": 0, "versamenti_aperti": 0, "tipi": {}}
            presenti = (spy["tipi"] | ({"CASSA"} if spy["casse"] else set())
                        | segni_prima_nota(prima_nota, negozio.get("codice"), day))
            mancanti = [t["label"] for t in tipi
                        if not valori["tipi"].get(t["id"])
                        and obbligatoria(regole.get(t["id"]), SYSSPY_PER_TIPO.get(t["id"]) in presenti)]
            if state == "pending" and mancanti:
                state = "incomplete"
            summary["versamenti_aperti"] += valori["versamenti_aperti"]
            summary["anomalie"] += n["n"]
            celle.append({
                "date": iso,
                "day_number": day.day,
                "is_today": day == today,
                "state": state,
                "total": valori["total"],
                "worked": valori["worked"],
                "pending": valori["pending"],
                "tipi": [(t["sigla"], t["label"], valori["tipi"].get(t["id"], 0)) for t in tipi],
                "versamenti_aperti": valori["versamenti_aperti"],
                "casse_sysspy": spy["casse"],
                "squadrate": spy["squadrate"],
                "note_aperte": n["n"],
                "richieste_contatto": n["contatto"],
                "emergenza": emergenza.motivo if emergenza else "",
                "mancanti": mancanti if inviata else [],
                "detail_url": "" if day > today else (
                    f"/primanota/versamenti/?negozio={negozio_id}&data_da={iso}&data_a={iso}" if versamenti
                    else f"/primanota/giornata/{negozio_id}/{iso}/"),
            })
        righe.append({"store_id": negozio_id, "code": str(negozio.get("codice") or "").strip(),
                      "description": str(negozio.get("descrizione") or "").strip(), "cells": celle})

    # "Senza invio" conta solo il mese corrente fino a oggi, come nel monitor carichi.
    giorni_correnti = {date(today.year, today.month, d).isoformat() for d in range(1, today.day + 1)}
    ricevuti = {k for k in inviate if k[1] in giorni_correnti}
    ids = {_safe_int(n.get("id"), 0) for n in negozi}
    summary["missing_current_month"] = sum(
        1 for i in ids for g in giorni_correnti
        if (i, g) not in ricevuti and stato_giornata(i, date.fromisoformat(g), stati)["stato"] != GiornataLavorazione.CHIUSURA)

    previous_year, previous_month = _month_shift(year, month, -1)
    next_year, next_month = _month_shift(year, month, 1)
    return {
        "year": year, "month": month, "month_label": f"{MONTH_LABELS[month]} {year}",
        "view_mode": view_mode, "week_start": days[0].isoformat(), "week_end": days[-1].isoformat(),
        "previous_week": (days[0] - timedelta(days=7)).isoformat() if view_mode == "week" else "",
        "next_week": (days[0] + timedelta(days=7)).isoformat() if view_mode == "week" else "",
        "previous_year": previous_year, "previous_month": previous_month,
        "next_year": next_year, "next_month": next_month,
        "days": [{"date": d.isoformat(), "day_number": d.day, "weekday": WEEKDAY_LABELS[d.weekday()],
                  "is_today": d == today} for d in days],
        "rows": righe, "summary": summary,
        "current_month_label": f"{MONTH_LABELS[today.month]} {today.year}",
        "months": [(i, MONTH_LABELS[i]) for i in range(1, 13)],
    }

