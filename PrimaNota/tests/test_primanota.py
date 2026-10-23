import json
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings

from incarichi.services import baserow_client, baserow_layer
from primanota import sysspy
from primanota.models import Condivisione, DocumentoSysSpy, FileSysSpy, Nota, RegolaDocumento
from primanota.services import importazione

DATI = Path(__file__).resolve().parent / "dati"
CAMPI_NEGOZIO = {"codice": "field_8142", "descrizione": "field_8143", "attivo": "field_8144"}


class BaserowFinto:
    """La tabella Baserow delle scansioni Prima Nota, in memoria, con i campi per nome."""

    def __init__(self):
        self.righe = {}
        self.prossimo = 1

    def __call__(self, metodo, url, params=None, json=None, **kwargs):
        percorso = urlparse(url).path.rstrip("/").split("/")
        risposta = mock.Mock(ok=True, status_code=200, content=b"x")
        if percorso[-1].isdigit() and percorso[-2] != "table":
            riga_id = int(percorso[-1])
            if metodo == "GET":
                dati = self.righe[riga_id]
            elif metodo == "PATCH":
                self.righe[riga_id].update(self._link(json))
                dati = self.righe[riga_id]
            else:
                del self.righe[riga_id]
                dati, risposta.content = {}, b""
        elif metodo == "POST":
            riga = {"id": self.prossimo, **self._link(json)}
            riga["Documento"] = [{"url": f"/media/{f['name']}", "visible_name": f["visible_name"], "is_image": False}
                                 for f in json["Documento"]]
            self.righe[self.prossimo] = riga
            self.prossimo += 1
            dati = riga
        else:
            righe = sorted(self.righe.values(), key=lambda r: (r["Data Documento"], r["id"]), reverse=True)
            negozio = (params or {}).get("filter__Negozio__link_row_has")
            if negozio:
                righe = [r for r in righe if r["Negozio"][0]["id"] == int(negozio)]
            dati = {"results": righe, "next": None}
        risposta.json.return_value = dati
        return risposta

    @staticmethod
    def _link(dati):
        # Baserow restituisce i link come [{"id":..,"value":..}].
        out = dict(dati)
        for campo in ("Negozio", "Caricato Da", "Lavorato Da", "Versamento Lavorato Da"):
            if campo in out:
                out[campo] = [{"id": i, "value": f"utente {i}"} for i in out[campo]]
        return out


def negozio(id_, codice, descrizione):
    return {"id": id_, CAMPI_NEGOZIO["codice"]: codice, CAMPI_NEGOZIO["descrizione"]: descrizione,
            CAMPI_NEGOZIO["attivo"]: True}


def utente(id_, tipo, negozio_id=None, ruolo="Dipendente", menu=True):
    return {"id": id_, "field_2250": f"Utente {id_}", "field_2253": {"value": ruolo}, "field_8146": {"value": tipo},
            "field_8147": [{"id": negozio_id, "value": "x"}] if negozio_id else [], "field_8166": True,
            "field_9000": menu}


class Base(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.archivio = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.archivio)
        override = override_settings(PRIMANOTA_ARCHIVIO_DIR=self.archivio)
        override.enable()
        self.addCleanup(override.disable)

        from scansioni.services import baserow_scansioni
        baserow_scansioni._NEGOZI_CACHE.update(expires_at=0, rows=[], by_id={})
        baserow_client.NEGOZI[:] = [negozio(10, "5048", "Motta S. Anastasia"), negozio(11, "5050", "Catania")]
        baserow_layer.UTENTI.clear()
        baserow_layer.UTENTI.update({
            "pv@x": utente(1, "Negozio", negozio_id=10),
            "altro_pv@x": utente(4, "Negozio", negozio_id=11),
            "ufficio@x": utente(2, "Ufficio"),
            "direttore@x": utente(3, "Ufficio", ruolo="Direttore"),
            "admin@x": utente(6, "Ufficio", ruolo="Amministratore", menu=False),
            "nomenu@x": utente(5, "Ufficio", menu=False),
        })
        self.baserow = BaserowFinto()
        patcher = mock.patch("primanota.services.baserow_primanota.requests.request", self.baserow)
        patcher.start()
        self.addCleanup(patcher.stop)

    def client_per(self, email):
        c = Client(enforce_csrf_checks=False)
        sessione = c.session
        sessione["baserow_user_email"] = email
        sessione.save()
        c.email = email
        return c

    @staticmethod
    def pdf(nome="scan.pdf"):
        return SimpleUploadedFile(nome, b"%PDF-1.4", content_type="application/pdf")

    def carica(self, client, tipo, giorno="2026-05-28", cassa=None):
        """Una scansione già in Baserow, caricata dal negozio del client (il modulo vuole la giornata intera)."""
        from primanota.services.baserow_primanota import crea_scansione
        user = baserow_layer.UTENTI[client.email]
        return crea_scansione(user, user["field_8147"][0]["id"], giorno, tipo, self.pdf(), cassa=cassa)

    def scansione_sede(self, tipo, giorno="2026-05-28", cassa=None):
        return self.carica(self.client_per("pv@x"), tipo, giorno, cassa)

    def importa_fixture(self):
        cartella = Path(self.archivio) / "share"
        cartella.mkdir()
        shutil.copy(DATI / "SysSpy.20260528.1", cartella)
        cond = Condivisione.objects.create(negozio_id=10, codice_negozio="5048", percorso=str(cartella))
        return cond, cartella, importazione.importa_condivisione(cond)


class TestSysSpy(TestCase):
    def setUp(self):
        self.file = sysspy.analizza("SysSpy.20260528.1", (DATI / "SysSpy.20260528.1").read_bytes())
        self.assertEqual(len(self.file["giornate"]), 1)
        self.a = self.file["giornate"][0]

    def test_data_cassa_negozio_dal_nome_e_dal_contenuto(self):
        self.assertEqual((self.a["data"], self.file["cassa"], self.file["codice_negozio"]), (date(2026, 5, 28), 1, "5048"))

    def test_chiusura_pos_con_importo_a_capo(self):
        # Alcuni terminali stampano «TOTALE POS» e sotto «EUR 18,00» (5034 cassa 1).
        testo = (DATI / "SysSpy.20260528.1").read_text(encoding="latin-1")
        testo = testo.replace("9832     TOTALE POS EUR     18,00", "9832     TOTALE POS\n9832     EUR                18,00")
        testo = testo.replace("9832     TOTALE HOST EUR    18,00", "9832     TOTALE HOST\n9832     EUR                18,00")
        self.assertNotIn("TOTALE POS EUR", testo)
        g = sysspy.analizza("SysSpy.20260528.1", testo.encode("latin-1"))["giornate"][0]
        self.assertEqual([(p["totale_pos"], p["totale_host"], p["esito"]) for p in g["chiusure_pos"]],
                         [(Decimal("18.00"), Decimal("18.00"), "ESEGUITA")])
        self.assertEqual(g["totale_pos"], Decimal("18.00"))

    def test_testo_senza_le_prime_quattro_colonne(self):
        self.assertNotIn("9949", self.a["testo"])
        self.assertIn(" TOTALE GIORNALIERO                       18,00", self.a["testo"].splitlines())

    def test_chiusure_e_valori(self):
        v = self.a["valori_fiscali"]
        self.assertEqual(v["totale_giornaliero"], Decimal("18.00"))
        self.assertEqual(v["corrisp_non_riscosso"], Decimal("18.00"))
        self.assertEqual(v["num_scontrini_fiscali"], 4)   # 3 scontrini + la chiusura
        self.assertEqual(self.a["totale_pos"], Decimal("18.00"))
        self.assertTrue(self.a["chiusura_fiscale"]["testo"].lstrip().startswith("TO.CAL. SRL"))
        pos = self.a["chiusure_pos"][0]["testo"]
        self.assertTrue(pos.lstrip().startswith("NON  FISCALE"))
        self.assertIn("CASSA 1 NEGOZIO 5048", pos)  # comprende il foglio C.C.D. del cassiere

    def test_scontrini_abortiti_storni_e_pos_negati(self):
        docs = {d["numero"]: d for d in self.a["scontrini"]}
        self.assertEqual(list(docs), ["1104-0001", "1104-0002", "1104-0003"])
        self.assertTrue(docs["1104-0002"]["abortito"])
        self.assertEqual(docs["1104-0003"]["storni"], 1)
        self.assertEqual(len(self.a["pos_negate"]), 1)
        # L'abortito non entra nella somma: torna con il totale giornaliero.
        self.assertEqual(self.a["totale_scontrini"], Decimal("18.00"))

    def test_pagamenti(self):
        # Carta Credito 18,00; contanti 0 dello scontrino con storno: non compare.
        self.assertEqual(self.a["pagamenti"], {"Carta Credito": Decimal("18.00")})

    def test_file_con_due_giornate(self):
        # Come il PV 5034: il file del 13 contiene anche la giornata del 12 (file del 12 mancante).
        testo = (DATI / "SysSpy.20260528.1").read_bytes().decode("utf-8-sig").replace("28/05/2026", "12/10/2026")
        secondo = "\r\n".join(r.replace("12/10/2026", "13/10/2026") for r in testo.splitlines())
        f = sysspy.analizza("SysSpy.20261013.1", (testo + secondo).encode())
        self.assertEqual([g["data"] for g in f["giornate"]], [date(2026, 10, 12), date(2026, 10, 13)])
        self.assertEqual([g["valori_fiscali"]["totale_giornaliero"] for g in f["giornate"]], [Decimal("18.00")] * 2)
        self.assertEqual(f["data_file"], date(2026, 10, 13))

    def test_ristampa_non_sposta_la_giornata(self):
        righe = sysspy.righe("9832 01/01/2020 10:00   DOC.1-1\r\n9899 28/05/2026 13:09\r\n")
        self.assertEqual([g for g, _ in sysspy.dividi_per_data(righe, date(2026, 5, 28))], [date(2026, 5, 28)])

    def test_importi_con_separatore_migliaia(self):
        self.assertEqual(sysspy.importo("TOTALE POS EUR  2.400,30"), Decimal("2400.30"))


class TestImportazione(Base):
    def test_archivia_e_salta_i_file_gia_presenti(self):
        cond, cartella, stato = self.importa_fixture()
        self.assertEqual((stato["importati"], stato["errori"]), (1, 0), stato)
        f = FileSysSpy.objects.get()
        self.assertEqual((f.data, f.data_file, f.cassa, f.totale_pos, f.pagato_pos),
                         (date(2026, 5, 28), date(2026, 5, 28), 1, Decimal("18.00"), Decimal("18.00")))
        self.assertTrue(f.quadrato)
        self.assertTrue(Path(f.percorso_archivio).is_file())
        self.assertIn("/5048/2026/05/28/cassa_1/", f.percorso_archivio)
        self.assertNotIn("9832", importazione.leggi_testo(f))
        self.assertEqual(sorted(f.documenti.values_list("tipo", flat=True)),
                         [DocumentoSysSpy.ABORTITO, DocumentoSysSpy.POS_NEGATO, DocumentoSysSpy.STORNO])
        self.assertEqual(importazione.importa_condivisione(cond)["saltati"], 1)

    def test_file_modificato_sostituisce_il_precedente(self):
        cond, cartella, _ = self.importa_fixture()
        file = cartella / "SysSpy.20260528.1"
        file.write_bytes(file.read_bytes() + b"9999 \r\n")
        self.assertEqual(importazione.importa_condivisione(cond)["importati"], 1)
        self.assertEqual(FileSysSpy.objects.count(), 1)
        self.assertEqual(DocumentoSysSpy.objects.count(), 3)

    def test_password_cifrata(self):
        self.assertEqual(importazione.decifra(importazione.cifra("segreta")), "segreta")


