from contenuti.models import Listino
from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base
from dispositivi.models import OrarioSchermi


class NuoveSchedeIsolateTest(Base):
    """L'Administrator di un'azienda vede solo la sua, anche nelle schede aggiunte dopo e anche
    se chiede un'altra azienda con X-Cliente; l'elenco delle aziende è del SystemAdministrator."""

    def test_administrator_non_vede_le_altre_aziende(self):
        with contesto_cliente(self.b.id):
            Listino.objects.create(cliente=self.b, nome="Listino di B")
            OrarioSchermi.objects.create(cliente=self.b, nome="Orario di B")
        self.come(self.admin_a, cliente=self.b)
        for url in ("/api/listini/", "/api/orari/", "/api/stato-schermi/", "/api/messa-in-onda/", "/api/email/",
                    "/api/invii-rapporti/", "/api/statistiche-code/", "/api/annunci/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotIn("di B", r.content.decode(), url)
            self.assertNotIn(str(self.mon_b.id), r.content.decode(), url)
        self.assertEqual(self.client.get("/api/piattaforma/clienti/").status_code, 403)
