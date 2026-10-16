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
        ricerca = q.genera_ricerca("prezzo", {"tabella": "articoli", "codice": "ean", "descrizione": "descr", "prezzo": "prezzo"})
        db = sqlite3.connect(":memory:")
        db.executescript("CREATE TABLE articoli (ean TEXT, descr TEXT, prezzo REAL); INSERT INTO articoli VALUES ('1', 'Sale fino', 0.5), ('2', 'Pasta', 1), ('3', 'Sale grosso', 0.4);")
        self.assertEqual([r[0] for r in db.execute(ricerca, {"testo": "%SALE%"})], ["Sale fino", "Sale grosso"])
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

        # Quando copiarlo: orari e/o minuti, almeno uno; «Aggiorna adesso» arriva al totem.
        fonte_id = r.json()["id"]
        url_fonte = f"/api/fonti-plugin/{fonte_id}/"
        self.assertEqual(self.client.patch(url_fonte, {"aggiorna_minuti": 0, "orari": []}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url_fonte, {"orari": ["25:00"]}, format="json").status_code, 400)
        r = self.client.patch(url_fonte, {"aggiorna_minuti": 0, "orari": ["13:00", "6.30"]}, format="json")
        self.assertEqual(r.json()["orari"], ["06:30", "13:00"])
        self.assertIsNotNone(self.client.post(f"{url_fonte}aggiorna/").json()["richiesta_copia"])

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
        self.assertEqual((servizio["orari"], servizio["minuti"]), (["06:30", "13:00"], 0))
        self.assertTrue(servizio["richiesta"])
        self.assertEqual(master["plugin"]["prezzo"]["timeout"], 6)
        altro = self.manifest(secondo)
        self.assertEqual(altro["plugin"]["prezzo"]["aspetto"]["sfondo"], "#000000")
        self.assertNotIn("plugin", altro["code"])  # la password resta al master
        # Un totem o monitor non master cerca prezzi e ingredienti nel servizio del Totem Master.
        self.assertEqual(altro["code"]["indirizzo"], "https://192.168.1.70:8443")
        self.assertNotIn("reparti", altro["code"])
        anteprima = self.client.get(f"/api/anteprima/{self.mon_a_milano.id}/manifest/").json()
        self.assertNotIn("plugin", anteprima["code"])  # e non passa dal pannello

        # Il semplice utente non vede le impostazioni; un'altra azienda non vede la fonte.
        self.come(self.user_a)
        self.assertEqual(self.client.get("/api/plugin/prezzo/").status_code, 403)
        self.come(self.admin_b)
        self.assertEqual(self.ids(self.client.get("/api/fonti-plugin/")), set())


