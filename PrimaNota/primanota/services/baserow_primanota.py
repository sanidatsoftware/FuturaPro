"""
Scansioni di Prima Nota su Baserow, con la stessa logica di Scansioni PV.

La tabella si indica in settings.BASEROW_PRIMANOTA_TABLE_ID. I campi si leggono
e scrivono per nome (user_field_names=true), così non serve configurare gli id
dei campi: basta creare la tabella con i nomi qui sotto (vedi README).
"""

from datetime import datetime

import requests
from django.conf import settings

from incarichi.services.baserow_client import upload_user_file
from incarichi.services.baserow_layer import format_date, format_datetime, normalize_file_list
from scansioni.services.baserow_scansioni import (
    LOCAL_TZ,
    _build_rows_endpoint,
    _get_baserow_headers,
    extract_bool,
    extract_first_id,
    extract_first_value,
    normalize_baserow_date_value,
)

CAMPO_DATA = "Data Documento"
CAMPO_NEGOZIO = "Negozio"
CAMPO_ATTIVO = "Attivo"
CAMPO_TIPO = "Tipo Documento"
CAMPO_CASSA = "Cassa"
CAMPO_DOCUMENTO = "Documento"
CAMPO_NOTE = "Note"
CAMPO_CARICATO_DA = "Caricato Da"
CAMPO_DATA_UPLOAD = "Data Upload"
CAMPO_LAVORATO = "Lavorato"
CAMPO_LAVORATO_DA = "Lavorato Da"
CAMPO_DATA_LAVORAZIONE = "Data Lavorazione"
CAMPO_VERS_LAVORATO = "Versamento Lavorato"
CAMPO_VERS_LAVORATO_DA = "Versamento Lavorato Da"
CAMPO_VERS_DATA = "Data Lavorazione Versamento"

CHIUSURA_FISCALE = "Chiusura fiscale"
CHIUSURA_POS = "Chiusure POS bancari"
RESI = "Resi"
TRANSAZIONI_ABORTITE = "Transazioni abortite"
VERSAMENTO_CONTANTE = "Versamenti contante"
FATTURE_SPESE = "Fatture spese del giorno"

# Ordine di presentazione in tutte le pagine. "chiave" è usata negli URL e nel monitor.
TIPI_DOCUMENTO = [
    {"id": CHIUSURA_FISCALE, "label": CHIUSURA_FISCALE, "chiave": "fiscale", "sigla": "F"},
    {"id": CHIUSURA_POS, "label": CHIUSURA_POS, "chiave": "pos", "sigla": "P"},
    {"id": RESI, "label": RESI, "chiave": "resi", "sigla": "R"},
    {"id": TRANSAZIONI_ABORTITE, "label": TRANSAZIONI_ABORTITE, "chiave": "abortite", "sigla": "A"},
    {"id": FATTURE_SPESE, "label": FATTURE_SPESE, "chiave": "fatture", "sigla": "S"},
    {"id": VERSAMENTO_CONTANTE, "label": VERSAMENTO_CONTANTE, "chiave": "versamenti", "sigla": "V"},
]
TIPI_VALIDI = {t["id"] for t in TIPI_DOCUMENTO}


def _tabella():
    table_id = getattr(settings, "BASEROW_PRIMANOTA_TABLE_ID", None)
    if not table_id:
        raise RuntimeError("Configurare BASEROW_PRIMANOTA_TABLE_ID nelle impostazioni del portale.")
    return int(table_id)


def _ora_locale():
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


def _richiesta(metodo, url, **kwargs):
    risposta = requests.request(metodo, url, headers=_get_baserow_headers(), timeout=60, **kwargs)
    if not risposta.ok:
        raise RuntimeError(f"Errore Baserow {risposta.status_code}: {risposta.text[:300]}")
    return risposta.json() if risposta.content else {}


