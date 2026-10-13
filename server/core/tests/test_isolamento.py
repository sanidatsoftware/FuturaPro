"""L'isolamento tra clienti, verificato da ogni lato da cui potrebbe rompersi.

Se uno di questi test fallisce, la versione non si rilascia.
"""

import secrets

from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from rest_framework.test import APITestCase

from audit.models import EventoAudit
from clienti.models import Abilitazioni, Cliente, Sede
from core.contesto import ContestoMancante, contesto_attivo, contesto_cliente, contesto_piattaforma
from dispositivi.models import Monitor
from teleassistenza.models import SessioneTeleassistenza
from utenti.models import Ruolo, Utente

PASSWORD = "Una-password-lunga-123"


def crea_utente(username, ruolo, cliente=None, sedi=()):
    utente = Utente(username=username, ruolo=ruolo, cliente=cliente)
    utente.set_password(PASSWORD)
    utente.save()
    if sedi:
        with contesto_cliente(cliente.id):
            utente.sedi_consentite.set(sedi)
    return utente


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        with contesto_piattaforma():
            cls.a = Cliente.objects.create(nome="Azienda A")
            cls.b = Cliente.objects.create(nome="Azienda B")
            for cliente in (cls.a, cls.b):
                Abilitazioni.objects.create(cliente=cliente)
            cls.a_milano = Sede.objects.create(cliente=cls.a, nome="Milano")
            cls.a_roma = Sede.objects.create(cliente=cls.a, nome="Roma")
            cls.b_sede = Sede.objects.create(cliente=cls.b, nome="Torino")
            cls.mon_a_milano = Monitor.objects.create(cliente=cls.a, sede=cls.a_milano, nome="Ingresso", piattaforma="android")
            cls.mon_a_roma = Monitor.objects.create(cliente=cls.a, sede=cls.a_roma, nome="Sala attesa", piattaforma="windows")
            cls.mon_b = Monitor.objects.create(cliente=cls.b, sede=cls.b_sede, nome="Vetrina B", piattaforma="android")

        cls.assoluto = crea_utente("assoluto", Ruolo.ADMIN_ASSOLUTO)
        cls.tecnico = crea_utente("tecnico", Ruolo.TECNICO)
        cls.admin_a = crea_utente("admin_a", Ruolo.ADMIN_CLIENTE, cls.a)
        cls.user_a = crea_utente("user_a", Ruolo.USER_CLIENTE, cls.a)
        cls.user_a_milano = crea_utente("user_a_milano", Ruolo.USER_CLIENTE, cls.a, sedi=[cls.a_milano])
        cls.admin_b = crea_utente("admin_b", Ruolo.ADMIN_CLIENTE, cls.b)

    def setUp(self):
        cache.clear()

    def come(self, utente, cliente=None):
        self.client.force_login(utente)
        if cliente is not None:
            self.client.credentials(HTTP_X_CLIENTE=str(cliente.id))
        else:
            self.client.credentials()

    def ids(self, risposta):
        self.assertEqual(risposta.status_code, 200, risposta.content)
        return {r["id"] for r in risposta.json()["results"]}


class DatabaseTest(Base):
    """La seconda barriera: anche aggirando l'applicazione, il database non mostra altri clienti."""

    def conta(self, tabella):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{tabella}"')
            return cursor.fetchone()[0]

    def test_il_ruolo_del_database_non_aggira_la_rls(self):
        from core.checks import ruolo_database_soggetto_a_rls

        self.assertEqual(ruolo_database_soggetto_a_rls(None, databases=["default"]), [])

    def test_senza_contesto_il_database_non_restituisce_nulla(self):
        self.assertEqual(self.conta("dispositivi_monitor"), 0)
        self.assertEqual(self.conta("clienti_cliente"), 0)

    def test_senza_contesto_l_applicazione_rifiuta_la_query(self):
        with self.assertRaises(ContestoMancante):
            list(Monitor.objects.all())

    def test_sql_diretto_vede_solo_il_proprio_cliente(self):
        with contesto_cliente(self.a.id):
            self.assertEqual(self.conta("dispositivi_monitor"), 2)
            self.assertEqual(self.conta("clienti_cliente"), 1)
            self.assertEqual(self.conta("clienti_sede"), 2)
            # Il gestore base non filtra: qui risponde solo la Row-Level Security.
            self.assertEqual(Monitor._base_manager.count(), 2)

    def test_anche_l_applicazione_filtra_da_sola(self):
        # La prima barriera non deve contare sulla seconda: la query porta già il filtro.
        with contesto_cliente(self.a.id):
            self.assertIn(self.a.id.hex, str(Monitor.objects.all().query).replace("-", ""))

    def test_non_si_scrive_nei_dati_di_un_altro_cliente(self):
        with contesto_cliente(self.a.id):
            with self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE dispositivi_monitor SET cliente_id = %s WHERE id = %s",
                        [str(self.b.id), str(self.mon_a_milano.id)],
                    )
            with self.assertRaises(PermissionError):
                Monitor(cliente=self.b, sede=self.b_sede, nome="Intruso", piattaforma="android").save()

    def test_il_registro_di_audit_non_si_modifica(self):
        with contesto_cliente(self.a.id):
            evento = EventoAudit.objects.create(cliente_id=self.a.id, azione="prova")
            with self.assertRaises(DatabaseError), transaction.atomic():
                EventoAudit.objects.filter(id=evento.id).update(azione="falsificata")
            with self.assertRaises(DatabaseError), transaction.atomic():
                EventoAudit.objects.filter(id=evento.id).delete()


