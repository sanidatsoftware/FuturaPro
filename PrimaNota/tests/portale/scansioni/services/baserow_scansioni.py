from datetime import datetime
import time
import requests
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings

from incarichi.services import baserow_client as baserow_client_module

from incarichi.services.baserow_client import (
    get_table_rows,
    get_table_rows_named,
    create_row,
    update_row,
    delete_row,
    upload_user_file,
)

from incarichi.services.baserow_layer import (
    find_user_by_email,
    get_user_role,
    normalize_file_list,
    format_date,
    format_datetime,
)


LOCAL_TZ = ZoneInfo("Europe/Rome")

# Tabelle Baserow
UTENTI_TABLE_ID = getattr(settings, "BASEROW_UTENTI_TABLE_ID", 272)
NEGOZI_TABLE_ID = getattr(settings, "BASEROW_NEGOZI_TABLE_ID", 880)
SCANSIONI_TABLE_ID = getattr(settings, "BASEROW_SCANSIONI_PV_TABLE_ID", 881)

# Tabella Utenti
UTENTE_NOME = "field_2250"
UTENTE_EMAIL = "field_2252"
UTENTE_RUOLO = "field_2253"
UTENTE_TIPO = "field_8146"
UTENTE_CODICE_NEGOZIO = "field_8147"
UTENTE_MENU_INCARICHI = "field_8165"
UTENTE_MENU_SCANSIONI = "field_8166"

TIPO_UTENTE_NEGOZIO = "Negozio"
TIPO_UTENTE_UFFICIO = "Ufficio"

# Tabella Negozi
NEGOZIO_CODICE = "field_8142"
NEGOZIO_DESCRIZIONE = "field_8143"
NEGOZIO_ATTIVO = "field_8144"
NEGOZIO_NOTE = "field_8145"

# Tabella Scansioni PV
SCAN_DATA_DOCUMENTO = "field_8149"
SCAN_NEGOZIO = "field_8150"
SCAN_ATTIVO = "field_8151"
SCAN_TIPO_DOCUMENTO = "field_8153"
SCAN_DOCUMENTO = "field_8154"
SCAN_NOTE = "field_8155"
SCAN_CARICATO_DA = "field_8156"
SCAN_DATA_UPLOAD = "field_8158"
SCAN_LAVORATO = "field_8159"
SCAN_LAVORATO_DA = "field_8160"
SCAN_DATA_LAVORAZIONE = "field_8162"

TIPO_DOCUMENTO_DDT_CARICHI_ID = 3398
TIPO_DOCUMENTO_DDT_RESI_ID = 3399

TIPI_DOCUMENTO = [
    {"id": TIPO_DOCUMENTO_DDT_CARICHI_ID, "label": "DDT Carichi"},
    {"id": TIPO_DOCUMENTO_DDT_RESI_ID, "label": "DDT Resi"},
]

# Cache breve dei negozi: evita una chiamata Baserow per ogni riga scansione.
_NEGOZI_CACHE = {"expires_at": 0.0, "rows": [], "by_id": {}}
_NEGOZI_CACHE_TTL_SECONDS = 300


def get_tipo_documento_label(value):
    raw = extract_first_value(value)

    if str(raw) == str(TIPO_DOCUMENTO_DDT_CARICHI_ID):
        return "DDT Carichi"

    if str(raw) == str(TIPO_DOCUMENTO_DDT_RESI_ID):
        return "DDT Resi"

    return raw or ""


def now_local_iso():
    return datetime.now(LOCAL_TZ).replace(microsecond=0).isoformat()


def normalize_baserow_date_value(value):
    if not value:
        return ""

    value = str(value)

    # Baserow può restituire anche data+ora, es. 2026-06-30T02:00:00.
    # Per filtri e ordinamenti usiamo solo YYYY-MM-DD.
    if len(value) >= 10:
        return value[:10]

    return value


def extract_value(value):
    if isinstance(value, dict):
        return value.get("value", "")

    if isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, dict):
                values.append(item.get("value", ""))
            else:
                values.append(item)
        return values

    return value


def extract_first_value(value):
    value = extract_value(value)

    if isinstance(value, list):
        return value[0] if value else ""

    return value or ""


