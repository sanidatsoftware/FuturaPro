import csv
import io
from datetime import date, datetime, time, timedelta

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import exceptions, serializers, viewsets

from core.api import GESTIONE, SOLO_ASSOLUTO, VistaConContesto

from .models import EventoAudit


class EventoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.SerializerMethodField()

    class Meta:
        model = EventoAudit
        fields = [
            "id", "quando", "utente", "ruolo", "per_conto_piattaforma",
            "azione", "oggetto_tipo", "oggetto_id", "dettagli", "cliente", "cliente_nome",
        ]

    def get_cliente_nome(self, evento):
        return (self.context.get("clienti") or {}).get(evento.cliente_id, "")


class FiltriRegistro:
    """Filtri comuni: ?dal=&al= (giorni), ?utente=, ?azione= (anche parziale), ?cerca= (nei
    dettagli), ?formato=csv per scaricarlo."""

    def get_queryset(self):
        eventi = EventoAudit.objects.all()
        p = self.request.query_params
        try:
            if p.get("dal"):
                eventi = eventi.filter(quando__gte=timezone.make_aware(datetime.combine(date.fromisoformat(p["dal"]), time.min)))
            if p.get("al"):
                eventi = eventi.filter(quando__lt=timezone.make_aware(datetime.combine(date.fromisoformat(p["al"]) + timedelta(days=1), time.min)))
        except ValueError:
            raise exceptions.ValidationError("Date non valide.")
        if p.get("utente"):
            eventi = eventi.filter(utente__iexact=p["utente"])
        if p.get("azione"):
            eventi = eventi.filter(azione__icontains=p["azione"])
        if p.get("cerca"):
            eventi = eventi.filter(dettagli__icontains=p["cerca"]) | eventi.filter(azione__icontains=p["cerca"])
        return eventi.order_by("-quando")

    def get_serializer_context(self):
        contesto = super().get_serializer_context()
        if getattr(self, "ambito", "") == "piattaforma":
            from clienti.models import Cliente

            contesto["clienti"] = dict(Cliente.objects.values_list("id", "nome"))
        return contesto

    def list(self, request, *args, **kwargs):
        if request.query_params.get("formato") != "csv":
            risposta = super().list(request, *args, **kwargs)
            if isinstance(risposta.data, dict):
                risposta.data["utenti"] = sorted(set(self.get_queryset().values_list("utente", flat=True)) - {""})[:200]
            return risposta
        uscita = io.StringIO()
        scrittore = csv.writer(uscita, delimiter=";")
        scrittore.writerow(["Quando", "Utente", "Ruolo", "Per conto della piattaforma", "Azione", "Oggetto", "Dettagli"])
        for e in self.get_queryset()[:20000]:
            scrittore.writerow([
                timezone.localtime(e.quando).strftime("%d/%m/%Y %H:%M:%S"), e.utente, e.ruolo,
                "sì" if e.per_conto_piattaforma else "", e.azione, e.oggetto_tipo, e.dettagli or "",
            ])
        risposta = HttpResponse("﻿" + uscita.getvalue(), content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = 'attachment; filename="registro-operazioni.csv"'
        return risposta


class AuditClienteViewSet(FiltriRegistro, VistaConContesto, viewsets.ReadOnlyModelViewSet):
    """Il registro del cliente, comprese le azioni fatte dalla piattaforma per suo conto."""

    ruoli_lettura = GESTIONE
    serializer_class = EventoSerializer


class AuditPiattaformaViewSet(FiltriRegistro, VistaConContesto, viewsets.ReadOnlyModelViewSet):
    """Il registro di tutta la piattaforma (tutte le aziende): solo il SystemAdministrator."""

    ambito = "piattaforma"
    ruoli_lettura = SOLO_ASSOLUTO
    serializer_class = EventoSerializer
