from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base
from layout.api import dati_zona
from layout.models import Layout, Zona

from .listini import leggi_csv, prezzo_normalizzato


class CsvTest(SimpleTestCase):
    def test_prezzi(self):
        self.assertEqual(prezzo_normalizzato("€ 12,90"), "12.90")
        self.assertEqual(prezzo_normalizzato("1.234,5"), "1234.50")
        self.assertEqual(prezzo_normalizzato("3.5"), "3.50")
        self.assertEqual(prezzo_normalizzato("a peso"), "")

    def test_intestazione_facoltativa_e_separatori(self):
        con = "Articolo;Prezzo;UM;Note;Evidenza\nProsciutto crudo;2,49;all'etto;OFFERTA;sì\n;1;;;\n"
        righe, avvisi = leggi_csv(con)
        self.assertEqual(righe, [{"prodotto": "Prosciutto crudo", "prezzo": "2.49", "unita": "all'etto", "nota": "OFFERTA", "evidenza": True, "visibile": True}])
        self.assertEqual(len(avvisi), 1)
        senza, _ = leggi_csv("Pane casereccio,3.20,al kg\n")
        self.assertEqual((senza[0]["prodotto"], senza[0]["prezzo"], senza[0]["unita"]), ("Pane casereccio", "3.20", "al kg"))


class ListiniTest(Base):
    def test_listino_dal_pannello_al_player_e_dal_gestionale(self):
        self.come(self.admin_a)
        r = self.client.post("/api/listini/", {"nome": "Banco salumi", "righe": [{"prodotto": "Mortadella", "prezzo": "1,59", "unita": "all'etto"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        listino = r.json()
        self.assertEqual(listino["righe"][0]["prezzo"], "1.59")
        r = self.client.post(f"/api/listini/{listino['id']}/importa/", {"file": SimpleUploadedFile("l.csv", "Salame;2,10;all'etto;;\nCoppa;2,90;all'etto;OFFERTA;si\n".encode())}, format="multipart")
        self.assertEqual(len(r.json()["righe"]), 2)
        self.assertIn("Coppa;2,90", self.client.get(f"/api/listini/{listino['id']}/esporta/").content.decode())
        # Un indirizzo della rete interna non si accetta (il server non va a leggere lì).
        self.assertEqual(self.client.patch(f"/api/listini/{listino['id']}/", {"fonte_url": "http://192.168.1.10/listino.csv"}, format="json").status_code, 400)

        # La zona del layout lo manda al player, solo le righe visibili.
        with contesto_cliente(self.a.id):
            layout = Layout.objects.create(cliente=self.a, nome="Banco", orientamento="orizzontale")
            zona = Zona.objects.create(cliente=self.a, layout=layout, tipo="listino", x=0, y=0, larghezza=50, altezza=100, configurazione={"listino": listino["id"]})
            dati = dati_zona(zona)["listino"]
        self.assertEqual([r["prodotto"] for r in dati["righe"]], ["Salame", "Coppa"])

        # Il gestionale invia il CSV con la chiave del listino.
        chiave = self.client.post(f"/api/listini/{listino['id']}/chiave/").json()["chiave"]
        self.client.logout()
        r = self.client.post("/api/listini/carica/", data="Bresaola;3,80;all'etto;;\n", content_type="text/csv", HTTP_AUTHORIZATION=f"Listino {chiave}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.client.post("/api/listini/carica/", data="X;1\n", content_type="text/csv", HTTP_AUTHORIZATION="Listino sbagliata").status_code, 401)
        with contesto_cliente(self.a.id):
            self.assertEqual([r["prodotto"] for r in dati_zona(Zona.objects.get(id=zona.id))["listino"]["righe"]], ["Bresaola"])
