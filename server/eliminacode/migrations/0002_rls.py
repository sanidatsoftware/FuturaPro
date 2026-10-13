from django.db import migrations

from core.rls import proteggi


class Migration(migrations.Migration):
    dependencies = [("eliminacode", "0001_initial")]

    operations = [proteggi("eliminacode_reparto")]
