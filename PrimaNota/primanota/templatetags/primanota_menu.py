"""Per il menu del portale: {% load primanota_menu %}{% primanota_visibile utente as show_primanota %}"""

import logging

from django import template

register = template.Library()


@register.simple_tag
def primanota_visibile(utente):
    # Un errore qui non deve mai impedire di aprire il menu.
    try:
        from primanota.services.accesso import can_access_primanota
        return can_access_primanota(utente)
    except Exception:
        logging.getLogger(__name__).exception("Visibilità Prima Nota nel menu")
        return False
