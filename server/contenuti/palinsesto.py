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

from layout.manifest import descrivi, layout_del_monitor, riferimenti

from .models import DURATA_IMMAGINE, Contenuto, ElementoPlaylist, Pubblicazione, Tipo


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
    destinatari = Q(monitor=monitor) | Q(gruppi__monitor=monitor)
    if monitor.sede.insegna_id:
        destinatari |= Q(insegne=monitor.sede.insegna_id)
    return (
        Pubblicazione.objects.filter(destinatari)
        .filter(Q(orientamento="") | Q(orientamento=monitor.orientamento))
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


def _voce(contenuto) -> dict:
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
    return voce


# Il servizio code del totem: HTTPS per monitor e totem, HTTP per le bilance.
PORTA_CODE_HTTPS = 8443
PORTA_CODE_HTTP = 8090


def code_del_monitor(monitor, layout: dict) -> dict:
    """Dove sono le code del negozio. Con un totem, il monitor le legge da lì e il
    totem riceve anche la configurazione dei reparti (con le impronte delle chiavi
    delle bilance) da passare al suo servizio code."""
    from eliminacode.models import CredenzialePulsante, Reparto

    totem = monitor.sede.indirizzo_totem
    if not totem:
        return {"modo": "server"}
    code = {"modo": "totem", "indirizzo": f"https://{totem}:{PORTA_CODE_HTTPS}"}
    if any(z["tipo"] == "prendi_numero" for z in layout["zone"]):
        chiavi = {}
        for c in CredenzialePulsante.objects.filter(reparto__sede_id=monitor.sede_id):
            chiavi.setdefault(str(c.reparto_id), []).append(c.impronta_chiave)
        code["reparti"] = [
            {
                "id": str(r.id), "nome": r.nome, "colore": r.colore, "colore_testo": r.colore_testo,
                "ordine": r.ordine, "massimo": r.massimo, "attivo": r.attivo,
                "chiavi": sorted(chiavi.get(str(r.id), [])),
            }
            for r in Reparto.objects.filter(sede_id=monitor.sede_id).order_by("ordine", "nome")
        ]
    return code


def manifest(monitor) -> dict:
    """Tutto ciò che serve al player per andare avanti da solo: layout, file, playlist e regole."""
    pubblicazioni = list(pubblicazioni_del_monitor(monitor))
    layout = descrivi(layout_del_monitor(monitor), monitor.orientamento)
    playlist_fisse, immagini_layout = riferimenti(layout)
    playlist_ids = {str(p.playlist_id) for p in pubblicazioni} | playlist_fisse
    elementi = (
        ElementoPlaylist.objects.filter(playlist_id__in=playlist_ids)
        .select_related("contenuto")
        .order_by("playlist_id", "ordine")
    )

    playlist = {}
    riserva = str(monitor.immagine_riserva_id) if monitor.immagine_riserva_id else None
    contenuti = {str(c.id): c for c in Contenuto.objects.filter(id__in=immagini_layout | ({riserva} if riserva else set()))}
    for elemento in elementi:
        playlist.setdefault(str(elemento.playlist_id), []).append(
            {"contenuto": str(elemento.contenuto_id), "durata": durata_effettiva(elemento)}
        )
        contenuti[str(elemento.contenuto_id)] = elemento.contenuto

    corpo = {
        "monitor": str(monitor.id),
        "schermo": {"orientamento": monitor.orientamento, "rotazione": monitor.rotazione},
        # Date e orari delle regole sono in questo fuso, non in quello del dispositivo.
        "fuso_orario": settings.TIME_ZONE,
        "layout": layout,
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
        # Quando non c'è nulla in onda le slide mostrano questa immagine, invece del nero.
        "riserva": riserva,
        "contenuti": {chiave: _voce(contenuto) for chiave, contenuto in contenuti.items()},
        "code": code_del_monitor(monitor, layout),
    }
    # La versione dipende solo dal contenuto: se nulla cambia, il player non riscarica.
    corpo["versione"] = sha256(json.dumps(corpo, sort_keys=True).encode()).hexdigest()
    return corpo
