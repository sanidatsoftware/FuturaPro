"""Formati italiani per importi e percentuali nelle pagine Chiusure Fiscali."""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _numero(valore, decimali):
    try:
        testo = f"{Decimal(str(valore)):,.{decimali}f}"
    except (InvalidOperation, ValueError, TypeError):
        return "—"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".")


@register.filter
def euro(valore):
    """1234.5 -> «1.234,50 €»"""
    return "—" if valore in (None, "") else f"{_numero(valore, 2)} €"


@register.filter
def intero(valore):
    return "—" if valore in (None, "") else _numero(valore, 0)


@register.filter
def perc(valore):
    return "—" if valore in (None, "") else f"{_numero(valore, 1)}%"


@register.filter
def quota(valore, massimo):
    """Larghezza in % di una barra rispetto al valore massimo."""
    try:
        return round(float(valore) / float(massimo) * 100, 2) if float(massimo) else 0
    except (TypeError, ValueError):
        return 0
