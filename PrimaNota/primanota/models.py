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
    percorso_sospesi = models.CharField(max_length=500, blank=True,
                                        help_text="Cartella dei file SR degli scontrini sospesi (stesse credenziali)")
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
    versione_analisi = models.IntegerField(default=0, help_text="Versione delle regole con cui è stato letto il file")
    elenco_scontrini = models.JSONField(default=list, blank=True,
                                        help_text="Per scontrino: numero, ora, totale, pagato POS, abortito, cassiere, "
                                                  "reso, correzioni (n e €) - vedi importazione.archivia")
    cassieri = models.JSONField(default=dict, blank=True, help_text="{codice cassiere: nome} letti dal file")

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
    def buoni_e_crediti(self):
        """Buoni pasto + Credito registrati negli scontrini."""
        from .sysspy import PAGAMENTI_NON_RISCOSSI
        if not self.pagamenti:
            return None
        return sum((Decimal(str(v)) for k, v in self.pagamenti.items() if k in PAGAMENTI_NON_RISCOSSI), Decimal("0"))

    @property
    def configurazione_non_riscosso(self):
        """Cosa la cassa mette nel CORRISP. NON RISCOSSI: "carte", "buoni" o "" se non si riconosce."""
        nr = self.corrisp_non_riscosso
        if nr is None or self.cassa_vuota:
            return ""
        if self.pagato_pos is not None and nr == self.pagato_pos:
            return "carte"
        if self.buoni_e_crediti is not None and nr == self.buoni_e_crediti:
            return "buoni"
        return ""

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

    @classmethod
    def da_scansionare(cls):
        """
        I documenti che chiedono una scansione: le «transazioni abortite» stampate per una sospensione
        dello scontrino (SOSPENSIONE SCONTRINO … OPERAZIONE ABORTITA) non sono abortite vere e non contano.
        """
        return cls.objects.exclude(tipo=cls.ABORTITO, testo__contains="SOSPENSIONE SCONTRINO")


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
    chiusa = models.BooleanField(default=False, help_text="Lavorata dalla sede")
    chiusa_da = models.CharField(max_length=200, blank=True)
    chiusa_il = models.DateTimeField(null=True, blank=True)
    # Note sui versamenti contante: le vedono solo Direttori e Amministratori.
    versamento = models.BooleanField(default=False)
    scansione_id = models.IntegerField(null=True, blank=True, help_text="Scansione Baserow a cui si riferisce")
    inviata_a = models.TextField(blank=True, help_text="Indirizzi a cui è stata inviata per email")
    esito_invio = models.TextField(blank=True)
    modificata_il = models.DateTimeField(null=True, blank=True, help_text="Ultima modifica del negozio")

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
        (SE_SYSSPY, "Obbligatoria solo se la giornata ne contiene (SysSpy o prima nota)"),
        (FACOLTATIVO, "Facoltativa"),
    ]
    PREDEFINITE = {
        "Chiusura fiscale": SEMPRE,
        "Chiusure POS bancari": SEMPRE,
        "Resi": SE_SYSSPY,
        "Transazioni abortite": SE_SYSSPY,
        "Versamenti contante": SEMPRE,
        # Con «spese del giorno con fattura» (causale 17) nella prima nota va allegata la fattura.
        "Fatture spese del giorno": SE_SYSSPY,
    }

    tipo_documento = models.CharField(max_length=60, unique=True)
    obbligo = models.CharField(max_length=20, choices=SCELTE, default=SEMPRE)

    @classmethod
    def mappa(cls):
        out = dict(cls.PREDEFINITE)
        out.update(dict(cls.objects.values_list("tipo_documento", "obbligo")))
        return out


class DestinatarioEmail(models.Model):
    """Indirizzi tra cui il negozio sceglie a chi inviare una nota sul versamento."""

    nome = models.CharField(max_length=200)
    email = models.EmailField()
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} <{self.email}>"


class CollegamentoBuoniPasto(models.Model):
    """Database SQL Server della cassa centrale (una sola riga), deciso da Amministratore o Direttore."""

    host = models.CharField(max_length=200, blank=True, default="192.168.1.194")
    database = models.CharField(max_length=200, blank=True, default="Scontrini")
    utente = models.CharField(max_length=200, blank=True)
    password_cifrata = models.TextField(blank=True)
    modificato_da = models.CharField(max_length=200, blank=True)
    modificato_il = models.DateTimeField(null=True, blank=True)

    @classmethod
    def corrente(cls):
        return cls.objects.first() or cls()