def extract_first_id(value):
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get("id")
        return first

    return None


def extract_bool(value):
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str):
        return value.strip().lower() in ["true", "1", "sì", "si", "yes", "on"]
    return bool(value)


def get_current_user_from_request(request):
    email = request.session.get("baserow_user_email")

    if not email:
        return None

    return find_user_by_email(email)


def get_user_name(user):
    if not user:
        return ""

    return user.get(UTENTE_NOME, "")


def get_user_type(user):
    return extract_first_value(user.get(UTENTE_TIPO))


def user_menu_incarichi_enabled(user):
    return extract_bool(user.get(UTENTE_MENU_INCARICHI))


def user_menu_scansioni_enabled(user):
    return extract_bool(user.get(UTENTE_MENU_SCANSIONI))


def get_user_store_link(user):
    value = user.get(UTENTE_CODICE_NEGOZIO)

    if isinstance(value, list):
        return value

    return []


def get_user_store_id(user):
    return extract_first_id(user.get(UTENTE_CODICE_NEGOZIO))


def is_store_user(user):
    return get_user_type(user) == TIPO_UTENTE_NEGOZIO


def is_office_user(user):
    return get_user_type(user) == TIPO_UTENTE_UFFICIO


def can_access_scansioni(user):
    # Visibilità menu Scansioni PV controllata da Utenti.Menu_Scansioni.
    # Per Tipo Utente = Negozio resta obbligatorio anche Codice Negozio collegato.
    if not user_menu_scansioni_enabled(user):
        return False

    tipo_utente = get_user_type(user)

    if tipo_utente == TIPO_UTENTE_NEGOZIO:
        return bool(get_user_store_id(user))

    if tipo_utente == TIPO_UTENTE_UFFICIO:
        return True

    return False


def can_access_incarichi(user):
    # Visibilità menu Incarichi controllata da Utenti.Menu_Incarichi.
    # Le autorizzazioni operative interne restano quelle del modulo incarichi.
    if not user_menu_incarichi_enabled(user):
        return False

    return get_user_role(user) in ["Amministratore", "Direttore", "Dipendente", "Utente"]


def get_negozi_raw(force_refresh=False):
    now = time.monotonic()

    if (
        not force_refresh
        and _NEGOZI_CACHE["rows"]
        and _NEGOZI_CACHE["expires_at"] > now
    ):
        return _NEGOZI_CACHE["rows"]

    data = get_table_rows(NEGOZI_TABLE_ID)
    rows = data.get("results", [])

    _NEGOZI_CACHE["rows"] = rows
    _NEGOZI_CACHE["by_id"] = {
        row.get("id"): row
        for row in rows
        if row.get("id") is not None
    }
    _NEGOZI_CACHE["expires_at"] = now + _NEGOZI_CACHE_TTL_SECONDS

    return rows


def get_negozi_lookup():
    get_negozi_raw()
    return _NEGOZI_CACHE["by_id"]



def _get_baserow_api_root():
    """
    Ricava l'URL base dalla configurazione già usata dal progetto.
    Non modifica il client condiviso da Incarichi e Segnalazioni.
    """
    candidate_names = [
        "BASEROW_API_URL",
        "BASEROW_BASE_URL",
        "BASEROW_URL",
        "BASEROW_PUBLIC_URL",
    ]

    for name in candidate_names:
        value = getattr(settings, name, None)
        if value:
            return str(value).rstrip("/")

    for name in candidate_names + ["BASE_URL", "API_URL"]:
        value = getattr(baserow_client_module, name, None)
        if value:
            return str(value).rstrip("/")

    raise RuntimeError("URL Baserow non trovato nelle impostazioni del progetto.")


def _get_baserow_headers():
    headers = getattr(baserow_client_module, "HEADERS", None)
    if headers:
        return dict(headers)

    token = (
        getattr(settings, "BASEROW_API_TOKEN", None)
        or getattr(settings, "BASEROW_TOKEN", None)
    )
    if not token:
        raise RuntimeError("Token API Baserow non trovato.")

    return {"Authorization": f"Token {token}"}


