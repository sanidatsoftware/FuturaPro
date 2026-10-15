from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin


# Si apre anche dentro il pannello (stesso sito), non in pagine esterne.
@xframe_options_sameorigin
def editor(request, layout_id=None):
    """L'editor visuale dei layout; senza id, l'elenco. I dati passano dalle API con la sessione."""
    return render(request, "layout/editor.html", {"layout_id": layout_id})
