"""I listini prezzi: righe da CSV (file, testo incollato, indirizzo pubblico o invio dal gestionale).

Il CSV ha una riga per prodotto: prodotto; prezzo; unità; nota; evidenza. L'intestazione è
facoltativa; il separatore può essere punto e virgola, virgola o tabulazione; il prezzo può
avere la virgola («12,90») e il simbolo dell'euro.
"""

import csv
import io
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from layout import fonti

MASSIMO_RIGHE = 500
COLONNE = ["prodotto", "prezzo", "unita", "nota", "evidenza"]
_SINONIMI = {
    "prodotto": "prodotto", "articolo": "prodotto", "descrizione": "prodotto", "nome": "prodotto",
    "prezzo": "prezzo", "euro": "prezzo", "importo": "prezzo",
    "unita": "unita", "unità": "unita", "um": "unita", "u.m.": "unita", "misura": "unita",
    "nota": "nota", "note": "nota", "offerta": "nota",
    "evidenza": "evidenza", "in evidenza": "evidenza",
}
_VERO = {"1", "si", "sì", "s", "x", "true", "vero", "yes"}


def prezzo_normalizzato(testo: str) -> str:
    """«€ 12,90» → «12.90»; vuoto se non è un numero (es. «a peso»: resta nella nota)."""
    pulito = re.sub(r"[€\s]", "", str(testo or ""))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", pulito):
        pulito = pulito.replace(".", "")
    pulito = pulito.replace(",", ".")
    try:
        valore = float(pulito)
    except ValueError:
        return ""
    if valore < 0 or valore > 1_000_000:
        return ""
    return f"{valore:.2f}"


def riga_pulita(dati: dict) -> dict:
    return {
        "prodotto": str(dati.get("prodotto") or "").strip()[:120],
        "prezzo": prezzo_normalizzato(dati.get("prezzo")),
        "unita": str(dati.get("unita") or "").strip()[:30],
        "nota": str(dati.get("nota") or "").strip()[:60],
        "evidenza": str(dati.get("evidenza")).strip().lower() in _VERO or dati.get("evidenza") is True,
        "visibile": dati.get("visibile", True) is not False,
    }


def leggi_csv(testo: str) -> tuple[list[dict], list[str]]:
    """Le righe del listino e gli avvisi (righe saltate)."""
    testo = testo.lstrip("﻿")
    if not testo.strip():
        return [], []
    campione = testo[:4096]
    separatore = max([";", ",", "\t"], key=campione.count)
    lettore = list(csv.reader(io.StringIO(testo), delimiter=separatore))
    lettore = [r for r in lettore if any(c.strip() for c in r)]
    colonne = COLONNE
    if lettore:
        prima = [c.strip().lower() for c in lettore[0]]
        if any(c in _SINONIMI for c in prima) and not prezzo_normalizzato(lettore[0][1] if len(lettore[0]) > 1 else ""):
            colonne = [_SINONIMI.get(c, f"_{i}") for i, c in enumerate(prima)]
            lettore = lettore[1:]
    righe, avvisi = [], []
    for numero, valori in enumerate(lettore, start=1):
        dati = {colonne[i]: v for i, v in enumerate(valori) if i < len(colonne)}
        riga = riga_pulita(dati)
        if not riga["prodotto"]:
            avvisi.append(f"Riga {numero}: manca il prodotto, saltata.")
            continue
        righe.append(riga)
        if len(righe) >= MASSIMO_RIGHE:
            avvisi.append(f"Tenute le prime {MASSIMO_RIGHE} righe.")
            break
    return righe, avvisi


def csv_del_listino(listino) -> str:
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    scrittore.writerow(COLONNE)
    for r in listino.righe:
        scrittore.writerow([r["prodotto"], r["prezzo"].replace(".", ","), r["unita"], r["nota"], "sì" if r["evidenza"] else ""])
    return "﻿" + uscita.getvalue()


def aggiorna_da_fonte(listino) -> bool:
    """Rilegge l'indirizzo del listino. Se non risponde restano le righe di prima."""
    try:
        grezzo = fonti.scarica(listino.fonte_url)
        righe, _ = leggi_csv(grezzo.decode("utf-8-sig", errors="replace"))
        if not righe:
            raise ValueError("nessuna riga")
    except Exception as errore:
        listino.errore_fonte = f"Indirizzo non leggibile ({errore.__class__.__name__}): restano i prezzi di prima."[:300]
        listino.aggiornato_il = timezone.now()  # si riprova al prossimo intervallo, non a ogni richiesta
        listino.save(update_fields=["errore_fonte", "aggiornato_il"])
        return False
    listino.righe = righe
    listino.errore_fonte = ""
    listino.aggiornato_il = timezone.now()
    listino.save(update_fields=["righe", "errore_fonte", "aggiornato_il", "modificato"])
    return True


def dati_listino(listino) -> dict:
    """Per il player: solo le righe visibili. Un listino con indirizzo si rilegge quando è vecchio."""
    if listino.fonte_url and (
        listino.aggiornato_il is None or timezone.now() - listino.aggiornato_il > timedelta(minutes=listino.aggiorna_minuti)
    ):
        with transaction.atomic():
            aggiorna_da_fonte(listino)
    return {
        "nome": listino.nome,
        "righe": [{k: r[k] for k in ("prodotto", "prezzo", "unita", "nota", "evidenza")} for r in listino.righe if r.get("visibile", True)],
        "aggiornato": (listino.aggiornato_il or listino.modificato).isoformat(),
    }
