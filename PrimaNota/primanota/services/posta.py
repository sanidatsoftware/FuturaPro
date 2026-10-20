"""
Invio per email delle note sui versamenti contante, con la scansione in allegato.

Usa la posta già configurata nel portale (/opt/tocal/email_config.json, la stessa degli
Incarichi): server, utente, password e mittente non si ripetono qui. Il file si legge
soltanto, senza riscriverlo.
"""

import json
import logging
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

import requests
from django.conf import settings

log = logging.getLogger(__name__)

CONFIG_PORTALE = "/opt/tocal/email_config.json"
NOME_MITTENTE = "TOCAL - Documenti Amministrativi"


def _percorso():
    return getattr(settings, "PRIMANOTA_EMAIL_CONFIG", CONFIG_PORTALE)


def configurazione():
    """Configurazione di posta del portale; {} se il file manca o non si legge."""
    try:
        with open(_percorso(), encoding="utf-8") as f:
            dati = json.load(f)
    except (OSError, ValueError):
        return {}
    return dati if isinstance(dati, dict) else {}


def stato():
    """Riepilogo per la pagina delle impostazioni, senza password."""
    c = configurazione()
    return {"percorso": _percorso(), "trovata": bool(c), "attiva": bool(c.get("enabled", True)) and bool(c.get("smtp_host")),
            "server": f"{c.get('smtp_host', '')}:{c.get('smtp_port', '')}" if c.get("smtp_host") else "",
            "mittente": c.get("from_email") or c.get("smtp_user") or "", "ssl": bool(c.get("smtp_ssl"))}


def configurata():
    return stato()["attiva"]


def _smtp(c, msg):
    """Come le Segnalazioni del portale: SSL diretto o STARTTLS."""
    host, porta = c.get("smtp_host") or "", int(c.get("smtp_port") or 465)
    utente, password = c.get("smtp_user") or "", c.get("smtp_password") or ""
    contesto = ssl.create_default_context()
    if c.get("smtp_ssl"):
        with smtplib.SMTP_SSL(host, porta, context=contesto, timeout=30) as smtp:
            if utente:
                smtp.login(utente, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=contesto)
            smtp.ehlo()
            if utente:
                smtp.login(utente, password)
            smtp.send_message(msg)


def invia(destinatari, oggetto, testo, allegato_url=None, allegato_nome=None):
    """Invia il messaggio; l'allegato si scarica da Baserow. Solleva un'eccezione se non riesce."""
    c = configurazione()
    if not c:
        raise RuntimeError(f"Configurazione email del portale non trovata ({_percorso()}).")
    if not c.get("enabled", True):
        raise RuntimeError("Invio email disattivato nella configurazione del portale.")
    if not c.get("smtp_host"):
        raise RuntimeError("Server di posta non indicato nella configurazione del portale.")
    mittente = c.get("from_email") or c.get("smtp_user")
    msg = EmailMessage()
    msg["Subject"] = " ".join(str(oggetto).split())
    msg["From"] = formataddr((NOME_MITTENTE, mittente))
    msg["To"] = ", ".join(destinatari)
    msg.set_content(testo)
    msg.add_alternative(
        f"<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#263238\">"
        f"<h2 style=\"color:#2d4055;margin:0 0 12px\">{escape(oggetto)}</h2>"
        f"<div>{escape(testo).replace(chr(10), '<br>')}</div></div>", subtype="html")
    if allegato_url:
        risposta = requests.get(allegato_url, timeout=60)
        risposta.raise_for_status()
        nome = allegato_nome or allegato_url.rsplit("/", 1)[-1]
        tipo = (risposta.headers.get("Content-Type") or mimetypes.guess_type(nome)[0] or "application/octet-stream").split(";")[0]
        principale, _, secondario = tipo.partition("/")
        msg.add_attachment(risposta.content, maintype=principale, subtype=secondario or "octet-stream", filename=nome)
    _smtp(c, msg)
