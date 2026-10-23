import base64
import json
import time
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from django.test import override_settings

from audit.models import EventoAudit
from core.contesto import contesto_cliente, contesto_piattaforma
from core.tests.test_isolamento import Base
from dispositivi.models import CredenzialeDispositivo, Monitor, impronta

from . import mesh
from .models import AccountRemoto, ConfigurazioneRemota, CredenzialeRemota, SessioneRemota

CHIAVE = "ab" * 80
MESH = {"FUTURAPRO_MESH_URL": "http://meshcentral:4430/mesh/", "FUTURAPRO_MESH_CHIAVE": CHIAVE, "FUTURAPRO_MESH_PUBBLICO": "https://server.lan/mesh/"}
POSTAZIONE = "0123456789abcdef0123456789abcdef"
TAG = impronta(POSTAZIONE)[:32]
PC = {"id": "node/mesh/PC1", "nome": "CASSA-01", "host": "CASSA-01", "in_linea": True, "sistema": "Windows 11", "ip": "10.0.0.7", "tag": TAG, "ultimo_contatto": None}
SCONOSCIUTO = {**PC, "id": "node/mesh/PC2", "nome": "NUOVO", "tag": ""}


class MeshFinto:
    """Al posto di MeshCentral: risponde alle azioni che usa FuturaPro."""

    def __init__(self):
        self.richieste = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def richiedi(self, azione, **dati):
        self.richieste.append((azione, dati))
        if azione == "meshes":
            return {"meshes": [{"_id": "mesh/mesh/G1", "name": mesh.NOME_GRUPPO}]}
        if azione == "nodes":
            return {"nodes": {"mesh/mesh/G1": [
                {"_id": PC["id"], "name": "CASSA-01", "rname": "CASSA-01", "conn": 1, "osdesc": "Windows 11", "ip": "10.0.0.7", "agent": {"tag": TAG}},
                {"_id": SCONOSCIUTO["id"], "name": "NUOVO", "conn": 0, "agent": {}},
            ]}}
        return {"result": "ok"}


def leggi_gettone(gettone):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    grezzo = base64.b64decode(gettone.replace("@", "+").replace("$", "/"))
    iv, tag, cifrato = grezzo[:12], grezzo[12:28], grezzo[28:]
    return json.loads(AESGCM(bytes.fromhex(CHIAVE)[:32]).decrypt(iv, cifrato + tag, None))


@override_settings(**MESH)
class GettoniTest(Base):
    def test_formato_dei_gettoni_di_meshcentral(self):
        dati = leggi_gettone(mesh.gettone({"u": "user/mesh/fp-1", "a": 3}))
        self.assertEqual((dati["u"], dati["a"]), ("user/mesh/fp-1", 3))
        self.assertLess(abs(dati["time"] - time.time()), 5)
        indirizzo = mesh.indirizzo_schermo("user/mesh/fp-1", "node/mesh/AB$c@d")
        parti = urlsplit(indirizzo)
        self.assertEqual(parti.netloc + parti.path, "server.lan/mesh/")
        domanda = parse_qs(parti.query)
        self.assertEqual((domanda["node"], domanda["viewmode"]), (["AB$c@d"], ["11"]))
        self.assertEqual(leggi_gettone(domanda["login"][0])["expire"], 2)
        self.assertEqual(parse_qs(urlsplit(mesh.indirizzo_schermo("user/mesh/fp-1", "node/mesh/X", "file")).query)["viewmode"], ["13"])

    @override_settings(FUTURAPRO_MESH_CHIAVE="")
    def test_senza_chiave_non_configurato(self):
        self.assertFalse(mesh.configurato())
        with self.assertRaises(mesh.MeshNonConfigurato):
            mesh.gettone({})


def credenziali(cliente, utente="negozio", password="Segreta-123"):
    credenziale = CredenzialeRemota(cliente=cliente, utente=utente)
    credenziale.imposta_password(password)
    credenziale.save()
    return credenziale


