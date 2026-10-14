"""Gli allarmi degli schermi scollegati: li controlla `manage.py controlla_schermi`, ogni minuto.

Uno schermo è «scollegato» quando non manda il segnale periodico da più dei minuti scelti dal
cliente. Fuori dal suo orario di accensione non è un guasto (se il cliente lo chiede). Si manda
una email sola per scollegamento e, se richiesto, una quando torna in linea.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core.contesto import contesto_cliente, contesto_piattaforma

from .models import EventoSchermo, ImpostazioniAllarmi, Monitor, acceso_secondo_orario, orario_del_monitor


def email_configurata() -> bool:
    return bool(settings.EMAIL_HOST)


def durata(delta) -> str:
    minuti = int(delta.total_seconds() // 60)
    if minuti < 60:
        return f"{minuti} min"
    ore, minuti = divmod(minuti, 60)
    if ore < 48:
        return f"{ore} h {minuti} min" if minuti else f"{ore} h"
    return f"{ore // 24} giorni"


def invia(impostazioni, oggetto, testo) -> bool:
    if not impostazioni.email:
        return False
    try:
        send_mail(oggetto, testo, settings.DEFAULT_FROM_EMAIL, impostazioni.email, fail_silently=False)
        return True
    except Exception:
        return False


def controlla_cliente(impostazioni, adesso=None) -> dict:
    adesso = adesso or timezone.now()
    locale = timezone.localtime(adesso)
    soglia = adesso - timedelta(minutes=impostazioni.minuti)
    scollegati, tornati = [], []
    for monitor in Monitor.objects.select_related("sede"):
        if monitor.ultimo_contatto is None:
            continue  # mai collegato: non è un guasto, è da installare
        fuori = monitor.ultimo_contatto < soglia
        if fuori and monitor.allarme_dal is None:
            if impostazioni.solo_in_orario and not acceso_secondo_orario(orario_del_monitor(monitor), locale):
                continue
            monitor.allarme_dal = adesso
            monitor.save(update_fields=["allarme_dal"])
            scollegati.append(monitor)
        elif not fuori and monitor.allarme_dal is not None:
            tornati.append((monitor, adesso - monitor.allarme_dal))
            monitor.allarme_dal = None
            monitor.save(update_fields=["allarme_dal"])

    if scollegati:
        righe = [
            f"- {m.nome} ({m.sede.nome}): nessun segnale da {durata(adesso - m.ultimo_contatto)}, "
            f"ultimo contatto {timezone.localtime(m.ultimo_contatto):%d/%m %H:%M}"
            for m in scollegati
        ]
        testo = (
            "Questi schermi non rispondono:\n\n" + "\n".join(righe)
            + "\n\nControlla che siano accesi e collegati alla rete. Riceverai un'altra email quando tornano in linea."
        )
        inviata = invia(impostazioni, f"FuturaPro: {len(scollegati)} schermo/i scollegato/i", testo)
        for m in scollegati:
            EventoSchermo.objects.create(
                cliente_id=m.cliente_id, monitor=m, tipo=EventoSchermo.Tipo.SCOLLEGATO, email_inviata=inviata,
                dettaglio=f"ultimo contatto {timezone.localtime(m.ultimo_contatto):%d/%m %H:%M}",
            )
    if tornati:
        inviata = False
        if impostazioni.avvisa_ritorno:
            righe = [f"- {m.nome} ({m.sede.nome}): fuori linea per circa {durata(fuori)}" for m, fuori in tornati]
            inviata = invia(impostazioni, f"FuturaPro: {len(tornati)} schermo/i di nuovo in linea", "Di nuovo in linea:\n\n" + "\n".join(righe))
        for m, fuori in tornati:
            EventoSchermo.objects.create(
                cliente_id=m.cliente_id, monitor=m, tipo=EventoSchermo.Tipo.RICOLLEGATO, email_inviata=inviata,
                dettaglio=f"fuori linea per {durata(fuori)}",
            )
    return {"scollegati": len(scollegati), "tornati": len(tornati)}


def controlla_tutti(adesso=None) -> dict:
    with contesto_piattaforma():
        clienti = list(ImpostazioniAllarmi.objects.filter(attivo=True).values_list("cliente_id", flat=True))
    totale = {"clienti": 0, "scollegati": 0, "tornati": 0}
    for cliente_id in clienti:
        with contesto_cliente(cliente_id):
            impostazioni = ImpostazioniAllarmi.objects.get()
            esito = controlla_cliente(impostazioni, adesso)
        totale["clienti"] += 1
        totale["scollegati"] += esito["scollegati"]
        totale["tornati"] += esito["tornati"]
    return totale
