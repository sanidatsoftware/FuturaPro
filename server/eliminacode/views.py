from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin


# Si apre anche dentro il pannello (stesso sito), non in pagine esterne.
@xframe_options_sameorigin
def banco(request):
    """La pagina del banco: tablet, PC o browser della bilancia. I dati li legge con la sessione o con la chiave."""
    return render(request, "eliminacode/banco.html")


# Si apre anche dentro il pannello (stesso sito), non in pagine esterne.
@xframe_options_sameorigin
def biglietto(request, codice):
    """La pagina della coda sul telefono (dal QR del biglietto): pubblica, senza dati personali."""
    return render(request, "eliminacode/biglietto.html", {"codice": codice})
