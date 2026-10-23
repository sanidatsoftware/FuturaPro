"""Il «bollino» dei canali in diretta, dal database pubblico iptv-org (pubblico dominio).

iptv-org cataloga decine di migliaia di canali: per ognuno dice se è per adulti (``is_nsfw``,
categoria ``xxx``), se è chiuso, e tiene una lista nera (canali per adulti, diritti). Il server
ne scarica una copia compatta una volta al giorno (``aggiorna``) e la usa per dare a ogni canale
di una lista M3U un bollino:

- **vietato**: per adulti nel database, in lista nera, o con un nome/gruppo da adulti. Con il
  «Filtro contenuti» attivo per le dirette non si importa, mai.
- **riconosciuto**: il database lo conosce e non è per adulti (se è chiuso lo si segnala).
- **sconosciuto**: il database non lo conosce: si importa solo se chi gestisce l'azienda lo
  conferma.

Il canale si cerca per ``tvg-id``, poi per indirizzo del flusso, poi per nome nello stesso paese.
In ogni caso, una diretta in onda è sorvegliata dal filtro (``filtro.controlla_dirette``).
"""

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone as tz
from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

from django.conf import settings

FONTE = "https://iptv-org.github.io/api/"
AGGIORNA_ORE = 24
MASSIMO_FILE = 40 * 1024 * 1024
# Parole intere (nel nome o nel gruppo del canale) che bastano per vietarlo.
PAROLE_ADULTI = {
    "xxx", "adult", "adults", "adulti", "adulto", "porn", "porno", "sex", "sexy", "erotic", "erotica",
    "erotico", "erotik", "hustler", "playboy", "nsfw", "hentai", "brazzers", "vivid",
}
VIETATO, RICONOSCIUTO, SCONOSCIUTO = "vietato", "riconosciuto", "sconosciuto"


def percorso() -> Path:
    return Path(settings.MEDIA_ROOT) / "plugin" / "canali-iptv-org.json"


def norma(nome: str) -> str:
    """Il nome per il confronto: senza qualità («(1080p)», «HD»), simboli («Ⓖ») e spazi."""
    nome = re.sub(r"[Ⓐ-ⓩ①-⓿]", " ", nome)  # lettere e numeri cerchiati
    nome = unicodedata.normalize("NFKD", nome)
    nome = re.sub(r"\(.*?\)|\[.*?\]", " ", nome)
    nome = "".join(c for c in nome if c.isalnum() or c == " ").lower()
    nome = re.sub(r"\b(hd|sd|fhd|uhd|4k|tv)\b", " ", nome)
    return re.sub(r"\s+", "", nome)


def parole_adulti(*testi: str) -> str | None:
    for testo in testi:
        if re.search(r"(?<![\w+])18\s*\+", testo or ""):
            return "18+"
        for parola in re.findall(r"[a-z0-9]+", (testo or "").lower()):
            if parola in PAROLE_ADULTI:
                return parola
    return None


# --- Il database ----------------------------------------------------------------------------


def _scarica(url: str) -> bytes:
    # L'indirizzo è fisso (FONTE), non scritto da un utente: niente controllo sulla rete interna.
    richiesta = Request(url, headers={"User-Agent": "FuturaPro/1.0 (+digital signage)"})
    with urlopen(richiesta, timeout=60) as risposta:
        dati = risposta.read(MASSIMO_FILE + 1)
    if len(dati) > MASSIMO_FILE:
        raise ValueError(f"{url}: risposta troppo grande")
    return dati