class FileSRI(models.Model):
    """File degli scontrini sospesi di una cassa (CPaammgg.SRI.CassaN), letto dalla condivisione del negozio."""

    negozio_id = models.IntegerField(db_index=True)
    codice_negozio = models.CharField(max_length=20)
    percorso_origine = models.CharField(max_length=500)
    nome = models.CharField(max_length=100)
    data = models.DateField(null=True, blank=True)
    cassa = models.IntegerField(null=True, blank=True)
    dimensione = models.BigIntegerField(default=0)
    modificato_il = models.FloatField(default=0)
    testo = models.TextField(blank=True)
    righe_non_lette = models.IntegerField(default=0)
    importato_il = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["negozio_id", "percorso_origine"], name="sri_unico_per_origine")]
        ordering = ["-data", "cassa"]


class ScontrinoSospeso(models.Model):
    """Uno scontrino sospeso e, se avvenuti, il suo richiamo e l'emissione fiscale (FINE RISTAMPA)."""

    SOSPESO, RICHIAMATO, EMESSO = "sospeso", "richiamato", "emesso"
    RIBATTUTO, PROBABILE = "ribattuto", "probabile"

    negozio_id = models.IntegerField(db_index=True)
    codice_negozio = models.CharField(max_length=20)
    identificativo = models.CharField(max_length=40)
    cassa = models.IntegerField(null=True, blank=True)
    data = models.DateField(null=True, blank=True, db_index=True)
    ora = models.TimeField(null=True, blank=True)
    numero = models.IntegerField(null=True, blank=True)
    importo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    richiamato_data = models.DateField(null=True, blank=True)
    richiamato_ora = models.TimeField(null=True, blank=True)
    cassa_richiamo = models.IntegerField(null=True, blank=True)
    emesso_data = models.DateField(null=True, blank=True)
    emesso_ora = models.TimeField(null=True, blank=True)
    cassa_emissione = models.IntegerField(null=True, blank=True)
    numero_emesso = models.IntegerField(null=True, blank=True)
    importo_emesso = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Senza richiamo (es. problemi di rete) la spesa può essere stata ribattuta a mano: lo scontrino
    # fiscale trovato nei SysSpy (stesso negozio, giorno della sospensione o successivo, qualsiasi cassa).
    ribattuto = models.CharField(max_length=10, blank=True, choices=[(RIBATTUTO, "Ribattuto"), (PROBABILE, "Probabilmente ribattuto")])
    rib_data = models.DateField(null=True, blank=True)
    rib_ora = models.CharField(max_length=5, blank=True)
    rib_cassa = models.IntegerField(null=True, blank=True)
    rib_numero = models.IntegerField(null=True, blank=True)
    rib_importo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rib_somiglianza = models.FloatField(null=True, blank=True, help_text="Quota di articoli in comune (0-1)")
    rib_motivo = models.CharField(max_length=200, blank=True)
    rib_altri = models.JSONField(default=list, blank=True, help_text="Altri scontrini candidati")
    # Dalla cartella dei file SR della cassa: «attesa» (file presente), «richiamato» (.RICH), «rimosso»
    # (il file non c'è più), vuoto se la cartella non è configurata o il file non è mai stato visto.
    in_cassa = models.CharField(max_length=12, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["negozio_id", "identificativo"], name="sospeso_unico")]
        ordering = ["-data", "-ora"]

    @property
    def stato(self):
        if self.emesso_data:
            return self.EMESSO
        if self.ribattuto:
            return self.ribattuto
        if self.richiamato_data or self.in_cassa == "richiamato":
            return self.RICHIAMATO
        return self.SOSPESO

    @property
    def differenza(self):
        """Importo emesso meno importo sospeso (articoli aggiunti o tolti dopo il richiamo)."""
        if self.importo is None or self.importo_emesso is None:
            return None
        return self.importo_emesso - self.importo


