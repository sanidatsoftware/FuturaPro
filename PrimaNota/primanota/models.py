"""
Dati locali della Prima Nota.

Le scansioni stanno in Baserow, come quelle di Scansioni PV. Qui stanno invece:
- la condivisione di ogni negozio da cui prelevare i SysSpy;
- l'archivio dei SysSpy (il testo completo è su disco, nel DB solo i dati estratti);
- le note, anomalie e richieste di contatto.

I negozi restano quelli della tabella Baserow Negozi: qui si salva il loro id.
"""

from decimal import Decimal

from django.db import models


class Condivisione(models.Model):
    negozio_id = models.IntegerField(unique=True, help_text="Id della riga nella tabella Baserow Negozi")
    codice_negozio = models.CharField(max_length=20)
    percorso = models.CharField(max_length=500, help_text=r"\\server\share\cartella oppure /mnt/negozi/5048")
    utente = models.CharField(max_length=200, blank=True)
    password_cifrata = models.TextField(blank=True)
    attiva = models.BooleanField(default=True)
    ultima_importazione = models.DateTimeField(null=True, blank=True)
    ultimo_esito = models.TextField(blank=True)

    class Meta:
        ordering = ["codice_negozio"]

    def __str__(self):
        return f"{self.codice_negozio} {self.percorso}"


class FileSysSpy(models.Model):
    negozio_id = models.IntegerField(db_index=True)
    codice_negozio = models.CharField(max_length=20)
    data = models.DateField(null=True, db_index=True, help_text="Giornata a cui appartiene questa parte del file")
    data_file = models.DateField(null=True, help_text="Data nel nome del file: può essere successiva se la cassa "
                                                      "non ha prodotto il file del giorno")
    cassa = models.IntegerField(null=True)
    nome_file = models.CharField(max_length=100)
    percorso_origine = models.CharField(max_length=700)
    percorso_archivio = models.CharField(max_length=700)
    percorso_testo = models.CharField(max_length=700, help_text="Testo senza le prime 4 colonne, compresso")
    dimensione = models.BigIntegerField()
    modificato_il = models.FloatField(help_text="mtime del file in negozio")
    sha256 = models.CharField(max_length=64)
    importato_il = models.DateTimeField(auto_now=True)
    righe = models.IntegerField(default=0)
    codice_negozio_letto = models.CharField(max_length=20, blank=True)

    chiusura_pos = models.TextField(blank=True)
    chiusura_fiscale = models.TextField(blank=True)
    totale_pos = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    totale_host = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    totale_giornaliero = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    totale_annulli = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    totale_resi = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    corrisp_riscosso = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    corrisp_non_riscosso = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    num_scontrini_fiscali = models.IntegerField(null=True)
    matricola_stampante = models.CharField(max_length=30, blank=True)
    scontrini_trovati = models.IntegerField(default=0)
    totale_scontrini = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    pagamenti = models.JSONField(default=dict, blank=True, help_text="Totale per tipo di pagamento negli scontrini")
    elenco_scontrini = models.JSONField(default=list, blank=True,
                                        help_text="[numero, ora, totale, pagato con POS] per spiegare le differenze")

    class Meta:
        ordering = ["-data", "codice_negozio", "cassa"]
        constraints = [
            # Un file può contenere più giornate: una riga per giornata.
            models.UniqueConstraint(fields=["negozio_id", "percorso_origine", "data"], name="primanota_sysspy_giornata"),
        ]
        indexes = [models.Index(fields=["negozio_id", "data"])]

    @property
    def differenza_pos(self):
        if self.totale_pos is None or self.corrisp_non_riscosso is None:
            return None
        return self.totale_pos - self.corrisp_non_riscosso

    @property
    def differenza_scontrini(self):
        if self.totale_scontrini is None or self.totale_giornaliero is None:
            return None
        return self.totale_scontrini - self.totale_giornaliero

    @property
    def pagato_pos(self):
        """Carta Credito + Bancomat registrati negli scontrini."""
        from .sysspy import PAGAMENTI_POS
        if not self.pagamenti:
            return None
        return sum((Decimal(str(v)) for k, v in self.pagamenti.items() if k in PAGAMENTI_POS), Decimal("0"))

    @property
    def cassa_vuota(self):
        """Cassa non usata: chiusura a zero e nessuno scontrino."""
        return self.scontrini_trovati == 0 and not self.totale_giornaliero

    @property
    def da_altro_file(self):
        return bool(self.data_file and self.data and self.data_file != self.data)

    @property
    def quadrato(self):
        from .services.controlli import quadrato
        return quadrato(self)

    @property
    def controlli(self):
        from .services.controlli import controlli
        return controlli(self)

