from django.contrib.auth.views import LoginView, redirect_to_login
from django.http import FileResponse, Http404
from django.shortcuts import render
from rest_framework import exceptions, serializers
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from audit.models import registra
from contenuti.file import riconosci
from rest_framework.decorators import action

from core.api import GESTIONE, SOLO_ASSOLUTO, TUTTI, ViewSetCliente, VistaConContesto

from .models import Aspetto, ImpostazioniEmail, InvioRapporto

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
    """Nome e logo della piattaforma: li cambia solo il SystemAdministrator."""

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


class ImpostazioniEmailSerializer(serializers.ModelSerializer):
    # La password si scrive e basta: non torna mai indietro dall'API.
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=300)
    password_impostata = serializers.SerializerMethodField()
    porta = serializers.IntegerField(min_value=1, max_value=65535, required=False)

    class Meta:
        model = ImpostazioniEmail
        fields = ["attivo", "host", "porta", "sicurezza", "utente", "password", "password_impostata", "mittente", "modificato"]
        read_only_fields = ["modificato"]

    def get_password_impostata(self, impostazioni):
        return bool(impostazioni.password_cifrata)

    def validate(self, dati):
        attivo = dati.get("attivo", getattr(self.instance, "attivo", False))
        host = dati.get("host", getattr(self.instance, "host", ""))
        if attivo and not host:
            raise serializers.ValidationError({"host": "Indica il server SMTP."})
        return dati

    def update(self, impostazioni, dati):
        from core.email import cifra

        password = dati.pop("password", None)
        if password is not None:
            impostazioni.password_cifrata = cifra(password)
        return super().update(impostazioni, dati)


class EmailView(VistaConContesto, RetrieveUpdateAPIView):
    """Il server email dell'azienda (SMTP, account, mittente): lo imposta chi gestisce il cliente.
    POST: un'email di prova."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = GESTIONE
    serializer_class = ImpostazioniEmailSerializer

    def get_object(self):
        impostazioni = ImpostazioniEmail.objects.first()
        return impostazioni or ImpostazioniEmail.objects.create()

    def retrieve(self, request, *args, **kwargs):
        from django.conf import settings

        from core import email

        dati = self.get_serializer(self.get_object()).data
        return Response({**dati, "origine": email.origine(), "server": bool(settings.EMAIL_HOST)})

    def perform_update(self, serializer):
        registra(self.request.user, "email_modificata", serializer.save())

    def post(self, request):
        from core import email

        destinatario = str(request.data.get("a") or request.user.email or "").strip()
        if not destinatario:
            raise exceptions.ValidationError({"a": "Indica a chi mandare l'email di prova."})
        if not email.configurata():
            raise exceptions.ValidationError("Nessun server email configurato.")
        try:
            email.invia("FuturaPro: email di prova", "Se leggi questo messaggio, le email dell'azienda partono correttamente.", [destinatario])
        except Exception as errore:
            raise exceptions.ValidationError(f"L'email non è partita: {errore}")
        return Response({"inviata": destinatario})


class InvioRapportoSerializer(serializers.ModelSerializer):
    email = serializers.ListField(child=serializers.EmailField(), min_length=1, max_length=20)

    class Meta:
        model = InvioRapporto
        fields = ["id", "tipo", "nome", "attivo", "email", "frequenza", "filtri", "ultimo_periodo", "ultimo_invio", "ultimo_errore"]
        read_only_fields = ["ultimo_periodo", "ultimo_invio", "ultimo_errore"]

    def validate_filtri(self, filtri):
        if not isinstance(filtri, dict):
            raise serializers.ValidationError("Filtri non validi.")
        return {k: str(v)[:120] for k, v in filtri.items() if k in ("raggruppa", "fornitore", "campagna", "sede") and v}


class InviiRapportiViewSet(ViewSetCliente):
    """I rapporti mandati da soli per email, con i loro destinatari (?tipo= per filtrare)."""

    ruoli_scrittura = GESTIONE
    serializer_class = InvioRapportoSerializer

    def get_queryset(self):
        invii = InvioRapporto.objects.all()
        tipo = self.request.query_params.get("tipo")
        return invii.filter(tipo=tipo) if tipo else invii

    def perform_create(self, serializer):
        registra(self.request.user, "invio_rapporto_creato", serializer.save())

    def perform_update(self, serializer):
        registra(self.request.user, "invio_rapporto_modificato", serializer.save())

    @action(detail=True, methods=["post"])
    def invia(self, request, pk=None):
        """Lo manda subito, con il periodo appena concluso (non cambia la pianificazione)."""
        from django.utils import timezone

        from core import email

        from . import rapporti

        invio = self.get_object()
        if not email.configurata():
            raise exceptions.ValidationError("L'azienda non ha ancora un server email: impostalo in «Impostazioni → Email».")
        _, dal, al = rapporti.periodo(invio.frequenza, timezone.localdate())
        try:
            rapporti.manda(invio, dal, al)
        except Exception as errore:
            raise exceptions.ValidationError(f"L'email non è partita: {errore}")
        return Response({"inviato": True, "dal": dal, "al": al})
