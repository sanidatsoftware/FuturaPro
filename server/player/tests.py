from django.test import TestCase


class PagineTest(TestCase):
    def test_player_e_anteprima(self):
        r = self.client.get("/player/")
        self.assertContains(r, 'data-modo="player"')
        self.assertContains(r, "player/avvio.js")
        r = self.client.get("/anteprima/00000000-0000-0000-0000-000000000001/")
        self.assertContains(r, 'data-modo="anteprima"')
        self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")

    def test_editor_e_banco(self):
        self.assertContains(self.client.get("/editor/"), "layout/editor.js")
        r = self.client.get("/editor/00000000-0000-0000-0000-000000000001/")
        self.assertContains(r, 'data-layout="00000000-0000-0000-0000-000000000001"')
        self.assertContains(self.client.get("/banco/"), "eliminacode/banco.js")

    def test_pannello_chiede_l_accesso(self):
        r = self.client.get("/pannello/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/accesso/"))
        self.assertEqual(self.client.get("/")["Location"], "/pannello/")

    def test_service_worker(self):
        r = self.client.get("/player/sw.js")
        self.assertEqual(r["Content-Type"], "text/javascript; charset=utf-8")
        self.assertContains(r, "futurapro-app-")
