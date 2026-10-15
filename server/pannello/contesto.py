from .models import Aspetto


def aspetto(request):
    """Nome, colore e logo della piattaforma, e il tema scelto dall'utente, in ogni pagina."""
    utente = getattr(request, "user", None)
    tema = utente.tema if utente is not None and utente.is_authenticated else "auto"
    from .accesso import pulita

    attuale = Aspetto.attuale()
    riquadro = pulita(attuale.accesso, attuale.sottotitolo)["logo"]["riquadro_barra"]
    return {"aspetto": attuale, "tema": tema, "logo_riquadro": riquadro}
