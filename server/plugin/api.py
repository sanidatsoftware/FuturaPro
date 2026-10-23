"""API dei plugin: impostazioni per azienda (/api/plugin/<tipo>/) e file di ogni negozio
(/api/fonti-plugin/). Le usa chi gestisce il cliente, se il SystemAdministrator ha abilitato il plugin."""

import re
from datetime import timedelta

from rest_framework import exceptions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import registra
from clienti.models import Abilitazioni, Sede
from core.api import GESTIONE, RiferimentoCliente, VistaConContesto, ViewSetCliente
from core.email import cifra
from dispositivi.models import Monitor

from . import filtro
from . import query as q
from .models import FiltroContenuti, FontePlugin, ImpostazioniPlugin, TipoPlugin

COLORE = re.compile(r"^#[0-9a-fA-F]{6}$")
CARATTERI = ["sans-serif", "serif", "Arial", "Verdana", "Tahoma", "Georgia", "Roboto", "Montserrat", "Oswald"]

# Il popup: valori predefiniti e controlli (tipo, minimo, massimo o scelte).
ASPETTO = {
    "carattere": ("sans-serif", CARATTERI),
    "dimensione": (100, (50, 250)),       # percentuale sulla grandezza automatica
    "larghezza": (70, (30, 100)),         # percentuale dello schermo
    "posizione": ("centro", ["centro", "alto", "basso"]),
    "sfondo": ("#ffffff", "colore"),
    "testo": ("#1d2330", "colore"),
    "colore_prezzo": ("#1f4e79", "colore"),
    "colore_offerta": ("#d32f2f", "colore"),
    "banner_testo": ("OFFERTA", 30),
    "banner_sfondo": ("#d32f2f", "colore"),
    "banner_colore": ("#ffffff", "colore"),
    "lampeggia": (True, bool),
    "mostra_prezzo_pieno": (True, bool),
    "colore_allergeni": ("#b71c1c", "colore"),
}


def aspetto_pulito(dati) -> dict:
    dati = dati if isinstance(dati, dict) else {}
    pulito = {}
    for chiave, (predefinito, regola) in ASPETTO.items():
        valore = dati.get(chiave, predefinito)
        if regola == "colore":
            valore = valore if isinstance(valore, str) and COLORE.match(valore) else predefinito
        elif regola is bool:
            valore = bool(valore)
        elif isinstance(regola, tuple):
            try:
                valore = max(regola[0], min(regola[1], int(valore)))
            except (TypeError, ValueError):
                valore = predefinito
        elif isinstance(regola, list):
            valore = valore if valore in regola else predefinito
        else:  # testo con lunghezza massima
            valore = str(valore or "")[:regola]
        pulito[chiave] = valore
    return pulito


VALIDITA_PROVA = timedelta(minutes=2)


def stato_prova(fonte) -> dict:
    """in_attesa, ok, errore, senza_risposta o mai."""
    from django.utils import timezone

    if fonte.prova_esito:
        return {"stato": "ok" if fonte.prova_esito.get("ok") else "errore", **fonte.prova_esito}
    if not fonte.prova_richiesta:
        return {"stato": "mai"}
    if timezone.now() - fonte.prova_richiesta <= VALIDITA_PROVA:
        return {"stato": "in_attesa", "chiesta": fonte.prova_richiesta.isoformat()}
    return {"stato": "senza_risposta", "messaggio": "Il Totem Master non ha risposto: è acceso e in linea?"}


def prove_per_il_monitor(monitor) -> list:
    """Le prove di accesso che questo schermo deve fare: tocca al Totem Master della sede
    (o, se la sede non ne ha uno, a uno qualsiasi dei suoi totem)."""
    from django.utils import timezone

    master = Monitor.objects.filter(sede_id=monitor.sede_id, totem_master=True).values_list("id", flat=True).first()
    if master is not None and master != monitor.id:
        return []
    attese = FontePlugin.objects.filter(
        sede_id=monitor.sede_id, prova_esito={}, prova_richiesta__gt=timezone.now() - VALIDITA_PROVA
    )
    return [{"tipo": f.tipo, "richiesta": f.prova_richiesta.isoformat()} for f in attese]


def abilitato(tipo: str) -> bool:
    abilitazioni = Abilitazioni.objects.first()
    return bool(abilitazioni and getattr(abilitazioni, f"plugin_{tipo}", False))


class ImpostazioniPluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImpostazioniPlugin
        fields = ["tipo", "attivo", "formato", "mappatura", "query", "aspetto", "timeout", "prefissi", "plu_inizio", "plu_lunghezza", "mostra_prezzo"]
        read_only_fields = ["tipo"]
        extra_kwargs = {"timeout": {"min_value": 2, "max_value": 120}, "plu_inizio": {"min_value": 1, "max_value": 12},
                        "plu_lunghezza": {"min_value": 1, "max_value": 7}}

    def validate_aspetto(self, valore):
        return aspetto_pulito(valore)

    def validate_formato(self, valore):
        if valore and valore not in q.PREIMPOSTAZIONI.get(self.instance.tipo, {}):
            raise serializers.ValidationError("Gestionale non previsto.")
        return valore

    def validate_query(self, valore):
        try:
            return q.valida_query(valore)
        except ValueError as errore:
            raise serializers.ValidationError(str(errore))

    def validate_prefissi(self, valore):
        if not isinstance(valore, list) or len(valore) > 30:
            raise serializers.ValidationError("Al massimo 30 prefissi.")
        puliti, visti = [], set()
        for p in valore:
            prefisso = str((p or {}).get("prefisso", "")).strip()
            if not re.fullmatch(r"\d{1,3}", prefisso):
                raise serializers.ValidationError(f"Prefisso non valido: «{prefisso}» (1-3 cifre, es. 20).")
            if prefisso in visti:
                raise serializers.ValidationError(f"Il prefisso {prefisso} è ripetuto.")
            visti.add(prefisso)
            puliti.append({"prefisso": prefisso, "reparto": str(p.get("reparto", ""))[:40], "codice": str(p.get("codice", "")).strip()[:20]})
        return puliti

    def validate(self, dati):
        tipo = self.instance.tipo
        attivo = dati.get("attivo", self.instance.attivo)
        query = dati.get("query", self.instance.query) or dati.get("formato", self.instance.formato)
        try:
            dati["mappatura"] = q.valida_mappatura(tipo, dati.get("mappatura", self.instance.mappatura), obbligatoria=attivo and not query)
        except ValueError as errore:
            raise serializers.ValidationError({"mappatura": errore.args[0]})
        if tipo == TipoPlugin.INGREDIENTI:
            inizio = dati.get("plu_inizio", self.instance.plu_inizio)
            lunghezza = dati.get("plu_lunghezza", self.instance.plu_lunghezza)
            if inizio + lunghezza - 1 > 12:
                raise serializers.ValidationError({"plu_lunghezza": "Il PLU deve stare nelle prime 12 cifre del codice."})
            # I prefissi servono solo a riconoscere le etichette della bilancia lette con il lettore:
            # senza, Info Ingredienti funziona dal pulsante sul totem (ricerca per codice o descrizione).
        return dati


class FontePluginSerializer(serializers.ModelSerializer):
    sede = RiferimentoCliente(Sede)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=200)
    ha_password = serializers.SerializerMethodField()

    class Meta:
        model = FontePlugin
        fields = ["id", "tipo", "sede", "indirizzo", "percorso", "utente", "password", "ha_password", "aggiorna_minuti", "orari",
                  "richiesta_copia", "prova"]
        read_only_fields = ["richiesta_copia"]
        extra_kwargs = {"aggiorna_minuti": {"min_value": 0, "max_value": 1440}}

    def validate(self, dati):
        minuti = dati.get("aggiorna_minuti", getattr(self.instance, "aggiorna_minuti", 15))
        orari = dati.get("orari", getattr(self.instance, "orari", []))
        if not minuti and not orari:
            raise serializers.ValidationError({"orari": "Indica almeno un orario o ogni quanti minuti copiare il file."})
        return dati

    prova = serializers.SerializerMethodField()

    def get_ha_password(self, fonte):
        return bool(fonte.password_cifrata)

    def get_prova(self, fonte):
        return stato_prova(fonte)

    def validate_orari(self, valore):
        if not isinstance(valore, list) or len(valore) > 8:
            raise serializers.ValidationError("Al massimo 8 orari.")
        orari = set()
        for orario in valore:
            orario = str(orario).strip()
            if not re.fullmatch(r"([01]?\d|2[0-3])[:.][0-5]\d", orario):
                raise serializers.ValidationError(f"Orario non valido: «{orario}» (es. 06:30).")
            ore, minuti = re.split(r"[:.]", orario)
            orari.add(f"{int(ore):02d}:{minuti}")
        return sorted(orari)

    def validate_indirizzo(self, valore):
        valore = valore.strip().strip("\\/")
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", valore):
            raise serializers.ValidationError("Indirizzo IP o nome del PC, es. 192.168.1.20")
        return valore

    def validate_percorso(self, valore):
        valore = valore.strip().replace("/", "\\").strip("\\")
        parti = [p for p in valore.split("\\") if p]
        if len(parti) < 2 or any(p in (".", "..") for p in parti) or any(c in valore for c in '<>:"|?*'):
            raise serializers.ValidationError("Cartella condivisa e file, es. Dati\\Prezzi\\articoli.db")
        return "\\".join(parti)

    def create(self, dati):
        password = dati.pop("password", "")
        return super().create({**dati, "password_cifrata": cifra(password)})

    def update(self, fonte, dati):
        password = dati.pop("password", None)
        if password is not None and password != "":
            fonte.password_cifrata = cifra(password)
        return super().update(fonte, dati)


