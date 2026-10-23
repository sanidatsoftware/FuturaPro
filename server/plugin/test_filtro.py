import io
import unittest
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from audit.models import EventoAudit
from contenuti import palinsesto
from contenuti.models import Contenuto, Controllo, Tipo
from contenuti.tests import ConFile
from core.contesto import contesto_cliente
from dispositivi.models import Monitor

from . import canali, filtro
from .models import FiltroContenuti

# Nei test il modello è finto: il colore dell'immagine decide la «probabilità di nudo».
NUDO_PER_COLORE = {"red": 0.6, "blue": 0.95, "green": 0.0, "orange": 0.0}
COLORI = {(255, 0, 0): "red", (0, 0, 255): "blue", (0, 128, 0): "green", (255, 165, 0): "orange"}


def categorie_finte(immagine):
    r, g, b = immagine.convert("RGB").resize((1, 1)).getpixel((0, 0))
    vicino = min(COLORI, key=lambda c: sum((x - y) ** 2 for x, y in zip(c, (r, g, b))))
    nudo = NUDO_PER_COLORE[COLORI[vicino]]
    return {"nudo": nudo, "intimo": (1 - nudo) / 2, "vestito": (1 - nudo) / 2, "altro": 0.0}


def foto(colore, nome="foto.png"):
    uscita = io.BytesIO()
    Image.new("RGB", (64, 48), colore).save(uscita, "PNG")
    return SimpleUploadedFile(nome, uscita.getvalue(), content_type="image/png")


def video(colori, nome="spot.mp4"):
    """Un MP4 con un fotogramma al secondo per colore."""
    import av

    uscita = io.BytesIO()
    with av.open(uscita, "w", format="mp4") as contenitore:
        flusso = contenitore.add_stream("libx264", rate=1)
        flusso.width, flusso.height, flusso.pix_fmt = 64, 48, "yuv420p"
        for colore in colori:
            fotogramma = av.VideoFrame.from_image(Image.new("RGB", (64, 48), colore))
            for pacchetto in flusso.encode(fotogramma):
                contenitore.mux(pacchetto)
        for pacchetto in flusso.encode():
            contenitore.mux(pacchetto)
    return SimpleUploadedFile(nome, uscita.getvalue(), content_type="video/mp4")


