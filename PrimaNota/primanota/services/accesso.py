"""
Utenti, permessi e negozi: gli stessi di Scansioni PV, letti da Baserow con le
funzioni già presenti nel portale. Qui c'è solo ciò che cambia per la Prima Nota.
"""

from django.conf import settings

from scansioni.services.baserow_scansioni import (  # noqa: F401  (riesportate per il modulo)
    DUPLICATE_ALLOWED_ROLES,
    UTENTE_NOME,
    extract_bool,
    get_current_user_from_request,
    get_negozi_attivi,
    get_negozi_lookup,
    get_user_store_id,
    is_office_user,
    is_store_user,
    normalize_negozio,
    user_menu_scansioni_enabled,
)
from incarichi.services.baserow_layer import get_user_role


def _menu_primanota_abilitato(user):
    # Campo booleano "Menu_PrimaNota" della tabella Utenti. Finché non è configurato
    # vale la stessa abilitazione di Scansioni PV.
    campo = getattr(settings, "BASEROW_UTENTE_MENU_PRIMANOTA_FIELD", "")
    if campo:
        return extract_bool(user.get(campo))
    return user_menu_scansioni_enabled(user)


def can_access_primanota(user):
    if not user or not _menu_primanota_abilitato(user):
        return False
    if is_store_user(user):
        return bool(get_user_store_id(user))
    return is_office_user(user)


def can_manage_primanota(user):
    """Configurazione delle condivisioni e importazione: Amministratore e Direttore."""
    return bool(user) and is_office_user(user) and get_user_role(user) in DUPLICATE_ALLOWED_ROLES


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
