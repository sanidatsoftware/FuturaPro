"""
Collegamento al database SQL Server della cassa centrale (ONLCassaCentrale su WEBNETSRV),
usato da «Buoni Pasto per Emettitore» e «Consultazione Prima Nota». I dati di accesso li
salvano Direttore o Amministratore nel portale (password cifrata).
"""

from django.conf import settings

NON_CONFIGURATO = ("Collegamento al database della cassa centrale non configurato "
                   "(«Collegamento database», a cura di Direttore o Amministratore).")


def configurazione():
    """
    {"host", "database", "user", "password"}: quella salvata nel portale (Collegamento database),
    altrimenti settings.BUONI_PASTO_DB; None se manca.
    """
    from ..models import CollegamentoBuoniPasto
    from .importazione import decifra

    c = CollegamentoBuoniPasto.objects.first()
    if c and c.host and c.utente:
        return {"host": c.host, "database": c.database or "Scontrini", "user": c.utente,
                "password": decifra(c.password_cifrata)}
    c = getattr(settings, "BUONI_PASTO_DB", None)
    return c if c and c.get("host") else None


def _pymssql():
    try:
        import pymssql
    except ImportError:
        raise RuntimeError("Manca il modulo pymssql: rieseguire l'installazione.")
    return pymssql


def esegui(c, sql, parametri=(), dizionari=False):
    """Esegue la query e restituisce tutte le righe (dict per colonna con dizionari=True); RuntimeError se non riesce."""
    pymssql = _pymssql()
    try:
        with pymssql.connect(server=c["host"], user=c.get("user", ""), password=c.get("password", ""),
                             database=c.get("database") or "Scontrini", login_timeout=15, timeout=300) as cn:
            with cn.cursor(as_dict=dizionari) as cur:
                cur.execute(sql, parametri)
                return cur.fetchall()
    except pymssql.Error as exc:
        raise RuntimeError(f"Database della cassa centrale non raggiungibile o query non riuscita: {exc}")


def prova(c):
    """Prova il collegamento con i dati indicati (SELECT 1)."""
    esegui(c, "SELECT 1")
