from django.db import migrations

from core.rls import proteggi, tramite


class Migration(migrations.Migration):
    dependencies = [("contenuti", "0001_initial")]

    operations = [
        proteggi("contenuti_contenuto"),
        proteggi("contenuti_playlist"),
        proteggi("contenuti_elementoplaylist"),
        proteggi("contenuti_pubblicazione"),
        proteggi("contenuti_pubblicazione_monitor", condizione=tramite("contenuti_pubblicazione", "pubblicazione_id")),
        proteggi("contenuti_pubblicazione_gruppi", condizione=tramite("contenuti_pubblicazione", "pubblicazione_id")),
    ]