class TestPagine(Base):
    def test_accesso(self):
        self.assertEqual(Client().get("/primanota/admin/").status_code, 302)
        self.assertEqual(self.client_per("nomenu@x").get("/primanota/admin/").status_code, 403)
        self.assertRedirects(self.client_per("pv@x").get("/primanota/admin/"), "/primanota/upload/", fetch_redirect_response=False)
        self.assertEqual(self.client_per("ufficio@x").get("/primanota/condivisioni/").status_code, 403)
        self.assertEqual(self.client_per("direttore@x").get("/primanota/condivisioni/").status_code, 200)
        # L'Amministratore entra anche senza la casella Menu_PrimaNota.
        self.assertEqual(self.client_per("admin@x").get("/primanota/condivisioni/").status_code, 200)

    def test_il_negozio_salva_la_giornata_solo_con_gli_obbligatori(self):
        from primanota.models import RegolaDocumento
        cond, cartella, _ = self.importa_fixture()   # 28/05: SysSpy con una sospensione e nessun reso
        # Una transazione abortita vera (non una sospensione) sulla cassa 2.
        (cartella / "SysSpy.20260528.2").write_text(sysspy_abortita("28/05/2026", 2))
        importazione.importa_condivisione(cond)
        RegolaDocumento.objects.create(tipo_documento="Chiusure POS bancari", obbligo=RegolaDocumento.FACOLTATIVO)
        pv = self.client_per("pv@x")
        pagina = pv.get("/primanota/upload/", {"data": "2026-05-28"})
        stati = {v["tipo"]["id"]: (v["stato"], v["manca"]) for v in pagina.context["voci"]}
        self.assertEqual(stati, {"Chiusura fiscale": ("obbligatoria", True), "Chiusure POS bancari": ("non_richiesta", False),
                                 "Resi": ("non_richiesta", False), "Transazioni abortite": ("obbligatoria", True),
                                 "Fatture spese del giorno": ("in_attesa", False),   # prima nota non consultabile
                                 "Versamenti contante": ("obbligatoria", True)})
        self.assertContains(pagina, 'name="documento_pos" class="documento" accept=".pdf,image/*"\n                               disabled')
        # Senza tutti gli obbligatori non si salva niente.
        r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "documento_fiscale": self.pdf(),
                                           "documento_versamenti": self.pdf()})
        self.assertContains(r, "Mancano gli allegati obbligatori: Transazioni abortite")
        self.assertEqual(self.baserow.righe, {})
        # Una voce non prevista non si allega.
        r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "documento_fiscale": self.pdf(),
                                           "documento_abortite": self.pdf(), "documento_versamenti": self.pdf(),
                                           "documento_pos": self.pdf()})
        self.assertContains(r, "non previsti per questa giornata: Chiusure POS bancari")
        self.assertEqual(self.baserow.righe, {})
        r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "documento_fiscale": self.pdf(),
                                           "cassa_fiscale": "1", "documento_abortite": self.pdf(),
                                           "documento_versamenti": self.pdf(), "note": "ok"})
        self.assertRedirects(r, "/primanota/upload/?uploaded=1&data=2026-05-28", fetch_redirect_response=False)
        righe = sorted((r["Tipo Documento"], r["Cassa"], r["Negozio"][0]["id"]) for r in self.baserow.righe.values())
        self.assertEqual(righe, [("Chiusura fiscale", 1, 10), ("Transazioni abortite", None, 10), ("Versamenti contante", None, 10)])
        # Con gli obbligatori già caricati si può aggiungere un documento da solo.
        self.assertFalse(any(v["manca"] for v in pv.get("/primanota/upload/", {"data": "2026-05-28"}).context["voci"]))
        r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "documento_versamenti": self.pdf()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.baserow.righe), 4)

    def test_senza_sysspy_le_voci_che_ne_dipendono_restano_caricabili(self):
        pv = self.client_per("pv@x")
        stati = {v["tipo"]["id"]: v["stato"] for v in pv.get("/primanota/upload/", {"data": "2026-05-20"}).context["voci"]}
        self.assertEqual((stati["Resi"], stati["Chiusura fiscale"]), ("in_attesa", "obbligatoria"))

    def test_giornata_affianca_scansioni_e_sysspy(self):
        self.importa_fixture()
        self.scansione_sede("Chiusure POS bancari")
        r = self.client_per("ufficio@x").get("/primanota/giornata/10/2026-05-28/")
        self.assertContains(r, "TOTALE HOST EUR")             # chiusura POS dal SysSpy
        self.assertContains(r, "TOTALE GIORNALIERO")          # chiusura fiscale dal SysSpy
        # L'abortita della fixture è una sospensione dello scontrino: non è tra le abortite da scansionare.
        abortite = next(x for x in r.context["sezioni"] if x["tipo"]["id"] == "Transazioni abortite")
        self.assertEqual((abortite["anteprime"], abortite["obbligatoria"]), ([], False))
        self.assertContains(r, "✓ POS")
        self.assertContains(r, "scan.pdf")
        self.assertContains(r, "Mancante")                    # gli altri generi non sono stati caricati

    def test_versamento_ha_un_lavorato_separato(self):
        self.carica(self.client_per("pv@x"), "Versamenti contante")
        self.carica(self.client_per("pv@x"), "Resi")
        uff = self.client_per("ufficio@x")
        r = uff.post("/primanota/update-lavorato/1/", json.dumps({"lavorato": True, "versamento": True}),
                     content_type="application/json")
        self.assertEqual(r.status_code, 200)
        riga = self.baserow.righe[1]
        self.assertTrue(riga["Versamento Lavorato"])
        self.assertFalse(riga["Lavorato"])
        self.assertEqual(riga["Versamento Lavorato Da"][0]["id"], 2)
        r = uff.post("/primanota/update-lavorato/2/", json.dumps({"lavorato": True, "versamento": True}),
                     content_type="application/json")
        self.assertEqual(r.status_code, 400)  # il flag versamento non vale per i resi

    def test_il_negozio_non_elimina_documenti_lavorati_o_di_altri(self):
        self.carica(self.client_per("pv@x"), "Resi")
        self.baserow.righe[1]["Lavorato"] = True
        self.assertEqual(self.client_per("pv@x").post("/primanota/delete/1/").status_code, 400)
        self.assertEqual(self.client_per("altro_pv@x").post("/primanota/delete/1/").status_code, 403)
        self.assertEqual(self.client_per("ufficio@x").post("/primanota/delete/1/").status_code, 200)
        self.assertNotIn(1, self.baserow.righe)

    def test_note_dal_negozio_e_chiusura_in_ufficio(self):
        pv = self.client_per("pv@x")
        # La nota si scrive sotto gli allegati e si salva con «Salva», anche senza allegati.
        pagina = pv.get("/primanota/upload/", {"data": "2026-05-28"})
        self.assertEqual([v for _, v in pagina.context["tipi_nota"]],
                         ["Nessuna", "Nota sul versamento", "Nota per Anomalia Tecnica", "Richiesta Contatto"])
        # Con «Nessuna» il testo non si salva.
        r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "tipo_nota": "", "note": "ignorata"})
        self.assertContains(r, "scegli il tipo di nota")
        self.assertFalse(Nota.objects.exists())
        r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "tipo_nota": "RICHIESTA_CONTATTO", "note": "Chiamatemi"})
        self.assertEqual(r.status_code, 302)
        nota = Nota.objects.get()
        self.assertEqual((nota.tipo, nota.data), ("RICHIESTA_CONTATTO", date(2026, 5, 28)))
        self.assertEqual((nota.negozio_id, nota.creata_da), (10, "Utente 1"))
        uff = self.client_per("ufficio@x")
        self.assertContains(uff.get("/primanota/note/"), "Chiamatemi")
        uff.post(f"/primanota/note/{nota.id}/chiudi/")
        nota.refresh_from_db()
        self.assertTrue(nota.chiusa)
        self.assertEqual(nota.chiusa_da, "Utente 2")

    def test_monitor(self):
        oggi = date.today()
        ieri = (oggi - timedelta(days=1)).isoformat() if oggi.day > 1 else oggi.isoformat()
        pv = self.client_per("pv@x")
        self.scansione_sede("Chiusura fiscale", giorno=ieri)
        self.carica(pv, "Versamenti contante", giorno=ieri)
        Nota.objects.create(negozio_id=10, data=ieri, tipo=Nota.ANOMALIA, testo="x", creata_da="x")
        r = self.client_per("ufficio@x").get("/primanota/monitor/")
        self.assertEqual(r.status_code, 200)
        riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
        cella = next(c for c in riga["cells"] if c["date"] == ieri)
        # Il monitor generale non conta i versamenti: hanno un monitor proprio.
        self.assertEqual((cella["state"], cella["total"], cella["note_aperte"]), ("incomplete", 1, 1))
        r = self.client_per("ufficio@x").get("/primanota/versamenti/monitor/")
        riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
        cella_v = next(c for c in riga["cells"] if c["date"] == ieri)
        self.assertEqual((cella_v["state"], cella_v["total"]), ("pending", 1))
        self.assertIn("/primanota/versamenti/?negozio=10", cella_v["detail_url"])
        self.assertEqual(cella["mancanti"], ["Chiusure POS bancari"])
        self.assertEqual(cella["detail_url"], f"/primanota/giornata/10/{ieri}/")
        altro = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 11)
        self.assertEqual(next(c for c in altro["cells"] if c["date"] == ieri)["state"], "missing")

    def test_condivisione_password_vuota_resta_invariata(self):
        d = self.client_per("admin@x")
        d.post("/primanota/condivisioni/", {"negozio_id": 10, "percorso": "/mnt/x", "password": "segreta", "attiva": "on"})
        d.post("/primanota/condivisioni/", {"negozio_id": 10, "percorso": "/mnt/y", "password": "", "attiva": "on"})
        c = Condivisione.objects.get()
        self.assertEqual((c.percorso, c.codice_negozio, importazione.decifra(c.password_cifrata)), ("/mnt/y", "5048", "segreta"))

    def test_archivio_e_ricerca_nel_testo(self):
        self.importa_fixture()
        uff = self.client_per("ufficio@x")
        r = uff.get("/primanota/sysspy/", {"data_da": "2026-05-28", "testo": "powerade"})
        self.assertEqual(len(r.context["risultati"]), 1)
        f = FileSysSpy.objects.get()
        self.assertContains(uff.get(f"/primanota/sysspy/{f.id}/"), "OPERAZIONE ABORTITA")
        self.assertEqual(uff.get(f"/primanota/sysspy/{f.id}/scarica/").status_code, 200)
        r = uff.get("/primanota/sysspy/", {"data_da": "2026-01-01", "data_a": "2026-05-28", "testo": "x"})
        self.assertIn("al massimo", r.context["error"])


class TestMenu(Base):
    def test_voce_di_menu_solo_per_chi_e_abilitato(self):
        from django.template import Context, Template
        t = Template("{% load primanota_menu %}{% primanota_visibile utente as v %}{{ v }}")
        self.assertEqual(t.render(Context({"utente": baserow_layer.UTENTI["pv@x"]})), "True")
        self.assertEqual(t.render(Context({"utente": baserow_layer.UTENTI["nomenu@x"]})), "False")
        self.assertEqual(t.render(Context({"utente": baserow_layer.UTENTI["admin@x"]})), "True")
        # Senza la casella Menu_PrimaNota non basta essere abilitati a Scansioni PV.
        with override_settings(BASEROW_UTENTE_MENU_PRIMANOTA_FIELD=""), \
                mock.patch("primanota.services.accesso.campo_menu_primanota", return_value=None):
            self.assertEqual(t.render(Context({"utente": baserow_layer.UTENTI["pv@x"]})), "False")
        self.assertEqual(t.render(Context({"utente": None})), "False")


class TestPianificazione(Base):
    def setUp(self):
        super().setUp()
        from primanota.models import Pianificazione
        self.piano = Pianificazione.corrente()
        self.piano.orari = "20:30, 06:00"
        self.piano.save()
        self.importa = mock.patch("primanota.services.importazione.importa_tutte",
                                  return_value={"messaggio": "ok"}).start()
        self.addCleanup(mock.patch.stopall)

    def ora(self, testo):
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.fromisoformat(testo).replace(tzinfo=ZoneInfo("Europe/Rome"))

    def test_orari(self):
        esegui = importazione.esegui_pianificazione
        esegui(self.ora("2026-10-19 07:00"))              # recupera le 06:00 di oggi
        self.assertEqual(self.importa.call_count, 1)
        self.assertEqual(esegui(self.ora("2026-10-19 12:00")), "niente da fare")
        esegui(self.ora("2026-10-19 20:35"))              # 20:30
        esegui(self.ora("2026-10-19 20:40"))              # già fatta
        self.assertEqual(self.importa.call_count, 2)
        self.assertEqual(self.importa.call_args.kwargs["completa"], False)

    def test_ricostruzione_settimanale(self):
        self.piano.ricostruzione_attiva = True
        self.piano.ricostruzione_giorno = 6   # domenica
        self.piano.ricostruzione_ora = "02:00"
        self.piano.save()
        importazione.esegui_pianificazione(self.ora("2026-10-25 02:05"))   # domenica
        self.assertTrue(self.importa.call_args.kwargs["completa"])
        importazione.esegui_pianificazione(self.ora("2026-10-25 06:05"))
        self.assertFalse(self.importa.call_args.kwargs["completa"])

    def test_disattivata(self):
        self.piano.attiva = False
        self.piano.save()
        self.assertEqual(importazione.esegui_pianificazione(self.ora("2026-10-19 21:00")), "pianificazione disattivata")

    def test_salvataggio_orari_solo_amministratore(self):
        dati = {"azione": "pianificazione", "attiva": "on", "orari": "21:15,6:00", "ricostruzione_giorno": "0",
                "ricostruzione_ora": "03:00"}
        self.assertEqual(self.client_per("ufficio@x").post("/primanota/condivisioni/", dati).status_code, 403)
        self.client_per("admin@x").post("/primanota/condivisioni/", dati)
        self.piano.refresh_from_db()
        self.assertEqual(self.piano.orari, "06:00, 21:15")
        r = self.client_per("admin@x").post("/primanota/condivisioni/", {**dati, "orari": "25:00"})
        self.assertContains(r, "Orari non validi")


class TestImportaTutti(Base):
    def test_importa_tutti_i_negozi(self):
        cond, cartella, _ = self.importa_fixture()
        Condivisione.objects.create(negozio_id=11, codice_negozio="5050", percorso="/non/esiste")
        stato = importazione.importa_tutte(completa=True)
        self.assertEqual((stato["negozi"], stato["negozi_fatti"], stato["importati"]), (2, 2, 1))
        self.assertIn("5050: errore", "\n".join(stato["esiti"]))
        self.assertEqual(self.client_per("ufficio@x").post("/primanota/condivisioni/importa-tutti/").status_code, 403)


class TestDivisioneEControlli(Base):
    def test_giornata_recuperata_dal_file_del_giorno_dopo(self):
        cartella = Path(self.archivio) / "share"
        cartella.mkdir()
        testo = (DATI / "SysSpy.20260528.1").read_bytes().decode("utf-8-sig")
        giorno12 = testo.replace("28/05/2026", "12/10/2026")
        giorno13 = "\r\n".join(r.replace("12/10/2026", "13/10/2026") for r in giorno12.splitlines())
        (cartella / "SysSpy.20261013.1").write_bytes((giorno12 + giorno13).encode())
        cond = Condivisione.objects.create(negozio_id=10, codice_negozio="5048", percorso=str(cartella))
        importazione.importa_condivisione(cond)
        dodici = FileSysSpy.objects.get(data=date(2026, 10, 12))
        self.assertTrue(dodici.da_altro_file)
        self.assertEqual(FileSysSpy.objects.count(), 2)
        r = self.client_per("ufficio@x").get("/primanota/giornata/10/2026-10-12/")
        self.assertContains(r, "dal file del 13/10")
        self.assertContains(r, "TOTALE GIORNALIERO")

    def test_rielabora_archivio(self):
        self.importa_fixture()
        f = FileSysSpy.objects.get()
        FileSysSpy.objects.filter(pk=f.pk).update(pagamenti={}, data_file=None, versione_analisi=0)
        self.assertEqual(importazione.rielabora_archivio(processi=1), {"file": 1, "errori": 0})
        # Riprende da dove era arrivata: i file già con la versione attuale non si rifanno.
        self.assertEqual(importazione.rielabora_archivio(processi=1), {"file": 0, "errori": 0})
        f = FileSysSpy.objects.get()
        self.assertEqual((f.data_file, f.pagamenti), (date(2026, 5, 28), {"Carta Credito": "18.00"}))

    def test_spiegazione_differenza_pos(self):
        self.importa_fixture()
        f = FileSysSpy.objects.get()
        f.totale_pos = Decimal("1212.00")  # il terminale ha incassato più di cassa e scontrini
        c = {x["nome"]: x for x in f.controlli}
        self.assertEqual(c["POS"]["esito"], "attenzione")
        self.assertIn("terminale ha incassato 1.194,00 € in più", c["POS"]["spiegazione"])
        f.totale_giornaliero = Decimal("16.01")
        c = {x["nome"]: x for x in f.controlli}
        self.assertIn("1,99 € in più", c["Scontrini"]["spiegazione"])

    def test_cassa_vuota(self):
        f = FileSysSpy(scontrini_trovati=0, totale_giornaliero=Decimal("0"), num_scontrini_fiscali=1)
        self.assertEqual([c["titolo"] for c in f.controlli], ["Cassa non usata"])
        self.assertTrue(f.quadrato)

    def test_regole_scansioni_obbligatorie(self):
        from primanota.models import RegolaDocumento
        self.importa_fixture()   # la fixture contiene un'abortita e nessun reso
        r = self.client_per("ufficio@x").get("/primanota/giornata/10/2026-05-28/")
        sezioni = {s["tipo"]["id"]: s["obbligatoria"] for s in r.context["sezioni"]}
        # I versamenti non sono più nella giornata: hanno la sezione Versamenti.
        # L'abortita della fixture è una sospensione dello scontrino: non chiede la scansione.
        self.assertEqual(sezioni, {"Chiusura fiscale": True, "Chiusure POS bancari": True, "Resi": False,
                                   "Transazioni abortite": False, "Fatture spese del giorno": False})
        self.client_per("admin@x").post("/primanota/condivisioni/", {"azione": "regole", "regola_versamenti": "FACOLTATIVO"})
        self.assertEqual(RegolaDocumento.mappa()["Versamenti contante"], "FACOLTATIVO")

    def test_stampa_pdf(self):
        import pymupdf
        self.importa_fixture()
        self.scansione_sede("Chiusura fiscale", cassa=1)
        pdf_scansione = pymupdf.open()
        pdf_scansione.new_page().insert_text((50, 50), "SCANSIONE")
        with mock.patch("primanota.services.stampa._scarica", return_value=(pdf_scansione.tobytes(), "application/pdf")):
            r = self.client_per("ufficio@x").get("/primanota/stampa/", {"sezione": "fiscale", "data_da": "2026-05-28",
                                                                         "per_pagina": 4})
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")   # si apre nella finestra della pagina
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        testo = doc[0].get_text()
        self.assertEqual(doc.page_count, 1)
        self.assertIn("TOTALE GIORNALIERO", testo)
        self.assertIn("SCANSIONE", testo)
        # Il negozio stampa le proprie chiusure, anche chiedendo quelle di un altro.
        with mock.patch("primanota.services.stampa._scarica", return_value=(pdf_scansione.tobytes(), "application/pdf")):
            r = self.client_per("altro_pv@x").get("/primanota/stampa/", {"sezione": "fiscale", "negozio": 10,
                                                                          "data_da": "2026-05-28"})
        self.assertNotIn("TOTALE GIORNALIERO", pymupdf.open(stream=r.content, filetype="pdf")[0].get_text())


class TestCampoMenu(Base):
    def test_colonna_trovata_per_nome(self):
        from primanota.services import accesso
        accesso._campo_menu.update(valore=None, scade=0)
        risposta = mock.Mock(json=lambda: [{"id": 7001, "name": "Menu_PrimaNota"}], raise_for_status=lambda: None)
        with override_settings(BASEROW_UTENTE_MENU_PRIMANOTA_FIELD=""), \
                mock.patch("primanota.services.accesso.requests.get", return_value=risposta) as get:
            self.assertEqual(accesso.campo_menu_primanota(), "field_7001")
            self.assertIn("/api/database/fields/table/272/", get.call_args.args[0])
        accesso._campo_menu.update(valore=None, scade=0)


