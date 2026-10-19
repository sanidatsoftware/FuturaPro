"""Sostituto di prova delle funzioni utenti/formattazione del portale."""

UTENTI = {}


def find_user_by_email(email):
    return UTENTI.get(email)


def get_user_role(user):
    ruolo = user.get("field_2253")
    return ruolo.get("value") if isinstance(ruolo, dict) else ruolo


def normalize_file_list(files):
    return [{"url": f.get("url", ""), "visible_name": f.get("visible_name") or f.get("name", "")} for f in files or []]


def format_date(value):
    return "/".join(reversed(value[:10].split("-"))) if value else ""


def format_datetime(value):
    return str(value or "")[:16].replace("T", " ")
