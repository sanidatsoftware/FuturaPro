from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render


def pannello(request):
    """Il pannello: una pagina sola, i dati passano dalle API con la sessione."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), "/api/sessione/login/")
    return render(request, "pannello/pannello.html")
