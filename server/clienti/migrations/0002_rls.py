from django.db import migrations

from core.rls import proteggi


class Migration(migrations.Migration):
    dependencies = [("clienti", "0001_initial")]

    operations = [
        proteggi("clienti_cliente", colonna="id"),
        proteggi("clienti_abilitazioni"),
        proteggi("clienti_sede"),
    ]
