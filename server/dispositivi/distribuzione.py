"""Distribuzione contenuti: i file del palinsesto sono arrivati agli schermi? E cosa va in onda?

Il player riferisce a ogni segnale periodico (ogni 10 secondi mentre scarica) quanti file e
byte del palinsesto più recente ha già, quali mancano, il file in corso e la velocità, e cosa
mostra ogni zona slide. Qui quei dati si confrontano con il manifest che lo schermo dovrebbe
avere adesso: così si vede se una promozione appena salvata è già arrivata ovunque.
"""

from __future__ import annotations

from django.utils import timezone

STATI = ("aggiornato", "pronto", "scaricamento", "fascia", "errore", "in_arrivo", "offline", "mai_collegato")
MASSIMO_MANCANTI = 300


def _intero(valore, massimo=10**13) -> int:
    try:
        return max(0, min(massimo, int(valore)))
    except (TypeError, ValueError):
        return 0


def pulisci_avanzamento(dati) -> dict | None:
    """Quello che riferisce il player, ridotto a numeri e testi brevi."""
    if not isinstance(dati, dict):
        return None
    in_corso = dati.get("in_corso")
    if isinstance(in_corso, dict):
        in_corso = {"nome": str(in_corso.get("nome") or "")[:200], "byte": _intero(in_corso.get("byte")), "totale": _intero(in_corso.get("totale"))}
    else:
        in_corso = None
    mancanti = [str(m)[:64] for m in (dati.get("mancanti") or [])[:MASSIMO_MANCANTI] if isinstance(m, str)]
    return {
        "versione": str(dati.get("versione") or "")[:64],
        "file": _intero(dati.get("file"), 100_000), "presenti": _intero(dati.get("presenti"), 100_000),
        "byte": _intero(dati.get("byte")), "byte_presenti": _intero(dati.get("byte_presenti")),
        "mancanti": mancanti, "in_corso": in_corso, "falliti": _intero(dati.get("falliti"), 100_000),
        "velocita": _intero(dati.get("velocita")), "senza_cache": dati.get("senza_cache") is True,
    }


def pulisci_in_onda(dati) -> list | None:
    if not isinstance(dati, list):
        return None
    voci = []
    for voce in dati[:12]:
        if isinstance(voce, dict) and voce.get("contenuto"):
            voci.append({
                "zona": str(voce.get("zona") or "")[:64], "contenuto": str(voce["contenuto"])[:64],
                "playlist": str(voce.get("playlist") or "")[:64] or None, "evento": str(voce.get("evento") or "")[:64] or None,
                "riserva": voce.get("riserva") is True, "da": str(voce.get("da") or "")[:40],
            })
    return voci


