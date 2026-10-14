import time

from django.core.management.base import BaseCommand

from dispositivi.allarmi import controlla_tutti
from pannello.rapporti import controlla as controlla_rapporti


class Command(BaseCommand):
    help = "I lavori periodici: allarmi degli schermi e rapporti per email, ogni minuto (--una-volta per un giro solo)."

    def add_arguments(self, parser):
        parser.add_argument("--una-volta", action="store_true")

    def handle(self, *args, una_volta=False, **opzioni):
        while True:
            for nome, lavoro in (("allarmi", controlla_tutti), ("rapporti", controlla_rapporti)):
                try:
                    esito = lavoro()
                    if esito and (not isinstance(esito, dict) or esito.get("scollegati") or esito.get("tornati")):
                        self.stdout.write(f"{nome}: {esito}")
                except Exception as errore:  # un errore passeggero non ferma il servizio
                    self.stderr.write(f"{nome}: {errore}")
            if una_volta:
                return
            time.sleep(60)
