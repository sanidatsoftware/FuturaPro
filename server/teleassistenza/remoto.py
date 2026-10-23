"""API del «Controllo Remoto» (solo SystemAdministrator e Tecnici; vedi mesh.py).

- GET  /api/remoto/                      inventario dei PC con il monitor e l'azienda abbinati
- GET  /api/remoto/dispositivi/?nodo=    l'hardware di un PC
- GET  /api/remoto/sessioni/             il registro delle sessioni
- POST /api/remoto/sessioni/             apre lo schermo di un PC: motivo e, ogni 12 ore, utente e
                                         password del Controllo Remoto dell'azienda del PC; risponde
                                         con l'indirizzo
- POST /api/remoto/sessioni/{id}/chiudi/
- POST /api/remoto/player/               mette in pausa o fa ripartire il player di un PC
- GET/POST /api/remoto/credenziali/      utente e password del Controllo Remoto di ogni azienda
- GET  /api/player/agente-remoto/?tag=   il programma dell'agente per lo script di installazione
"""

import time
from datetime import timedelta

from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import exceptions, serializers
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from audit.models import registra
from core.api import TELEASSISTENZA
from core.contesto import contesto_cliente, contesto_piattaforma
from dispositivi.models import Monitor
from clienti.models import Cliente

from . import mesh
from .models import ConfigurazioneRemota, CredenzialeRemota, SessioneRemota

# Dopo utente e password di un'azienda, per quanto non li si richiede in questo browser.
VALIDITA_VERIFICA = 12 * 3600
PASSWORD_MINIMA = 8


class SoloPiattaforma:
    """Il Controllo Remoto non esiste per le aziende: né lettura né scrittura."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_authenticated or request.user.ruolo not in TELEASSISTENZA:
            raise exceptions.PermissionDenied("Il Controllo Remoto è riservato alla piattaforma.")


def _monitor_per_tag() -> dict:
    """Tag dell'agente → monitor (con azienda e negozio), tra tutte le aziende."""
    with contesto_piattaforma():
        monitor = Monitor.objects.exclude(impronta_postazione="").select_related("sede", "cliente")
        return {
            mesh.tag_postazione(m.impronta_postazione): {
                "id": str(m.id), "nome": m.nome, "cliente_id": str(m.cliente_id), "cliente": m.cliente.nome,
                "sede": m.sede.nome if m.sede_id else "", "in_linea": m.online,
            }
            for m in monitor
        }


def _chiudi_scadute():
    """Le sessioni aperte da più della durata massima si chiudono da sole nel registro."""
    limite = timezone.now() - timedelta(minutes=ConfigurazioneRemota.attuale().durata_massima)
    SessioneRemota.objects.filter(chiusa__isnull=True, iniziata__lt=limite).update(chiusa=timezone.now(), chiusa_da="scaduta")


def _errore_mesh(errore):
    raise exceptions.APIException(str(errore)) if not isinstance(errore, mesh.MeshNonConfigurato) else exceptions.ValidationError(str(errore))


def _chiave_verifica(cliente_id) -> str:
    return f"remoto_{cliente_id}"


def _gia_verificato(request, credenziale) -> bool:
    """Utente e password di quell'azienda già scritti in questo browser nelle ultime 12 ore (e non
    cambiati da allora)."""
    quando, versione = (request.session.get(_chiave_verifica(credenziale.cliente_id)) or [0, ""])[:2]
    return time.time() - quando < VALIDITA_VERIFICA and versione == credenziale.modificata.isoformat()


def verifica_credenziali(request, cliente_id) -> None:
    """Per i PC di un'azienda servono utente e password del suo Controllo Remoto. Un PC non ancora
    abbinato a un monitor (appena installato) non ha azienda: basta l'accesso alla piattaforma."""
    if not cliente_id:
        return
    credenziale = CredenzialeRemota.objects.filter(cliente_id=cliente_id).first()
    if credenziale is None:
        raise exceptions.ValidationError({"credenziali": (
            "Per questa azienda non sono ancora impostati utente e password del Controllo Remoto: "
            "li imposta il SystemAdministrator in Controllo Remoto → Credenziali aziende."
        )})
    if _gia_verificato(request, credenziale):
        return
    if not credenziale.corrisponde(str(request.data.get("utente") or ""), str(request.data.get("password") or "")):
        raise exceptions.ValidationError({"credenziali": "Utente o password del Controllo Remoto di questa azienda non corrispondono."})
    request.session[_chiave_verifica(cliente_id)] = [int(time.time()), credenziale.modificata.isoformat()]


