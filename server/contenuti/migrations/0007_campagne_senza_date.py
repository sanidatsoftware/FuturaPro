from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contenuti", "0006_promozioni")]

    operations = [
        migrations.RemoveField(
            model_name="campagna",
            name="contenuti",
        ),
        migrations.AlterModelOptions(
            name="campagna",
            options={"ordering": ["nome"], "verbose_name_plural": "campagne"},
        ),
        migrations.RemoveField(
            model_name="campagna",
            name="data_fine",
        ),
        migrations.RemoveField(
            model_name="campagna",
            name="data_inizio",
        ),
        migrations.RemoveField(
            model_name="campagna",
            name="giorni",
        ),
        migrations.RemoveField(
            model_name="campagna",
            name="ora_fine",
        ),
        migrations.RemoveField(
            model_name="campagna",
            name="ora_inizio",
        ),
        migrations.RemoveField(
            model_name="pubblicazione",
            name="campagna",
        ),
        migrations.AlterField(
            model_name="campagna",
            name="codice",
            field=models.CharField(
                blank=True, help_text="Riferimento interno.", max_length=50
            ),
        ),
        migrations.DeleteModel(
            name="ContenutoCampagna",
        ),
    ]
