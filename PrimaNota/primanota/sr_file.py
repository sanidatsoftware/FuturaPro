"""
Lettura dei file degli scontrini sospesi salvati dalla cassa (es. SR010051105.289, SR030159225.289.RICH).

Il nome è l'identificativo del file SRI (cassa, numero documento, giorno dell'anno); l'estensione .RICH
vuol dire che lo scontrino è stato richiamato, senza estensione è ancora in attesa. Il contenuto è
binario: un record di 460 byte per articolo, con
    +3   «V» e il codice (barcode o PLU)          +117 descrizione (20 caratteri)
    +21  importo (double)   +29 aliquota IVA       +233 reparto
    +37  prezzo unitario    +45 quantità           +259 «!codice!codice!tipo!barcode!qtà!PZ|KG!...!»
    +53  peso (per gli articoli a peso)
I prezzi sono quelli pieni: le promozioni la cassa le calcola sul totale e qui non ci sono, quindi
la somma degli articoli può superare l'importo del file SRI.
"""

import re
import struct
from decimal import Decimal

NOME_RE = re.compile(r"^(SR\d{6,}\.\d{1,3})(\.RICH)?$", re.IGNORECASE)
FIRMA_RE = re.compile(rb"!([^!\x00]*)!([^!\x00]*)!(\d+)!([^!\x00]*)!(\d+)!(KG|PZ|[A-Z]{0,3})!")
INIZIO_FIRMA = 259


def nome_valido(nome):
    return bool(NOME_RE.match(nome))


def identificativo(nome):
    """(identificativo, richiamato) dal nome del file."""
    m = NOME_RE.match(nome)
    return (m.group(1).upper(), bool(m.group(2))) if m else (None, False)


def _stringa(dati, inizio, lunghezza):
    return dati[inizio:inizio + lunghezza].split(b"\x00")[0].decode("latin-1").strip()


def analizza(nome, dati):
    """{"identificativo", "richiamato", "articoli": [{codice, descrizione, reparto, importo, iva, prezzo, quantita, peso, unita}], "totale_lordo"}."""
    ident, richiamato = identificativo(nome)
    articoli = []
    for m in FIRMA_RE.finditer(dati):
        inizio = m.start() - INIZIO_FIRMA
        if inizio < 0 or dati[inizio + 3:inizio + 4] != b"V":
            continue
        codice = _stringa(dati, inizio + 4, 20)
        if "VIRTUALE" in codice.upper():   # riga tecnica della cassa, non un articolo
            continue
        importo, iva, prezzo, quantita, peso = struct.unpack_from("<ddddd", dati, inizio + 21)
        unita = m.group(6).decode("latin-1")
        articoli.append({
            "codice": codice, "descrizione": _stringa(dati, inizio + 117, 21), "reparto": _stringa(dati, inizio + 233, 20),
            "importo": str(round(Decimal(str(importo)), 2)), "iva": round(iva, 2), "prezzo": str(round(Decimal(str(prezzo)), 3)),
            "quantita": round(quantita, 3), "peso": round(peso, 3) if unita == "KG" else None, "unita": unita,
        })
    totale = sum((Decimal(a["importo"]) for a in articoli), Decimal("0"))
    return {"identificativo": ident, "richiamato": richiamato, "articoli": articoli, "totale_lordo": totale}


def testo(articoli, titolo=""):
    """Lo scontrino sospeso ricostruito dagli articoli, in colonne come quelli dei SysSpy."""
    righe = [titolo, ""] if titolo else []
    for a in articoli:
        righe.append(f"{a['descrizione'][:28]:<28}{a['importo'].replace('.', ','):>10}")
        if a["unita"] == "KG" and a.get("peso"):
            righe.append(f"   {str(a['peso']).replace('.', ',')} kg x {a['prezzo'].replace('.', ',')} EUR/kg")
        elif a.get("quantita") and a["quantita"] != 1:
            righe.append(f"   {a['quantita']:g} x {a['prezzo'].replace('.', ',')}")
    totale = sum((Decimal(a["importo"]) for a in articoli), Decimal("0"))
    righe += ["-" * 38, f"{'TOTALE A PREZZO PIENO':<28}{str(totale).replace('.', ','):>10}",
              "(senza le promozioni, che la cassa", " calcola al totale)"]
    return "\n".join(righe)
