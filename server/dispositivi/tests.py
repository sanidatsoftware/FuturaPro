from contenuti import palinsesto
from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base

from .models import GruppoMonitor, Monitor


class OrariTest(Base):
    def manifest(self, monitor):
        with contesto_cliente(self.a.id):
            return palinsesto.manifest(Monitor.objects.get(id=monitor.id))

    def test_orario_piu_preciso_e_validazione(self):
        self.come(self.admin_a)
        with contesto_cliente(self.a.id):
            gruppo = GruppoMonitor.objects.create(cliente=self.a, nome="Casse")
            self.mon_a_milano.gruppi.add(gruppo)
        # Senza orario: sempre acceso.
        self.assertIsNone(self.manifest(self.mon_a_milano)["accensione"])
        fasce = [{"giorni": [5, 0, 0, 1], "dalle": "07:30", "alle": "21:00"}]
        r = self.client.post("/api/orari/", {"nome": "Negozi", "fasce": fasce, "chiusure": ["2026-12-25", "2026-12-25"], "gruppi": [str(gruppo.id)]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["fasce"], [{"giorni": [0, 1, 5], "dalle": "07:30", "alle": "21:00"}])
        self.assertEqual(r.json()["chiusure"], ["2026-12-25"])
        self.assertEqual(self.manifest(self.mon_a_milano)["accensione"]["nome"], "Negozi")
        # Quello scelto per lo schermo vince su quello del gruppo.
        self.client.post("/api/orari/", {"nome": "Ingresso", "fasce": [], "monitor": [str(self.mon_a_milano.id)]}, format="json")
        self.assertEqual(self.manifest(self.mon_a_milano)["accensione"]["nome"], "Ingresso")
        errata = {"nome": "X", "fasce": [{"giorni": [], "dalle": "08:00", "alle": "08:00"}]}
        self.assertEqual(self.client.post("/api/orari/", errata, format="json").status_code, 400)
        # Solo la gestione modifica gli orari.
        self.come(self.user_a)
        self.assertEqual(self.client.post("/api/orari/", {"nome": "Y"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/orari/").status_code, 200)


class AllarmiTest(Base):
    def test_scollegato_ricollegato_e_una_sola_email(self):
        from datetime import timedelta

        from django.core import mail
        from django.test import override_settings
        from django.utils import timezone

        from .allarmi import controlla_tutti

        self.come(self.admin_a)
        self.assertEqual(self.client.put("/api/stato-schermi/", {"attivo": True}, format="json").status_code, 400)
        r = self.client.put("/api/stato-schermi/", {"attivo": True, "email": ["negozio@example.com"], "minuti": 10}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        adesso = timezone.now()
        with contesto_cliente(self.a.id):
            Monitor.objects.filter(id=self.mon_a_milano.id).update(ultimo_contatto=adesso - timedelta(minutes=30))
        with override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            self.assertEqual(controlla_tutti(adesso)["scollegati"], 1)
            self.assertEqual(controlla_tutti(adesso)["scollegati"], 0)  # una sola volta
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("Ingresso", mail.outbox[0].body)
            with contesto_cliente(self.a.id):
                Monitor.objects.filter(id=self.mon_a_milano.id).update(ultimo_contatto=adesso)
            self.assertEqual(controlla_tutti(adesso)["tornati"], 1)
            self.assertEqual(len(mail.outbox), 2)
        stato = self.client.get("/api/stato-schermi/").json()
        self.assertEqual([e["tipo"] for e in stato["eventi"]], ["ricollegato", "scollegato"])
        self.assertTrue(any(s["nome"] == "Ingresso" for s in stato["schermi"]))
        # Un utente di sede vede lo stato ma non cambia gli allarmi.
        self.come(self.user_a)
        self.assertEqual(self.client.get("/api/stato-schermi/").status_code, 200)
        self.assertEqual(self.client.put("/api/stato-schermi/", {"attivo": False}, format="json").status_code, 403)

    def test_fuori_orario_non_e_un_guasto(self):
        from datetime import timedelta

        from django.utils import timezone

        from .allarmi import controlla_tutti
        from .models import OrarioSchermi

        self.come(self.admin_a)
        self.client.put("/api/stato-schermi/", {"attivo": True, "email": ["a@example.com"]}, format="json")
        with contesto_cliente(self.a.id):
            orario = OrarioSchermi.objects.create(cliente=self.a, nome="Mai", fasce=[])
            orario.monitor.add(self.mon_a_milano)
            Monitor.objects.filter(id=self.mon_a_milano.id).update(ultimo_contatto=timezone.now() - timedelta(hours=3))
        self.assertEqual(controlla_tutti()["scollegati"], 0)

    def test_il_segnale_conta_i_minuti(self):
        import secrets

        from .models import CredenzialeDispositivo, PresenzaSchermo, impronta

        token = secrets.token_urlsafe(32)
        with contesto_cliente(self.a.id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        intestazione = {"HTTP_AUTHORIZATION": f"Device {token}"}
        self.client.post("/api/player/heartbeat/", {"versione": "1", "riposo": True}, format="json", **intestazione)
        self.client.post("/api/player/heartbeat/", {"versione": "1"}, format="json", **intestazione)  # troppo presto: non conta
        with contesto_cliente(self.a.id):
            presenza = PresenzaSchermo.objects.get(monitor=self.mon_a_milano)
        self.assertEqual((presenza.minuti, presenza.minuti_riposo), (1, 1))


class DownloadTest(Base):
    def test_fascia_e_scarica_adesso_nel_manifest(self):
        self.come(self.admin_a)
        with contesto_cliente(self.a.id):
            self.assertIsNone(palinsesto.manifest(Monitor.objects.get(id=self.mon_a_milano.id))["download"])
        r = self.client.put("/api/download/", {"attivo": True, "dalle": "22:30", "alle": "06:00", "kbps": 256}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        with contesto_cliente(self.a.id):
            fascia = palinsesto.manifest(Monitor.objects.get(id=self.mon_a_milano.id))["download"]
        self.assertEqual(fascia, {"dalle": "22:30", "alle": "06:00", "kbps": 256, "subito_fino": None})
        self.assertEqual(self.client.post("/api/download/").status_code, 200)
        with contesto_cliente(self.a.id):
            self.assertIsNotNone(palinsesto.manifest(Monitor.objects.get(id=self.mon_a_milano.id))["download"]["subito_fino"])
        self.come(self.user_a)
        self.assertEqual(self.client.put("/api/download/", {"attivo": False}, format="json").status_code, 403)


class StoricoERegistroTest(Base):
    def test_storico_allarmi_e_registro_con_filtri(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import EventoSchermo

        adesso = timezone.now()
        with contesto_cliente(self.a.id):
            for tipo, minuti_fa in (("scollegato", 90), ("ricollegato", 30)):
                e = EventoSchermo.objects.create(cliente=self.a, monitor=self.mon_a_milano, tipo=tipo, dettaglio="prova")
                EventoSchermo.objects.filter(id=e.id).update(quando=adesso - timedelta(minutes=minuti_fa))
        self.come(self.admin_a)
        dati = self.client.get("/api/storico-allarmi/").json()
        self.assertEqual(dati["riepilogo"][0]["scollegamenti"], 1)
        self.assertEqual(dati["riepilogo"][0]["minuti"], 60)
        self.assertIn("Scollegato", self.client.get("/api/storico-allarmi/?formato=csv").content.decode())
        # Il registro delle operazioni, con i filtri e il CSV.
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"nome": "Ingresso nuovo"}, format="json")
        registro = self.client.get("/api/audit/?cerca=monitor").json()
        self.assertTrue(any(e["azione"] == "monitor_modificato" for e in registro["results"]))
        self.assertIn("admin_a", registro["utenti"])
        self.assertEqual(self.client.get("/api/audit/?dal=2000-01-01&al=2000-01-02").json()["count"], 0)
        self.assertIn("monitor_modificato", self.client.get("/api/audit/?formato=csv").content.decode())
        self.come(self.user_a)
        self.assertEqual(self.client.get("/api/audit/").status_code, 403)



class StampanteTest(Base):
    def manifest(self, monitor):
        with contesto_cliente(self.a.id):
            return palinsesto.manifest(Monitor.objects.get(id=monitor.id))

    def test_anagrafica_abbinamento_e_prova(self):
        import secrets

        from django.utils import timezone

        from layout.models import Layout, Zona

        from .models import CredenzialeDispositivo, impronta

        with contesto_cliente(self.a.id):
            layout = Layout.objects.create(cliente=self.a, nome="Totem", orientamento="orizzontale")
            Zona.objects.create(cliente=self.a, layout=layout, tipo="prendi_numero", x=0, y=0, larghezza=100, altezza=100,
                                configurazione={"stampa": "browser", "messaggio": "Grazie"})
            Monitor.objects.filter(id=self.mon_a_milano.id).update(layout=layout)
            token = secrets.token_urlsafe(32)
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        self.come(self.admin_a)
        nuova = {"nome": "Epson salumi", "sede": str(self.a_milano.id), "tipo": "epson", "indirizzo": ""}
        self.assertEqual(self.client.post("/api/stampanti/", nuova, format="json").status_code, 400)
        r = self.client.post("/api/stampanti/", {**nuova, "indirizzo": "https://192.168.5.20/", "intestazione": "Negozio"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        stampante = r.json()
        self.assertEqual(stampante["indirizzo"], "192.168.5.20")
        roma = self.client.post("/api/stampanti/", {**nuova, "nome": "Roma", "sede": str(self.a_roma.id), "tipo": "browser"}, format="json").json()

        # Si abbina dall'anagrafica degli schermi, solo una stampante della stessa sede.
        url = f"/api/monitor/{self.mon_a_milano.id}/"
        self.assertEqual(self.client.patch(url, {"stampante": roma["id"]}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"stampante": stampante["id"]}, format="json").status_code, 200)
        m = self.manifest(self.mon_a_milano)
        zona = m["layout"]["zone"][0]["configurazione"]
        self.assertEqual((zona["stampa"], zona["stampante"], zona["intestazione"], zona["messaggio"]), ("epson", "192.168.5.20", "Negozio", "Grazie"))
        self.assertEqual(m["stampante"]["nome"], "Epson salumi")

        # La prova: serve un totem abbinato in linea; il semplice utente la può chiedere.
        prova = f"/api/stampanti/{stampante['id']}/prova/"
        self.come(self.user_a)
        self.assertEqual(self.client.patch(f"/api/stampanti/{stampante['id']}/", {"nome": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(prova).status_code, 400)
        with contesto_cliente(self.a.id):
            Monitor.objects.filter(id=self.mon_a_milano.id).update(ultimo_contatto=timezone.now())
        self.assertEqual(self.client.post(prova).status_code, 202)
        intestazione = {"HTTP_AUTHORIZATION": f"Device {token}"}
        self.assertEqual(self.client.get("/api/player/schermata/", **intestazione).json()["prova_stampa"]["stampante"], "192.168.5.20")
        self.client.post("/api/player/prova-stampa/", {"ok": False, "messaggio": "tempo scaduto"}, format="json", **intestazione)
        self.assertIsNone(self.client.get("/api/player/schermata/", **intestazione).json()["prova_stampa"])
        self.assertEqual(self.client.get(f"/api/stampanti/{stampante['id']}/").json()["prova"]["stato"], "fallita")

        # Un altro cliente non la vede; eliminandola il totem torna alla stampa del layout.
        self.come(self.admin_b)
        self.assertEqual(self.client.get(f"/api/stampanti/{stampante['id']}/").status_code, 404)
        self.come(self.admin_a)
        self.assertEqual(self.client.delete(f"/api/stampanti/{stampante['id']}/").status_code, 204)
        self.assertEqual(self.manifest(self.mon_a_milano)["layout"]["zone"][0]["configurazione"]["stampa"], "browser")

    def test_un_solo_totem_master_per_sede(self):
        from hashlib import sha256

        from layout.models import Layout, Zona

        with contesto_cliente(self.a.id):
            layout = Layout.objects.create(cliente=self.a, nome="Totem", orientamento="orizzontale")
            Zona.objects.create(cliente=self.a, layout=layout, tipo="prendi_numero", x=0, y=0, larghezza=100, altezza=100, configurazione={})
            secondo = Monitor.objects.create(cliente=self.a, sede=self.a_milano, nome="Totem 2", piattaforma="windows", layout=layout)
            Monitor.objects.filter(id=self.mon_a_milano.id).update(layout=layout)
        self.come(self.admin_a)
        self.client.patch(f"/api/sedi/{self.a_milano.id}/", {"indirizzo_totem": "192.168.1.70"})
        # Senza master, come prima: ogni totem tiene le code.
        self.assertIn("reparti", self.manifest(secondo)["code"])
        self.assertEqual(self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"totem_master": True}, format="json").status_code, 200)
        master, altro = self.manifest(self.mon_a_milano)["code"], self.manifest(secondo)["code"]
        self.assertIn("reparti", master)
        self.assertNotIn("reparti", altro)
        self.assertEqual(master["totem"], [sha256(altro["chiave"].encode()).hexdigest()])
        # Scegliendone un altro, il primo smette di esserlo.
        self.assertEqual(self.client.patch(f"/api/monitor/{secondo.id}/", {"totem_master": True}, format="json").status_code, 200)
        with contesto_cliente(self.a.id):
            self.assertEqual(list(Monitor.objects.filter(totem_master=True).values_list("nome", flat=True)), ["Totem 2"])


class LayoutTicketTest(Base):
    def test_layout_logo_e_stampante(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from layout.models import Layout, Zona

        self.come(self.admin_a)
        r = self.client.post("/api/layout-ticket/", {"nome": "Standard", "carta": 80}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        layout = r.json()
        self.assertEqual([e["campo"] for e in layout["elementi"]][:4], ["logo", "intestazione", "reparto", "numero"])
        url = f"/api/layout-ticket/{layout['id']}/"
        doppio = [{"campo": "numero"}, {"campo": "numero"}]
        self.assertEqual(self.client.patch(url, {"elementi": doppio}, format="json").status_code, 400)
        elementi = [{"campo": "intestazione", "testo": "Supermercato", "dimensione": 999, "carattere": "Comic"},
                    {"campo": "numero", "dimensione": 200, "grassetto": True}, {"campo": "testo", "testo": "Grazie"}]
        r = self.client.patch(url, {"elementi": elementi}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        primo = r.json()["elementi"][0]
        self.assertEqual((primo["dimensione"], primo["carattere"]), (400, "sans-serif"))  # riportati nei limiti

        # Il logo: un PNG trasparente largo 2000 punti diventa grigio e largo quanto la carta.
        grezzo = io.BytesIO()
        Image.new("RGBA", (2000, 500), (255, 0, 0, 128)).save(grezzo, "PNG")
        r = self.client.post(f"{url}logo/", {"file": SimpleUploadedFile("logo.png", grezzo.getvalue(), "image/png")})
        self.assertEqual(r.status_code, 200, r.content)
        logo = Image.open(io.BytesIO(self.client.get(f"{url}logo/").content))
        self.assertEqual((logo.mode, logo.width), ("L", 576))
        self.assertEqual(self.client.post(f"{url}logo/", {"file": SimpleUploadedFile("x.png", b"non immagine", "image/png")}).status_code, 400)

        # Abbinato alla stampante del totem, arriva nel manifest con i testi propri della stampante.
        with contesto_cliente(self.a.id):
            video = Layout.objects.create(cliente=self.a, nome="Totem", orientamento="orizzontale")
            Zona.objects.create(cliente=self.a, layout=video, tipo="prendi_numero", x=0, y=0, larghezza=100, altezza=100, configurazione={})
            Monitor.objects.filter(id=self.mon_a_milano.id).update(layout=video)
        stampante = self.client.post("/api/stampanti/", {"nome": "Epson", "sede": str(self.a_milano.id), "tipo": "epson", "indirizzo": "10.0.0.5",
                                                         "modello": "TM-T20IV", "carta": 58, "layout": layout["id"], "messaggio": "Buona spesa"}, format="json").json()
        self.assertEqual(stampante["punti"], 420)  # TM-T20IV su carta da 58 mm
        modelli = {m["chiave"]: m for m in self.client.get("/api/stampanti/modelli/").json()}
        self.assertEqual(modelli["TM-T20IV"]["carte"], {"80": 576, "58": 420})
        self.assertEqual(self.client.patch(f"/api/stampanti/{stampante['id']}/", {"modello": "XYZ"}, format="json").status_code, 400)
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"stampante": stampante["id"]}, format="json")
        with contesto_cliente(self.a.id):
            zona = palinsesto.manifest(Monitor.objects.get(id=self.mon_a_milano.id))["layout"]["zone"][0]["configurazione"]
        self.assertEqual(zona["ticket"]["punti"], 420)  # la larghezza è quella della stampante
        self.assertTrue(zona["ticket"]["logo"].startswith("data:image/png;base64,"))
        self.assertEqual((zona["ticket"]["messaggio"], zona["ticket"]["elementi"][2]["testo"]), ("Buona spesa", "Grazie"))

        # Il semplice utente non lo cambia; un'altra azienda non lo vede.
        self.come(self.user_a)
        self.assertEqual(self.client.patch(url, {"nome": "x"}, format="json").status_code, 403)
        self.come(self.admin_b)
        self.assertEqual(self.client.get(url).status_code, 404)


class DistribuzioneTest(Base):
    """«Distribuzione contenuti»: i file del palinsesto sono arrivati agli schermi? Cosa è in onda?"""

    def test_avanzamento_promozioni_e_vista_globale(self):
        import secrets

        from contenuti.models import Campagna, Contenuto, ElementoPlaylist, Playlist, Promozione, Pubblicazione

        from .models import CredenzialeDispositivo, impronta

        with contesto_cliente(self.a.id):
            immagini = [Contenuto.objects.create(cliente=self.a, nome=f"Volantino {n}", tipo="immagine", sha256=f"{n}" * 64,
                                                 dimensione=1000 * n, mime="image/jpeg") for n in (1, 2)]
            playlist = Playlist.objects.create(cliente=self.a, nome="Volantino")
            for ordine, c in enumerate(immagini):
                ElementoPlaylist.objects.create(cliente=self.a, playlist=playlist, contenuto=c, ordine=ordine)
            campagna = Campagna.objects.create(cliente=self.a, nome="Autunno", colore="#ff8800")
            promozione = Promozione.objects.create(cliente=self.a, campagna=campagna, nome="Volantino ottobre")
            pubblicazione = Pubblicazione.objects.create(cliente=self.a, nome="Volantino ottobre", playlist=playlist, promozione=promozione)
            pubblicazione.monitor.set([self.mon_a_milano])
            token = secrets.token_urlsafe(32)
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        player = {"HTTP_AUTHORIZATION": f"Device {token}"}
        versione = self.client.get("/api/player/palinsesto/", **player).json()["versione"]

        def schermo(nome):
            dati = self.client.get("/api/distribuzione/").json()
            return dati, next(s for sede in dati["sedi"] for s in sede["schermi"] if s["nome"] == nome)

        self.come(self.admin_a)
        dati, s = schermo("Ingresso")
        self.assertEqual((s["stato"], s["file_totali"], s["byte_totali"]), ("mai_collegato", 2, 3000))
        # Il player scarica: un file c'è, il secondo è a metà.
        self.client.post("/api/player/heartbeat/", {
            "versione": "web", "manifest": "vecchia", "distribuzione": {
                "versione": versione, "file": 2, "presenti": 1, "mancanti": ["2" * 64], "falliti": 0, "velocita": 500,
                "in_corso": {"nome": "Volantino 2", "byte": 1000, "totale": 2000}},
            "in_onda": [{"zona": "z1", "contenuto": str(immagini[0].id), "playlist": str(playlist.id), "da": "2026-10-15T10:00:00Z"}],
        }, format="json", **player)
        dati, s = schermo("Ingresso")
        self.assertEqual((s["stato"], s["file_presenti"], s["byte_presenti"], s["percentuale"]), ("scaricamento", 1, 2000, 66))
        self.assertEqual(s["in_corso"]["percentuale"], 50)
        self.assertEqual(s["in_onda"][0]["nome"], "Volantino 1")
        self.assertEqual((s["in_onda"][0]["promozione"], s["in_onda"][0]["campagna"]), ("Volantino ottobre", "Autunno"))
        promo = dati["promozioni"][0]
        self.assertEqual((promo["nome"], promo["schermi"], promo["completi"]), ("Volantino ottobre", 1, 0))
        # Tutto arrivato e in onda.
        self.client.post("/api/player/heartbeat/", {"versione": "web", "manifest": versione, "distribuzione": {
            "versione": versione, "file": 2, "presenti": 2, "mancanti": []}}, format="json", **player)
        dati, s = schermo("Ingresso")
        self.assertEqual((s["stato"], s["percentuale"]), ("aggiornato", 100))
        self.assertEqual(dati["promozioni"][0]["completi"], 1)
        self.assertEqual(dati["stati"]["aggiornato"], 1)
        # Lo user limitata a Milano vede solo Milano; l'altra azienda non vede nulla di A.
        self.come(self.user_a_milano)
        self.assertEqual([sede["nome"] for sede in self.client.get("/api/distribuzione/").json()["sedi"]], ["Milano"])
        self.come(self.admin_b)
        self.assertEqual([sede["nome"] for sede in self.client.get("/api/distribuzione/").json()["sedi"]], ["Torino"])
        self.assertEqual(self.client.get("/api/piattaforma/distribuzione/").status_code, 403)
        # Il SystemAdministrator vede tutte le aziende, ognuna con i suoi totali.
        self.come(self.assoluto)
        globale = self.client.get("/api/piattaforma/distribuzione/").json()
        self.assertEqual(globale["schermi"], 3)
        self.assertEqual({a["nome"]: a["stati"]["aggiornato"] for a in globale["aziende"]}, {"Azienda A": 1, "Azienda B": 0})


class DisposizioneTicketTest(Base):
    """Layout Ticket: disposizione guidata (in colonna) o libera (riquadri x, y, w)."""

    def test_disposizione_libera(self):
        from . import ticket

        self.come(self.admin_a)
        layout = self.client.post("/api/layout-ticket/", {"nome": "Libero", "carta": 80}, format="json").json()
        self.assertEqual(layout["disposizione"], "guidata")
        elementi = layout["elementi"]
        elementi[0].update(x=40, y=-5, w=99999)
        r = self.client.patch(f"/api/layout-ticket/{layout['id']}/", {"disposizione": "libera", "elementi": elementi}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["disposizione"], "libera")
        self.assertEqual((r.json()["elementi"][0]["x"], r.json()["elementi"][0]["y"], r.json()["elementi"][0]["w"]), (40, 0, 1000))
        self.assertNotIn("x", r.json()["elementi"][1])  # senza riquadro: nessuna posizione inventata
        self.assertEqual(self.client.patch(f"/api/layout-ticket/{layout['id']}/", {"disposizione": "sparsa"}, format="json").status_code, 400)
        from core.contesto import contesto_cliente

        from .models import LayoutTicket

        with contesto_cliente(self.a.id):
            self.assertEqual(ticket.per_il_player(LayoutTicket.objects.get(id=layout["id"]))["disposizione"], "libera")


class AggiornamentoPlayerTest(Base):
    def test_il_segnale_dice_la_versione_attuale(self):
        import secrets

        from player.versione import versione

        from .models import CredenzialeDispositivo, impronta

        token = secrets.token_urlsafe(32)
        with contesto_cliente(self.a.id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        r = self.client.post("/api/player/heartbeat/", {"versione": "web-0.2"}, format="json", HTTP_AUTHORIZATION=f"Device {token}")
        self.assertEqual(r.json(), {"versione_player": versione()})
        self.come(self.admin_a)
        stato = self.client.get("/api/stato-schermi/").json()
        self.assertEqual(stato["versione_attuale"], versione())
        self.assertEqual(next(s for s in stato["schermi"] if s["nome"] == "Ingresso")["versione"], "web-0.2")
        avvisi = self.client.get("/api/panoramica/").json()["avvisi"]
        self.assertTrue(any("versione precedente" in a["testo"] for a in avvisi))


class GuardianoPostazioneTest(Base):
    """Il guardiano dello script di Windows chiede da quanto tace il player della sua postazione."""

    def test_segnale_della_postazione(self):
        import secrets

        from .models import CredenzialeDispositivo, SegnalePostazione, impronta

        codice = secrets.token_hex(16)
        self.assertEqual(self.client.get(f"/api/player/postazione/{codice}/").status_code, 404)  # mai sentito
        self.assertEqual(self.client.get("/api/player/postazione/../x/").status_code, 404)
        token = secrets.token_urlsafe(32)
        with contesto_cliente(self.a.id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
        self.client.post("/api/player/heartbeat/", {"versione": "web", "postazione": codice}, format="json", HTTP_AUTHORIZATION=f"Device {token}")
        self.assertLess(self.client.get(f"/api/player/postazione/{codice}/").json()["secondi"], 5)
        # Si conserva solo l'impronta del codice, non il codice.
        self.assertFalse(SegnalePostazione.objects.filter(impronta=codice).exists())
        # Un codice non valido nel segnale si ignora.
        self.client.post("/api/player/heartbeat/", {"versione": "web", "postazione": "x' OR 1=1"}, format="json", HTTP_AUTHORIZATION=f"Device {token}")
        self.assertEqual(SegnalePostazione.objects.count(), 1)


class InstallazioneTest(Base):
    """I comandi pronti del pannello contengono le impronte: lo script le controlla da solo."""

    def test_comandi_con_le_impronte(self):
        import secrets
        import shutil
        import subprocess
        import tempfile

        from django.test import override_settings

        from clienti.models import Sede

        from .models import CredenzialeDispositivo, impronta

        cartella = tempfile.mkdtemp()
        try:
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{cartella}/k.pem",
                            "-out", f"{cartella}/ca.crt", "-days", "2", "-subj", "/CN=prova"], check=True, capture_output=True)
            attesa = subprocess.run(["openssl", "x509", "-in", f"{cartella}/ca.crt", "-noout", "-fingerprint", "-sha256"],
                                    check=True, capture_output=True, text=True).stdout.split("=")[1].strip().replace(":", "")
            with contesto_cliente(self.a.id):
                Sede.objects.filter(id=self.a_milano.id).update(indirizzo_totem="192.168.1.65")
                Monitor.objects.filter(id=self.mon_a_milano.id).update(totem_master=True)
            # Il Totem Master riferisce l'impronta del suo certificato.
            token = secrets.token_urlsafe(32)
            with contesto_cliente(self.a.id):
                CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=self.mon_a_milano, cliente_id=self.a.id)
            self.client.post("/api/player/heartbeat/", {"versione": "web", "impronta_totem": "ab" * 32}, format="json",
                             HTTP_AUTHORIZATION=f"Device {token}")
            self.come(self.admin_a)
            with override_settings(FUTURAPRO_CA_CERT=f"{cartella}/ca.crt", FUTURAPRO_INDIRIZZO="192.168.1.67"):
                dati = self.client.get("/api/installazione/").json()
            self.assertEqual(dati["impronta_server"], attesa)
            milano = next(s for s in dati["sedi"] if s["nome"] == "Milano")
            self.assertIn(f"-Server 192.168.1.67 -Impronta {attesa} -Tipo totem", milano["comando_totem"])
            self.assertIn(f"-Tipo monitor -Totem 192.168.1.65 -ImprontaTotem {'AB' * 32}", milano["comando_monitor"])
            # Senza certificato interno (certificato pubblico) niente -Impronta; lo User non li vede.
            with override_settings(FUTURAPRO_CA_CERT="", FUTURAPRO_INDIRIZZO="schermi.esempio.it"):
                self.assertNotIn("-Impronta ", self.client.get("/api/installazione/").json()["sedi"][0]["comando_totem"])
            self.come(self.user_a)
            self.assertEqual(self.client.get("/api/installazione/").status_code, 403)
        finally:
            shutil.rmtree(cartella, ignore_errors=True)
