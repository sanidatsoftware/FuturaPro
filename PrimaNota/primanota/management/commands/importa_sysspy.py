from django.core.management.base import BaseCommand

from primanota.models import Condivisione
from primanota.services.importazione import importa_condivisione


class Command(BaseCommand):
    help = "Preleva e archivia i SysSpy nuovi o modificati dalle condivisioni dei negozi (da cron, la sera)."

    def add_arguments(self, parser):
        parser.add_argument("--negozio", help="Solo questo codice negozio")
        parser.add_argument("--completa", action="store_true", help="Rilegge anche i file già archiviati")

    def handle(self, *args, **opzioni):
        condivisioni = Condivisione.objects.filter(attiva=True).exclude(percorso="")
        if opzioni["negozio"]:
            condivisioni = condivisioni.filter(codice_negozio=opzioni["negozio"])
        for cond in condivisioni:
            stato = importa_condivisione(cond, completa=opzioni["completa"])
            self.stdout.write(f"{cond.codice_negozio}: {cond.ultimo_esito}")
            if stato["stato"] == "errore":
                self.stderr.write(f"{cond.codice_negozio}: {stato['messaggio']}")
