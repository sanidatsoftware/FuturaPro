from pathlib import Path

from django.db import models, transaction

from core.models import ModelloCliente

DURATA_IMMAGINE = 10  # secondi, se non indicata


class Tipo(models.TextChoices):
    IMMAGINE = "immagine", "Immagine"
    VIDEO = "video", "Video"
    WEB = "web", "Pagina web"
    # Un flusso in tempo reale (HLS .m3u8 o video via internet): lo scarica ogni player
    # con la sua connessione, il server non lo tocca.
    DIRETTA = "diretta", "Diretta (streaming)"


class Controllo(models.TextChoices):
    """Lo stato di una diretta per il plugin «Filtro contenuti»."""

    ATTESA = "attesa", "In verifica"
    OK = "ok", "Verificata"
    BLOCCATA = "bloccata", "Bloccata dal filtro"
    # Il server non la raggiunge (rete interna, canale spento): non si può controllare, non va in onda.
    NON_VERIFICABILE = "irraggiungibile", "Non verificabile"


class Uso(models.TextChoices):
    LIBRERIA = "libreria", "Libreria delle promozioni"
    # Il logo o il video che uno schermo mostra quando non c'è nulla in onda: caricato
    # a parte, non compare nella libreria e non scade con le promozioni.
    RISERVA = "riserva", "Riserva degli schermi"


def percorso_file(contenuto, nome_originale):
    # Un percorso per cliente, e un nome che non dipende da quello caricato.
    if contenuto.cliente_id is None:
        raise ValueError("Il contenuto non ha ancora un cliente: il file finirebbe fuori dalla sua cartella.")
    return f"clienti/{contenuto.cliente_id}/contenuti/{contenuto.id}{Path(nome_originale).suffix.lower()}"


class Contenuto(ModelloCliente):
    nome = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    file = models.FileField(upload_to=percorso_file, blank=True)
    url = models.URLField(blank=True, help_text="Solo per le pagine web.")
    mime = models.CharField(max_length=100, blank=True)
    dimensione = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    # Vuota: le immagini restano DURATA_IMMAGINE secondi, i video vanno fino alla fine.
    durata = models.PositiveIntegerField(null=True, blank=True)
    caricato_da = models.CharField(max_length=150, blank=True)
    uso = models.CharField(max_length=10, choices=Uso.choices, default=Uso.LIBRERIA)
    # Dirette: il logo del canale (dalla lista M3U) e chi ha confermato che la
    # riproduzione in pubblico è autorizzata (canone, licenze, abbonamenti).
    logo_url = models.URLField(max_length=500, blank=True)
    autorizzata_da = models.CharField(max_length=150, blank=True)
    autorizzata_il = models.DateTimeField(null=True, blank=True)
    # Misure in pixel: le immagini le legge il server, i video le manda il pannello.
    larghezza = models.PositiveIntegerField(null=True, blank=True)
    altezza = models.PositiveIntegerField(null=True, blank=True)
    # Dirette e plugin «Filtro contenuti»: vuoto se la diretta non è da controllare (filtro spento
    # quando è stata aggiunta); altrimenti va in onda solo se l'ultimo controllo è «ok».
    controllo = models.CharField(max_length=16, choices=Controllo.choices, blank=True)
    controllo_il = models.DateTimeField(null=True, blank=True)
    # L'esito dell'ultimo controllo: punteggi, motivo, tentativi falliti di fila.
    controllo_esito = models.JSONField(default=dict, blank=True)
    # Video e plugin «Filtro contenuti»: i tratti con nudo ([da, a] in secondi) che sullo schermo
    # restano coperti dall'immagine di riserva, senza audio.
    coperture = models.JSONField(default=list, blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creato"]
        verbose_name_plural = "contenuti"

    def __str__(self):
        return self.nome

    @property
    def orientamento(self) -> str | None:
        """«verticale» per i totem, «orizzontale» per i monitor; None se le misure mancano."""
        if not self.larghezza or not self.altezza:
            return None
        return "verticale" if self.altezza > self.larghezza else "orizzontale"

    @property
    def percorso_miniatura(self) -> str:
        return f"clienti/{self.cliente_id}/miniature/{self.id}.jpg"

    def delete(self, *args, **kwargs):
        file = self.file
        miniatura = self.percorso_miniatura
        risultato = super().delete(*args, **kwargs)
        if file:
            # Il file sparisce solo se la cancellazione nel database va a buon fine.
            def cancella():
                file.storage.delete(file.name)
                file.storage.delete(miniatura)

            transaction.on_commit(cancella)
        return risultato


class Playlist(ModelloCliente):
    nome = models.CharField(max_length=200)
    descrizione = models.CharField(max_length=500, blank=True)
    creata = models.DateTimeField(auto_now_add=True)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "playlist"

    def __str__(self):
        return self.nome


class ElementoPlaylist(ModelloCliente):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="elementi")
    contenuto = models.ForeignKey(Contenuto, on_delete=models.CASCADE, related_name="+")
    ordine = models.PositiveIntegerField()
    # Vuota: vale la durata del contenuto.
    durata = models.PositiveIntegerField(null=True, blank=True)
    # Le dirette partono senza audio, se non è chiesto qui.
    audio = models.BooleanField(default=False)

    class Meta:
        ordering = ["playlist", "ordine"]


