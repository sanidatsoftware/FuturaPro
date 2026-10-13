from django.db import migrations

from core.rls import proteggi, tramite


class Migration(migrations.Migration):
    dependencies = [("utenti", "0001_initial")]

    operations = [
        proteggi("utenti_utente_sedi_consentite", condizione=tramite("clienti_sede", "sede_id")),
    ]