def aggiorna(forza: bool = False) -> dict:
    """Scarica canali, lista nera, flussi e paesi da iptv-org e scrive l'indice compatto."""
    file = percorso()
    if not forza and file.exists():
        eta = datetime.now(tz.utc) - datetime.fromtimestamp(file.stat().st_mtime, tz.utc)
        if eta < timedelta(hours=AGGIORNA_ORE):
            return {"aggiornato": False}
    leggi = lambda nome: json.loads(_scarica(FONTE + nome))  # noqa: E731
    canali, nera, flussi, paesi = leggi("channels.json"), leggi("blocklist.json"), leggi("streams.json"), leggi("countries.json")
    indice = {
        "aggiornato": datetime.now(tz.utc).isoformat(timespec="seconds"),
        # id → [paese, per adulti, chiuso, nome]
        "canali": {
            c["id"]: [c.get("country") or "", int(bool(c.get("is_nsfw")) or "xxx" in (c.get("categories") or [])), int(bool(c.get("closed"))), c.get("name") or ""]
            for c in canali
        },
        "nera": {b["channel"]: b.get("reason", "") for b in nera if b.get("channel")},
        "url": {s["url"]: s["channel"] for s in flussi if s.get("channel") and s.get("url")},
        "paesi": {p["name"].lower(): p["code"] for p in paesi if p.get("name") and p.get("code")},
        "nomi": {},
    }
    for c in canali:
        for nome in [c.get("name") or "", *(c.get("alt_names") or [])]:
            chiave = f"{norma(nome)}|{c.get('country') or ''}"
            if norma(nome):
                indice["nomi"].setdefault(chiave, [])
                if c["id"] not in indice["nomi"][chiave]:
                    indice["nomi"][chiave].append(c["id"])
    file.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = file.with_suffix(".parziale")
    temporaneo.write_text(json.dumps(indice, separators=(",", ":")))
    temporaneo.replace(file)
    _indice_da.cache_clear()
    return {"aggiornato": True, "canali": len(indice["canali"])}


@lru_cache(maxsize=1)
def _indice_da(file: str, _modifica: float) -> dict:
    return json.loads(Path(file).read_text())


def _indice() -> dict | None:
    file = percorso()
    if not file.exists():
        return None
    return _indice_da(str(file), file.stat().st_mtime)



def indice(scarica_se_manca: bool = True) -> dict | None:
    """L'indice locale; se manca (primo uso) prova a scaricarlo subito."""
    trovato = _indice()
    if trovato is None and scarica_se_manca:
        try:
            aggiorna(forza=True)
        except (OSError, ValueError):
            return None
        trovato = _indice()
    return trovato


def stato() -> dict | None:
    trovato = _indice()
    return {"aggiornato": trovato["aggiornato"], "canali": len(trovato["canali"])} if trovato else None


# --- Il bollino ---------------------------------------------------------------------------------


def valuta(canale: dict, dati: dict | None) -> dict:
    """Il bollino di un canale (nome, gruppo, tvg_id, url) con il motivo e il canale riconosciuto."""
    parola = parole_adulti(canale.get("nome", ""), canale.get("gruppo", ""))
    if parola:
        return {"bollino": VIETATO, "motivo": f"nome o gruppo da adulti («{parola}»)", "canale": None}
    if dati is None:
        return {"bollino": SCONOSCIUTO, "motivo": "database dei canali non disponibile", "canale": None}
    identificativo = (canale.get("tvg_id") or "").split("@")[0].strip()
    if identificativo not in dati["canali"] and identificativo not in dati["nera"]:
        identificativo = dati["url"].get(canale.get("url", ""), "")
    if not identificativo:
        paese = ""
        if canale.get("tvg_id") and "." in canale["tvg_id"]:
            paese = canale["tvg_id"].split("@")[0].rsplit(".", 1)[-1].upper()
        paese = paese or dati["paesi"].get((canale.get("gruppo") or "").strip().lower(), "")
        trovati = dati["nomi"].get(f"{norma(canale.get('nome', ''))}|{paese}", []) if paese else []
        if len(trovati) > 1:
            # Più canali con quel nome nello stesso paese: va bene solo se nessuno è a rischio.
            rischio = [t for t in trovati if dati["canali"].get(t, [0, 1])[1] or dati["nera"].get(t) == "nsfw"]
            trovati = trovati[:1] if not rischio else []
        if len(trovati) == 1:
            identificativo = trovati[0]
    if not identificativo:
        return {"bollino": SCONOSCIUTO, "motivo": "non presente nel database dei canali", "canale": None}
    motivo_nera = dati["nera"].get(identificativo)
    if motivo_nera == "nsfw":
        return {"bollino": VIETATO, "motivo": "in lista nera: canale per adulti", "canale": identificativo}
    paese, adulti, chiuso, nome = dati["canali"].get(identificativo, ["", 0, 0, ""])
    if adulti:
        return {"bollino": VIETATO, "motivo": "classificato per adulti", "canale": identificativo}
    if motivo_nera:
        return {"bollino": SCONOSCIUTO, "motivo": f"in lista nera ({motivo_nera})", "canale": identificativo}
    motivo = f"{nome} ({paese})" if nome else "nel database dei canali"
    # Un canale chiuso non è un rischio per adulti: si segnala soltanto (il flusso può non funzionare).
    return {"bollino": RICONOSCIUTO, "motivo": motivo + (", segnato come chiuso" if chiuso else ""), "canale": identificativo}
