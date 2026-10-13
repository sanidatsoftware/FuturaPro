from django.shortcuts import render


def editor(request, layout_id=None):
    """L'editor visuale dei layout; senza id, l'elenco. I dati passano dalle API con la sessione."""
    return render(request, "layout/editor.html", {"layout_id": layout_id})
