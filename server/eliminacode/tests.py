import secrets
from datetime import timedelta

from django.utils import timezone

from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base
from dispositivi.models import CredenzialeDispositivo, Monitor, impronta

from . import servizi
from .models import Reparto

CATANIA = {"localita": "Catania", "latitudine": 37.5, "longitudine": 15.08}


class ConReparti(Base):
    def setUp(self):
        super().setUp()
        with contesto_cliente(self.a.id):
            self.salumeria = Reparto.objects.create(sede=self.a_milano, nome="Salumeria", colore="#e8a3a3", ordine=1)
            self.macelleria = Reparto.objects.create(sede=self.a_milano, nome="Macelleria", ordine=2)
            self.roma = Reparto.objects.create(sede=self.a_roma, nome="Gastronomia")

    def stato(self, reparto):
        with contesto_cliente(reparto.cliente_id):
            return Reparto.objects.get(id=reparto.id)


class CodaTest(ConReparti):
    def op(self, operazione, reparto, *argomenti):
        with contesto_cliente(reparto.cliente_id):
            return operazione(reparto.id, *argomenti)

    def test_biglietti_e_chiamate(self):
        numeri = [self.op(servizi.emetti, self.salumeria).ultimo_emesso for _ in range(3)]
        # I numeri partono da 0.
        self.assertEqual(numeri, [0, 1, 2])
        reparto = self.op(servizi.avanti, self.salumeria)
        self.assertEqual((reparto.numero, reparto.in_coda), (0, 2))
        reparto = self.op(servizi.indietro, self.salumeria)
        self.assertEqual((reparto.numero, reparto.in_coda), (None, 3))

    def test_dopo_il_99_si_riparte_da_0_e_la_coda_resta_giusta(self):
        with contesto_cliente(self.a.id):
            Reparto.objects.filter(id=self.salumeria.id).update(
                chiamati=99, emessi=99, giornata=timezone.localdate()
            )
        self.assertEqual(self.stato(self.salumeria).numero, 98)
        self.assertEqual(self.op(servizi.emetti, self.salumeria).ultimo_emesso, 99)
        reparto = self.op(servizi.emetti, self.salumeria)
        self.assertEqual((reparto.ultimo_emesso, reparto.in_coda), (0, 2))
        self.op(servizi.avanti, self.salumeria)
        reparto = self.op(servizi.avanti, self.salumeria)
        self.assertEqual((reparto.numero, reparto.in_coda), (0, 0))

    def test_avanti_senza_totem_e_primo_biglietto_dopo(self):
        for _ in range(5):
            self.op(servizi.avanti, self.salumeria)
        self.assertEqual(self.stato(self.salumeria).in_coda, 0)
        self.assertEqual(self.stato(self.salumeria).numero, 4)
        self.assertEqual(self.op(servizi.emetti, self.salumeria).ultimo_emesso, 5)

    def test_nuovo_giorno_riparte_da_zero(self):
        with contesto_cliente(self.a.id):
            Reparto.objects.filter(id=self.salumeria.id).update(
                chiamati=40, emessi=45, giornata=timezone.localdate() - timedelta(days=1)
            )
        reparto = self.op(servizi.emetti, self.salumeria)
        self.assertEqual((reparto.ultimo_emesso, reparto.in_coda), (0, 1))

    def test_imposta_mantiene_chi_e_in_coda(self):
        for _ in range(4):
            self.op(servizi.emetti, self.salumeria)
        reparto = self.op(servizi.imposta, self.salumeria, 50)
        self.assertEqual((reparto.numero, reparto.in_coda, reparto.ultimo_emesso), (50, 4, 54))

    def test_ripeti_rinnova_la_chiamata(self):
        prima = self.op(servizi.avanti, self.salumeria).chiamato_il
        dopo = self.op(servizi.ripeti, self.salumeria)
        self.assertEqual(dopo.numero, 0)
        self.assertGreater(dopo.chiamato_il, prima)


