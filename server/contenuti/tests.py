import secrets
import shutil
import tempfile
from datetime import date, datetime, time
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from clienti.models import Abilitazioni
from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base
from dispositivi.models import CredenzialeDispositivo, GruppoMonitor, impronta

from . import palinsesto
from .models import Contenuto

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64


def png(nome="logo.png"):
    return SimpleUploadedFile(nome, PNG, content_type="image/png")


def regola(**campi):
    base = dict(attiva=True, data_inizio=None, data_fine=None, ora_inizio=None, ora_fine=None,
                giorni=[], priorita=0, creata=datetime(2026, 1, 1))
    return SimpleNamespace(**{**base, **campi})


class RegoleTest(SimpleTestCase):
    """Le regole del palinsesto: le stesse che applicherà il player."""

    lunedi_9 = datetime(2026, 10, 12, 9, 0)

    def test_fascia_oraria(self):
        self.assertTrue(palinsesto.valida(regola(ora_inizio=time(8), ora_fine=time(12)), self.lunedi_9))
        self.assertFalse(palinsesto.valida(regola(ora_inizio=time(9, 1), ora_fine=time(12)), self.lunedi_9))
        # La fine è esclusa.
        self.assertFalse(palinsesto.valida(regola(ora_inizio=time(8), ora_fine=time(9)), self.lunedi_9))

    def test_fascia_che_scavalca_la_mezzanotte(self):
        notte = regola(ora_inizio=time(22), ora_fine=time(6))
        self.assertTrue(palinsesto.valida(notte, datetime(2026, 10, 12, 23, 30)))
        self.assertTrue(palinsesto.valida(notte, datetime(2026, 10, 13, 5, 59)))
        self.assertFalse(palinsesto.valida(notte, self.lunedi_9))

    def test_giorni_e_date(self):
        self.assertTrue(palinsesto.valida(regola(giorni=[0, 2]), self.lunedi_9))
        self.assertFalse(palinsesto.valida(regola(giorni=[5, 6]), self.lunedi_9))
        self.assertTrue(palinsesto.valida(regola(data_inizio=date(2026, 10, 12), data_fine=date(2026, 10, 12)), self.lunedi_9))
        self.assertFalse(palinsesto.valida(regola(data_fine=date(2026, 10, 11)), self.lunedi_9))
        self.assertFalse(palinsesto.valida(regola(attiva=False), self.lunedi_9))

    def test_vince_la_priorita_poi_si_accoda(self):
        prima = regola(nome="prima", creata=datetime(2026, 1, 1))
        seconda = regola(nome="seconda", creata=datetime(2026, 2, 1))
        urgente = regola(nome="urgente", priorita=10, ora_inizio=time(8), ora_fine=time(10))
        self.assertEqual([p.nome for p in palinsesto.in_onda([seconda, prima], self.lunedi_9)], ["prima", "seconda"])
        self.assertEqual([p.nome for p in palinsesto.in_onda([prima, urgente], self.lunedi_9)], ["urgente"])
        self.assertEqual([p.nome for p in palinsesto.in_onda([prima, urgente], datetime(2026, 10, 12, 11))], ["prima"])


class ConFile(Base):
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

    def carica(self, file=None, **campi):
        return self.client.post("/api/contenuti/", {"file": file or png(), **campi}, format="multipart")


