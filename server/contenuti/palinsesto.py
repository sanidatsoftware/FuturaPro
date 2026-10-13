"""Le regole del palinsesto: cosa va in onda su un monitor in un certo istante.

Il player applicherà le stesse regole sul manifest che riceve (vedi
docs/SPECIFICA.md, «Palinsesto»): se cambiano qui, cambiano anche lì.

1. Una pubblicazione vale se è attiva, se la data è fra ``data_inizio`` e
   ``data_fine`` (comprese), se il giorno della settimana è in ``giorni`` (o
   ``giorni`` è vuoto) e se l'ora è in [``ora_inizio``, ``ora_fine``). Una
   fascia con fine prima dell'inizio scavalca la mezzanotte.
2. Fra quelle valide vince la priorità più alta.
3. A pari priorità le playlist si accodano, in ordine di creazione: pubblicare
   altro sugli stessi monitor lo aggiunge alla rotazione.
"""

from datetime import date, datetime, time
from hashlib import sha256
import json

from django.conf import settings
from django.db.models import Q
from django.urls import reverse

from .models import DURATA_IMMAGINE, ElementoPlaylist, Pubblicazione, Tipo


def _nell_orario(ora: time, inizio: time | None, fine: time | None) -> bool:
    if inizio is None and fine is None:
        return True
    inizio = inizio or time.min
    if fine is None:
        return ora >= inizio
    if inizio <= fine:
        return inizio <= ora < fine
    return ora >= inizio or ora < fine


def _data_valida(giorno: date, inizio: date | None, fine: date | None) -> bool:
    return (inizio is None or giorno >= inizio) and (fine is None or giorno <= fine)


def valida(pubblicazione, istante: datetime) -> bool:
    return (
        pubblicazione.attiva
        and _data_valida(istante.date(), pubblicazione.data_inizio, pubblicazione.data_fine)
        and (not pubblicazione.giorni or istante.weekday() in pubblicazione.giorni)
        and _nell_orario(istante.time(), pubblicazione.ora_inizio, pubblicazione.ora_fine)
    )


def pubblicazioni_del_monitor(monitor):
    return (
        Pubblicazione.objects.filter(Q(monitor=monitor) | Q(gruppi__monitor=monitor))
        .distinct()
        .order_by("-priorita", "creata")
    )


def in_onda(pubblicazioni, istante: datetime) -> list:
    """Le pubblicazioni che vanno in onda in quell'istante, già in ordine di riproduzione."""
    valide = [p for p in pubblicazioni if valida(p, istante)]
    if not valide:
        return []
    massima = max(p.priorita for p in valide)
    return sorted((p for p in valide if p.priorita == massima), key=lambda p: p.creata)


def durata_effettiva(elemento) -> int | None:
    """Secondi di visualizzazione; None per un video senza durata (va fino alla fine)."""
    if elemento.durata:
        return elemento.durata
    if elemento.contenuto.durata:
        return elemento.contenuto.durata
    return None if elemento.contenuto.tipo == Tipo.VIDEO else DURATA_IMMAGINE


def manifest(monitor) -> dict:
    """Tutto ciò che serve al player per andare avanti da solo: file, playlist e regole."""
    pubblicazioni = list(pubblicazioni_del_monitor(monitor))
    playlist_ids = {p.playlist_id for p in pubblicazioni}
    elementi = (
        ElementoPlaylist.objects.filter(playlist_id__in=playlist_ids)
        .select_related("contenuto")
        .order_by("playlist_id", "ordine")
    )

    playlist, file = {}, {}
    for elemento in elementi:
        contenuto = elemento.contenuto
        playlist.setdefault(str(elemento.playlist_id), []).append(
            {"contenuto": str(contenuto.id), "durata": durata_effettiva(elemento)}
        )
        voce = {"tipo": contenuto.tipo, "nome": contenuto.nome}
        if contenuto.tipo == Tipo.WEB:
            voce["url"] = contenuto.url
        else:
            voce.update(
                url=reverse("player-file", args=[contenuto.id]),
                sha256=contenuto.sha256,
                dimensione=contenuto.dimensione,
                mime=contenuto.mime,
            )
        file[str(contenuto.id)] = voce

    corpo = {
        "monitor": str(monitor.id),
        # Date e orari delle regole sono in questo fuso, non in quello del dispositivo.
        "fuso_orario": settings.TIME_ZONE,
        "pubblicazioni": [
            {
                "id": str(p.id),
                "playlist": str(p.playlist_id),
                "priorita": p.priorita,
                "data_inizio": p.data_inizio and p.data_inizio.isoformat(),
                "data_fine": p.data_fine and p.data_fine.isoformat(),
                "ora_inizio": p.ora_inizio and p.ora_inizio.isoformat(),
                "ora_fine": p.ora_fine and p.ora_fine.isoformat(),
                "giorni": p.giorni,
                "attiva": p.attiva,
            }
            for p in pubblicazioni
        ],
        "playlist": playlist,
        "contenuti": file,
    }
    # La versione dipende solo dal contenuto: se nulla cambia, il player non riscarica.
    corpo["versione"] = sha256(json.dumps(corpo, sort_keys=True).encode()).hexdigest()
    return corpo