class PluginView(VistaConContesto, APIView):
    """GET/PUT le impostazioni di un plugin, con i negozi (totem, file, stato della copia)."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = GESTIONE

    def _impostazioni(self, tipo):
        if tipo not in TipoPlugin.values:
            raise exceptions.NotFound()
        if not abilitato(tipo):
            raise exceptions.PermissionDenied("Plugin non abilitato per questa azienda: lo attiva il SystemAdministrator.")
        return ImpostazioniPlugin.objects.filter(tipo=tipo).first() or ImpostazioniPlugin.objects.create(tipo=tipo)

    def _risposta(self, impostazioni):
        dati = ImpostazioniPluginSerializer(impostazioni).data
        dati["aspetto"] = aspetto_pulito(impostazioni.aspetto)
        dati["campi"] = [{"chiave": c, "obbligatoria": o, "etichetta": e} for c, o, e in q.CAMPI[impostazioni.tipo]]
        dati["uscite"] = q.USCITE[impostazioni.tipo]
        dati["query_generata"] = q.query_di(impostazioni) if not impostazioni.query else None
        dati["preimpostazioni"] = [{"chiave": k, "nome": v[0]} for k, v in q.PREIMPOSTAZIONI[impostazioni.tipo].items()]
        dati["prezzo_attivo"] = bool(
            abilitato("prezzo") and ImpostazioniPlugin.objects.filter(tipo="prezzo", attivo=True).exists()
        )
        negozi = []
        fonti = {f.sede_id: f for f in FontePlugin.objects.filter(tipo=impostazioni.tipo)}
        for sede in Sede.objects.order_by("nome"):
            master = Monitor.objects.filter(sede=sede, totem_master=True).first()
            stato = ((master.info_dispositivo or {}).get("plugin") or {}).get(impostazioni.tipo) if master else None
            fonte = fonti.get(sede.id)
            negozi.append({
                "sede": str(sede.id), "nome": sede.nome, "indirizzo_totem": sede.indirizzo_totem,
                "master": master.nome if master else None, "master_online": bool(master and master.online),
                "fonte": FontePluginSerializer(fonte).data if fonte else None, "stato": stato,
            })
        dati["negozi"] = negozi
        return dati

    def get(self, request, tipo):
        return Response(self._risposta(self._impostazioni(tipo)))

    def put(self, request, tipo):
        impostazioni = self._impostazioni(tipo)
        dati = ImpostazioniPluginSerializer(impostazioni, data=request.data, partial=True)
        dati.is_valid(raise_exception=True)
        salvate = dati.save()
        registra(request.user, "plugin_modificato", None, plugin=tipo, attivo=salvate.attivo)
        return Response(self._risposta(salvate))


class FontiPluginViewSet(ViewSetCliente):
    """Il file SQLite di ogni negozio per un plugin (?tipo=)."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = GESTIONE
    serializer_class = FontePluginSerializer

    def get_queryset(self):
        fonti = FontePlugin.objects.select_related("sede")
        tipo = self.request.query_params.get("tipo")
        return fonti.filter(tipo=tipo) if tipo else fonti

    def _verifica(self, tipo):
        if not abilitato(tipo):
            raise exceptions.PermissionDenied("Plugin non abilitato per questa azienda.")

    def perform_create(self, serializer):
        self._verifica(serializer.validated_data["tipo"])
        registra(self.request.user, "fonte_plugin_creata", serializer.save())

    def perform_update(self, serializer):
        self._verifica(serializer.validated_data.get("tipo", serializer.instance.tipo))
        registra(self.request.user, "fonte_plugin_modificata", serializer.save())

    def perform_destroy(self, fonte):
        registra(self.request.user, "fonte_plugin_eliminata", fonte)
        fonte.delete()

    @action(detail=True, methods=["post"])
    def prova(self, request, pk=None):
        """«Prova accesso»: il Totem Master del negozio prova cartella condivisa e file (entro poco)."""
        from django.utils import timezone

        fonte = self.get_object()
        self._verifica(fonte.tipo)
        fonte.prova_richiesta = timezone.now()
        fonte.prova_esito = {}
        fonte.save(update_fields=["prova_richiesta", "prova_esito"])
        return Response(self.get_serializer(fonte).data)

    @action(detail=True, methods=["post"])
    def aggiorna(self, request, pk=None):
        """«Aggiorna adesso»: il Totem Master ricopia il file appena riceve la configurazione."""
        from django.utils import timezone

        fonte = self.get_object()
        self._verifica(fonte.tipo)
        fonte.richiesta_copia = timezone.now()
        fonte.save(update_fields=["richiesta_copia"])
        registra(request.user, "fonte_plugin_aggiorna", fonte)
        return Response(self.get_serializer(fonte).data)


