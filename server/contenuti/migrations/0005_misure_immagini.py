"""Legge larghezza e altezza delle immagini già caricate, per riconoscere verticali e orizzontali."""

from django.db import migrations


def misura(apps, schema_editor):
    from contenuti.file import misure_immagine

    # Le tabelle hanno la Row-Level Security: la migrazione lavora come piattaforma.
    schema_editor.execute("SELECT set_config('app.piattaforma', 'on', true)")
    Contenuto = apps.get_model("contenuti", "Contenuto")
    for contenuto in Contenuto._base_manager.filter(tipo="immagine", larghezza__isnull=True).exclude(file=""):
        try:
            with contenuto.file.open("rb") as file:
                misure = misure_immagine(file)
        except OSError:
            continue
        if misure:
            contenuto.larghezza, contenuto.altezza = misure
            contenuto.save(update_fields=["larghezza", "altezza"])


class Migration(migrations.Migration):
    dependencies = [("contenuti", "0004_campagne_rls")]

    operations = [migrations.RunPython(misura, migrations.RunPython.noop)]