class TestCasiReali(TestCase):
    """Situazioni trovate nei SysSpy di Adrano (5031), ridotte all'essenziale."""

    RESO = """8232                 TO.CAL. SRL
8232                                         Euro
8233    SOLE SOLARETTO GR.27                 1,99
8232              FIRMA DIRETTORE
8232              MOTIVO DEL RESO
8236 --------------------------------------------
8236 TOTALE EURO                             1,99
8232 17/10/2026 12:36               DOC.1094-0234
8232                 TO.CAL. SRL
8232                                         Euro
8233    PANINI                              44,62
8236 TOTALE EURO                            44,62
8238 Credito                                44,62
8241 RESTO                                   0,00
8232 17/10/2026 12:40               DOC.1094-0235
"""

    def test_buono_di_reso_escluso_e_credito_come_pagamento(self):
        g = sysspy.analizza("SysSpy.20261017.3", self.RESO.replace("\n", "\r\n").encode())["giornate"][0]
        self.assertTrue(g["scontrini"][0]["reso"])
        self.assertEqual(g["totale_scontrini"], Decimal("44.62"))
        self.assertEqual(g["pagamenti"], {"Credito": Decimal("44.62")})

    def test_configurazione_non_riscosso(self):
        carte = FileSysSpy(corrisp_non_riscosso=Decimal("10"), scontrini_trovati=3, totale_giornaliero=Decimal("50"),
                           pagamenti={"Carta Credito": "6", "Bancomat": "4", "Buoni Pasto": "8"})
        buoni = FileSysSpy(corrisp_non_riscosso=Decimal("8"), scontrini_trovati=3, totale_giornaliero=Decimal("50"),
                           pagamenti={"Carta Credito": "6", "Bancomat": "4", "Buoni Pasto": "8"})
        self.assertEqual((carte.configurazione_non_riscosso, buoni.configurazione_non_riscosso), ("carte", "buoni"))


class TestStampaPerNegozio(TestCase):
    def test_ogni_negozio_su_fogli_suoi_con_testata(self):
        import pymupdf
        from primanota.services.stampa import genera_pdf
        voci = [("5031 - Adrano", "17/10/2026  Cassa 3", "testo", "TOTALE GIORNALIERO 1,00"),
                ("5031 - Adrano", "17/10/2026  Cassa 4", "testo", "TOTALE GIORNALIERO 2,00"),
                ("5034 - Librino", "17/10/2026  Cassa 1", "testo", "TOTALE GIORNALIERO 3,00")]
        doc = pymupdf.open(stream=genera_pdf(voci, per_pagina=4, titolo="Chiusure fiscali"), filetype="pdf")
        self.assertEqual(doc.page_count, 2)   # il secondo negozio non sta sul foglio del primo
        self.assertEqual([doc[i].get_text().splitlines()[0] for i in range(2)], ["5031 - Adrano", "5034 - Librino"])


class TestVersamentiNoteStatistiche(Base):
    def test_versamenti_solo_per_la_sede(self):
        self.carica(self.client_per("pv@x"), "Versamenti contante")
        self.assertEqual(self.client_per("pv@x").get("/primanota/versamenti/").status_code, 302)  # il negozio torna al caricamento
        r = self.client_per("ufficio@x").get("/primanota/versamenti/", {"data_da": "2026-05-28"})
        self.assertEqual(len(r.context["scansioni"]), 1)
        # Nel riepilogo Scansioni i versamenti non compaiono più.
        r = self.client_per("ufficio@x").get("/primanota/admin/", {"data_da": "2026-05-28"})
        self.assertEqual(r.context["conteggio"], 0)

    def test_nota_sul_versamento_inviata_per_email(self):
        from primanota.models import DestinatarioEmail
        DestinatarioEmail.objects.create(nome="Amministrazione", email="amm@x.it")
        DestinatarioEmail.objects.create(nome="Direzione", email="dir@x.it")
        DestinatarioEmail.objects.create(nome="Vecchio", email="old@x.it", attivo=False)
        self.carica(self.client_per("pv@x"), "Versamenti contante")
        # Va sempre a tutti i destinatari attivi, senza sceglierli.
        with mock.patch("primanota.services.posta.invia") as invia:
            r = self.client_per("pv@x").post("/primanota/upload/", {
                "azione": "nota_versamento", "scansione_id": 1, "testo": "Mancano 10 euro"})
        self.assertRedirects(r, "/primanota/upload/?versamento=inviata", fetch_redirect_response=False)
        destinatari, oggetto, corpo = invia.call_args.args
        self.assertEqual(sorted(destinatari), ["amm@x.it", "dir@x.it"])
        self.assertIn("Mancano 10 euro", corpo)
        self.assertEqual(invia.call_args.kwargs["allegato_url"], "/media/up_scan.pdf")
        nota = Nota.objects.get()
        self.assertTrue(nota.versamento)
        self.assertEqual((nota.scansione_id, nota.esito_invio), (1, "Inviata"))
        # La nota è in Gestione Versamenti, non nelle Chiusure Fiscali.
        uff = self.client_per("ufficio@x")
        self.assertEqual(uff.get("/primanota/admin/").context["note_negozi"], [])
        self.assertEqual(uff.get("/primanota/note/").context["elenco"], [])
        self.assertEqual([n.testo for n, _ in uff.get("/primanota/versamenti/note/").context["elenco"]], ["Mancano 10 euro"])
        self.assertEqual(self.client_per("pv@x").get("/primanota/versamenti/note/").status_code, 302)

    def test_nota_sul_versamento_dalla_giornata_e_dal_salva(self):
        from primanota.models import DestinatarioEmail
        DestinatarioEmail.objects.create(nome="Amministrazione", email="amm@x.it")
        self.carica(self.client_per("pv@x"), "Versamenti contante")
        pv = self.client_per("pv@x")
        pagina = pv.get("/primanota/giornata/10/2026-05-28/")
        self.assertContains(pagina, '<option value="VERSAMENTO">Nota sul versamento</option>')
        self.assertContains(pagina, "Sarà inviata per email")
        with mock.patch("primanota.services.posta.invia") as invia:
            pv.post("/primanota/giornata/10/2026-05-28/", {"tipo": "VERSAMENTO", "testo": "banconota da 50 non registrata"})
            pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "tipo_nota": "VERSAMENTO", "note": "seconda nota"})
        self.assertEqual(invia.call_count, 2)
        self.assertEqual(invia.call_args_list[0].kwargs["allegato_url"], "/media/up_scan.pdf")   # scansione del giorno
        self.assertEqual(sorted(Nota.objects.filter(versamento=True).values_list("testo", flat=True)),
                         ["banconota da 50 non registrata", "seconda nota"])
        # Nella giornata il negozio e la sede le vedono con l'esito dell'invio.
        self.assertContains(pv.get("/primanota/giornata/10/2026-05-28/"), "Inviata a amm@x.it")
        self.assertContains(self.client_per("ufficio@x").get("/primanota/giornata/10/2026-05-28/"), "banconota da 50")
        # Una nota normale resta senza email.
        with mock.patch("primanota.services.posta.invia") as invia:
            pv.post("/primanota/giornata/10/2026-05-28/", {"tipo": "NOTA", "testo": "nota normale"})
        invia.assert_not_called()

    def test_note_da_lavorare_e_lavorate(self):
        vecchia = Nota.objects.create(negozio_id=10, data="2026-05-27", testo="vecchia", creata_da="x")
        Nota.objects.create(negozio_id=10, data="2026-05-28", testo="nuova", creata_da="x")
        Nota.objects.create(negozio_id=10, data="2026-05-28", testo="fatta", creata_da="x", chiusa=True)
        uff = self.client_per("ufficio@x")
        self.assertEqual([n.testo for n, _ in uff.get("/primanota/note/").context["elenco"]], ["nuova", "vecchia"])
        self.assertEqual([n.testo for n, _ in uff.get("/primanota/note/?lavorate=1").context["elenco"]], ["fatta"])
        self.assertTrue(vecchia.pk)

    def test_statistiche(self):
        self.importa_fixture()
        r = self.client_per("direttore@x").get("/primanota/statistiche/finanziarie/", {"data_da": "2026-05-28", "data_a": "2026-05-28"})
        dati = r.context["dati"]
        self.assertEqual((dati["kpi"]["totale"], dati["kpi"]["scontrini"], dati["kpi"]["abortite"]), (Decimal("18.00"), 2, 1))
        self.assertEqual(dati["cassieri"][0]["nome"], "MARIO ROSSI")
        self.assertEqual(dati["pagamenti"][0]["voce"], "Carta Credito")
        self.assertContains(r, "18,00 €")

    def test_nome_del_pdf(self):
        from primanota.services.stampa import nome_file
        self.assertEqual(nome_file("fiscale", "5031 - Pv Adrano", "2026-10-17", "2026-10-17"),
                         "Chiusure_fiscali_5031_Pv_Adrano_2026-10-17.pdf")
        self.assertEqual(nome_file("pos", "", "2026-10-01", "2026-10-17", "sysspy"),
                         "Chiusure_POS_Tutti_i_negozi_dal_2026-10-01_al_2026-10-17_solo_SysSpy.pdf")


