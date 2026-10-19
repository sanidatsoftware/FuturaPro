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

from datetime import date, datetime, time, timedelta
from hashlib import sha256
import hmac
import json

from django.conf import settings
from django.db.models import Q
from django.urls import reverse

from dispositivi.stampanti import applica as applica_stampante
from dispositivi.stampanti import per_il_player as per_il_player_stampante
from plugin.manifest import per_il_monitor as plugin_del_monitor
from layout.manifest import descrivi, layout_del_monitor, riferimenti

from .models import DURATA_IMMAGINE, Contenuto, ElementoPlaylist, EventoStraordinario, Pubblicazione, Tipo


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


def telefono_per_manifest():
    from eliminacode.registro import telefono_per_manifest as calcola

    return calcola()


def download_del_monitor(monitor):
    from dispositivi.api import download_del_monitor as calcola

    return calcola(monitor)


def accensione_del_monitor(monitor):
    from dispositivi.models import orario_del_monitor

    orario = orario_del_monitor(monitor)
    if orario is None:
        return None
    return {"nome": orario.nome, "fasce": orario.fasce, "chiusure": orario.chiusure}


def eventi_del_monitor(monitor):
    """Gli eventi straordinari non ancora finiti per questo schermo (al massimo i prossimi 120 giorni)."""
    from django.utils import timezone

    destinatari = Q(monitor=monitor) | Q(gruppi__monitor=monitor)
    if monitor.sede.insegna_id:
        destinatari |= Q(insegne=monitor.sede.insegna_id)
    adesso = timezone.now()
    return (
        EventoStraordinario.objects.filter(destinatari, attivo=True, fine__gt=adesso, inizio__lt=adesso + timedelta(days=120))
        .select_related("contenuto").distinct().order_by("inizio")
    )


def dirette_a_orari(pubblicazioni, adesso=None) -> tuple[list, dict]:
    """Le dirette delle promozioni da mandare a certe ore («alle 12:00 per 5 minuti»): per oggi e
    domani diventano interruzioni come gli eventi straordinari (il player ferma le slide, manda la
    diretta e poi riprende). Valgono le date, i giorni e la fascia oraria della promozione."""
    from django.utils import timezone

    from .campagne import durata_voce
    from .models import ContenutoPromozione

    adesso = adesso or timezone.now()
    locale = timezone.localtime(adesso)
    # Le dirette vanno ai monitor (orizzontali): non dalla parte verticale (totem) della promozione.
    attive = {p.promozione_id: p for p in pubblicazioni if p.attiva and p.promozione_id and p.orientamento != "verticale"}
    if not attive:
        return [], {}
    voci = ContenutoPromozione.objects.filter(promozione_id__in=attive, ripeti__modo="orari").select_related("contenuto", "promozione__campagna")
    eventi, contenuti = [], {}
    for voce in voci:
        promo, pubblicazione = voce.promozione, attive[voce.promozione_id]
        durata = durata_voce(voce.contenuto, voce.durata, promo.campagna) or 300
        for giorno in (locale.date(), locale.date() + timedelta(days=1)):
            if not (promo.data_inizio <= giorno <= promo.data_fine) or (promo.giorni and giorno.weekday() not in promo.giorni):
                continue
            for orario in voce.ripeti.get("orari") or []:
                ore, minuti = (int(x) for x in orario.split(":"))
                inizio_ora = time(ore, minuti)
                if (promo.ora_inizio and inizio_ora < promo.ora_inizio) or (promo.ora_fine and inizio_ora >= promo.ora_fine):
                    continue
                inizio = timezone.make_aware(datetime.combine(giorno, inizio_ora))
                fine = inizio + timedelta(seconds=durata)
                if fine <= adesso:
                    continue
                eventi.append({
                    "id": f"diretta-{voce.id}-{giorno.isoformat()}-{orario}", "nome": f"{promo.nome} · diretta delle {orario}",
                    "contenuto": str(voce.contenuto_id), "inizio": inizio.isoformat(), "fine": fine.isoformat(),
                    "audio": voce.audio, "volume": 80, "schermo_intero": False, "playlist": str(pubblicazione.playlist_id),
                })
                contenuti[str(voce.contenuto_id)] = voce.contenuto
    return sorted(eventi, key=lambda e: e["inizio"]), contenuti


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
    elif contenuto.tipo == Tipo.DIRETTA:
        voce.update(url=contenuto.url, logo=contenuto.logo_url)
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


def annunci_della_sede(sede_id):
    from eliminacode.annunci import annunci_della_sede as calcola

    return calcola(sede_id)


def chiave_totem(sede_id) -> str:
    """La chiave con cui i totem secondari chiedono i biglietti al Totem Master (server code)
    della sede. Derivata dalla chiave del server: non si salva e cambia con lei."""
    return hmac.new(settings.SECRET_KEY.encode(), f"totem-secondario:{sede_id}".encode(), sha256).hexdigest()


