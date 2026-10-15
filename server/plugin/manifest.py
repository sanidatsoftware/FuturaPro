"""Cosa dei plugin va nel manifest: ai dispositivi del negozio come mostrare le risposte,
al servizio code del Totem Master anche dove prendere il file e quale query eseguire."""

from core.email import decifra

from .api import abilitato, aspetto_pulito
from .models import FontePlugin, ImpostazioniPlugin
from .query import query_di


def per_il_monitor(monitor, code: dict):
    """(per il player, per il servizio code); None quando non c'è nulla."""
    if code.get("modo") != "totem":
        return None, None  # senza totem i dati del negozio non si raggiungono
    impostazioni = {i.tipo: i for i in ImpostazioniPlugin.objects.filter(attivo=True) if abilitato(i.tipo)}
    if not impostazioni:
        return None, None
    fonti = {f.tipo: f for f in FontePlugin.objects.filter(sede_id=monitor.sede_id, tipo__in=impostazioni)}
    player, servizio = {}, {}
    for tipo, i in impostazioni.items():
        fonte, sql = fonti.get(tipo), query_di(i)
        if fonte is None or not sql:
            continue
        voce = {"timeout": i.timeout, "aspetto": aspetto_pulito(i.aspetto)}
        if tipo == "ingredienti":
            voce.update({
                "prefissi": i.prefissi, "plu_inizio": i.plu_inizio, "plu_lunghezza": i.plu_lunghezza,
                "mostra_prezzo": i.mostra_prezzo and "prezzo" in impostazioni and "prezzo" in fonti,
            })
        player[tipo] = voce
        if "reparti" in code:
            condivisione, _, file = fonte.percorso.partition("\\")
            servizio[tipo] = {
                "condivisione": f"\\\\{fonte.indirizzo}\\{condivisione}", "file": file,
                "utente": fonte.utente, "password": decifra(fonte.password_cifrata),
                "minuti": fonte.aggiorna_minuti, "query": sql,
            }
    return player or None, servizio or None
