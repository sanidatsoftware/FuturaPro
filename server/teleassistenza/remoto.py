"""API del «Controllo Remoto» (solo SystemAdministrator e Tecnici; vedi mesh.py).

- GET  /api/remoto/                      inventario dei PC con il monitor e l'azienda abbinati
- GET  /api/remoto/dispositivi/?nodo=    l'hardware di un PC
- GET  /api/remoto/sessioni/             il registro delle sessioni
- POST /api/remoto/sessioni/             apre lo schermo di un PC: motivo e, ogni 12 ore, il codice
                                         della verifica in due passaggi; risponde con l'indirizzo
- POST /api/remoto/sessioni/{id}/chiudi/
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
from utenti import doppio

from . import mesh
from .models import ConfigurazioneRemota, SessioneRemota

# Dopo il codice della verifica in due passaggi, per quanto non lo si richiede in questo browser.
VALIDITA_VERIFICA = 12 * 3600


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
        for d in dispositivi:
            d["monitor"] = abbinati.get(d["tag"]) if d["tag"] else None
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
        if not nodo.startswith("node/"):
            raise exceptions.ValidationError({"nodo": "PC non valido."})
        if len(motivo) < 5:
            raise exceptions.ValidationError({"motivo": "Scrivi il motivo del collegamento (resta nel registro)."})
        if not utente.doppio_attivo:
            raise exceptions.PermissionDenied(
                "Per il Controllo Remoto serve la verifica in due passaggi: attivala nel tuo Profilo."
            )
        verificato = request.session.get("doppio_remoto", 0)
        if time.time() - verificato > VALIDITA_VERIFICA:
            if not doppio.verifica_utente(utente, request.data.get("codice")):
                raise exceptions.ValidationError({"codice": "Serve il codice dell'app di autenticazione (6 cifre)."})
            request.session["doppio_remoto"] = int(time.time())
        try:
            with mesh.Comando() as comando:
                gruppo = mesh.gruppo(comando)
                pc = next((d for d in mesh.dispositivi(comando, gruppo) if d["id"] == nodo), None)
                if pc is None:
                    raise exceptions.NotFound("PC non trovato nel Controllo Remoto.")
                account = mesh.assicura_account(comando, utente, gruppo)
        except (mesh.MeshErrore, mesh.MeshNonConfigurato) as errore:
            _errore_mesh(errore)
        abbinato = _monitor_per_tag().get(pc["tag"]) if pc["tag"] else None
        sessione = SessioneRemota.objects.create(
            nodo=nodo, nome_pc=pc["nome"], tecnico_id=utente.id, tecnico=utente.username, motivo=motivo[:300],
            indirizzo_ip=request.META.get("REMOTE_ADDR"),
            monitor_id=abbinato["id"] if abbinato else None, nome_monitor=abbinato["nome"] if abbinato else "",
            cliente_id=abbinato["cliente_id"] if abbinato else None, nome_cliente=abbinato["cliente"] if abbinato else "",
        )
        dettagli = {"pc": pc["nome"], "monitor": sessione.nome_monitor, "motivo": sessione.motivo, "sessione": str(sessione.id)}
        with contesto_piattaforma():
            registra(utente, "controllo_remoto_aperto", sessione, cliente=sessione.nome_cliente, **dettagli)
        if sessione.cliente_id:
            # Nel registro dell'azienda resta che c'è stato un intervento (non può aprirne).
            with contesto_cliente(sessione.cliente_id):
                registra(utente, "controllo_remoto_aperto", sessione, **dettagli)
        return Response({
            "sessione": SessioneRemotaSerializer(sessione).data,
            "indirizzo": mesh.indirizzo_schermo(account, nodo),
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
