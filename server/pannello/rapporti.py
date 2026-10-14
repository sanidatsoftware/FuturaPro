"""I rapporti mandati da soli per email (InvioRapporto): messa in onda, tempi d'attesa,
disponibilità degli schermi. Li controlla il pianificatore ogni minuto; ogni periodo parte una
volta sola, dalle 7 del mattino. Il server email è quello generale (core.email)."""

import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from core import email
from core.contesto import contesto_cliente, contesto_piattaforma

from .models import InvioRapporto

ORA_INVIO = 7
RIPROVA_DOPO = timedelta(minutes=30)


def periodo(frequenza: str, oggi: date) -> tuple[str, date, date]:
    """Il periodo appena concluso: (etichetta, dal, al)."""
    if frequenza == InvioRapporto.Frequenza.GIORNALIERA:
        ieri = oggi - timedelta(days=1)
        return ieri.isoformat(), ieri, ieri
    if frequenza == InvioRapporto.Frequenza.MENSILE:
        al = oggi.replace(day=1) - timedelta(days=1)
        return al.strftime("%Y-%m"), al.replace(day=1), al
    lunedi = oggi - timedelta(days=oggi.weekday() + 7)
    anno, settimana, _ = lunedi.isocalendar()
    return f"{anno}-W{settimana:02d}", lunedi, lunedi + timedelta(days=6)


def _csv(intestazione, righe) -> str:
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    scrittore.writerow(intestazione)
    scrittore.writerows(righe)
    return "﻿" + uscita.getvalue()


def _ore(secondi):
    return f"{secondi / 3600:.1f}".replace(".", ",")


def _messa_in_onda(invio, dal, al):
    from contenuti.messa_in_onda import RAGGRUPPAMENTI, rapporto
    from contenuti.models import MessaInOnda

    filtri = invio.filtri or {}
    righe = MessaInOnda.objects.filter(giorno__gte=dal, giorno__lte=al)
    if filtri.get("fornitore"):
        righe = righe.filter(fornitore=filtri["fornitore"])
    for campo in ("campagna", "sede"):
        if filtri.get(campo):
            righe = righe.filter(**{f"{campo}_id": filtri[campo]})
    raggruppa = filtri.get("raggruppa") if filtri.get("raggruppa") in RAGGRUPPAMENTI else "campagna"
    dati = rapporto(righe, raggruppa)
    t = dati["totale"]
    testo = [
        f"Messa in onda dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}" + (f" — fornitore {filtri['fornitore']}" if filtri.get("fornitore") else ""),
        "",
        f"Totale: {t['passaggi']} passaggi, {_ore(t['secondi'])} ore in onda, {t['negozi']} negozi, {t['schermi']} schermi.",
        "",
    ]
    for r in dati["righe"][:20]:
        testo.append(f"- {r['nome']}: {r['passaggi']} passaggi, {_ore(r['secondi'])} ore, {r['negozi']} negozi")
    if len(dati["righe"]) > 20:
        testo.append(f"… e altre {len(dati['righe']) - 20} righe nel file allegato.")
    allegato = _csv(
        [RAGGRUPPAMENTI[raggruppa][1], "Passaggi", "Ore in onda", "Schermi", "Negozi", "Giorni"],
        [[r["nome"], r["passaggi"], _ore(r["secondi"]), r["schermi"], r["negozi"], r["giorni"]] for r in dati["righe"] + [t]],
    )
    return testo, [(f"messa-in-onda-{dal}-{al}.csv", allegato, "text/csv")]


def _attese(invio, dal, al):
    from eliminacode.models import Reparto
    from eliminacode.statistiche import calcola

    reparti = list(Reparto.objects.select_related("sede").order_by("sede__nome", "ordine", "nome"))
    dati = calcola(reparti, dal, al)
    minuti = lambda m: "—" if m is None else f"{m:.0f} min".replace(".", ",")  # noqa: E731
    testo = [f"Tempi d'attesa dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}", ""]
    righe = []
    for r in dati["reparti"]:
        if not r["biglietti"] and not r["serviti"]:
            continue
        testo.append(f"- {r['nome']} ({r['sede']}): {r['biglietti']} biglietti, attesa media {minuti(r['attesa_media'])}, "
                     f"9 su 10 entro {minuti(r['attesa_p90'])}, rinunce {r['rinunce']}")
        righe.append([r["nome"], r["sede"], r["biglietti"], r["serviti"], r["attesa_media"], r["attesa_p90"], r["attesa_massima"], r["rinunce"], r["serviti_ora"]])
    critiche = sorted((c for c in dati["mappa"] if c["attesa_media"] and c["biglietti"] >= 5), key=lambda c: -c["attesa_media"])[:3]
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    if critiche:
        testo += ["", "Fasce con più attesa:"] + [f"- {giorni[c['giorno']]} {c['ora']}–{c['ora'] + 1}: {minuti(c['attesa_media'])} ({c['biglietti']} biglietti)" for c in critiche]
    allegato = _csv(["Reparto", "Negozio", "Biglietti", "Serviti", "Attesa media (min)", "9 su 10 entro (min)", "Massima (min)", "Rinunce", "Serviti all'ora"], righe)
    return testo, [(f"tempi-attesa-{dal}-{al}.csv", allegato, "text/csv")]


