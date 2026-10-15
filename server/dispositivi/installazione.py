"""I comandi pronti per installare il player su un PC Windows, con le impronte dei certificati.

Lo script di installazione deve fidarsi del certificato interno del server e di quello del Totem
Master del negozio. Invece di far confrontare a occhio due stringhe lunghe, il pannello (aperto in
HTTPS, quindi già sicuro) mette le impronte giuste nel comando: lo script le confronta da solo e
si ferma solo se non coincidono. L'impronta del totem la riferisce il suo player al server.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import urllib.request
from pathlib import Path

from django.conf import settings

IMPRONTA = re.compile(r"^[0-9A-F]{64}$")


def impronta_pem(testo: str) -> str:
    """SHA-256 del certificato (DER) in esadecimale maiuscolo, come la calcola lo script; "" se non c'è."""
    corpo = re.search(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", testo, re.S)
    if not corpo:
        return ""
    try:
        der = base64.b64decode("".join(corpo.group(1).split()))
    except ValueError:
        return ""
    return hashlib.sha256(der).hexdigest().upper()


def impronta_certificato(percorso: str) -> str:
    if not percorso:
        return ""
    try:
        return impronta_pem(Path(percorso).read_text())
    except OSError:
        return ""


_letta = {"quando": 0.0, "impronta": ""}


def impronta_server() -> str:
    """L'impronta del certificato interno del server: dal file indicato, o chiedendola a Caddy
    all'indirizzo da cui la scaricano i player (risposta tenuta 10 minuti). "" se non ce n'è uno."""
    impronta = impronta_certificato(settings.FUTURAPRO_CA_CERT)
    if impronta or not settings.FUTURAPRO_CA_URL:
        return impronta
    if time.monotonic() - _letta["quando"] < 600:
        return _letta["impronta"]
    impronta = ""
    try:
        richiesta = urllib.request.Request(settings.FUTURAPRO_CA_URL)
        if settings.FUTURAPRO_INDIRIZZO:
            richiesta.add_header("Host", settings.FUTURAPRO_INDIRIZZO)
        with urllib.request.urlopen(richiesta, timeout=3) as risposta:
            impronta = impronta_pem(risposta.read(100_000).decode("ascii", "ignore"))
    except (OSError, ValueError):
        impronta = ""
    _letta.update(quando=time.monotonic(), impronta=impronta)
    return impronta


def indirizzo_server(request) -> str:
    return settings.FUTURAPRO_INDIRIZZO or request.get_host().split(":")[0]


def comandi(request, sedi, monitor) -> dict:
    """Server, impronta e, per ogni sede, il comando del totem e quello dei monitor."""
    server = indirizzo_server(request)
    impronta = impronta_server()
    base = (f"irm http://{server}/installa/player-windows.ps1 -OutFile $env:TEMP\\futurapro.ps1; "
            f"powershell -ExecutionPolicy Bypass -File $env:TEMP\\futurapro.ps1 -Server {server}")
    if impronta:
        base += f" -Impronta {impronta}"
    masters = {m.sede_id: m for m in monitor if m.totem_master}
    risultato = []
    for sede in sedi:
        master = masters.get(sede.id)
        impronta_totem = ((master.info_dispositivo or {}).get("impronta_totem") or "") if master else ""
        voce = {"id": str(sede.id), "nome": sede.nome, "totem": sede.indirizzo_totem or "", "impronta_totem": impronta_totem,
                "comando_totem": f"{base} -Tipo totem" + (f" -IndirizzoTotem {sede.indirizzo_totem}" if sede.indirizzo_totem else "")}
        monitor_cmd = f"{base} -Tipo monitor"
        if sede.indirizzo_totem:
            monitor_cmd += f" -Totem {sede.indirizzo_totem}"
            if impronta_totem:
                monitor_cmd += f" -ImprontaTotem {impronta_totem}"
        voce["comando_monitor"] = monitor_cmd
        risultato.append(voce)
    return {"server": server, "impronta_server": impronta, "sedi": risultato}
