"""
Utenti, permessi e negozi: gli stessi di Scansioni PV, letti da Baserow con le
funzioni già presenti nel portale. Qui c'è solo ciò che cambia per la Prima Nota.
"""

import logging
import time

import requests
from django.conf import settings

from scansioni.services.baserow_scansioni import (  # noqa: F401  (riesportate per il modulo)
    UTENTE_NOME,
    UTENTI_TABLE_ID,
    _build_rows_endpoint,
    _get_baserow_headers,
    extract_bool,
    get_current_user_from_request,
    get_negozi_attivi,
    get_negozi_lookup,
    get_user_store_id,
    is_office_user,
    is_store_user,
    normalize_negozio,
)
from incarichi.services.baserow_layer import get_user_role


AMMINISTRATORE = "Amministratore"


def is_amministratore(user):
    return bool(user) and get_user_role(user) == AMMINISTRATORE


NOME_CAMPO_MENU = "Menu_PrimaNota"
_campo_menu = {"valore": None, "scade": 0.0}


def campo_menu_primanota():
    """
    Id ("field_NNNN") della casella "Menu_PrimaNota" della tabella Utenti. Si legge da
    settings se indicato, altrimenti si cerca la colonna per nome in Baserow (così basta
    aggiungerla in Baserow). Il risultato resta in memoria 10 minuti.
    """
    campo = getattr(settings, "BASEROW_UTENTE_MENU_PRIMANOTA_FIELD", "")
    if campo:
        return campo
    adesso = time.monotonic()
    if _campo_menu["scade"] > adesso:
        return _campo_menu["valore"]
    valore = None
    try:
        url = _build_rows_endpoint(UTENTI_TABLE_ID).replace("/database/rows/table/", "/database/fields/table/")
        r = requests.get(url, headers=_get_baserow_headers(), timeout=15)
        r.raise_for_status()
        valore = next((f"field_{c['id']}" for c in r.json() if c.get("name") == NOME_CAMPO_MENU), None)
    except Exception:
        logging.getLogger(__name__).exception("Lettura dei campi della tabella Utenti")
    _campo_menu.update(valore=valore, scade=adesso + 600)
    return valore


def _menu_primanota_abilitato(user):
    # Casella "Menu_PrimaNota" della tabella Utenti, come "Menu_Scansioni" per Scansioni PV.
    # Se la colonna non c'è, la Prima Nota la vede solo l'Amministratore.
    campo = campo_menu_primanota()
    return bool(campo) and extract_bool(user.get(campo))


def can_access_primanota(user):
    if not user:
        return False
    if is_amministratore(user):
        return True
    if not _menu_primanota_abilitato(user):
        return False
    if is_store_user(user):
        return bool(get_user_store_id(user))
    return is_office_user(user)


RUOLI_GESTIONE = {AMMINISTRATORE, "Direttore"}


def can_manage_primanota(user):
    """Condivisioni dei negozi, importazioni, orari e regole: Amministratore e Direttore."""
    return bool(user) and get_user_role(user) in RUOLI_GESTIONE


def nome_utente(user):
    return (user or {}).get(UTENTE_NOME, "") or ""


def negozi_attivi_ordinati():
    def chiave(n):
        codice = str(n.get("codice") or "").strip()
        return (0, int(codice), "") if codice.isdigit() else (1, 0, codice.casefold())
    return sorted(get_negozi_attivi(), key=chiave)


def negozio(negozio_id):
    try:
        row = get_negozi_lookup().get(int(negozio_id))
    except (TypeError, ValueError):
        return None
    return normalize_negozio(row) if row else None


def etichetta_negozio(n):
    if not n:
        return ""
    codice = str(n.get("codice") or "").strip()
    descrizione = str(n.get("descrizione") or "").strip()
    return f"{codice} - {descrizione}" if codice and descrizione else codice or descrizione
