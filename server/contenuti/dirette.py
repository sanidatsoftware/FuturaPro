"""Dirette in streaming: lettura delle liste M3U e creazione dei canali nella libreria.

Il server legge solo la lista (un testo); il flusso video lo scarica ogni player con
la sua connessione a internet, non passa mai dal server né dalla sua sede.
"""

import re

from django.utils import timezone

from layout.fonti import scarica

from plugin import filtro

from .models import Contenuto, Controllo, Tipo

MASSIMO_LISTA = 8 * 1024 * 1024
MASSIMO_CANALI = 5000
# Un intermezzo di diretta dura 5 minuti, se non si sceglie altro.
DURATA_DIRETTA = 300
ATTRIBUTO = re.compile(r'([\w-]+)="([^"]*)"')


def e_flusso_hls(testo: str) -> bool:
    """Un .m3u8 di un singolo canale (HLS) e non un elenco di canali: ha i tag #EXT-X-."""
    return "#EXT-X-" in testo[:20000]


def leggi_m3u(testo: str) -> list[dict]:
    """I canali di una lista M3U/M3U8 estesa: nome, indirizzo, logo e gruppo."""
    canali, visti, informazioni = [], set(), None
    for riga in testo.splitlines():
        riga = riga.strip()
        if not riga:
            continue
        if riga.upper().startswith("#EXTINF"):
            intestazione, _, nome = riga.partition(",")
            attributi = dict(ATTRIBUTO.findall(intestazione))
            informazioni = {
                "nome": (nome.strip() or attributi.get("tvg-name", "")).strip()[:200],
                "logo": attributi.get("tvg-logo", "")[:500],
                "gruppo": attributi.get("group-title", "")[:100],
            }
            continue
        if riga.startswith("#"):
            continue
        if not re.match(r"^https?://", riga, re.IGNORECASE) or riga in visti or len(riga) > 1000:
            informazioni = None
            continue
        visti.add(riga)
        voce = informazioni or {"nome": "", "logo": "", "gruppo": ""}
        voce["url"] = riga
        voce["nome"] = voce["nome"] or riga.rsplit("/", 1)[-1][:200]
        if not re.match(r"^https?://", voce["logo"], re.IGNORECASE):
            voce["logo"] = ""
        canali.append(voce)
        informazioni = None
        if len(canali) >= MASSIMO_CANALI:
            break
    return canali


def scarica_lista(url: str) -> str:
    dati = scarica(url, massimo=MASSIMO_LISTA)
    for codifica in ("utf-8-sig", "latin-1"):
        try:
            return dati.decode(codifica)
        except UnicodeDecodeError:
            continue
    return dati.decode("utf-8", errors="replace")


def crea_dirette(canali: list[dict], utente) -> list[Contenuto]:
    """Aggiunge i canali alla libreria; quelli con lo stesso indirizzo esistono già e si riusano."""
    esistenti = {c.url: c for c in Contenuto.objects.filter(tipo=Tipo.DIRETTA)}
    adesso = timezone.now()
    # Con il «Filtro contenuti» attivo per le dirette, quelle nuove vanno in onda solo dopo il controllo.
    da_controllare = filtro.severita_per("diretta") is not None
    risultato = []
    for canale in canali:
        contenuto = esistenti.get(canale["url"])
        if contenuto is None:
            contenuto = Contenuto.objects.create(
                nome=canale["nome"][:200] or canale["url"][:200], tipo=Tipo.DIRETTA, url=canale["url"],
                logo_url=canale.get("logo", "")[:500], durata=DURATA_DIRETTA,
                # Le dirette sono quasi sempre 16:9: vanno ai monitor orizzontali.
                larghezza=1920, altezza=1080, caricato_da=utente.username,
                controllo=Controllo.ATTESA if da_controllare else "",
            )
        contenuto.autorizzata_da, contenuto.autorizzata_il = utente.username, adesso
        contenuto.save(update_fields=["autorizzata_da", "autorizzata_il"])
        esistenti[contenuto.url] = contenuto
        risultato.append(contenuto)
    return risultato
