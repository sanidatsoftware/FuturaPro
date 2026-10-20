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
    """Larghezza in % di una barra rispetto al valore massimo, col punto decimale (va nel CSS, non si localizza)."""
    try:
        return f"{float(valore) / float(massimo) * 100:.2f}" if float(massimo) else "0"
    except (TypeError, ValueError, ZeroDivisionError):
        return "0"


@register.filter
def get_item(contenitore, chiave):
    """Elemento di un dizionario o di una lista: {{ scala|get_item:livello }}."""
    try:
        return contenitore[chiave]
    except (KeyError, IndexError, TypeError):
        return ""


@register.filter
def cifra(valore, misura):
    """Numero di una matrice: importi con due decimali, pezzi e clienti interi (o un decimale nelle medie)."""
    from ..services.fasce_orarie import formato
    try:
        return formato(Decimal(str(valore)), misura)
    except (InvalidOperation, ValueError, TypeError):
        return "—"
