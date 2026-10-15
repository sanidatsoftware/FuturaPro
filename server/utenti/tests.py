from core.contesto import contesto_cliente
from core.tests.test_isolamento import Base
from utenti.models import Utente


class ProfiloTest(Base):
    """Ognuno, anche il SystemAdministrator, cambia da sé nome utente e password."""

    def test_nome_utente_e_password(self):
        self.come(self.assoluto)
        # Senza la password attuale non si cambia nulla.
        r = self.client.patch("/api/io/", {"username": "capo", "password_attuale": "sbagliata"}, format="json")
        self.assertEqual(r.status_code, 400)
        utente = Utente.objects.get(pk=self.assoluto.pk)
        utente.set_password("Vecchia12345!")
        utente.save()
        self.client.force_login(utente)
        self.assertEqual(self.client.patch("/api/io/", {"username": "admin_a", "password_attuale": "Vecchia12345!"}, format="json").status_code, 400)  # già usato
        self.assertEqual(self.client.patch("/api/io/", {"password": "corta", "password_attuale": "Vecchia12345!"}, format="json").status_code, 400)
        r = self.client.patch("/api/io/", {"username": "capo", "password": "Nuova-Password-2026", "password_attuale": "Vecchia12345!",
                                           "first_name": "Mario", "email": "capo@esempio.it"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["username"], r.json()["first_name"]), ("capo", "Mario"))
        # Resta collegato, e la password nuova vale.
        self.assertEqual(self.client.get("/api/io/").status_code, 200)
        self.assertTrue(Utente.objects.get(pk=utente.pk).check_password("Nuova-Password-2026"))
        # Il tema non chiede la password.
        self.assertEqual(self.client.patch("/api/io/", {"tema": "scuro"}, format="json").json()["tema"], "scuro")


class RuoliTest(Base):
    """Solo il SystemAdministrator crea SystemAdministrator, tecnici e Administrator;
    l'Administrator crea gli User della sua azienda."""

    def test_chi_crea_chi(self):
        from clienti.models import Abilitazioni

        with contesto_cliente(self.a.id):
            Abilitazioni.objects.update(admin_gestisce_utenti=True, max_utenti=20)
        nuovo = lambda ruolo, nome: {"username": nome, "password": "Password-Lunga-1", "ruolo": ruolo}
        self.come(self.admin_a)
        self.assertEqual(self.client.post("/api/utenti/", nuovo("user_cliente", "cassiera"), format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/utenti/", nuovo("admin_cliente", "vice"), format="json").status_code, 403)
        # Non promuove un User né tocca un altro Administrator.
        cassiera = Utente.objects.get(username="cassiera")
        self.assertEqual(self.client.patch(f"/api/utenti/{cassiera.id}/", {"ruolo": "admin_cliente"}, format="json").status_code, 403)
        altro = Utente.objects.create_user("admin_a2", password="Password-Lunga-1", ruolo="admin_cliente", cliente=self.a)
        self.assertEqual(self.client.patch(f"/api/utenti/{altro.id}/", {"password": "Altra-Password-9"}, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/piattaforma/utenti/", nuovo("admin_assoluto", "x"), format="json").status_code, 403)
        # Il SystemAdministrator sì: Administrator per l'azienda e altri SystemAdministrator.
        self.come(self.assoluto, self.a)
        self.assertEqual(self.client.post("/api/utenti/", nuovo("admin_cliente", "vice"), format="json").status_code, 201)
        r = self.client.post("/api/piattaforma/utenti/", nuovo("admin_assoluto", "secondo_capo"), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(Utente.objects.get(username="secondo_capo").cliente_id)
        # Non si disattiva da solo.
        self.assertEqual(self.client.patch(f"/api/piattaforma/utenti/{self.assoluto.id}/", {"is_active": False}, format="json").status_code, 400)
        self.come(self.tecnico)
        self.assertEqual(self.client.post("/api/piattaforma/utenti/", nuovo("admin_assoluto", "y"), format="json").status_code, 403)


class PaginaInizialeTest(Base):
    """Dopo l'accesso si apre la pagina scelta nel Profilo, o quella consigliata per il ruolo."""

    def test_apertura(self):
        from utenti.models import Utente

        for utente, attesa in ((self.assoluto, "/pannello/#panoramica"), (self.admin_a, "/pannello/#panoramica"),
                               (self.tecnico, "/pannello/#stato"), (self.user_a, "/palinsesto/")):
            u = Utente.objects.get(pk=utente.pk)
            u.set_password("Password-Lunga-1")
            u.save()
            self.client.logout()
            r = self.client.post("/accesso/", {"username": u.username, "password": "Password-Lunga-1"})
            self.assertRedirects(r, attesa, fetch_redirect_response=False)
        # Scelta nel Profilo (l'utente con la password nuova appena impostata).
        self.client.force_login(Utente.objects.get(pk=self.admin_a.pk))
        r = self.client.patch("/api/io/", {"pagina_iniziale": "messa_in_onda"}, format="json")
        self.assertEqual(r.json().get("apertura"), "messa_in_onda", r.content)
        self.assertEqual(self.client.patch("/api/io/", {"pagina_iniziale": "../x"}, format="json").status_code, 400)
        self.client.logout()
        r = self.client.post("/accesso/", {"username": "admin_a", "password": "Password-Lunga-1"})
        self.assertRedirects(r, "/pannello/#messa_in_onda", fetch_redirect_response=False)
        # Con «next» vale quello.
        self.client.logout()
        r = self.client.post("/accesso/?next=/editor/", {"username": "admin_a", "password": "Password-Lunga-1", "next": "/editor/"})
        self.assertRedirects(r, "/editor/", fetch_redirect_response=False)
