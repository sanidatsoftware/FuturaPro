from django.db import migrations

from core.rls import proteggi


class Migration(migrations.Migration):
    dependencies = [("teleassistenza", "0001_initial")]

    operations = [
        proteggi("teleassistenza_sessioneteleassistenza"),
    ]