def _pc_e_monitor(comando, nodo: str):
    """Il PC (dall'inventario di MeshCentral) e il monitor FuturaPro abbinato, se c'è."""
    pc = next((d for d in mesh.dispositivi(comando, mesh.gruppo(comando)) if d["id"] == nodo), None)
    if pc is None:
        raise exceptions.NotFound("PC non trovato nel Controllo Remoto.")
    return pc, (_monitor_per_tag().get(pc["tag"]) if pc["tag"] else None)


class SessioneRemotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessioneRemota
        fields = [
            "id", "nodo", "nome_pc", "monitor_id", "nome_monitor", "cliente_id", "nome_cliente", "tecnico", "motivo",
            "indirizzo_ip", "iniziata", "chiusa", "chiusa_da",
        ]


class InventarioView(SoloPiattaforma, APIView):
    def get(self, request):
        _chiudi_scadute()
        aperte = SessioneRemotaSerializer(SessioneRemota.objects.filter(chiusa__isnull=True), many=True).data
        risposta = {"configurato": mesh.configurato(), "dispositivi": [], "sessioni_aperte": aperte, "errore": None}
        if not risposta["configurato"]:
            return Response(risposta)
        try:
            with mesh.Comando() as comando:
                gruppo = mesh.gruppo(comando)
                dispositivi = mesh.dispositivi(comando, gruppo)
                if request.user.ruolo == "admin_assoluto":
                    # La console completa di MeshCentral, per il SystemAdministrator.
                    risposta["console"] = mesh.indirizzo_console(mesh.assicura_account(comando, request.user, gruppo))
        except mesh.MeshErrore as errore:
            risposta["errore"] = str(errore)
            return Response(risposta)
        abbinati = _monitor_per_tag()
        credenziali = {str(c.cliente_id): c for c in CredenzialeRemota.objects.all()}
        for d in dispositivi:
            d["monitor"] = abbinati.get(d["tag"]) if d["tag"] else None
            cliente = (d["monitor"] or {}).get("cliente_id")
            # Cosa chiedere al tecnico per questo PC: «credenziali» (utente e password
            # dell'azienda), «mancanti» (l'azienda non le ha ancora) o niente.
            credenziale = credenziali.get(cliente) if cliente else None
            if not cliente:
                d["accesso"] = ""
            elif credenziale is None:
                d["accesso"] = "mancanti"
            else:
                d["accesso"] = "" if _gia_verificato(request, credenziale) else "credenziali"
        risposta["dispositivi"] = sorted(dispositivi, key=lambda d: (not d["in_linea"], (d["monitor"] or {}).get("cliente", "~"), d["nome"].lower()))
        return Response(risposta)


class DispositivoView(SoloPiattaforma, APIView):
    def get(self, request):
        nodo = str(request.query_params.get("nodo") or "")
        if not nodo.startswith("node/"):
            raise exceptions.ValidationError({"nodo": "PC non valido."})
        try:
            with mesh.Comando() as comando:
                return Response(mesh.informazioni(comando, nodo))
        except (mesh.MeshErrore, mesh.MeshNonConfigurato) as errore:
            _errore_mesh(errore)


class LimiteRemoto(UserRateThrottle):
    scope = "remoto"


