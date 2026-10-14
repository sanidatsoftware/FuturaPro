from django.db import migrations

from core.rls import proteggi, tramite


class Migration(migrations.Migration):
    dependencies = [("contenuti", "0003_campagne")]

    operations = [
        proteggi("contenuti_campagna"),
        proteggi("contenuti_contenutocampagna"),
        proteggi("contenuti_campagna_insegne", condizione=tramite("contenuti_campagna", "campagna_id")),
        proteggi("contenuti_campagna_gruppi", condizione=tramite("contenuti_campagna", "campagna_id")),
        proteggi("contenuti_campagna_monitor", condizione=tramite("contenuti_campagna", "campagna_id")),
        proteggi("contenuti_pubblicazione_insegne", condizione=tramite("contenuti_pubblicazione", "pubblicazione_id")),
    ]
