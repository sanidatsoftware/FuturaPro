"""Dati esterni per le zone: meteo (Open-Meteo, senza chiave) e notizie (feed RSS/Atom).

Li scarica il server, non i player: una richiesta sola per tutti i monitor che
mostrano la stessa località o lo stesso feed, e i player non devono poter
raggiungere internet. Se la fonte non risponde si continua a mostrare l'ultimo
dato buono.

Gli indirizzi dei feed li scrive l'Administrator: prima di collegarsi si
controlla che non puntino alla rete interna del server (anche dopo i
redirect), altrimenti un feed potrebbe servire a sondarla.
"""

import ipaddress
import json
import socket
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from defusedxml import ElementTree
from django.core.cache import cache

TIMEOUT = 8
MASSIMO_BYTE = 2 * 1024 * 1024
AGENTE = "FuturaPro/1.0 (+digital signage)"
METEO_MINUTI = 15
# Quanto a lungo un dato vecchio fa da riserva se la fonte non risponde.
RISERVA_ORE = 48


class IndirizzoNonAmmesso(ValueError):
    pass


def verifica_indirizzo(url: str) -> None:
    parti = urlsplit(url)
    if parti.scheme not in ("http", "https") or not parti.hostname:
        raise IndirizzoNonAmmesso(url)
    try:
        risolti = socket.getaddrinfo(parti.hostname, parti.port or (443 if parti.scheme == "https" else 80))
    except socket.gaierror as errore:
        raise IndirizzoNonAmmesso(url) from errore
    for *_, indirizzo in risolti:
        ip = ipaddress.ip_address(indirizzo[0])
        if not ip.is_global:
            raise IndirizzoNonAmmesso(f"{url} punta a una rete non pubblica")


class _RedirectControllati(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, nuovo_url):
        verifica_indirizzo(nuovo_url)
        return super().redirect_request(req, fp, code, msg, headers, nuovo_url)


_apri = build_opener(_RedirectControllati).open


def scarica(url: str, massimo: int = MASSIMO_BYTE) -> bytes:
    verifica_indirizzo(url)
    with _apri(Request(url, headers={"User-Agent": AGENTE}), timeout=TIMEOUT) as risposta:
        dati = risposta.read(massimo + 1)
    if len(dati) > massimo:
        raise ValueError(f"{url}: risposta troppo grande")
    return dati


def _con_riserva(chiave: str, minuti: int, produci):
    """Il dato fresco se c'è, altrimenti lo produce; se fallisce, l'ultimo dato buono."""
    fresco = cache.get(f"{chiave}:fresco")
    if fresco is not None:
        return fresco
    try:
        valore = produci()
    except (URLError, OSError, ValueError, ElementTree.ParseError, KeyError, TypeError):
        return cache.get(f"{chiave}:riserva")
    cache.set(f"{chiave}:fresco", valore, minuti * 60)
    cache.set(f"{chiave}:riserva", valore, RISERVA_ORE * 3600)
    return valore


# --- Meteo -------------------------------------------------------------------

# Codici WMO usati da Open-Meteo → descrizione e icona (le icone sono nel motore).
CONDIZIONI = {
    0: ("Sereno", "sole"),
    1: ("Poco nuvoloso", "sole_nuvole"),
    2: ("Parzialmente nuvoloso", "sole_nuvole"),
    3: ("Coperto", "nuvole"),
    45: ("Nebbia", "nebbia"),
    48: ("Nebbia", "nebbia"),
    51: ("Pioviggine", "pioggia"),
    53: ("Pioviggine", "pioggia"),
    55: ("Pioviggine", "pioggia"),
    61: ("Pioggia debole", "pioggia"),
    63: ("Pioggia", "pioggia"),
    65: ("Pioggia forte", "pioggia"),
    66: ("Pioggia gelata", "pioggia"),
    67: ("Pioggia gelata", "pioggia"),
    71: ("Neve debole", "neve"),
    73: ("Neve", "neve"),
    75: ("Neve forte", "neve"),
    77: ("Neve", "neve"),
    80: ("Rovesci", "pioggia"),
    81: ("Rovesci", "pioggia"),
    82: ("Rovesci forti", "pioggia"),
    85: ("Rovesci di neve", "neve"),
    86: ("Rovesci di neve", "neve"),
    95: ("Temporale", "temporale"),
    96: ("Temporale con grandine", "temporale"),
    99: ("Temporale con grandine", "temporale"),
}


def _condizione(codice):
    descrizione, icona = CONDIZIONI.get(int(codice), ("", "nuvole"))
    return {"descrizione": descrizione, "icona": icona}


def meteo(latitudine: float, longitudine: float, fuso: str = "Europe/Rome") -> dict | None:
    lat, lon = round(latitudine, 2), round(longitudine, 2)

    def produci():
        parametri = urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,is_day",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "forecast_days": 1,
                "timezone": fuso,
            }
        )
        dati = json.loads(scarica(f"https://api.open-meteo.com/v1/forecast?{parametri}"))
        attuale, giorno = dati["current"], dati["daily"]
        return {
            "temperatura": round(attuale["temperature_2m"]),
            "giorno": bool(attuale.get("is_day", 1)),
            **_condizione(attuale["weather_code"]),
            "massima": round(giorno["temperature_2m_max"][0]),
            "minima": round(giorno["temperature_2m_min"][0]),
        }

    return _con_riserva(f"meteo:{lat}:{lon}", METEO_MINUTI, produci)


def cerca_localita(nome: str) -> list[dict]:
    parametri = urlencode({"name": nome, "count": 8, "language": "it", "format": "json"})
    dati = json.loads(scarica(f"https://geocoding-api.open-meteo.com/v1/search?{parametri}"))
    return [
        {
            "nome": r["name"],
            "zona": ", ".join(x for x in (r.get("admin2") or r.get("admin1"), r.get("country")) if x),
            "latitudine": r["latitude"],
            "longitudine": r["longitude"],
        }
        for r in dati.get("results", [])
    ]


# --- Notizie -----------------------------------------------------------------

MASSIMO_TITOLI = 30
ATOM = "{http://www.w3.org/2005/Atom}"


def titoli_dal_feed(xml: bytes) -> list[str]:
    radice = ElementTree.fromstring(xml)
    titoli = [e.findtext("title") for e in radice.iter("item")]  # RSS
    titoli += [e.findtext(f"{ATOM}title") for e in radice.iter(f"{ATOM}entry")]  # Atom
    puliti = [" ".join(t.split()) for t in titoli if t and t.strip()]
    return puliti[:MASSIMO_TITOLI]


def notizie(feed: list[str], minuti: int) -> list[str]:
    titoli = []
    for url in feed:
        titoli += _con_riserva(f"feed:{url}", minuti, lambda url=url: titoli_dal_feed(scarica(url))) or []
    return titoli