class TestChiusureVisteDalNegozio(Base):
    def test_il_negozio_vede_le_proprie_chiusure(self):
        self.importa_fixture()
        pv = self.client_per("pv@x")
        self.assertContains(pv.get("/primanota/upload/"), "Le tue giornate")
        r = pv.get("/primanota/giornata/10/2026-05-28/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "TOTALE GIORNALIERO")          # chiusura fiscale
        self.assertContains(r, "TOTALE HOST EUR")             # chiusura POS
        self.assertContains(r, "✓ POS")                       # stessi controlli della sede
        self.assertNotContains(r, "onchange=\"toggleLavorato")   # ma niente «lavorato»
        self.assertNotContains(r, "/primanota/admin/")        # né il menu della sede
        f = FileSysSpy.objects.get()
        self.assertEqual(pv.get(f"/primanota/sysspy/{f.id}/").status_code, 200)
        # Le giornate di un altro negozio no.
        altro = self.client_per("altro_pv@x")
        self.assertEqual(altro.get("/primanota/giornata/10/2026-05-28/").status_code, 403)
        self.assertEqual(altro.get(f"/primanota/sysspy/{f.id}/").status_code, 404)
        # Dalla giornata il negozio può scrivere una nota.
        pv.post("/primanota/giornata/10/2026-05-28/", {"tipo": "ANOMALIA", "testo": "POS non torna"})
        self.assertEqual(Nota.objects.get().testo, "POS non torna")

    def test_ultime_giornate_nella_pagina_di_caricamento(self):
        from primanota import views
        self.importa_fixture()
        oggi = date(2026, 5, 30)
        with mock.patch("primanota.views.timezone.localdate", return_value=oggi):
            giornate = views._giornate_recenti(10)
        self.assertEqual([g["data"] for g in giornate][:2], [date(2026, 5, 29), date(2026, 5, 28)])
        g = giornate[1]
        self.assertEqual((g["casse"], g["anomalie"]), (1, []))
        # Regole predefinite: chiusure e versamento sempre; resi no; l'abortita è una sospensione e non conta.
        self.assertEqual(g["mancanti"], ["Chiusura fiscale", "Chiusure POS bancari", "Versamenti contante"])
        RegolaDocumento.objects.create(tipo_documento="Versamenti contante", obbligo=RegolaDocumento.FACOLTATIVO)
        with mock.patch("primanota.views.timezone.localdate", return_value=oggi):
            g = views._giornate_recenti(10)[1]
        self.assertEqual(g["mancanti"], ["Chiusura fiscale", "Chiusure POS bancari"])


class TestDocumentiAmministrativi(Base):
    def test_tre_sezioni_per_la_sede(self):
        uff = self.client_per("ufficio@x")
        home = uff.get("/primanota/")
        for voce in ("Chiusure Fiscali", "Gestione Versamenti", "Consultazione Prima Nota"):
            self.assertContains(home, f"<h2>{voce}</h2>")
        self.assertNotContains(home, "<h2>Statistiche</h2>")   # solo Direttori e Amministratori
        self.assertContains(self.client_per("direttore@x").get("/primanota/"), "<h2>Statistiche</h2>")
        # Nelle Chiusure Fiscali nessun riferimento ai versamenti; in Gestione Versamenti il suo menu.
        admin = uff.get("/primanota/admin/")
        self.assertNotContains(admin, "/primanota/versamenti/")
        self.assertNotContains(admin, "/primanota/statistiche/")
        menu_versamenti = uff.get("/primanota/versamenti/monitor/")
        for link in ("/primanota/versamenti/monitor/", "/primanota/versamenti/", "/primanota/versamenti/note/"):
            self.assertContains(menu_versamenti, f'href="{link}"')
        self.assertNotContains(menu_versamenti, 'href="/primanota/sysspy/"')
        self.assertRedirects(self.client_per("pv@x").get("/primanota/"), "/primanota/upload/", fetch_redirect_response=False)

    def test_installazione_rinomina_la_scheda_del_menu(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("installa", Path(__file__).parents[1] / "installa" / "installa.py")
        installa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installa)
        vecchio = "{% load primanota_menu %}{% primanota_visibile utente as show_primanota %}<h2>Chiusure Fiscali</h2>" \
                  "<p>Scansioni chiusure fiscali, POS, resi, abortite e versamenti, con i file scontrini delle casse.</p>"
        nuovo = installa.modifica_menu(vecchio)
        self.assertIn("<h2>Documenti Amministrativi</h2>", nuovo)
        self.assertIn("gestione versamenti e statistiche", nuovo)


class TestPostaDelPortale(Base):
    def test_invia_con_la_configurazione_del_portale(self):
        from primanota.services import posta
        config = Path(self.archivio) / "email_config.json"
        config.write_text(json.dumps({"enabled": True, "smtp_host": "smtp.prova", "smtp_port": 465, "smtp_user": "u@x.it",
                                      "smtp_password": "pw", "smtp_ssl": True, "from_email": "da@x.it", "rules": {}}))
        allegato = mock.Mock(content=b"%PDF-1.4", headers={"Content-Type": "application/pdf"})
        with override_settings(PRIMANOTA_EMAIL_CONFIG=str(config)), \
                mock.patch("primanota.services.posta.smtplib.SMTP_SSL") as smtp, \
                mock.patch("primanota.services.posta.requests.get", return_value=allegato):
            self.assertEqual(posta.stato()["server"], "smtp.prova:465")
            posta.invia(["a@x.it", "b@x.it"], "Versamento 5048", "Mancano 10 euro", "http://b/scan.pdf", "scan.pdf")
            # La pagina delle impostazioni mostra il server ma non la password.
            pagina = self.client_per("admin@x").get("/primanota/impostazioni-email/")
        sessione = smtp.return_value.__enter__.return_value
        sessione.login.assert_called_once_with("u@x.it", "pw")
        msg = sessione.send_message.call_args.args[0]
        self.assertEqual((msg["To"], msg["Subject"]), ("a@x.it, b@x.it", "Versamento 5048"))
        self.assertIn("da@x.it", msg["From"])
        self.assertEqual([p.get_filename() for p in msg.iter_attachments()], ["scan.pdf"])
        self.assertContains(pagina, "smtp.prova:465")
        self.assertNotContains(pagina, "pw<")

    def test_senza_configurazione_non_invia(self):
        from primanota.services import posta
        with override_settings(PRIMANOTA_EMAIL_CONFIG="/non/esiste.json"):
            self.assertFalse(posta.configurata())
            with self.assertRaisesRegex(RuntimeError, "non trovata"):
                posta.invia(["a@x.it"], "x", "y")


class TestStatistichePdf(Base):
    def test_pdf_con_grafici_scelti(self):
        import pymupdf
        self.importa_fixture()
        uff = self.client_per("direttore@x")
        for andamento, torta in (("linea", "barre"), ("colonne", "torta"), ("area", "torta")):
            r = uff.get("/primanota/statistiche/finanziarie/pdf/", {"data_da": "2026-05-25", "data_a": "2026-05-30", "andamento": andamento,
                                                        "grafico_negozi": torta, "grafico_pagamenti": torta,
                                                        "vista_da": "2026-05-27", "vista_a": "2026-05-29"})
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")
            self.assertIn('filename="Statistiche_finanziarie_Tutti_i_negozi_dal_2026-05-25_al_2026-05-30.pdf"', r["Content-Disposition"])
            doc = pymupdf.open(stream=r.content, filetype="pdf")
            testo = "".join(p.get_text() for p in doc)
            self.assertIn("Andamento dei corrispettivi (dal 27/05 al 29/05)", testo)
            self.assertIn("MARIO ROSSI", testo)
            self.assertIn("18,00 €", testo)
            self.assertEqual(sum(len(p.get_images()) for p in doc), 2)   # andamento; negozi e pagamenti
        self.assertEqual(self.client_per("pv@x").get("/primanota/statistiche/finanziarie/pdf/").status_code, 302)

    def test_pagina_con_comandi_dei_grafici(self):
        self.importa_fixture()
        r = self.client_per("direttore@x").get("/primanota/statistiche/finanziarie/", {"data_da": "2026-05-28", "data_a": "2026-05-28"})
        for comando in ('id="zoomPiu"', 'id="zoomMeno"', 'data-valore="colonne"', 'data-valore="torta"', 'id="stampaPdf"'):
            self.assertContains(r, comando)
        self.assertEqual(r.context["grafici"]["pagamenti"], [{"etichetta": "Carta Credito", "valore": 18.0}])


class TestBuoniPasto(Base):
    RIGHE = [("5031", "Pv Adrano", 18, "DAY RISTOSERVICE", Decimal("120.50")),
             ("5031", "Pv Adrano", 21, "EDENRED", Decimal("80.00")),
             ("5048", "Pv Motta", 18, "DAY RISTOSERVICE", Decimal("30.00"))]

    def test_query_con_parametri(self):
        import sys
        from primanota.services import buoni_pasto
        cursore = mock.MagicMock()
        cursore.fetchall.return_value = self.RIGHE
        modulo = mock.MagicMock(Error=Exception)
        modulo.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursore
        with mock.patch.dict(sys.modules, {"pymssql": modulo}), \
                override_settings(BUONI_PASTO_DB={"host": "sql", "database": "Scontrini", "user": "u", "password": "p"}):
            righe = buoni_pasto.interroga("2026-10-01", "2026-10-19", ["5031", "5048' OR 1=1 --"])
        sql, parametri = cursore.execute.call_args.args
        self.assertIn("AND r.pv IN (%s, %s)", sql)
        self.assertNotIn("5031", sql)   # i punti vendita non entrano nel testo SQL
        self.assertEqual(parametri, ("20261001", "20261019", "5031", "5048' OR 1=1 --"))
        self.assertEqual(modulo.connect.call_args.kwargs["server"], "sql")
        self.assertEqual(righe[0], ("5031", "Pv Adrano", 18, "DAY RISTOSERVICE", Decimal("120.50")))

    def test_pagina_totali_e_stampe(self):
        uff = self.client_per("direttore@x")
        with mock.patch("primanota.services.buoni_pasto.interroga") as interroga:
            r = uff.get("/primanota/buoni-pasto/")
            interroga.assert_not_called()   # la query parte solo con «Cerca»
            interroga.return_value = self.RIGHE
            r = uff.get("/primanota/buoni-pasto/", {"data_da": "2026-10-01", "data_a": "2026-10-19", "pv": ["5031", "5048"]})
            self.assertEqual(interroga.call_args.args, ("2026-10-01", "2026-10-19", ["5031", "5048"]))
            ris = r.context["risultato"]
            self.assertEqual([(g["pv"], g["totale"]) for g in ris["gruppi"]], [("5031", Decimal("200.50")), ("5048", Decimal("30.00"))])
            self.assertEqual([(e["emettitore"], e["importo"]) for e in ris["per_emettitore"]],
                             [("DAY RISTOSERVICE", Decimal("150.50")), ("EDENRED", Decimal("80.00"))])
            self.assertEqual(ris["totale"], Decimal("230.50"))
            self.assertContains(r, "Totale generale")
            self.assertContains(r, 'class="fascia-b"')   # fasce alternate per punto vendita
            csv = uff.get("/primanota/buoni-pasto/", {"data_da": "2026-10-01", "data_a": "2026-10-19", "formato": "csv"})
            self.assertIn("5031;Pv Adrano;18;DAY RISTOSERVICE;120,50", csv.content.decode("utf-8-sig"))
            self.assertIn("Buoni_pasto_per_emettitore_Tutti_dal_2026-10-01_al_2026-10-19.csv", csv["Content-Disposition"])
            pdf = uff.get("/primanota/buoni-pasto/", {"data_da": "2026-10-01", "data_a": "2026-10-19", "formato": "pdf"})
        import pymupdf
        testo = pymupdf.open(stream=pdf.content, filetype="pdf")[0].get_text()
        self.assertIn("Totale 5031 Pv Adrano", testo)
        self.assertIn("230,50 €", testo)
        self.assertEqual(self.client_per("pv@x").get("/primanota/buoni-pasto/").status_code, 302)
        self.assertContains(uff.get("/primanota/statistiche/"), "Buoni Pasto per Emettitori")

    def test_errore_di_collegamento(self):
        with override_settings(BUONI_PASTO_DB=None):
            r = self.client_per("direttore@x").get("/primanota/buoni-pasto/", {"data_da": "2026-10-01", "data_a": "2026-10-19"})
        self.assertContains(r, "non configurato")

    def test_larghezza_barre_non_localizzata(self):
        from primanota.templatetags.primanota_formati import quota
        with override_settings(LANGUAGE_CODE="it", USE_THOUSAND_SEPARATOR=True):
            self.assertEqual(quota(49.5, 100), "49.50")


class TestCollegamentoBuoniPasto(Base):
    def test_solo_direttore_e_amministratore(self):
        from primanota.models import CollegamentoBuoniPasto
        from primanota.services import cassa_centrale as buoni_pasto
        self.assertEqual(self.client_per("ufficio@x").get("/primanota/buoni-pasto/collegamento/").status_code, 403)
        self.assertEqual(self.client_per("pv@x").get("/primanota/buoni-pasto/collegamento/").status_code, 302)
        d = self.client_per("direttore@x")
        with mock.patch("primanota.services.cassa_centrale.prova") as prova:
            r = d.post("/primanota/buoni-pasto/collegamento/", {"host": "10.0.0.5", "database": "Scontrini", "utente": "lettore",
                                                                "password": "segreta", "azione": "prova"})
        self.assertContains(r, "il database risponde")
        self.assertEqual(prova.call_args.args[0], {"host": "10.0.0.5", "database": "Scontrini", "user": "lettore", "password": "segreta"})
        c = CollegamentoBuoniPasto.objects.get()
        self.assertNotIn("segreta", c.password_cifrata)
        self.assertNotContains(r, "segreta")
        # Password vuota: resta quella salvata.
        self.client_per("admin@x").post("/primanota/buoni-pasto/collegamento/", {"host": "10.0.0.6", "utente": "lettore", "password": ""})
        self.assertEqual(buoni_pasto.configurazione()["password"], "segreta")
        self.assertEqual(buoni_pasto.configurazione()["host"], "10.0.0.6")
        # Il link al collegamento lo vede chi può gestirlo; l'ufficio non entra nelle statistiche.
        self.assertContains(d.get("/primanota/buoni-pasto/"), "/primanota/buoni-pasto/collegamento/")
        self.assertEqual(self.client_per("ufficio@x").get("/primanota/buoni-pasto/").status_code, 403)
        for url in ("/primanota/statistiche/", "/primanota/buoni-pasto/"):
            self.assertRedirects(self.client_per("pv@x").get(url), "/primanota/upload/", fetch_redirect_response=False)



def righe_prima_nota(*file):
    """Le righe dei CSV di esempio come le restituisce pymssql (dict per colonna, importi Decimal)."""
    import csv
    colonne = (DATI / "prima_nota_colonne.txt").read_text().split()
    out = []
    for nome in file:
        with open(DATI / nome, encoding="utf-8") as f:
            for r in csv.reader(f, delimiter=";", quotechar='"'):
                d = dict(zip(colonne, r))
                for k in ("importo", "imponibile", "iva", "importo_ori"):
                    d[k] = Decimal(d[k].replace(",", "."))
                d["causale_descr"], d["nome_negozio"] = "", "PV PROVA " + d["pv"]
                out.append(d)
    return out


class TestPrimaNota(Base):
    RIPRESA = [("5040", Decimal("5229924.84"), Decimal("5229924.84"), Decimal("2744142.44"), 17810)]

    def esegui_finto(self, righe):
        def esegui(c, sql, parametri=(), dizionari=False):
            self.query.append((sql, parametri))
            return righe if dizionari else [r for r in self.RIPRESA if r[0] in parametri]
        self.query = []
        return mock.patch.multiple("primanota.services.prima_nota", esegui=esegui, configurazione=lambda: {"host": "x"})

    def test_giornata_come_nel_gestionale(self):
        with self.esegui_finto(righe_prima_nota("prima_nota_5040.csv")):
            r = self.client_per("ufficio@x").get("/primanota/prima-nota/", {"pv": "5040", "data": "2026-10-19"})
        g = r.context["giornata"]
        self.assertEqual(self.query[0][1], ("20261019", "20261019", "5040"))
        self.assertIn("ISNULL(r.data_ann, 0) = 0", self.query[0][0])
        self.assertEqual(self.query[1][1], ("20261019", "5040"))   # ripresa: tutto prima del giorno
        # Gli stessi numeri della schermata del gestionale.
        self.assertEqual((g["periodo"]["entrate"], g["periodo"]["uscite"], g["periodo"]["evidenze"], g["periodo"]["movimenti"]),
                         (Decimal("936.41"), Decimal("936.41"), Decimal("697.19"), 15))
        self.assertEqual((g["progressivo"]["entrate"], g["progressivo"]["evidenze"], g["progressivo"]["movimenti"]),
                         (Decimal("5230861.25"), Decimal("2744839.63"), 17825))
        causali = {c["codice"]: c for c in g["causali"]}
        self.assertEqual([c["codice"] for c in g["causali"]][:5], [1, 15, 14, 16, 2])   # ordine del modello
        self.assertEqual((len(causali[1]["movimenti"]), causali[1]["entrate"]), (4, Decimal("934.75")))
        self.assertEqual(causali[10]["movimenti"][0]["descrizione"], "Oper: 72-ROSSI MARIO")
        self.assertEqual(causali[21]["evidenze"], Decimal("20"))
        self.assertIsNone(causali[3]["uscite"])
        nota = causali[17]["movimenti"][0]["note"]
        self.assertTrue(nota.startswith("cassone elettronica") and nota.endswith("aut.mario manutentore"))
        self.assertContains(r, "aut.mario manutentore")   # nota intera, non tagliata
        self.assertContains(r, "5.230.861,25 €")

    def test_stampa_piu_negozi_una_pagina_ciascuno(self):
        import pymupdf
        with self.esegui_finto(righe_prima_nota("prima_nota_5031.csv", "prima_nota_5040.csv")):
            r = self.client_per("ufficio@x").get("/primanota/prima-nota/", {"formato": "pdf", "dal": "2026-10-19", "al": "2026-10-19"})
        self.assertEqual(self.query[0][1], ("20261019", "20261019"))   # nessun PV scelto = tutti
        self.assertIn('filename="Prima_nota_Tutti_i_PV_2026-10-19.pdf"', r["Content-Disposition"])
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        self.assertEqual(doc.page_count, 2)
        self.assertIn("5031 PV PROVA 5031", doc[0].get_text())
        testo = " ".join(doc[1].get_text().split())
        self.assertIn("5040 PV PROVA 5040", testo)
        self.assertIn("salumeria coprati dal manutentore aut.mario manutentore", testo)   # nota intera
        self.assertIn("5.230.861,25", testo)
        self.assertEqual(self.client_per("pv@x").get("/primanota/prima-nota/").status_code, 302)

    def test_senza_ricerca_nessuna_query(self):
        with self.esegui_finto([]):
            r = self.client_per("ufficio@x").get("/primanota/prima-nota/")
        self.assertEqual(self.query, [])
        self.assertContains(r, "Consulta un punto vendita")


class TestFasceOrarie(Base):
    # (codice, descrizione, minuto di inizio fascia, tipo cliente, valore, pezzi, clienti, giorni) dalle tabelle *2
    NEGOZI = [("5031", "PV ADRANO", 8 * 60, 0, Decimal("700.50"), 350, 50, 7), ("5031", "PV ADRANO", 8 * 60 + 15, 0, Decimal("500"), 250, 40, 7),
              ("5031", "PV ADRANO", 9 * 60, 0, Decimal("1500"), 700, 100, 7), ("5031", "PV ADRANO", 9 * 60, 1, Decimal("300"), 200, 20, 7),
              ("5048", "PV MOTTA", 9 * 60 + 45, 0, Decimal("700"), 300, 50, 6), ("5048", "PV MOTTA", 18 * 60, 0, Decimal("2100"), 1000, 150, 6),
              ("5048", "PV MOTTA", 6 * 60 + 45, 0, Decimal("99"), 10, 1, 1)]
    REPARTI = [("10", "ORTOFRUTTA", 9 * 60, 0, Decimal("500"), 200, 80, 7), ("20", "MACELLERIA", 9 * 60 + 15, 0, Decimal("2000"), 1000, 100, 7),
               ("20", "MACELLERIA", 18 * 60, 0, Decimal("2100"), 1000, 120, 6)]

    def esegui_finto(self):
        def esegui(c, sql, parametri=(), dizionari=False):
            self.query.append((sql, parametri))
            if "DescrizioneReparti AS r" in sql:
                return [("10", "ORTOFRUTTA"), ("20", "MACELLERIA"), ("3", "PANE")]
            return self.REPARTI if "VenditeReparto2" in sql else self.NEGOZI
        self.query = []
        return mock.patch.multiple("primanota.services.fasce_orarie", esegui=esegui, configurazione=lambda: {"host": "x"})

    def test_quarti_d_ora_e_orario(self):
        uff = self.client_per("direttore@x")
        with self.esegui_finto():
            uff.get("/primanota/fasce-orarie/", {"data_da": "2026-10-13", "data_a": "2026-10-19"})
            self.assertEqual(self.query, [])   # senza «Cerca» nessuna query
            r = uff.get("/primanota/fasce-orarie/", {"data_da": "2026-10-13", "data_a": "2026-10-19", "pv": ["5031", "5048"],
                                                    "cerca": "1", "dalle": "07:00", "alle": "22:00", "passo": "15"})
        sql, parametri = self.query[0]
        self.assertIn("VenditeFasceOrarie2", sql)
        self.assertIn("JOIN Statistiche.dbo.FasceOrarie2 AS f", sql)
        self.assertEqual(parametri, ("20261013", "20261020", "5031", "5048"))   # fino a fine giornata del 19
        ris, tab = r.context["risultato"], r.context["tab"]
        # La fascia delle 6:45 è fuori dall'orario scelto.
        self.assertEqual(tab["fasce"], ["08:00-08:15", "08:15-08:30", "09:00-09:15", "09:45-10:00", "18:00-18:15"])
        self.assertEqual(ris["totale"], {"valore": Decimal("5800.50"), "pezzi": 2800, "clienti": 410})
        self.assertEqual(ris["di_punta"], "18:00-18:15")
        self.assertEqual([(t["tipo"], t["valore"]) for t in ris["per_tipo"]], [(0, Decimal("5500.50")), (1, Decimal("300"))])
        self.assertContains(r, "Per tipo cliente")
        self.assertEqual(tab["righe"][1]["celle"][-1][1], 6)   # la cella più alta ha il colore più scuro
        # Raggruppate per ora e solo dalle 8 alle 10.
        with self.esegui_finto():
            r = uff.get("/primanota/fasce-orarie/", {"data_da": "2026-10-13", "data_a": "2026-10-19", "cerca": "1",
                                                    "dalle": "08:00", "alle": "10:00", "passo": "60", "misura": "pezzi", "media": "1"})
        tab = r.context["tab"]
        self.assertEqual(tab["fasce"], ["08:00-09:00", "09:00-10:00"])
        self.assertEqual(tab["righe"][0]["celle"][0][0], Decimal("600") / 7)   # 350 + 250 pezzi in 7 giorni
        self.assertEqual(tab["righe"][1]["totale"], Decimal("300") / 6)
        self.assertContains(r, "dalle 08:00 alle 10:00")

    def test_per_reparto_clienti_dai_negozi(self):
        uff = self.client_per("direttore@x")
        with self.esegui_finto():
            r = uff.get("/primanota/fasce-orarie/", {"vista": "reparti", "data_da": "2026-10-13", "data_a": "2026-10-19",
                                                    "reparto": ["10", "20"], "cerca": "1", "misura": "clienti", "passo": "60"})
        sql_reparti = next(s for s, p in self.query if "VenditeReparto2" in s)
        self.assertIn("CodRepartoVenditeReparto IN (%s, %s)", sql_reparti)
        self.assertIn("f.NumeroFasciaOraria = r.FasciaOraVenditeReparto", sql_reparti)
        ris = r.context["risultato"]
        self.assertEqual([e["etichetta"] for e in ris["righe"]], ["10 ORTOFRUTTA", "20 MACELLERIA"])
        # I clienti totali delle 9 sono quelli dei punti vendita (50 + 40... solo le fasce delle 9: 100 + 20 + 50),
        # non 80 + 100 dei reparti.
        self.assertEqual(ris["per_fascia"][9 * 60]["clienti"], 170)
        self.assertContains(r, "PANE")   # elenco dei reparti nei filtri
        self.assertContains(r, "lo stesso cliente compra in più reparti")

    def test_stampe_e_accesso(self):
        import pymupdf
        uff = self.client_per("direttore@x")
        with self.esegui_finto():
            csv = uff.get("/primanota/fasce-orarie/", {"data_da": "2026-10-13", "data_a": "2026-10-19", "formato": "csv"})
            pdf = uff.get("/primanota/fasce-orarie/", {"data_da": "2026-10-13", "data_a": "2026-10-19", "formato": "pdf",
                                                      "dalle": "00:00", "alle": "24:00"})
        righe = csv.content.decode("utf-8-sig").splitlines()
        self.assertEqual(righe[0], "Punto vendita;08:00-08:15;08:15-08:30;09:00-09:15;09:45-10:00;18:00-18:15;Totale")
        self.assertEqual(righe[1], "5031 PV ADRANO;700,50;500,00;1.800,00;0,00;0,00;3.000,50")
        self.assertIn("Fasce_orarie_negozi_Tutti_dal_2026-10-13_al_2026-10-19_valore.pdf", pdf["Content-Disposition"])
        testo = pymupdf.open(stream=pdf.content, filetype="pdf")[0].get_text()
        self.assertIn("5.899,50", testo)   # dalle 0 alle 24 entra anche la fascia delle 6:45
        self.assertEqual(self.client_per("pv@x").get("/primanota/fasce-orarie/").status_code, 302)
        self.assertContains(uff.get("/primanota/statistiche/"), "Vendite per Fasce Orarie")

    def test_pdf_a_blocchi_di_colonne(self):
        from primanota.services import fasce_orarie
        righe = [("5031", "PV ADRANO", m, 0, Decimal("10"), 1, 1, 1) for m in range(7 * 60, 22 * 60, 15)]
        ris = fasce_orarie.componi(righe, dalle=7 * 60, alle=22 * 60, passo=15)
        self.assertEqual(len(ris["fasce"]), 60)
        import pymupdf
        doc = pymupdf.open(stream=fasce_orarie.pdf(ris, "valore", False, "negozi", "Prova", "sotto", "x.pdf"), filetype="pdf")
        testo = "".join(p.get_text() for p in doc)
        self.assertEqual(" ".join(testo.split()).count("% sul totale"), 4)   # 60 fasce in 4 tabelle da 16
        self.assertIn("600,00", testo)

class TestMenuStatistiche(Base):
    def test_tre_sezioni_solo_per_direttori_e_amministratori(self):
        for email in ("direttore@x", "admin@x"):
            c = self.client_per(email)
            self.assertContains(c.get("/primanota/"), 'href="/primanota/statistiche/"')
            r = c.get("/primanota/statistiche/")
            for voce in ("Statistiche finanziarie", "Vendite per Fasce Orarie", "Buoni Pasto per Emettitori"):
                self.assertContains(r, f"<h2>{voce}</h2>")
        uff = self.client_per("ufficio@x")
        self.assertNotContains(uff.get("/primanota/"), 'href="/primanota/statistiche/"')
        for url in ("/primanota/statistiche/", "/primanota/statistiche/finanziarie/", "/primanota/statistiche/finanziarie/pdf/",
                    "/primanota/fasce-orarie/", "/primanota/buoni-pasto/"):
            self.assertEqual(uff.get(url).status_code, 403, url)
            self.assertEqual(self.client_per("pv@x").get(url).status_code, 302, url)
        # Le consultazioni della sede restano all'ufficio.
        self.assertEqual(uff.get("/primanota/prima-nota/").status_code, 200)
        # Vecchi collegamenti alle statistiche con i filtri.
        r = self.client_per("direttore@x").get("/primanota/statistiche/", {"data_da": "2026-05-01", "data_a": "2026-05-31"})
        self.assertRedirects(r, "/primanota/statistiche/finanziarie/?data_da=2026-05-01&data_a=2026-05-31",
                             fetch_redirect_response=False)


class TestElaborazioneInCorso(Base):
    def test_ricerche_con_indicatore_di_attesa(self):
        d = self.client_per("direttore@x")
        with mock.patch("primanota.services.cassa_centrale.configurazione", return_value=None):
            for url, testo in (("/primanota/statistiche/finanziarie/", "Calcolo delle statistiche in corso"),
                               ("/primanota/fasce-orarie/", "Ricerca delle vendite per fasce orarie in corso"),
                               ("/primanota/buoni-pasto/", "Ricerca dei buoni pasto in corso"),
                               ("/primanota/prima-nota/", "Ricerca della prima nota in corso")):
                r = d.get(url)
                self.assertContains(r, f'data-attesa="{testo}…"')
                self.assertContains(r, "function mostraAttesa(")


class TestFattureSpese(Base):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def prima_nota(self, presenze, spese=()):
        """Prima nota simulata: giornate presenti e righe di «spese del giorno con fattura»."""
        def esegui(c, sql, parametri=(), dizionari=False):
            if "COUNT(*)" in sql and "causale = 17" in sql:
                return presenze
            return list(spese)
        return mock.patch.multiple("primanota.services.prima_nota", esegui=esegui, configurazione=lambda: {"host": "x"})

    def stati(self, giorno="2026-05-28"):
        r = self.client_per("pv@x").get("/primanota/upload/", {"data": giorno})
        return {v["tipo"]["id"]: (v["stato"], v["manca"]) for v in r.context["voci"]}

    def test_obbligatoria_solo_con_spese_con_fattura(self):
        # Prima nota della giornata senza spese con fattura: la voce non è prevista.
        with self.prima_nota([("5048", 20260528, 12, 0, Decimal("0"))]):
            self.assertEqual(self.stati()["Fatture spese del giorno"], ("non_richiesta", False))
        from django.core.cache import cache
        cache.clear()
        # Con una spesa con fattura (causale 17) la scansione è obbligatoria.
        with self.prima_nota([("5048", 20260528, 13, 1, Decimal("27.20"))]):
            self.assertEqual(self.stati()["Fatture spese del giorno"], ("obbligatoria", True))
            self.carica(self.client_per("pv@x"), "Fatture spese del giorno")
            self.assertEqual(self.stati()["Fatture spese del giorno"], ("obbligatoria", False))

    def test_monitor_e_giornata(self):
        from primanota.models import RegolaDocumento
        for t in ("Chiusura fiscale", "Chiusure POS bancari"):
            RegolaDocumento.objects.create(tipo_documento=t, obbligo=RegolaDocumento.FACOLTATIVO)
        ieri = date.today() - timedelta(days=1)
        spesa = {"anno": 2026, "progressivo": 335832, "pv": "5048", "data": ieri.strftime("%Y%m%d"), "ora": "085653",
                 "causale": 17, "segno": "E", "importo": Decimal("27.20"), "int_ragsoc": "", "tipo_doc_rif": "",
                 "num_doc_rif": "", "data_doc_rif": "00000000", "note": "cassone elettronica acquisto interruttori",
                 "causale_descr": "SPESE DEL GIORNO CON FATTURA", "nome_negozio": "PV MOTTA"}
        self.carica(self.client_per("pv@x"), "Resi", giorno=ieri.isoformat())
        with self.prima_nota([("5048", int(ieri.strftime("%Y%m%d")), 13, 1, Decimal("27.20"))], [spesa]):
            r = self.client_per("ufficio@x").get("/primanota/monitor/", {"anno": ieri.year, "mese": ieri.month})
            riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
            cella = next(c for c in riga["cells"] if c["date"] == ieri.isoformat())
            self.assertIn("Fatture spese del giorno", cella["mancanti"])
            r = self.client_per("ufficio@x").get(f"/primanota/giornata/10/{ieri.isoformat()}/")
        sezione = next(s for s in r.context["sezioni"] if s["tipo"]["id"] == "Fatture spese del giorno")
        self.assertTrue(sezione["obbligatoria"])
        self.assertContains(r, "Dati prima nota")
        self.assertContains(r, "Importo: 27,20 €")
        self.assertContains(r, "cassone elettronica acquisto interruttori")


class TestScontriniSospesi(Base):
    def importa_sri(self, *extra):
        cartella = Path(self.archivio) / "share_sri"
        cartella.mkdir(exist_ok=True)
        for f in (DATI / "sri").iterdir():
            shutil.copy(f, cartella)
        for nome, testo in extra:
            (cartella / nome).write_text(testo)
        cond, _ = Condivisione.objects.get_or_create(negozio_id=10, codice_negozio="5048", defaults={"percorso": str(cartella)})
        return importazione.importa_condivisione(cond)

    def test_lettura_dei_file(self):
        from primanota import sri
        a = sri.analizza("CP261016.SRI.Cassa3", (DATI / "sri" / "CP261016.SRI.Cassa3").read_bytes())
        self.assertEqual((a["data_file"], a["cassa"], a["non_lette"]), (date(2026, 10, 16), 3, 0))
        self.assertEqual([e["tipo"] for e in a["eventi"]], ["sospeso", "richiamato", "emesso"])
        self.assertEqual((a["eventi"][0]["importo"], a["eventi"][0]["numero"], str(a["eventi"][0]["ora"])),
                         (Decimal("14.68"), 159, "18:38:47"))
        self.assertEqual(a["eventi"][2]["numero"], 169)   # nuovo numero dello scontrino emesso
        self.assertEqual(sri.data_sospensione("SR030159225.289", date(2026, 10, 16)), date(2026, 10, 16))   # 289° giorno
        self.assertEqual(sri.data_sospensione("SR010001001.365", date(2027, 1, 2)), date(2026, 12, 31))

    def test_importazione_e_stati(self):
        from primanota.models import FileSRI, ScontrinoSospeso
        self.importa_sri()
        self.assertEqual(FileSRI.objects.count(), 5)
        self.assertEqual(ScontrinoSospeso.objects.count(), 8)
        emesso = ScontrinoSospeso.objects.get(identificativo="SR030159225.289")
        self.assertEqual((emesso.stato, emesso.numero_emesso, emesso.importo_emesso, emesso.differenza),
                         ("emesso", 169, Decimal("14.68"), Decimal("0")))
        self.assertEqual(ScontrinoSospeso.objects.filter(richiamato_data__isnull=True).count(), 7)
        # Un richiamo nel file di un altro giorno e di un'altra cassa completa lo scontrino sospeso il 19.
        self.importa_sri(("CP261020.SRI.Cassa2",
                          "RICH.SOSPENSIONE: SR010172326.292 Ora: 090510 Cassa: 2 \n"
                          "FINE RISTAMPA   : SR010172326.292 Ora: 090530 Cassa: 2 Sct: 12 Eur.: 70,00\n"))
        s = ScontrinoSospeso.objects.get(identificativo="SR010172326.292")
        self.assertEqual((s.stato, s.data, s.cassa, s.cassa_emissione, s.emesso_data, s.differenza),
                         ("emesso", date(2026, 10, 19), 1, 2, date(2026, 10, 20), Decimal("1.55")))
        # Rileggere tutto non duplica niente.
        cond = Condivisione.objects.get(negozio_id=10)
        importazione.importa_condivisione(cond, completa=True)
        self.assertEqual(ScontrinoSospeso.objects.count(), 8)

    def test_pagina(self):
        self.importa_sri()
        uff = self.client_per("ufficio@x")
        r = uff.get("/primanota/sospesi/", {"data_da": "2026-10-01", "data_a": "2026-10-31"})
        self.assertEqual(r.context["riepilogo"]["sospeso"]["numero"], 7)
        self.assertEqual(r.context["riepilogo"]["emesso"]["importo"], Decimal("14.68"))
        self.assertContains(r, "⚠ Ancora sospeso")
        r = uff.get("/primanota/sospesi/", {"data_da": "2026-10-01", "data_a": "2026-10-31", "stato": "emesso"})
        self.assertEqual([s.identificativo for s in r.context["righe"]], ["SR030159225.289"])
        r = uff.get("/primanota/giornata/10/2026-10-16/")
        self.assertContains(r, "Scontrini sospesi (4)")
        self.assertContains(r, "✓ Emesso 16/10 18:47 · scontrino 169")
        self.assertEqual(self.client_per("pv@x").get("/primanota/sospesi/").status_code, 302)


class TestContenutoScontriniSospesi(Base):
    """Il sospeso del SRI è il documento 0002 del SysSpy di prova (28/05/2026, cassa 1), emesso poi come 0003."""

    SRI = ("SOSP.SCONTRINO  : SR010002113.148 Ora: 113300 Cassa: 1 Sct: 0002 Eur.: 5,40\n"
           "SOSP.SCONTRINO  : SR010009999.148 Ora: 170000 Cassa: 1 Sct: 0099 Eur.: 9,99\n")

    def prepara(self, emesso=True):
        cartella = Path(self.archivio) / "share"
        cartella.mkdir()
        shutil.copy(DATI / "SysSpy.20260528.1", cartella)
        testo = self.SRI + ("RICH.SOSPENSIONE: SR010002113.148 Ora: 115900 Cassa: 1 \n"
                            "FINE RISTAMPA   : SR010002113.148 Ora: 120000 Cassa: 1 Sct: 3 Eur.: 0,00\n" if emesso else "")
        (cartella / "CP260528.SRI.Cassa1").write_text(testo)
        importazione.importa_condivisione(Condivisione.objects.create(negozio_id=10, codice_negozio="5048", percorso=str(cartella)))

    def test_affiancati_e_righe_evidenziate(self):
        from primanota.models import ScontrinoSospeso
        self.prepara()
        s = ScontrinoSospeso.objects.get(identificativo="SR010002113.148")
        uff = self.client_per("ufficio@x")
        d = uff.get(f"/primanota/sospesi/{s.id}/scontrini/").json()
        self.assertTrue(d["sospeso"]["trovato"])
        self.assertIn("SCONTRINO ANNULLATO", d["sospeso"]["testo"])
        self.assertIn("DOC.1104-0002", d["sospeso"]["testo"])
        self.assertTrue(d["emesso"]["trovato"])
        self.assertIn("DOC.1104-0003", d["emesso"]["testo"])
        # Quello senza SysSpy corrispondente dice perché manca.
        altro = ScontrinoSospeso.objects.get(identificativo="SR010009999.148")
        d = uff.get(f"/primanota/sospesi/{altro.id}/scontrini/").json()
        self.assertFalse(d["sospeso"]["trovato"])
        self.assertNotIn("emesso", d)
        r = uff.get("/primanota/sospesi/", {"data_da": "2026-05-01", "data_a": "2026-05-31"})
        # Cassiere: il documento sospeso non ha «CASSIERE nnn» né il nome stampato, quindi si prende quello
        # dello scontrino precedente della stessa cassa (con «?»); il documento 99 non è nel SysSpy.
        self.assertEqual({x.numero: x.cassiere for x in r.context["righe"]}, {2: "MARIO ROSSI ?", 99: ""})
        self.assertContains(r, "<th>Cassiere</th>")
        self.assertContains(r, 'class="r-emesso"')
        self.assertContains(r, 'class="r-sospeso"')

    def test_pdf_degli_ancora_sospesi(self):
        import pymupdf
        self.prepara(emesso=False)
        r = self.client_per("ufficio@x").get("/primanota/sospesi/", {"data_da": "2026-05-01", "data_a": "2026-05-31",
                                                                     "stato": "sospeso", "formato": "pdf", "per_pagina": 4})
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("Scontrini_sospesi_Tutti_i_negozi_dal_2026-05-01_al_2026-05-31_Ancora_sospesi.pdf", r["Content-Disposition"])
        testo = " ".join("".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf")).split())
        self.assertIn("5048 - Motta S. Anastasia", testo)
        self.assertIn("TEPELENE ACQUA NAT.P", testo)   # il contenuto dello scontrino sospeso
        self.assertIn("documento 2", testo)
        self.assertIn("Scontrino non trovato nel SysSpy", testo)   # il secondo non ha documento


def sysspy_abortita(giorno, cassa):
    """SysSpy minimo con una transazione abortita vera (senza sospensione dello scontrino)."""
    testo = sysspy_scontrini(giorno, cassa, [(7, "10:15", [("POWERADE M.BLAST ZER", "1,25")])])
    return testo.replace(f"8232 {giorno} 10:15", f"1600              OPERAZIONE ABORTITA\n8232 {giorno} 10:15")


def sysspy_scontrini(giorno, cassa, scontrini):
    """SysSpy minimo: scontrini (numero, «HH:MM», [(articolo, importo)]) di una cassa in un giorno «gg/mm/aaaa»."""
    righe = []
    for numero, ora, articoli in scontrini:
        totale = sum(Decimal(i.replace(",", ".")) for _, i in articoli)
        righe += ["8232                  TO.CAL. SRL", f"8232                    CASSA {cassa:02d}",
                  "8232                                           Euro"]
        righe += [f"8233    {a:<20}{i:>19}" for a, i in articoli]
        righe += ["8236 ----------------------------------------------",
                  f"8236 TOTALE EURO{str(totale).replace('.', ','):>35}",
                  f"8243 CASSA{str(totale).replace('.', ','):>41}", "8232 CASSIERE 200",
                  f"8232 {giorno} {ora}                 DOC.1105-{numero:04d}", "8232 "]
    return "\n".join(righe) + "\n"


class TestRibattuti(Base):
    """Sospeso: documento 0002 del 28/05 cassa 1 (TEPELENE ACQUA NAT.P 5,40, alle 11:33), mai richiamato."""

    def importa(self, *file_extra):
        cartella = Path(self.archivio) / "share"
        cartella.mkdir()
        shutil.copy(DATI / "SysSpy.20260528.1", cartella)
        (cartella / "CP260528.SRI.Cassa1").write_text("SOSP.SCONTRINO  : SR010002113.148 Ora: 113300 Cassa: 1 Sct: 0002 Eur.: 5,40\n")
        for nome, testo in file_extra:
            (cartella / nome).write_text(testo)
        importazione.importa_condivisione(Condivisione.objects.create(negozio_id=10, codice_negozio="5048", percorso=str(cartella)))
        from primanota.models import ScontrinoSospeso
        return ScontrinoSospeso.objects.get(identificativo="SR010002113.148")

    def test_ribattuto_il_giorno_dopo_su_un_altra_cassa(self):
        s = self.importa(("SysSpy.20260529.2", sysspy_scontrini("29/05/2026", 2, [
            (9, "08:40", [("TEPELENE ACQUA NAT.P", "5,50")]),      # stessi articoli, totale diverso: meno buono
            (10, "09:05", [("TEPELENE ACQUA NAT.P", "5,40")])])))   # stesso totale e stesso articolo
        self.assertEqual((s.stato, s.rib_data, s.rib_cassa, s.rib_numero, s.rib_importo),
                         ("ribattuto", date(2026, 5, 29), 2, 10, Decimal("5.40")))
        self.assertEqual(s.rib_motivo, "stesso totale e stessi articoli")
        self.assertEqual([a["numero"] for a in s.rib_altri], ["9"])
        # Nella pagina: stato, scontrino ribattuto affiancato, escluso dal PDF degli ancora sospesi.
        uff = self.client_per("ufficio@x")
        r = uff.get("/primanota/sospesi/", {"data_da": "2026-05-01", "data_a": "2026-05-31"})
        self.assertContains(r, "↻ Ribattuto a mano")
        self.assertContains(r, 'class="r-ribattuto"')
        d = uff.get(f"/primanota/sospesi/{s.id}/scontrini/").json()
        self.assertIn("Ribattuto · cassa 2 · scontrino 10", d["emesso"]["titolo"])
        self.assertIn("DOC.1105-0010", d["emesso"]["testo"])
        r = uff.get("/primanota/sospesi/", {"data_da": "2026-05-01", "data_a": "2026-05-31", "stato": "sospeso"})
        self.assertEqual(r.context["righe"], [])

    def test_probabili(self):
        # Due scontrini uguali: probabilmente ribattuto (il primo dopo la sospensione), con l'altro candidato.
        s = self.importa(("SysSpy.20260528.3", sysspy_scontrini("28/05/2026", 3, [
            (5, "11:00", [("TEPELENE ACQUA NAT.P", "5,40")]),       # prima della sospensione: non conta
            (6, "11:50", [("TEPELENE ACQUA NAT.P", "5,40")]),
            (7, "12:30", [("TEPELENE ACQUA NAT.P", "5,40")])])))
        self.assertEqual((s.stato, s.rib_numero), ("probabile", 6))
        self.assertIn("più scontrini uguali", s.rib_motivo)
        self.assertEqual([a["numero"] for a in s.rib_altri], ["7"])

    def test_totale_diverso_con_gli_stessi_articoli(self):
        s = self.importa(("SysSpy.20260529.2", sysspy_scontrini("29/05/2026", 2, [
            (10, "09:05", [("TEPELENE ACQUA NAT.P", "5,50")]),
            (11, "09:10", [("FINDUS 18 BAST.NUOVA", "5,40")])])))   # stesso totale ma nessun articolo in comune
        # Lo scontrino con lo stesso totale ma senza articoli in comune non è un candidato.
        self.assertEqual((s.stato, s.rib_numero, s.rib_importo), ("probabile", 10, Decimal("5.50")))
        self.assertEqual(s.rib_motivo, "totale diverso, 98% di articoli in comune")
        self.assertEqual(s.rib_altri, [])

    def test_stesso_articolo_in_quantita_diversa(self):
        # Sospesi 6 pezzi (5,40), il giorno dopo uno solo dello stesso articolo (0,90): non è ribattuto.
        s = self.importa(("SysSpy.20260529.2", sysspy_scontrini("29/05/2026", 2, [
            (10, "18:26", [("TEPELENE ACQUA NAT.P", "0,90")])])))
        self.assertEqual((s.stato, s.ribattuto), ("sospeso", ""))

    def test_solo_una_parte_in_comune(self):
        # Il 64% in comune (un articolo grande uguale, gli altri diversi) non basta.
        s = self.importa(("SysSpy.20260529.2", sysspy_scontrini("29/05/2026", 2, [
            (10, "09:05", [("TEPELENE ACQUA NAT.P", "5,40"), ("PANE", "1,50"), ("LATTE", "1,54")])])))
        self.assertEqual((s.stato, s.ribattuto), ("sospeso", ""))

    def test_niente_di_simile(self):
        s = self.importa(("SysSpy.20260529.2", sysspy_scontrini("29/05/2026", 2, [
            (10, "09:05", [("PANE", "1,20"), ("LATTE", "1,50")]),
            (11, "09:10", [("GRANAROLO IL QUATTRO", "1,94"), ("OLIVE NERE GRECHE MA", "3,46")])])))   # stesso totale, altri articoli
        self.assertEqual((s.stato, s.ribattuto), ("sospeso", ""))


class TestComandoRibattuti(Base):
    importa = TestRibattuti.importa

    def test_ricalcolo_da_riga_di_comando(self):
        from io import StringIO
        from django.core.management import call_command
        from primanota.models import ScontrinoSospeso
        s = self.importa(("SysSpy.20260529.2", sysspy_scontrini("29/05/2026", 2, [(10, "09:05", [("TEPELENE ACQUA NAT.P", "5,40")])])))
        ScontrinoSospeso.objects.filter(pk=s.pk).update(ribattuto="")
        uscita = StringIO()
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 6, 30)):
            call_command("importa_sysspy", "--ribattuti", stdout=uscita)
        self.assertIn("5048: ribattuti ricalcolati", uscita.getvalue())
        self.assertEqual(ScontrinoSospeso.objects.get(pk=s.pk).stato, "ribattuto")


