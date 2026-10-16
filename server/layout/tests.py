import secrets
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from clienti.models import Abilitazioni
from contenuti.tests import ConFile
from core.contesto import contesto_cliente
from dispositivi.models import CredenzialeDispositivo, impronta

from . import fonti
from .models import Layout

CATANIA = {"localita": "Catania", "latitudine": 37.5, "longitudine": 15.08}
FEED = "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"
METEO = {"temperatura": 21, "giorno": True, "descrizione": "Sereno", "icona": "sole", "massima": 24, "minima": 15}


def zona(tipo, x=0, y=0, larghezza=100, altezza=100, **configurazione):
    return {"tipo": tipo, "x": x, "y": y, "larghezza": larghezza, "altezza": altezza, "configurazione": configurazione}


class LayoutTest(ConFile):
    def crea(self, **dati):
        return self.client.post("/api/layout/", {"nome": "Prova", **dati}, format="json")

    def test_da_modello(self):
        self.come(self.admin_a)
        r = self.client.post("/api/layout/da-modello/", {"modello": "orizzontale_informativo", **CATANIA, "feed": [FEED]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual([z["tipo"] for z in r.json()["zone"]], ["slide", "orologio", "meteo", "notizie"])
        slide = r.json()["zone"][0]["configurazione"]
        self.assertEqual((slide["transizione"], slide["durata_transizione"]), ("dissolvenza", 800))

    def test_modello_con_meteo_richiede_la_localita(self):
        self.come(self.admin_a)
        r = self.client.post("/api/layout/da-modello/", {"modello": "totem_verticale", "feed": [FEED]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_zone_non_valide(self):
        self.come(self.admin_a)
        self.assertEqual(self.crea(zone=[zona("slide", x=50, larghezza=60)]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("orologio", colore="rosso")]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("slide", transizione="esplosione")]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("notizie")]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("slide"), zona("slide")]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("notizie", feed=["ftp://x.it/feed"])]).status_code, 400)

    def test_pulsanti_info_prezzo_e_ingredienti(self):
        from .zone import valida_configurazione

        self.come(self.admin_a)
        # Due pulsanti sopra la slide (zone sovrapposte, livelli diversi).
        r = self.crea(zone=[zona("slide"), zona("pulsante_plugin", plugin="prezzo", forma="pillola", spessore_contorno=3),
                            zona("pulsante_plugin", plugin="ingredienti", sfondo="")])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.crea(zone=[zona("pulsante_plugin", plugin="sconti")]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("pulsante_plugin", forma="stella")]).status_code, 400)
        predefinita = valida_configurazione("pulsante_plugin", {})
        self.assertEqual((predefinita["plugin"], predefinita["forma"], predefinita["testo"]), ("prezzo", "arrotondato", ""))

    def test_formato_immagini_e_adattamenti(self):
        self.come(self.admin_a)
        r = self.crea(formato_larghezza=2480, formato_altezza=3508, zone=[zona("slide", adattamento="sfondo")])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["formato_larghezza"], r.json()["formato_altezza"]), (2480, 3508))
        r = self.client.patch(f"/api/layout/{r.json()['id']}/", {"formato_larghezza": None}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.crea(formato_larghezza=10, formato_altezza=10).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("slide", adattamento="allunga")]).status_code, 201)
        self.assertEqual(self.crea(zone=[zona("slide", adattamento="esplodi")]).status_code, 400)

    def test_non_usa_contenuti_e_playlist_di_altri_clienti(self):
        self.come(self.admin_b)
        immagine_b = self.carica().json()["id"]
        playlist_b = self.client.post("/api/playlist/", {"nome": "B"}, format="json").json()["id"]
        self.come(self.admin_a)
        self.assertEqual(self.crea(zone=[zona("immagine", contenuto=immagine_b)]).status_code, 400)
        self.assertEqual(self.crea(zone=[zona("slide", sorgente=playlist_b)]).status_code, 400)
        self.assertEqual(self.crea(immagine_sfondo=immagine_b).status_code, 400)

    def test_layout_degli_altri_risultano_inesistenti(self):
        self.come(self.admin_a)
        r = self.crea(zone=[zona("meteo", **CATANIA)])
        id_layout, id_zona = r.json()["id"], r.json()["zone"][0]["id"]
        self.come(self.admin_b)
        self.assertEqual(self.client.get(f"/api/layout/{id_layout}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/zone/{id_zona}/dati/").status_code, 404)
        r = self.client.patch(f"/api/monitor/{self.mon_b.id}/", {"layout": id_layout}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_permessi(self):
        self.come(self.user_a)
        self.assertEqual(self.crea().status_code, 403)
        self.assertEqual(self.client.get("/api/layout/").status_code, 200)
        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(admin_gestisce_layout=False)
        self.come(self.admin_a)
        self.assertEqual(self.crea().status_code, 403)
        self.come(self.assoluto, cliente=self.a)
        self.assertEqual(self.crea().status_code, 201)

    def test_un_solo_predefinito_per_orientamento(self):
        self.come(self.admin_a)
        primo = self.crea(predefinito=True).json()["id"]
        self.crea(nome="Totem", orientamento="verticale", predefinito=True)
        secondo = self.crea(nome="Nuovo", predefinito=True).json()["id"]
        with contesto_cliente(self.a.id):
            predefiniti = set(Layout.objects.filter(predefinito=True).values_list("nome", flat=True))
            self.assertFalse(Layout.objects.get(id=primo).predefinito)
            self.assertTrue(Layout.objects.get(id=secondo).predefinito)
        self.assertEqual(predefiniti, {"Nuovo", "Totem"})

    def test_orientamento_del_layout_e_del_monitor_devono_coincidere(self):
        self.come(self.admin_a)
        totem = self.crea(orientamento="verticale").json()["id"]
        url = f"/api/monitor/{self.mon_a_milano.id}/"
        self.assertEqual(self.client.patch(url, {"layout": totem}, format="json").status_code, 400)
        r = self.client.patch(url, {"layout": totem, "orientamento": "verticale", "rotazione": 90}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.patch(f"/api/layout/{totem}/", {"orientamento": "orizzontale"}, format="json")
        self.assertEqual(r.status_code, 400)


class ManifestLayoutTest(ConFile):
    def player(self, monitor):
        token = secrets.token_urlsafe(32)
        with contesto_cliente(monitor.cliente_id):
            CredenzialeDispositivo.objects.create(impronta_token=impronta(token), monitor=monitor, cliente_id=monitor.cliente_id)
        return {"HTTP_AUTHORIZATION": f"Device {token}"}

    def manifest(self, dispositivo):
        self.client.logout()
        return self.client.get("/api/player/palinsesto/", **dispositivo).json()

    def test_senza_layout_slide_a_tutto_schermo(self):
        manifest = self.manifest(self.player(self.mon_a_milano))
        self.assertEqual(manifest["schermo"], {"orientamento": "orizzontale", "rotazione": 0})
        self.assertEqual([(z["tipo"], z["larghezza"]) for z in manifest["layout"]["zone"]], [("slide", 100)])

    def test_predefinito_e_assegnato(self):
        self.come(self.admin_a)
        predefinito = self.client.post("/api/layout/", {"nome": "Predefinito", "predefinito": True}, format="json").json()["id"]
        assegnato = self.client.post("/api/layout/", {"nome": "Vetrina"}, format="json").json()["id"]
        self.client.patch(f"/api/monitor/{self.mon_a_roma.id}/", {"layout": assegnato}, format="json")
        self.assertEqual(self.manifest(self.player(self.mon_a_milano))["layout"]["id"], predefinito)
        self.assertEqual(self.manifest(self.player(self.mon_a_roma))["layout"]["id"], assegnato)

    def test_immagini_e_playlist_del_layout_vanno_al_player(self):
        self.come(self.admin_a)
        logo, slide = self.carica().json()["id"], self.carica().json()["id"]
        playlist = self.client.post("/api/playlist/", {"nome": "Fissa", "elementi": [{"contenuto": slide}]}, format="json").json()["id"]
        layout = self.client.post(
            "/api/layout/",
            {"nome": "Logo", "zone": [zona("slide", larghezza=80, sorgente=playlist), zona("immagine", x=80, larghezza=20, contenuto=logo)]},
            format="json",
        ).json()["id"]
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"layout": layout}, format="json")
        dispositivo = self.player(self.mon_a_milano)
        manifest = self.manifest(dispositivo)
        self.assertEqual(set(manifest["contenuti"]), {logo, slide})
        self.assertIn(playlist, manifest["playlist"])
        self.assertEqual(self.client.get(f"/api/player/file/{logo}/", **dispositivo).status_code, 200)

    @mock.patch("layout.fonti.meteo", return_value=METEO)
    def test_dati_delle_zone_per_il_player(self, _):
        self.come(self.admin_a)
        r = self.client.post("/api/layout/", {"nome": "Meteo", "zone": [zona("meteo", **CATANIA)]}, format="json").json()
        self.client.patch(f"/api/monitor/{self.mon_a_milano.id}/", {"layout": r["id"]}, format="json")
        id_zona = r["zone"][0]["id"]
        self.client.logout()
        dati = self.client.get(f"/api/player/zone/{id_zona}/dati/", **self.player(self.mon_a_milano))
        self.assertEqual(dati.json(), {"meteo": METEO})
        # Un monitor con un altro layout non legge le zone di questo.
        self.assertEqual(self.client.get(f"/api/player/zone/{id_zona}/dati/", **self.player(self.mon_a_roma)).status_code, 404)


