"""La Panoramica: la pagina iniziale con il colpo d'occhio su tutto (schermi, contenuti,
palinsesto, code, plugin, spazio, ultime operazioni) e, in cima, le cose da guardare.

``azienda()`` lavora nel contesto del cliente; la piattaforma la chiama per ogni azienda.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

MB = 1024 * 1024


def _avviso(livello, testo, scheda):
    return {"livello": livello, "testo": testo, "scheda": scheda}


def _fa(istante, adesso):
    if istante is None:
        return "mai collegato"
    minuti = int((adesso - istante).total_seconds() // 60)
    if minuti < 60:
        return f"da {minuti} min"
    if minuti < 2880:
        return f"da {minuti // 60} h"
    return f"da {minuti // 1440} giorni"


def azienda(sedi=None, con_registro=True, adesso=None) -> dict:
    """La panoramica dell'azienda del contesto; «sedi»: solo queste (User limitato)."""
    from audit.models import EventoAudit
    from clienti.models import Abilitazioni
    from contenuti.models import Contenuto, Promozione
    from dispositivi import distribuzione
    from dispositivi.models import Monitor
    from eliminacode.models import Biglietto, Reparto
    from plugin.api import stato_prova
    from plugin.models import FontePlugin

    adesso = adesso or timezone.now()
    oggi = timezone.localdate(adesso)
    avvisi = []

    # --- Schermi e distribuzione -------------------------------------------------------------
    monitor = list(Monitor.objects.select_related("sede").order_by("sede__nome", "nome"))
    if sedi is not None:
        monitor = [m for m in monitor if m.sede_id in sedi]
    schermi = [distribuzione.stato_schermo(m, adesso) for m in monitor]
    riepilogo = distribuzione.riepilogo(schermi)
    per_id = {str(m.id): m for m in monitor}
    spenti = sorted((s for s in schermi if not s["online"]), key=lambda s: per_id[s["id"]].ultimo_contatto or adesso)
    # Schermo nero: secondo il palinsesto del server non ha nulla da mostrare adesso (né promozioni,
    # né playlist del layout, né eventi, né default). Non si guarda quello che riferisce il player:
    # un player di una versione precedente non lo manda, e non vuol dire che non mostri nulla.
    neri = [s for s in schermi if s["online"] and not s["riposo"] and s["stato"] == "aggiornato" and not s["programmato"]]
    online = sum(1 for s in schermi if s["online"])
    in_allarme = sum(1 for m in monitor if m.allarme_dal)
    for s in spenti[:3]:
        avvisi.append(_avviso("critico", f"{s['nome']} ({s['sede']}) non è in linea {_fa(per_id[s['id']].ultimo_contatto, adesso)}", "stato"))
    if len(spenti) > 3:
        altri = len(spenti) - 3
        avvisi.append(_avviso("critico", "Un altro schermo non in linea" if altri == 1 else f"Altri {altri} schermi non in linea", "stato"))
    errori = [s for s in schermi if s["stato"] == "errore"]
    if errori:
        avvisi.append(_avviso("attenzione", f"{len(errori)} schermi non riescono a scaricare dei file", "distribuzione"))
    if neri:
        avvisi.append(_avviso("attenzione", f"{len(neri)} schermi accesi senza nulla in onda (né promozioni né default)", "monitor"))

    # --- Palinsesto: in onda, in partenza, in scadenza ---------------------------------------
    in_onda = [p for p in riepilogo["promozioni"] if p["in_onda_su"]]
    in_onda.sort(key=lambda p: -p["in_onda_su"])
    incomplete = [p for p in riepilogo["promozioni"] if p["percentuale"] < 100]
    promozioni = Promozione.objects.select_related("campagna")
    partenza = [
        {"nome": p.nome, "campagna": p.campagna.nome, "colore": p.campagna.colore, "dal": p.data_inizio, "al": p.data_fine}
        for p in promozioni.filter(data_inizio__gt=oggi, data_inizio__lte=oggi + timedelta(days=7)).order_by("data_inizio")[:6]
    ]
    scadenza = [
        {"nome": p.nome, "campagna": p.campagna.nome, "colore": p.campagna.colore, "dal": p.data_inizio, "al": p.data_fine}
        for p in promozioni.filter(data_fine__gte=oggi, data_fine__lte=oggi + timedelta(days=3)).order_by("data_fine")[:6]
    ]
    # Una promozione che finisce presto e niente che parta dopo: gli schermi resteranno sul default.
    if scadenza and not promozioni.filter(data_inizio__gt=oggi, data_inizio__lte=oggi + timedelta(days=4)).exists():
        ultima = max(p["al"] for p in scadenza)
        avvisi.append(_avviso("attenzione", f"Le promozioni finiscono il {ultima.strftime('%d/%m')} e non ne parte nessuna dopo", "palinsesto"))

    # --- Code di oggi --------------------------------------------------------------------------
    reparti = Reparto.objects.select_related("sede").order_by("sede__nome", "ordine", "nome")
    if sedi is not None:
        reparti = reparti.filter(sede_id__in=sedi)
    biglietti = {}
    for b in Biglietto.objects.filter(giornata=oggi, reparto__in=reparti).only("reparto_id", "emesso_il", "chiamato_il"):
        voce = biglietti.setdefault(b.reparto_id, {"emessi": 0, "chiamati": 0, "attesa": 0.0})
        voce["emessi"] += 1
        if b.chiamato_il:
            voce["chiamati"] += 1
            voce["attesa"] += (b.chiamato_il - b.emesso_il).total_seconds()
    code = []
    for r in reparti:
        voce = biglietti.get(r.id)
        if not voce:
            continue
        code.append({
            "reparto": r.nome, "sede": r.sede.nome, "colore": r.colore, "emessi": voce["emessi"], "chiamati": voce["chiamati"],
            "in_coda": voce["emessi"] - voce["chiamati"],
            "attesa_media": round(voce["attesa"] / voce["chiamati"] / 60, 1) if voce["chiamati"] else None,
        })

    # --- Plugin: le copie dei file e le prove di accesso --------------------------------------
    abilitazioni = Abilitazioni.objects.first()
    plugin = []
    fonti = FontePlugin.objects.select_related("sede")
    if sedi is not None:
        fonti = fonti.filter(sede_id__in=sedi)
    masters = {m.sede_id: m for m in monitor if m.totem_master}
    for f in fonti:
        if abilitazioni and not getattr(abilitazioni, f"plugin_{f.tipo}", False):
            continue
        copia = ((masters.get(f.sede_id) and masters[f.sede_id].info_dispositivo or {}).get("plugin") or {}).get(f.tipo) or {}
        prova = stato_prova(f)
        voce = {"tipo": f.tipo, "sede": f.sede.nome, "copiato": copia.get("copiato") or None, "errore": copia.get("errore") or None,
                "prova": prova["stato"]}
        plugin.append(voce)
        nome = "Info Prezzo" if f.tipo == "prezzo" else "Info Ingredienti"
        if voce["errore"]:
            avvisi.append(_avviso("attenzione", f"{nome} di {f.sede.nome}: la copia del file non riesce ({voce['errore'][:80]})", f"info_{f.tipo}"))
        elif prova["stato"] == "errore":
            avvisi.append(_avviso("attenzione", f"{nome} di {f.sede.nome}: la prova di accesso non è riuscita", f"info_{f.tipo}"))

    # --- Spazio ----------------------------------------------------------------------------------
    occupato = Contenuto.objects.aggregate(totale=Sum("dimensione"))["totale"] or 0
    disponibile = (abilitazioni.spazio_mb if abilitazioni else 0) * MB
    spazio = {"occupato": occupato, "disponibile": disponibile,
              "percentuale": min(100, round(occupato * 100 / disponibile)) if disponibile else 0}
    if spazio["percentuale"] >= 90:
        avvisi.append(_avviso("critico" if spazio["percentuale"] >= 98 else "attenzione",
                              f"Spazio quasi esaurito: {spazio['percentuale']}% usato", "palinsesto"))

    registro = []
    if con_registro:
        for e in EventoAudit.objects.order_by("-quando")[:6]:
            dettagli = e.dettagli if isinstance(getattr(e, "dettagli", None), dict) else {}
            registro.append({"quando": e.quando, "utente": e.utente, "azione": e.azione, "nome": str(dettagli.get("nome") or dettagli.get("username") or "")[:80]})

    avvisi.sort(key=lambda a: a["livello"] != "critico")
    return {
        "adesso": adesso,
        "avvisi": avvisi,
        "schermi": {
            "totale": len(schermi), "online": online, "riposo": sum(1 for s in schermi if s["online"] and s["riposo"]),
            "in_allarme": in_allarme, "senza_nulla": len(neri),
            "spenti": [{"nome": s["nome"], "sede": s["sede"], "da": _fa(per_id[s["id"]].ultimo_contatto, adesso)} for s in spenti[:6]],
        },
        "distribuzione": {k: riepilogo[k] for k in ("percentuale", "stati", "velocita", "byte_totali", "byte_presenti", "schermi")}
                         | {"incomplete": incomplete[:5]},
        "palinsesto": {"in_onda": in_onda[:6], "partenza": partenza, "scadenza": scadenza},
        "code": code,
        "plugin": plugin,
        "spazio": spazio,
        "registro": registro,
    }
