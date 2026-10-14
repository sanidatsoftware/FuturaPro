"""Contesto di esecuzione: per quale cliente sta lavorando il codice in questo momento.

È l'unico punto da cui passa l'isolamento tra clienti, e lo fa a due livelli:

1. nell'applicazione, dove ``GestoreCliente`` filtra ogni query sul cliente
   del contesto, e senza contesto rifiuta di eseguirla;
2. nel database, dove le stesse informazioni finiscono in due variabili di
   sessione PostgreSQL (``app.cliente_id`` e ``app.piattaforma``) lette dalle
   policy di Row-Level Security.

Un errore in un punto solo non basta quindi a mostrare i dati di un altro
cliente. Le variabili sono impostate con ``is_local = true``: valgono fino
alla fine della transazione e poi spariscono da sole, così una connessione
riusata non si porta dietro il cliente della richiesta precedente.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from django.db import connection, transaction


@dataclass(frozen=True)
class Contesto:
    # Il cliente su cui si opera; None solo nel contesto di piattaforma.
    cliente_id: UUID | None
    # True solo per le operazioni del SystemAdministrator che riguardano
    # tutta la piattaforma (anagrafica clienti, utenti di piattaforma).
    piattaforma: bool = False


class ContestoMancante(RuntimeError):
    """Una query sui dati di un cliente è partita senza sapere per quale cliente."""


_contesto: ContextVar[Contesto | None] = ContextVar("futurapro_contesto", default=None)


def contesto_corrente() -> Contesto:
    contesto = _contesto.get()
    if contesto is None:
        raise ContestoMancante(
            "Nessun cliente nel contesto: usare contesto_cliente() o contesto_piattaforma()."
        )
    return contesto


def contesto_attivo() -> Contesto | None:
    return _contesto.get()


def _scrivi_sul_database(contesto: Contesto | None) -> None:
    cliente = str(contesto.cliente_id) if contesto and contesto.cliente_id else ""
    piattaforma = "on" if contesto and contesto.piattaforma else "off"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.cliente_id', %s, true), set_config('app.piattaforma', %s, true)",
            [cliente, piattaforma],
        )


def imposta(contesto: Contesto | None) -> None:
    """Imposta il contesto per il resto della transazione corrente.

    Serve alle viste, che girano già dentro la transazione della richiesta
    (ATOMIC_REQUESTS). Altrove si usano i context manager qui sotto.
    """
    _contesto.set(contesto)
    if contesto is not None and connection.in_atomic_block:
        _scrivi_sul_database(contesto)


def azzera() -> None:
    _contesto.set(None)


@contextmanager
def _entra(contesto: Contesto):
    precedente = _contesto.get()
    token = _contesto.set(contesto)
    try:
        with transaction.atomic():
            _scrivi_sul_database(contesto)
            try:
                yield contesto
            finally:
                # Dentro una transazione più ampia (una richiesta, un test)
                # set_config locale durerebbe fino in fondo: va rimesso a mano.
                _scrivi_sul_database(precedente)
    finally:
        _contesto.reset(token)


def contesto_cliente(cliente_id: UUID | str):
    return _entra(Contesto(cliente_id=UUID(str(cliente_id))))


def contesto_piattaforma():
    return _entra(Contesto(cliente_id=None, piattaforma=True))
