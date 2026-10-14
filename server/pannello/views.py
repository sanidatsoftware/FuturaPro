from django.contrib.auth.views import LoginView, redirect_to_login
from django.http import FileResponse, Http404
from django.shortcuts import render
from rest_framework import serializers
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from audit.models import registra
from contenuti.file import riconosci
from core.api import SOLO_ASSOLUTO, TUTTI, VistaConContesto

from .models import Aspetto

LOGO_MAX = 2 * 1024 * 1024


def pannello(request):
    """Il pannello: una pagina sola, i dati passano dalle API con la sessione."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return render(request, "pannello/pannello.html")


def palinsesto(request):
    """«Creazione palinsesto»: libreria, campagne e calendario. I dati passano dalle API."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return render(request, "pannello/palinsesto.html")


class Accesso(LoginView):
    template_name = "pannello/accesso.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        # Dalla scheda «Aspetto»: vedere la pagina anche da dentro.
        if request.GET.get("anteprima"):
            self.redirect_authenticated_user = False
        return super().dispatch(request, *args, **kwargs)


def logo(request):
    """Il logo della pagina di accesso: pubblico, come ogni logo."""
    aspetto = Aspetto.attuale()
    if not aspetto.logo:
        raise Http404()
    risposta = FileResponse(aspetto.logo.open("rb"))
    risposta["Cache-Control"] = "public, max-age=86400"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta


class AspettoSerializer(serializers.ModelSerializer):
    colore = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)
    logo = serializers.FileField(required=False, allow_null=True, write_only=True)
    ha_logo = serializers.SerializerMethodField()

    class Meta:
        model = Aspetto
        fields = ["nome_app", "sottotitolo", "colore", "logo", "ha_logo", "modificato"]
        read_only_fields = ["modificato"]

    def get_ha_logo(self, aspetto):
        return bool(aspetto.logo)

    def validate_logo(self, file):
        if file is None:
            return None
        if file.size > LOGO_MAX:
            raise serializers.ValidationError("Il logo supera 2 MB.")
        # Solo immagini riconosciute dal contenuto: niente SVG, che può contenere script.
        formato = riconosci(file)
        if formato is None or formato[0] != "immagine":
            raise serializers.ValidationError("Il logo dev'essere un'immagine PNG, JPEG, GIF o WebP.")
        return file

    def update(self, aspetto, dati):
        if "logo" in dati:
            nuovo = dati.pop("logo")
            if aspetto.logo:
                aspetto.logo.delete(save=False)
            if nuovo is not None:
                aspetto.logo.save(f"logo{nuovo.name[nuovo.name.rfind('.'):].lower() if '.' in nuovo.name else ''}", nuovo, save=False)
        return super().update(aspetto, dati)


class AspettoView(VistaConContesto, RetrieveUpdateAPIView):
    """Nome e logo della piattaforma: li cambia solo l'Administrator Assoluto."""

    ambito = "piattaforma"
    ruoli_lettura = TUTTI
    ruoli_scrittura = SOLO_ASSOLUTO
    serializer_class = AspettoSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        aspetto = Aspetto.attuale()
        if aspetto._state.adding:
            aspetto.save()
        return aspetto

    def perform_update(self, serializer):
        registra(self.request.user, "aspetto_modificato", serializer.save())