class TestFileSR(Base):
    def test_lettura(self):
        from primanota import sr_file
        a = sr_file.analizza("SR010127317.289", (DATI / "sr_cassa" / "SR010127317.289").read_bytes())
        self.assertEqual((a["identificativo"], a["richiamato"], len(a["articoli"]), a["totale_lordo"]),
                         ("SR010127317.289", False, 9, Decimal("26.47")))   # il file SRI dice 25,77: 0,70 di promozioni
        salsiccia = a["articoli"][4]
        self.assertEqual((salsiccia["descrizione"], salsiccia["reparto"], salsiccia["importo"], salsiccia["peso"], salsiccia["unita"]),
                         ("SALSICCIA COND.PROV/", "CARNE", "3.82", 0.386, "KG"))
        self.assertEqual(sr_file.identificativo("SR030159225.289.RICH"), ("SR030159225.289", True))
        self.assertFalse(sr_file.nome_valido("CP261016.SRI.Cassa1"))

    def prepara(self):
        share, cartella_sr = Path(self.archivio) / "share", Path(self.archivio) / "sr"
        share.mkdir()
        shutil.copytree(DATI / "sr_cassa", cartella_sr)
        for f in (DATI / "sri").iterdir():
            shutil.copy(f, share)
        cond = Condivisione.objects.create(negozio_id=10, codice_negozio="5034", percorso=str(share), percorso_sospesi=str(cartella_sr))
        return cond, cartella_sr

    def test_importazione_stato_in_cassa_e_contenuto(self):
        from primanota.models import FileSR, ScontrinoSospeso
        cond, cartella_sr = self.prepara()
        importazione.importa_condivisione(cond)
        cond.refresh_from_db()
        self.assertIn("file SR: 3 in cassa", cond.ultimo_esito)
        stati = dict(ScontrinoSospeso.objects.values_list("identificativo", "in_cassa"))
        self.assertEqual((stati["SR010127317.289"], stati["SR030159225.289"], stati["SR010083341.289"]), ("attesa", "richiamato", ""))
        # La cassa cancella un file: resta nell'archivio del portale, segnato come non più presente.
        (cartella_sr / "SR010127317.289").unlink()
        importazione.importa_condivisione(cond)
        f = FileSR.objects.get(identificativo="SR010127317.289")
        self.assertEqual((f.presente, f.stato_in_cassa, bool(f.scomparso_il), Path(f.percorso_archivio).is_file()),
                         (False, "rimosso", True, True))
        self.assertEqual(ScontrinoSospeso.objects.get(identificativo="SR010127317.289").in_cassa, "rimosso")
        # Senza SysSpy di quel giorno lo scontrino sospeso si ricostruisce dal file SR.
        s = ScontrinoSospeso.objects.get(identificativo="SR010051105.289")
        uff = self.client_per("ufficio@x")
        d = uff.get(f"/primanota/sospesi/{s.id}/scontrini/").json()
        self.assertTrue(d["sospeso"]["trovato"])
        self.assertIn("Dal file SR della cassa", d["sospeso"]["testo"])
        self.assertIn("SALSICCIA COND.PROV/", d["sospeso"]["testo"])
        self.assertEqual(d["sospeso"]["file_sr"]["stato"], "in attesa di richiamo")
        r = uff.get("/primanota/sospesi/", {"data_da": "2026-10-01", "data_a": "2026-10-31"})
        self.assertContains(r, "<th>In cassa</th>")
        self.assertContains(r, "non più presente")

    def test_richiamato_in_cassa_senza_riga_nel_sri(self):
        from primanota.models import ScontrinoSospeso
        cond, cartella_sr = self.prepara()
        (cartella_sr / "SR010051105.289").rename(cartella_sr / "SR010051105.289.RICH")
        importazione.importa_condivisione(cond)
        s = ScontrinoSospeso.objects.get(identificativo="SR010051105.289")
        self.assertEqual((s.richiamato_data, s.in_cassa, s.stato), (None, "richiamato", "richiamato"))

    def test_impostazione_della_cartella(self):
        self.client_per("admin@x").post("/primanota/condivisioni/", {"negozio_id": 10, "percorso": r"\\192.168.1.50\SysSpy",
                                                                      "percorso_sospesi": r"\\192.168.1.50\Sospesi", "attiva": "on"})
        self.assertEqual(Condivisione.objects.get(negozio_id=10).percorso_sospesi, r"\\192.168.1.50\Sospesi")
        self.assertContains(self.client_per("admin@x").get("/primanota/condivisioni/"), "Cartella sospesi (SR)")


    def test_rich_e_file_in_attesa_insieme(self):
        from primanota.models import FileSR, ScontrinoSospeso
        cond, cartella_sr = self.prepara()
        importazione.importa_condivisione(cond)
        self.assertEqual(ScontrinoSospeso.objects.get(identificativo="SR010051105.289").in_cassa, "attesa")
        # La cassa crea il .RICH prima di cancellare l'altro: vale il .RICH, in qualunque ordine arrivino.
        shutil.copy(cartella_sr / "SR010051105.289", cartella_sr / "SR010051105.289.RICH")
        importazione.importa_condivisione(cond)
        f = FileSR.objects.get(identificativo="SR010051105.289")
        self.assertEqual((f.richiamato, f.nome), (True, "SR010051105.289.RICH"))
        self.assertEqual(ScontrinoSospeso.objects.get(identificativo="SR010051105.289").stato, "richiamato")
        # Poi la cassa cancella tutti e due: resta «richiamato».
        (cartella_sr / "SR010051105.289").unlink()
        (cartella_sr / "SR010051105.289.RICH").unlink()
        importazione.importa_condivisione(cond)
        f.refresh_from_db()
        self.assertEqual((f.presente, f.stato_in_cassa), (False, "richiamato"))
        self.assertEqual(ScontrinoSospeso.objects.get(identificativo="SR010051105.289").in_cassa, "richiamato")


