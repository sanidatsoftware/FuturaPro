from calendar import monthrange
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from .baserow_scansioni import (
    LOCAL_TZ,
    SCAN_ATTIVO,
    SCAN_DATA_DOCUMENTO,
    SCAN_LAVORATO,
    SCAN_NEGOZIO,
    SCAN_TIPO_DOCUMENTO,
    extract_bool,
    extract_first_id,
    get_negozi_attivi,
    get_scansioni_raw,
    get_tipo_documento_label,
    normalize_baserow_date_value,
)


WEEKDAY_LABELS = ("LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM")
MONTH_LABELS = (
    "",
    "Gennaio",
    "Febbraio",
    "Marzo",
    "Aprile",
    "Maggio",
    "Giugno",
    "Luglio",
    "Agosto",
    "Settembre",
    "Ottobre",
    "Novembre",
    "Dicembre",
)


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _month_shift(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _build_days(year, month, view_mode, week_start=None):
    today = datetime.now(LOCAL_TZ).date()

    if view_mode == "week":
        try:
            start = date.fromisoformat(str(week_start or ""))
        except ValueError:
            reference_day = min(today.day, monthrange(year, month)[1])
            reference = date(year, month, reference_day)
            start = reference - timedelta(days=reference.weekday())

        return [start + timedelta(days=offset) for offset in range(7)]

    return [
        date(year, month, day_number)
        for day_number in range(1, monthrange(year, month)[1] + 1)
    ]


def _store_sort_key(store):
    code = str(store.get("codice") or "").strip()
    try:
        return (0, int(code), "")
    except ValueError:
        return (1, 0, code.casefold())


def build_transmission_monitor(year=None, month=None, view_mode="month", week_start=None):
    """
    Costruisce una matrice di sola lettura usando esclusivamente i dati
    già presenti nelle tabelle Negozi e Scansioni.

    Non crea campi, non aggiorna record e non modifica il flusso di upload.
    """
    today = datetime.now(LOCAL_TZ).date()
    year = _safe_int(year, today.year)
    month = _safe_int(month, today.month)

    if month < 1 or month > 12:
        year, month = today.year, today.month

    view_mode = "week" if view_mode == "week" else "month"
    days = _build_days(year, month, view_mode, week_start)
    valid_dates = {day.isoformat() for day in days}

    # La funzione esistente è paginata. Il monitor filtra poi soltanto
    # il periodo visualizzato senza modificare la procedura principale.
    raw_rows = get_scansioni_raw(filters={}, user_store_id=None)

    aggregate = {}

    for row in raw_rows:
        if not extract_bool(row.get(SCAN_ATTIVO, True)):
            continue

        document_date = normalize_baserow_date_value(
            row.get(SCAN_DATA_DOCUMENTO, "")
        )
        if document_date not in valid_dates:
            continue

        store_id = extract_first_id(row.get(SCAN_NEGOZIO, []))
        if store_id is None:
            continue

        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            continue

        key = (store_id, document_date)
        cell = aggregate.setdefault(
            key,
            {
                "total": 0,
                "worked": 0,
                "pending": 0,
                "carichi": 0,
                "resi": 0,
            },
        )

        cell["total"] += 1

        if extract_bool(row.get(SCAN_LAVORATO)):
            cell["worked"] += 1
        else:
            cell["pending"] += 1

        document_type = get_tipo_documento_label(
            row.get(SCAN_TIPO_DOCUMENTO)
        )
        if document_type == "DDT Carichi":
            cell["carichi"] += 1
        elif document_type == "DDT Resi":
            cell["resi"] += 1

    stores = sorted(get_negozi_attivi(), key=_store_sort_key)

    # I primi tre valori sono separati intenzionalmente:
    # - pending/worked/documents descrivono SOLO la tabella visualizzata;
    # - missing_current_month descrive SOLO il mese corrente fino a oggi.
    summary = {
        "pending": 0,
        "worked": 0,
        "documents": 0,
        "missing_current_month": 0,
    }

    current_month_dates = {
        date(today.year, today.month, day_number).isoformat()
        for day_number in range(1, today.day + 1)
    }
    current_month_transmissions = set()

    for row in raw_rows:
        if not extract_bool(row.get(SCAN_ATTIVO, True)):
            continue

        document_date = normalize_baserow_date_value(
            row.get(SCAN_DATA_DOCUMENTO, "")
        )
        if document_date not in current_month_dates:
            continue

        store_id = extract_first_id(row.get(SCAN_NEGOZIO, []))
        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            continue

        current_month_transmissions.add((store_id, document_date))

    matrix_rows = []

    for store in stores:
        store_id = _safe_int(store.get("id"), 0)
        code = str(store.get("codice") or "").strip()
        description = str(store.get("descrizione") or "").strip()
        cells = []

        for day in days:
            day_iso = day.isoformat()
            values = aggregate.get((store_id, day_iso))

            if day > today:
                state = "future"
                total = worked = pending = carichi = resi = 0
                detail_url = ""
            elif not values:
                state = "missing"
                total = worked = pending = carichi = resi = 0
                detail_url = ""
            else:
                total = values["total"]
                worked = values["worked"]
                pending = values["pending"]
                carichi = values["carichi"]
                resi = values["resi"]

                if pending:
                    state = "pending"
                    summary["pending"] += 1
                else:
                    state = "worked"
                    summary["worked"] += 1

                summary["documents"] += total

                query = {
                    "negozio": code,
                    "data_da": day_iso,
                    "data_a": day_iso,
                    "vista": "negozio",
                }
                if state == "pending":
                    query["solo_non_lavorati"] = "on"

                detail_url = "/scansioni/admin/?" + urlencode(query)

            cells.append(
                {
                    "date": day_iso,
                    "day_number": day.day,
                    "weekday": WEEKDAY_LABELS[day.weekday()],
                    "is_today": day == today,
                    "state": state,
                    "total": total,
                    "worked": worked,
                    "pending": pending,
                    "carichi": carichi,
                    "resi": resi,
                    "detail_url": detail_url,
                }
            )

        matrix_rows.append(
            {
                "store_id": store_id,
                "code": code,
                "description": description,
                "cells": cells,
            }
        )

    active_store_ids = {
        _safe_int(store.get("id"), 0)
        for store in stores
        if _safe_int(store.get("id"), 0)
    }
    expected_current_month = len(active_store_ids) * len(current_month_dates)
    received_current_month = sum(
        1
        for store_id, document_date in current_month_transmissions
        if store_id in active_store_ids and document_date in current_month_dates
    )
    summary["missing_current_month"] = max(
        expected_current_month - received_current_month,
        0,
    )

    previous_year, previous_month = _month_shift(year, month, -1)
    next_year, next_month = _month_shift(year, month, 1)

    if view_mode == "week":
        previous_week = days[0] - timedelta(days=7)
        next_week = days[0] + timedelta(days=7)
    else:
        previous_week = next_week = None

    return {
        "year": year,
        "month": month,
        "month_label": f"{MONTH_LABELS[month]} {year}",
        "view_mode": view_mode,
        "week_start": days[0].isoformat(),
        "week_end": days[-1].isoformat(),
        "previous_week": previous_week.isoformat() if previous_week else "",
        "next_week": next_week.isoformat() if next_week else "",
        "previous_year": previous_year,
        "previous_month": previous_month,
        "next_year": next_year,
        "next_month": next_month,
        "days": [
            {
                "date": day.isoformat(),
                "day_number": day.day,
                "weekday": WEEKDAY_LABELS[day.weekday()],
                "is_today": day == today,
            }
            for day in days
        ],
        "rows": matrix_rows,
        "summary": summary,
        "current_month_label": f"{MONTH_LABELS[today.month]} {today.year}",
    }
