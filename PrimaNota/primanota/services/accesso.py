"""
Utenti, permessi e negozi: gli stessi di Scansioni PV, letti da Baserow con le
funzioni già presenti nel portale. Qui c'è solo ciò che cambia per la Prima Nota.
"""

from django.conf import settings

from scansioni.services.baserow_scansioni import (  # noqa: F401  (riesportate per il modulo)
    UTENTE_NOME,
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


def _menu_primanota_abilitato(user):
    # Casella "Menu_PrimaNota" della tabella Utenti, come "Menu_Scansioni" per Scansioni PV.
    # Finché il campo non è configurato la Prima Nota la vede solo l'Amministratore.
    campo = getattr(settings, "BASEROW_UTENTE_MENU_PRIMANOTA_FIELD", "")
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


def can_manage_primanota(user):
    """Condivisioni dei negozi, importazioni e orari: solo Amministratore."""
    return is_amministratore(user)


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