class LibreriaTest(ConFile):
    def test_caricamento_riconosce_il_formato_dal_contenuto(self):
        self.come(self.admin_a)
        r = self.carica(SimpleUploadedFile("finto.jpg", MP4, content_type="image/jpeg"), durata=30)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["tipo"], r.json()["mime"]), ("video", "video/mp4"))
        with contesto_cliente(self.a.id):
            contenuto = Contenuto.objects.get(id=r.json()["id"])
        self.assertTrue(contenuto.file.name.startswith(f"clienti/{self.a.id}/"))

    def test_rifiuta_file_non_supportati(self):
        self.come(self.admin_a)
        r = self.carica(SimpleUploadedFile("virus.png", b"MZ\x90\x00 eseguibile", content_type="image/png"))
        self.assertEqual(r.status_code, 400)

    def test_pagina_web_richiede_la_durata(self):
        self.come(self.admin_a)
        self.assertEqual(self.client.post("/api/contenuti/", {"url": "https://example.com"}).status_code, 400)
        r = self.client.post("/api/contenuti/", {"url": "https://example.com", "durata": 20})
        self.assertEqual((r.status_code, r.json()["tipo"]), (201, "web"))

    def test_rispetta_lo_spazio_concesso(self):
        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(spazio_mb=0)
        self.come(self.admin_a)
        self.assertEqual(self.carica().status_code, 400)

    def test_lo_user_cliente_carica_il_tecnico_no(self):
        self.come(self.user_a)
        self.assertEqual(self.carica().status_code, 201)
        self.come(self.tecnico, cliente=self.a)
        self.assertEqual(self.carica().status_code, 403)

    def test_contenuti_e_file_degli_altri_risultano_inesistenti(self):
        self.come(self.admin_a)
        id_a = self.carica().json()["id"]
        self.assertEqual(self.client.get(f"/api/contenuti/{id_a}/file/").status_code, 200)
        self.come(self.admin_b)
        self.assertEqual(self.client.get(f"/api/contenuti/{id_a}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/contenuti/{id_a}/file/").status_code, 404)
        r = self.client.post("/api/playlist/", {"nome": "furba", "elementi": [{"contenuto": id_a}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_playlist_mantiene_l_ordine(self):
        self.come(self.admin_a)
        primo, secondo = self.carica().json()["id"], self.carica().json()["id"]
        r = self.client.post(
            "/api/playlist/",
            {"nome": "Vetrina", "elementi": [{"contenuto": secondo, "durata": 5}, {"contenuto": primo}]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        id_playlist = r.json()["id"]
        self.assertEqual([e["contenuto"] for e in r.json()["elementi"]], [secondo, primo])
        r = self.client.patch(f"/api/playlist/{id_playlist}/", {"elementi": [{"contenuto": primo}]}, format="json")
        self.assertEqual([e["contenuto"] for e in r.json()["elementi"]], [primo])


class PubblicaTest(ConFile):
    def pubblica(self, **dati):
        return self.client.post("/api/pubblica/", dati, format="json")

    def player(self, monitor):
        token = secrets.token_urlsafe(32)
        with contesto_cliente(monitor.cliente_id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=monitor, cliente_id=monitor.cliente_id)
        return {"HTTP_AUTHORIZATION": f"Device {token}"}

    def test_dal_caricamento_al_player(self):
        self.come(self.admin_a)
        contenuto = self.carica(durata=8).json()["id"]
        r = self.pubblica(contenuti=[contenuto], monitor=[str(self.mon_a_milano.id)])
        self.assertEqual(r.status_code, 201, r.content)

        anteprima = self.client.get(f"/api/anteprima/{self.mon_a_milano.id}/").json()["sequenza"]
        self.assertEqual([(e["contenuto"], e["durata"]) for e in anteprima], [(contenuto, 8)])
        self.assertEqual(self.client.get(f"/api/anteprima/{self.mon_a_roma.id}/").json()["sequenza"], [])

        self.client.logout()
        dispositivo = self.player(self.mon_a_milano)
        r = self.client.get("/api/player/palinsesto/", **dispositivo)
        self.assertEqual(r.status_code, 200)
        manifest = r.json()
        self.assertEqual(manifest["fuso_orario"], "Europe/Rome")
        self.assertEqual(list(manifest["contenuti"]), [contenuto])
        voce = manifest["contenuti"][contenuto]
        self.assertEqual(voce["sha256"], __import__("hashlib").sha256(PNG).hexdigest())

        self.assertEqual(self.client.get("/api/player/palinsesto/", HTTP_IF_NONE_MATCH=r["ETag"], **dispositivo).status_code, 304)
        file = self.client.get(voce["url"], **dispositivo)
        self.assertEqual(b"".join(file.streaming_content), PNG)

    def test_il_player_scarica_solo_cio_che_e_pubblicato_su_di_lui(self):
        self.come(self.admin_a)
        contenuto = self.carica().json()["id"]
        self.pubblica(contenuti=[contenuto], monitor=[str(self.mon_a_milano.id)])
        self.client.logout()
        url = f"/api/player/file/{contenuto}/"
        self.assertEqual(self.client.get(url, **self.player(self.mon_a_roma)).status_code, 404)
        self.assertEqual(self.client.get(url, **self.player(self.mon_b)).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_pubblicazione_su_gruppo(self):
        with contesto_cliente(self.a.id):
            gruppo = GruppoMonitor.objects.create(nome="Tutti")
            gruppo.monitor.add(self.mon_a_milano, self.mon_a_roma)
        self.come(self.admin_a)
        contenuto = self.carica().json()["id"]
        self.assertEqual(self.pubblica(contenuti=[contenuto], gruppi=[str(gruppo.id)]).status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/anteprima/{self.mon_a_roma.id}/").json()["sequenza"]), 1)

    def test_non_pubblica_sui_monitor_degli_altri(self):
        self.come(self.admin_a)
        contenuto = self.carica().json()["id"]
        self.assertEqual(self.pubblica(contenuti=[contenuto], monitor=[str(self.mon_b.id)]).status_code, 400)

    def test_utente_limitato_pubblica_solo_nelle_sue_sedi(self):
        self.come(self.user_a_milano)
        contenuto = self.carica().json()["id"]
        self.assertEqual(self.pubblica(contenuti=[contenuto], monitor=[str(self.mon_a_roma.id)]).status_code, 400)
        with contesto_cliente(self.a.id):
            gruppo = GruppoMonitor.objects.create(nome="Milano")
        self.assertEqual(self.pubblica(contenuti=[contenuto], gruppi=[str(gruppo.id)]).status_code, 403)
        self.assertEqual(self.pubblica(contenuti=[contenuto], monitor=[str(self.mon_a_milano.id)]).status_code, 201)

    def test_utente_limitato_non_vede_le_pubblicazioni_delle_altre_sedi(self):
        self.come(self.admin_a)
        contenuto = self.carica().json()["id"]
        roma = self.pubblica(contenuti=[contenuto], monitor=[str(self.mon_a_roma.id)]).json()["id"]
        self.come(self.user_a_milano)
        self.assertEqual(self.client.get(f"/api/pubblicazioni/{roma}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/anteprima/{self.mon_a_roma.id}/").status_code, 404)

    def test_regole_non_valide(self):
        self.come(self.admin_a)
        contenuto = self.carica().json()["id"]
        monitor = [str(self.mon_a_milano.id)]
        self.assertEqual(self.pubblica(contenuti=[contenuto]).status_code, 400)
        self.assertEqual(
            self.pubblica(contenuti=[contenuto], monitor=monitor, data_inizio="2026-10-10", data_fine="2026-10-01").status_code,
            400,
        )
        self.assertEqual(self.pubblica(contenuti=[contenuto], monitor=monitor, giorni=[7]).status_code, 400)


class RipetiDiretteTest(ConFile):
    """Una diretta in una promozione: al suo posto, ogni N immagini, ogni N minuti o a certe ore."""

    def test_regole_della_diretta(self):
        from datetime import date as giorno, timedelta as intervallo

        from django.utils import timezone

        from . import campagne
        from .models import Campagna, Contenuto, Promozione

        self.come(self.admin_a)
        immagini = [self.carica(durata=10).json()["id"] for _ in range(5)]
        with contesto_cliente(self.a.id):
            diretta = Contenuto.objects.create(cliente=self.a, nome="Rai 1", tipo="diretta", url="https://esempio.it/live.m3u8", durata=300)
            campagna = Campagna.objects.create(cliente=self.a, nome="Prova", durata=10)
            campagna.monitor.add(self.mon_a_milano)
        oggi = timezone.localdate()
        base = {"campagna": str(campagna.id), "nome": "Promo", "data_inizio": oggi.isoformat(), "data_fine": (oggi + intervallo(days=3)).isoformat(),
                "contenuti": [str(diretta.id), *immagini]}

        # Ogni 2 immagini (e non più al suo posto in testa).
        r = self.client.post("/api/promozioni/", {**base, "ripeti": {str(diretta.id): {"modo": "ogni_slide", "ogni": 2}}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        promo = r.json()
        self.assertEqual(promo["ripeti"], {str(diretta.id): {"modo": "ogni_slide", "ogni": 2}})
        with contesto_cliente(self.a.id):
            playlist = Promozione.objects.get(id=promo["id"]).pubblicazioni.get().playlist
            sequenza = [str(e.contenuto_id) for e in playlist.elementi.order_by("ordine")]
        d = str(diretta.id)
        self.assertEqual(sequenza, [immagini[0], immagini[1], d, immagini[2], immagini[3], d, immagini[4]])

        # Ogni minuto: 10 s per immagine, la sequenza è più corta → una volta, in fondo.
        r = self.client.patch(f"/api/promozioni/{promo['id']}/", {"ripeti": {d: {"modo": "ogni_minuti", "ogni": 1}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        with contesto_cliente(self.a.id):
            self.assertEqual([str(e.contenuto_id) for e in playlist.elementi.order_by("ordine")], [*immagini, d])

        # A orari: fuori dalla sequenza, nel manifest come interruzione.
        r = self.client.patch(f"/api/promozioni/{promo['id']}/", {"ripeti": {d: {"modo": "orari", "orari": ["23:59", "00:00"]}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        with contesto_cliente(self.a.id):
            self.assertNotIn(d, [str(e.contenuto_id) for e in playlist.elementi.all()])
            pubblicazioni = list(Promozione.objects.get(id=promo["id"]).pubblicazioni.all())
            eventi, contenuti = __import__("contenuti.palinsesto", fromlist=["x"]).dirette_a_orari(pubblicazioni)
        self.assertIn(d, contenuti)
        self.assertTrue(eventi and all(e["contenuto"] == d and e["playlist"] == str(playlist.id) for e in eventi))
        self.assertTrue(any(e["inizio"].startswith((oggi + intervallo(days=1)).isoformat() + "T00:00") for e in eventi))

        # Regole non valide.
        for regola in ({"modo": "ogni_slide", "ogni": 0}, {"modo": "orari", "orari": ["25:00"]}, {"modo": "boh"}):
            self.assertEqual(self.client.patch(f"/api/promozioni/{promo['id']}/", {"ripeti": {d: regola}}, format="json").status_code, 400)
        # Le immagini non si ripetono: la regola vale solo per le dirette.
        self.client.patch(f"/api/promozioni/{promo['id']}/", {"ripeti": {immagini[0]: {"modo": "ogni_slide", "ogni": 1}}}, format="json")
        self.assertEqual(self.client.get(f"/api/promozioni/{promo['id']}/").json()["ripeti"], {})