class Orientamento(models.TextChoices):
    ORIZZONTALE = "orizzontale", "Monitor (orizzontale)"
    VERTICALE = "verticale", "Totem (verticale)"


class Campagna(ModelloCliente):
    """Un insieme di promozioni (es. «Autunno 2026» con i volantini di ottobre e novembre).

    Tiene ciò che le promozioni hanno in comune: destinatari, colore, priorità e
    secondi per immagine, e ha una sua validità (es. tutto il 2026) dentro la quale
    stanno le date delle sue promozioni.
    """

    nome = models.CharField(max_length=200)
    data_inizio = models.DateField(null=True, blank=True)
    data_fine = models.DateField(null=True, blank=True)
    codice = models.CharField(max_length=50, blank=True, help_text="Riferimento interno.")
    # Chi paga lo spazio (co-marketing): i rapporti di messa in onda si raggruppano anche così.
    fornitore = models.CharField(max_length=120, blank=True)
    colore = models.CharField(max_length=7, default="#3d6fb6")
    note = models.CharField(max_length=500, blank=True)
    priorita = models.IntegerField(default=0)
    # Secondi per ogni immagine; i video vanno fino alla fine.
    durata = models.PositiveIntegerField(null=True, blank=True)
    insegne = models.ManyToManyField("clienti.Insegna", blank=True, related_name="campagne")
    gruppi = models.ManyToManyField("dispositivi.GruppoMonitor", blank=True, related_name="campagne")
    monitor = models.ManyToManyField("dispositivi.Monitor", blank=True, related_name="campagne")
    creata = models.DateTimeField(auto_now_add=True)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "campagne"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="campagna_nome_unico")]

    def __str__(self):
        return self.nome


class Promozione(ModelloCliente):
    """Una promozione di una campagna (es. «Volantino 6-19 ottobre»): le sue date e le sue immagini.

    Diventa una pubblicazione per orientamento: le immagini verticali vanno ai totem,
    quelle orizzontali ai monitor (``contenuti.campagne``).
    """

    campagna = models.ForeignKey(Campagna, on_delete=models.CASCADE, related_name="promozioni")
    nome = models.CharField(max_length=200)
    data_inizio = models.DateField(null=True, blank=True)
    data_fine = models.DateField(null=True, blank=True)
    ora_inizio = models.TimeField(null=True, blank=True)
    ora_fine = models.TimeField(null=True, blank=True)
    giorni = models.JSONField(default=list, blank=True)
    contenuti = models.ManyToManyField(Contenuto, through="ContenutoPromozione", blank=True, related_name="promozioni")
    creata = models.DateTimeField(auto_now_add=True)
    modificata = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_inizio", "nome"]
        verbose_name_plural = "promozioni"
        constraints = [models.UniqueConstraint(fields=["campagna", "nome"], name="promozione_nome_unico")]

    def __str__(self):
        return self.nome


