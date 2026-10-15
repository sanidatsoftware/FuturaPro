"""La versione del player web: si calcola da sola dal contenuto dei suoi file.

Così non c'è un numero da ricordarsi di cambiare: ogni modifica a pagina, motore, stili o service
worker dà una versione nuova. Il server la manda a ogni segnale periodico e il player che ne ha
una diversa si ricarica da solo (vedi avvio.js); nel pannello si vede quale gira davvero su ogni
schermo. BASE è la parte leggibile, da cambiare quando si vuole segnare un passo importante.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from futurapro.versione import RELEASE

BASE = RELEASE
CARTELLA = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def versione() -> str:
    impronta = hashlib.sha256()
    file = sorted((CARTELLA / "static" / "player").rglob("*")) + sorted((CARTELLA / "templates" / "player").glob("*"))
    for percorso in file:
        if percorso.is_file():
            impronta.update(percorso.relative_to(CARTELLA).as_posix().encode())
            impronta.update(percorso.read_bytes())
    return f"web-{BASE}-{impronta.hexdigest()[:7]}"