def _build_rows_endpoint(table_id):
    root = _get_baserow_api_root()

    # Gestisce sia URL host semplici, sia URL che includono già /api.
    if "/api/database/rows/table" in root:
        prefix = root.split("/api/database/rows/table", 1)[0]
    elif root.endswith("/api"):
        prefix = root[:-4]
    else:
        prefix = root

    return f"{prefix}/api/database/rows/table/{int(table_id)}/"


def _get_scansioni_rows_filtered_api(filters=None, user_store_id=None):
    """
    Legge direttamente da Baserow solo le righe utili.

    La richiesta:
    - applica i filtri lato API;
    - ordina dai record più recenti;
    - segue tutte le pagine Baserow;
    - recupera solo metadati degli allegati, non il contenuto dei PDF.
    """
    filters = filters or {}
    endpoint = _build_rows_endpoint(SCANSIONI_TABLE_ID)

    params = {
        "size": 200,
        "user_field_names": "false",
        f"filter__{SCAN_ATTIVO}__equal": "true",
    }

    filtro_data_da = str(filters.get("data_da") or "").strip()
    filtro_data_a = str(filters.get("data_a") or "").strip()
    filtro_tipo_id = filters.get("tipo_id")
    solo_non_lavorati = bool(filters.get("solo_non_lavorati"))

    if solo_non_lavorati:
        params[f"filter__{SCAN_LAVORATO}__equal"] = "false"

    # Non applichiamo il range date direttamente all'API Baserow.
    # In Baserow 2.2.2 gli operatori date_after/date_before sono esclusivi:
    # un intervallo 23/07 - 24/07 escluderebbe sia il 23 sia il 24.
    # Il filtro inclusivo viene applicato più sotto in Python con >= e <=.
    if filtro_tipo_id:
        params[f"filter__{SCAN_TIPO_DOCUMENTO}__single_select_equal"] = str(filtro_tipo_id)

    if user_store_id:
        params[f"filter__{SCAN_NEGOZIO}__link_row_has"] = str(user_store_id)

    rows = []
    next_url = endpoint
    next_params = params

    while next_url:
        response = requests.get(
            next_url,
            headers=_get_baserow_headers(),
            params=next_params,
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                f"Errore Baserow {response.status_code}: {response.text}"
            )

        data = response.json()
        rows.extend(data.get("results", []))

        next_url = data.get("next")
        next_params = None

    rows.sort(key=lambda r: int(r.get("id") or 0), reverse=True)
    return rows


def _get_scansioni_rows_paginated_unfiltered():
    """
    Fallback sicuro: legge tutte le pagine Baserow senza filtri API.
    A differenza del vecchio get_table_rows, non si ferma ai primi 200 record.
    """
    endpoint = _build_rows_endpoint(SCANSIONI_TABLE_ID)
    params = {
        "size": 200,
        "user_field_names": "false",
    }

    rows = []
    next_url = endpoint
    next_params = params

    while next_url:
        response = requests.get(
            next_url,
            headers=_get_baserow_headers(),
            params=next_params,
            timeout=30,
        )

        if not response.ok:
            raise RuntimeError(
                f"Errore Baserow {response.status_code}: {response.text}"
            )

        data = response.json()
        rows.extend(data.get("results", []))
        next_url = data.get("next")
        next_params = None

    rows.sort(key=lambda r: int(r.get("id") or 0), reverse=True)
    return rows

def get_scansioni_raw(filters=None, user_store_id=None):
    """
    Prima tenta la lettura filtrata direttamente da Baserow.
    Se Baserow 2.2.2 rifiuta uno dei filtri, legge comunque TUTTE le pagine
    e lascia alla normalizzazione Python l'applicazione dei filtri.
    Non ritorna mai più soltanto i primi 200 record.
    """
    try:
        return _get_scansioni_rows_filtered_api(
            filters=filters,
            user_store_id=user_store_id,
        )
    except Exception as exc:
        print(
            "[SCANSIONI] Filtro API non accettato; "
            f"uso fallback paginato completo. Errore: {exc}"
        )
        return _get_scansioni_rows_paginated_unfiltered()