def _schermi(invio, dal, al):
    from dispositivi.models import Monitor, PresenzaSchermo, acceso_secondo_orario, orario_del_monitor

    testo = [f"Disponibilità degli schermi dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}", ""]
    righe = []
    for m in Monitor.objects.select_related("sede").order_by("sede__nome", "nome"):
        orario = orario_del_monitor(m)
        atteso = 0
        giorno = dal
        while giorno <= al:
            inizio = timezone.make_aware(datetime.combine(giorno, time(0, 0)))
            atteso += sum(10 for passo in range(144) if acceso_secondo_orario(orario, timezone.localtime(inizio + timedelta(minutes=10 * passo + 5))))
            giorno += timedelta(days=1)
        presenze = PresenzaSchermo.objects.filter(monitor=m, giorno__gte=dal, giorno__lte=al)
        in_linea = sum(max(0, p.minuti - p.minuti_riposo) for p in presenze)
        quota = round(min(1, in_linea / atteso) * 100) if atteso else None
        testo.append(f"- {m.nome} ({m.sede.nome}): {'—' if quota is None else f'{quota}%'} del tempo previsto")
        righe.append([m.nome, m.sede.nome, round(in_linea / 60, 1), round(atteso / 60, 1), "" if quota is None else quota])
    allegato = _csv(["Schermo", "Negozio", "Ore in linea", "Ore previste", "Disponibilità %"], righe)
    return testo, [(f"schermi-{dal}-{al}.csv", allegato, "text/csv")]


PRODUTTORI = {"messa_in_onda": _messa_in_onda, "attese": _attese, "schermi": _schermi}


def manda(invio, dal, al) -> None:
    """Prepara e manda il rapporto del periodo; solleva un'eccezione se non parte."""
    from .models import Aspetto

    testo, allegati = PRODUTTORI[invio.tipo](invio, dal, al)
    nome_app = Aspetto.attuale().nome_app
    testo += ["", f"— {nome_app}: rapporto «{invio.nome}», inviato in automatico. Per non riceverlo più chiedi a chi gestisce il pannello."]
    email.invia(f"{nome_app}: {invio.nome} ({dal:%d/%m}–{al:%d/%m/%Y})", "\n".join(testo), invio.email, allegati=allegati)


def controlla(adesso=None) -> int:
    """Manda i rapporti dovuti (dalle 7 del mattino, una volta per periodo)."""
    adesso = adesso or timezone.now()
    locale = timezone.localtime(adesso)
    if locale.hour < ORA_INVIO:
        return 0
    with contesto_piattaforma():
        attivi = list(InvioRapporto.objects.filter(attivo=True).values_list("id", "cliente_id"))
    mandati = 0
    for invio_id, cliente_id in attivi:
        with contesto_cliente(cliente_id):
            invio = InvioRapporto.objects.get(id=invio_id)
            etichetta, dal, al = periodo(invio.frequenza, locale.date())
            # Il server email è quello dell'azienda: senza, non si prova nemmeno.
            if invio.ultimo_periodo == etichetta or not email.configurata():
                continue
            if invio.ultimo_errore and invio.ultimo_invio and adesso - invio.ultimo_invio < RIPROVA_DOPO:
                continue
            try:
                manda(invio, dal, al)
            except Exception as errore:
                invio.ultimo_errore = str(errore)[:300]
                invio.ultimo_invio = adesso
                invio.save(update_fields=["ultimo_errore", "ultimo_invio"])
                continue
            invio.ultimo_periodo = etichetta
            invio.ultimo_invio = adesso
            invio.ultimo_errore = ""
            invio.save(update_fields=["ultimo_periodo", "ultimo_invio", "ultimo_errore"])
            mandati += 1
    return mandati
