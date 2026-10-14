import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from clienti.models import Insegna
from core.contesto import contesto_cliente
from dispositivi.models import GruppoMonitor, Monitor

from . import palinsesto
from .tests import ConFile


def immagine(larghezza, altezza, nome="volantino.jpg"):
    uscita = io.BytesIO()
    Image.new("RGB", (larghezza, altezza), "orange").save(uscita, "JPEG")
    return SimpleUploadedFile(nome, uscita.getvalue(), content_type="image/jpeg")


class CampagneTest(ConFile):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with contesto_cliente(cls.a.id):
            cls.tocal = Insegna.objects.create(cliente=cls.a, nome="Tocal")
            cls.a_milano.insegna = cls.tocal
            cls.a_milano.save()
            cls.totem_milano = Monitor.objects.create(
                cliente=cls.a, sede=cls.a_milano, nome="Totem", piattaforma="windows", orientamento="verticale"
            )
            cls.tutti = GruppoMonitor.objects.create(cliente=cls.a, nome="Tutti")

    def carica(self, file=None, **campi):
        return super().carica(file, **campi).json()

    def pubblicati(self, monitor):
        with contesto_cliente(self.a.id):
            m = Monitor.objects.get(id=monitor.id)
            corpo = palinsesto.manifest(m)
        return {c for elenco in corpo["playlist"].values() for c in (e["contenuto"] for e in elenco)}

    def test_misure_e_orientamento_dal_file(self):
        self.come(self.admin_a)
        verticale = self.carica(immagine(248, 350))
        self.assertEqual((verticale["larghezza"], verticale["altezza"], verticale["orientamento"]), (248, 350, "verticale"))
        self.assertEqual(self.carica(immagine(192, 108))["orientamento"], "orizzontale")
        r = self.client.get(f"/api/contenuti/{verticale['id']}/miniatura/")
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/jpeg"))

    def test_campagna_per_insegna_divide_totem_e_monitor(self):
        self.come(self.admin_a)
        verticale = self.carica(immagine(248, 350))["id"]
        orizzontale = self.carica(immagine(192, 108))["id"]
        r = self.client.post("/api/campagne/", {
            "nome": "Volantino 6-19 ottobre", "data_inizio": "2026-10-06", "data_fine": "2026-10-19",
            "insegne": [str(self.tocal.id)], "contenuti": [verticale, orizzontale], "durata": 8,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["contenuti"], [verticale, orizzontale])
        self.assertEqual(sorted(p["orientamento"] for p in r.json()["pubblicazioni"]), ["orizzontale", "verticale"])
        # Milano è Tocal: il totem riceve la verticale, il monitor l'orizzontale; Roma niente.
        self.assertEqual(self.pubblicati(self.totem_milano), {verticale})
        self.assertEqual(self.pubblicati(self.mon_a_milano), {orizzontale})
        self.assertEqual(self.pubblicati(self.mon_a_roma), set())

        # Togliendo l'orizzontale sparisce la pubblicazione per i monitor.
        r = self.client.patch(f"/api/campagne/{r.json()['id']}/", {"contenuti": [verticale]}, format="json")
        self.assertEqual([p["orientamento"] for p in r.json()["pubblicazioni"]], ["verticale"])
        self.assertEqual(self.pubblicati(self.mon_a_milano), set())

        self.assertEqual(self.client.delete(f"/api/campagne/{r.json()['id']}/").status_code, 204)
        self.assertEqual(self.client.get("/api/pubblicazioni/").json()["results"], [])

    def test_campagna_senza_destinatari_resta_bozza(self):
        self.come(self.admin_a)
        verticale = self.carica(immagine(248, 350))["id"]
        r = self.client.post("/api/campagne/", {"nome": "Natale", "contenuti": [verticale]}, format="json")
        self.assertEqual((r.status_code, r.json()["stato"], r.json()["pubblicazioni"]), (201, "bozza", []))

    def test_importa_csv_prova_poi_salva(self):
        self.come(self.admin_a)
        testo = (
            "nome;data_inizio;data_fine;insegne;gruppi;giorni\n"
            "Volantino 1;02/01/2026;15/01/2026;tocal;;\n"
            "Weekend;01/06/2026;30/06/2026;;Tutti;sab|dom\n"
        )
        file = lambda: SimpleUploadedFile("c.csv", testo.encode("utf-8"), content_type="text/csv")
        r = self.client.post("/api/campagne/importa/", {"file": file(), "prova": "1"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x["azione"] for x in r.json()["righe"]], ["crea", "crea"])
        self.assertEqual(self.client.get("/api/campagne/").json()["count"], 0)

        r = self.client.post("/api/campagne/importa/", {"file": file()}, format="multipart")
        self.assertEqual((r.status_code, r.json()["salvate"]), (201, 2), r.content)
        campagne = {c["nome"]: c for c in self.client.get("/api/campagne/").json()["results"]}
        self.assertEqual(campagne["Weekend"]["giorni"], [5, 6])
        self.assertEqual(campagne["Volantino 1"]["insegne"], [str(self.tocal.id)])
        # Nessun contenuto ancora: bozze, niente in onda.
        self.assertEqual(campagne["Volantino 1"]["stato"], "bozza")

        # Reimportando si aggiornano, non si duplicano.
        r = self.client.post("/api/campagne/importa/", {"file": file(), "prova": "1"}, format="multipart")
        self.assertEqual([x["azione"] for x in r.json()["righe"]], ["aggiorna", "aggiorna"])

    def test_csv_con_errori_non_salva_nulla(self):
        self.come(self.admin_a)
        testo = "nome;data_inizio;data_fine;insegne\nBuona;01/01/2026;02/01/2026;\nCattiva;05/01/2026;01/01/2026;Inesistente\n"
        r = self.client.post("/api/campagne/importa/", {"file": SimpleUploadedFile("c.csv", testo.encode())}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()["righe"][1]["errori"])
        self.assertEqual(self.client.get("/api/campagne/").json()["count"], 0)

    def test_insegne_e_campagne_degli_altri_risultano_inesistenti(self):
        self.come(self.admin_b)
        r = self.client.post("/api/campagne/", {"nome": "X", "insegne": [str(self.tocal.id)]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/insegne/").json()["results"], [])

    def test_utente_limitato_solo_monitor_delle_sue_sedi(self):
        self.come(self.user_a_milano)
        r = self.client.post("/api/campagne/", {"nome": "X", "insegne": [str(self.tocal.id)]}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/campagne/", {"nome": "Y", "monitor": [str(self.mon_a_roma.id)]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/campagne/", {"nome": "Z", "monitor": [str(self.mon_a_milano.id)]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
