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

    def test_pagina_di_accesso_composta(self):
        import base64
        import json

        self.come(self.assoluto)
        composizione = {"logo": {"posizione": "al_centro", "altezza": 9999, "mostra_nome": False}, "allineamento": "centro",
                        "righe": [{"testo": "Benvenuti", "dimensione": 50, "peso": "grassetto", "colore": "#ff0000"},
                                  {"testo": "<script>x</script>", "dimensione": 18, "colore": "rosso"}]}
        r = self.client.patch("/api/piattaforma/aspetto/", {"accesso": composizione}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["accesso"]["logo"]["altezza"], 360)  # riportata nei limiti
        self.assertEqual(r.json()["sottotitolo"], "Benvenuti")  # la prima riga resta la frase
        # Anteprima dal vivo (non salva): i valori arrivano nell'indirizzo.
        prova = base64.urlsafe_b64encode(json.dumps({"righe": [{"testo": "Solo anteprima"}]}).encode()).decode().rstrip("=")
        self.assertContains(self.client.get(f"/accesso/?anteprima=1&prova={prova}"), "Solo anteprima")
        self.client.logout()
        pagina = self.client.get("/accesso/").content.decode()
        self.assertIn("font-size: 50px; color: #ff0000", pagina)
        self.assertIn("allinea-centro", pagina)
        self.assertNotIn("<script>x</script>", pagina)  # i testi passano dall'escape del template
        self.assertNotIn("Solo anteprima", pagina)
        # L'anteprima con valori non salvati è solo per chi è nel pannello di piattaforma.
        self.assertNotContains(self.client.get(f"/accesso/?anteprima=1&prova={prova}"), "Solo anteprima")

    def test_logo_fino_a_3_mb(self):
        from pannello.views import LOGO_MAX

        self.assertEqual(LOGO_MAX, 3 * 1024 * 1024)

    # L'icona (barra del pannello e scheda del browser) è distinta dal logo della pagina di accesso.
    def test_icona_ico_o_png(self):
        from PIL import Image

        self.come(self.assoluto)
        ico = io.BytesIO()
        Image.new("RGBA", (32, 32), (0, 120, 255, 255)).save(ico, "ICO")
        r = self.client.patch("/api/piattaforma/aspetto/", {"icona": SimpleUploadedFile("favicon.ico", ico.getvalue())}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ha_icona"])
        risposta = self.client.get("/aspetto/icona/")
        self.assertEqual(risposta["Content-Type"], "image/x-icon")
        pannello = self.client.get("/pannello/")
        self.assertContains(pannello, 'rel="icon" href="/aspetto/icona/')
        self.assertContains(pannello, 'class="icona" src="/aspetto/icona/')
        self.assertContains(self.client.get("/accesso/?anteprima=1"), 'rel="icon"')
        # Un PNG va bene; un testo spacciato per icona no.
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"icona": png()}, format="multipart").status_code, 200)
        svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"icona": SimpleUploadedFile("i.svg", svg)}, format="multipart").status_code, 200)
        risposta = self.client.get("/aspetto/icona/")
        self.assertEqual(risposta["Content-Type"], "image/svg+xml")
        self.assertIn("sandbox", risposta["Content-Security-Policy"])
        for cattivo in (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://altrove.it/x.png"/></svg>'):
            self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"icona": SimpleUploadedFile("c.svg", cattivo)}, format="multipart").status_code, 400)
        falso = SimpleUploadedFile("x.ico", b"<svg onload='alert(1)'/>")
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"icona": falso}, format="multipart").status_code, 400)
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"icona": None}, format="json").json()["ha_icona"], False)
        self.assertEqual(self.client.get("/aspetto/icona/").status_code, 404)

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


class LogoBarraTest(Base):
    def test_riquadro_del_logo_nella_barra_facoltativo(self):
        self.come(self.assoluto)
        self.assertNotContains(self.client.get("/pannello/"), "con-riquadro")
        self.client.patch("/api/piattaforma/aspetto/", {"accesso": {"logo": {"riquadro_barra": True}}}, format="json")
        self.assertContains(self.client.get("/pannello/"), "marchio con-riquadro")



class StiliAccessoTest(Base):
    """La pagina di accesso con gli stili «Oro»: titolo dorato, simbolo, sfondo animato, Powered by."""

    def test_stili(self):
        self.come(self.assoluto)
        r = self.client.patch("/api/piattaforma/aspetto/", {"accesso": {"stile": "oro_animato", "simbolo": "futurapro",
                                                                          "powered": {"mostra": True, "testo": "Powered by"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["accesso"]["stile"], "oro_animato")
        self.client.logout()
        pagina = self.client.get("/accesso/").content.decode()
        self.assertIn('class="vetrina oro oro_animato"', pagina)
        self.assertIn('class="sfondo"', pagina)
        self.assertIn('class="simbolo"', pagina)
        self.assertIn("Powered by", pagina)
        self.assertIn("cinzel-latin.woff2", pagina)
        self.come(self.assoluto)
        self.assertEqual(self.client.patch("/api/piattaforma/aspetto/", {"accesso": {"stile": "neon"}}, format="json").json()["accesso"]["stile"], "classico")
        self.client.logout()
        self.assertNotIn('class="sfondo"', self.client.get("/accesso/").content.decode())


class PanoramicaTest(Base):
    """La Panoramica: avvisi e riepiloghi dell'azienda; per la piattaforma tutte le aziende."""

    def test_azienda_e_piattaforma(self):
        from datetime import timedelta

        from django.utils import timezone

        from clienti.models import Abilitazioni
        from core.contesto import contesto_cliente
        from eliminacode.models import Biglietto, Reparto

        adesso = timezone.now()
        with contesto_cliente(self.a.id):
            reparto = Reparto.objects.create(cliente=self.a, sede=self.a_milano, nome="Salumeria")
            Biglietto.objects.create(cliente=self.a, reparto=reparto, giornata=timezone.localdate(), progressivo=1, numero=1,
                                     emesso_il=adesso - timedelta(minutes=10), chiamato_il=adesso - timedelta(minutes=4))
            Biglietto.objects.create(cliente=self.a, reparto=reparto, giornata=timezone.localdate(), progressivo=2, numero=2, emesso_il=adesso)
            Abilitazioni.objects.update(spazio_mb=1)
        self.come(self.admin_a)
        d = self.client.get("/api/panoramica/").json()
        self.assertEqual(d["schermi"]["totale"], 2)
        self.assertTrue(any("non è in linea" in a["testo"] or "non in linea" in a["testo"] for a in d["avvisi"]))
        self.assertEqual(d["code"], [{"reparto": "Salumeria", "sede": "Milano", "colore": reparto.colore, "emessi": 2, "chiamati": 1, "in_coda": 1, "attesa_media": 6.0}])
        self.assertIn("registro", d)
        # Lo User limitato a Milano non vede Roma né il registro.
        self.come(self.user_a_milano)
        d = self.client.get("/api/panoramica/").json()
        self.assertEqual((d["schermi"]["totale"], d["registro"]), (1, []))
        self.assertEqual(self.client.get("/api/piattaforma/panoramica/").status_code, 403)
        self.come(self.assoluto)
        g = self.client.get("/api/piattaforma/panoramica/").json()
        self.assertEqual(g["totali"]["aziende"], 2)
        self.assertEqual(g["totali"]["biglietti"], 2)
