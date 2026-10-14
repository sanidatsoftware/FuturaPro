from .models import Aspetto


def aspetto(request):
    """Nome, colore e logo della piattaforma, e il tema scelto dall'utente, in ogni pagina."""
    utente = getattr(request, "user", None)
    tema = utente.tema if utente is not None and utente.is_authenticated else "auto"
    return {"aspetto": Aspetto.attuale(), "tema": tema}
