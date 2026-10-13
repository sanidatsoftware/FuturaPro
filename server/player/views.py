from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin


def schermo(request):
    """Il player nel browser: un PC in modalità kiosk, o la WebView delle app native."""
    return render(request, "player/schermo.html", {"modo": "player"})


@xframe_options_sameorigin
def anteprima(request, monitor_id):
    """L'anteprima di un monitor nel pannello; i dati li legge con la sessione dell'utente."""
    return render(request, "player/schermo.html", {"modo": "anteprima", "monitor": monitor_id})