# --- Filtro contenuti ----------------------------------------------------------------------------


class FiltroContenutiSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiltroContenuti
        fields = ["immagini", "severita_immagini", "video", "severita_video", "dirette", "severita_dirette", "modificato"]
        read_only_fields = ["modificato"]


class FiltroContenutiView(VistaConContesto, APIView):
    """GET/PUT il plugin «Filtro contenuti» (chi gestisce l'azienda); POST prova un file o una
    diretta senza salvare nulla: dice cosa farebbe il filtro, con i punteggi."""

    ruoli_lettura = GESTIONE
    ruoli_scrittura = GESTIONE

    def _risposta(self, impostazioni):
        from contenuti.models import Contenuto, Controllo, Tipo
        from audit.models import EventoAudit

        dati = FiltroContenutiSerializer(impostazioni).data
        dati["disponibile"] = filtro.disponibile()
        dati["severita"] = {
            nome: {"soglia": round(v["soglia"] * 100), "ogni_secondi": v["ogni_secondi"],
                   "fotogrammi_diretta": v["fotogrammi_diretta"], "ricontrollo": v["ricontrollo"]}
            for nome, v in filtro.SEVERITA.items()
        }
        dirette = Contenuto.objects.filter(tipo=Tipo.DIRETTA).exclude(controllo="").order_by("nome")
        dati["dirette_controllate"] = [
            {"id": str(c.id), "nome": c.nome, "url": c.url, "controllo": c.controllo,
             "stato": Controllo(c.controllo).label, "controllo_il": c.controllo_il, "esito": c.controllo_esito}
            for c in dirette
        ]
        rifiuti = EventoAudit.objects.filter(azione__in=["contenuto_rifiutato_filtro", "diretta_bloccata_filtro"]).order_by("-quando")[:30]
        dati["rifiuti"] = [
            {"quando": e.quando, "utente": e.utente, "azione": e.azione, "nome": e.dettagli.get("nome", ""),
             "tipo": e.dettagli.get("tipo", "diretta"), "punteggio": e.dettagli.get("punteggio")}
            for e in rifiuti
        ]
        return dati

    def get(self, request):
        return Response(self._risposta(FiltroContenuti.objects.first() or FiltroContenuti()))

    def put(self, request):
        impostazioni = FiltroContenuti.objects.first()
        dati = FiltroContenutiSerializer(impostazioni, data=request.data, partial=True)
        dati.is_valid(raise_exception=True)
        salvate = dati.save()
        registra(request.user, "filtro_contenuti_modificato", None, **{k: v for k, v in dati.validated_data.items()})
        return Response(self._risposta(salvate))

    def post(self, request):
        """Prova: un file (immagine o video) oppure l'indirizzo di una diretta, con una severità."""
        from contenuti.file import riconosci

        severita = request.data.get("severita") or "media"
        if severita not in filtro.SEVERITA:
            raise exceptions.ValidationError({"severita": "Bassa, media o alta."})
        if not filtro.disponibile():
            raise exceptions.ValidationError("Il modello del filtro non si avvia su questo server.")
        file = request.FILES.get("file")
        try:
            if file is not None:
                formato = riconosci(file)
                if formato is None or formato[0] not in ("immagine", "video"):
                    raise exceptions.ValidationError({"file": "Scegli un'immagine o un video (JPEG, PNG, GIF, WebP, MP4, MOV, WebM)."})
                tipo = formato[0]
                esito = (filtro.controlla_immagine if tipo == "immagine" else filtro.controlla_video)(file, severita)
            else:
                url = str(request.data.get("url") or "").strip()
                if not url.lower().startswith(("http://", "https://")):
                    raise exceptions.ValidationError({"url": "Indica un file oppure l'indirizzo di una diretta."})
                tipo = "diretta"
                esito = filtro.controlla_diretta(url, severita)
        except filtro.DirettaIrraggiungibile as errore:
            raise exceptions.ValidationError({"url": f"Diretta non raggiungibile dal server: {errore}"})
        except exceptions.ValidationError:
            raise
        except Exception:
            raise exceptions.ValidationError({"file": "Il filtro non riesce a leggere questo file."})
        return Response({"tipo": tipo, "severita": severita, **esito.come_dati()})
