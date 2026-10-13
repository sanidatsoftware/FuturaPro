from django.db import migrations

from core.rls import proteggi, tramite


class Migration(migrations.Migration):
    dependencies = [("dispositivi", "0001_initial")]

    operations = [
        proteggi("dispositivi_gruppomonitor"),
        proteggi("dispositivi_monitor"),
        proteggi("dispositivi_monitor_gruppi", condizione=tramite("dispositivi_monitor", "monitor_id")),
    ]