class ContenutoPromozione(ModelloCliente):
    promozione = models.ForeignKey(Promozione, on_delete=models.CASCADE, related_name="voci")
    contenuto = models.ForeignKey(Contenuto, on_delete=models.CASCADE, related_name="+")
    ordine = models.PositiveIntegerField()
    # Secondi in onda di questa voce (es. 5 minuti di diretta); vuota: quella della campagna.
    durata = models.PositiveIntegerField(null=True, blank=True)
    # Solo per le dirette: con l'audio acceso. Spento, gli altri suoni del monitor restano.
    audio = models.BooleanField(default=False)
    # Solo per le dirette: quando ripeterla. {} = una volta, al suo posto nella sequenza;
    # {"modo": "ogni_slide", "ogni": 10}: dopo ogni 10 voci; {"modo": "ogni_minuti", "ogni": 15}:
    # circa ogni 15 minuti di sequenza; {"modo": "orari", "orari": ["12:00", "18:30"]}: a quelle
    # ore interrompe le slide per la sua durata, poi le slide riprendono (vedi palinsesto).
    ripeti = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["promozione", "ordine"]


class Pubblicazione(ModelloCliente):
    """Una playlist pubblicata su certi monitor, con le sue regole di calendario.

    Le regole vanno tutte al player, che le valuta da solo: così continua a
    seguire il palinsesto anche quando la rete manca. ``contenuti.palinsesto``
    le valuta allo stesso modo per l'anteprima nel pannello.
    """

    nome = models.CharField(max_length=200)
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="pubblicazioni")
    monitor = models.ManyToManyField("dispositivi.Monitor", blank=True, related_name="pubblicazioni")
    gruppi = models.ManyToManyField("dispositivi.GruppoMonitor", blank=True, related_name="pubblicazioni")
    # Tutti i monitor delle sedi di queste insegne.
    insegne = models.ManyToManyField("clienti.Insegna", blank=True, related_name="pubblicazioni")
    # Vuoto: tutti i destinatari; altrimenti solo i monitor di questo orientamento.
    orientamento = models.CharField(max_length=12, choices=Orientamento.choices, blank=True)
    # Le pubblicazioni di una promozione le crea e aggiorna la promozione stessa.
    promozione = models.ForeignKey(Promozione, on_delete=models.CASCADE, null=True, blank=True, related_name="pubblicazioni")
    data_inizio = models.DateField(null=True, blank=True)
    data_fine = models.DateField(null=True, blank=True)
    ora_inizio = models.TimeField(null=True, blank=True)
    ora_fine = models.TimeField(null=True, blank=True)
    # 0 = lunedì … 6 = domenica; vuoto = tutti i giorni.
    giorni = models.JSONField(default=list, blank=True)
    priorita = models.IntegerField(default=0)
    attiva = models.BooleanField(default=True)
    creata = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priorita", "creata"]
        verbose_name_plural = "pubblicazioni"

    def __str__(self):
        return self.nome


