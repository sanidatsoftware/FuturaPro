import fcntl

from django.core.management.base import BaseCommand

from primanota.models import Condivisione
from primanota.services.importazione import (
    archivio_dir, esegui_pianificazione, importa_condivisione, importa_tutte, rielabora_archivio)


class Command(BaseCommand):
    help = "Preleva e archivia i SysSpy nuovi o modificati dalle condivisioni dei negozi."

    def add_arguments(self, parser):
        parser.add_argument("--negozio", help="Solo questo codice negozio")
        parser.add_argument("--completa", action="store_true", help="Rilegge anche i file già archiviati")
        parser.add_argument("--rielabora", action="store_true",
                            help="Rilegge i file già archiviati (senza condivisioni) con le regole attuali")
        parser.add_argument("--pianificato", action="store_true",
                            help="Per il crontab: lavora solo agli orari decisi nel portale (Condivisioni negozi)")

    def handle(self, *args, **opzioni):
        if opzioni["rielabora"]:
            negozio_id = None
            if opzioni["negozio"]:
                cond = Condivisione.objects.filter(codice_negozio=opzioni["negozio"]).first()
                negozio_id = cond.negozio_id if cond else -1
            esito = rielabora_archivio(negozio_id, scrivi=self.stdout.write)
            self.stdout.write(f"Rielaborati {esito['file']} file, {esito['errori']} errori")
            return
        if opzioni["pianificato"]:
            archivio_dir().mkdir(parents=True, exist_ok=True)
            # Se l'esecuzione precedente è ancora in corso, questa non parte.
            with open(archivio_dir() / ".pianificazione.lock", "w") as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return
                esito = esegui_pianificazione(scrivi=self.stdout.write)
                if esito != "niente da fare":
                    self.stdout.write(esito)
            return
        if opzioni["negozio"]:
            for cond in Condivisione.objects.filter(attiva=True, codice_negozio=opzioni["negozio"]).exclude(percorso=""):
                importa_condivisione(cond, completa=opzioni["completa"])
                self.stdout.write(f"{cond.codice_negozio}: {cond.ultimo_esito}")
            return
        stato = importa_tutte(completa=opzioni["completa"], scrivi=self.stdout.write)
        self.stdout.write(stato["messaggio"])