RSS = b"""<?xml version="1.0"?><rss><channel><title>Feed</title>
<item><title>Prima  notizia</title></item><item><title>Seconda notizia</title></item></channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title>
<entry><title>Notizia Atom</title></entry></feed>"""
BOMBA = b"""<?xml version="1.0"?><!DOCTYPE b [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><item><title>&b;</title></item></rss>"""


class FontiTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_titoli_rss_e_atom(self):
        self.assertEqual(fonti.titoli_dal_feed(RSS), ["Prima notizia", "Seconda notizia"])
        self.assertEqual(fonti.titoli_dal_feed(ATOM), ["Notizia Atom"])

    def test_xml_ostile_non_passa(self):
        with mock.patch("layout.fonti.scarica", return_value=BOMBA):
            self.assertEqual(fonti.notizie(["https://esempio.it/feed"], 15), [])

    def test_rete_interna_vietata(self):
        for url in ("http://127.0.0.1/feed", "http://localhost:8000/", "http://10.0.0.5/x", "http://169.254.169.254/latest/"):
            with self.assertRaises(fonti.IndirizzoNonAmmesso, msg=url):
                fonti.verifica_indirizzo(url)

    def test_se_la_fonte_cade_resta_l_ultimo_dato_buono(self):
        with mock.patch("layout.fonti.scarica", return_value=RSS):
            self.assertEqual(len(fonti.notizie(["https://esempio.it/feed"], 15)), 2)
        cache.delete("feed:https://esempio.it/feed:fresco")
        with mock.patch("layout.fonti.scarica", side_effect=OSError("giù")):
            self.assertEqual(len(fonti.notizie(["https://esempio.it/feed"], 15)), 2)

    def test_meteo(self):
        risposta = (
            b'{"current": {"temperature_2m": 20.6, "weather_code": 61, "is_day": 1},'
            b' "daily": {"temperature_2m_max": [23.4], "temperature_2m_min": [14.2]}}'
        )
        with mock.patch("layout.fonti.scarica", return_value=risposta):
            self.assertEqual(
                fonti.meteo(37.5, 15.08),
                {"temperatura": 21, "giorno": True, "descrizione": "Pioggia debole", "icona": "pioggia", "massima": 23, "minima": 14},
            )


