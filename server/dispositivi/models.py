import hashlib
import secrets
import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.models import ModelloCliente

ONLINE_ENTRO = timedelta(minutes=2)
DURATA_CODICE = timedelta(minutes=15)


def impronta(token: str) -> str:
    # I token sono 32 byte casuali: basta SHA-256, non serve un hash lento.
    return hashlib.sha256(token.encode()).hexdigest()


class Piattaforma(models.TextChoices):
    WINDOWS = "windows", "Windows"
    ANDROID = "android", "Android"


class GruppoMonitor(ModelloCliente):
    nome = models.CharField(max_length=200)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "gruppi di monitor"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="gruppo_nome_unico")]

    def __str__(self):
        return self.nome


class LayoutTicket(ModelloCliente):
    """Com'è fatto il biglietto stampato: gli elementi in colonna (logo, intestazione, reparto,
    numero, testo di fine biglietto…), ognuno con carattere, grandezza e allineamento. Si sceglie
    per ogni stampante (vedi «ticket»). Il totem lo disegna come immagine: esce identico
    sulla Epson di rete e sulla stampante di sistema."""

    nome = models.CharField(max_length=100)
    # Larghezza della carta: 80 mm (576 punti a 203 dpi) o 58 mm (384 punti).
    carta = models.PositiveSmallIntegerField(choices=[(80, "80 mm"), (58, "58 mm")], default=80)
    elementi = models.JSONField(default=list, blank=True)
    # Il logo in PNG (base64), già in scala di grigi e alla larghezza della carta.
    logo = models.TextField(blank=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "layout ticket"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="layout_ticket_nome_unico")]

    def __str__(self):
        return self.nome


class StampanteTicket(ModelloCliente):
    """Una stampante dei biglietti di un negozio. Si abbina ai totem dall'anagrafica degli schermi."""

    class Tipo(models.TextChoices):
        SISTEMA = "browser", "Stampante di sistema del PC del totem"
        EPSON = "epson", "Stampante di rete Epson TM (ePOS-Print)"

    nome = models.CharField(max_length=100)
    sede = models.ForeignKey("clienti.Sede", on_delete=models.PROTECT, related_name="stampanti")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.EPSON)
    # Epson: indirizzo IP o nome in rete, eventualmente con la porta.
    indirizzo = models.CharField(max_length=100, blank=True)
    modello = models.CharField(max_length=60, blank=True)
    # Com'è fatto il biglietto; vuoto: quello semplice, con i testi della zona «prendi il numero».
    layout = models.ForeignKey(LayoutTicket, on_delete=models.SET_NULL, null=True, blank=True, related_name="stampanti")
    # Vuoti: valgono quelli del layout ticket, o della zona «prendi il numero» del layout.
    intestazione = models.CharField(max_length=60, blank=True)
    messaggio = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=200, blank=True)
    # La stampa di prova: la chiede il pannello, la esegue un totem abbinato (vedi «stampanti»).
    prova_richiesta = models.DateTimeField(null=True, blank=True)
    prova_monitor = models.ForeignKey("dispositivi.Monitor", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    prova_esito = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "stampante ticket"
        verbose_name_plural = "stampanti ticket"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="stampante_nome_unico")]

    def __str__(self):
        return self.nome