def _percentuale(parte, tutto) -> int:
    if not tutto:
        return 100
    return min(100, int(parte * 100 // tutto))


def _promozione_di(pubblicazione) -> dict:
    promozione = pubblicazione.promozione
    if promozione is None:
        return {"chiave": f"p-{pubblicazione.id}", "nome": pubblicazione.nome, "campagna": "", "colore": "#6b7280"}
    campagna = promozione.campagna
    return {"chiave": str(promozione.id), "nome": promozione.nome, "campagna": campagna.nome, "colore": campagna.colore}


def stato_schermo(monitor, adesso=None) -> dict:
    """Lo stato di distribuzione di un monitor: va calcolato nel contesto del suo cliente."""
    from contenuti import palinsesto
    from contenuti.models import Contenuto

    adesso = timezone.localtime(adesso or timezone.now())
    corpo = palinsesto.manifest(monitor)
    versione = corpo["versione"]
    info = monitor.info_dispositivo or {}
    riferito = info.get("distribuzione") or {}
    file = {}
    for voce in corpo["contenuti"].values():
        if voce.get("sha256"):
            file.setdefault(voce["sha256"], voce)
    byte_totali = sum(int(v.get("dimensione") or 0) for v in file.values())

    aggiornato = bool(monitor.manifest_ricevuto) and monitor.manifest_ricevuto == versione
    stesso = riferito.get("versione") == versione
    in_corso = riferito.get("in_corso") if stesso else None
    if aggiornato or (stesso and riferito.get("senza_cache")):
        mancanti = set()
    elif stesso:
        mancanti = set(riferito.get("mancanti") or []) & set(file)
    else:
        mancanti = None  # il monitor non ha ancora visto questa versione: non si sa
    if mancanti is None:
        file_presenti = byte_presenti = None
        percentuale = None
    else:
        file_presenti = len(file) - len(mancanti)
        byte_presenti = sum(int(v.get("dimensione") or 0) for sha, v in file.items() if sha not in mancanti)
        if in_corso:
            byte_presenti += min(in_corso.get("byte", 0), in_corso.get("totale") or in_corso.get("byte", 0))
        percentuale = _percentuale(byte_presenti, byte_totali) if byte_totali else _percentuale(file_presenti, len(file))

    if monitor.ultimo_contatto is None:
        stato = "mai_collegato"
    elif not monitor.online:
        stato = "offline"
    elif aggiornato:
        stato = "aggiornato"
    elif not stesso:
        stato = "in_arrivo"
    elif info.get("attesa_download"):
        stato = "fascia"
    elif in_corso:
        stato = "scaricamento"
    elif riferito.get("falliti"):
        stato = "errore"
    elif not mancanti:
        stato = "pronto"
    else:
        stato = "scaricamento"

    # Le promozioni di questo schermo: i loro file ci sono tutti?
    pubblicazioni = list(palinsesto.pubblicazioni_del_monitor(monitor).select_related("promozione__campagna"))
    ora_in_onda = {p.id for p in palinsesto.in_onda(pubblicazioni, adesso)}
    per_playlist = {}
    promozioni = []
    for p in pubblicazioni:
        descrizione = _promozione_di(p)
        per_playlist[str(p.playlist_id)] = descrizione
        sha = {corpo["contenuti"][e["contenuto"]].get("sha256") for e in corpo["playlist"].get(str(p.playlist_id), [])
               if e["contenuto"] in corpo["contenuti"]} - {None}
        promozioni.append({
            **descrizione, "file": len(sha), "byte": sum(int(file[s].get("dimensione") or 0) for s in sha if s in file),
            "completa": None if mancanti is None else not (sha & mancanti), "in_onda": p.id in ora_in_onda,
            "fino_al": p.data_fine and p.data_fine.isoformat(),
        })

    # Cosa mostra adesso ogni zona slide (come riferito dal player).
    voci_in_onda = info.get("in_onda") or []
    sconosciuti = {v["contenuto"] for v in voci_in_onda if v["contenuto"] not in corpo["contenuti"]}
    altri = {str(c.id): {"nome": c.nome, "tipo": c.tipo} for c in Contenuto.objects.filter(id__in=sconosciuti)} if sconosciuti else {}
    eventi = {e["id"]: e["nome"] for e in corpo["eventi"]}
    in_onda = []
    if monitor.online and not info.get("riposo"):
        for v in voci_in_onda:
            voce = corpo["contenuti"].get(v["contenuto"]) or altri.get(v["contenuto"]) or {"nome": "Contenuto rimosso", "tipo": ""}
            promozione = per_playlist.get(v.get("playlist") or "")
            in_onda.append({
                "zona": v["zona"], "contenuto": v["contenuto"], "nome": voce.get("nome", ""), "tipo": voce.get("tipo", ""),
                "promozione": promozione["nome"] if promozione else "", "campagna": promozione["campagna"] if promozione else "",
                "colore": promozione["colore"] if promozione else "", "evento": eventi.get(v.get("evento") or "", ""),
                "riserva": v.get("riserva", False), "da": v.get("da", ""),
            })

    fascia = corpo.get("download")
    return {
        "id": str(monitor.id), "nome": monitor.nome, "sede": monitor.sede.nome, "sede_id": str(monitor.sede_id),
        "orientamento": monitor.orientamento, "online": monitor.online, "riposo": bool(info.get("riposo")),
        "stato": stato, "percentuale": percentuale,
        "file_totali": len(file), "file_presenti": file_presenti, "byte_totali": byte_totali, "byte_presenti": byte_presenti,
        "in_corso": in_corso and {**in_corso, "percentuale": _percentuale(in_corso.get("byte", 0), in_corso.get("totale", 0))},
        "velocita": riferito.get("velocita", 0) if in_corso else 0, "falliti": riferito.get("falliti", 0) if stesso else 0,
        "fascia": fascia and {"dalle": fascia.get("dalle"), "alle": fascia.get("alle"), "kbps": fascia.get("kbps")},
        "ultimo_contatto": monitor.ultimo_contatto, "riferito": riferito.get("riferito") if stesso else None,
        "schermata_il": monitor.schermata_il, "in_onda": in_onda, "promozioni": promozioni,
    }


def riepilogo(schermi: list) -> dict:
    """Totali per stato e byte, per sede e per promozione."""
    conteggi = {s: 0 for s in STATI}
    for s in schermi:
        conteggi[s["stato"]] += 1
    noti = [s for s in schermi if s["byte_presenti"] is not None]
    byte_totali = sum(s["byte_totali"] for s in schermi)
    byte_presenti = sum(s["byte_presenti"] for s in noti)
    sedi = {}
    for s in schermi:
        sede = sedi.setdefault(s["sede_id"], {"id": s["sede_id"], "nome": s["sede"], "schermi": []})
        sede["schermi"].append(s)
    for sede in sedi.values():
        sede["aggiornati"] = sum(1 for s in sede["schermi"] if s["stato"] == "aggiornato")
        sede["percentuale"] = _percentuale(sum(s["byte_presenti"] or 0 for s in sede["schermi"]), sum(s["byte_totali"] for s in sede["schermi"]))
    promozioni = {}
    for s in schermi:
        for p in s["promozioni"]:
            voce = promozioni.setdefault(p["chiave"], {**{k: p[k] for k in ("chiave", "nome", "campagna", "colore", "fino_al")},
                                                     "schermi": 0, "completi": 0, "in_onda_su": 0, "file": 0, "byte": 0})
            voce["schermi"] += 1
            voce["completi"] += 1 if p["completa"] else 0
            voce["in_onda_su"] += 1 if p["in_onda"] and s["stato"] == "aggiornato" and not s["riposo"] else 0
            voce["file"] = max(voce["file"], p["file"])
            voce["byte"] = max(voce["byte"], p["byte"])
    for voce in promozioni.values():
        voce["percentuale"] = _percentuale(voce["completi"], voce["schermi"])
    return {
        "schermi": len(schermi), "stati": conteggi, "online": sum(1 for s in schermi if s["online"]),
        "byte_totali": byte_totali, "byte_presenti": byte_presenti,
        "percentuale": _percentuale(sum(1 for s in schermi if s["stato"] == "aggiornato"), len(schermi)),
        "velocita": sum(s["velocita"] for s in schermi),
        "sedi": sorted(sedi.values(), key=lambda x: x["nome"].lower()),
        "promozioni": sorted(promozioni.values(), key=lambda p: (p["percentuale"], p["nome"].lower())),
    }
