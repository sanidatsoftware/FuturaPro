"""La versione di FuturaPro: «RELEASE.build · mese/anno», es. 1.6.071 · 10/2026.

RELEASE si cambia a mano quando si battezza una release (vedi docs/VERSIONI.md); il numero di
build cresce da solo: è il numero di modifiche del codice (commit); mese e anno sono quelli
dell'ultima modifica. Sul server li scrive deploy/aggiorna.sh (e installa.sh) in .env come
FP_BUILD e FP_BUILD_DATA, perché nel container il repository git non c'è; in sviluppo li si
chiede direttamente a git.
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
def build() -> str:
    numero = os.environ.get("FUTURAPRO_BUILD", "").strip() or _git("rev-list", "--count", "HEAD")
    return f"{int(numero):03d}" if numero.isdigit() else "dev"


@lru_cache(maxsize=1)
def mese_anno() -> str:
    """«10/2026»: il mese dell'ultima modifica del codice; "" se non si sa."""
    data = os.environ.get("FUTURAPRO_BUILD_DATA", "").strip() or _git("log", "-1", "--format=%cd", "--date=format:%Y-%m")
    if len(data) == 7 and data[4] == "-" and data.replace("-", "").isdigit():
        return f"{data[5:]}/{data[:4]}"
    return ""


def versione() -> str:
    """«1.6.071 · 10/2026»."""
    return f"{RELEASE}.{build()}" + (f" · {mese_anno()}" if mese_anno() else "")
