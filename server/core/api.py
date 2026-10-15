"""Base comune delle API: chi può fare cosa, e per quale cliente.

Ogni vista dichiara il proprio ``ambito`` e i ruoli ammessi:

- ``ambito = "piattaforma"``: dati di tutta la piattaforma, solo ruoli di piattaforma;
- ``ambito = "cliente"``: dati di un cliente. Gli utenti di un cliente lavorano
  sempre e soltanto sul proprio; gli utenti di piattaforma scelgono il cliente
  con l'intestazione ``X-Cliente``, che il pannello imposta dal selettore
  dell'azienda.
"""

from uuid import UUID

from rest_framework import permissions, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from clienti.models import Cliente
from utenti.models import Ruolo

from . import contesto

INTESTAZIONE_CLIENTE = "HTTP_X_CLIENTE"

TUTTI = frozenset(Ruolo)
GESTIONE = frozenset({Ruolo.ADMIN_ASSOLUTO, Ruolo.ADMIN_CLIENTE})
SOLO_ASSOLUTO = frozenset({Ruolo.ADMIN_ASSOLUTO})
TELEASSISTENZA = frozenset({Ruolo.ADMIN_ASSOLUTO, Ruolo.TECNICO})
# Chi lavora sui contenuti: tutti tranne il tecnico, che li può solo vedere.
CONTENUTI = frozenset({Ruolo.ADMIN_ASSOLUTO, Ruolo.ADMIN_CLIENTE, Ruolo.USER_CLIENTE})


def _cliente_scelto(request) -> UUID:
    # Dall'intestazione (pannello) o dall'indirizzo (API navigabile nel browser).
    valore = request.META.get(INTESTAZIONE_CLIENTE) or request.GET.get("cliente")
    if not valore:
        raise ValidationError({"cliente": "Seleziona un cliente (intestazione X-Cliente)."})
    try:
        cliente_id = UUID(valore)
    except ValueError:
        raise NotFound("Cliente inesistente.")
    with contesto.contesto_piattaforma():
        if not Cliente.objects.filter(id=cliente_id).exists():
            raise NotFound("Cliente inesistente.")
    return cliente_id


class PermessoRuolo(permissions.BasePermission):
    """Legge ``ruoli_lettura`` e ``ruoli_scrittura`` dalla vista."""

    def has_permission(self, request, view):
        utente = request.user
        if not utente or not utente.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return utente.ruolo in view.ruoli_lettura
        return utente.ruolo in view.ruoli_scrittura


class VistaConContesto:
    ambito = "cliente"
    ruoli_lettura = TUTTI
    ruoli_scrittura = GESTIONE
    permission_classes = [PermessoRuolo]

    def perform_authentication(self, request):
        super().perform_authentication(request)
        contesto.imposta(self._contesto_per(request))

    def _contesto_per(self, request):
        utente = request.user
        if not utente or not utente.is_authenticated:
            return None
        if self.ambito == "piattaforma":
            if not utente.di_piattaforma:
                raise PermissionDenied()
            return contesto.Contesto(cliente_id=None, piattaforma=True)
        if utente.di_piattaforma:
            return contesto.Contesto(cliente_id=_cliente_scelto(request))
        # Un utente di un cliente non sceglie: X-Cliente viene ignorata.
        with contesto.contesto_cliente(utente.cliente_id):
            if not Cliente.objects.filter(id=utente.cliente_id, attivo=True).exists():
                raise PermissionDenied("Il cliente è disattivato.")
        return contesto.Contesto(cliente_id=utente.cliente_id)


class ViewSetCliente(VistaConContesto, viewsets.ModelViewSet):
    pass


class RiferimentoCliente(serializers.PrimaryKeyRelatedField):
    """Riferimento a un oggetto del cliente corrente: quelli degli altri risultano inesistenti.

    Il queryset si costruisce a ogni validazione, mai all'import, perché
    senza contesto il gestore si rifiuta di rispondere.
    """

    def __init__(self, modello, **kwargs):
        self.modello = modello
        if not kwargs.get("read_only"):
            kwargs["queryset"] = modello._base_manager.none()
        super().__init__(**kwargs)

    def get_queryset(self):
        return self.modello.objects.all()


def sedi_visibili(utente):
    """Le sedi a cui è limitato un User, oppure None se vede tutto il cliente."""
    if utente.ruolo != Ruolo.USER_CLIENTE:
        return None
    sedi = list(utente.sedi_consentite.values_list("id", flat=True))
    return sedi or None