def normalize_negozio(row):
    return {
        "id": row.get("id"),
        "codice": row.get(NEGOZIO_CODICE, ""),
        "descrizione": row.get(NEGOZIO_DESCRIZIONE, ""),
        "attivo": bool(row.get(NEGOZIO_ATTIVO)),
        "note": row.get(NEGOZIO_NOTE, ""),
    }


def get_negozio_by_id(negozio_id, negozi_lookup=None):
    try:
        negozio_id = int(negozio_id)
    except Exception:
        return None

    lookup = negozi_lookup if negozi_lookup is not None else get_negozi_lookup()
    return lookup.get(negozio_id)


def get_negozi_attivi():
    return [
        normalize_negozio(row)
        for row in get_negozi_raw()
        if bool(row.get(NEGOZIO_ATTIVO))
    ]


def get_negozio_display_label_by_id(negozio_id, negozi_lookup=None):
    negozio = get_negozio_by_id(negozio_id, negozi_lookup)
    if not negozio:
        return ""

    codice = str(negozio.get(NEGOZIO_CODICE, "") or "").strip()
    descrizione = str(negozio.get(NEGOZIO_DESCRIZIONE, "") or "").strip()

    if codice and descrizione:
        return f"{codice} - {descrizione}"

    return codice or descrizione


def get_negozio_sort_code_by_id(negozio_id, negozi_lookup=None):
    negozio = get_negozio_by_id(negozio_id, negozi_lookup)
    if not negozio:
        return ""
    return str(negozio.get(NEGOZIO_CODICE, "") or "").strip()


def normalize_scansione(row, negozi_lookup=None):
    documento = normalize_file_list(row.get(SCAN_DOCUMENTO, []))
    negozio = row.get(SCAN_NEGOZIO, [])
    caricato_da = row.get(SCAN_CARICATO_DA, [])
    lavorato_da = row.get(SCAN_LAVORATO_DA, [])

    tipo_documento = get_tipo_documento_label(row.get(SCAN_TIPO_DOCUMENTO))

    negozio_id = extract_first_id(negozio)
    negozio_label = get_negozio_display_label_by_id(negozio_id, negozi_lookup) or extract_first_value(negozio)
    negozio_sort_code = get_negozio_sort_code_by_id(negozio_id, negozi_lookup) or str(negozio_label)

    return {
        "id": row.get("id"),
        "data_documento": normalize_baserow_date_value(row.get(SCAN_DATA_DOCUMENTO, "")),
        "data_documento_fmt": format_date(normalize_baserow_date_value(row.get(SCAN_DATA_DOCUMENTO, ""))),
        "negozio": negozio,
        "negozio_id": negozio_id,
        "negozio_label": negozio_label,
        "negozio_sort_code": negozio_sort_code,
        "tipo_documento": tipo_documento,
        "documento": documento,
        "note": row.get(SCAN_NOTE, ""),
        "caricato_da": caricato_da,
        "caricato_da_label": extract_first_value(caricato_da),
        "data_upload": row.get(SCAN_DATA_UPLOAD, ""),
        "data_upload_fmt": format_datetime(row.get(SCAN_DATA_UPLOAD, "")),
        "lavorato": bool(row.get(SCAN_LAVORATO)),
        "lavorato_da": lavorato_da,
        "lavorato_da_label": extract_first_value(lavorato_da),
        "data_lavorazione": row.get(SCAN_DATA_LAVORAZIONE, ""),
        "data_lavorazione_fmt": format_datetime(row.get(SCAN_DATA_LAVORAZIONE, "")),
        "attivo": bool(row.get(SCAN_ATTIVO)),
    }


def user_can_view_scansione(user, scansione):
    if is_office_user(user):
        return True

    if is_store_user(user):
        user_store_id = get_user_store_id(user)
        return user_store_id and scansione.get("negozio_id") == user_store_id

    return False


