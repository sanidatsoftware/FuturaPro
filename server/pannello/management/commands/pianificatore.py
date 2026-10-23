import time

from django.core.management.base import BaseCommand

from dispositivi.allarmi import controlla_tutti
from pannello.rapporti import controlla as controlla_rapporti
from plugin.filtro import controlla_dirette


class Command(BaseCommand):
    help = (
        "I lavori periodici, ogni minuto: allarmi degli schermi, rapporti per email e controllo delle dirette "
        "del Filtro contenuti (--una-volta per un giro solo)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--una-volta", action="store_true")

    def handle(self, *args, una_volta=False, **opzioni):
        while True:
            for nome, lavoro in (("allarmi", controlla_tutti), ("rapporti", controlla_rapporti), ("filtro", controlla_dirette)):
                try:
                    esito = lavoro()
                    if esito and (not isinstance(esito, dict) or any(esito.get(k) for k in ("scollegati", "tornati", "bloccate", "errore"))):
                        self.stdout.write(f"{nome}: {esito}")
                except Exception as errore:  # un errore passeggero non ferma il servizio
                    self.stderr.write(f"{nome}: {errore}")
            if una_volta:
                return
            time.sleep(60)
