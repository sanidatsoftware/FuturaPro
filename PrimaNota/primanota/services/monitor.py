"""
Monitor trasmissioni Prima Nota: una riga per negozio, una colonna per giorno,
come il Monitor Trasmissioni PV dei carichi. In più ogni cella riporta i SysSpy
archiviati, i versamenti da lavorare e le anomalie aperte.
"""

from datetime import date, datetime, timedelta

from django.db.models import Count, Q

from scansioni.services.monitor_trasmissioni import MONTH_LABELS, WEEKDAY_LABELS, _build_days, _month_shift, _safe_int
from scansioni.services.baserow_scansioni import LOCAL_TZ

from ..models import FileSysSpy, Nota
from .accesso import negozi_attivi_ordinati
from .baserow_primanota import TIPI_DOCUMENTO, elenco_scansioni


def _sysspy_per_giorno(dal, al):
    out = {}
    for f in FileSysSpy.objects.filter(data__range=(dal, al)).only(
            "negozio_id", "data", "totale_pos", "corrisp_non_riscosso", "totale_scontrini", "totale_giornaliero"):
        cella = out.setdefault((f.negozio_id, f.data.isoformat()), {"casse": 0, "squadrate": 0})
        cella["casse"] += 1
        if not f.quadrato:
            cella["squadrate"] += 1
    return out


def _note_aperte_per_giorno(dal, al):
    out = {}
    for r in (Nota.objects.filter(data__range=(dal, al), chiusa=False).values("negozio_id", "data")
              .annotate(n=Count("id"), contatto=Count("id", filter=Q(tipo=Nota.RICHIESTA_CONTATTO)))):
        out[(r["negozio_id"], r["data"].isoformat())] = r
    return out


def build_monitor(year=None, month=None, view_mode="month", week_start=None):
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
    scansioni = elenco_scansioni(data_da=dal.isoformat(), data_a=al.isoformat())

    aggregato = {}
    for s in scansioni:
        if not s["negozio_id"]:
            continue
        cella = aggregato.setdefault((s["negozio_id"], s["data_documento"]), {
            "total": 0, "worked": 0, "pending": 0, "versamenti_aperti": 0,
            "tipi": {t["id"]: 0 for t in TIPI_DOCUMENTO}})
        cella["total"] += 1
        cella["worked" if s["lavorato"] else "pending"] += 1
        if s["tipo_documento"] in cella["tipi"]:
            cella["tipi"][s["tipo_documento"]] += 1
        if s["versamento"] and not s["versamento_lavorato"]:
            cella["versamenti_aperti"] += 1

    sysspy = _sysspy_per_giorno(days[0], days[-1])
    note = _note_aperte_per_giorno(days[0], days[-1])
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
            spy = sysspy.get((negozio_id, iso), {"casse": 0, "squadrate": 0})
            n = note.get((negozio_id, iso), {"n": 0, "contatto": 0})
            if day > today:
                state = "future"
            elif not valori:
                state = "missing"
            else:
                state = "pending" if valori["pending"] else "worked"
                summary[state] += 1
                summary["documents"] += valori["total"]
            valori = valori or {"total": 0, "worked": 0, "pending": 0, "versamenti_aperti": 0, "tipi": {}}
            summary["versamenti_aperti"] += valori["versamenti_aperti"]
            summary["anomalie"] += n["n"]
            mancanti = [t["label"] for t in TIPI_DOCUMENTO[:2] if not valori["tipi"].get(t["id"])]
            celle.append({
                "date": iso,
                "day_number": day.day,
                "is_today": day == today,
                "state": state,
                "total": valori["total"],
                "worked": valori["worked"],
                "pending": valori["pending"],
                "tipi": [(t["sigla"], t["label"], valori["tipi"].get(t["id"], 0)) for t in TIPI_DOCUMENTO],
                "versamenti_aperti": valori["versamenti_aperti"],
                "casse_sysspy": spy["casse"],
                "squadrate": spy["squadrate"],
                "note_aperte": n["n"],
                "richieste_contatto": n["contatto"],
                "mancanti": mancanti if valori["total"] else [],
                "detail_url": "" if day > today else f"/primanota/giornata/{negozio_id}/{iso}/",
            })
        righe.append({"store_id": negozio_id, "code": str(negozio.get("codice") or "").strip(),
                      "description": str(negozio.get("descrizione") or "").strip(), "cells": celle})

    # "Senza invio" conta solo il mese corrente fino a oggi, come nel monitor carichi.
    giorni_correnti = {date(today.year, today.month, d).isoformat() for d in range(1, today.day + 1)}
    ricevuti = {k for k in aggregato if k[1] in giorni_correnti}
    ids = {_safe_int(n.get("id"), 0) for n in negozi}
    summary["missing_current_month"] = max(
        len(ids) * len(giorni_correnti) - sum(1 for k in ricevuti if k[0] in ids), 0)

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

