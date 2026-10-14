from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.contesto import contesto_cliente
from dispositivi.models import Monitor

from . import dirette, palinsesto
from .test_campagne import immagine
from .tests import ConFile

LISTA = """#EXTM3U
#EXTINF:-1 tvg-id="uno.it" tvg-logo="https://esempio.it/uno.png" group-title="Generale",Canale Uno
https://flussi.esempio.it/uno/index.m3u8
#EXTINF:-1 tvg-logo="javascript:alert(1)" group-title="News",Canale Due
#EXTVLCOPT:http-user-agent=Qualcosa
https://flussi.esempio.it/due.m3u8
#EXTINF:-1,Doppione
https://flussi.esempio.it/uno/index.m3u8
#EXTINF:-1,Locale
rtmp://non-ammesso/flusso
"""


class LetturaM3uTest(SimpleTestCase):
    def test_canali_logo_e_gruppi(self):
        canali = dirette.leggi_m3u(LISTA)
        self.assertEqual([c["nome"] for c in canali], ["Canale Uno", "Canale Due"])
        self.assertEqual(canali[0]["logo"], "https://esempio.it/uno.png")
        self.assertEqual(canali[0]["gruppo"], "Generale")
        # Niente logo che non sia un indirizzo web, niente doppioni né protocolli strani.
        self.assertEqual(canali[1]["logo"], "")


class FlussoSingoloTest(SimpleTestCase):
    def test_riconosce_un_canale_hls(self):
        self.assertTrue(dirette.e_flusso_hls("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\nseg0.ts\n"))
        self.assertFalse(dirette.e_flusso_hls(LISTA))


class DiretteTest(ConFile):
    def test_serve_la_conferma_delle_autorizzazioni(self):
        self.come(self.admin_a)
        canale = {"nome": "Canale Uno", "url": "https://flussi.esempio.it/uno.m3u8"}
        r = self.client.post("/api/contenuti/dirette/", {"canali": [canale]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/contenuti/dirette/", {"canali": [canale], "autorizzazione": True}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        diretta = r.json()[0]
        self.assertEqual((diretta["tipo"], diretta["orientamento"], diretta["autorizzata_da"]), ("diretta", "orizzontale", "admin_a"))
        # Rimandandola non si duplica.
        r = self.client.post("/api/contenuti/dirette/", {"canali": [canale], "autorizzazione": True}, format="json")
        self.assertEqual(r.json()[0]["id"], diretta["id"])

    def test_lista_da_file(self):
        self.come(self.admin_a)
        r = self.client.post("/api/contenuti/m3u/", {"file": SimpleUploadedFile("tv.m3u", LISTA.encode())}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["canali"]), 2)
        r = self.client.post("/api/contenuti/m3u/", {"url": "http://127.0.0.1/lista.m3u"}, format="json")
        self.assertEqual(r.status_code, 400)  # niente reti interne

    def test_intermezzo_nella_promozione(self):
        self.come(self.admin_a)
        foto = super().carica(immagine(192, 108)).json()["id"]
        diretta = self.client.post("/api/contenuti/dirette/", {
            "canali": [{"nome": "Uno", "url": "https://flussi.esempio.it/uno.m3u8"}], "autorizzazione": True,
        }, format="json").json()[0]["id"]
        campagna = self.client.post("/api/campagne/", {
            "nome": "Con diretta", "data_inizio": "2026-01-01", "data_fine": "2026-12-31",
            "monitor": [str(self.mon_a_milano.id)], "durata": 8,
        }, format="json").json()
        r = self.client.post("/api/promozioni/", {
            "campagna": campagna["id"], "nome": "Intermezzo", "data_inizio": "2026-01-01", "data_fine": "2026-12-31",
            "contenuti": [foto, diretta], "durate": {diretta: 420},
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["durate"], {diretta: 420})
        with contesto_cliente(self.a.id):
            corpo = palinsesto.manifest(Monitor.objects.get(id=self.mon_a_milano.id))
        sequenza = next(iter(corpo["playlist"].values()))
        self.assertEqual([(e["contenuto"], e["durata"]) for e in sequenza], [(foto, 8), (diretta, 420)])
        self.assertEqual(corpo["contenuti"][diretta]["tipo"], "diretta")
        self.assertEqual(corpo["contenuti"][diretta]["url"], "https://flussi.esempio.it/uno.m3u8")