class TestRiprovaDatabaseOccupato(SimpleTestCase):
    def test_riprova_se_locked(self):
        from django.db import OperationalError
        from primanota.services import importazione
        chiamate = []

        def funzione():
            chiamate.append(1)
            if len(chiamate) < 3:
                raise OperationalError("database is locked")
            return "ok"

        with mock.patch.object(importazione.time, "sleep"):
            self.assertEqual(importazione._con_riprova(funzione), "ok")
        self.assertEqual(len(chiamate), 3)

    def test_altri_errori_subito(self):
        from django.db import OperationalError
        from primanota.services import importazione

        def funzione():
            raise OperationalError("no such table")

        with self.assertRaises(OperationalError):
            importazione._con_riprova(funzione)


class TestStatoGiornata(Base):
    def cella(self, giorno, versamenti=False):
        url = "/primanota/versamenti/monitor/" if versamenti else "/primanota/monitor/"
        r = self.client_per("direttore@x").get(url, {"anno": giorno.year, "mese": giorno.month})
        riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
        return next(c for c in riga["cells"] if c["date"] == giorno.isoformat())

    def test_lavorato_della_giornata_intera_e_reversibile(self):
        ieri = date.today() - timedelta(days=1)
        self.scansione_sede("Chiusura fiscale", giorno=ieri.isoformat())
        self.scansione_sede("Resi", giorno=ieri.isoformat())
        uff = self.client_per("ufficio@x")
        self.assertEqual(self.cella(ieri)["state"], "incomplete")
        r = uff.post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/", {"stato": "lavorato"})
        self.assertRedirects(r, f"/primanota/giornata/10/{ieri.isoformat()}/", fetch_redirect_response=False)
        self.assertEqual(self.cella(ieri)["state"], "worked")
        # Le scansioni della giornata seguono il lavorato (il negozio non può più cancellarle).
        self.assertTrue(all(x["Lavorato"] for x in self.baserow.righe.values()))
        pagina = uff.get(f"/primanota/giornata/10/{ieri.isoformat()}/")
        self.assertContains(pagina, "Riporta da lavorare")
        uff.post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/", {"stato": "non_lavorato"})
        self.assertEqual(self.cella(ieri)["state"], "incomplete")
        self.assertFalse(any(x["Lavorato"] for x in self.baserow.righe.values()))
        uff.post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/", {"stato": "chiusura"})
        self.assertEqual(self.cella(ieri)["state"], "closed")
        # Il negozio non cambia lo stato.
        self.assertEqual(self.client_per("pv@x").post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/",
                                                      {"stato": "lavorato"}).status_code, 302)
        from primanota.models import GiornataLavorazione
        # «Giornata chiusura» vale per chiusure e versamenti.
        self.assertEqual(sorted(GiornataLavorazione.objects.values_list("sezione", "stato")),
                         [("chiusure", "chiusura"), ("versamenti", "chiusura")])

    def test_versamenti_lavorati_per_giornata(self):
        ieri = date.today() - timedelta(days=1)
        self.carica(self.client_per("pv@x"), "Versamenti contante", giorno=ieri.isoformat())
        uff = self.client_per("ufficio@x")
        pagina = uff.get("/primanota/versamenti/", {"data_da": ieri.isoformat()})
        self.assertEqual(len(pagina.context["scansioni"]), 1)
        self.assertContains(pagina, 'name="sezione" value="versamenti"')
        self.assertEqual(self.cella(ieri, versamenti=True)["state"], "pending")
        uff.post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/", {"stato": "lavorato", "sezione": "versamenti"})
        self.assertEqual(self.cella(ieri, versamenti=True)["state"], "worked")
        self.assertTrue(all(x["Versamento Lavorato"] for x in self.baserow.righe.values()))
        # Le Chiusure Fiscali della stessa giornata restano da lavorare.
        from primanota.models import GiornataLavorazione
        self.assertEqual(list(GiornataLavorazione.objects.values_list("sezione", flat=True)), ["versamenti"])
        self.assertEqual(uff.get("/primanota/versamenti/", {"data_da": ieri.isoformat(), "solo_da_lavorare": "on"}).context["scansioni"], [])
        uff.post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/", {"stato": "non_lavorato", "sezione": "versamenti"})
        self.assertEqual(self.cella(ieri, versamenti=True)["state"], "pending")
        self.assertFalse(any(x["Versamento Lavorato"] for x in self.baserow.righe.values()))

    def test_elenco_solo_giornate_da_lavorare(self):
        ieri = (date.today() - timedelta(days=1)).isoformat()
        self.scansione_sede("Chiusura fiscale", giorno=ieri)
        uff = self.client_per("ufficio@x")
        self.assertEqual(len(uff.get("/primanota/admin/").context["giornate"]), 1)
        uff.post(f"/primanota/giornata/10/{ieri}/stato/", {"stato": "lavorato", "ritorno": "/primanota/admin/"})
        self.assertEqual(uff.get("/primanota/admin/").context["giornate"], [])

    def test_pregresso_come_giornata_chiusura(self):
        ieri = date.today() - timedelta(days=1)
        with override_settings(PRIMANOTA_INIZIO_GESTIONE=date.today().isoformat()):
            self.assertEqual(self.cella(ieri)["state"], "closed")
            self.assertEqual(self.cella(ieri, versamenti=True)["state"], "closed")
            # Il pregresso con scansioni inviate dal negozio resta da lavorare, anche nell'elenco.
            self.scansione_sede("Chiusura fiscale", giorno=ieri.isoformat())
            self.carica(self.client_per("pv@x"), "Versamenti contante", giorno=ieri.isoformat())
            self.assertEqual(self.cella(ieri)["state"], "incomplete")
            self.assertEqual(self.cella(ieri, versamenti=True)["state"], "pending")
            self.assertEqual(len(self.client_per("ufficio@x").get("/primanota/admin/").context["giornate"]), 1)
            self.assertEqual(self.cella(ieri - timedelta(days=1))["state"], "closed")
            # Lo stato si può comunque cambiare a mano.
            self.client_per("ufficio@x").post(f"/primanota/giornata/10/{ieri.isoformat()}/stato/", {"stato": "chiusura"})
            self.assertEqual(self.cella(ieri)["state"], "closed")

    def test_chiusure_fiscali_si_apre_sul_monitor(self):
        uff = self.client_per("ufficio@x")
        self.assertContains(uff.get("/primanota/"), 'href="/primanota/monitor/"')
        self.assertContains(uff.get("/primanota/"), 'href="/primanota/versamenti/monitor/"')
        self.assertRedirects(uff.get("/primanota/upload/"), "/primanota/monitor/", fetch_redirect_response=False)


