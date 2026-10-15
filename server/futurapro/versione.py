"""La versione di FuturaPro: «RELEASE.build · AAAAMMGG», es. 1.6.072 · 20261015.

RELEASE si cambia a mano quando si battezza una release (vedi docs/VERSIONI.md); il numero di
build cresce da solo: è il numero di modifiche del codice (commit); la data (anno, mese, giorno)
è quella dell'ultima modifica. Nel container il repository git non c'è: deploy/aggiorna.sh (e installa.sh)
li scrivono prima di costruire l'immagine in server/futurapro/build.txt (fuori da git), che finisce
nell'immagine; in sviluppo li si chiede direttamente a git. Valgono anche le variabili
FUTURAPRO_BUILD e FUTURAPRO_BUILD_DATA, se impostate.
"""

import os
import subprocess
from functools import lru_cache
from pathlib import Path

RELEASE = "1.6"


def _git(*argomenti) -> str:
    try:
        return subprocess.run(
            ["git", *argomenti], cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


@lru_cache(maxsize=1)
def _da_file() -> dict:
    """build.txt: righe «FP_BUILD=74» e «FP_BUILD_DATA=20261015»."""
    valori = {}
    try:
        for riga in (Path(__file__).resolve().parent / "build.txt").read_text().splitlines():
            chiave, _, valore = riga.partition("=")
            valori[chiave.strip()] = valore.strip()
    except OSError:
        pass
    return valori


@lru_cache(maxsize=1)
def build() -> str:
    numero = (os.environ.get("FUTURAPRO_BUILD", "").strip() or _da_file().get("FP_BUILD", "")
              or _git("rev-list", "--count", "HEAD"))
    return f"{int(numero):03d}" if numero.isdigit() else "dev"


@lru_cache(maxsize=1)
def data_build() -> str:
    """«20261015» (AAAAMMGG): il giorno dell'ultima modifica del codice; "" se non si sa."""
    data = (os.environ.get("FUTURAPRO_BUILD_DATA", "").strip() or _da_file().get("FP_BUILD_DATA", "")
            or _git("log", "-1", "--format=%cd", "--date=format:%Y%m%d"))
    return data if len(data) == 8 and data.isdigit() else ""


def versione() -> str:
    """«1.6.072 · 20261015»."""
    return f"{RELEASE}.{build()}" + (f" · {data_build()}" if data_build() else "")
