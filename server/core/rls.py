"""Operazioni di migrazione per la Row-Level Security di PostgreSQL.

FORCE ROW LEVEL SECURITY applica le policy anche al proprietario delle
tabelle, cioè all'utente con cui si collega l'applicazione: senza, le policy
non proteggerebbero niente. Quando le variabili di contesto non sono
impostate ``current_setting(..., true)`` vale NULL o stringa vuota e la
condizione è falsa: senza contesto non si legge e non si scrive nulla.
"""

from django.db import migrations

CONDIZIONE = (
    "current_setting('app.piattaforma', true) = 'on' "
    "OR {colonna}::text = current_setting('app.cliente_id', true)"
)


def proteggi(tabella: str, colonna: str = "cliente_id", condizione: str | None = None) -> migrations.RunSQL:
    """``condizione`` sostituisce quella standard, per le tabelle senza colonna cliente."""
    condizione = condizione or CONDIZIONE.format(colonna=colonna)
    return migrations.RunSQL(
        sql=[
            f'ALTER TABLE "{tabella}" ENABLE ROW LEVEL SECURITY',
            f'ALTER TABLE "{tabella}" FORCE ROW LEVEL SECURITY',
            f'CREATE POLICY isolamento_cliente ON "{tabella}" '
            f"USING ({condizione}) WITH CHECK ({condizione})",
        ],
        reverse_sql=[
            f'DROP POLICY IF EXISTS isolamento_cliente ON "{tabella}"',
            f'ALTER TABLE "{tabella}" NO FORCE ROW LEVEL SECURITY',
            f'ALTER TABLE "{tabella}" DISABLE ROW LEVEL SECURITY',
        ],
    )


def tramite(tabella_collegata: str, colonna: str) -> str:
    """Condizione per le tabelle ponte molti-a-molti: la riga è visibile se lo è quella collegata.

    La sottoquery passa anch'essa dalla Row-Level Security di ``tabella_collegata``.
    """
    return f'EXISTS (SELECT 1 FROM "{tabella_collegata}" t WHERE t.id = {colonna})'