@override_settings(**MESH)
@mock.patch.object(mesh, "Comando", MeshFinto)
class ControlloRemotoTest(Base):
    def test_solo_la_piattaforma(self):
        for utente in (self.admin_a, self.user_a):
            self.come(utente, self.a)
            for url in ("/api/remoto/", "/api/remoto/sessioni/", "/api/remoto/dispositivi/?nodo=node/mesh/PC1", "/api/remoto/credenziali/"):
                self.assertEqual(self.client.get(url).status_code, 403, url)
            for url, dati in (
                ("/api/remoto/sessioni/", {"nodo": PC["id"], "motivo": "prova"}),
                ("/api/remoto/player/", {"nodo": PC["id"], "azione": "pausa"}),
                ("/api/remoto/credenziali/", {"cliente": str(self.a.id), "utente": "x", "password": "12345678"}),
            ):
                self.assertEqual(self.client.post(url, dati, format="json").status_code, 403, url)

    def test_inventario_con_abbinamento_dal_segnale_del_player(self):
        # Il player manda il codice della postazione: il PC con quel tag si abbina al monitor.
        token = "t" * 43
        with contesto_cliente(self.a.id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        r = self.client.post("/api/player/heartbeat/", {"versione": "x", "postazione": POSTAZIONE}, format="json", HTTP_AUTHORIZATION=f"Device {token}")
        self.assertEqual(r.status_code, 200, r.content)
        with contesto_cliente(self.a.id):
            self.assertEqual(Monitor.objects.get(id=self.mon_a_milano.id).impronta_postazione, impronta(POSTAZIONE))
        self.come(self.tecnico)
        dati = self.client.get("/api/remoto/").json()
        self.assertTrue(dati["configurato"])
        per_nome = {d["nome"]: d for d in dati["dispositivi"]}
        self.assertEqual((per_nome["CASSA-01"]["monitor"]["nome"], per_nome["CASSA-01"]["monitor"]["cliente"]), ("Ingresso", "Azienda A"))
        self.assertIsNone(per_nome["NUOVO"]["monitor"])
        self.assertNotIn("console", dati)  # la console completa è solo del SystemAdministrator
        self.come(self.assoluto)
        self.assertIn("console", self.client.get("/api/remoto/").json())

    def test_sessione_con_credenziali_dell_azienda_e_registro(self):
        with contesto_cliente(self.a.id):
            Monitor.objects.filter(id=self.mon_a_milano.id).update(impronta_postazione=impronta(POSTAZIONE))
        self.come(self.tecnico)
        manda = lambda **altro: self.client.post("/api/remoto/sessioni/", {"nodo": PC["id"], "motivo": "Schermo nero", **altro}, format="json")  # noqa: E731
        # L'azienda non ha ancora utente e password del Controllo Remoto: nessuno si collega.
        r = manda(utente="negozio", password="Segreta-123")
        self.assertEqual(r.status_code, 400)
        self.assertIn("non sono ancora impostati", str(r.json()))
        self.assertEqual(self.client.get("/api/remoto/").json()["dispositivi"][0]["accesso"], "mancanti")
        credenziali(self.a)
        self.assertEqual(self.client.get("/api/remoto/").json()["dispositivi"][0]["accesso"], "credenziali")
        self.assertEqual(manda().status_code, 400)
        self.assertEqual(manda(utente="negozio", password="sbagliata").status_code, 400)
        self.assertEqual(manda(utente="altro", password="Segreta-123").status_code, 400)
        self.assertEqual(self.client.post("/api/remoto/sessioni/", {"nodo": PC["id"], "motivo": "x"}, format="json").status_code, 400)
        r = manda(utente="Negozio", password="Segreta-123")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["indirizzo"].startswith("https://server.lan/mesh/?login="))
        self.assertIn("viewmode=11", r.json()["indirizzo"])
        self.assertIn("viewmode=13", manda(vista="file").json()["indirizzo"])
        self.assertEqual(manda(vista="terminale").status_code, 400)
        sessione = r.json()["sessione"]
        self.assertEqual((sessione["nome_pc"], sessione["nome_monitor"], sessione["nome_cliente"]), ("CASSA-01", "Ingresso", "Azienda A"))
        self.assertTrue(AccountRemoto.objects.filter(utente=self.tecnico).exists())
        # Per 12 ore, in questo browser, non si richiedono…
        self.assertEqual(self.client.get("/api/remoto/").json()["dispositivi"][0]["accesso"], "")
        self.assertEqual(manda().status_code, 201)
        # …finché non si cambiano.
        credenziale = CredenzialeRemota.objects.get(cliente=self.a)
        credenziale.imposta_password("Nuova-Segreta-1")
        credenziale.save()
        self.assertEqual(manda().status_code, 400)
        # Nel registro della piattaforma e in quello dell'azienda (che però non vede le pagine).
        with contesto_piattaforma():
            self.assertTrue(EventoAudit.objects.filter(azione="controllo_remoto_aperto", cliente__isnull=True).exists())
        with contesto_cliente(self.a.id):
            self.assertTrue(EventoAudit.objects.filter(azione="controllo_remoto_aperto").exists())
        r = self.client.post(f"/api/remoto/sessioni/{sessione['id']}/chiudi/")
        self.assertEqual((r.status_code, r.json()["chiusa_da"]), (200, "tecnico"))
        self.assertEqual(self.client.post(f"/api/remoto/sessioni/{sessione['id']}/chiudi/").status_code, 400)
        # Un PC non ancora abbinato si assiste lo stesso (nessuna azienda, nessuna credenziale).
        r = self.client.post("/api/remoto/sessioni/", {"nodo": SCONOSCIUTO["id"], "motivo": "Installazione"}, format="json")
        self.assertEqual((r.status_code, r.json()["sessione"]["nome_cliente"]), (201, ""))
        self.assertEqual(self.client.post("/api/remoto/sessioni/", {"nodo": "node/mesh/NO", "motivo": "Inesistente"}, format="json").status_code, 404)

    def test_pausa_e_riavvio_del_player(self):
        with contesto_cliente(self.a.id):
            Monitor.objects.filter(id=self.mon_a_milano.id).update(impronta_postazione=impronta(POSTAZIONE))
        credenziali(self.a)
        self.come(self.tecnico)
        finto = MeshFinto()
        with mock.patch.object(mesh, "Comando", lambda: finto):
            manda = lambda azione, **altro: self.client.post("/api/remoto/player/", {"nodo": PC["id"], "azione": azione, **altro}, format="json")  # noqa: E731
            self.assertEqual(manda("pausa").status_code, 400)  # servono le credenziali
            self.assertEqual(manda("spegni", utente="negozio", password="Segreta-123").status_code, 400)
            self.assertEqual(manda("pausa", utente="negozio", password="Segreta-123").status_code, 200)
            self.assertEqual(manda("riavvia").status_code, 200)
        comandi = [dati for azione, dati in finto.richieste if azione == "runcommands"]
        self.assertEqual([c["cmds"] for c in comandi], [mesh.COMANDI_PLAYER["pausa"], mesh.COMANDI_PLAYER["riavvia"]])
        self.assertEqual((comandi[0]["nodeids"], comandi[0]["type"], comandi[0]["runAsUser"]), ([PC["id"]], 2, 0))
        self.assertIn("Start-ScheduledTask -TaskName 'FuturaPro Player'", mesh.COMANDI_PLAYER["riavvia"])
        self.assertNotIn("Start-ScheduledTask", mesh.COMANDI_PLAYER["pausa"])
        with contesto_cliente(self.a.id):
            self.assertEqual(set(EventoAudit.objects.values_list("azione", flat=True)), {"player_in_pausa", "player_riavviato"})

    def test_credenziali_le_imposta_il_systemadministrator(self):
        dati = {"cliente": str(self.a.id), "utente": "negozio", "password": "Segreta-123"}
        self.come(self.tecnico)
        self.assertEqual(self.client.post("/api/remoto/credenziali/", dati, format="json").status_code, 403)
        self.come(self.assoluto)
        self.assertEqual(self.client.post("/api/remoto/credenziali/", {**dati, "password": "corta"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/remoto/credenziali/", {**dati, "cliente": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/remoto/credenziali/", dati, format="json").status_code, 200)
        credenziale = CredenzialeRemota.objects.get(cliente=self.a)
        self.assertNotIn("Segreta", credenziale.password)  # solo l'impronta
        self.assertTrue(credenziale.corrisponde("negozio", "Segreta-123"))
        self.come(self.tecnico)
        elenco = {a["nome"]: a for a in self.client.get("/api/remoto/credenziali/").json()}
        self.assertEqual((elenco["Azienda A"]["utente"], elenco["Azienda A"]["modificata_da"]), ("negozio", "assoluto"))
        self.assertEqual(elenco["Azienda B"]["utente"], "")
        self.assertNotIn("password", elenco["Azienda A"])

    def test_le_sessioni_dimenticate_si_chiudono_da_sole(self):
        from datetime import timedelta

        from django.utils import timezone

        sessione = SessioneRemota.objects.create(nodo=PC["id"], tecnico_id=self.tecnico.id, tecnico="tecnico", motivo="x")
        SessioneRemota.objects.filter(id=sessione.id).update(iniziata=timezone.now() - timedelta(hours=2))
        self.come(self.tecnico)
        elenco = self.client.get("/api/remoto/sessioni/").json()
        self.assertEqual(elenco[0]["chiusa_da"], "scaduta")

    def test_agente_per_lo_script_di_installazione(self):
        ConfigurazioneRemota.objects.create(gruppo="mesh/mesh/G1")
        r = self.client.get(f"/api/player/agente-remoto/?tag={TAG}")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(unquote(r["Location"]), f"https://server.lan/mesh/meshagents?id=4&meshid=G1&installflags=2&tag={TAG}")
        self.assertEqual(self.client.get("/api/player/agente-remoto/?tag=x").status_code, 404)
        with override_settings(FUTURAPRO_MESH_CHIAVE=""):
            self.assertEqual(self.client.get(f"/api/player/agente-remoto/?tag={TAG}").status_code, 404)