def normalizza(row):
    allegati = row.get(CAMPO_DOCUMENTO) or []
    documento = normalize_file_list(allegati)
    # Primo allegato da mostrare in anteprima nella giornata (PDF in iframe, immagini come img).
    primo = allegati[0] if allegati and isinstance(allegati[0], dict) else {}
    anteprima = {"url": primo.get("url", ""), "immagine": bool(primo.get("is_image"))} if primo.get("url") else None
    data = normalize_baserow_date_value(row.get(CAMPO_DATA, ""))
    tipo = str(extract_first_value(row.get(CAMPO_TIPO)) or "")
    cassa = row.get(CAMPO_CASSA)
    try:
        cassa = int(cassa) if cassa not in (None, "") else None
    except (TypeError, ValueError):
        cassa = None
    return {
        "id": row.get("id"),
        "data_documento": data,
        "data_documento_fmt": format_date(data),
        "negozio_id": extract_first_id(row.get(CAMPO_NEGOZIO) or []),
        "tipo_documento": tipo,
        "versamento": tipo == VERSAMENTO_CONTANTE,
        "cassa": cassa,
        "documento": documento,
        "anteprima": anteprima,
        "note": row.get(CAMPO_NOTE) or "",
        "caricato_da_label": extract_first_value(row.get(CAMPO_CARICATO_DA) or []),
        "data_upload_fmt": format_datetime(row.get(CAMPO_DATA_UPLOAD, "")),
        "lavorato": extract_bool(row.get(CAMPO_LAVORATO)),
        "lavorato_da_label": extract_first_value(row.get(CAMPO_LAVORATO_DA) or []),
        "data_lavorazione_fmt": format_datetime(row.get(CAMPO_DATA_LAVORAZIONE, "")),
        "versamento_lavorato": extract_bool(row.get(CAMPO_VERS_LAVORATO)),
        "versamento_lavorato_da_label": extract_first_value(row.get(CAMPO_VERS_LAVORATO_DA) or []),
        "versamento_data_fmt": format_datetime(row.get(CAMPO_VERS_DATA, "")),
    }


def elenco_scansioni(negozio_id=None, data_da="", data_a="", max_risultati=None):
    """
    Scansioni attive, dalla più recente. Le righe arrivano ordinate per data
    decrescente, quindi la lettura si ferma appena si supera l'inizio del periodo.
    """
    params = {
        "size": 200,
        "user_field_names": "true",
        "order_by": f"-{CAMPO_DATA}",
        f"filter__{CAMPO_ATTIVO}__boolean": "1",
    }
    if negozio_id:
        params[f"filter__{CAMPO_NEGOZIO}__link_row_has"] = str(negozio_id)

    out = []
    url, prossimi = _build_rows_endpoint(_tabella()), params
    while url:
        dati = _richiesta("GET", url, params=prossimi)
        fine = False
        for row in dati.get("results", []):
            s = normalizza(row)
            if data_da and s["data_documento"] and s["data_documento"] < data_da:
                fine = True
                break
            if data_a and s["data_documento"] > data_a:
                continue
            if negozio_id and s["negozio_id"] != int(negozio_id):
                continue
            out.append(s)
            if max_risultati and len(out) >= max_risultati:
                return out
        if fine:
            break
        url, prossimi = dati.get("next"), None
    return out


def leggi_scansione(scansione_id):
    url = f"{_build_rows_endpoint(_tabella())}{int(scansione_id)}/"
    return normalizza(_richiesta("GET", url, params={"user_field_names": "true"}))


def crea_scansione(user, negozio_id, data_documento, tipo_documento, documento_file, cassa=None, note=""):
    if tipo_documento not in TIPI_VALIDI:
        return {"error": "Tipo documento non valido."}
    tabella = _tabella()  # prima di caricare il file, così senza configurazione non resta un allegato orfano
    dati = {
        CAMPO_DATA: data_documento,
        CAMPO_NEGOZIO: [int(negozio_id)],
        CAMPO_ATTIVO: True,
        CAMPO_TIPO: tipo_documento,
        CAMPO_CASSA: cassa,
        CAMPO_DOCUMENTO: [upload_user_file(documento_file)],
        CAMPO_NOTE: note,
        CAMPO_CARICATO_DA: [user["id"]],
        CAMPO_DATA_UPLOAD: _ora_locale(),
        CAMPO_LAVORATO: False,
        CAMPO_VERS_LAVORATO: False,
    }
    return _richiesta("POST", _build_rows_endpoint(tabella), params={"user_field_names": "true"}, json=dati)


def aggiorna_lavorato(user, scansione_id, lavorato, versamento=False):
    """Lavorato della scansione, oppure (versamento=True) il flag separato dei versamenti contante."""
    if versamento:
        if not leggi_scansione(scansione_id)["versamento"]:
            return {"error": "Il flag versamento vale solo per i Versamenti contante."}
        campi = (CAMPO_VERS_LAVORATO, CAMPO_VERS_LAVORATO_DA, CAMPO_VERS_DATA)
    else:
        campi = (CAMPO_LAVORATO, CAMPO_LAVORATO_DA, CAMPO_DATA_LAVORAZIONE)
    dati = {
        campi[0]: bool(lavorato),
        campi[1]: [user["id"]] if lavorato else [],
        campi[2]: _ora_locale() if lavorato else None,
    }
    url = f"{_build_rows_endpoint(_tabella())}{int(scansione_id)}/"
    return _richiesta("PATCH", url, params={"user_field_names": "true"}, json=dati)


def elimina_scansione(scansione_id):
    url = f"{_build_rows_endpoint(_tabella())}{int(scansione_id)}/"
    _richiesta("DELETE", url)
    return {"ok": True}