class EvoPosTest(Base):
    """La query pronta per EvoPos, su un file con lo stesso schema (dati inventati)."""

    def test_codici_offerte_e_bilancia(self):
        from datetime import datetime, timedelta

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE Articoli (Codice TEXT, Descrizione TEXT, CodiceReparto TEXT, Tipo TEXT, Stato INTEGER);
            CREATE TABLE CodiceEan (Ean TEXT, CodiceArticolo TEXT);
            CREATE TABLE PrezziDiVendita (CodiceArticolo TEXT, numeroPrezzo INTEGER, Valore NUMERIC);
            CREATE TABLE LegacyPromo (CodiceOfferta TEXT, Attivo INTEGER, CodiceEffetto INTEGER, ValoreEffetto1 NUMERIC, DataInizio TEXT, DataFine TEXT);
            CREATE TABLE LinkArticoliLegacypromo (CodiceArticolo TEXT, CodiceOfferta TEXT);
            INSERT INTO Articoli VALUES ('00800000000011', 'PIATTI', '0005', 'PZ', 1), ('8000000000028', 'BISCOTTI', '0001', 'PZ', 1),
                                        ('2105120', 'MORTADELLA', '0012', 'KG', 1), ('8000000000035', 'VECCHIO', '0001', 'PZ', -48);
            INSERT INTO CodiceEan VALUES ('00800000000011', '00800000000011'), ('8000000000028', '8000000000028'),
                                         ('2105120', '2105120'), ('8000000000035', '8000000000035');
            INSERT INTO PrezziDiVendita VALUES ('00800000000011', 1, 1.19), ('00800000000011', 3, 1.0), ('8000000000028', 1, 2.5),
                                               ('2105120', 1, 14.9), ('8000000000035', 1, 1);
            INSERT INTO LinkArticoliLegacypromo VALUES ('00800000000011', 'A'), ('8000000000028', 'B');
        """)
        adesso = datetime.now()
        fmt = "%Y-%m-%d %H:%M:%S"
        db.execute("INSERT INTO LegacyPromo VALUES ('A', 1, 11, 0.3, ?, ?)", ((adesso - timedelta(days=1)).strftime(fmt), (adesso + timedelta(days=3)).strftime(fmt)))
        db.execute("INSERT INTO LegacyPromo VALUES ('B', 1, 11, 0.5, ?, ?)", ((adesso - timedelta(days=9)).strftime(fmt), (adesso - timedelta(days=2)).strftime(fmt)))

        def cerca(codice):
            riga = db.execute(q.EVOPOS, {"codice": codice, "codice_corto": codice.lstrip("0"), "plu": "", "reparto": ""}).fetchone()
            return dict(riga) if riga else None

        # Ricerca per descrizione (pulsante sul totem): solo articoli attivi, con l'offerta in corso.
        trovati = [dict(r) for r in db.execute(q.EVOPOS_RICERCA, {"testo": "%i%"}).fetchall()]
        self.assertEqual([t["descrizione"] for t in trovati], ["BISCOTTI", "PIATTI"])
        self.assertEqual(trovati[1]["prezzo_offerta"], 0.89)
        self.assertIsNone(trovati[0]["prezzo_offerta"])

        piatti = cerca("0800000000011")  # letto a 13 cifre, salvato a 14
        self.assertEqual((piatti["prezzo"], piatti["prezzo_offerta"]), (1.19, 0.89))
        self.assertIsNone(cerca("8000000000028")["prezzo_offerta"])  # offerta scaduta
        mortadella = cerca("2105120012345")  # etichetta della bilancia: prime 7 cifre
        self.assertEqual((mortadella["descrizione"], mortadella["unita"]), ("MORTADELLA", "kg"))
        self.assertIsNone(cerca("8000000000035"))  # articolo non attivo
        self.assertIsNone(cerca("1234567890123"))
        self.assertIsNone(piatti["prezzo_etichetta"])
        self.assertEqual(mortadella["prezzo_etichetta"], 12.34)  # cifre 8-12 dell'etichetta


class DigiTest(Base):
    """La query pronta per DIGI (DigiProject.db), su un file con lo stesso schema (dati inventati)."""

    def test_etichetta_bilancia(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE Plus (Id INT, Code INT, Label TEXT, SellPriceWithTaxes NUMERIC, BarCode1 TEXT, QuantityType INT,
                               IsEnabled BOOL, IngredientId INT, Text5Id INT, UpdatedAt DATETIME);
            CREATE TABLE Ingredients (Id INT, Description TEXT);
            CREATE TABLE Texts (Id INT, Message TEXT);
            CREATE TABLE PluDepartments (PluId INT, DepartmentId INT);
            CREATE TABLE Departments (Id INT, Name TEXT);
            INSERT INTO Departments VALUES (2, 'Macelleria'), (7, 'Salumeria');
            INSERT INTO Plus VALUES (1, 162, 'SALSICCIA FINA', 8.9, '2110162000003', 0, 1, 10, NULL, '2026-01-01'),
                                    (2, 254, 'COTTO', 9.9, '2120254000002', 0, 1, NULL, 20, '2026-01-01'),
                                    (3, 99, 'VECCHIO', 1, '2110099000004', 0, 0, NULL, NULL, NULL);
            INSERT INTO PluDepartments VALUES (1, 2), (2, 7), (3, 2);
            INSERT INTO Ingredients VALUES (10, 'INGREDIENTI: carne di suino - sale - pepe nero - a' || char(13) || char(10) || 'cqua');
            INSERT INTO Texts VALUES (20, 'INGREDIENTI: coscia di suino, sale');
        """)

        def cerca(codice):
            riga = db.execute(q.DIGI, {"codice": codice, "codice_corto": codice.lstrip("0"), "plu": "", "reparto": ""}).fetchone()
            return dict(riga) if riga else None

        trovati = [dict(r) for r in db.execute(q.DIGI_RICERCA, {"testo": "%s%"}).fetchall()]
        self.assertEqual([(t["descrizione"], t["reparto"]) for t in trovati], [("SALSICCIA FINA", "Macelleria")])

        salsiccia = cerca("2110162005664")
        self.assertEqual((salsiccia["descrizione"], salsiccia["reparto"], salsiccia["prezzo_etichetta"], salsiccia["unita"]),
                         ("SALSICCIA FINA", "Macelleria", 5.66, "kg"))
        self.assertTrue(salsiccia["ingredienti"].startswith("INGREDIENTI: carne di suino"))
        self.assertEqual(cerca("2120254002242")["ingredienti"], "INGREDIENTI: coscia di suino, sale")  # dal testo 5
        self.assertIsNone(cerca("2110099001000"))  # PLU disattivato
        self.assertIsNone(cerca("8001234567890"))


