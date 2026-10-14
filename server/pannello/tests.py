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
        r = self.client.patch("/api/piattaforma/aspetto/", {"nome_app": "Tocal Vision", "logo": png()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.client.logout()
        r = self.client.get("/api/sessione/login/")
        self.assertContains(r, "Tocal Vision")
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