@mock.patch.object(filtro, "categorie", categorie_finte)
class FiltroCaricamentiTest(ConFile):
    def attiva(self, **campi):
        with contesto_cliente(self.a.id):
            FiltroContenuti.objects.update_or_create(cliente=self.a, defaults=campi)

    def test_spento_non_controlla(self):
        self.come(self.admin_a)
        self.assertEqual(self.carica(foto("blue")).status_code, 201)

    def test_immagine_vietata_non_si_carica_e_resta_nel_registro(self):
        self.attiva(immagini=True, severita_immagini="media")
        self.come(self.user_a)
        r = self.carica(foto("red", "spiaggia.png"))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("rifiutata dal filtro", r.json()["file"][0])
        with contesto_cliente(self.a.id):
            self.assertFalse(Contenuto.objects.filter(nome="spiaggia.png").exists())
            rifiuto = EventoAudit.objects.get(azione="contenuto_rifiutato_filtro")
        self.assertEqual((rifiuto.utente, rifiuto.dettagli["nome"]), ("user_a", "spiaggia.png"))
        # Quello che il filtro lascia passare si carica normalmente.
        self.assertEqual(self.carica(foto("green")).status_code, 201)

    def test_la_severita_decide_la_soglia(self):
        self.attiva(immagini=True, severita_immagini="bassa")  # soglia 0,70: il rosso (0,6) passa
        self.come(self.admin_a)
        self.assertEqual(self.carica(foto("red")).status_code, 201)
        self.assertEqual(self.carica(foto("blue")).status_code, 400)

    def test_video_si_carica_con_i_tratti_vietati_coperti(self):
        self.attiva(video=True, severita_video="alta")  # un fotogramma al secondo, soglia 0,35
        self.come(self.admin_a)
        r = self.carica(video(["green", "green", "red", "red", "green", "green", "green", "blue", "green"]))
        self.assertEqual(r.status_code, 201, r.content)
        # Da un controllo prima a uno dopo: 1–4 s (secondi 2 e 3) e 6–8 s (secondo 7).
        self.assertEqual(r.json()["coperture"], [[1.0, 4.0], [6.0, 8.0]])
        with contesto_cliente(self.a.id):
            self.assertTrue(EventoAudit.objects.filter(azione="video_coperto_filtro").exists())
            voce = palinsesto._voce(Contenuto.objects.get(id=r.json()["id"]))
        self.assertEqual(voce["coperture"], [[1.0, 4.0], [6.0, 8.0]])
        pulito = self.carica(video(["green", "green", "green"])).json()
        self.assertEqual(pulito["coperture"], [])
        # Il filtro per le immagini non tocca i video, e viceversa.
        self.attiva(video=False, immagini=True)
        self.assertEqual(self.carica(video(["blue", "blue"])).json()["coperture"], [])

    def test_senza_modello_con_il_filtro_attivo_non_passa_nulla(self):
        self.attiva(immagini=True)
        self.come(self.admin_a)
        with mock.patch.object(filtro, "categorie", side_effect=filtro.FiltroNonDisponibile("assente")):
            r = self.carica(foto("green"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("non riesce a partire", r.json()["file"][0])


class FiltroPannelloTest(ConFile):
    def test_lo_gestisce_chi_gestisce_l_azienda(self):
        self.come(self.user_a)
        self.assertEqual(self.client.get("/api/plugin/filtro-contenuti/").status_code, 403)
        self.come(self.admin_a)
        dati = self.client.get("/api/plugin/filtro-contenuti/").json()
        self.assertEqual((dati["immagini"], dati["video"], dati["dirette"]), (False, False, False))
        r = self.client.put("/api/plugin/filtro-contenuti/", {"immagini": True, "severita_immagini": "alta"}, format="json")
        self.assertEqual((r.status_code, r.json()["severita_immagini"]), (200, "alta"))
        self.assertEqual(self.client.put("/api/plugin/filtro-contenuti/", {"severita_video": "massima"}, format="json").status_code, 400)
        # Ogni azienda ha il suo.
        self.come(self.admin_b)
        self.assertFalse(self.client.get("/api/plugin/filtro-contenuti/").json()["immagini"])

    @mock.patch.object(filtro, "categorie", categorie_finte)
    @mock.patch.object(filtro, "disponibile", return_value=True)
    def test_prova_senza_salvare(self, _disponibile):
        self.come(self.admin_a)
        r = self.client.post("/api/plugin/filtro-contenuti/", {"file": foto("red"), "severita": "alta"}, format="multipart")
        self.assertEqual((r.status_code, r.json()["vietato"], r.json()["tipo"]), (200, True, "immagine"))
        r = self.client.post("/api/plugin/filtro-contenuti/", {"file": foto("red"), "severita": "bassa"}, format="multipart")
        self.assertFalse(r.json()["vietato"])
        with contesto_cliente(self.a.id):
            self.assertFalse(Contenuto.objects.exists())


INDICE = {
    "aggiornato": "2026-10-23T10:00:00+00:00",
    "canali": {"Rai1.it": ["IT", 0, 0, "Rai 1"], "Spinto.us": ["US", 1, 0, "Spinto"], "Chiuso.it": ["IT", 0, 1, "Chiuso"]},
    "nera": {"Nero.us": "nsfw", "Diritti.it": "dmca"},
    "url": {"https://flussi.esempio.it/rai1.m3u8": "Rai1.it"},
    "paesi": {"italy": "IT"},
    "nomi": {"rai1|IT": ["Rai1.it"]},
}


class BolliniTest(ConFile):
    def test_bollino_dei_canali(self):
        valuta = lambda **c: canali.valuta(c, INDICE)["bollino"]  # noqa: E731
        self.assertEqual(valuta(nome="Rai 1", tvg_id="Rai1.it@SD"), "riconosciuto")
        self.assertEqual(valuta(nome="Senza id", url="https://flussi.esempio.it/rai1.m3u8"), "riconosciuto")
        self.assertEqual(valuta(nome="Rai 1 HD Ⓖ", gruppo="Italy"), "riconosciuto")  # per nome nel paese
        self.assertEqual(valuta(nome="Chiuso", tvg_id="Chiuso.it"), "riconosciuto")
        self.assertEqual(valuta(nome="Qualcosa", tvg_id="Spinto.us"), "vietato")
        self.assertEqual(valuta(nome="Qualcosa", tvg_id="Nero.us"), "vietato")
        self.assertEqual(valuta(nome="Hot XXX", gruppo=""), "vietato")
        self.assertEqual(valuta(nome="Canale 18+", gruppo=""), "vietato")
        self.assertEqual(valuta(nome="Film", gruppo="Adult"), "vietato")
        self.assertEqual(valuta(nome="La Sexta", gruppo="Spain"), "sconosciuto")  # «Sexta» non è «sex»
        self.assertEqual(valuta(nome="TV Locale", gruppo="Italy"), "sconosciuto")
        self.assertEqual(valuta(nome="Diritti", tvg_id="Diritti.it"), "sconosciuto")

    @mock.patch.object(canali, "indice", return_value=INDICE)
    def test_import_con_il_filtro_attivo(self, _indice):
        with contesto_cliente(self.a.id):
            FiltroContenuti.objects.create(cliente=self.a, dirette=True)
        self.come(self.admin_a)
        rai = {"nome": "Rai 1", "url": "https://flussi.esempio.it/rai1.m3u8"}
        locale = {"nome": "TV Locale", "url": "https://locale.esempio.it/live.m3u8", "gruppo": "Italy"}
        spinto = {"nome": "Spinto", "url": "https://spinto.esempio.us/live.m3u8", "tvg_id": "Spinto.us"}
        manda = lambda canali, **altro: self.client.post(  # noqa: E731
            "/api/contenuti/dirette/", {"canali": canali, "autorizzazione": True, **altro}, format="json")
        r = manda([rai, spinto])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Spinto", r.json()["canali"])
        self.assertEqual(manda([rai, locale]).status_code, 400)  # lo sconosciuto va confermato
        self.come(self.user_a)
        self.assertEqual(manda([locale], conferma_sconosciuti=True).status_code, 403)
        self.come(self.admin_a)
        r = manda([rai, locale], conferma_sconosciuti=True)
        self.assertEqual(r.status_code, 201, r.content)
        with contesto_cliente(self.a.id):
            dirette = {c.nome: c for c in Contenuto.objects.filter(tipo=Tipo.DIRETTA)}
        self.assertEqual(dirette["Rai 1"].controllo, Controllo.ATTESA)
        self.assertEqual(dirette["TV Locale"].controllo_esito["canale"]["bollino"], "sconosciuto")


@mock.patch.object(filtro, "disponibile", return_value=True)
class DiretteSorvegliateTest(ConFile):
    def pubblica(self, diretta_id):
        campagna = self.client.post("/api/campagne/", {
            "nome": "Diretta", "data_inizio": "2026-01-01", "data_fine": "2026-12-31",
            "monitor": [str(self.mon_a_milano.id)], "durata": 8,
        }, format="json").json()
        r = self.client.post("/api/promozioni/", {
            "campagna": campagna["id"], "nome": "In diretta", "data_inizio": "2026-01-01", "data_fine": "2026-12-31",
            "contenuti": [diretta_id],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def manifest(self):
        with contesto_cliente(self.a.id):
            return palinsesto.manifest(Monitor.objects.get(id=self.mon_a_milano.id))

    def test_in_onda_solo_dopo_il_controllo_e_mai_se_bloccata(self, _disponibile):
        with contesto_cliente(self.a.id):
            FiltroContenuti.objects.create(cliente=self.a, dirette=True, severita_dirette="media")
        self.come(self.admin_a)
        with mock.patch.object(canali, "indice", return_value=INDICE):
            diretta = self.client.post("/api/contenuti/dirette/", {
                "canali": [{"nome": "Rai 1", "url": "https://flussi.esempio.it/rai1.m3u8"}], "autorizzazione": True,
            }, format="json").json()[0]["id"]
        self.pubblica(diretta)
        self.assertNotIn(diretta, self.manifest()["contenuti"])  # in verifica

        pulita = filtro.Esito(vietato=False, punteggio=0.02, fotogrammi=6)
        with mock.patch.object(filtro, "controlla_diretta", return_value=pulita), mock.patch.object(canali, "aggiorna", return_value={}):
            self.assertEqual(filtro.controlla_dirette()["controllate"], 1)
        self.assertIn(diretta, self.manifest()["contenuti"])
        with contesto_cliente(self.a.id):
            self.assertEqual(Contenuto.objects.get(id=diretta).controllo_esito["canale"]["bollino"], "riconosciuto")

        # Al ricontrollo compare del nudo: la diretta sparisce dagli schermi, per sempre.
        with contesto_cliente(self.a.id):
            Contenuto.objects.filter(id=diretta).update(controllo_il="2026-01-01T00:00:00+00:00")
        sporca = filtro.Esito(vietato=True, punteggio=0.97, fotogrammi=2)
        with mock.patch.object(filtro, "controlla_diretta", return_value=sporca), mock.patch.object(canali, "aggiorna", return_value={}):
            self.assertEqual(filtro.controlla_dirette()["bloccate"], 1)
        self.assertNotIn(diretta, self.manifest()["contenuti"])
        self.assertEqual(self.manifest()["playlist"], {k: [] for k in self.manifest()["playlist"]})
        # Con l'immagine di riserva dello schermo, al posto della diretta va quella, per la stessa durata.
        riserva = self.carica(foto("orange", "logo.png"), uso="riserva").json()["id"]
        with contesto_cliente(self.a.id):
            Monitor.objects.filter(id=self.mon_a_milano.id).update(immagine_riserva_id=riserva)
        sequenza = next(iter(self.manifest()["playlist"].values()))
        self.assertEqual([(v["contenuto"], v["durata"], v["riserva"]) for v in sequenza], [(riserva, 300, True)])
        with contesto_cliente(self.a.id):
            self.assertTrue(EventoAudit.objects.filter(azione="diretta_bloccata_filtro").exists())
            Contenuto.objects.filter(id=diretta).update(controllo_il="2026-01-01T00:00:00+00:00")
        with mock.patch.object(filtro, "controlla_diretta", return_value=pulita) as controllo:
            filtro.controlla_dirette()
        controllo.assert_not_called()  # bloccata non si ricontrolla
        # Anche spegnendo il filtro, una diretta bloccata non torna in onda.
        with contesto_cliente(self.a.id):
            FiltroContenuti.objects.update(dirette=False)
        self.assertNotIn(diretta, self.manifest()["contenuti"])

    def test_irraggiungibile_dopo_tre_tentativi(self, _disponibile):
        with contesto_cliente(self.a.id):
            FiltroContenuti.objects.create(cliente=self.a, dirette=True)
            diretta = Contenuto.objects.create(nome="Locale", tipo=Tipo.DIRETTA, url="https://x.esempio.it/a.m3u8", controllo=Controllo.ATTESA)
        errore = filtro.DirettaIrraggiungibile("nessun fotogramma ricevuto")
        with mock.patch.object(filtro, "controlla_diretta", side_effect=errore), mock.patch.object(canali, "aggiorna", return_value={}):
            for _ in range(3):
                filtro.controlla_dirette()
        with contesto_cliente(self.a.id):
            diretta.refresh_from_db()
        self.assertEqual((diretta.controllo, diretta.controllo_esito["tentativi"]), (Controllo.NON_VERIFICABILE, 3))

    def test_dirette_senza_filtro_come_prima(self, _disponibile):
        self.come(self.admin_a)
        diretta = self.client.post("/api/contenuti/dirette/", {
            "canali": [{"nome": "Uno", "url": "https://flussi.esempio.it/uno.m3u8"}], "autorizzazione": True,
        }, format="json").json()[0]["id"]
        self.pubblica(diretta)
        self.assertIn(diretta, self.manifest()["contenuti"])


@unittest.skipUnless(filtro.MODELLO.exists(), "modello CLIP non scaricato (plugin/modello/scarica_modello.py)")
class ModelloVeroTest(ConFile):
    def test_immagini_qualunque_non_sono_nudo(self):
        # Sfondi pieni (anche color pelle) e una dissolvenza: non sono nudo nemmeno a severità alta.
        for colore in ("orange", "white", "black", "#f1c27d", "#ffe0bd"):
            uscita = io.BytesIO()
            Image.new("RGB", (300, 200), colore).save(uscita, "PNG")
            self.assertFalse(filtro.controlla_immagine(io.BytesIO(uscita.getvalue()), "alta").vietato)


class SorveglianzaTest(ConFile):
    def test_in_onda_si_ricontrolla_di_continuo_le_altre_ogni_qualche_ora(self):
        from datetime import timedelta

        from django.utils import timezone

        adesso = timezone.now()
        with contesto_cliente(self.a.id):
            diretta = Contenuto(nome="Uno", tipo=Tipo.DIRETTA, url="https://x.esempio.it/a.m3u8", controllo=Controllo.OK)
        diretta.controllo_il = adesso - timedelta(minutes=3)
        self.assertTrue(filtro.da_controllare(diretta, "alta", in_onda=True, adesso=adesso))  # ogni 2 minuti
        self.assertFalse(filtro.da_controllare(diretta, "media", in_onda=True, adesso=adesso))  # ogni 5
        self.assertFalse(filtro.da_controllare(diretta, "alta", in_onda=False, adesso=adesso))  # ogni 6 ore
        diretta.controllo_il = adesso - timedelta(hours=7)
        self.assertTrue(filtro.da_controllare(diretta, "bassa", in_onda=False, adesso=adesso))
        diretta.controllo = Controllo.BLOCCATA
        self.assertFalse(filtro.da_controllare(diretta, "alta", in_onda=True, adesso=adesso))


class PercorsoModelloTest(ConFile):
    def test_se_non_e_nell_immagine_si_usa_quello_scaricato_all_avvio(self):
        from pathlib import Path

        scaricato = Path(self.media) / "plugin" / "clip_visione.onnx"
        with mock.patch.object(filtro, "MODELLO", Path(self.media) / "assente" / "clip_visione.onnx"):
            self.assertEqual(filtro.percorso_modello(), filtro.MODELLO)  # nessuno dei due: quello dell'immagine
            scaricato.parent.mkdir(parents=True, exist_ok=True)
            scaricato.write_bytes(b"x")
            self.assertEqual(filtro.percorso_modello(), scaricato)
