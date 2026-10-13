import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError

from utenti.models import Ruolo, Utente


class Command(BaseCommand):
    help = "Crea un Administrator Assoluto (il primo serve per entrare nel pannello)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--email", default="")

    def handle(self, username, email, **opzioni):
        if Utente.objects.filter(username=username).exists():
            raise CommandError(f"L'utente {username} esiste già.")
        # Per le installazioni senza domande: la password arriva dall'ambiente, mai dalla riga di comando.
        password = os.environ.get("FUTURAPRO_ADMIN_PASSWORD")
        if not password:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Ripeti la password: "):
                raise CommandError("Le password non coincidono.")
        validate_password(password)
        utente = Utente(username=username, email=email, ruolo=Ruolo.ADMIN_ASSOLUTO)
        utente.set_password(password)
        utente.save()
        self.stdout.write(self.style.SUCCESS(f"Administrator Assoluto {username} creato."))