def get_scansioni_for_user(user, filters=None, max_results=None):
    """
    Carica le righe Scansioni una sola volta e risolve i negozi tramite una
    lookup già caricata. I filtri semplici vengono applicati sui dati grezzi
    prima della normalizzazione, riducendo sensibilmente il lavoro Python.
    """
    filters = filters or {}
    result = []
    user_store_id = get_user_store_id(user) if is_store_user(user) else None
    negozi_lookup = get_negozi_lookup()

    filtro_tipo = str(filters.get("tipo") or "").strip()
    filtro_data_da = str(filters.get("data_da") or "").strip()
    filtro_data_a = str(filters.get("data_a") or "").strip()
    solo_non_lavorati = bool(filters.get("solo_non_lavorati"))
    solo_lavorati = bool(filters.get("solo_lavorati"))
    lavorati_oggi = bool(filters.get("lavorati_oggi"))
    today_local = datetime.now(LOCAL_TZ).date().isoformat()

    filtro_tipo_id = None
    for tipo in TIPI_DOCUMENTO:
        if tipo.get("label") == filtro_tipo:
            filtro_tipo_id = tipo.get("id")
            break

    api_filters = {
        "tipo_id": filtro_tipo_id,
        "data_da": filtro_data_da,
        "data_a": filtro_data_a,
        "solo_non_lavorati": solo_non_lavorati,
    }

    raw_rows = get_scansioni_raw(
        filters=api_filters,
        user_store_id=user_store_id,
    )

    # Prima selezione sui campi grezzi, senza risolvere allegati/negozi.
    selected_rows = []
    for row in raw_rows:
        if not extract_bool(row.get(SCAN_ATTIVO, True)):
            continue

        raw_store_id = extract_first_id(row.get(SCAN_NEGOZIO, []))
        if user_store_id and raw_store_id != user_store_id:
            continue

        raw_date = normalize_baserow_date_value(row.get(SCAN_DATA_DOCUMENTO, ""))
        if filtro_data_da and raw_date < filtro_data_da:
            continue
        if filtro_data_a and raw_date > filtro_data_a:
            continue

        if filtro_tipo:
            raw_tipo = get_tipo_documento_label(row.get(SCAN_TIPO_DOCUMENTO))
            if raw_tipo != filtro_tipo:
                continue

        is_worked = extract_bool(row.get(SCAN_LAVORATO))

        if solo_non_lavorati and is_worked:
            continue
        if solo_lavorati and not is_worked:
            continue
        if lavorati_oggi:
            if not is_worked:
                continue
            worked_date = normalize_baserow_date_value(
                row.get(SCAN_DATA_LAVORAZIONE, "")
            )
            if worked_date != today_local:
                continue

        selected_rows.append(row)

    # I più recenti prima, utile soprattutto per lo storico del PV.
    selected_rows.sort(
        key=lambda row: (
            normalize_baserow_date_value(row.get(SCAN_DATA_DOCUMENTO, "")),
            str(row.get("id", "")),
        ),
        reverse=True,
    )

    if max_results:
        selected_rows = selected_rows[:max_results]

    for row in selected_rows:
        scansione = normalize_scansione(row, negozi_lookup=negozi_lookup)

        if user_can_view_scansione(user, scansione):
            result.append(scansione)

    # Controllo finale intenzionale per le viste rapide del cruscotto.
    # Questo secondo filtro rende il risultato indipendente dal percorso API
    # utilizzato (filtrato o fallback paginato).
    if solo_lavorati:
        result = [item for item in result if bool(item.get("lavorato"))]

    if solo_non_lavorati:
        result = [item for item in result if not bool(item.get("lavorato"))]

    if lavorati_oggi:
        result = [
            item for item in result
            if bool(item.get("lavorato"))
            and normalize_baserow_date_value(
                item.get("data_lavorazione", "")
            ) == today_local
        ]

    result.sort(
        key=lambda x: (
            str(x.get("negozio_sort_code", "")),
            x.get("data_documento", ""),
            x.get("tipo_documento", ""),
            str(x.get("id", "")),
        ),
        reverse=True,
    )
    return result


