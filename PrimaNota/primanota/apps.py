import django
from django.apps import AppConfig


class PrimanotaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "primanota"
    verbose_name = "Prima Nota"

    def ready(self):
        # Il portale usa SQLite e la Prima Nota vi scrive anche in background (importazioni, rielaborazioni):
        # una scrittura che trova il database occupato aspetta il suo turno (fino a 30 s) invece di dare
        # «database is locked», e le transazioni prendono subito il blocco in scrittura (IMMEDIATE), così due
        # scritture contemporanee non si bloccano a vicenda. Non cambia niente se il portale ha già scelto.
        from django.conf import settings
        db = settings.DATABASES.get("default", {})
        if "sqlite3" in db.get("ENGINE", ""):
            opzioni = db.setdefault("OPTIONS", {})
            opzioni.setdefault("timeout", 30)
            if django.VERSION >= (5, 1):
                opzioni.setdefault("transaction_mode", "IMMEDIATE")