class Monitor(ModelloCliente):
    nome = models.CharField(max_length=200)
    sede = models.ForeignKey("clienti.Sede", on_delete=models.PROTECT, related_name="monitor")
    gruppi = models.ManyToManyField(GruppoMonitor, blank=True, related_name="monitor")
    piattaforma = models.CharField(max_length=10, choices=Piattaforma.choices)
    versione_player = models.CharField(max_length=40, blank=True)
    # La versione del manifest che il player dice di avere: se è diversa da quella
    # attuale, il monitor non ha ancora ricevuto (o scaricato) le ultime modifiche.
    manifest_ricevuto = models.CharField(max_length=64, blank=True)
    info_dispositivo = models.JSONField(default=dict, blank=True)
    ultimo_contatto = models.DateTimeField(null=True, blank=True)
    abbinato_il = models.DateTimeField(auto_now_add=True)
    orientamento = models.CharField(
        max_length=12, choices=[("orizzontale", "Orizzontale"), ("verticale", "Verticale (totem)")], default="orizzontale"
    )
    # Quanto il player deve ruotare l'immagine: serve quando un televisore orizzontale
    # è montato in verticale; un totem nativo verticale resta a 0.
    rotazione = models.PositiveSmallIntegerField(choices=[(0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")], default=0)
    # Vuoto: il layout predefinito del cliente per il suo orientamento.
    layout = models.ForeignKey("layout.Layout", on_delete=models.SET_NULL, null=True, blank=True, related_name="monitor")
    # Quando il monitor ha mandato l'ultima fotografia dello schermo (vedi «schermate»).
    schermata_il = models.DateTimeField(null=True, blank=True)
    schermata_richiesta = models.DateTimeField(null=True, blank=True)
    # Quando è partito l'allarme «schermo scollegato» (si azzera quando torna in linea).
    allarme_dal = models.DateTimeField(null=True, blank=True)
    # Cosa mostrano le slide quando non c'è nulla in onda (es. il logo del negozio): mai uno schermo vuoto.
    immagine_riserva = models.ForeignKey(
        "contenuti.Contenuto", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Il totem che detiene i turni delle code della sede (il suo servizio code): uno per sede.
    # Gli altri totem chiedono a lui i numeri dei biglietti.
    totem_master = models.BooleanField(default=False)
    # La stampante dei biglietti del totem (Anagrafica Stampanti Ticket); vuoto = come nel layout.
    stampante = models.ForeignKey(
        "dispositivi.StampanteTicket", on_delete=models.SET_NULL, null=True, blank=True, related_name="monitor"
    )

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "monitor"
        constraints = [
            models.UniqueConstraint(fields=["sede"], condition=models.Q(totem_master=True), name="un_totem_master_per_sede"),
        ]

    def __str__(self):
        return self.nome

    @property
    def online(self) -> bool:
        return self.ultimo_contatto is not None and timezone.now() - self.ultimo_contatto < ONLINE_ENTRO


class RichiestaAbbinamento(models.Model):
    """Un player appena installato che mostra il suo codice e aspetta di essere abbinato.

    Non appartiene ancora a nessun cliente, quindi non è sotto Row-Level
    Security. Il player genera da sé il proprio token e ne manda una copia una
    volta sola: qui resta soltanto l'impronta.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codice = models.CharField(max_length=6, unique=True)
    impronta_token = models.CharField(max_length=64, unique=True)
    piattaforma = models.CharField(max_length=10, choices=Piattaforma.choices)
    info_dispositivo = models.JSONField(default=dict, blank=True)
    creata = models.DateTimeField(auto_now_add=True)
    scade = models.DateTimeField()

    @classmethod
    def nuova(cls, token: str, piattaforma: str, info: dict) -> "RichiestaAbbinamento":
        cls.objects.filter(scade__lt=timezone.now()).delete()
        while True:
            codice = f"{secrets.randbelow(1_000_000):06d}"
            if not cls.objects.filter(codice=codice).exists():
                break
        return cls.objects.create(
            codice=codice,
            impronta_token=impronta(token),
            piattaforma=piattaforma,
            info_dispositivo=info,
            scade=timezone.now() + DURATA_CODICE,
        )

    @property
    def scaduta(self) -> bool:
        return timezone.now() >= self.scade


class CredenzialeDispositivo(models.Model):
    """Chi è il player che si presenta con un certo token, e di quale cliente è.

    Sta fuori dalla Row-Level Security perché va letta prima di conoscere il
    cliente: è proprio lei a dirlo. Contiene solo impronte, mai i token.
    """

    impronta_token = models.CharField(max_length=64, primary_key=True)
    monitor = models.OneToOneField(Monitor, on_delete=models.CASCADE, related_name="credenziale")
    cliente_id = models.UUIDField()
    revocata = models.BooleanField(default=False)
    creata = models.DateTimeField(auto_now_add=True)


class OrarioSchermi(ModelloCliente):
    """Quando gli schermi sono accesi: fasce per giorno della settimana e giorni di chiusura.

    Fuori orario il player va in riposo (schermo nero, niente audio né dirette). Uno schermo
    senza orario resta sempre acceso. Se più orari valgono per uno schermo, vince il più
    specifico: quello scelto per lo schermo, poi per un suo gruppo, poi per la sua insegna.
    """

    nome = models.CharField(max_length=200)
    # [{"giorni": [0..6], "dalle": "07:30", "alle": "21:00"}, …]; 0 = lunedì. «alle» prima di
    # «dalle» vuol dire che la fascia passa la mezzanotte.
    fasce = models.JSONField(default=list, blank=True)
    # ["2026-12-25", …]: tutto il giorno spento.
    chiusure = models.JSONField(default=list, blank=True)
    attivo = models.BooleanField(default=True)
    insegne = models.ManyToManyField("clienti.Insegna", blank=True, related_name="orari_schermi")
    gruppi = models.ManyToManyField(GruppoMonitor, blank=True, related_name="orari_schermi")
    monitor = models.ManyToManyField(Monitor, blank=True, related_name="orari_schermi")
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "orari degli schermi"

    def __str__(self):
        return self.nome


def orario_del_monitor(monitor):
    """L'orario che vale per lo schermo (il più specifico), o None: sempre acceso."""
    orari = OrarioSchermi.objects.filter(attivo=True)
    for filtro in (
        {"monitor": monitor},
        {"gruppi__monitor": monitor},
        {"insegne": monitor.sede.insegna_id} if monitor.sede.insegna_id else None,
    ):
        if filtro is None:
            continue
        trovato = orari.filter(**filtro).order_by("-modificato").first()
        if trovato is not None:
            return trovato
    return None


def acceso_secondo_orario(orario, quando) -> bool:
    """Come regole.js/acceso nel player: lo schermo dovrebbe essere acceso in quell'istante
    locale? Senza orario, sempre."""
    if orario is None:
        return True
    if quando.date().isoformat() in (orario.chiusure or []):
        return False
    ora = quando.strftime("%H:%M")
    oggi = quando.weekday()
    ieri = (oggi + 6) % 7
    for f in orario.fasce or []:
        if f["dalle"] < f["alle"]:
            if oggi in f["giorni"] and f["dalle"] <= ora < f["alle"]:
                return True
        elif (oggi in f["giorni"] and ora >= f["dalle"]) or (ieri in f["giorni"] and ora < f["alle"]):
            return True
    return False


class PresenzaSchermo(ModelloCliente):
    """Minuti di collegamento di uno schermo in un giorno (dal segnale periodico, uno al minuto)."""

    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE, related_name="presenze")
    giorno = models.DateField()
    minuti = models.PositiveIntegerField(default=0)
    # Di cui a riposo, fuori dall'orario di accensione.
    minuti_riposo = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["monitor", "giorno"]
        constraints = [models.UniqueConstraint(fields=["monitor", "giorno"], name="presenza_unica_al_giorno")]


class EventoSchermo(ModelloCliente):
    """Lo storico degli allarmi: quando uno schermo si è scollegato e quando è tornato."""

    class Tipo(models.TextChoices):
        SCOLLEGATO = "scollegato", "Scollegato"
        RICOLLEGATO = "ricollegato", "Tornato in linea"

    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE, related_name="eventi_stato")
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    quando = models.DateTimeField(auto_now_add=True)
    # Da quando non rispondeva (per lo scollegamento) o per quanto è rimasto fuori (minuti).
    dettaglio = models.CharField(max_length=200, blank=True)
    email_inviata = models.BooleanField(default=False)

    class Meta:
        ordering = ["-quando"]


class ImpostazioniAllarmi(ModelloCliente):
    """Chi avvisare, via email, quando uno schermo resta scollegato."""

    attivo = models.BooleanField(default=False)
    email = models.JSONField(default=list, blank=True)
    minuti = models.PositiveIntegerField(default=15)
    # Fuori dall'orario di accensione uno schermo spento non è un guasto.
    solo_in_orario = models.BooleanField(default=True)
    avvisa_ritorno = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "impostazioni allarmi"
        constraints = [models.UniqueConstraint(fields=["cliente"], name="allarmi_uno_per_cliente")]


class ImpostazioniDownload(ModelloCliente):
    """Quando e quanto in fretta gli schermi scaricano i file nuovi (facoltativo).

    Fuori fascia restano in onda le promozioni già scaricate; quelle nuove partono quando i loro
    file sono arrivati. Uno schermo nuovo, i file degli eventi straordinari vicini e il pulsante
    «Scarica adesso» saltano la fascia.
    """

    attivo = models.BooleanField(default=False)
    dalle = models.TimeField(default="22:00")
    alle = models.TimeField(default="06:00")
    # Kilobyte al secondo per schermo; 0 = senza limite.
    kbps = models.PositiveIntegerField(default=0)
    # «Scarica adesso»: fino a quest'ora la fascia non vale.
    subito_fino = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "impostazioni download"
        constraints = [models.UniqueConstraint(fields=["cliente"], name="download_uno_per_cliente")]