class AdminClienteTest(Base):
    def test_vede_solo_i_propri_monitor_anche_indicando_un_altro_cliente(self):
        self.come(self.admin_a, cliente=self.b)
        self.assertEqual(
            self.ids(self.client.get("/api/monitor/")),
            {str(self.mon_a_milano.id), str(self.mon_a_roma.id)},
        )

    def test_i_dati_degli_altri_risultano_inesistenti(self):
        self.come(self.admin_a)
        self.assertEqual(self.client.get(f"/api/monitor/{self.mon_b.id}/").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/monitor/{self.mon_b.id}/", {"nome": "x"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/sedi/{self.b_sede.id}/").status_code, 404)

    def test_non_puo_usare_oggetti_di_altri_clienti_nei_riferimenti(self):
        self.come(self.admin_a)
        r = self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"sede": str(self.b_sede.id)})
        self.assertEqual(r.status_code, 400)

    def test_vede_solo_gli_utenti_del_proprio_cliente(self):
        self.come(self.admin_a)
        nomi = {u["username"] for u in self.client.get("/api/utenti/").json()["results"]}
        self.assertEqual(nomi, {"admin_a", "user_a", "user_a_milano"})

    def test_non_accede_alla_piattaforma(self):
        self.come(self.admin_a)
        for url in ("/api/piattaforma/clienti/", "/api/piattaforma/utenti/", "/api/piattaforma/audit/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_non_avvia_la_teleassistenza_ma_ne_vede_il_registro(self):
        self.come(self.admin_a)
        r = self.client.post("/api/teleassistenza/sessioni/", {"monitor": str(self.mon_a_milano.id), "motivo": "x"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/api/teleassistenza/sessioni/").status_code, 200)

    def test_non_si_assegna_ruoli_di_piattaforma(self):
        self.come(self.admin_a)
        r = self.client.post("/api/utenti/", {"username": "furbo", "ruolo": "admin_assoluto", "password": PASSWORD})
        self.assertEqual(r.status_code, 400)

    def test_legge_ma_non_modifica_le_abilitazioni(self):
        self.come(self.admin_a)
        self.assertEqual(self.client.get("/api/abilitazioni/").status_code, 200)
        self.assertEqual(self.client.patch("/api/abilitazioni/", {"max_monitor": 999}).status_code, 403)

    def test_rispetta_le_abilitazioni_concesse(self):
        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(admin_gestisce_utenti=False)
        self.come(self.admin_a)
        r = self.client.post("/api/utenti/", {"username": "nuovo", "ruolo": "user_cliente", "password": PASSWORD})
        self.assertEqual(r.status_code, 403)

    def test_cliente_disattivato_non_entra(self):
        with contesto_piattaforma():
            Cliente.objects.filter(id=self.a.id).update(attivo=False)
        self.come(self.admin_a)
        self.assertEqual(self.client.get("/api/monitor/").status_code, 403)


class UserClienteTest(Base):
    def test_non_gestisce(self):
        self.come(self.user_a)
        self.assertEqual(self.client.post("/api/sedi/", {"nome": "Napoli"}).status_code, 403)
        self.assertEqual(self.client.get("/api/utenti/").status_code, 403)
        self.assertEqual(self.client.get("/api/teleassistenza/sessioni/").status_code, 403)

    def test_limitato_alle_sedi_assegnate(self):
        self.come(self.user_a_milano)
        self.assertEqual(self.ids(self.client.get("/api/monitor/")), {str(self.mon_a_milano.id)})
        self.assertEqual(self.ids(self.client.get("/api/sedi/")), {str(self.a_milano.id)})

    def test_senza_sedi_assegnate_vede_tutto_il_cliente(self):
        self.come(self.user_a)
        self.assertEqual(len(self.ids(self.client.get("/api/monitor/"))), 2)


class PiattaformaTest(Base):
    def test_assoluto_deve_scegliere_il_cliente(self):
        self.come(self.assoluto)
        self.assertEqual(self.client.get("/api/monitor/").status_code, 400)

    def test_assoluto_vede_solo_il_cliente_scelto(self):
        self.come(self.assoluto, cliente=self.b)
        self.assertEqual(self.ids(self.client.get("/api/monitor/")), {str(self.mon_b.id)})

    def test_cliente_inesistente(self):
        self.come(self.assoluto)
        self.client.credentials(HTTP_X_CLIENTE="00000000-0000-0000-0000-000000000000")
        self.assertEqual(self.client.get("/api/monitor/").status_code, 404)

    def test_le_azioni_per_conto_del_cliente_finiscono_nel_suo_registro(self):
        self.come(self.assoluto, cliente=self.b)
        self.assertEqual(self.client.patch(f"/api/monitor/{self.mon_b.id}/", {"nome": "Vetrina"}).status_code, 200)
        self.come(self.admin_b)
        eventi = self.client.get("/api/audit/").json()["results"]
        self.assertTrue(any(e["per_conto_piattaforma"] and e["utente"] == "assoluto" for e in eventi))
        self.come(self.admin_a)
        self.assertEqual(self.client.get("/api/audit/").json()["results"], [])

    def test_crea_cliente_con_abilitazioni(self):
        self.come(self.assoluto)
        r = self.client.post("/api/piattaforma/clienti/", {"nome": "Azienda C"})
        self.assertEqual(r.status_code, 201)
        with contesto_cliente(r.json()["id"]):
            self.assertTrue(Abilitazioni.objects.exists())

    def test_tecnico_apre_teleassistenza_su_qualunque_cliente(self):
        self.come(self.tecnico, cliente=self.b)
        r = self.client.post("/api/teleassistenza/sessioni/", {"monitor": str(self.mon_b.id), "motivo": "Schermo nero"})
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post(f"/api/teleassistenza/sessioni/{r.json()['id']}/chiudi/")
        self.assertEqual(r.json()["stato"], "chiusa")

    def test_tecnico_non_mescola_i_clienti(self):
        self.come(self.tecnico, cliente=self.b)
        r = self.client.post("/api/teleassistenza/sessioni/", {"monitor": str(self.mon_a_milano.id), "motivo": "x"})
        self.assertEqual(r.status_code, 400)
        with contesto_piattaforma():
            self.assertFalse(SessioneTeleassistenza.objects.exists())

    def test_tecnico_non_gestisce(self):
        self.come(self.tecnico, cliente=self.b)
        self.assertEqual(self.client.patch(f"/api/monitor/{self.mon_b.id}/", {"nome": "x"}).status_code, 403)
        self.assertEqual(self.client.get("/api/piattaforma/utenti/").status_code, 403)

    def test_il_contesto_non_sopravvive_alla_richiesta(self):
        self.come(self.assoluto, cliente=self.b)
        self.client.get("/api/monitor/")
        self.assertIsNone(contesto_attivo())


class AbbinamentoTest(Base):
    def test_flusso_completo(self):
        token = secrets.token_urlsafe(32)
        self.client.logout()
        r = self.client.post("/api/player/abbinamento/", {"token": token, "piattaforma": "android"}, format="json")
        self.assertEqual(r.status_code, 201)
        codice = r.json()["codice"]

        dispositivo = {"HTTP_AUTHORIZATION": f"Device {token}"}
        self.assertFalse(self.client.get("/api/player/stato/", **dispositivo).json()["abbinato"])

        self.come(self.admin_a)
        r = self.client.post("/api/monitor/abbina/", {"codice": codice, "nome": "Cassa", "sede": str(self.a_milano.id)})
        self.assertEqual(r.status_code, 201, r.content)

        self.come(self.admin_b)
        r = self.client.post("/api/monitor/abbina/", {"codice": codice, "nome": "Rubato", "sede": str(self.b_sede.id)})
        self.assertEqual(r.status_code, 400)

        self.client.logout()
        stato = self.client.get("/api/player/stato/", **dispositivo).json()
        self.assertEqual((stato["abbinato"], stato["nome"]), (True, "Cassa"))
        self.assertEqual(self.client.post("/api/player/heartbeat/", {"versione": "1.0"}, **dispositivo).status_code, 204)
        with contesto_cliente(self.a.id):
            self.assertTrue(Monitor.objects.get(nome="Cassa").online)

    def test_token_sconosciuto(self):
        r = self.client.post("/api/player/heartbeat/", HTTP_AUTHORIZATION=f"Device {secrets.token_urlsafe(32)}")
        self.assertIn(r.status_code, (401, 403))

    def test_limite_monitor(self):
        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(max_monitor=2)
        token = secrets.token_urlsafe(32)
        codice = self.client.post("/api/player/abbinamento/", {"token": token, "piattaforma": "windows"}).json()["codice"]
        self.come(self.admin_a)
        r = self.client.post("/api/monitor/abbina/", {"codice": codice, "nome": "Troppi", "sede": str(self.a_milano.id)})
        self.assertEqual(r.status_code, 400)
