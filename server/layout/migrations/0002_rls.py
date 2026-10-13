from django.db import migrations

from core.rls import proteggi


class Migration(migrations.Migration):
    dependencies = [("layout", "0001_initial")]

    operations = [
        proteggi("layout_layout"),
        proteggi("layout_zona"),
    ]
