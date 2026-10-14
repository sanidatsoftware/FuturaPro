"""Il registro di messa in onda: cosa è andato davvero sugli schermi, dove e per quanto.

I player mandano i passaggi a pacchetti; qui si riassumono per giorno, schermo, contenuto e
promozione (``MessaInOnda``), così il registro resta piccolo anche con molti schermi.
"""

import csv
import io
import uuid
from collections import defaultdict

from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Contenuto, EventoStraordinario, MessaInOnda, Pubblicazione

MASSIMO_PASSAGGI = 5000


def _uuid(valore):
    try:
        return str(uuid.UUID(str(valore)))
    except (ValueError, TypeError):
        return None


def registra(monitor, passaggi: list) -> int:
    """Passaggi: {contenuto, playlist?, evento?, riserva?, inizio (ISO), secondi}."""
    validi = []
    for p in passaggi[:MASSIMO_PASSAGGI]:
        if not isinstance(p, dict):
            continue
        contenuto = _uuid(p.get("contenuto"))
        inizio = parse_datetime(str(p.get("inizio", "")))
        try:
            secondi = int(round(float(p.get("secondi", 0))))
        except (TypeError, ValueError):
            continue
        if not contenuto or inizio is None or secondi < 1:
            continue
        if timezone.is_naive(inizio):
            inizio = timezone.make_aware(inizio)
        validi.append((contenuto, _uuid(p.get("playlist")), _uuid(p.get("evento")), bool(p.get("riserva")), inizio, min(secondi, 86400)))
    if not validi:
        return 0
    contenuti = {str(c.id): c for c in Contenuto.objects.filter(id__in={v[0] for v in validi})}
    pubblicazioni = {
        str(p.playlist_id): p
        for p in Pubblicazione.objects.filter(playlist_id__in={v[1] for v in validi if v[1]}).select_related("promozione__campagna")
    }
    eventi = {str(e.id): e for e in EventoStraordinario.objects.filter(id__in={v[2] for v in validi if v[2]})}

    somme = defaultdict(lambda: [0, 0, None])
    for contenuto_id, playlist, evento_id, riserva, inizio, secondi in validi:
        contenuto = contenuti.get(contenuto_id)
        if contenuto is None:
            continue
        promozione = campagna = None
        if evento_id:
            origine = MessaInOnda.Origine.EVENTO
            nome_promozione = eventi[evento_id].nome if evento_id in eventi else "Evento straordinario"
        elif riserva:
            origine, nome_promozione = MessaInOnda.Origine.RISERVA, ""
        else:
            pubblicazione = pubblicazioni.get(playlist or "")
            promozione = pubblicazione.promozione if pubblicazione else None
            campagna = promozione.campagna if promozione else None
            origine = MessaInOnda.Origine.PROMOZIONE if promozione else MessaInOnda.Origine.PLAYLIST
            nome_promozione = promozione.nome if promozione else (pubblicazione.nome if pubblicazione else "")
        giorno = timezone.localdate(inizio)
        chiave = f"{giorno.isoformat()}|{monitor.id}|{contenuto.id}|{promozione.id if promozione else evento_id or ''}|{origine}"
        somma = somme[chiave]
        somma[0] += 1
        somma[1] += secondi
        somma[2] = (giorno, origine, contenuto, promozione, campagna, nome_promozione)

    for chiave, (passaggi_, secondi, (giorno, origine, contenuto, promozione, campagna, nome_promozione)) in somme.items():
        riga, creata = MessaInOnda.objects.get_or_create(chiave=chiave, defaults={
            "cliente_id": monitor.cliente_id, "giorno": giorno, "monitor": monitor, "sede_id": monitor.sede_id,
            "origine": origine, "contenuto": contenuto, "nome_contenuto": contenuto.nome[:200],
            "promozione": promozione, "nome_promozione": nome_promozione[:200],
            "campagna": campagna, "nome_campagna": campagna.nome if campagna else "",
            "fornitore": campagna.fornitore if campagna else "",
            "passaggi": passaggi_, "secondi": secondi,
        })
        if not creata:
            MessaInOnda.objects.filter(id=riga.id).update(passaggi=F("passaggi") + passaggi_, secondi=F("secondi") + secondi)
    return len(validi)


RAGGRUPPAMENTI = {
    "campagna": ("nome_campagna", "Campagna"),
    "promozione": ("nome_promozione", "Promozione"),
    "fornitore": ("fornitore", "Fornitore"),
    "contenuto": ("nome_contenuto", "Contenuto"),
    "sede": ("sede__nome", "Negozio"),
    "monitor": ("monitor__nome", "Schermo"),
    "giorno": ("giorno", "Giorno"),
}


def rapporto(righe, raggruppa: str) -> dict:
    """Le righe del registro riassunte per campagna, promozione, fornitore, negozio…"""
    campo, _ = RAGGRUPPAMENTI[raggruppa]
    gruppi = defaultdict(lambda: {"passaggi": 0, "secondi": 0, "schermi": set(), "sedi": set(), "giorni": set()})
    totale = {"passaggi": 0, "secondi": 0, "schermi": set(), "sedi": set(), "giorni": set()}
    for r in righe.values(campo, "passaggi", "secondi", "monitor_id", "sede_id", "giorno"):
        nome = r[campo]
        nome = nome.isoformat() if hasattr(nome, "isoformat") else (nome or "—")
        for g in (gruppi[nome], totale):
            g["passaggi"] += r["passaggi"]
            g["secondi"] += r["secondi"]
            g["schermi"].add(r["monitor_id"])
            g["sedi"].add(r["sede_id"])
            g["giorni"].add(r["giorno"])

    def piatto(nome, g):
        return {"nome": nome, "passaggi": g["passaggi"], "secondi": g["secondi"], "schermi": len(g["schermi"]),
                "negozi": len(g["sedi"] - {None}), "giorni": len(g["giorni"])}

    elenco = [piatto(n, g) for n, g in gruppi.items()]
    elenco.sort(key=lambda x: x["nome"] if raggruppa == "giorno" else -x["secondi"])
    return {"righe": elenco, "totale": piatto("Totale", totale)}


def csv_del_rapporto(dati, raggruppa) -> str:
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    scrittore.writerow([RAGGRUPPAMENTI[raggruppa][1], "Passaggi", "Ore in onda", "Schermi", "Negozi", "Giorni"])
    for r in dati["righe"] + [dati["totale"]]:
        scrittore.writerow([r["nome"], r["passaggi"], f"{r['secondi'] / 3600:.2f}".replace(".", ","), r["schermi"], r["negozi"], r["giorni"]])
    return "﻿" + uscita.getvalue()
