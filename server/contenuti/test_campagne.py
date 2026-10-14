import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from clienti.models import Insegna
from core.contesto import contesto_cliente
from dispositivi.models import GruppoMonitor, Monitor

from . import palinsesto
from .models import Contenuto
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
            cls.insegna = Insegna.objects.create(cliente=cls.a, nome="Insegna A")
            cls.a_milano.insegna = cls.insegna
            cls.a_milano.save()
            cls.totem_milano = Monitor.objects.create(
                cliente=cls.a, sede=cls.a_milano, nome="Totem", piattaforma="windows", orientamento="verticale"
            )
            cls.tutti = GruppoMonitor.objects.create(cliente=cls.a, nome="Tutti")

    def carica(self, file=None, **campi):
        return super().carica(file, **campi).json()

    def pubblicati(self, monitor):
        with contesto_cliente(self.a.id):
            corpo = palinsesto.manifest(Monitor.objects.get(id=monitor.id))
        return {c for elenco in corpo["playlist"].values() for c in (e["contenuto"] for e in elenco)}

    def campagna(self, **campi):
        r = self.client.post("/api/campagne/", {"nome": "Autunno", **campi}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def promozione(self, campagna, **campi):
        dati = {"campagna": campagna["id"], "nome": "Volantino", "data_inizio": "2026-10-06", "data_fine": "2026-10-19", **campi}
        return self.client.post("/api/promozioni/", dati, format="json")

    def test_misure_e_orientamento_dal_file(self):
        self.come(self.admin_a)
        verticale = self.carica(immagine(248, 350))
        self.assertEqual((verticale["larghezza"], verticale["altezza"], verticale["orientamento"]), (248, 350, "verticale"))
        self.assertEqual(self.carica(immagine(192, 108))["orientamento"], "orizzontale")
        r = self.client.get(f"/api/contenuti/{verticale['id']}/miniatura/")
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/jpeg"))

    def test_promozione_per_insegna_divide_totem_e_monitor(self):
        self.come(self.admin_a)
        verticale = self.carica(immagine(248, 350))["id"]
        orizzontale = self.carica(immagine(192, 108))["id"]
        campagna = self.campagna(insegne=[str(self.insegna.id)], durata=8)
        r = self.promozione(campagna, contenuti=[verticale, orizzontale])
        self.assertEqual(r.status_code, 201, r.content)
        promo = r.json()
        self.assertEqual(promo["contenuti"], [verticale, orizzontale])
        self.assertEqual(sorted(p["orientamento"] for p in promo["pubblicazioni"]), ["orizzontale", "verticale"])
        # Milano è dell'insegna: il totem riceve la verticale, il monitor l'orizzontale; Roma niente.
        self.assertEqual(self.pubblicati(self.totem_milano), {verticale})
        self.assertEqual(self.pubblicati(self.mon_a_milano), {orizzontale})
        self.assertEqual(self.pubblicati(self.mon_a_roma), set())

        # La campagna riassume le sue promozioni.
        c = self.client.get(f"/api/campagne/{campagna['id']}/").json()
        self.assertEqual((c["data_inizio"], c["data_fine"], len(c["promozioni"])), ("2026-10-06", "2026-10-19", 1))

        # Cambiando i destinatari della campagna cambiano quelli di tutte le promozioni.
        self.client.patch(f"/api/campagne/{campagna['id']}/", {"insegne": [], "monitor": [str(self.mon_a_roma.id)]}, format="json")
        self.assertEqual(self.pubblicati(self.mon_a_roma), {orizzontale})
        self.assertEqual(self.pubblicati(self.totem_milano), set())

        # Togliendo l'orizzontale sparisce la pubblicazione per i monitor.
        r = self.client.patch(f"/api/promozioni/{promo['id']}/", {"contenuti": [verticale]}, format="json")
        self.assertEqual([p["orientamento"] for p in r.json()["pubblicazioni"]], ["verticale"])
        self.assertEqual(self.pubblicati(self.mon_a_roma), set())

        self.assertEqual(self.client.delete(f"/api/campagne/{campagna['id']}/").status_code, 204)
        self.assertEqual(self.client.get("/api/pubblicazioni/").json()["results"], [])
        self.assertEqual(self.client.get("/api/promozioni/").json()["results"], [])

    def test_promozione_senza_destinatari_resta_bozza(self):
        self.come(self.admin_a)
        verticale = self.carica(immagine(248, 350))["id"]
        r = self.promozione(self.campagna(), contenuti=[verticale], data_inizio="2099-01-01", data_fine="2099-01-10")
        self.assertEqual((r.status_code, r.json()["stato"], r.json()["pubblicazioni"]), (201, "bozza", []))

    def test_date_obbligatorie_e_nomi_unici(self):
        self.come(self.admin_a)
        campagna = self.campagna()
        r = self.client.post("/api/promozioni/", {"campagna": campagna["id"], "nome": "X"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.promozione(campagna).status_code, 201)
        self.assertEqual(self.promozione(campagna, nome="volantino").status_code, 400)
        self.assertEqual(self.promozione(campagna, nome="Altro", data_fine="2026-10-01").status_code, 400)

    def test_importa_csv_prova_poi_salva(self):
        self.come(self.admin_a)
        testo = (
            "campagna;promozione;data_inizio;data_fine;insegne;gruppi;giorni\n"
            "Autunno;Volantino 1;06/10/2026;19/10/2026;insegna a;;\n"
            "Autunno;Volantino 2;20/10/2026;02/11/2026;;Tutti;\n"
            "Speciali;Weekend;01/06/2026;30/06/2026;;Tutti;sab|dom\n"
        )
        file = lambda: SimpleUploadedFile("c.csv", testo.encode("utf-8"), content_type="text/csv")
        r = self.client.post("/api/campagne/importa/", {"file": file(), "prova": "1"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x["azione"] for x in r.json()["righe"]], ["crea", "crea", "crea"])
        self.assertEqual(self.client.get("/api/campagne/").json()["count"], 0)

        r = self.client.post("/api/campagne/importa/", {"file": file()}, format="multipart")
        self.assertEqual((r.status_code, r.json()["salvate"], r.json()["campagne"]), (201, 3, 2), r.content)
        campagne = {c["nome"]: c for c in self.client.get("/api/campagne/").json()["results"]}
        # I destinatari delle righe di una campagna si sommano.
        self.assertEqual(campagne["Autunno"]["insegne"], [str(self.insegna.id)])
        self.assertEqual(campagne["Autunno"]["gruppi"], [str(self.tutti.id)])
        self.assertEqual([p["nome"] for p in campagne["Autunno"]["promozioni"]], ["Volantino 1", "Volantino 2"])
        self.assertEqual(campagne["Speciali"]["promozioni"][0]["giorni"], [5, 6])

        # Reimportando si aggiornano, non si duplicano.
        r = self.client.post("/api/campagne/importa/", {"file": file(), "prova": "1"}, format="multipart")
        self.assertEqual([x["azione"] for x in r.json()["righe"]], ["aggiorna", "aggiorna", "aggiorna"])

    def test_csv_con_errori_non_salva_nulla(self):
        self.come(self.admin_a)
        testo = (
            "campagna;promozione;data_inizio;data_fine;insegne\n"
            "A;Buona;01/01/2026;02/01/2026;\n"
            "A;Cattiva;05/01/2026;01/01/2026;Inesistente\n"
        )
        r = self.client.post("/api/campagne/importa/", {"file": SimpleUploadedFile("c.csv", testo.encode())}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()["righe"][1]["errori"])
        self.assertEqual(self.client.get("/api/campagne/").json()["count"], 0)

    def test_pulizia_dei_contenuti_di_promozioni_scadute(self):
        self.come(self.admin_a)
        vecchia = self.carica(immagine(248, 350))["id"]
        attuale = self.carica(immagine(248, 350))["id"]
        condivisa = self.carica(immagine(192, 108))["id"]
        libera = self.carica(immagine(192, 108))["id"]
        campagna = self.campagna(insegne=[str(self.insegna.id)])
        ieri = timezone.localdate() - timedelta(days=1)
        self.promozione(campagna, nome="Scaduta", data_inizio=str(ieri - timedelta(days=10)), data_fine=str(ieri),
                        contenuti=[vecchia, condivisa])
        self.promozione(campagna, nome="In corso", data_inizio=str(ieri), data_fine=str(ieri + timedelta(days=10)),
                        contenuti=[attuale, condivisa])
        r = self.client.get("/api/contenuti/pulizia/")
        self.assertEqual(r.json()["id"], [vecchia])
        r = self.client.post("/api/contenuti/pulizia/", format="json")
        self.assertEqual(r.json()["contenuti"], 1)
        with contesto_cliente(self.a.id):
            rimasti = {str(i) for i in Contenuto.objects.values_list("id", flat=True)}
        self.assertEqual(rimasti, {attuale, condivisa, libera})

    def test_campagne_degli_altri_risultano_inesistenti(self):
        self.come(self.admin_a)
        campagna = self.campagna()
        self.come(self.admin_b)
        self.assertEqual(self.promozione(campagna).status_code, 400)
        r = self.client.post("/api/campagne/", {"nome": "X", "insegne": [str(self.insegna.id)]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/insegne/").json()["results"], [])

    def test_utente_limitato_solo_monitor_delle_sue_sedi(self):
        self.come(self.user_a_milano)
        r = self.client.post("/api/campagne/", {"nome": "X", "insegne": [str(self.insegna.id)]}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/campagne/", {"nome": "Y", "monitor": [str(self.mon_a_roma.id)]}, format="json")
        self.assertEqual(r.status_code, 400)
        campagna = self.campagna(nome="Z", monitor=[str(self.mon_a_milano.id)])
        self.assertEqual(self.promozione(campagna).status_code, 201)
