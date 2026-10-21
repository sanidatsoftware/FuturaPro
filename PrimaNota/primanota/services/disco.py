"""
Spazio su disco del server, per l'indicatore in Impostazioni: dischi dove stanno il portale, il database e
l'archivio dei SysSpy, e quanto occupano archivio e database. La dimensione dell'archivio si calcola
scorrendo le cartelle, quindi si tiene in memoria per 15 minuti.
"""

import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

ATTENZIONE = 80   # % di disco occupato
CRITICO = 90


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


def stato(ricalcola=False):
    """{"dischi": [{nomi, totale, usato, libero, percentuale, livello}], "archivio": byte, "database": byte}."""
    from .importazione import archivio_dir

    chiave = "primanota:disco"
    if not ricalcola and (trovato := cache.get(chiave)) is not None:
        return trovato
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
    risultato = {
        "dischi": list(dischi.values()),
        "archivio": _dimensione_cartella(archivio_dir()) if archivio_dir().is_dir() else 0,
        "database": database.stat().st_size if database.is_file() else None,
    }
    cache.set(chiave, risultato, 15 * 60)
    return risultato