class SessioniRemoteView(SoloPiattaforma, APIView):
    def get_throttles(self):
        return [LimiteRemoto()] if self.request.method == "POST" else []

    def get(self, request):
        _chiudi_scadute()
        sessioni = SessioneRemota.objects.all()
        if request.query_params.get("nodo"):
            sessioni = sessioni.filter(nodo=request.query_params["nodo"])
        return Response(SessioneRemotaSerializer(sessioni[:300], many=True).data)

    def post(self, request):
        utente = request.user
        nodo = str(request.data.get("nodo") or "")
        motivo = str(request.data.get("motivo") or "").strip()
        vista = str(request.data.get("vista") or "schermo")
        if not nodo.startswith("node/"):
            raise exceptions.ValidationError({"nodo": "PC non valido."})
        if vista not in mesh.VISTE:
            raise exceptions.ValidationError({"vista": "Schermo o file."})
        if len(motivo) < 5:
            raise exceptions.ValidationError({"motivo": "Scrivi il motivo del collegamento (resta nel registro)."})
        try:
            with mesh.Comando() as comando:
                pc, abbinato = _pc_e_monitor(comando, nodo)
                verifica_credenziali(request, abbinato["cliente_id"] if abbinato else None)
                account = mesh.assicura_account(comando, utente, mesh.gruppo(comando))
        except (mesh.MeshErrore, mesh.MeshNonConfigurato) as errore:
            _errore_mesh(errore)
        sessione = SessioneRemota.objects.create(
            nodo=nodo, nome_pc=pc["nome"], tecnico_id=utente.id, tecnico=utente.username, motivo=motivo[:300],
            indirizzo_ip=request.META.get("REMOTE_ADDR"),
            monitor_id=abbinato["id"] if abbinato else None, nome_monitor=abbinato["nome"] if abbinato else "",
            cliente_id=abbinato["cliente_id"] if abbinato else None, nome_cliente=abbinato["cliente"] if abbinato else "",
        )
        dettagli = {"pc": pc["nome"], "monitor": sessione.nome_monitor, "motivo": sessione.motivo, "sessione": str(sessione.id), "vista": vista}
        with contesto_piattaforma():
            registra(utente, "controllo_remoto_aperto", sessione, cliente=sessione.nome_cliente, **dettagli)
        if sessione.cliente_id:
            # Nel registro dell'azienda resta che c'è stato un intervento (non può aprirne).
            with contesto_cliente(sessione.cliente_id):
                registra(utente, "controllo_remoto_aperto", sessione, **dettagli)
        return Response({
            "sessione": SessioneRemotaSerializer(sessione).data,
            "indirizzo": mesh.indirizzo_schermo(account, nodo, vista),
        }, status=201)


