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
