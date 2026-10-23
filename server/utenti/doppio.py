"""La verifica in due passaggi (TOTP, RFC 6238): il codice di 6 cifre che cambia ogni 30 secondi
nelle app di autenticazione (Google Authenticator, Microsoft Authenticator, …).

Il segreto dell'utente è conservato cifrato (core.email.cifra, chiave derivata da SECRET_KEY);
un codice già usato non vale una seconda volta. Serve per il Controllo Remoto
(teleassistenza): prima di aprire lo schermo di un PC, ogni tanto, si chiede il codice.
"""

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote

PASSO = 30
CIFRE = 6
# Si accetta anche il codice del passo prima e di quello dopo (orologi un po' diversi).
TOLLERANZA = 1


def nuovo_segreto() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _codice(segreto: str, passo: int) -> str:
    chiave = base64.b32decode(segreto + "=" * (-len(segreto) % 8))
    impronta = hmac.new(chiave, struct.pack(">Q", passo), hashlib.sha1).digest()
    inizio = impronta[-1] & 0x0F
    numero = struct.unpack(">I", impronta[inizio:inizio + 4])[0] & 0x7FFFFFFF
    return str(numero % 10**CIFRE).zfill(CIFRE)


def codice_attuale(segreto: str, adesso: float | None = None) -> str:
    return _codice(segreto, int((adesso or time.time()) // PASSO))


def passo_valido(segreto: str, codice: str, ultimo_passo: int = 0, adesso: float | None = None) -> int | None:
    """Il passo del codice se è giusto e non ancora usato (> ultimo_passo), altrimenti None."""
    codice = "".join(c for c in str(codice or "") if c.isdigit())
    if len(codice) != CIFRE:
        return None
    attuale = int((adesso or time.time()) // PASSO)
    for passo in range(attuale - TOLLERANZA, attuale + TOLLERANZA + 1):
        if passo > ultimo_passo and hmac.compare_digest(_codice(segreto, passo), codice):
            return passo
    return None


def indirizzo_app(segreto: str, utente: str, emittente: str = "FuturaPro") -> str:
    """L'indirizzo otpauth:// da mostrare come QR all'app di autenticazione."""
    return f"otpauth://totp/{quote(emittente)}:{quote(utente)}?secret={segreto}&issuer={quote(emittente)}&digits={CIFRE}&period={PASSO}"


def verifica_utente(utente, codice: str) -> bool:
    """Controlla il codice dell'utente (con la verifica attiva) e lo segna come usato."""
    from core.email import decifra

    if not utente.doppio_attivo:
        return False
    passo = passo_valido(decifra(utente.doppio_segreto), codice, utente.doppio_ultimo_passo)
    if passo is None:
        return False
    utente.doppio_ultimo_passo = passo
    utente.save(update_fields=["doppio_ultimo_passo"])
    return True