def code_del_monitor(monitor, layout: dict) -> dict:
    """Dove sono le code del negozio. Le tiene il servizio code del Totem Master della sede:
    i monitor leggono i numeri da lì; il master riceve la configurazione dei reparti (con le
    impronte delle chiavi delle bilance e dei totem secondari) da passare al suo servizio; i
    totem secondari ricevono la chiave per chiedergli i biglietti. Senza un master indicato,
    come prima: ogni totem con la zona «prendi il numero» tiene le code in locale."""
    from dispositivi.models import Monitor
    from eliminacode.models import CredenzialePulsante, Reparto

    totem = monitor.sede.indirizzo_totem
    if not totem:
        return {"modo": "server"}
    code = {"modo": "totem", "indirizzo": f"https://{totem}:{PORTA_CODE_HTTPS}"}
    ha_prendi_numero = any(z["tipo"] == "prendi_numero" for z in layout["zone"])
    master = Monitor.objects.filter(sede_id=monitor.sede_id, totem_master=True).values_list("id", flat=True).first()
    if master is not None and master != monitor.id:
        if ha_prendi_numero:
            code["chiave"] = chiave_totem(monitor.sede_id)
        return code
    if master is None and not ha_prendi_numero:
        return code
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
    if master is not None:
        code["totem"] = [sha256(chiave_totem(monitor.sede_id).encode()).hexdigest()]
    return code


def manifest(monitor) -> dict:
    """Tutto ciò che serve al player per andare avanti da solo: layout, file, playlist e regole."""
    pubblicazioni = list(pubblicazioni_del_monitor(monitor))
    layout = descrivi(layout_del_monitor(monitor), monitor.orientamento)
    for zona in layout["zone"]:
        # La stampante abbinata al totem vale sopra quella della zona (vedi dispositivi.stampanti).
        if zona["tipo"] == "prendi_numero":
            zona["configurazione"] = applica_stampante(monitor, zona["configurazione"])
    playlist_fisse, immagini_layout = riferimenti(layout)
    playlist_ids = {str(p.playlist_id) for p in pubblicazioni} | playlist_fisse
    elementi = (
        ElementoPlaylist.objects.filter(playlist_id__in=playlist_ids)
        .select_related("contenuto")
        .order_by("playlist_id", "ordine")
    )

    playlist = {}
    eventi = list(eventi_del_monitor(monitor))
    riserva = str(monitor.immagine_riserva_id) if monitor.immagine_riserva_id else None
    contenuti = {str(c.id): c for c in Contenuto.objects.filter(id__in=immagini_layout | ({riserva} if riserva else set()))}
    for evento in eventi:
        contenuti[str(evento.contenuto_id)] = evento.contenuto
    interruzioni, contenuti_interruzioni = dirette_a_orari(pubblicazioni)
    contenuti.update(contenuti_interruzioni)
    for elemento in elementi:
        voce = {"contenuto": str(elemento.contenuto_id), "durata": durata_effettiva(elemento)}
        if elemento.audio:
            voce["audio"] = True
        playlist.setdefault(str(elemento.playlist_id), []).append(voce)
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
        # Quando lo schermo è acceso (fasce per giorno, chiusure); null: sempre.
        "accensione": accensione_del_monitor(monitor),
        # Quando scaricare i file nuovi e a che velocità; null: sempre, senza limiti.
        "download": download_del_monitor(monitor),
        # Precedenza su tutto, dall'inizio alla fine (istanti assoluti, con il fuso).
        "eventi": [
            {
                "id": str(e.id), "nome": e.nome, "contenuto": str(e.contenuto_id),
                "inizio": e.inizio.isoformat(), "fine": e.fine.isoformat(),
                "audio": e.audio, "volume": e.volume, "schermo_intero": e.schermo_intero,
            }
            for e in eventi
        ] + interruzioni,
        "contenuti": {chiave: _voce(contenuto) for chiave, contenuto in contenuti.items()},
        "code": code_del_monitor(monitor, layout),
        # La coda sul telefono: indirizzo per il QR sul biglietto; null se non attiva.
        "telefono": telefono_per_manifest(),
        # I file audio dei numeri chiamati, per i reparti della sede che li hanno.
        "annunci": annunci_della_sede(monitor.sede_id),
        # La stampante dei biglietti abbinata (per la stampa di prova); null: quella del layout.
        "stampante": per_il_player_stampante(monitor.stampante if monitor.stampante_id else None),
    }
    # I plugin (Info Prezzo, Info Ingredienti): come mostrarli e, al Totem Master, dove cercare.
    corpo["plugin"], servizio_plugin = plugin_del_monitor(monitor, corpo["code"])
    if servizio_plugin:
        corpo["code"]["plugin"] = servizio_plugin
    # La versione dipende solo dal contenuto: se nulla cambia, il player non riscarica.
    corpo["versione"] = sha256(json.dumps(corpo, sort_keys=True).encode()).hexdigest()
    return corpo
