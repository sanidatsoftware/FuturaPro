from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database)
def ruolo_database_soggetto_a_rls(app_configs, databases=None, **kwargs):
    """Un superuser o un ruolo con BYPASSRLS salterebbe in silenzio l'isolamento tra clienti."""
    errori = []
    for alias in databases or []:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            (aggira,) = cursor.fetchone()
        if aggira:
            errori.append(
                Error(
                    f"L'utente del database '{alias}' è superuser o ha BYPASSRLS: "
                    "la Row-Level Security non lo vincola.",
                    hint="Collegare l'applicazione con un ruolo dedicato, senza SUPERUSER né BYPASSRLS.",
                    id="futurapro.E001",
                )
            )
    return errori
