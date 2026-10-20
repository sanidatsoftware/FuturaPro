"""Invio per email delle note sui versamenti contante, con la scansione in allegato."""

import logging
import mimetypes

import requests
from django.core.mail import EmailMessage, get_connection

from ..models import ImpostazioniEmail
from .importazione import decifra

log = logging.getLogger(__name__)


def configurata():
    imp = ImpostazioniEmail.corrente()
    return bool(imp.host and imp.mittente)


def _connessione(imp):
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=imp.host, port=imp.porta, username=imp.utente or None,
        password=decifra(imp.password_cifrata) or None,
        use_tls=imp.sicurezza == "tls", use_ssl=imp.sicurezza == "ssl", timeout=30)


def invia(destinatari, oggetto, testo, allegato_url=None, allegato_nome=None):
    """Invia il messaggio; l'allegato si scarica da Baserow. Solleva un'eccezione se non riesce."""
    imp = ImpostazioniEmail.corrente()
    if not imp.host or not imp.mittente:
        raise RuntimeError("Server di posta non configurato (Documenti Amministrativi > Chiusure Fiscali > Impostazioni).")
    messaggio = EmailMessage(oggetto, testo, imp.mittente, list(destinatari), connection=_connessione(imp))
    if allegato_url:
        risposta = requests.get(allegato_url, timeout=60)
        risposta.raise_for_status()
        nome = allegato_nome or allegato_url.rsplit("/", 1)[-1]
        tipo = risposta.headers.get("Content-Type") or mimetypes.guess_type(nome)[0] or "application/octet-stream"
        messaggio.attach(nome, risposta.content, tipo.split(";")[0])
    messaggio.send(fail_silently=False)
