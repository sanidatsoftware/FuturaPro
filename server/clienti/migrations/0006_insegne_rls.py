from django.db import migrations

from core.rls import proteggi


class Migration(migrations.Migration):
    dependencies = [("clienti", "0005_insegne")]

    operations = [proteggi("clienti_insegna")]
