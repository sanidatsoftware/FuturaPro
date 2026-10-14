"""I tempi d'attesa ai banchi, dal registro dei biglietti (registro.py)."""

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from .models import Biglietto, ChiamataCoda


def _percentile(valori, quota):
    if not valori:
        return None
    ordinati = sorted(valori)
    return ordinati[min(len(ordinati) - 1, int(round(quota * (len(ordinati) - 1))))]


def _minuti(secondi):
    return None if secondi is None else round(secondi / 60, 1)


def calcola(reparti, dal, al) -> dict:
    """Riepilogo per reparto, mappa giorno × ora e andamento giorno per giorno."""
    oggi = timezone.localdate()
    biglietti = list(
        Biglietto.objects.filter(reparto__in=reparti, giornata__gte=dal, giornata__lte=al).values(
            "reparto_id", "giornata", "emesso_il", "chiamato_il"
        )
    )
    chiamate = list(
        ChiamataCoda.objects.filter(reparto__in=reparti, giornata__gte=dal, giornata__lte=al, operazione="avanti")
        .values("reparto_id", "giornata", "quando").order_by("quando")
    )
    attese = defaultdict(list)  # reparto -> secondi
    rinunce = defaultdict(int)
    mappa = defaultdict(list)  # (giorno settimana, ora) -> secondi d'attesa
    conteggio_mappa = defaultdict(int)
    per_giorno = defaultdict(lambda: {"biglietti": 0, "attese": []})
    for b in biglietti:
        locale = timezone.localtime(b["emesso_il"])
        chiave = (locale.weekday(), locale.hour)
        conteggio_mappa[chiave] += 1
        giorno = per_giorno[b["giornata"].isoformat()]
        giorno["biglietti"] += 1
        if b["chiamato_il"]:
            attesa = max(0, (b["chiamato_il"] - b["emesso_il"]).total_seconds())
            attese[b["reparto_id"]].append(attesa)
            mappa[chiave].append(attesa)
            giorno["attese"].append(attesa)
        elif b["giornata"] < oggi:
            rinunce[b["reparto_id"]] += 1

    # Ritmo del banco: clienti serviti per ora di apertura effettiva (tra la prima e l'ultima chiamata).
    serviti = defaultdict(int)
    ore_attive = defaultdict(float)
    per_reparto_giorno = defaultdict(list)
    for c in chiamate:
        serviti[c["reparto_id"]] += 1
        per_reparto_giorno[(c["reparto_id"], c["giornata"])].append(c["quando"])
    for (reparto_id, _), istanti in per_reparto_giorno.items():
        if len(istanti) > 1:
            ore_attive[reparto_id] += (istanti[-1] - istanti[0]).total_seconds() / 3600

    riepilogo = []
    for r in reparti:
        valori = attese.get(r.id, [])
        emessi = sum(1 for b in biglietti if b["reparto_id"] == r.id)
        riepilogo.append({
            "id": str(r.id), "nome": r.nome, "sede": r.sede.nome, "colore": r.colore,
            "biglietti": emessi, "serviti": serviti.get(r.id, 0), "rinunce": rinunce.get(r.id, 0),
            "attesa_media": _minuti(sum(valori) / len(valori)) if valori else None,
            "attesa_p90": _minuti(_percentile(valori, 0.9)),
            "attesa_massima": _minuti(max(valori)) if valori else None,
            "serviti_ora": round(serviti[r.id] / ore_attive[r.id], 1) if ore_attive.get(r.id) else None,
        })
    giorni = []
    giorno = dal
    while giorno <= al:
        dati = per_giorno.get(giorno.isoformat())
        valori = dati["attese"] if dati else []
        giorni.append({
            "giorno": giorno.isoformat(), "biglietti": dati["biglietti"] if dati else 0,
            "attesa_media": _minuti(sum(valori) / len(valori)) if valori else None,
        })
        giorno += timedelta(days=1)
    return {
        "reparti": riepilogo,
        "mappa": [
            {"giorno": g, "ora": h, "biglietti": conteggio_mappa[(g, h)], "attesa_media": _minuti(sum(v) / len(v)) if (v := mappa.get((g, h))) else None}
            for g in range(7) for h in range(24) if conteggio_mappa.get((g, h))
        ],
        "giorni": giorni,
    }
