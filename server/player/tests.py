from django.test import TestCase


class PagineTest(TestCase):
    def test_player_e_anteprima(self):
        r = self.client.get("/player/")
        self.assertContains(r, 'data-modo="player"')
        self.assertContains(r, "player/avvio.js")
        r = self.client.get("/anteprima/00000000-0000-0000-0000-000000000001/")
        self.assertContains(r, 'data-modo="anteprima"')
        self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")
