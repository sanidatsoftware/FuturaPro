"""
Dati locali della Prima Nota.

Le scansioni stanno in Baserow, come quelle di Scansioni PV. Qui stanno invece:
- la condivisione di ogni negozio da cui prelevare i SysSpy;
- l'archivio dei SysSpy (il testo completo è su disco, nel DB solo i dati estratti);
- le note, anomalie e richieste di contatto.

I negozi restano quelli della tabella Baserow Negozi: qui si salva il loro id.
"""

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
    data = models.DateField(null=True, db_index=True)
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

    class Meta:
        ordering = ["-data", "codice_negozio", "cassa"]
        constraints = [
            models.UniqueConstraint(fields=["negozio_id", "percorso_origine"], name="primanota_sysspy_unico"),
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
    def quadrato(self):
        return self.differenza_pos in (None, 0) and self.differenza_scontrini in (None, 0)


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