class DocumentoSysSpy(models.Model):
    """Documenti particolari trovati nel SysSpy, da mostrare accanto alle scansioni."""

    ABORTITO = "ABORTITO"
    RESO = "RESO"
    STORNO = "STORNO"
    ANNULLAMENTO = "ANNULLAMENTO"
    POS_NEGATO = "POS_NEGATO"
    TIPI = [
        (ABORTITO, "Transazione abortita"),
        (RESO, "Reso"),
        (STORNO, "Storno"),
        (ANNULLAMENTO, "Annullamento riga"),
        (POS_NEGATO, "Pagamento POS negato"),
    ]

    file = models.ForeignKey(FileSysSpy, on_delete=models.CASCADE, related_name="documenti")
    tipo = models.CharField(max_length=20, choices=TIPI)
    numero = models.CharField(max_length=30, blank=True)
    ora = models.CharField(max_length=5, blank=True)
    importo = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    testo = models.TextField()

    class Meta:
        ordering = ["file__cassa", "ora"]


class Nota(models.Model):
    NOTA = "NOTA"
    ANOMALIA = "ANOMALIA"
    RICHIESTA_CONTATTO = "RICHIESTA_CONTATTO"
    TIPI = [
        (NOTA, "Nota"),
        (ANOMALIA, "Anomalia"),
        (RICHIESTA_CONTATTO, "Richiesta di contatto"),
    ]

    negozio_id = models.IntegerField(db_index=True)
    data = models.DateField(db_index=True, help_text="Giornata di prima nota")
    tipo = models.CharField(max_length=20, choices=TIPI, default=NOTA)
    testo = models.TextField()
    creata_da = models.CharField(max_length=200)
    creata_il = models.DateTimeField(auto_now_add=True)
    chiusa = models.BooleanField(default=False)
    chiusa_da = models.CharField(max_length=200, blank=True)
    chiusa_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creata_il"]


class Pianificazione(models.Model):
    """
    Orari dell'importazione automatica, decisi nel portale da Amministratore o Direttore.
    Il crontab lancia "importa_sysspy --pianificato" ogni 5 minuti: il comando
    lavora solo quando è passato un orario non ancora eseguito.
    """

    GIORNI = [(0, "Lunedì"), (1, "Martedì"), (2, "Mercoledì"), (3, "Giovedì"), (4, "Venerdì"),
              (5, "Sabato"), (6, "Domenica")]

    attiva = models.BooleanField(default=True)
    orari = models.CharField(max_length=200, default="20:30, 22:00, 06:00",
                             help_text="Orari dell'importazione dei file nuovi, separati da virgola (HH:MM)")
    ricostruzione_attiva = models.BooleanField(default=False)
    ricostruzione_giorno = models.IntegerField(choices=GIORNI, default=6)
    ricostruzione_ora = models.CharField(max_length=5, default="02:00")
    ultima_importazione = models.DateTimeField(null=True, blank=True)
    ultima_ricostruzione = models.DateTimeField(null=True, blank=True)
    ultimo_esito = models.TextField(blank=True)

    @classmethod
    def corrente(cls):
        return cls.objects.first() or cls.objects.create()

    def elenco_orari(self):
        out = []
        for pezzo in self.orari.replace(";", ",").split(","):
            pezzo = pezzo.strip()
            if pezzo:
                ore, minuti = pezzo.split(":")
                out.append((int(ore), int(minuti)))
        return sorted(set(out))


class RegolaDocumento(models.Model):
    """Quando una scansione è obbligatoria nella giornata di prima nota (decide Amministratore o Direttore)."""

    SEMPRE = "SEMPRE"
    SE_SYSSPY = "SE_SYSSPY"
    FACOLTATIVO = "FACOLTATIVO"
    SCELTE = [
        (SEMPRE, "Obbligatoria ogni giorno"),
        (SE_SYSSPY, "Obbligatoria solo se il SysSpy ne contiene"),
        (FACOLTATIVO, "Facoltativa"),
    ]
    PREDEFINITE = {
        "Chiusura fiscale": SEMPRE,
        "Chiusure POS bancari": SEMPRE,
        "Resi": SE_SYSSPY,
        "Transazioni abortite": SE_SYSSPY,
        "Versamenti contante": SEMPRE,
    }

    tipo_documento = models.CharField(max_length=60, unique=True)
    obbligo = models.CharField(max_length=20, choices=SCELTE, default=SEMPRE)

    @classmethod
    def mappa(cls):
        out = dict(cls.PREDEFINITE)
        out.update(dict(cls.objects.values_list("tipo_documento", "obbligo")))
        return out

