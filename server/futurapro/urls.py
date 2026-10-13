from django.urls import include, path
from rest_framework.routers import DefaultRouter

from audit.api import AuditClienteViewSet, AuditPiattaformaViewSet
from clienti.api import AbilitazioniView, ClientiViewSet, SediViewSet
from contenuti.api import (
    AnteprimaView,
    ContenutiViewSet,
    FilePlayerView,
    PalinsestoPlayerView,
    PlaylistViewSet,
    PubblicaView,
    PubblicazioniViewSet,
)
from dispositivi.api import GruppiViewSet, HeartbeatView, MonitorViewSet, RichiestaAbbinamentoView, StatoPlayerView
from layout.api import CercaLocalitaView, DatiZonaPlayerView, DatiZonaView, LayoutViewSet
from teleassistenza.api import SessioniViewSet
from utenti.api import IoView, UtentiClienteViewSet, UtentiPiattaformaViewSet

router = DefaultRouter()
# Piattaforma: solo Administrator Assoluto (e tecnici, in lettura, per l'elenco clienti).
router.register("piattaforma/clienti", ClientiViewSet, basename="clienti")
router.register("piattaforma/utenti", UtentiPiattaformaViewSet, basename="utenti-piattaforma")
router.register("piattaforma/audit", AuditPiattaformaViewSet, basename="audit-piattaforma")
# Cliente: il proprio per gli utenti del cliente, quello in X-Cliente per la piattaforma.
router.register("sedi", SediViewSet, basename="sedi")
router.register("gruppi", GruppiViewSet, basename="gruppi")
router.register("monitor", MonitorViewSet, basename="monitor")
router.register("utenti", UtentiClienteViewSet, basename="utenti")
router.register("audit", AuditClienteViewSet, basename="audit")
router.register("contenuti", ContenutiViewSet, basename="contenuti")
router.register("playlist", PlaylistViewSet, basename="playlist")
router.register("pubblicazioni", PubblicazioniViewSet, basename="pubblicazioni")
router.register("layout", LayoutViewSet, basename="layout")
router.register("teleassistenza/sessioni", SessioniViewSet, basename="teleassistenza")

urlpatterns = [
    path("api/io/", IoView.as_view(), name="io"),
    path("api/abilitazioni/", AbilitazioniView.as_view(), name="abilitazioni"),
    path("api/player/abbinamento/", RichiestaAbbinamentoView.as_view(), name="player-abbinamento"),
    path("api/player/stato/", StatoPlayerView.as_view(), name="player-stato"),
    path("api/pubblica/", PubblicaView.as_view(), name="pubblica"),
    path("api/anteprima/<uuid:monitor_id>/", AnteprimaView.as_view(), name="anteprima"),
    path("api/player/palinsesto/", PalinsestoPlayerView.as_view(), name="player-palinsesto"),
    path("api/player/file/<uuid:contenuto_id>/", FilePlayerView.as_view(), name="player-file"),
    path("api/zone/<uuid:zona_id>/dati/", DatiZonaView.as_view(), name="zona-dati"),
    path("api/meteo/localita/", CercaLocalitaView.as_view(), name="meteo-localita"),
    path("api/player/zone/<uuid:zona_id>/dati/", DatiZonaPlayerView.as_view(), name="player-zona-dati"),
    path("api/player/heartbeat/", HeartbeatView.as_view(), name="player-heartbeat"),
    path("api/", include(router.urls)),
    path("api/sessione/", include("rest_framework.urls")),
]
