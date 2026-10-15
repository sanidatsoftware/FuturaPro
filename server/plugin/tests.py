import sqlite3

from clienti.models import Abilitazioni
from contenuti import palinsesto
from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base
from dispositivi.models import Monitor

from . import query as q


def esegui(sql, **parametri):
    """La query come la esegue il servizio code: parametri tutti presenti, testo."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE articoli (ean TEXT, descr TEXT, prezzo REAL, promo REAL, fine TEXT, plu INTEGER, banco TEXT);
        INSERT INTO articoli VALUES ('8001234567890', 'Pasta 500 g', 1.29, 0.99, '2026-12-31', NULL, NULL);
        INSERT INTO articoli VALUES ('80012345', 'Sale', 0.5, NULL, NULL, NULL, NULL);
        INSERT INTO articoli VALUES (NULL, 'Prosciutto crudo', 32.9, NULL, NULL, 123, '20');
        CREATE TABLE bilancia (plu INTEGER, reparto TEXT, nome TEXT, ingr TEXT);
        INSERT INTO bilancia VALUES (123, '20', 'Prosciutto crudo', 'Coscia di suino, sale');
        INSERT INTO bilancia VALUES (123, '21', 'Pane casereccio', 'Farina, acqua, lievito');
    """)
    valori = {"codice": "", "codice_corto": "", "plu": "", "reparto": "", **parametri}
    riga = db.execute(sql, valori).fetchone()
    return dict(riga) if riga else None


class QueryTest(Base):
    def test_query_generate(self):
        prezzo = q.genera("prezzo", {"tabella": "articoli", "codice": "ean", "descrizione": "descr", "prezzo": "prezzo",
                                     "prezzo_offerta": "promo", "offerta_al": "fine", "plu": "plu", "reparto": "banco"})
        self.assertEqual(esegui(prezzo, codice="8001234567890", codice_corto="8001234567890")["prezzo_offerta"], 0.99)
        self.assertEqual(esegui(prezzo, codice="0080012345", codice_corto="80012345")["descrizione"], "Sale")
        self.assertEqual(esegui(prezzo, plu="00123", reparto="20")["prezzo"], 32.9)
        self.assertIsNone(esegui(prezzo, codice="1", codice_corto="1"))
        ingredienti = q.genera("ingredienti", {"tabella": "bilancia", "plu": "plu", "reparto": "reparto", "descrizione": "nome", "ingredienti": "ingr"})
        # Stesso PLU in due banchi: decide il prefisso.
        self.assertEqual(esegui(ingredienti, plu="00123", reparto="21")["descrizione"], "Pane casereccio")
        with self.assertRaises(ValueError):
            q.valida_mappatura("prezzo", {"tabella": 'x"; DROP'}, obbligatoria=False)
        with self.assertRaises(ValueError):
            q.valida_query("DELETE FROM articoli")
        with self.assertRaises(ValueError):
            q.valida_query("SELECT 1; DELETE FROM articoli")


class PluginTest(Base):
    def manifest(self, monitor):
        with contesto_cliente(self.a.id):
            return palinsesto.manifest(Monitor.objects.get(id=monitor.id))

    def test_abilitazione_configurazione_e_manifest(self):
        self.come(self.admin_a)
        self.assertEqual(self.client.get("/api/plugin/prezzo/").status_code, 403)  # non abilitato
        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(plugin_prezzo=True)
        r = self.client.put("/api/plugin/prezzo/", {"attivo": True, "mappatura": {"tabella": "articoli"}}, format="json")
        self.assertEqual(r.status_code, 400)  # mancano le colonne obbligatorie
        mappatura = {"tabella": "articoli", "codice": "ean", "descrizione": "descr", "prezzo": "prezzo"}
        r = self.client.put("/api/plugin/prezzo/", {"attivo": True, "mappatura": mappatura, "timeout": 6,
                                                    "aspetto": {"sfondo": "#000000", "dimensione": 999}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["aspetto"]["dimensione"], 250)
        fonte = {"tipo": "prezzo", "sede": str(self.a_milano.id), "indirizzo": "192.168.1.20", "percorso": "Dati/Prezzi/articoli.db",
                 "utente": "negozio", "password": "segreta"}
        r = self.client.post("/api/fonti-plugin/", fonte, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertNotIn("password", r.json())
        self.assertTrue(r.json()["ha_password"])

        # Senza totem nella sede i dati del negozio non si raggiungono: niente plugin.
        self.assertIsNone(self.manifest(self.mon_a_milano)["plugin"])
        self.client.patch(f"/api/sedi/{self.a_milano.id}/", {"indirizzo_totem": "192.168.1.70"})
        with contesto_cliente(self.a.id):
            secondo = Monitor.objects.create(cliente=self.a, sede=self.a_milano, nome="Cassa", piattaforma="android")
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"totem_master": True}, format="json")
        master = self.manifest(self.mon_a_milano)
        servizio = master["code"]["plugin"]["prezzo"]
        self.assertEqual((servizio["condivisione"], servizio["file"], servizio["password"]), ("\\\\192.168.1.20\\Dati", "Prezzi\\articoli.db", "segreta"))
        self.assertIn('FROM "articoli"', servizio["query"])
        self.assertEqual(master["plugin"]["prezzo"]["timeout"], 6)
        altro = self.manifest(secondo)
        self.assertEqual(altro["plugin"]["prezzo"]["aspetto"]["sfondo"], "#000000")
        self.assertNotIn("plugin", altro["code"])  # la password resta al master
        anteprima = self.client.get(f"/api/anteprima/{self.mon_a_milano.id}/manifest/").json()
        self.assertNotIn("plugin", anteprima["code"])  # e non passa dal pannello

        # Il semplice utente non vede le impostazioni; un'altra azienda non vede la fonte.
        self.come(self.user_a)
        self.assertEqual(self.client.get("/api/plugin/prezzo/").status_code, 403)
        self.come(self.admin_b)
        self.assertEqual(self.ids(self.client.get("/api/fonti-plugin/")), set())
