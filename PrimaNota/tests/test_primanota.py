import json
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from incarichi.services import baserow_client, baserow_layer
from primanota import sysspy
from primanota.models import Condivisione, DocumentoSysSpy, FileSysSpy, Nota
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
        return c

    def carica(self, client, tipo, giorno="2026-05-28", cassa=""):
        return client.post("/primanota/upload/", {
            "data_documento": giorno, "tipo_documento": tipo, "cassa": cassa, "note": "",
            "documento": SimpleUploadedFile("scan.pdf", b"%PDF-1.4", content_type="application/pdf")})

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

    def test_il_negozio_carica_per_genere(self):
        pv = self.client_per("pv@x")
        r = self.carica(pv, "Chiusura fiscale", cassa="1")
        self.assertRedirects(r, "/primanota/upload/?uploaded=1", fetch_redirect_response=False)
        riga = self.baserow.righe[1]
        self.assertEqual((riga["Negozio"][0]["id"], riga["Tipo Documento"], riga["Cassa"]), (10, "Chiusura fiscale", 1))
        self.assertFalse(riga["Lavorato"])
        self.assertContains(self.carica(pv, "Tipo inventato"), "Compila Data")
        self.assertContains(pv.get("/primanota/upload/"), "Chiusura fiscale")

    def test_giornata_affianca_scansioni_e_sysspy(self):
        self.importa_fixture()
        self.carica(self.client_per("pv@x"), "Chiusure POS bancari")
        r = self.client_per("ufficio@x").get("/primanota/giornata/10/2026-05-28/")
        self.assertContains(r, "TOTALE HOST EUR")             # chiusura POS dal SysSpy
        self.assertContains(r, "TOTALE GIORNALIERO")          # chiusura fiscale dal SysSpy
        self.assertContains(r, "SCONTRINO ANNULLATO")         # transazione abortita
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
        pv.post("/primanota/upload/", {"azione": "nota", "data": "2026-05-28", "tipo": "RICHIESTA_CONTATTO", "testo": "Chiamatemi"})
        nota = Nota.objects.get()
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
        self.carica(pv, "Chiusura fiscale", giorno=ieri)
        self.carica(pv, "Versamenti contante", giorno=ieri)
        Nota.objects.create(negozio_id=10, data=ieri, tipo=Nota.ANOMALIA, testo="x", creata_da="x")
        r = self.client_per("ufficio@x").get("/primanota/monitor/")
        self.assertEqual(r.status_code, 200)
        riga = next(x for x in r.context["monitor"]["rows"] if x["store_id"] == 10)
        cella = next(c for c in riga["cells"] if c["date"] == ieri)
        self.assertEqual((cella["state"], cella["total"], cella["versamenti_aperti"], cella["note_aperte"]),
                         ("incomplete", 2, 1, 1))
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
        FileSysSpy.objects.filter(pk=f.pk).update(pagamenti={}, data_file=None)
        self.assertEqual(importazione.rielabora_archivio(), {"file": 1, "errori": 0})
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
        self.assertEqual(sezioni, {"Chiusura fiscale": True, "Chiusure POS bancari": True, "Resi": False,
                                   "Transazioni abortite": True, "Versamenti contante": True})
        self.client_per("admin@x").post("/primanota/condivisioni/", {"azione": "regole", "regola_versamenti": "FACOLTATIVO"})
        self.assertEqual(RegolaDocumento.mappa()["Versamenti contante"], "FACOLTATIVO")

    def test_stampa_pdf(self):
        import pymupdf
        self.importa_fixture()
        self.carica(self.client_per("pv@x"), "Chiusura fiscale", cassa="1")
        pdf_scansione = pymupdf.open()
        pdf_scansione.new_page().insert_text((50, 50), "SCANSIONE")
        with mock.patch("primanota.services.stampa._scarica", return_value=(pdf_scansione.tobytes(), "application/pdf")):
            r = self.client_per("ufficio@x").get("/primanota/stampa/", {"sezione": "fiscale", "data_da": "2026-05-28",
                                                                         "per_pagina": 4})
        self.assertEqual(r["Content-Type"], "application/pdf")
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        testo = doc[0].get_text()
        self.assertEqual(doc.page_count, 1)
        self.assertIn("TOTALE GIORNALIERO", testo)
        self.assertIn("SCANSIONE", testo)
        self.assertEqual(self.client_per("pv@x").get("/primanota/stampa/").status_code, 302)


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