class TestPrimaNotaPrimaDelleScansioni(Base):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def prima_nota(self, righe):
        movimento = {"progressivo": 335830, "ora": "185501", "causale": 9, "importo": Decimal("47.50"), "segno": "-",
                     "causale_descr": "PAGAMENTO FORNITORI", "data_cert": None}

        def esegui(c, sql, parametri=(), dizionari=False):
            if "COUNT(*)" in sql:
                return righe
            return [movimento] if righe and righe[0][5] else []
        return mock.patch.multiple("primanota.services.prima_nota", esegui=esegui, configurazione=lambda: {"host": "x"})

    def test_scansioni_solo_con_la_prima_nota_certificata(self):
        pv = self.client_per("pv@x")
        dati = {"data_documento": "2026-05-28", "documento_fiscale": self.pdf(), "documento_pos": self.pdf(),
                "documento_versamenti": self.pdf()}
        with self.prima_nota([]):
            self.assertContains(pv.get("/primanota/upload/", {"data": "2026-05-28"}), "non è ancora presente")
            r = pv.post("/primanota/upload/", dati)
            self.assertContains(r, "compila e certifica prima la prima nota")
            # La sola nota si salva comunque.
            self.assertEqual(pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "tipo_nota": "ANOMALIA", "note": "manca la prima nota"}).status_code, 302)
        from django.core.cache import cache
        cache.clear()
        with self.prima_nota([("5048", 20260528, 12, 0, Decimal("0"), 3)]):   # 3 movimenti non certificati
            self.assertContains(pv.post("/primanota/upload/", dict(dati, documento_fiscale=self.pdf(),
                                                                   documento_pos=self.pdf(), documento_versamenti=self.pdf())),
                                "non è ancora certificata")
            self.assertContains(pv.get("/primanota/upload/", {"data": "2026-05-28"}),
                                "Movimenti senza certificazione: n. 335830 delle 18:55:01 PAGAMENTO FORNITORI 47,50 €")
        self.assertEqual(self.baserow.righe, {})
        cache.clear()
        cache.clear()
        # Il conteggio dei non certificati esclude le righe senza causale (causale 0).
        from primanota.services import prima_nota as servizio
        self.assertIn("ISNULL(r.causale, 0) <> 0", servizio.QUERY_PRESENZE)
        with self.prima_nota([("5048", 20260528, 12, 0, Decimal("0"), 0)]):
            r = pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "documento_fiscale": self.pdf(),
                                               "documento_pos": self.pdf(), "documento_versamenti": self.pdf(),
                                               "tipo_nota": "ANOMALIA", "note": "ok"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.baserow.righe), 3)
        # La nota è una sola, non copiata su ogni allegato.
        self.assertEqual({x["Note"] for x in self.baserow.righe.values()}, {""})
        self.assertEqual(Nota.objects.filter(testo="ok").count(), 1)


class TestAllegatiLeggeri(SimpleTestCase):
    def test_pdf_pesante_alleggerito(self):
        import pymupdf
        from primanota.services.allegati import ottimizza
        riga = bytes(range(256)) * 29 + bytes(2480 * 3 - 256 * 29)
        pix = pymupdf.Pixmap(pymupdf.csRGB, 2480, 3508, riga * 3508, False)
        doc = pymupdf.open()
        pagina = doc.new_page(width=595, height=842)
        pagina.insert_image(pagina.rect, stream=pix.tobytes("jpeg", jpg_quality=95))   # scansione a 300 dpi
        originale = SimpleUploadedFile("scan.pdf", doc.tobytes(), content_type="application/pdf")
        leggero = ottimizza(originale)
        self.assertLess(leggero.size, originale.size)
        self.assertEqual(pymupdf.open(stream=leggero.read(), filetype="pdf").page_count, 1)

    def test_piccoli_e_immagini_restano_uguali(self):
        from primanota.services.allegati import ottimizza
        piccolo = SimpleUploadedFile("scan.pdf", b"%PDF-1.4", content_type="application/pdf")
        self.assertIs(ottimizza(piccolo), piccolo)
        foto = SimpleUploadedFile("foto.jpg", b"x" * 400000, content_type="image/jpeg")
        self.assertIs(ottimizza(foto), foto)


class TestSpazioDisco(Base):
    def test_indicatore_in_impostazioni(self):
        r = self.client_per("direttore@x").get("/primanota/condivisioni/", {"disco": "aggiorna"})
        self.assertContains(r, "Spazio su disco del server")
        disco = r.context["disco"]
        self.assertTrue(disco["dischi"])
        self.assertIn("Archivio SysSpy e allegati", [n for d in disco["dischi"] for n in d["nomi"]])
        from primanota.services.disco import _livello
        self.assertEqual([_livello(50), _livello(85), _livello(95)], ["ok", "attenzione", "critico"])


class TestEmergenza(Base):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def prima_nota(self, righe):
        def esegui(c, sql, parametri=(), dizionari=False):
            return righe if "COUNT(*)" in sql else []
        return mock.patch.multiple("primanota.services.prima_nota", esegui=esegui, configurazione=lambda: {"host": "x"})

    def test_emergenza_senza_prima_nota(self):
        from primanota.models import Emergenza
        self.importa_fixture()
        ieri = date.today() - timedelta(days=1)
        pv = self.client_per("pv@x")
        with self.prima_nota([]):
            pagina = pv.get("/primanota/upload/", {"data": ieri.isoformat()})
            self.assertContains(pagina, "Attiva Emergenza")
            # Senza motivo non si attiva.
            r = pv.post("/primanota/upload/", {"azione": "emergenza", "data": ieri.isoformat(), "motivo": " "})
            self.assertContains(r, "scrivi il motivo")
            pv.post("/primanota/upload/", {"azione": "emergenza", "data": ieri.isoformat(), "motivo": "gestionale fermo"})
            self.assertEqual(Emergenza.objects.get().motivo, "gestionale fermo")
            self.assertTrue(Nota.objects.filter(tipo="ANOMALIA", testo__contains="gestionale fermo").exists())
            pagina = pv.get("/primanota/upload/", {"data": ieri.isoformat()})
            self.assertContains(pagina, "Modalità Emergenza attiva")
            self.assertIsNone(pagina.context["blocco_prima_nota"])
            # Le voci «solo se la giornata ne contiene» diventano tutte caricabili, non obbligatorie.
            stati = {v["tipo"]["id"]: v["stato"] for v in pagina.context["voci"]}
            self.assertEqual((stati["Resi"], stati["Transazioni abortite"], stati["Fatture spese del giorno"]),
                             ("in_attesa", "in_attesa", "in_attesa"))
            self.assertEqual(stati["Chiusura fiscale"], "obbligatoria")
            r = pv.post("/primanota/upload/", {"data_documento": ieri.isoformat(), "documento_fiscale": self.pdf(),
                                               "documento_pos": self.pdf(), "documento_versamenti": self.pdf(),
                                               "documento_resi": self.pdf()})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(len(self.baserow.righe), 4)
            # Monitor della sede: giallo lampeggiante su chiusure e versamenti.
            for url in ("/primanota/monitor/", "/primanota/versamenti/monitor/"):
                r = self.client_per("direttore@x").get(url, {"anno": ieri.year, "mese": ieri.month})
                riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
                cella = next(c for c in riga["cells"] if c["date"] == ieri.isoformat())
                self.assertEqual((cella["state"], cella["emergenza"]), ("emergency", "gestionale fermo"))
        from django.core.cache import cache
        cache.clear()
        # Arrivata la prima nota, il giallo si spegne.
        with self.prima_nota([("5048", int(ieri.strftime("%Y%m%d")), 12, 0, Decimal("0"), 0)]):
            r = self.client_per("direttore@x").get("/primanota/monitor/", {"anno": ieri.year, "mese": ieri.month})
            riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
            self.assertNotEqual(next(c for c in riga["cells"] if c["date"] == ieri.isoformat())["state"], "emergency")


class TestRielaboraPeriodo(Base):
    def test_dall_archivio_solo_negozio_e_giorni_scelti(self):
        from primanota import sysspy as modulo
        self.importa_fixture()
        f = FileSysSpy.objects.get()
        self.assertEqual(f.versione_analisi, modulo.VERSIONE_ANALISI)
        f.chiusura_pos = ""
        f.save(update_fields=["chiusura_pos"])
        # Fuori periodo non si tocca niente, anche se il file è già alla versione attuale.
        importazione.rielabora_archivio(10, processi=1, periodo=(date(2026, 5, 29), date(2026, 5, 30)))
        self.assertEqual(FileSysSpy.objects.get().chiusura_pos, "")
        importazione.rielabora_archivio(10, processi=1, periodo=(date(2026, 5, 28), date(2026, 5, 28)))
        self.assertIn("TOTALE POS EUR", FileSysSpy.objects.get().chiusura_pos)

    def test_dalle_casse_solo_i_file_del_periodo(self):
        cond, cartella, _ = self.importa_fixture()
        (cartella / "SysSpy.20260529.2").write_text(sysspy_scontrini("29/05/2026", 2, [(1, "10:00", [("PANE", "1,20")])]))
        stato = importazione.importa_condivisione(cond, periodo=(date(2026, 5, 28), date(2026, 5, 28)))
        # Il file del 28 si rilegge (anche se già archiviato), quello del 29 resta fuori.
        self.assertEqual((stato["esaminati"], stato["importati"]), (1, 1))
        self.assertFalse(FileSysSpy.objects.filter(data=date(2026, 5, 29)).exists())

    def test_pagina_impostazioni(self):
        self.importa_fixture()
        r = self.client_per("direttore@x").post("/primanota/condivisioni/rielabora-periodo/",
                                                {"negozio": "10", "dal": "2026-05-29", "al": "2026-05-28", "fonte": "archivio"})
        self.assertRedirects(r, "/primanota/condivisioni/?errore_periodo=1", fetch_redirect_response=False)
        with mock.patch("primanota.services.importazione.avvia_rielaborazione_in_background", return_value="x") as avvia:
            r = self.client_per("direttore@x").post("/primanota/condivisioni/rielabora-periodo/",
                                                    {"negozio": "10", "dal": "2026-05-28", "al": "2026-05-28", "fonte": "archivio"})
        self.assertRedirects(r, "/primanota/importazione/x/", fetch_redirect_response=False)
        self.assertEqual(avvia.call_args[0][:2], (10, (date(2026, 5, 28), date(2026, 5, 28))))
        with mock.patch("primanota.services.importazione.avvia_in_background", return_value="y") as avvia:
            self.client_per("direttore@x").post("/primanota/condivisioni/rielabora-periodo/",
                                                {"negozio": "10", "dal": "2026-05-28", "al": "2026-05-28", "fonte": "casse"})
        self.assertEqual(avvia.call_args[1]["periodo"], (date(2026, 5, 28), date(2026, 5, 28)))
        self.assertEqual(self.client_per("ufficio@x").post("/primanota/condivisioni/rielabora-periodo/", {}).status_code, 403)


class TestModificaNote(Base):
    def test_il_negozio_corregge_o_elimina_le_sue_note_aperte(self):
        nota = Nota.objects.create(negozio_id=10, data="2026-05-28", tipo=Nota.ANOMALIA, testo="prima", creata_da="Utente 1")
        pv = self.client_per("pv@x")
        self.assertContains(pv.get("/primanota/upload/"), "Modifica o elimina")
        pv.post(f"/primanota/note/{nota.id}/modifica/", {"testo": "corretta"})
        nota.refresh_from_db()
        self.assertEqual(nota.testo, "corretta")
        self.assertIsNotNone(nota.modificata_il)
        # Un altro negozio e l'ufficio no; una nota già lavorata nemmeno.
        self.assertEqual(self.client_per("altro_pv@x").post(f"/primanota/note/{nota.id}/elimina/").status_code, 403)
        self.assertEqual(self.client_per("ufficio@x").post(f"/primanota/note/{nota.id}/elimina/").status_code, 403)
        nota.chiusa = True
        nota.save()
        self.assertEqual(pv.post(f"/primanota/note/{nota.id}/modifica/", {"testo": "x"}).status_code, 403)
        self.assertNotContains(pv.get("/primanota/upload/"), "Modifica o elimina")
        nota.chiusa = False
        nota.save()
        r = pv.post(f"/primanota/note/{nota.id}/elimina/", {"ritorno": "/primanota/giornata/10/2026-05-28/"})
        self.assertRedirects(r, "/primanota/giornata/10/2026-05-28/", fetch_redirect_response=False)
        self.assertFalse(Nota.objects.exists())

    def test_nota_sul_versamento_gia_inviata_manda_la_rettifica(self):
        from primanota.models import DestinatarioEmail
        DestinatarioEmail.objects.create(nome="Amministrazione", email="amm@x.it")
        pv = self.client_per("pv@x")
        with mock.patch("primanota.services.posta.invia") as invia:
            pv.post("/primanota/upload/", {"data_documento": "2026-05-28", "tipo_nota": "VERSAMENTO", "note": "mancano 50"})
            nota = Nota.objects.get()
            pv.post(f"/primanota/note/{nota.id}/modifica/", {"testo": "mancano 20"})
            pv.post(f"/primanota/note/{nota.id}/elimina/")
        oggetti = [c.args[1] for c in invia.call_args_list]
        self.assertEqual(len(oggetti), 3)
        self.assertTrue(oggetti[1].startswith("NOTA MODIFICATA"))
        self.assertIn("Testo inviato in precedenza:\nmancano 50", invia.call_args_list[1].args[2])
        self.assertTrue(oggetti[2].startswith("NOTA ANNULLATA"))
        self.assertFalse(Nota.objects.exists())