def create_scansione_pv(user, data_documento, tipo_documento_id, documento_file, note=""):
    if not can_access_scansioni(user):
        return {"error": "Utente non autorizzato alla gestione scansioni."}

    negozio_id = get_user_store_id(user)

    if not negozio_id and is_office_user(user):
        return {"error": "Per gli utenti ufficio usare il portale amministrativo."}

    if not negozio_id:
        return {"error": "Utente negozio non collegato ad alcun Codice Negozio."}

    uploaded_documento = []

    if documento_file:
        uploaded_documento.append(upload_user_file(documento_file))

    data = {
        SCAN_DATA_DOCUMENTO: data_documento,
        SCAN_NEGOZIO: [negozio_id],
        SCAN_ATTIVO: True,
        SCAN_TIPO_DOCUMENTO: int(tipo_documento_id),
        SCAN_DOCUMENTO: uploaded_documento,
        SCAN_NOTE: note,
        SCAN_CARICATO_DA: [user["id"]],
        SCAN_DATA_UPLOAD: now_local_iso(),
        SCAN_LAVORATO: False,
        SCAN_LAVORATO_DA: [],
        SCAN_DATA_LAVORAZIONE: None,
    }

    return create_row(
        table_id=SCANSIONI_TABLE_ID,
        data=data,
    )


def update_lavorato(user, scansione_id, lavorato):
    if not is_office_user(user):
        return {"error": "Solo utenti ufficio possono lavorare i documenti."}

    try:
        scansione_id = int(scansione_id)
    except Exception:
        return {"error": "ID scansione non valido."}

    data = {
        SCAN_LAVORATO: bool(lavorato),
    }

    if lavorato:
        data[SCAN_LAVORATO_DA] = [user["id"]]
        data[SCAN_DATA_LAVORAZIONE] = now_local_iso()
    else:
        data[SCAN_LAVORATO_DA] = []
        data[SCAN_DATA_LAVORAZIONE] = None

    return update_row(
        table_id=SCANSIONI_TABLE_ID,
        row_id=scansione_id,
        data=data,
    )


def delete_scansione(user, scansione_id):
    try:
        scansione_id = int(scansione_id)
    except Exception:
        return {"error": "ID scansione non valido."}

    scansione = None
    for item in get_scansioni_for_user(user):
        if item.get("id") == scansione_id:
            scansione = item
            break

    if not scansione:
        return {"error": "Scansione non trovata o non autorizzata."}

    if is_office_user(user):
        return delete_row(SCANSIONI_TABLE_ID, scansione_id)

    # Il negozio può eliminare solo se il documento non è stato ancora lavorato.
    if is_store_user(user) and not scansione.get("lavorato"):
        return delete_row(SCANSIONI_TABLE_ID, scansione_id)

    return {"error": "Documento già lavorato: cancellazione non consentita."}




_GLOBAL_SCAN_COUNTERS_CACHE = {
    "expires_at": 0,
    "data": None,
}


def get_global_scan_counters(force_refresh=False, cache_seconds=20):
    """
    Calcola i contatori sull'intera tabella Scansioni, indipendentemente
    dai filtri della pagina.

    Indicatori:
    - lavorati: record attivi con Lavorato=True;
    - da_lavorare: record attivi con Lavorato=False o vuoto;
    - giorni_aperti: date documento distinte con almeno un record da lavorare;
    - lavorati_oggi: record lavorati nella data odierna, in base alla
      Data lavorazione.

    La cache breve evita letture ripetute durante semplici refresh di pagina.
    Dopo una spunta il chiamante può usare force_refresh=True.
    """
    now_ts = time.time()

    if (
        not force_refresh
        and _GLOBAL_SCAN_COUNTERS_CACHE.get("data") is not None
        and now_ts < _GLOBAL_SCAN_COUNTERS_CACHE.get("expires_at", 0)
    ):
        return dict(_GLOBAL_SCAN_COUNTERS_CACHE["data"])

    rows = get_scansioni_raw(filters={}, user_store_id=None)
    today = datetime.now(LOCAL_TZ).date().isoformat()

    lavorati = 0
    da_lavorare = 0
    giorni_aperti = set()
    lavorati_oggi = 0

    for row in rows:
        if not extract_bool(row.get(SCAN_ATTIVO, True)):
            continue

        is_worked = extract_bool(row.get(SCAN_LAVORATO))

        if is_worked:
            lavorati += 1

            data_lavorazione = normalize_baserow_date_value(
                row.get(SCAN_DATA_LAVORAZIONE, "")
            )
            if data_lavorazione == today:
                lavorati_oggi += 1
        else:
            da_lavorare += 1

            data_documento = normalize_baserow_date_value(
                row.get(SCAN_DATA_DOCUMENTO, "")
            )
            if data_documento:
                giorni_aperti.add(data_documento)

    counters = {
        "lavorati": lavorati,
        "da_lavorare": da_lavorare,
        "giorni_aperti": len(giorni_aperti),
        "lavorati_oggi": lavorati_oggi,
        "data_oggi": format_date(today),
    }

    _GLOBAL_SCAN_COUNTERS_CACHE["data"] = dict(counters)
    _GLOBAL_SCAN_COUNTERS_CACHE["expires_at"] = now_ts + max(
        int(cache_seconds or 0),
        0,
    )

    return counters