class EventoStraordinario(ModelloCliente):
    """Un evento a data e ora fissa (es. la diretta di una partita, lo spot di un'inaugurazione).

    Per tutta la sua durata ha la precedenza su qualunque promozione: il player interrompe la
    playlist, manda l'evento e poi riprende da capo. I numeri delle code restano sullo schermo e
    si sentono con il loro volume; l'evento ha audio e volume suoi.
    """

    nome = models.CharField(max_length=200)
    inizio = models.DateTimeField()
    durata = models.PositiveIntegerField(help_text="Secondi.")
    # Calcolata: inizio + durata. Serve a trovare in fretta gli eventi non ancora finiti.
    fine = models.DateTimeField(editable=False)
    contenuto = models.ForeignKey(Contenuto, on_delete=models.PROTECT, related_name="eventi")
    audio = models.BooleanField(default=True)
    volume = models.PositiveSmallIntegerField(default=80)
    # Tutto lo schermo, sopra ogni zona; altrimenti nella zona slide principale.
    schermo_intero = models.BooleanField(default=False)
    attivo = models.BooleanField(default=True)
    insegne = models.ManyToManyField("clienti.Insegna", blank=True, related_name="eventi")
    gruppi = models.ManyToManyField("dispositivi.GruppoMonitor", blank=True, related_name="eventi")
    monitor = models.ManyToManyField("dispositivi.Monitor", blank=True, related_name="eventi")
    note = models.CharField(max_length=500, blank=True)
    creato_da = models.CharField(max_length=150, blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inizio"]
        verbose_name_plural = "eventi straordinari"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        from datetime import timedelta

        self.fine = self.inizio + timedelta(seconds=self.durata)
        super().save(*args, **kwargs)


class Listino(ModelloCliente):
    """Una tabella di prodotti e prezzi da mostrare sugli schermi con la zona «Listino»
    (es. il banco salumi o la panetteria).

    Le righe si scrivono nel pannello, si importano da un CSV o arrivano da un indirizzo del
    gestionale (``fonte_url``), riletto ogni ``aggiorna_minuti``.
    """

    nome = models.CharField(max_length=200)
    # [{"prodotto", "prezzo" (testo, es. "12.90"), "unita", "nota", "evidenza", "visibile"}]
    righe = models.JSONField(default=list, blank=True)
    fonte_url = models.URLField(max_length=500, blank=True)
    aggiorna_minuti = models.PositiveIntegerField(default=30)
    aggiornato_il = models.DateTimeField(null=True, blank=True)
    errore_fonte = models.CharField(max_length=300, blank=True)
    # Il gestionale può inviare il CSV con «Authorization: Listino <chiave>»: qui l'impronta.
    impronta_chiave = models.CharField(max_length=64, blank=True, db_index=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "listini"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="listino_nome_unico")]

    def __str__(self):
        return self.nome


class MessaInOnda(ModelloCliente):
    """Il registro di messa in onda, riassunto per giorno: quante volte e per quanti secondi un
    contenuto è andato davvero in onda su uno schermo, e per quale promozione.

    Lo scrivono i player (``POST /api/player/passaggi/``), che annotano ogni passaggio e lo
    inviano a pacchetti anche dopo giorni senza rete. I nomi restano anche se promozione o
    contenuto vengono cancellati.
    """

    class Origine(models.TextChoices):
        PROMOZIONE = "promozione", "Promozione"
        EVENTO = "evento", "Evento straordinario"
        RISERVA = "riserva", "Riserva dello schermo"
        PLAYLIST = "playlist", "Playlist fissa"

    chiave = models.CharField(max_length=200, unique=True)
    giorno = models.DateField()
    monitor = models.ForeignKey("dispositivi.Monitor", on_delete=models.CASCADE, related_name="messa_in_onda")
    sede = models.ForeignKey("clienti.Sede", on_delete=models.SET_NULL, null=True, related_name="+")
    origine = models.CharField(max_length=12, choices=Origine.choices)
    contenuto = models.ForeignKey(Contenuto, on_delete=models.SET_NULL, null=True, related_name="+")
    nome_contenuto = models.CharField(max_length=200)
    promozione = models.ForeignKey(Promozione, on_delete=models.SET_NULL, null=True, related_name="+")
    nome_promozione = models.CharField(max_length=200, blank=True)
    campagna = models.ForeignKey(Campagna, on_delete=models.SET_NULL, null=True, related_name="+")
    nome_campagna = models.CharField(max_length=200, blank=True)
    fornitore = models.CharField(max_length=120, blank=True)
    passaggi = models.PositiveIntegerField(default=0)
    secondi = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["giorno"]
        verbose_name_plural = "messa in onda"
        indexes = [models.Index(fields=["giorno"]), models.Index(fields=["campagna", "giorno"])]
