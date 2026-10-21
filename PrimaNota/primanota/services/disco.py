"""
Spazio su disco del server, per l'indicatore in Impostazioni: dischi dove stanno il portale, il database e
l'archivio dei SysSpy, e quanto occupano archivio e database. Lo spazio dei dischi si legge subito; la
dimensione dell'archivio va calcolata scorrendo migliaia di file, quindi si calcola in background e si
tiene in memoria per 6 ore, senza far aspettare la pagina.
"""

import os
import shutil
import threading
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

ATTENZIONE = 80   # % di disco occupato
CRITICO = 90
CHIAVE_ARCHIVIO = "primanota:disco:archivio"
_calcolo_in_corso = threading.Lock()


def _dimensione_cartella(percorso):
    totale = 0
    for radice, _, file in os.walk(percorso):
        for nome in file:
            try:
                totale += os.lstat(os.path.join(radice, nome)).st_size
            except OSError:
                pass
    return totale


def _livello(percentuale):
    if percentuale >= CRITICO:
        return "critico"
    return "attenzione" if percentuale >= ATTENZIONE else "ok"


def _calcola_archivio(cartella):
    try:
        cache.set(CHIAVE_ARCHIVIO, _dimensione_cartella(cartella) if cartella.is_dir() else 0, 6 * 3600)
    finally:
        _calcolo_in_corso.release()


def dimensione_archivio(ricalcola=False):
    """Byte occupati dall'archivio, o None se il calcolo è appena partito in background."""
    from .importazione import archivio_dir

    valore = None if ricalcola else cache.get(CHIAVE_ARCHIVIO)
    if valore is None and _calcolo_in_corso.acquire(blocking=False):
        threading.Thread(target=_calcola_archivio, args=(archivio_dir(),), daemon=True).start()
    return valore


def stato(ricalcola=False):
    """{"dischi": [{nomi, percorso, totale, usato, libero, percentuale, livello}], "archivio": byte o None, "database": byte}."""
    from .importazione import archivio_dir

    database = Path(str(settings.DATABASES["default"].get("NAME") or ""))
    luoghi = [("Portale", Path(settings.BASE_DIR)), ("Archivio SysSpy e allegati", archivio_dir())]
    if database.is_file():
        luoghi.append(("Database", database.parent))
    dischi = {}
    for nome, percorso in luoghi:
        try:
            dispositivo = os.stat(percorso).st_dev
            uso = shutil.disk_usage(percorso)
        except OSError:
            continue
        d = dischi.setdefault(dispositivo, {"nomi": [], "percorso": str(percorso), "totale": uso.total,
                                            "usato": uso.total - uso.free, "libero": uso.free})
        d["nomi"].append(nome)
    for d in dischi.values():
        d["percentuale"] = round(d["usato"] * 100 / d["totale"], 1) if d["totale"] else 0
        d["livello"] = _livello(d["percentuale"])
    return {
        "dischi": list(dischi.values()),
        "archivio": dimensione_archivio(ricalcola),
        "database": database.stat().st_size if database.is_file() else None,
    }
