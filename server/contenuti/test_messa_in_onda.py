import secrets

from core.contesto import contesto_cliente
from dispositivi.models import CredenzialeDispositivo, Monitor, impronta

from .models import Pubblicazione
from .test_campagne import immagine
from .tests import ConFile


class MessaInOndaTest(ConFile):
    def test_passaggi_riassunti_e_rapporti(self):
        self.come(self.admin_a)
        foto = self.client.post("/api/contenuti/", {"file": immagine(192, 108)}, format="multipart").json()["id"]
        campagna = self.client.post("/api/campagne/", {
            "nome": "Caffè autunno", "data_inizio": "2026-01-01", "data_fine": "2026-12-31", "fornitore": "Torrefazione Esempio",
            "monitor": [str(self.mon_a_milano.id)],
        }, format="json").json()
        promo = self.client.post("/api/promozioni/", {
            "campagna": campagna["id"], "nome": "Ottobre", "data_inizio": "2026-10-01", "data_fine": "2026-10-31", "contenuti": [foto],
        }, format="json").json()
        with contesto_cliente(self.a.id):
            playlist = str(Pubblicazione.objects.get(promozione_id=promo["id"]).playlist_id)
        token = secrets.token_urlsafe(32)
        with contesto_cliente(self.a.id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        passaggi = [
            {"contenuto": foto, "playlist": playlist, "inizio": "2026-10-14T10:00:00+02:00", "secondi": 10},
            {"contenuto": foto, "playlist": playlist, "inizio": "2026-10-14T10:01:00+02:00", "secondi": 10},
            {"contenuto": foto, "riserva": True, "inizio": "2026-10-14T23:00:00+02:00", "secondi": 30},
            {"contenuto": "non-un-id", "inizio": "2026-10-14T10:00:00+02:00", "secondi": 5},
        ]
        r = self.client.post("/api/player/passaggi/", {"passaggi": passaggi}, format="json", HTTP_AUTHORIZATION=f"Device {token}")
        self.assertEqual(r.json()["registrati"], 3)
        # Rimandati (es. dopo una caduta di rete) si sommano.
        self.client.post("/api/player/passaggi/", {"passaggi": passaggi[:1]}, format="json", HTTP_AUTHORIZATION=f"Device {token}")

        dati = self.client.get("/api/messa-in-onda/?dal=2026-10-01&al=2026-10-31&raggruppa=fornitore").json()
        fornitore = next(r for r in dati["righe"] if r["nome"] == "Torrefazione Esempio")
        self.assertEqual((fornitore["passaggi"], fornitore["secondi"], fornitore["schermi"]), (3, 30, 1))
        self.assertEqual(dati["totale"]["passaggi"], 4)
        self.assertIn("Torrefazione Esempio", dati["scelte"]["fornitori"])
        solo = self.client.get(f"/api/messa-in-onda/?dal=2026-10-01&al=2026-10-31&raggruppa=promozione&campagna={campagna['id']}").json()
        self.assertEqual([r["nome"] for r in solo["righe"]], ["Ottobre"])
        csv = self.client.get("/api/messa-in-onda/?dal=2026-10-01&al=2026-10-31&raggruppa=campagna&formato=csv").content.decode()
        self.assertIn("Caffè autunno;3;0,01", csv)
        # I nomi restano anche se la promozione viene cancellata.
        self.client.delete(f"/api/promozioni/{promo['id']}/")
        dopo = self.client.get("/api/messa-in-onda/?dal=2026-10-01&al=2026-10-31&raggruppa=promozione").json()
        self.assertIn("Ottobre", [r["nome"] for r in dopo["righe"]])
