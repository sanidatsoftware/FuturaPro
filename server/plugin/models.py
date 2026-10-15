"""I servizi plugin facoltativi: Info Prezzo e Info Ingredienti.

Il SystemAdministrator li abilita per l'azienda (``Abilitazioni``), l'Administrator li attiva
e li configura. I dati stanno in un file SQLite su un PC del negozio (cartella condivisa con
utente e password): il server centrale non li vede. Li legge il servizio code del Totem
Master della sede, che copia il file in locale e risponde alle ricerche dei dispositivi del
negozio; il server prepara solo la configurazione e la query.
"""

from django.db import models

from core.models import ModelloCliente


class TipoPlugin(models.TextChoices):
    PREZZO = "prezzo", "Info Prezzo"
    INGREDIENTI = "ingredienti", "Info Ingredienti"


class ImpostazioniPlugin(ModelloCliente):
    tipo = models.CharField(max_length=12, choices=TipoPlugin.choices)
    attivo = models.BooleanField(default=False)
    # Dove sono i dati nel file: tabella e colonne (vedi «query»), oppure una query scritta a mano.
    mappatura = models.JSONField(default=dict, blank=True)
    query = models.TextField(blank=True)
    # Il popup: caratteri, grandezze, colori, banner «Offerta», lampeggio.
    aspetto = models.JSONField(default=dict, blank=True)
    timeout = models.PositiveSmallIntegerField(default=8)
    # Info Ingredienti: i prefissi dei codici bilancia (es. «20» = Salumeria) e dove sta il PLU.
    prefissi = models.JSONField(default=list, blank=True)
    plu_inizio = models.PositiveSmallIntegerField(default=3)
    plu_lunghezza = models.PositiveSmallIntegerField(default=5)
    mostra_prezzo = models.BooleanField(default=False)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "impostazioni plugin"
        constraints = [models.UniqueConstraint(fields=["cliente", "tipo"], name="plugin_uno_per_tipo")]


class FontePlugin(ModelloCliente):
    """Il file SQLite di un negozio: \\\\indirizzo\\percorso, con l'utente della cartella condivisa."""

    tipo = models.CharField(max_length=12, choices=TipoPlugin.choices)
    sede = models.ForeignKey("clienti.Sede", on_delete=models.CASCADE, related_name="fonti_plugin")
    indirizzo = models.CharField(max_length=100)
    # Cartella condivisa e file, es. «Dati\\Prezzi\\articoli.db» (la prima parte è la condivisione).
    percorso = models.CharField(max_length=300)
    utente = models.CharField(max_length=150, blank=True)
    # Cifrata con una chiave derivata da SECRET_KEY: non si legge dall'API.
    password_cifrata = models.TextField(blank=True)
    # Ogni quanti minuti il totem ricopia il file (solo se è cambiato).
    aggiorna_minuti = models.PositiveSmallIntegerField(default=15)

    class Meta:
        verbose_name_plural = "fonti plugin"
        constraints = [models.UniqueConstraint(fields=["cliente", "tipo", "sede"], name="fonte_plugin_una_per_sede")]