DUPLICATE_ALLOWED_ROLES = {"Amministratore", "Direttore"}
DUPLICATE_BACKUP_DIR = Path("/opt/tocal/backups/scansioni_duplicati")


def can_manage_scansioni_duplicates(user):
    return bool(user) and get_user_role(user) in DUPLICATE_ALLOWED_ROLES


def _file_signature(file_item):
    """
    Firma prudente dell'allegato. Considera duplicati solo file con stesso
    nome, dimensione e tipo MIME. Non usa l'orario di caricamento.
    """
    if not isinstance(file_item, dict):
        return ("", 0, "")

    name = (
        file_item.get("original_name")
        or file_item.get("visible_name")
        or file_item.get("name")
        or ""
    )
    size = file_item.get("size") or 0
    mime = file_item.get("mime_type") or file_item.get("content_type") or ""

    try:
        size = int(size)
    except Exception:
        size = 0

    return (str(name).strip().lower(), size, str(mime).strip().lower())


def _duplicate_key_for_row(row):
    files = row.get(SCAN_DOCUMENTO) or []
    if not isinstance(files, list) or not files:
        return None

    signatures = tuple(sorted(_file_signature(item) for item in files))
    if not any(sig[0] for sig in signatures):
        return None

    store_id = extract_first_id(row.get(SCAN_NEGOZIO, []))
    doc_date = normalize_baserow_date_value(row.get(SCAN_DATA_DOCUMENTO, ""))
    doc_type = get_tipo_documento_label(row.get(SCAN_TIPO_DOCUMENTO))

    return (
        str(store_id or ""),
        doc_date,
        str(doc_type or "").strip(),
        signatures,
    )