class FileSR(models.Model):
    """Copia di un file SR della cassa (il carrello di uno scontrino sospeso), conservata anche dopo che la cassa lo cancella."""

    negozio_id = models.IntegerField(db_index=True)
    codice_negozio = models.CharField(max_length=20)
    identificativo = models.CharField(max_length=40)
    nome = models.CharField(max_length=60)
    richiamato = models.BooleanField(default=False)
    presente = models.BooleanField(default=True, help_text="Il file c'era nell'ultima lettura della cartella")
    dimensione = models.BigIntegerField(default=0)
    modificato_il = models.FloatField(default=0)
    percorso_archivio = models.CharField(max_length=700, blank=True)
    articoli = models.JSONField(default=list, blank=True)
    totale_lordo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    visto_il = models.DateTimeField(null=True, blank=True)
    scomparso_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["negozio_id", "identificativo"], name="file_sr_unico")]

    @property
    def stato_in_cassa(self):
        if self.richiamato:
            return "richiamato"
        return "attesa" if self.presente else "rimosso"


class GiornataLavorazione(models.Model):
    """
    Stato della giornata di un negozio deciso dalla sede: vale per tutta la pagina del negozio, non per il
    singolo allegato. Senza riga la giornata è «non lavorata», o «giornata chiusura» se è precedente
    all'inizio della gestione (il pregresso) e il negozio non ha inviato scansioni.
    """

    LAVORATO = "lavorato"
    NON_LAVORATO = "non_lavorato"
    CHIUSURA = "chiusura"
    STATI = [(LAVORATO, "Lavorato"), (NON_LAVORATO, "Non lavorato"), (CHIUSURA, "Giornata chiusura")]
    # Chiusure Fiscali e Gestione Versamenti si lavorano separatamente, ognuna con il suo stato.
    CHIUSURE = "chiusure"
    VERSAMENTI = "versamenti"
    SEZIONI = [(CHIUSURE, "Chiusure Fiscali"), (VERSAMENTI, "Versamenti")]

    negozio_id = models.IntegerField(db_index=True)
    data = models.DateField(db_index=True)
    sezione = models.CharField(max_length=20, choices=SEZIONI, default=CHIUSURE)
    stato = models.CharField(max_length=20, choices=STATI)
    modificato_da = models.CharField(max_length=200, blank=True)
    modificato_il = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["negozio_id", "data", "sezione"], name="giornata_sezione_unica")]

    @staticmethod
    def inizio_gestione():
        """Primo giorno gestito con il monitor: i giorni prima, senza uno stato scelto, sono «giornata chiusura»."""
        from datetime import date
        from django.conf import settings
        valore = getattr(settings, "PRIMANOTA_INIZIO_GESTIONE", "2026-10-20")   # pregresso fino al 19/10/2026
        return valore if isinstance(valore, date) else date.fromisoformat(str(valore))

    @classmethod
    def stato_predefinito(cls, giorno, con_scansioni=False):
        """Il pregresso è «giornata chiusura» solo se il negozio non ha inviato niente: ciò che è arrivato va lavorato."""
        return cls.CHIUSURA if giorno < cls.inizio_gestione() and not con_scansioni else cls.NON_LAVORATO

    @classmethod
    def mappa(cls, dal, al, negozio_id=None, sezione=CHIUSURE):
        """{(negozio_id, data): riga} delle giornate con uno stato scelto nel periodo, per la sezione."""
        righe = cls.objects.filter(data__range=(dal, al), sezione=sezione)
        if negozio_id is not None:
            righe = righe.filter(negozio_id=negozio_id)
        return {(g.negozio_id, g.data): g for g in righe}


class Emergenza(models.Model):
    """
    Modalità Emergenza dichiarata dal negozio per una giornata: la prima nota non si può compilare o certificare
    per problemi tecnici, quindi le scansioni si inviano lo stesso e le voci «obbligatoria solo se la giornata
    ne contiene» restano caricabili. Nel monitor la giornata lampeggia in giallo finché la prima nota non c'è.
    """

    negozio_id = models.IntegerField(db_index=True)
    data = models.DateField(db_index=True)
    motivo = models.TextField()
    attivata_da = models.CharField(max_length=200)
    attivata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["negozio_id", "data"], name="emergenza_unica")]

    @classmethod
    def giorni(cls, dal, al, negozio_id=None):
        """{(negozio_id, data): emergenza} nel periodo."""
        righe = cls.objects.filter(data__range=(dal, al))
        if negozio_id is not None:
            righe = righe.filter(negozio_id=negozio_id)
        return {(e.negozio_id, e.data): e for e in righe}
