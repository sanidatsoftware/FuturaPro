from pathlib import Path

from django.db import models, transaction

from core.models import ModelloCliente


def numero_mostrato(totale: int, massimo: int) -> int | None:
    """Il numero sul biglietto e sui display: da 0 a ``massimo`` e poi di nuovo 0.

    ``totale`` conta i biglietti (o le chiamate) della giornata: il primo è lo 0.
    None quando non ce n'è ancora nessuno.
    """
    return (totale - 1) % (massimo + 1) if totale > 0 else None


class SerieAnnunci(ModelloCliente):
    """Gli annunci registrati di un banco, un file audio per numero (es. «SALUMERIA_27.mp3»).

    Una serie può servire più reparti, anche di sedi diverse: la «Salumeria» di ogni negozio.
    """

    nome = models.CharField(max_length=60)
    creata = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "serie di annunci"
        constraints = [models.UniqueConstraint(fields=["cliente", "nome"], name="serie_annunci_nome_unico")]

    def __str__(self):
        return self.nome


def percorso_annuncio(annuncio, nome_originale):
    estensione = Path(nome_originale).suffix.lower() or ".mp3"
    return f"clienti/{annuncio.cliente_id}/annunci/{annuncio.serie_id}/{annuncio.id}{estensione}"


class FileAnnuncio(ModelloCliente):
    serie = models.ForeignKey(SerieAnnunci, on_delete=models.CASCADE, related_name="file")
    # Il numero chiamato; vuoto: il file per i numeri che non ne hanno uno.
    numero = models.PositiveIntegerField(null=True, blank=True)
    file = models.FileField(upload_to=percorso_annuncio, max_length=255)
    nome_originale = models.CharField(max_length=200, blank=True)
    sha256 = models.CharField(max_length=64)
    dimensione = models.PositiveIntegerField(default=0)
    caricato = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["serie", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["serie", "numero"], name="annuncio_numero_unico"),
            models.UniqueConstraint(fields=["serie"], condition=models.Q(numero__isnull=True), name="annuncio_predefinito_unico"),
        ]

    def delete(self, *args, **kwargs):
        file = self.file
        risultato = super().delete(*args, **kwargs)
        if file:
            transaction.on_commit(lambda: file.storage.delete(file.name))
        return risultato


class Reparto(ModelloCliente):
    """Un banco con la sua coda: salumeria, macelleria, gastronomia…

    I contatori sono totali della giornata e non girano mai; il numero da 0 a 99
    si ricava da lì. Così «clienti in coda» è una sottrazione, anche dopo il 99.
    Al primo uso di un nuovo giorno la coda riparte da zero.
    """

    sede = models.ForeignKey("clienti.Sede", on_delete=models.CASCADE, related_name="reparti")
    nome = models.CharField(max_length=60)
    colore = models.CharField(max_length=7, default="#e31b23")
    colore_testo = models.CharField(max_length=7, default="#ffffff")
    ordine = models.PositiveIntegerField(default=0)
    # L'ultimo numero prima di ripartire da 0.
    massimo = models.PositiveIntegerField(default=99)
    attivo = models.BooleanField(default=True)
    azzeramento_automatico = models.BooleanField(default=True)
    # Contatori della giornata.
    giornata = models.DateField(null=True, blank=True)
    chiamati = models.PositiveIntegerField(default=0)
    emessi = models.PositiveIntegerField(default=0)
    # Cambia a ogni chiamata, anche a «ripeti»: i display lampeggiano e annunciano.
    chiamato_il = models.DateTimeField(null=True, blank=True)
    # Alla chiamata i monitor fanno sentire il file del numero, se la serie ce l'ha.
    annunci = models.ForeignKey(SerieAnnunci, on_delete=models.SET_NULL, null=True, blank=True, related_name="reparti")

    class Meta:
        ordering = ["sede", "ordine", "nome"]
        verbose_name_plural = "reparti"
        constraints = [models.UniqueConstraint(fields=["sede", "nome"], name="reparto_nome_unico")]

    def __str__(self):
        return self.nome

    @property
    def numero(self) -> int | None:
        return numero_mostrato(self.chiamati, self.massimo)

    @property
    def ultimo_emesso(self) -> int | None:
        return numero_mostrato(self.emessi, self.massimo)

    @property
    def in_coda(self) -> int:
        return max(0, self.emessi - self.chiamati)

    def stato(self) -> dict:
        return {
            "id": str(self.id),
            "nome": self.nome,
            "colore": self.colore,
            "colore_testo": self.colore_testo,
            "numero": self.numero,
            "in_coda": self.in_coda,
            "ultimo_emesso": self.ultimo_emesso,
            "chiamato_il": self.chiamato_il.isoformat() if self.chiamato_il else None,
        }


class CredenzialePulsante(models.Model):
    """Fuori dalla Row-Level Security come le credenziali dei player: dice di quale cliente è la chiave."""

    impronta_chiave = models.CharField(max_length=64, primary_key=True)
    reparto = models.OneToOneField(Reparto, on_delete=models.CASCADE, related_name="credenziale")
    cliente_id = models.UUIDField()
    creata = models.DateTimeField(auto_now_add=True)


def codice_biglietto() -> str:
    """Il codice del QR sul biglietto: 10 caratteri casuali, senza lettere che si confondono."""
    import secrets

    alfabeto = "23456789abcdefghjkmnpqrstuvwxyz"
    return "".join(secrets.choice(alfabeto) for _ in range(10))


class Biglietto(ModelloCliente):
    """Un biglietto emesso (dal totem o dal server): serve ai tempi d'attesa e alla coda sul
    telefono. ``progressivo`` è il totale dei biglietti della giornata (non gira mai), ``numero``
    quello stampato (da 0 al massimo del reparto)."""

    reparto = models.ForeignKey(Reparto, on_delete=models.CASCADE, related_name="biglietti")
    giornata = models.DateField()
    progressivo = models.PositiveIntegerField()
    numero = models.PositiveIntegerField()
    emesso_il = models.DateTimeField()
    chiamato_il = models.DateTimeField(null=True, blank=True)
    codice = models.CharField(max_length=16, unique=True, default=codice_biglietto)

    class Meta:
        # Niente unicità su giornata e progressivo: dopo un «azzera» i progressivi ripartono.
        ordering = ["reparto", "emesso_il"]
        indexes = [models.Index(fields=["reparto", "giornata"])]


class ChiamataCoda(ModelloCliente):
    """Ogni chiamata del banco (avanti, indietro, ripeti, imposta), con il totale dei chiamati:
    il ritmo del banco anche senza biglietti, e il numero servito per la coda sul telefono."""

    reparto = models.ForeignKey(Reparto, on_delete=models.CASCADE, related_name="chiamate")
    giornata = models.DateField()
    quando = models.DateTimeField()
    operazione = models.CharField(max_length=10)
    progressivo = models.PositiveIntegerField()
    numero = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["reparto", "quando"]
        indexes = [models.Index(fields=["reparto", "giornata"])]


class ImpostazioniTelefono(ModelloCliente):
    """La coda sul telefono (facoltativa): il QR sul biglietto e la pagina che segue la coda."""

    attivo = models.BooleanField(default=False)
    testo = models.CharField(max_length=80, default="Segui la coda dal telefono")
    # A quanti numeri dal proprio il telefono avvisa.
    avviso_a = models.PositiveSmallIntegerField(default=3)

    class Meta:
        verbose_name_plural = "impostazioni coda sul telefono"
        constraints = [models.UniqueConstraint(fields=["cliente"], name="telefono_uno_per_cliente")]