class ProvaAccessoTest(Base):
    """«Prova accesso»: il pannello chiede, il Totem Master prova cartella e file, il LED si accende."""

    def test_richiesta_esecuzione_ed_esito(self):
        import secrets

        from dispositivi.models import CredenzialeDispositivo, impronta

        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(plugin_prezzo=True)
            altro = Monitor.objects.create(cliente=self.a, sede=self.a_milano, nome="Cassa", piattaforma="android")
        self.come(self.admin_a)
        fonte = {"tipo": "prezzo", "sede": str(self.a_milano.id), "indirizzo": "192.168.1.20", "percorso": "Dati/articoli.db"}
        fonte_id = self.client.post("/api/fonti-plugin/", fonte, format="json").json()["id"]
        url = f"/api/fonti-plugin/{fonte_id}/"
        self.assertEqual(self.client.get(url).json()["prova"]["stato"], "mai")
        self.assertEqual(self.client.post(f"{url}prova/").json()["prova"]["stato"], "in_attesa")
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"totem_master": True}, format="json")

        def intestazione(monitor):
            token = secrets.token_urlsafe(32)
            with contesto_cliente(self.a.id):
                CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=monitor, cliente_id=self.a.id)
            return {"HTTP_AUTHORIZATION": f"Device {token}"}

        # Tocca solo al Totem Master della sede.
        self.assertEqual(self.client.get("/api/player/schermata/", **intestazione(altro)).json()["prova_plugin"], [])
        master = intestazione(self.mon_a_milano)
        prove = self.client.get("/api/player/schermata/", **master).json()["prova_plugin"]
        self.assertEqual([p["tipo"] for p in prove], ["prezzo"])
        # Una risposta a una richiesta vecchia non conta.
        self.client.post("/api/player/prova-plugin/", {"tipo": "prezzo", "richiesta": "2020-01-01", "ok": True}, format="json", **master)
        self.assertEqual(self.client.get(url).json()["prova"]["stato"], "in_attesa")
        r = self.client.post("/api/player/prova-plugin/", {"tipo": "prezzo", "richiesta": prove[0]["richiesta"], "ok": False,
                                                          "messaggio": "Cartella non raggiungibile"}, format="json", **master)
        self.assertEqual(r.status_code, 204)
        prova = self.client.get(url).json()["prova"]
        self.assertEqual((prova["stato"], prova["messaggio"], prova["totem"]), ("errore", "Cartella non raggiungibile", self.mon_a_milano.nome))
        self.assertEqual(self.client.get("/api/player/schermata/", **master).json()["prova_plugin"], [])  # fatta
        # Un'altra azienda non può chiedere la prova.
        self.come(self.admin_b)
        self.assertEqual(self.client.post(f"{url}prova/").status_code, 404)
