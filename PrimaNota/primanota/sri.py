"""
Lettura dei file degli scontrini sospesi delle casse (es. CP261016.SRI.Cassa3).

Ogni riga è un evento dello stesso scontrino, riconosciuto dall'identificativo:
    SOSP.SCONTRINO  : SR030159225.289 Ora: 183847 Cassa: 3 Sct: 0159 Eur.: 14,68    sospeso
    RICH.SOSPENSIONE: SR030159225.289 Ora: 184731 Cassa: 3                           richiamato
    FINE RISTAMPA   : SR030159225.289 Ora: 184736 Cassa: 3 Sct: 169 Eur.: 14,68      emesso (nuovo numero)
Il numero dopo il punto dell'identificativo è il giorno dell'anno della sospensione (289 = 16 ottobre).
"""

import re
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

NOME_RE = re.compile(r"^CP(\d{2})(\d{2})(\d{2})\.SRI\.Cassa(\d+)$", re.IGNORECASE)
RIGA_RE = re.compile(
    r"^(?P<evento>SOSP\.SCONTRINO|RICH\.SOSPENSIONE|FINE RISTAMPA)\s*:\s*(?P<id>\S+)\s+Ora:\s*(?P<ora>\d{6})"
    r"\s+Cassa:\s*(?P<cassa>\d+)(?:\s+Sct:\s*(?P<sct>\d+))?(?:\s+Eur\.:\s*(?P<eur>[\d.,]+))?",
    re.IGNORECASE)
EVENTI = {"SOSP.SCONTRINO": "sospeso", "RICH.SOSPENSIONE": "richiamato", "FINE RISTAMPA": "emesso"}


def data_dal_nome(nome):
    """(data, cassa) dal nome del file; (None, None) se non è un file di sospesi."""
    m = NOME_RE.match(nome)
    if not m:
        return None, None
    aa, mm, gg, cassa = m.groups()
    try:
        return date(2000 + int(aa), int(mm), int(gg)), int(cassa)
    except ValueError:
        return None, int(cassa)


def data_sospensione(identificativo, riferimento):
    """Giorno della sospensione dal suffisso dell'identificativo (giorno dell'anno), vicino alla data del file."""
    try:
        giorno_anno = int(identificativo.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return riferimento
    if not riferimento or not 1 <= giorno_anno <= 366:
        return riferimento
    for anno in (riferimento.year, riferimento.year - 1):   # sospeso a fine dicembre, richiamato a gennaio
        d = date(anno, 1, 1) + timedelta(days=giorno_anno - 1)
        if d <= riferimento and d.year == anno:
            return d
    return riferimento


def _ora(t):
    return time(int(t[:2]) % 24, int(t[2:4]) % 60, int(t[4:6]) % 60)


def _importo(t):
    if not t:
        return None
    try:
        return Decimal(t.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def analizza(nome, dati):
    """{"data_file", "cassa", "eventi": [{tipo, id, data, ora, cassa, numero, importo}], "non_lette"}."""
    data_file, cassa_file = data_dal_nome(nome)
    testo = dati.decode("latin-1") if isinstance(dati, bytes) else dati
    eventi, non_lette = [], 0
    for riga in testo.splitlines():
        if not riga.strip():
            continue
        m = RIGA_RE.match(riga.strip())
        if not m:
            non_lette += 1
            continue
        identificativo = m["id"].strip()
        eventi.append({
            "tipo": EVENTI[m["evento"].upper()], "id": identificativo,
            # L'evento avviene nel giorno del file; la sospensione si data dall'identificativo.
            "data": data_sospensione(identificativo, data_file) if m["evento"].upper().startswith("SOSP") else data_file,
            "ora": _ora(m["ora"]), "cassa": int(m["cassa"]),
            "numero": int(m["sct"]) if m["sct"] else None, "importo": _importo(m["eur"]),
        })
    return {"data_file": data_file, "cassa": cassa_file, "eventi": eventi, "non_lette": non_lette, "testo": testo}
