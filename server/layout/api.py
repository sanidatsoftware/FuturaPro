from django.core.exceptions import ValidationError
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Abilitazioni
from contenuti.models import Contenuto, Tipo
from core.api import GESTIONE, TUTTI, RiferimentoCliente, ViewSetCliente, VistaConContesto
from core.contesto import contesto_cliente
from dispositivi.api import VistaPlayer, credenziale_dalla_richiesta
from dispositivi.models import Monitor
from utenti.models import Ruolo

from . import fonti
from .manifest import layout_del_monitor
from .models import Layout, Orientamento, TipoZona, Zona
from .zone import MODELLI, valida_configurazione


class ZonaSerializer(serializers.ModelSerializer):
    x = serializers.FloatField(min_value=0, max_value=100)
    y = serializers.FloatField(min_value=0, max_value=100)
    larghezza = serializers.FloatField(min_value=0.5, max_value=100)
    altezza = serializers.FloatField(min_value=0.5, max_value=100)

    class Meta:
        model = Zona
        fields = ["id", "tipo", "nome", "x", "y", "larghezza", "altezza", "livello", "configurazione"]
        read_only_fields = ["id"]

    def validate(self, dati):
        # Un piccolo margine per gli arrotondamenti di chi trascina le zone nel pannello.
        if dati["x"] + dati["larghezza"] > 100.01 or dati["y"] + dati["altezza"] > 100.01:
            raise serializers.ValidationError("La zona esce dallo schermo.")
        dati["configurazione"] = valida_configurazione(dati["tipo"], dati.get("configurazione"))
        return dati


def salva_zone(layout, zone):
    """Sostituisce tutte le zone: il pannello manda sempre il layout intero."""
    Zona.objects.filter(layout=layout).delete()
    Zona.objects.bulk_create(Zona(cliente_id=layout.cliente_id, layout=layout, **zona) for zona in zone)


class LayoutSerializer(serializers.ModelSerializer):
    zone = ZonaSerializer(many=True, required=False)
    immagine_sfondo = RiferimentoCliente(Contenuto, required=False, allow_null=True)
    sfondo = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)

    class Meta:
        model = Layout
        fields = [
            "id", "nome", "orientamento", "sfondo", "immagine_sfondo", "carattere",
            "formato_larghezza", "formato_altezza", "predefinito", "zone", "creato", "modificato",
        ]
        read_only_fields = ["creato", "modificato"]
        extra_kwargs = {
            "formato_larghezza": {"min_value": 100, "max_value": 20000},
            "formato_altezza": {"min_value": 100, "max_value": 20000},
        }

    def validate(self, dati):
        larghezza = dati.get("formato_larghezza", getattr(self.instance, "formato_larghezza", None))
        altezza = dati.get("formato_altezza", getattr(self.instance, "formato_altezza", None))
        if (larghezza is None) != (altezza is None):
            raise serializers.ValidationError("Formato delle immagini: indica sia la larghezza sia l'altezza, o nessuna delle due.")
        return dati

    def validate_immagine_sfondo(self, contenuto):
        if contenuto is not None and contenuto.tipo != Tipo.IMMAGINE:
            raise serializers.ValidationError("Lo sfondo deve essere un'immagine.")
        return contenuto

    def validate_zone(self, zone):
        if sum(1 for z in zone if z["tipo"] == TipoZona.SLIDE and z["configurazione"]["sorgente"] == "palinsesto") > 1:
            raise serializers.ValidationError("Una sola zona di slide può mostrare il palinsesto.")
        return zone

    def create(self, dati):
        zone = dati.pop("zone", [])
        layout = super().create(dati)
        salva_zone(layout, zone)
        return layout

    def update(self, layout, dati):
        zone = dati.pop("zone", None)
        if "orientamento" in dati and dati["orientamento"] != layout.orientamento and layout.monitor.exists():
            raise serializers.ValidationError({"orientamento": "Il layout è assegnato a monitor con l'altro orientamento."})
        layout = super().update(layout, dati)
        if zone is not None:
            salva_zone(layout, zone)
        return layout


class DaModelloSerializer(serializers.Serializer):
    modello = serializers.ChoiceField(list(MODELLI))
    nome = serializers.CharField(max_length=200, required=False)
    localita = serializers.CharField(max_length=100, required=False)
    latitudine = serializers.FloatField(required=False)
    longitudine = serializers.FloatField(required=False)
    feed = serializers.ListField(child=serializers.URLField(), required=False)
    messaggi = serializers.ListField(child=serializers.CharField(max_length=300), required=False)


