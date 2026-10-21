from django.db import migrations

# Le due banche indicate dalla sede, già pronte; restano modificabili da Impostazioni › Raggruppamenti Banche.
BANCHE = {
    "UNICREDIT": {5: ["UC Mastercard", "UC Visa", "AMERICAN EXPRESS", "Maestro"], 4: ["BANCOMAT"]},
    "BANCA BPM": {5: ["AMEX", "CREDITO"], 4: ["Debito"]},
}


def crea(apps, schema_editor):
    Istituto = apps.get_model("primanota", "IstitutoCredito")
    Tipologia = apps.get_model("primanota", "TipologiaPos")
    for nome, causali in BANCHE.items():
        istituto, nuovo = Istituto.objects.get_or_create(nome=nome)
        if not nuovo:
            continue   # già configurata a mano: non si tocca
        for causale, tipologie in causali.items():
            for descrizione in tipologie:
                Tipologia.objects.create(istituto=istituto, causale=causale, descrizione=descrizione)


class Migration(migrations.Migration):
    dependencies = [("primanota", "0016_raggruppamenti_banche")]
    operations = [migrations.RunPython(crea, migrations.RunPython.noop)]
