import time

from django.core.management.base import BaseCommand

from dispositivi.allarmi import controlla_tutti


class Command(BaseCommand):
    help = "Controlla gli schermi scollegati e manda le email di allarme. Con --ciclo, ogni minuto."

    def add_arguments(self, parser):
        parser.add_argument("--ciclo", action="store_true", help="Ripete il controllo ogni 60 secondi (servizio pianificatore).")

    def handle(self, *args, ciclo=False, **opzioni):
        while True:
            try:
                esito = controlla_tutti()
                if esito["scollegati"] or esito["tornati"]:
                    self.stdout.write(f"allarmi: {esito}")
            except Exception as errore:  # il servizio non deve fermarsi per un errore passeggero
                self.stderr.write(f"controllo schermi: {errore}")
            if not ciclo:
                return
            time.sleep(60)