class LayoutViewSet(ViewSetCliente):
    """I layout del cliente. L'AdminCliente li gestisce se l'Administrator Assoluto lo consente."""

    ruoli_scrittura = GESTIONE
    serializer_class = LayoutSerializer

    def get_queryset(self):
        return Layout.objects.prefetch_related("zone")

    def _verifica_abilitazione(self):
        if self.request.user.ruolo != Ruolo.ADMIN_ASSOLUTO and not Abilitazioni.objects.get().admin_gestisce_layout:
            raise exceptions.PermissionDenied("La gestione dei layout non è abilitata per questo cliente.")

    def perform_create(self, serializer):
        self._verifica_abilitazione()
        self._togli_predefinito(serializer.validated_data)
        layout = serializer.save()
        registra(self.request.user, "layout_creato", layout, nome=layout.nome)

    def perform_update(self, serializer):
        self._verifica_abilitazione()
        self._togli_predefinito(serializer.validated_data, serializer.instance)
        layout = serializer.save()
        registra(self.request.user, "layout_modificato", layout, nome=layout.nome)

    def _togli_predefinito(self, dati, layout=None):
        # Prima del salvataggio, altrimenti scatta il vincolo di unicità del database.
        if dati.get("predefinito"):
            orientamento = dati.get("orientamento") or (layout.orientamento if layout else Orientamento.ORIZZONTALE)
            altri = Layout.objects.filter(orientamento=orientamento, predefinito=True)
            if layout is not None:
                altri = altri.exclude(id=layout.id)
            altri.update(predefinito=False)

    def perform_destroy(self, layout):
        self._verifica_abilitazione()
        registra(self.request.user, "layout_eliminato", layout, nome=layout.nome)
        layout.delete()

    @action(detail=False, methods=["post"], url_path="da-modello")
    def da_modello(self, request):
        """Crea un layout da uno dei modelli pronti; meteo e notizie prendono località e feed indicati."""
        self._verifica_abilitazione()
        dati = DaModelloSerializer(data=request.data)
        dati.is_valid(raise_exception=True)
        richiesta = dati.validated_data
        modello = MODELLI[richiesta["modello"]]

        zone = []
        for livello, (tipo, (x, y, larghezza, altezza), configurazione) in enumerate(modello["zone"]):
            configurazione = dict(configurazione or {})
            if tipo == TipoZona.METEO:
                configurazione.update({k: richiesta.get(k) for k in ("localita", "latitudine", "longitudine")})
            elif tipo == TipoZona.NOTIZIE:
                configurazione.update(feed=richiesta.get("feed", []), messaggi=richiesta.get("messaggi", []))
            zone.append(
                {"tipo": tipo, "x": x, "y": y, "larghezza": larghezza, "altezza": altezza,
                 "livello": livello, "configurazione": configurazione}
            )
        serializer = self.get_serializer(
            data={
                "nome": richiesta.get("nome") or modello["nome"],
                "orientamento": modello["orientamento"],
                "sfondo": modello.get("sfondo", "#000000"),
                "zone": zone,
            }
        )
        serializer.is_valid(raise_exception=True)
        layout = serializer.save()
        registra(request.user, "layout_creato", layout, nome=layout.nome, modello=richiesta["modello"])
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def modelli(self, request):
        return Response(
            [{"modello": chiave, "nome": m["nome"], "orientamento": m["orientamento"]} for chiave, m in MODELLI.items()]
        )


def dati_zona(zona, monitor=None) -> dict:
    """I dati dinamici di una zona (meteo, notizie, code), già pronti per il motore."""
    configurazione = zona.configurazione
    if zona.tipo in (TipoZona.CODA, TipoZona.PRENDI_NUMERO):
        from eliminacode.api import reparti_della_zona

        return {"code": [r.stato() for r in reparti_della_zona(configurazione, monitor)]}
    if zona.tipo == TipoZona.METEO:
        return {"meteo": fonti.meteo(configurazione["latitudine"], configurazione["longitudine"])}
    if zona.tipo == TipoZona.NOTIZIE:
        titoli = fonti.notizie(configurazione.get("feed", []), configurazione.get("aggiornamento_minuti", 15))
        return {"notizie": configurazione.get("messaggi", []) + titoli}
    if zona.tipo == TipoZona.LISTINO:
        from contenuti.listini import dati_listino
        from contenuti.models import Listino

        listino = Listino.objects.filter(id=configurazione.get("listino")).first()
        return {"listino": dati_listino(listino) if listino else {"nome": "", "righe": [], "aggiornato": None}}
    raise exceptions.NotFound()


class DatiZonaView(VistaConContesto, APIView):
    """Per l'anteprima nel pannello: gli stessi dati che riceve il player."""

    ruoli_lettura = TUTTI

    def get(self, request, zona_id):
        zona = Zona.objects.filter(id=zona_id).first()
        if zona is None:
            raise exceptions.NotFound()
        # L'anteprima di un monitor passa il monitor: le code sono quelle della sua sede.
        monitor = None
        if request.query_params.get("monitor"):
            try:
                monitor = Monitor.objects.filter(id=request.query_params["monitor"]).first()
            except ValidationError:
                monitor = None
        return Response(dati_zona(zona, monitor))


class CercaLocalitaView(VistaConContesto, APIView):
    """Per scegliere la località del meteo scrivendo il nome della città."""

    ruoli_lettura = GESTIONE

    def get(self, request):
        nome = request.query_params.get("nome", "").strip()
        if len(nome) < 2:
            raise exceptions.ValidationError({"nome": "Scrivi almeno due lettere."})
        try:
            return Response(fonti.cerca_localita(nome))
        except (OSError, ValueError):
            return Response({"errore": "Servizio meteo non raggiungibile."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)



class DatiZonaPlayerView(VistaPlayer):
    """Meteo e notizie per il player, solo per le zone del layout che sta mostrando."""

    def get(self, request, zona_id):
        credenziale = credenziale_dalla_richiesta(request)
        with contesto_cliente(credenziale.cliente_id):
            monitor = Monitor.objects.get(id=credenziale.monitor_id)
            layout = layout_del_monitor(monitor)
            zona = layout and layout.zone.filter(id=zona_id).first()
            if not zona:
                raise exceptions.NotFound()
            return Response(dati_zona(zona, monitor))
