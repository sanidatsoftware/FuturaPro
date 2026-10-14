import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from core.tests.test_isolamento import Base


def png():
    uscita = io.BytesIO()
    Image.new("RGBA", (40, 20), (255, 0, 0, 128)).save(uscita, "PNG")
    return SimpleUploadedFile("marchio.png", uscita.getvalue(), content_type="image/png")


class AspettoTest(Base):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.mkdtemp()
        cls._media = override_settings(MEDIA_ROOT=cls.media)
        cls._media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media.disable()
        shutil.rmtree(cls.media, ignore_errors=True)

    def test_pagina_di_accesso_con_nome_e_logo(self):
        r = self.client.get("/accesso/")
        self.assertContains(r, "FuturaPro")
        self.assertNotContains(r, "Django REST framework")
        self.come(self.assoluto)
        r = self.client.patch("/api/piattaforma/aspetto/", {"nome_app": "Insegna Vision", "logo": png()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.client.logout()
        r = self.client.get("/api/sessione/login/")
        self.assertContains(r, "Insegna Vision")
        self.assertContains(r, "/aspetto/logo/")
        self.assertEqual(self.client.get("/aspetto/logo/").status_code, 200)

    def test_solo_l_administrator_assoluto_cambia_l_aspetto(self):
        self.come(self.admin_a)
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"nome_app": "X"}, format="json").status_code, 403)
        self.come(self.tecnico)
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"nome_app": "X"}, format="json").status_code, 403)

    def test_il_logo_deve_essere_un_immagine(self):
        self.come(self.assoluto)
        svg = SimpleUploadedFile("x.svg", b"<svg onload='alert(1)'/>", content_type="image/svg+xml")
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"logo": svg}, format="multipart").status_code, 400)

    def test_accesso_porta_al_pannello(self):
        r = self.client.post("/accesso/", {"username": "admin_a", "password": "sbagliata"})
        self.assertContains(r, "non corretti")
        self.assertRedirects(self.client.get("/pannello/"), "/accesso/?next=/pannello/", fetch_redirect_response=False)


class TemaTest(Base):
    def test_il_tema_si_sceglie_e_arriva_alle_pagine(self):
        self.come(self.user_a)
        self.assertEqual(self.client.get("/api/io/").json()["tema"], "auto")
        self.assertEqual(self.client.patch("/api/io/", {"tema": "viola"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch("/api/io/", {"tema": "scuro"}, format="json").json()["tema"], "scuro")
        for pagina in ("/pannello/", "/palinsesto/", "/editor/"):
            self.assertContains(self.client.get(pagina), 'data-tema="scuro"')


class EmailAziendaTest(Base):
    """Ogni azienda ha il suo server di posta; i destinatari li sceglie ogni funzione."""

    def test_server_per_azienda_rapporti_e_prova(self):
        from datetime import datetime

        from django.core import mail
        from django.test import override_settings
        from django.utils import timezone

        from core.contesto import contesto_cliente
        from pannello.models import ImpostazioniEmail
        from pannello.rapporti import controlla, periodo

        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_HOST=""):
            self.come(self.admin_a)
            r = self.client.put("/api/email/", {"attivo": True, "host": "smtp.azienda-a.it", "porta": 587, "utente": "avvisi@azienda-a.it", "password": "segreta", "mittente": "A <avvisi@azienda-a.it>"}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertNotIn("password", r.json())
            self.assertTrue(r.json()["password_impostata"])
            with contesto_cliente(self.a.id):
                self.assertNotIn("segreta", ImpostazioniEmail.objects.get().password_cifrata)
            self.assertEqual(self.client.post("/api/email/", {"a": "io@azienda-a.it"}, format="json").status_code, 200)
            self.assertEqual(mail.outbox[-1].from_email, "A <avvisi@azienda-a.it>")
            # Un'altra azienda non lo vede e non lo usa.
            self.come(self.admin_b)
            self.assertEqual(self.client.get("/api/email/").json()["host"], "")
            self.assertEqual(self.client.post("/api/email/", {"a": "x@b.it"}, format="json").status_code, 400)
            # Un rapporto settimanale con i suoi destinatari.
            self.come(self.admin_a)
            r = self.client.post("/api/invii-rapporti/", {"tipo": "schermi", "nome": "Schermi della settimana", "email": ["tecnico@azienda-a.it"], "frequenza": "settimanale"}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            lunedi_mattina = timezone.make_aware(datetime(2026, 10, 19, 8, 0))
            prima = len(mail.outbox)
            self.assertEqual(controlla(lunedi_mattina), 1)
            self.assertEqual(controlla(lunedi_mattina), 0)  # una volta per periodo
            self.assertEqual(len(mail.outbox), prima + 1)
            messaggio = mail.outbox[-1]
            self.assertEqual(messaggio.to, ["tecnico@azienda-a.it"])
            self.assertEqual(messaggio.attachments[0][0], "schermi-2026-10-12-2026-10-18.csv")
            self.assertEqual(periodo("mensile", datetime(2026, 11, 1).date())[1:], (datetime(2026, 10, 1).date(), datetime(2026, 10, 31).date()))
            # «Invia adesso» e i permessi: lo user non crea invii.
            self.assertEqual(self.client.post(f"/api/invii-rapporti/{r.json()['id']}/invia/").status_code, 200)
            self.come(self.user_a)
            self.assertEqual(self.client.post("/api/invii-rapporti/", {"tipo": "attese", "nome": "x", "email": ["a@b.it"]}, format="json").status_code, 403)
