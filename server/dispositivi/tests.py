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