CHIUSURA_BPM = """             CHIUSURA
     AMEX
     PAGAMENTI           0,00
     (num. pagamenti 0)
     STORNI              0,00
     ------------------------
     TOTALE EUR          0,00
     Debito
     PAGAMENTI         404,49
     (num. pagamenti 12)
     STORNI              0,00
     ------------------------
     TOTALE EUR        404,49
     CREDITO
     PAGAMENTI         236,86
     (num. pagamenti 9)
     STORNI              0,00
     ------------------------
     TOTALE EUR        236,86
     JCB
     PAGAMENTI          10,00
     (num. pagamenti 1)
     ------------------------
     TOTALE EUR         10,00
     TRANSAZIONI           22
     TOTALE POS
     EUR               651,35"""
CHIUSURA_BPM_CASSA_2 = """             CHIUSURA
     Debito
     Pagamenti EUR       5,00
     (num.pagamenti 1)
     ------------------------
     Totale    EUR       5,00
     (TRANSAZIONI 1)
     TOTALE POS EUR      5,00"""


class TestRaggruppamentiBanche(TestPrimaNota):
    def test_tipologie_dalle_chiusure_pos(self):
        self.assertEqual(sysspy.circuiti_pos(CHIUSURA_BPM), {"AMEX": Decimal("0.00"), "Debito": Decimal("404.49"),
                                                             "CREDITO": Decimal("236.86"), "JCB": Decimal("10.00")})
        self.assertEqual(sysspy.circuiti_pos(CHIUSURA_BPM_CASSA_2), {"Debito": Decimal("5.00")})
        g = sysspy.analizza("SysSpy.20260528.1", (DATI / "SysSpy.20260528.1").read_bytes())["giornate"][0]
        self.assertEqual(sysspy.circuiti_pos(g["chiusure_pos"][0]["testo"]), {"UC Mastercard": Decimal("18.00")})

    def test_banche_predefinite_e_configurazione(self):
        from primanota.models import IstitutoCredito
        self.assertEqual({i.nome: sorted((t.causale, t.descrizione) for t in i.tipologie.all()) for i in IstitutoCredito.objects.all()}, {
            "BANCA BPM": [(4, "Debito"), (5, "AMEX"), (5, "CREDITO")],
            "UNICREDIT": [(4, "BANCOMAT"), (5, "AMERICAN EXPRESS"), (5, "Maestro"), (5, "UC Mastercard"), (5, "UC Visa")]})
        bpm = IstitutoCredito.objects.get(nome="BANCA BPM")
        direttore = self.client_per("direttore@x")
        self.assertEqual(self.client_per("ufficio@x").get("/primanota/banche/").status_code, 403)
        self.assertContains(direttore.get("/primanota/banche/"), "UC Mastercard")
        # Modificabili: tipologie e punti vendita.
        direttore.post("/primanota/banche/", {"istituto": bpm.id, "nome": "BANCA BPM", "causale_5": "AMEX\nCREDITO\n\nJCB",
                                             "causale_4": "Debito", "negozi": ["5048"]})
        self.assertEqual(sorted(bpm.tipologie.values_list("descrizione", flat=True)), ["AMEX", "CREDITO", "Debito", "JCB"])
        self.assertEqual(list(bpm.negozi.values_list("codice_negozio", flat=True)), ["5048"])
        # Un punto vendita ha un solo istituto.
        unicredit = IstitutoCredito.objects.get(nome="UNICREDIT")
        direttore.post("/primanota/banche/", {"istituto": unicredit.id, "nome": "UNICREDIT", "causale_5": "UC Visa",
                                             "causale_4": "BANCOMAT", "negozi": ["5048"]})
        self.assertEqual((bpm.negozi.count(), unicredit.negozi.count()), (0, 1))
        direttore.post("/primanota/banche/", {"azione": "elimina", "istituto": unicredit.id})
        self.assertFalse(IstitutoCredito.objects.filter(nome="UNICREDIT").exists())

    def _sysspy_5040(self):
        from primanota.models import IstitutoCredito, IstitutoNegozio
        IstitutoNegozio.objects.create(codice_negozio="5040", istituto=IstitutoCredito.objects.get(nome="BANCA BPM"))
        for cassa, testo in ((1, CHIUSURA_BPM), (2, CHIUSURA_BPM_CASSA_2)):
            FileSysSpy.objects.create(negozio_id=12, codice_negozio="5040", data=date(2026, 10, 19), cassa=cassa,
                                      nome_file=f"SysSpy.20261019.{cassa}", percorso_origine=f"x{cassa}", percorso_archivio=f"x{cassa}",
                                      percorso_testo=f"x{cassa}", dimensione=1, modificato_il=0, chiusura_pos=testo)

    def test_spaccato_e_confronto_a_video_e_in_stampa(self):
        import pymupdf
        self._sysspy_5040()
        with self.esegui_finto(righe_prima_nota("prima_nota_5040.csv")):
            r = self.client_per("ufficio@x").get("/primanota/prima-nota/", {"pv": "5040", "data": "2026-10-19"})
            pdf = self.client_per("ufficio@x").get("/primanota/prima-nota/", {"formato": "pdf", "dal": "2026-10-19",
                                                                              "al": "2026-10-19", "pv": "5040"})
        causali = {c["codice"]: c for c in r.context["giornata"]["causali"]}
        # Somma delle casse 1 e 2: Debito 404,49 + 5,00; in prima nota la causale 4 è 4,49.
        self.assertEqual(causali[4]["spaccato"], [("Debito", Decimal("409.49"))])
        # La causale resta in Uscite com'è registrata; lo spaccato è la contropartita in Evidenze.
        self.assertEqual((causali[4]["uscite"], causali[4]["colonna_pos"]), (Decimal("4.49"), "evidenze"))
        self.assertEqual(causali[4]["controllo"], {"prima_nota": Decimal("4.49"), "pos": Decimal("409.49"), "differenza": Decimal("-405.00")})
        self.assertEqual(causali[5]["spaccato"], [("CREDITO", Decimal("236.86"))])   # AMEX a zero non compare
        self.assertEqual(causali[5]["controllo"]["differenza"], Decimal("0"))
        self.assertEqual(r.context["giornata"]["pos_non_assegnate"], [("JCB", Decimal("10.00"))])
        self.assertContains(r, "Confronto con Importo da Prima Nota")
        self.assertContains(r, "✓ Coincide")
        self.assertContains(r, "⚠ Differenza")
        testo = " ".join(pymupdf.open(stream=pdf.content, filetype="pdf")[0].get_text().split())
        self.assertIn("CREDITO (chiusure POS)", testo)
        # In stampa il controllo compare solo dove c'è differenza (causale 4), non dove coincide (causale 5).
        self.assertEqual(testo.count("Confronto con Importo da Prima Nota"), 1)
        self.assertIn("DIFFERENZA -405,00", testo)
        self.assertNotIn("Coincide", testo)
        self.assertIn("Tipologie della chiusura POS non assegnate: JCB 10,00", testo)

    def test_punto_vendita_senza_istituto(self):
        with self.esegui_finto(righe_prima_nota("prima_nota_5040.csv")):
            r = self.client_per("ufficio@x").get("/primanota/prima-nota/", {"pv": "5040", "data": "2026-10-19"})
        self.assertContains(r, "non associato a un istituto di credito")
        self.assertNotIn("controllo", {c["codice"]: c for c in r.context["giornata"]["causali"]}[4])


class TestSoloVersamento(Base):
    def cella(self, url, giorno):
        r = self.client_per("direttore@x").get(url, {"anno": giorno.year, "mese": giorno.month})
        riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
        return next(c for c in riga["cells"] if c["date"] == giorno.isoformat())

    def test_niente_da_allegare_nelle_chiusure_e_solo_versamento(self):
        from primanota.models import RegolaDocumento
        for t in ("Chiusura fiscale", "Chiusure POS bancari"):
            RegolaDocumento.objects.create(tipo_documento=t, obbligo=RegolaDocumento.FACOLTATIVO)
        ieri = date.today() - timedelta(days=1)
        self.assertEqual(self.cella("/primanota/monitor/", ieri)["state"], "missing")
        self.carica(self.client_per("pv@x"), "Versamenti contante", giorno=ieri.isoformat())
        # Verde in entrambe le sezioni: nelle chiusure non c'era niente di obbligatorio.
        chiusure = self.cella("/primanota/monitor/", ieri)
        self.assertEqual((chiusure["state"], chiusure["mancanti"]), ("pending", []))
        self.assertEqual(self.cella("/primanota/versamenti/monitor/", ieri)["state"], "pending")
        # Con una scansione obbligatoria nelle chiusure, invece, manca qualcosa (arancio, non rosso).
        RegolaDocumento.objects.filter(tipo_documento="Chiusura fiscale").update(obbligo=RegolaDocumento.SEMPRE)
        chiusure = self.cella("/primanota/monitor/", ieri)
        self.assertEqual((chiusure["state"], chiusure["mancanti"]), ("incomplete", ["Chiusura fiscale"]))


class TestGiustificazioni(Base):
    def importa_con_differenza_pos(self):
        # Chiusura POS di 10,00 contro 18,00 di carte negli scontrini: «Differenza POS».
        cartella = Path(self.archivio) / "share"
        cartella.mkdir()
        testo = (DATI / "SysSpy.20260528.1").read_text(encoding="latin-1").replace(
            "9832     TOTALE POS EUR     18,00", "9832     TOTALE POS EUR     10,00")
        (cartella / "SysSpy.20260528.1").write_text(testo, encoding="latin-1")
        importazione.importa_condivisione(Condivisione.objects.create(negozio_id=10, codice_negozio="5048", percorso=str(cartella)))
        return FileSysSpy.objects.get()

    def test_il_negozio_giustifica_la_differenza_pos(self):
        f = self.importa_con_differenza_pos()
        pos = next(c for c in f.controlli if c["nome"] == "POS")
        self.assertEqual(pos["esito"], "attenzione")
        self.assertFalse(f.quadrato)
        pv = self.client_per("pv@x")
        self.assertContains(pv.get("/primanota/giornata/10/2026-05-28/"), "Punto vendita: spiega alla sede il motivo")
        self.assertContains(self.client_per("ufficio@x").get("/primanota/giornata/10/2026-05-28/"), "Sede: registra la giustificazione")
        pv.post("/primanota/giornata/10/2026-05-28/", {"azione": "giustifica", "cassa": "1", "controllo": "POS",
                                                       "testo": "POS guasto, chiusura non stampata"})
        f = FileSysSpy.objects.get()
        pos = next(c for c in f.controlli if c["nome"] == "POS")
        self.assertEqual((pos["esito"], pos["giustificazione"].testo), ("giustificato", "POS guasto, chiusura non stampata"))
        self.assertTrue(f.quadrato)
        # La sede la riceve tra le anomalie e la vede nella giornata; il monitor non segna più la cassa.
        self.assertTrue(Nota.objects.filter(tipo="ANOMALIA", testo__contains="POS guasto").exists())
        self.assertContains(self.client_per("ufficio@x").get("/primanota/giornata/10/2026-05-28/"), "Togli giustificazione")
        from primanota.services.monitor import _sysspy_per_giorno
        self.assertEqual(_sysspy_per_giorno(date(2026, 5, 28), date(2026, 5, 28))[(10, "2026-05-28")]["squadrate"], 0)
        # Un controllo senza anomalia non si giustifica; la giustificazione si può togliere.
        pv.post("/primanota/giornata/10/2026-05-28/", {"azione": "giustifica", "cassa": "1", "controllo": "Scontrini", "testo": "x"})
        self.client_per("ufficio@x").post("/primanota/giornata/10/2026-05-28/", {"azione": "togli_giustificazione", "cassa": "1", "controllo": "POS"})
        from primanota.models import GiustificazioneControllo
        self.assertFalse(GiustificazioneControllo.objects.exists())
        self.assertFalse(FileSysSpy.objects.get().quadrato)
        # Un altro negozio non può.
        self.client_per("altro_pv@x").post("/primanota/giornata/10/2026-05-28/", {"azione": "giustifica", "cassa": "1",
                                                                                 "controllo": "POS", "testo": "x"})
        self.assertFalse(GiustificazioneControllo.objects.exists())


def chiusura_fiscale_sysspy(totale, quando, cassa=1):
    """Righe di una chiusura fiscale («quando»: «gg/mm/aaaa hh:mm»)."""
    return "\n".join(["8232                 TO.CAL. SRL", "8232                                         Euro",
                      f"9949 TOTALE GIORNALIERO{totale:>26}", f"9956 CORRISP. NON RISCOSSI{'0,00':>22}",
                      f"9964 NUMERO CASSA{cassa:>33}", f"8232 {quando}", "8232 "]) + "\n"


class TestChiusureFiscaliSpostate(TestCase):
    def test_chiusura_stampata_la_mattina_dopo_e_doppia_chiusura_a_zero(self):
        testo = (sysspy_scontrini("17/10/2026", 1, [(1, "19:00", [("PANE", "5,00")])])
                 # La sera del 17 nessuna chiusura: la cassa la stampa la mattina del 18, prima delle vendite.
                 + chiusura_fiscale_sysspy("5,00", "18/10/2026 08:43")
                 + sysspy_scontrini("18/10/2026", 1, [(2, "10:00", [("LATTE", "3,00")])])
                 + chiusura_fiscale_sysspy("3,00", "18/10/2026 13:20")
                 + chiusura_fiscale_sysspy("0,00", "18/10/2026 13:25"))   # seconda chiusura, a zero
        giornate = {g["data"]: g for g in sysspy.analizza("SysSpy.20261019.1", testo.encode("latin-1"))["giornate"]}
        self.assertEqual(giornate[date(2026, 10, 17)]["valori_fiscali"]["totale_giornaliero"], Decimal("5.00"))
        self.assertEqual(giornate[date(2026, 10, 18)]["valori_fiscali"]["totale_giornaliero"], Decimal("3.00"))
        self.assertEqual((giornate[date(2026, 10, 17)]["totale_scontrini"], giornate[date(2026, 10, 18)]["totale_scontrini"]),
                         (Decimal("5.00"), Decimal("3.00")))


class TestChiusuraPosMancante(TestCase):
    def controllo_pos(self, pagamenti):
        from primanota.services.controlli import controlli
        f = FileSysSpy(negozio_id=10, codice_negozio="5048", data=date(2026, 10, 17), cassa=1, totale_giornaliero=Decimal("18"),
                       totale_scontrini=Decimal("18"), scontrini_trovati=1, pagamenti=pagamenti, totale_pos=None)
        return next(c for c in controlli(f) if c["nome"] == "POS")

    def test_carte_senza_chiusura_pos_sono_un_anomalia(self):
        # Es. POS sostituito dal tecnico senza fare la chiusura: le carte negli scontrini restano senza chiusura.
        c = self.controllo_pos({"Carta Credito": "15.00", "Contanti": "3.00"})
        self.assertEqual((c["esito"], c["titolo"]), ("attenzione", "Chiusura POS mancante (15,00 € di carte)"))
        # Senza carte non c'è niente da chiudere.
        self.assertEqual(self.controllo_pos({"Contanti": "18.00"})["esito"], "info")


class TestMonitorSoloAttivi(Base):
    def test_i_negozi_non_attivi_non_compaiono(self):
        def negozi(url):
            return [r["store_id"] for r in self.client_per("direttore@x").get(url).context["monitor"]["rows"]]
        self.assertEqual(negozi("/primanota/monitor/"), [10, 11])   # nessuna condivisione: tutti
        Condivisione.objects.create(negozio_id=10, codice_negozio="5048", percorso="/x", attiva=True)
        Condivisione.objects.create(negozio_id=11, codice_negozio="5050", percorso="", attiva=False)
        self.assertEqual(negozi("/primanota/monitor/"), [10])
        self.assertEqual(negozi("/primanota/versamenti/monitor/"), [10])
