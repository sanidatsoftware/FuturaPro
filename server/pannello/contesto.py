from .models import Aspetto


def aspetto(request):
    """Nome, colore e logo della piattaforma in ogni pagina."""
    return {"aspetto": Aspetto.attuale()}
