import shutil
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from clienti.models import Cliente
from contenuti.models import Contenuto
from core.contesto import contesto_cliente, contesto_piattaforma


class DatiDimostrativiTest(TestCase):
    def test_crea_il_cliente_demo_con_i_file_nella_sua_cartella(self):
        cartella = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cartella, ignore_errors=True)
        with override_settings(MEDIA_ROOT=cartella):
            call_command("dati_dimostrativi", password="Una-password-lunga-123", stdout=open("/dev/null", "w"))
        with contesto_piattaforma():
            cliente = Cliente.objects.get(nome="Demo")
        with contesto_cliente(cliente.id):
            percorsi = [c.file.name for c in Contenuto.objects.all()]
        self.assertTrue(percorsi)
        self.assertTrue(all(p.startswith(f"clienti/{cliente.id}/") for p in percorsi), percorsi)