def _duplicate_group_id(key):
    raw = json.dumps(key, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _choose_duplicate_keeper(rows):
    """
    Conserva prima un record già lavorato; a parità conserva il più vecchio.
    In questo modo non si perde un'eventuale lavorazione già registrata.
    """
    def priority(row):
        worked = extract_bool(row.get(SCAN_LAVORATO))
        row_id = int(row.get("id") or 0)
        return (0 if worked else 1, row_id)

    return sorted(rows, key=priority)[0]


def analyze_scansioni_duplicates(user):
    if not can_manage_scansioni_duplicates(user):
        return {"error": "Funzione riservata a Direttore e Amministratore."}

    raw_rows = get_scansioni_raw(filters={}, user_store_id=None)
    negozi_lookup = get_negozi_lookup()
    grouped = {}

    for row in raw_rows:
        if not extract_bool(row.get(SCAN_ATTIVO, True)):
            continue

        key = _duplicate_key_for_row(row)
        if key is None:
            continue

        grouped.setdefault(key, []).append(row)

    groups = []
    total_duplicates = 0

    for key, rows in grouped.items():
        if len(rows) < 2:
            continue

        keeper = _choose_duplicate_keeper(rows)
        delete_rows = [row for row in rows if row.get("id") != keeper.get("id")]
        total_duplicates += len(delete_rows)

        normalized = [
            normalize_scansione(row, negozi_lookup=negozi_lookup)
            for row in sorted(rows, key=lambda r: int(r.get("id") or 0))
        ]

        groups.append({
            "group_id": _duplicate_group_id(key),
            "negozio": normalized[0].get("negozio_label") if normalized else "",
            "data_documento": normalized[0].get("data_documento_fmt") if normalized else "",
            "tipo_documento": normalized[0].get("tipo_documento") if normalized else "",
            "file_name": key[3][0][0] if key[3] else "",
            "file_size": key[3][0][1] if key[3] else 0,
            "copies": len(rows),
            "keeper_id": keeper.get("id"),
            "delete_ids": [row.get("id") for row in delete_rows],
            "rows": normalized,
        })

    groups.sort(
        key=lambda g: (
            g.get("negozio", ""),
            g.get("data_documento", ""),
            g.get("tipo_documento", ""),
            g.get("file_name", ""),
        )
    )

    return {
        "groups": groups,
        "group_count": len(groups),
        "duplicate_count": total_duplicates,
        "scanned_count": len(raw_rows),
    }


def _backup_duplicate_rows(rows, user):
    DUPLICATE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    path = DUPLICATE_BACKUP_DIR / f"duplicati_scansioni_{timestamp}.json"

    payload = {
        "created_at": now_local_iso(),
        "created_by": get_user_name(user),
        "role": get_user_role(user),
        "table_id": SCANSIONI_TABLE_ID,
        "rows": rows,
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)


def delete_scansioni_duplicate_groups(user, selected_group_ids):
    if not can_manage_scansioni_duplicates(user):
        return {"error": "Funzione riservata a Direttore e Amministratore."}

    selected_group_ids = {str(value) for value in (selected_group_ids or []) if value}
    if not selected_group_ids:
        return {"error": "Nessun gruppo duplicato selezionato."}

    analysis = analyze_scansioni_duplicates(user)
    if "error" in analysis:
        return analysis

    selected_groups = [
        group for group in analysis["groups"]
        if group["group_id"] in selected_group_ids
    ]

    if not selected_groups:
        return {"error": "I gruppi selezionati non risultano più duplicati."}

    raw_rows = get_scansioni_raw(filters={}, user_store_id=None)
    rows_by_id = {int(row.get("id")): row for row in raw_rows if row.get("id")}

    delete_ids = []
    backup_rows = []
    for group in selected_groups:
        for row_id in group["delete_ids"]:
            row_id = int(row_id)
            if row_id in rows_by_id:
                delete_ids.append(row_id)
                backup_rows.append(rows_by_id[row_id])

    backup_path = _backup_duplicate_rows(backup_rows, user)

    deleted = []
    errors = []
    for row_id in delete_ids:
        try:
            delete_row(SCANSIONI_TABLE_ID, row_id)
            deleted.append(row_id)
        except Exception as exc:
            errors.append({"id": row_id, "error": str(exc)})

    return {
        "success": not errors,
        "deleted_count": len(deleted),
        "deleted_ids": deleted,
        "errors": errors,
        "backup_path": backup_path,
    }

def build_admin_tree(scansioni):
    tree = {}

    for item in scansioni:
        negozio = item.get("negozio_label") or "Senza negozio"
        data = item.get("data_documento_fmt") or "Senza data"
        tipo = item.get("tipo_documento") or "Senza tipo"

        tree.setdefault(negozio, {})
        tree[negozio].setdefault(data, {})
        tree[negozio][data].setdefault(tipo, [])
        tree[negozio][data][tipo].append(item)

    return tree


def build_admin_tree_by_date(scansioni):
    tree = {}

    ordered = sorted(
        scansioni,
        key=lambda x: (
            x.get("data_documento", ""),
            str(x.get("negozio_sort_code", "")),
            str(x.get("tipo_documento", "")),
        ),
        reverse=True,
    )

    for item in ordered:
        data = item.get("data_documento_fmt") or "Senza data"
        negozio = item.get("negozio_label") or "Senza negozio"
        tipo = item.get("tipo_documento") or "Senza tipo"

        tree.setdefault(data, {})
        tree[data].setdefault(negozio, {})
        tree[data][negozio].setdefault(tipo, [])
        tree[data][negozio][tipo].append(item)

    return tree


def sort_scansioni_for_table(scansioni):
    return sorted(
        scansioni,
        key=lambda x: (
            str(x.get("negozio_sort_code", "")),
            x.get("data_documento", ""),
            str(x.get("tipo_documento", "")),
            str(x.get("id", "")),
        ),
    )
