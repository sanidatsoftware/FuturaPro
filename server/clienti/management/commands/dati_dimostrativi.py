"""Un cliente dimostrativo pronto da mostrare: layout, slide, notizie, meteo.

    python manage.py dati_dimostrativi --password "…"

Crea il cliente «Demo», l'AdminCliente «demo_admin», la sede «Sede principale»,
il gruppo «Tutti», i layout orizzontale e totem (predefiniti), alcune slide e
la loro pubblicazione sul gruppo. Basta abbinare uno schermo inserendolo nel
gruppo «Tutti» per vederlo funzionare.
"""

import hashlib
import secrets
import struct
import zlib

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIRequestFactory, force_authenticate

from clienti.models import Abilitazioni, Cliente, Sede
from contenuti.api import salva_elementi
from contenuti.models import Contenuto, Playlist, Pubblicazione
from core.contesto import contesto_cliente, contesto_piattaforma
from dispositivi.models import GruppoMonitor
from layout.api import LayoutViewSet
from layout.models import Layout
from utenti.models import Ruolo, Utente

CATANIA = {"localita": "Catania", "latitudine": 37.50, "longitudine": 15.09}
FEED = ["https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml"]
MESSAGGI = ["Benvenuti!", "Orari di apertura: 9:00 – 19:30"]
SLIDE = [
    ("Slide blu", (13, 71, 161), (66, 165, 245)),
    ("Slide verde", (27, 94, 32), (129, 199, 132)),
    ("Slide arancio", (191, 54, 12), (255, 183, 77)),
]


def png_sfumato(larghezza, altezza, alto, basso) -> bytes:
    """Un PNG con una sfumatura verticale, senza librerie grafiche."""
    righe = bytearray()
    for y in range(altezza):
        t = y / (altezza - 1)
        colore = bytes(round(a + (b - a) * t) for a, b in zip(alto, basso))
        righe += b"\x00" + colore * larghezza
    def blocco(tipo, dati):
        return struct.pack(">I", len(dati)) + tipo + dati + struct.pack(">I", zlib.crc32(tipo + dati))

    intestazione = struct.pack(">IIBBBBB", larghezza, altezza, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + blocco(b"IHDR", intestazione) + blocco(b"IDAT", zlib.compress(bytes(righe), 9)) + blocco(b"IEND", b"")


class Command(BaseCommand):
    help = "Crea il cliente dimostrativo «Demo»."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password di demo_admin (se manca se ne genera una).")

    def handle(self, password, **opzioni):
        if Utente.objects.filter(username="demo_admin").exists():
            raise CommandError("I dati dimostrativi esistono già.")
        password = password or secrets.token_urlsafe(12)

        with contesto_piattaforma():
            cliente = Cliente.objects.create(nome="Demo")
            Abilitazioni.objects.create(cliente=cliente)
        admin = Utente(username="demo_admin", ruolo=Ruolo.ADMIN_CLIENTE, cliente=cliente)
        admin.set_password(password)
        admin.save()

        with contesto_cliente(cliente.id):
            Sede.objects.create(nome="Sede principale")
            tutti = GruppoMonitor.objects.create(nome="Tutti")
            for richiesta in (
                {"modello": "orizzontale_informativo", "nome": "Orizzontale informativo"},
                {"modello": "totem_verticale", "nome": "Totem"},
            ):
                self._layout(admin, {**richiesta, **CATANIA, "feed": FEED, "messaggi": MESSAGGI})

            contenuti = []
            for nome, alto, basso in SLIDE:
                dati = png_sfumato(960, 540, alto, basso)
                contenuto = Contenuto(nome=nome, tipo="immagine", mime="image/png", dimensione=len(dati), durata=6,
                                      sha256=hashlib.sha256(dati).hexdigest(), caricato_da="demo")
                contenuto.file.save(f"{nome}.png", ContentFile(dati), save=False)
                contenuto.save()
                contenuti.append(contenuto)
            playlist = Playlist.objects.create(nome="Benvenuto")
            salva_elementi(playlist, [{"contenuto": c} for c in contenuti])
            pubblicazione = Pubblicazione.objects.create(nome="Benvenuto", playlist=playlist)
            pubblicazione.gruppi.add(tutti)

        self.stdout.write(self.style.SUCCESS(f"Cliente «Demo» creato. Accesso: demo_admin / {password}"))

    def _layout(self, admin, richiesta):
        # Si passa dall'API, così i layout dimostrativi seguono le stesse validazioni.
        richiesta_http = APIRequestFactory().post("/api/layout/da-modello/", richiesta, format="json")
        force_authenticate(richiesta_http, user=admin)
        risposta = LayoutViewSet.as_view({"post": "da_modello"})(richiesta_http)
        if risposta.status_code != 201:
            raise CommandError(f"Layout non creato: {risposta.data}")
        layout = Layout.objects.get(id=risposta.data["id"])
        layout.predefinito = True
        layout.save()
        # Le slide dimostrative sono sfumature: riempire la zona rende meglio che lasciare bande nere.
        for zona in layout.zone.filter(tipo="slide"):
            zona.configurazione["adattamento"] = "riempi"
            zona.save()
