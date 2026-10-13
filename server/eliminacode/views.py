from django.shortcuts import render


def banco(request):
    """La pagina del banco: tablet, PC o browser della bilancia. I dati li legge con la sessione o con la chiave."""
    return render(request, "eliminacode/banco.html")