class ChiudiSessioneView(SoloPiattaforma, APIView):
    def post(self, request, pk):
        sessione = SessioneRemota.objects.filter(pk=pk).first()
        if sessione is None:
            raise exceptions.NotFound()
        if sessione.chiusa:
            raise exceptions.ValidationError("La sessione è già chiusa.")
        sessione.chiusa, sessione.chiusa_da = timezone.now(), request.user.username
        sessione.save(update_fields=["chiusa", "chiusa_da"])
        durata = int((sessione.chiusa - sessione.iniziata).total_seconds() // 60)
        with contesto_piattaforma():
            registra(request.user, "controllo_remoto_chiuso", sessione, pc=sessione.nome_pc, minuti=durata)
        if sessione.cliente_id:
            with contesto_cliente(sessione.cliente_id):
                registra(request.user, "controllo_remoto_chiuso", sessione, pc=sessione.nome_pc, minuti=durata)
        return Response(SessioneRemotaSerializer(sessione).data)


class PlayerRemotoView(SoloPiattaforma, APIView):
    """Mette in pausa il player di un PC (per lavorarci dallo schermo remoto: il guardiano non lo
    riapre più) o lo fa ripartire. Stesse credenziali dell'azienda del collegamento."""

    throttle_classes = [LimiteRemoto]
    AZIONI = {"pausa": "player_in_pausa", "riavvia": "player_riavviato"}

    def post(self, request):
        nodo = str(request.data.get("nodo") or "")
        azione = str(request.data.get("azione") or "")
        if not nodo.startswith("node/") or azione not in self.AZIONI:
            raise exceptions.ValidationError("PC o azione non validi.")
        try:
            with mesh.Comando() as comando:
                pc, abbinato = _pc_e_monitor(comando, nodo)
                verifica_credenziali(request, abbinato["cliente_id"] if abbinato else None)
                if not pc["in_linea"]:
                    raise exceptions.ValidationError("Il PC non è in linea.")
                if "windows" not in (pc["sistema"] or "").lower():
                    raise exceptions.ValidationError("Pausa e riavvio del player ci sono solo per i PC Windows.")
                mesh.comanda_player(comando, nodo, azione)
        except (mesh.MeshErrore, mesh.MeshNonConfigurato) as errore:
            _errore_mesh(errore)
        dettagli = {"pc": pc["nome"], "monitor": abbinato["nome"] if abbinato else ""}
        with contesto_piattaforma():
            registra(request.user, self.AZIONI[azione], None, cliente=abbinato["cliente"] if abbinato else "", **dettagli)
        if abbinato:
            with contesto_cliente(abbinato["cliente_id"]):
                registra(request.user, self.AZIONI[azione], None, **dettagli)
        return Response({"ok": True})


class CredenzialiView(SoloPiattaforma, APIView):
    """Utente e password del Controllo Remoto di ogni azienda. Li vedono (senza password) i tecnici,
    li imposta solo il SystemAdministrator."""

    def get(self, request):
        credenziali = {c.cliente_id: c for c in CredenzialeRemota.objects.all()}
        with contesto_piattaforma():
            clienti = list(Cliente.objects.all())
        return Response([
            {
                "cliente": str(c.id), "nome": c.nome, "attivo": c.attivo,
                "utente": credenziali[c.id].utente if c.id in credenziali else "",
                "modificata": credenziali[c.id].modificata if c.id in credenziali else None,
                "modificata_da": credenziali[c.id].modificata_da if c.id in credenziali else "",
            }
            for c in clienti
        ])

    def post(self, request):
        if request.user.ruolo != "admin_assoluto":
            raise exceptions.PermissionDenied("Utente e password del Controllo Remoto li imposta il SystemAdministrator.")
        with contesto_piattaforma():
            cliente = Cliente.objects.filter(pk=request.data.get("cliente")).first() if _uuid(request.data.get("cliente")) else None
        if cliente is None:
            raise exceptions.ValidationError({"cliente": "Azienda non trovata."})
        utente = str(request.data.get("utente") or "").strip()
        password = str(request.data.get("password") or "")
        if not utente or len(utente) > 150:
            raise exceptions.ValidationError({"utente": "Scrivi il nome utente."})
        if len(password) < PASSWORD_MINIMA:
            raise exceptions.ValidationError({"password": f"La password deve avere almeno {PASSWORD_MINIMA} caratteri."})
        credenziale = CredenzialeRemota.objects.filter(cliente=cliente).first() or CredenzialeRemota(cliente=cliente)
        credenziale.utente, credenziale.modificata_da = utente, request.user.username
        credenziale.imposta_password(password)
        credenziale.save()
        with contesto_piattaforma():
            registra(request.user, "credenziali_remote_impostate", None, cliente=cliente.nome, utente_remoto=utente)
        return Response({"cliente": str(cliente.id), "utente": utente, "modificata": credenziale.modificata})


def _uuid(valore) -> bool:
    import uuid

    try:
        uuid.UUID(str(valore))
        return True
    except ValueError:
        return False


def agente_remoto(request):
    """Lo script di installazione di Windows scarica da qui l'agente, legato alla sua postazione
    (tag: l'inizio dell'impronta del codice della postazione). Senza Controllo Remoto: 404."""
    from django.http import Http404

    tag = str(request.GET.get("tag") or "").lower()
    if not mesh.configurato() or len(tag) != mesh.LUNGHEZZA_TAG or any(c not in "0123456789abcdef" for c in tag):
        raise Http404()
    gruppo = ConfigurazioneRemota.attuale().gruppo
    if not gruppo:
        try:
            with mesh.Comando() as comando:
                gruppo = mesh.gruppo(comando)
        except mesh.MeshErrore:
            raise Http404()
    return HttpResponseRedirect(mesh.indirizzo_agente(gruppo, tag))
