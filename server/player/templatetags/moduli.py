"""I moduli JavaScript con la loro versione nell'indirizzo («?v=» e l'impronta del contenuto).

Il browser tiene in memoria i file statici: dopo un aggiornamento può prendere un modulo nuovo
e uno vecchio (es. motore.js aggiornato con ticket.js di prima) e la pagina non parte. Con
l'impronta nell'indirizzo ogni versione di un file è un indirizzo diverso: niente file misti.

    {% load moduli %}
    {% mappa_moduli %}                       (prima degli script: la mappa degli import)
    <script type="module" src="{% modulo 'player/avvio.js' %}"></script>
"""

import hashlib
import json
from functools import lru_cache

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()

CARTELLE = ("player", "pannello", "layout")


def _impronta(percorso: str) -> str:
    try:
        with open(percorso, "rb") as file:
            return hashlib.sha256(file.read()).hexdigest()[:10]
    except OSError:
        return ""


def _calcola() -> dict:
    """{nome statico: impronta} per i moduli delle cartelle del progetto."""
    impronte = {}
    for finder in finders.get_finders():
        for nome, archivio in finder.list([]):
            nome = nome.replace("\\", "/")
            if nome.split("/")[0] not in CARTELLE or not nome.endswith(".js") or "/vendor/" in nome or nome in impronte:
                continue
            impronte[nome] = _impronta(archivio.path(nome))
    return impronte


_in_memoria = lru_cache(maxsize=1)(_calcola)


def impronte() -> dict:
    # In sviluppo i file cambiano senza riavviare: si ricalcola ogni volta.
    return _calcola() if settings.DEBUG else _in_memoria()


def indirizzo(nome: str) -> str:
    impronta = impronte().get(nome)
    return f"{static(nome)}?v={impronta}" if impronta else static(nome)


@register.simple_tag
def modulo(nome):
    return indirizzo(nome)


@register.simple_tag
def mappa_moduli():
    mappa = {"imports": {static(nome): f"{static(nome)}?v={impronta}" for nome, impronta in impronte().items() if impronta}}
    return mark_safe(f'<script type="importmap">{json.dumps(mappa)}</script>')
