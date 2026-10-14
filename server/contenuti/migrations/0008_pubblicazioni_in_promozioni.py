"""Le pubblicazioni fatte a mano diventano promozioni, ognuna nella sua campagna.

Da qui in avanti tutto si gestisce da «Creazione palinsesto»: la vecchia scheda
«Contenuti e pubblicazioni» non c'è più. Le pubblicazioni restano le stesse (il
player non vede differenze); cambia solo chi le possiede.
"""

from django.db import migrations


def converti(apps, schema_editor):
    # Le tabelle hanno la Row-Level Security: la migrazione lavora come piattaforma.
    schema_editor.execute("SELECT set_config('app.piattaforma', 'on', true)")
    Campagna = apps.get_model("contenuti", "Campagna")
    Promozione = apps.get_model("contenuti", "Promozione")
    ContenutoPromozione = apps.get_model("contenuti", "ContenutoPromozione")
    Pubblicazione = apps.get_model("contenuti", "Pubblicazione")
    Playlist = apps.get_model("contenuti", "Playlist")
    ElementoPlaylist = apps.get_model("contenuti", "ElementoPlaylist")
    Zona = apps.get_model("layout", "Zona")

    playlist_dei_layout = {
        str(c.get("sorgente")) for c in Zona._base_manager.filter(tipo="slide").values_list("configurazione", flat=True)
    }
    for pubblicazione in Pubblicazione._base_manager.filter(promozione__isnull=True).order_by("creata"):
        nomi = set(Campagna._base_manager.filter(cliente_id=pubblicazione.cliente_id).values_list("nome", flat=True))
        nome, n = pubblicazione.nome[:190], 2
        while nome in nomi:
            nome, n = f"{pubblicazione.nome[:190]} ({n})", n + 1
        campagna = Campagna._base_manager.create(
            cliente_id=pubblicazione.cliente_id, nome=nome, priorita=pubblicazione.priorita,
        )
        campagna.monitor.set(pubblicazione.monitor.all())
        campagna.gruppi.set(pubblicazione.gruppi.all())
        campagna.insegne.set(pubblicazione.insegne.all())
        promozione = Promozione._base_manager.create(
            cliente_id=pubblicazione.cliente_id, campagna=campagna, nome=pubblicazione.nome[:200],
            data_inizio=pubblicazione.data_inizio, data_fine=pubblicazione.data_fine,
            ora_inizio=pubblicazione.ora_inizio, ora_fine=pubblicazione.ora_fine, giorni=pubblicazione.giorni,
        )
        elementi = list(ElementoPlaylist._base_manager.filter(playlist_id=pubblicazione.playlist_id).order_by("ordine"))
        visti = set()
        for elemento in elementi:
            if elemento.contenuto_id in visti:
                continue
            visti.add(elemento.contenuto_id)
            ContenutoPromozione._base_manager.create(
                cliente_id=pubblicazione.cliente_id, promozione=promozione,
                contenuto_id=elemento.contenuto_id, ordine=len(visti) - 1,
            )
        # La promozione potrà rifare la sua playlist: se è condivisa (con un'altra
        # pubblicazione o con una zona slide), le si dà una copia tutta sua.
        condivisa = (
            str(pubblicazione.playlist_id) in playlist_dei_layout
            or Pubblicazione._base_manager.filter(playlist_id=pubblicazione.playlist_id).exclude(id=pubblicazione.id).exists()
        )
        if condivisa:
            originale = Playlist._base_manager.get(id=pubblicazione.playlist_id)
            copia = Playlist._base_manager.create(
                cliente_id=originale.cliente_id, nome=originale.nome, descrizione=originale.descrizione
            )
            for elemento in elementi:
                ElementoPlaylist._base_manager.create(
                    cliente_id=elemento.cliente_id, playlist=copia, contenuto_id=elemento.contenuto_id,
                    ordine=elemento.ordine, durata=elemento.durata,
                )
            pubblicazione.playlist_id = copia.id
        pubblicazione.promozione = promozione
        pubblicazione.save(update_fields=["promozione", "playlist"])


class Migration(migrations.Migration):
    dependencies = [("contenuti", "0007_campagne_senza_date"), ("layout", "0004_formato_immagini")]

    operations = [migrations.RunPython(converti, migrations.RunPython.noop)]
