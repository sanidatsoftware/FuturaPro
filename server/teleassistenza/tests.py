import base64
import json
import time
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from django.test import override_settings

from audit.models import EventoAudit
from core.contesto import contesto_cliente, contesto_piattaforma
from core.email import decifra
from core.tests.test_isolamento import Base
from dispositivi.models import CredenzialeDispositivo, Monitor, impronta
from utenti import doppio

from . import mesh
from .models import AccountRemoto, ConfigurazioneRemota, SessioneRemota

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
        self.assertEqual((domanda["gotonode"], domanda["viewmode"]), (["AB$c@d"], ["11"]))
        self.assertEqual(leggi_gettone(domanda["login"][0])["expire"], 2)

    @override_settings(FUTURAPRO_MESH_CHIAVE="")
    def test_senza_chiave_non_configurato(self):
        self.assertFalse(mesh.configurato())
        with self.assertRaises(mesh.MeshNonConfigurato):
            mesh.gettone({})


class DoppioTest(Base):
    def test_attivazione_codici_e_disattivazione(self):
        self.come(self.tecnico)
        segreto = self.client.post("/api/io/doppio/", {"azione": "prepara"}, format="json").json()["segreto"]
        self.assertEqual(self.client.post("/api/io/doppio/", {"azione": "attiva", "codice": "000000"}, format="json").status_code, 400)
        codice = doppio.codice_attuale(segreto)
        self.assertEqual(self.client.post("/api/io/doppio/", {"azione": "attiva", "codice": codice}, format="json").status_code, 200)
        self.tecnico.refresh_from_db()
        self.assertTrue(self.tecnico.doppio_attivo)
        self.assertNotIn(segreto, self.tecnico.doppio_segreto)  # conservato cifrato
        self.assertEqual(decifra(self.tecnico.doppio_segreto), segreto)
        # Lo stesso codice non vale due volte.
        self.assertFalse(doppio.verifica_utente(self.tecnico, codice))
        self.assertTrue(self.client.get("/api/io/").json()["doppio_attivo"])
        r = self.client.post("/api/io/doppio/", {"azione": "disattiva", "password": "sbagliata", "codice": "1"}, format="json")
        self.assertEqual(r.status_code, 400)


def attiva_doppio(utente):
    segreto = doppio.nuovo_segreto()
    from core.email import cifra

    utente.doppio_segreto, utente.doppio_attivo, utente.doppio_ultimo_passo = cifra(segreto), True, 0
    utente.save()
    return segreto


@override_settings(**MESH)
@mock.patch.object(mesh, "Comando", MeshFinto)
class ControlloRemotoTest(Base):
    def test_solo_la_piattaforma(self):
        for utente in (self.admin_a, self.user_a):
            self.come(utente, self.a)
            for url in ("/api/remoto/", "/api/remoto/sessioni/", "/api/remoto/dispositivi/?nodo=node/mesh/PC1"):
                self.assertEqual(self.client.get(url).status_code, 403, url)
            r = self.client.post("/api/remoto/sessioni/", {"nodo": PC["id"], "motivo": "prova"}, format="json")
            self.assertEqual(r.status_code, 403)

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

    def test_sessione_con_verifica_in_due_passaggi_e_registro(self):
        with contesto_cliente(self.a.id):
            Monitor.objects.filter(id=self.mon_a_milano.id).update(impronta_postazione=impronta(POSTAZIONE))
        self.come(self.tecnico)
        manda = lambda **altro: self.client.post("/api/remoto/sessioni/", {"nodo": PC["id"], "motivo": "Schermo nero", **altro}, format="json")  # noqa: E731
        r = manda()
        self.assertEqual(r.status_code, 403)
        self.assertIn("verifica in due passaggi", r.json()["detail"])
        segreto = attiva_doppio(self.tecnico)
        self.assertEqual(manda().status_code, 400)  # serve il codice
        self.assertEqual(manda(codice="123456").status_code, 400)
        self.assertEqual(self.client.post("/api/remoto/sessioni/", {"nodo": PC["id"], "motivo": "x"}, format="json").status_code, 400)
        r = manda(codice=doppio.codice_attuale(segreto))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["indirizzo"].startswith("https://server.lan/mesh/?login="))
        sessione = r.json()["sessione"]
        self.assertEqual((sessione["nome_pc"], sessione["nome_monitor"], sessione["nome_cliente"]), ("CASSA-01", "Ingresso", "Azienda A"))
        self.assertTrue(AccountRemoto.objects.filter(utente=self.tecnico).exists())
        # Per 12 ore, in questo browser, il codice non si richiede.
        self.assertEqual(manda().status_code, 201)
        # Nel registro della piattaforma e in quello dell'azienda (che però non vede le pagine).
        with contesto_piattaforma():
            self.assertTrue(EventoAudit.objects.filter(azione="controllo_remoto_aperto", cliente__isnull=True).exists())
        with contesto_cliente(self.a.id):
            self.assertTrue(EventoAudit.objects.filter(azione="controllo_remoto_aperto").exists())
        r = self.client.post(f"/api/remoto/sessioni/{sessione['id']}/chiudi/")
        self.assertEqual((r.status_code, r.json()["chiusa_da"]), (200, "tecnico"))
        self.assertEqual(self.client.post(f"/api/remoto/sessioni/{sessione['id']}/chiudi/").status_code, 400)
        # Un PC non ancora abbinato si assiste lo stesso (nessuna azienda nel registro).
        r = self.client.post("/api/remoto/sessioni/", {"nodo": SCONOSCIUTO["id"], "motivo": "Installazione"}, format="json")
        self.assertEqual((r.status_code, r.json()["sessione"]["nome_cliente"]), (201, ""))
        self.assertEqual(self.client.post("/api/remoto/sessioni/", {"nodo": "node/mesh/NO", "motivo": "Inesistente"}, format="json").status_code, 404)

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
