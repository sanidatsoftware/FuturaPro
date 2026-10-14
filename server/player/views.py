from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin


def schermo(request):
    """Il player nel browser: un PC in modalità kiosk, o la WebView delle app native."""
    return render(request, "player/schermo.html", {"modo": "player"})


@xframe_options_sameorigin
def anteprima(request, monitor_id):
    """L'anteprima di un monitor nel pannello; i dati li legge con la sessione dell'utente."""
    return render(request, "player/schermo.html", {"modo": "anteprima", "monitor": monitor_id})


def service_worker(request):
    """Servito sotto /player/ perché il suo raggio d'azione sia la pagina del player."""
    risposta = render(request, "player/sw.js", content_type="text/javascript; charset=utf-8")
    risposta["Cache-Control"] = "no-cache"
    return risposta
