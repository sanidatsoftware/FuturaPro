"""L'invio delle email (allarmi, rapporti, …).

Server SMTP, account e mittente sono dell'azienda (``pannello.ImpostazioniEmail``, nel
contesto del cliente corrente): ognuna ha il suo dominio e la sua casella. In mancanza valgono,
se ci sono, le variabili FUTURAPRO_EMAIL_… del server. I destinatari li decide ogni funzione.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

SMTP = "django.core.mail.backends.smtp.EmailBackend"


def _fernet() -> Fernet:
    chiave = hashlib.sha256(f"futurapro-email:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(chiave))


def cifra(testo: str) -> str:
    return _fernet().encrypt(testo.encode()).decode() if testo else ""


def decifra(testo: str) -> str:
    try:
        return _fernet().decrypt(testo.encode()).decode() if testo else ""
    except InvalidToken:
        return ""  # SECRET_KEY cambiata: la password va reinserita


def _dal_pannello():
    from pannello.models import ImpostazioniEmail

    try:
        impostazioni = ImpostazioniEmail.objects.first()
    except Exception:  # fuori dal contesto di un cliente
        return None
    if impostazioni and impostazioni.attivo and impostazioni.host:
        return impostazioni
    return None


def configurata() -> bool:
    return _dal_pannello() is not None or bool(settings.EMAIL_HOST)


def origine() -> str:
    """Da dove viene la configurazione: «pannello», «server» o «nessuna»."""
    if _dal_pannello() is not None:
        return "pannello"
    return "server" if settings.EMAIL_HOST else "nessuna"


def _connessione():
    impostazioni = _dal_pannello()
    if impostazioni is None:
        return get_connection(), settings.DEFAULT_FROM_EMAIL
    # Nei test (backend in memoria) non si apre nessuna connessione vera.
    backend = settings.EMAIL_BACKEND if settings.EMAIL_BACKEND.endswith("locmem.EmailBackend") else SMTP
    connessione = get_connection(
        backend=backend, host=impostazioni.host, port=impostazioni.porta,
        username=impostazioni.utente or None, password=decifra(impostazioni.password_cifrata) or None,
        use_tls=impostazioni.sicurezza == "starttls", use_ssl=impostazioni.sicurezza == "ssl", timeout=20,
    )
    return connessione, impostazioni.mittente or impostazioni.utente or settings.DEFAULT_FROM_EMAIL


def invia(oggetto: str, testo: str, destinatari: list[str], html: str | None = None, allegati=()) -> None:
    """Manda un'email; solleva un'eccezione se non parte. ``allegati``: (nome, contenuto, tipo)."""
    if not destinatari:
        raise ValueError("Nessun destinatario.")
    connessione, mittente = _connessione()
    messaggio = EmailMultiAlternatives(oggetto, testo, mittente, list(destinatari), connection=connessione)
    if html:
        messaggio.attach_alternative(html, "text/html")
    for nome, contenuto, tipo in allegati:
        messaggio.attach(nome, contenuto, tipo)
    messaggio.send(fail_silently=False)