class BancoTest(ConReparti):
    def test_lo_user_cliente_chiama_ma_non_configura(self):
        self.come(self.user_a)
        r = self.client.post(f"/api/reparti/{self.salumeria.id}/avanti/")
        self.assertEqual((r.status_code, r.json()["numero"]), (200, 0))
        self.assertEqual(self.client.post("/api/reparti/", {"nome": "Pescheria", "sede": str(self.a_milano.id)}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/reparti/{self.salumeria.id}/chiave/").status_code, 403)

    def test_utente_limitato_solo_nelle_sue_sedi(self):
        self.come(self.user_a_milano)
        self.assertEqual(self.client.post(f"/api/reparti/{self.roma.id}/avanti/").status_code, 404)
        self.assertEqual(len(self.ids(self.client.get("/api/reparti/"))), 2)

    def test_altri_clienti(self):
        self.come(self.admin_b)
        self.assertEqual(self.client.post(f"/api/reparti/{self.salumeria.id}/avanti/").status_code, 404)
        r = self.client.post("/api/reparti/", {"nome": "Furbo", "sede": str(self.a_milano.id)})
        self.assertEqual(r.status_code, 400)

    def test_imposta_valida_il_numero(self):
        self.come(self.admin_a)
        url = f"/api/reparti/{self.salumeria.id}/imposta/"
        self.assertEqual(self.client.post(url, {"numero": 100}).status_code, 400)
        self.assertEqual(self.client.post(url, {"numero": 27}).json()["numero"], 27)
        self.assertEqual(self.client.post(url, {"numero": 0}).json()["numero"], 0)

    def test_chiave_per_pulsantiere_e_bilance(self):
        self.come(self.admin_a)
        chiave = self.client.post(f"/api/reparti/{self.salumeria.id}/chiave/").json()["chiave"]
        self.client.logout()
        pulsante = {"HTTP_AUTHORIZATION": f"Pulsante {chiave}"}
        r = self.client.post("/api/eliminacode/pulsante/avanti/", **pulsante)
        self.assertEqual((r.status_code, r.json()["nome"], r.json()["numero"]), (200, "Salumeria", 0))
        self.assertEqual(self.client.post("/api/eliminacode/pulsante/emetti/", **pulsante).status_code, 404)
        r = self.client.post("/api/eliminacode/pulsante/imposta/", {"numero": 42}, **pulsante)
        self.assertEqual(r.json()["numero"], 42)
        self.assertEqual(self.client.post("/api/eliminacode/pulsante/imposta/", {"numero": 100}, **pulsante).status_code, 400)
        self.assertIsNone(self.stato(self.macelleria).numero)

        self.come(self.admin_a)
        self.client.delete(f"/api/reparti/{self.salumeria.id}/chiave/")
        self.client.logout()
        r = self.client.post("/api/eliminacode/pulsante/avanti/", **pulsante)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r["WWW-Authenticate"], "Pulsante")


class TotemTest(ConReparti):
    def totem(self, monitor, **configurazione):
        self.come(self.admin_a)
        r = self.client.post(
            "/api/layout/",
            {"nome": "Totem", "zone": [{"tipo": "prendi_numero", "x": 0, "y": 0, "larghezza": 100, "altezza": 100,
                                        "configurazione": configurazione}]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.client.patch(f"/api/monitor/{monitor.id}/", {"layout": r.json()["id"]}, format="json")
        token = secrets.token_urlsafe(32)
        with contesto_cliente(monitor.cliente_id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=monitor, cliente_id=monitor.cliente_id)
        self.client.logout()
        return r.json()["zone"][0]["id"], {"HTTP_AUTHORIZATION": f"Device {token}"}

    def test_il_cliente_prende_il_numero(self):
        zona, dispositivo = self.totem(self.mon_a_milano)
        # Senza reparti scelti: quelli della sede del monitor, in ordine.
        code = self.client.get(f"/api/player/zone/{zona}/dati/", **dispositivo).json()["code"]
        self.assertEqual([c["nome"] for c in code], ["Salumeria", "Macelleria"])

        url = f"/api/player/zone/{zona}/emetti/"
        r = self.client.post(url, {"reparto": str(self.salumeria.id)}, **dispositivo)
        self.assertEqual((r.status_code, r.json()["numero"], r.json()["davanti"]), (201, 0, 0))
        r = self.client.post(url, {"reparto": str(self.salumeria.id)}, **dispositivo)
        self.assertEqual((r.json()["numero"], r.json()["davanti"]), (1, 1))
        # Un reparto di un'altra sede non si prende da questo totem.
        self.assertEqual(self.client.post(url, {"reparto": str(self.roma.id)}, **dispositivo).status_code, 400)

    def test_reparti_scelti_e_chiusi(self):
        zona, dispositivo = self.totem(self.mon_a_milano, reparti=[str(self.macelleria.id)])
        url = f"/api/player/zone/{zona}/emetti/"
        self.assertEqual(self.client.post(url, {"reparto": str(self.salumeria.id)}, **dispositivo).status_code, 400)
        with contesto_cliente(self.a.id):
            Reparto.objects.filter(id=self.macelleria.id).update(attivo=False)
        self.assertEqual(self.client.post(url, {"reparto": str(self.macelleria.id)}, **dispositivo).status_code, 400)

    def test_reparti_di_altri_clienti_non_si_configurano(self):
        with contesto_cliente(self.b.id):
            altro = Reparto.objects.create(sede=self.b_sede, nome="Altrui")
        self.come(self.admin_a)
        r = self.client.post(
            "/api/layout/",
            {"nome": "X", "zone": [{"tipo": "coda", "x": 0, "y": 0, "larghezza": 100, "altezza": 100,
                                    "configurazione": {"reparti": [str(altro.id)]}}]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_stampa_epson_richiede_l_indirizzo(self):
        self.come(self.admin_a)
        zona = {"tipo": "prendi_numero", "x": 0, "y": 0, "larghezza": 100, "altezza": 100, "configurazione": {"stampa": "epson"}}
        self.assertEqual(self.client.post("/api/layout/", {"nome": "X", "zone": [zona]}, format="json").status_code, 400)

    def test_modelli_supermercato(self):
        self.come(self.admin_a)
        for modello in ("supermercato_ora_meteo_reparti", "supermercato_reparti", "totem_eliminacode"):
            r = self.client.post("/api/layout/da-modello/", {"modello": modello, **CATANIA, "messaggi": ["Benvenuti"]}, format="json")
            self.assertEqual(r.status_code, 201, (modello, r.content))


class PersonalizzazioneTest(ConReparti):
    def zona(self, tipo, **configurazione):
        return {"tipo": tipo, "x": 0, "y": 0, "larghezza": 100, "altezza": 100, "configurazione": configurazione}

    def test_aspetto_dei_reparti_per_zona(self):
        self.come(self.admin_a)
        personalizza = {str(self.salumeria.id): {"etichetta": "Salumi e formaggi", "colore": "#2e7d32", "colore_testo": "#000000"}}
        r = self.client.post(
            "/api/layout/",
            {"nome": "Totem", "zone": [self.zona("prendi_numero", personalizza=personalizza, colonne=1,
                                                  testo_coda="{n} in attesa", arrotondamento=0, titolo="")]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        configurazione = r.json()["zone"][0]["configurazione"]
        self.assertEqual(configurazione["personalizza"], personalizza)
        self.assertEqual((configurazione["colonne"], configurazione["titolo"]), (1, ""))

    def test_personalizzazioni_non_valide(self):
        self.come(self.admin_a)
        with contesto_cliente(self.b.id):
            altro = Reparto.objects.create(sede=self.b_sede, nome="Altrui")
        for configurazione in (
            {"personalizza": {str(altro.id): {"colore": "#000000"}}},
            {"personalizza": {str(self.salumeria.id): {"colore": "verde"}}},
            {"disposizione": "a spirale"},
            {"colonne": 9},
        ):
            tipo = "prendi_numero" if "colonne" in configurazione else "coda"
            r = self.client.post("/api/layout/", {"nome": "X", "zone": [self.zona(tipo, **configurazione)]}, format="json")
            self.assertEqual(r.status_code, 400, configurazione)

    def test_colore_del_testo_del_reparto(self):
        self.come(self.admin_a)
        r = self.client.patch(f"/api/reparti/{self.salumeria.id}/", {"colore_testo": "#1d1d1d"})
        self.assertEqual(r.json()["colore_testo"], "#1d1d1d")


class CodeSulTotemTest(ConReparti):
    """Con l'indirizzo del totem sulla sede, le code le tiene il totem: il manifest lo dice."""

    def player(self, monitor):
        token = secrets.token_urlsafe(32)
        with contesto_cliente(monitor.cliente_id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=monitor, cliente_id=monitor.cliente_id)
        return {"HTTP_AUTHORIZATION": f"Device {token}"}

    def test_manifest(self):
        self.come(self.admin_a)
        self.assertEqual(self.client.patch(f"/api/sedi/{self.a_milano.id}/", {"indirizzo_totem": "https://x"}).status_code, 400)
        self.client.patch(f"/api/sedi/{self.a_milano.id}/", {"indirizzo_totem": "192.168.1.70"})
        chiave = self.client.post(f"/api/reparti/{self.salumeria.id}/chiave/").json()["chiave"]
        totem = self.client.post(
            "/api/layout/",
            {"nome": "Totem", "zone": [{"tipo": "prendi_numero", "x": 0, "y": 0, "larghezza": 100, "altezza": 100}]},
            format="json",
        ).json()["id"]
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"layout": totem}, format="json")
        self.client.logout()

        code = self.client.get("/api/player/palinsesto/", **self.player(self.mon_a_milano)).json()["code"]
        self.assertEqual((code["modo"], code["indirizzo"]), ("totem", "https://192.168.1.70:8443"))
        salumeria = next(r for r in code["reparti"] if r["nome"] == "Salumeria")
        self.assertEqual(salumeria["chiavi"], [impronta(chiave)])
        # Solo i reparti della sua sede.
        self.assertNotIn("Gastronomia", [r["nome"] for r in code["reparti"]])

        # Un monitor della stessa sede senza zona «prendi numero» sa dove leggere, ma non riceve le chiavi.
        with contesto_cliente(self.a.id):
            altro = Monitor.objects.create(sede=self.a_milano, nome="Display", piattaforma="windows")
        code = self.client.get("/api/player/palinsesto/", **self.player(altro)).json()["code"]
        self.assertEqual(code, {"modo": "totem", "indirizzo": "https://192.168.1.70:8443"})
        # E un monitor di una sede senza totem resta sul server.
        code = self.client.get("/api/player/palinsesto/", **self.player(self.mon_a_roma)).json()["code"]
        self.assertEqual(code, {"modo": "server"})

    def test_il_pannello_sa_se_il_monitor_e_aggiornato(self):
        dispositivo = self.player(self.mon_a_milano)
        versione = self.client.get("/api/player/palinsesto/", **dispositivo).json()["versione"]
        self.come(self.admin_a)
        self.assertFalse(self.client.get(f"/api/anteprima/{self.mon_a_milano.id}/").json()["aggiornato"])
        self.client.logout()
        self.client.post("/api/player/heartbeat/", {"manifest": versione}, **dispositivo)
        self.come(self.admin_a)
        self.assertTrue(self.client.get(f"/api/anteprima/{self.mon_a_milano.id}/").json()["aggiornato"])

    def test_il_monitor_segnala_una_diretta_che_non_parte(self):
        dispositivo = self.player(self.mon_a_milano)
        problema = {"testo": "Diretta «Uno» non partita: nessun segnale in 15 secondi.", "quando": "2026-10-14T10:00:00Z"}
        self.client.post("/api/player/heartbeat/", {"problema": problema}, format="json", **dispositivo)
        self.come(self.admin_a)
        self.assertEqual(self.client.get(f"/api/monitor/{self.mon_a_milano.id}/").json()["problema"]["testo"], problema["testo"])
        self.client.logout()
        # Quando torna tutto a posto, la segnalazione sparisce.
        self.client.post("/api/player/heartbeat/", {"problema": None}, format="json", **dispositivo)
        self.come(self.admin_a)
        self.assertIsNone(self.client.get(f"/api/monitor/{self.mon_a_milano.id}/").json()["problema"])

    def test_con_il_totem_il_server_non_da_numeri(self):
        self.come(self.admin_a)
        chiave = self.client.post(f"/api/reparti/{self.salumeria.id}/chiave/").json()["chiave"]
        self.client.patch(f"/api/sedi/{self.a_milano.id}/", {"indirizzo_totem": "192.168.1.70"})
        r = self.client.post(f"/api/reparti/{self.salumeria.id}/avanti/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("192.168.1.70", str(r.json()))
        self.assertEqual(self.client.get(f"/api/reparti/{self.salumeria.id}/").json()["totem"], "192.168.1.70")
        self.client.logout()
        r = self.client.post("/api/eliminacode/pulsante/avanti/", HTTP_AUTHORIZATION=f"Pulsante {chiave}")
        self.assertEqual(r.status_code, 400)
        # Le sedi senza totem continuano come prima.
        self.come(self.admin_a)
        self.assertEqual(self.client.post(f"/api/reparti/{self.roma.id}/avanti/").status_code, 200)
