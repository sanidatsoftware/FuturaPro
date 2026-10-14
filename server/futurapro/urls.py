from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from audit.api import AuditClienteViewSet, AuditPiattaformaViewSet
from clienti.api import AbilitazioniView, ClientiViewSet, InsegneViewSet, SediViewSet
from contenuti.api import (
    AnteprimaManifestView,
    AnteprimaView,
    CampagneViewSet,
    ContenutiViewSet,
    FilePlayerView,
    PalinsestoPlayerView,
    PlaylistViewSet,
    PromozioniViewSet,
    EventiViewSet,
    ListiniViewSet,
    CaricaListinoView,
    PubblicaView,
    PubblicazioniViewSet,
)
from dispositivi.api import (
    GruppiViewSet,
    HeartbeatView,
    MonitorViewSet,
    OrariViewSet,
    StatoSchermiView,
    DownloadView,
    RichiestaAbbinamentoView,
    SchermataPlayerView,
    StatoPlayerView,
)
from eliminacode import views as eliminacode
from eliminacode.api import AnnuncioPlayerView, EmettiPlayerView, PulsanteView, RepartiViewSet, SerieAnnunciViewSet
from layout import views as layout
from layout.api import CercaLocalitaView, DatiZonaPlayerView, DatiZonaView, LayoutViewSet
from pannello import views as pannello_viste
from pannello.views import pannello
from player import views as player
from teleassistenza.api import SessioniViewSet
from utenti.api import IoView, UtentiClienteViewSet, UtentiPiattaformaViewSet

router = DefaultRouter()
# Piattaforma: solo Administrator Assoluto (e tecnici, in lettura, per l'elenco clienti).
router.register("piattaforma/clienti", ClientiViewSet, basename="clienti")
router.register("piattaforma/utenti", UtentiPiattaformaViewSet, basename="utenti-piattaforma")
router.register("piattaforma/audit", AuditPiattaformaViewSet, basename="audit-piattaforma")
# Cliente: il proprio per gli utenti del cliente, quello in X-Cliente per la piattaforma.
router.register("insegne", InsegneViewSet, basename="insegne")
router.register("sedi", SediViewSet, basename="sedi")
router.register("gruppi", GruppiViewSet, basename="gruppi")
router.register("monitor", MonitorViewSet, basename="monitor")
router.register("orari", OrariViewSet, basename="orari")
router.register("utenti", UtentiClienteViewSet, basename="utenti")
router.register("audit", AuditClienteViewSet, basename="audit")
router.register("contenuti", ContenutiViewSet, basename="contenuti")
router.register("playlist", PlaylistViewSet, basename="playlist")
router.register("pubblicazioni", PubblicazioniViewSet, basename="pubblicazioni")
router.register("campagne", CampagneViewSet, basename="campagne")
router.register("promozioni", PromozioniViewSet, basename="promozioni")
router.register("eventi", EventiViewSet, basename="eventi")
router.register("listini", ListiniViewSet, basename="listini")
router.register("layout", LayoutViewSet, basename="layout")
router.register("reparti", RepartiViewSet, basename="reparti")
router.register("annunci", SerieAnnunciViewSet, basename="annunci")
router.register("teleassistenza/sessioni", SessioniViewSet, basename="teleassistenza")

urlpatterns = [
    path("api/io/", IoView.as_view(), name="io"),
    path("api/abilitazioni/", AbilitazioniView.as_view(), name="abilitazioni"),
    path("api/player/abbinamento/", RichiestaAbbinamentoView.as_view(), name="player-abbinamento"),
    path("api/player/stato/", StatoPlayerView.as_view(), name="player-stato"),
    path("api/pubblica/", PubblicaView.as_view(), name="pubblica"),
    path("api/anteprima/<uuid:monitor_id>/", AnteprimaView.as_view(), name="anteprima"),
    path("api/anteprima/<uuid:monitor_id>/manifest/", AnteprimaManifestView.as_view(), name="anteprima-manifest"),
    path("api/player/palinsesto/", PalinsestoPlayerView.as_view(), name="player-palinsesto"),
    path("api/player/file/<uuid:contenuto_id>/", FilePlayerView.as_view(), name="player-file"),
    path("api/zone/<uuid:zona_id>/dati/", DatiZonaView.as_view(), name="zona-dati"),
    path("api/meteo/localita/", CercaLocalitaView.as_view(), name="meteo-localita"),
    path("api/player/zone/<uuid:zona_id>/dati/", DatiZonaPlayerView.as_view(), name="player-zona-dati"),
    path("api/player/zone/<uuid:zona_id>/emetti/", EmettiPlayerView.as_view(), name="player-emetti"),
    path("api/eliminacode/pulsante/", PulsanteView.as_view(), name="pulsante-stato"),
    path("api/eliminacode/pulsante/<str:operazione>/", PulsanteView.as_view(), name="pulsante"),
    path("api/player/annunci/<uuid:file_id>/", AnnuncioPlayerView.as_view(), name="player-annuncio"),
    path("api/listini/carica/", CaricaListinoView.as_view(), name="listino-carica"),
    path("api/download/", DownloadView.as_view(), name="download"),
    path("api/stato-schermi/", StatoSchermiView.as_view(), name="stato-schermi"),
    path("api/player/heartbeat/", HeartbeatView.as_view(), name="player-heartbeat"),
    path("api/player/schermata/", SchermataPlayerView.as_view(), name="player-schermata"),
    path("api/", include(router.urls)),
    path("api/piattaforma/aspetto/", pannello_viste.AspettoView.as_view(), name="aspetto"),
    # La pagina di accesso è la nostra, anche per chi arriva dall'API navigabile.
    path("api/sessione/login/", pannello_viste.Accesso.as_view()),
    path("api/sessione/", include("rest_framework.urls")),
    path("accesso/", pannello_viste.Accesso.as_view(), name="accesso"),
    path("aspetto/logo/", pannello_viste.logo, name="logo"),
    path("", RedirectView.as_view(url="/pannello/", permanent=False)),
    path("pannello/", pannello, name="pannello"),
    path("palinsesto/", pannello_viste.palinsesto, name="palinsesto"),
    path("player/", player.schermo, name="player"),
    path("player/sw.js", player.service_worker, name="player-sw"),
    path("banco/", eliminacode.banco, name="banco"),
    path("editor/", layout.editor, name="editor"),
    path("editor/<uuid:layout_id>/", layout.editor, name="editor-layout"),
    path("anteprima/<uuid:monitor_id>/", player.anteprima, name="anteprima-schermo"),
]
