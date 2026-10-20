import json
import re
from collections import OrderedDict
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .models import Condivisione, DocumentoSysSpy, FileSysSpy, Nota, Pianificazione, RegolaDocumento
from .services.regole import obbligatoria
from .services import importazione
from .services.accesso import (
    can_access_primanota,
    can_manage_primanota,
    etichetta_negozio,
    get_current_user_from_request,
    get_user_store_id,
    is_office_user,
    is_store_user,
    negozi_attivi_ordinati,
    negozio,
    nome_utente,
)
from .services.baserow_primanota import (
    TIPI_DOCUMENTO,
    TIPI_VALIDI,
    TRANSAZIONI_ABORTITE,
    RESI,
    CHIUSURA_FISCALE,
    CHIUSURA_POS,
    VERSAMENTO_CONTANTE,
    aggiorna_lavorato,
    crea_scansione,
    elenco_scansioni,
    elimina_scansione,
    leggi_scansione,
)
from .services.monitor import build_monitor
from scansioni.services.baserow_scansioni import LOCAL_TZ

# La ricerca nel testo legge i file dal disco: si limita il numero di giornate.
MAX_GIORNI_RICERCA = 62


def _data(valore, predefinita=None):
    try:
        return date.fromisoformat(str(valore or "")).isoformat()
    except ValueError:
        return predefinita


def _accesso(solo_ufficio=False, solo_gestione=False):
    def decoratore(view):
        @wraps(view)
        def interna(request, *args, **kwargs):
            user = get_current_user_from_request(request)
            if not user:
                if request.method == "POST" and request.headers.get("Content-Type", "").startswith("application/json"):
                    return JsonResponse({"error": "Sessione scaduta"}, status=403)
                return redirect("/login/")
            if not can_access_primanota(user):
                return HttpResponseForbidden("Non sei autorizzato alla Prima Nota.")
            if solo_ufficio and not is_office_user(user):
                return redirect("/primanota/upload/")
            if solo_gestione and not can_manage_primanota(user):
                return HttpResponseForbidden("Funzione riservata ad Amministratore e Direttore.")
            request.utente_primanota = user
            # Il portale è configurato in UTC: date e orari della Prima Nota sono quelli italiani.
            timezone.activate(LOCAL_TZ)
            return view(request, *args, **kwargs)
        return interna
    return decoratore


def _contesto(request, **altro):
    user = request.utente_primanota
    return {"utente": user, "puo_gestire": can_manage_primanota(user), "tipi_documento": TIPI_DOCUMENTO, **altro}


@_accesso()
def home(request):
    if is_store_user(request.utente_primanota):
        return redirect("/primanota/upload/")
    return redirect("/primanota/admin/")


@_accesso()
def upload(request):
    user = request.utente_primanota
    if not is_store_user(user):
        return redirect("/primanota/admin/")
    negozio_id = get_user_store_id(user)
    error = None

    if request.method == "POST" and request.POST.get("azione") == "nota":
        giorno = _data(request.POST.get("data"))
        tipo = request.POST.get("tipo")
        testo = request.POST.get("testo", "").strip()
        if not giorno or tipo not in dict(Nota.TIPI) or not testo:
            error = "Compila data, tipo e testo della segnalazione."
        else:
            Nota.objects.create(negozio_id=negozio_id, data=giorno, tipo=tipo, testo=testo, creata_da=nome_utente(user))
            return redirect("/primanota/upload/?nota=1")
    elif request.method == "POST":
        giorno = _data(request.POST.get("data_documento"))
        tipo = request.POST.get("tipo_documento", "").strip()
        documento = request.FILES.get("documento")
        cassa = request.POST.get("cassa", "").strip()
        if not giorno or tipo not in TIPI_VALIDI or not documento:
            error = "Compila Data, Tipo Documento e allega il file."
        elif cassa and not cassa.isdigit():
            error = "La cassa deve essere un numero."
        else:
            try:
                risultato = crea_scansione(user, negozio_id, giorno, tipo, documento,
                                           cassa=int(cassa) if cassa else None,
                                           note=request.POST.get("note", "").strip())
            except RuntimeError as exc:
                risultato = {"error": str(exc)}
            if "error" in risultato:
                error = str(risultato["error"])
            else:
                # Post/Redirect/Get come in Scansioni PV: niente doppi invii.
                return redirect("/primanota/upload/?uploaded=1")

    try:
        scansioni = elenco_scansioni(negozio_id=negozio_id, max_risultati=50)
    except RuntimeError as exc:
        scansioni, error = [], error or str(exc)
    message = None
    if request.GET.get("uploaded") == "1":
        message = "Documento caricato correttamente."
    elif request.GET.get("nota") == "1":
        message = "Segnalazione inviata."
    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    return render(request, "primanota/upload.html", _contesto(
        request, scansioni=scansioni, error=error, message=message, ieri=ieri,
        tipi_nota=Nota.TIPI, note=Nota.objects.filter(negozio_id=negozio_id)[:30],
        negozio=etichetta_negozio(negozio(negozio_id))))


@_accesso(solo_ufficio=True)
def admin(request):
    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    data_da = _data(request.GET.get("data_da"), ieri)
    data_a = _data(request.GET.get("data_a"), data_da)
    filtro_negozio = request.GET.get("negozio", "")
    filtro_tipo = request.GET.get("tipo", "")
    filtri_inviati = bool(request.GET)
    solo_non_lavorati = (not filtri_inviati) or request.GET.get("solo_non_lavorati") == "on"
    error = None
    try:
        scansioni = elenco_scansioni(negozio_id=filtro_negozio or None, data_da=data_da, data_a=data_a)
    except RuntimeError as exc:
        scansioni, error = [], str(exc)
    if filtro_tipo:
        scansioni = [s for s in scansioni if s["tipo_documento"] == filtro_tipo]
    if solo_non_lavorati:
        scansioni = [s for s in scansioni if not s["lavorato"] or (s["versamento"] and not s["versamento_lavorato"])]

    # Raggruppate per giornata di prima nota (negozio + data), come la vista per negozio di Scansioni.
    negozi = {n["id"]: n for n in negozi_attivi_ordinati()}
    giornate = OrderedDict()
    for s in sorted(scansioni, key=lambda s: (s["data_documento"], str((negozi.get(s["negozio_id"]) or {}).get("codice", ""))), reverse=True):
        chiave = (s["negozio_id"], s["data_documento"])
        g = giornate.setdefault(chiave, {
            "negozio_id": s["negozio_id"], "data": s["data_documento"], "data_fmt": s["data_documento_fmt"],
            "negozio": etichetta_negozio(negozi.get(s["negozio_id"])) or s["negozio_id"], "scansioni": []})
        g["scansioni"].append(s)
    for g in giornate.values():
        g["scansioni"].sort(key=lambda s: ([t["id"] for t in TIPI_DOCUMENTO].index(s["tipo_documento"])
                                           if s["tipo_documento"] in TIPI_VALIDI else 99, s["cassa"] or 0))

    return render(request, "primanota/admin.html", _contesto(
        request, giornate=list(giornate.values()), negozi=list(negozi.values()), error=error,
        filtro_negozio=filtro_negozio, filtro_tipo=filtro_tipo, data_da=data_da, data_a=data_a,
        solo_non_lavorati=solo_non_lavorati, conteggio=len(scansioni), per_foglio=[1, 2, 4, 6, 8, 9],
        note_aperte=Nota.objects.filter(chiusa=False).count(),
        richieste_contatto=Nota.objects.filter(chiusa=False, tipo=Nota.RICHIESTA_CONTATTO).count()))


@_accesso(solo_ufficio=True)
def giornata(request, negozio_id, giorno):
    giorno = _data(giorno)
    if not giorno:
        raise Http404
    n = negozio(negozio_id)
    if not n:
        raise Http404("Negozio non trovato")
    error = None

    if request.method == "POST":
        testo = request.POST.get("testo", "").strip()
        tipo = request.POST.get("tipo")
        if testo and tipo in dict(Nota.TIPI):
            Nota.objects.create(negozio_id=negozio_id, data=giorno, tipo=tipo, testo=testo,
                                creata_da=nome_utente(request.utente_primanota))
        return redirect(request.path)

    try:
        scansioni = elenco_scansioni(negozio_id=negozio_id, data_da=giorno, data_a=giorno)
    except RuntimeError as exc:
        scansioni, error = [], str(exc)
    files = list(FileSysSpy.objects.filter(negozio_id=negozio_id, data=giorno).order_by("cassa"))
    documenti = list(DocumentoSysSpy.objects.filter(file__in=files).select_related("file"))

    def docs(*tipi):
        return [d for d in documenti if d.tipo in tipi]

    # Per ogni genere di scansione, il testo SysSpy da affiancare.
    anteprime = {
        CHIUSURA_FISCALE: [(f"Cassa {f.cassa}", f.chiusura_fiscale) for f in files if f.chiusura_fiscale],
        CHIUSURA_POS: [(f"Cassa {f.cassa}", f.chiusura_pos) for f in files if f.chiusura_pos],
        RESI: [(f"Cassa {d.file.cassa} · {d.numero} · {d.ora}", d.testo) for d in docs(DocumentoSysSpy.RESO)],
        TRANSAZIONI_ABORTITE: [(f"Cassa {d.file.cassa} · {d.numero} · {d.ora}", d.testo) for d in docs(DocumentoSysSpy.ABORTITO)],
        VERSAMENTO_CONTANTE: [],
    }
    regole = RegolaDocumento.mappa()
    sezioni = []
    for t in TIPI_DOCUMENTO:
        sezioni.append({
            "tipo": t,
            "scansioni": [s for s in scansioni if s["tipo_documento"] == t["id"]],
            "anteprime": anteprime[t["id"]],
            "versamento": t["id"] == VERSAMENTO_CONTANTE,
            "obbligatoria": obbligatoria(regole.get(t["id"]), bool(anteprime[t["id"]])),
        })
    altre = [s for s in scansioni if s["tipo_documento"] not in TIPI_VALIDI]

    casse = []
    for f in files:
        controlli = f.controlli
        casse.append({
            "file": f, "controlli": controlli,
            "anomalie": any(c["esito"] == "attenzione" for c in controlli),
            "da_spiegare": bool(controlli) and not f.cassa_vuota,
            "contanti": (f.pagamenti or {}).get("Contanti"),
            "buoni": (f.pagamenti or {}).get("Buoni Pasto"),
        })
    # Casse dello stesso negozio che registrano il "non riscosso" in modo diverso.
    configurazioni = {}
    for f in files:
        if f.configurazione_non_riscosso:
            configurazioni.setdefault(f.configurazione_non_riscosso, []).append(str(f.cassa))
    configurazioni_diverse = len(configurazioni) > 1 and {
        "carte": ", ".join(configurazioni["carte"]), "buoni": ", ".join(configurazioni["buoni"])}
    corrente = date.fromisoformat(giorno)
    return render(request, "primanota/giornata.html", _contesto(
        request, configurazioni_diverse=configurazioni_diverse, negozio=n, negozio_label=etichetta_negozio(n), negozio_id=negozio_id,
        giorno=giorno, giorno_fmt=corrente.strftime("%d/%m/%Y"),
        precedente=(corrente - timedelta(days=1)).isoformat(), successivo=(corrente + timedelta(days=1)).isoformat(),
        sezioni=sezioni, altre=altre, files=files, casse=casse, error=error,
        storni=docs(DocumentoSysSpy.STORNO, DocumentoSysSpy.ANNULLAMENTO), pos_negate=docs(DocumentoSysSpy.POS_NEGATO),
        note=Nota.objects.filter(negozio_id=negozio_id, data=giorno), tipi_nota=Nota.TIPI))


@_accesso(solo_ufficio=True)
def monitor(request):
    vista = request.GET.get("vista", "mese").strip().lower()
    try:
        dati = build_monitor(year=request.GET.get("anno"), month=request.GET.get("mese"),
                             view_mode="week" if vista in {"week", "settimana"} else "month",
                             week_start=request.GET.get("settimana", "").strip() or None)
        error = None
    except RuntimeError as exc:
        dati, error = None, str(exc)
    return render(request, "primanota/monitor.html", _contesto(request, monitor=dati, error=error))


@require_POST
@_accesso(solo_ufficio=True)
def update_lavorato(request, scansione_id):
    try:
        dati = json.loads(request.body or "{}")
    except ValueError:
        dati = {}
    try:
        risultato = aggiorna_lavorato(request.utente_primanota, scansione_id, bool(dati.get("lavorato")),
                                      versamento=bool(dati.get("versamento")))
    except RuntimeError as exc:
        risultato = {"error": str(exc)}
    return JsonResponse(risultato, status=400 if "error" in risultato else 200)


@require_POST
@_accesso()
def delete(request, scansione_id):
    user = request.utente_primanota
    try:
        s = leggi_scansione(scansione_id)
        if is_store_user(user):
            # Il negozio elimina solo i propri documenti non ancora lavorati, come in Scansioni PV.
            if s["negozio_id"] != get_user_store_id(user):
                return JsonResponse({"error": "Scansione non trovata o non autorizzata."}, status=403)
            if s["lavorato"] or s["versamento_lavorato"]:
                return JsonResponse({"error": "Documento già lavorato: cancellazione non consentita."}, status=400)
        return JsonResponse(elimina_scansione(scansione_id))
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@_accesso(solo_ufficio=True)
def chiudi_nota(request, nota_id):
    nota = get_object_or_404(Nota, pk=nota_id)
    nota.chiusa = not nota.chiusa
    nota.chiusa_da = nome_utente(request.utente_primanota) if nota.chiusa else ""
    nota.chiusa_il = timezone.now() if nota.chiusa else None
    nota.save()
    return redirect(request.POST.get("ritorno") or f"/primanota/giornata/{nota.negozio_id}/{nota.data.isoformat()}/")


@_accesso(solo_ufficio=True)
def note(request):
    stato = request.GET.get("stato", "aperte")
    elenco = Nota.objects.all()
    if stato == "aperte":
        elenco = elenco.filter(chiusa=False)
    negozi = {n["id"]: etichetta_negozio(n) for n in negozi_attivi_ordinati()}
    elenco = [(nota, negozi.get(nota.negozio_id, nota.negozio_id)) for nota in elenco[:300]]
    return render(request, "primanota/note.html", _contesto(request, elenco=elenco, stato=stato))


@_accesso(solo_ufficio=True)
def sysspy_archivio(request):
    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    data_da = _data(request.GET.get("data_da"), ieri)
    data_a = _data(request.GET.get("data_a"), data_da)
    filtro_negozio = request.GET.get("negozio", "")
    testo = request.GET.get("testo", "").strip()
    files = FileSysSpy.objects.filter(data__range=(data_da, data_a))
    if filtro_negozio.isdigit():
        files = files.filter(negozio_id=int(filtro_negozio))
    files = list(files.order_by("-data", "codice_negozio", "cassa")[:1000])
    error = None
    risultati = None
    if testo:
        if (date.fromisoformat(data_a) - date.fromisoformat(data_da)).days >= MAX_GIORNI_RICERCA:
            error = f"Per la ricerca nel testo scegliere al massimo {MAX_GIORNI_RICERCA} giorni."
        else:
            risultati = []
            cercato = testo.casefold()
            for f in files:
                try:
                    righe = [r for r in importazione.leggi_testo(f).splitlines() if cercato in r.casefold()]
                except OSError:
                    continue
                if righe:
                    risultati.append((f, righe[:5], len(righe)))
    negozi = negozi_attivi_ordinati()
    return render(request, "primanota/sysspy.html", _contesto(
        request, files=files, risultati=risultati, testo=testo, negozi=negozi, error=error,
        filtro_negozio=filtro_negozio, data_da=data_da, data_a=data_a))


@_accesso(solo_ufficio=True)
def sysspy_dettaglio(request, file_id):
    f = get_object_or_404(FileSysSpy, pk=file_id)
    try:
        testo = importazione.leggi_testo(f)
    except OSError:
        testo = "File di testo non trovato nell'archivio."
    return render(request, "primanota/sysspy_dettaglio.html", _contesto(
        request, f=f, testo=testo, negozio_label=etichetta_negozio(negozio(f.negozio_id)) or f.codice_negozio,
        documenti=f.documenti.all()))


@_accesso(solo_ufficio=True)
def sysspy_scarica(request, file_id):
    f = get_object_or_404(FileSysSpy, pk=file_id)
    if not Path(f.percorso_archivio).is_file():
        raise Http404
    return FileResponse(open(f.percorso_archivio, "rb"), as_attachment=True, filename=f.nome_file)


@_accesso(solo_ufficio=True, solo_gestione=True)
def condivisioni(request):
    piano = Pianificazione.corrente()
    errore_orari = None
    if request.method == "POST" and request.POST.get("azione") == "regole":
        for t in TIPI_DOCUMENTO:
            valore = request.POST.get(f"regola_{t['chiave']}")
            if valore in dict(RegolaDocumento.SCELTE):
                RegolaDocumento.objects.update_or_create(tipo_documento=t["id"], defaults={"obbligo": valore})
        return redirect("/primanota/condivisioni/?salvato=1")
    if request.method == "POST" and request.POST.get("azione") == "pianificazione":
        orari = request.POST.get("orari", "").strip()
        ora_ricostruzione = request.POST.get("ricostruzione_ora", "").strip()
        prova = Pianificazione(orari=orari)
        try:
            prova.elenco_orari()
            if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", ora_ricostruzione) or \
                    not all(0 <= o < 24 and 0 <= m < 60 for o, m in prova.elenco_orari()):
                raise ValueError
        except ValueError:
            errore_orari = "Orari non validi: scriverli come 20:30, 22:00, 06:00."
        else:
            piano.attiva = request.POST.get("attiva") == "on"
            piano.orari = ", ".join(f"{o:02d}:{m:02d}" for o, m in prova.elenco_orari())
            piano.ricostruzione_attiva = request.POST.get("ricostruzione_attiva") == "on"
            piano.ricostruzione_giorno = int(request.POST.get("ricostruzione_giorno", 6))
            piano.ricostruzione_ora = ora_ricostruzione.zfill(5)
            piano.save()
            return redirect("/primanota/condivisioni/?salvato=1")
    elif request.method == "POST":
        try:
            negozio_id = int(request.POST.get("negozio_id", ""))
        except ValueError:
            return redirect("/primanota/condivisioni/")
        n = negozio(negozio_id)
        if n:
            cond, _ = Condivisione.objects.get_or_create(negozio_id=negozio_id, defaults={"codice_negozio": n["codice"]})
            cond.codice_negozio = str(n["codice"])
            cond.percorso = request.POST.get("percorso", "").strip()
            cond.utente = request.POST.get("utente", "").strip()
            cond.attiva = request.POST.get("attiva") == "on"
            # Password lasciata vuota = resta quella salvata.
            if request.POST.get("password"):
                cond.password_cifrata = importazione.cifra(request.POST["password"])
            cond.save()
        return redirect("/primanota/condivisioni/")
    esistenti = {c.negozio_id: c for c in Condivisione.objects.all()}
    righe = [(n, esistenti.get(n["id"])) for n in negozi_attivi_ordinati()]
    return render(request, "primanota/condivisioni.html", _contesto(
        request, righe=righe, piano=piano, giorni=Pianificazione.GIORNI, errore_orari=errore_orari,
        regole=[(t, RegolaDocumento.mappa().get(t["id"])) for t in TIPI_DOCUMENTO], scelte_regole=RegolaDocumento.SCELTE,
        salvato=request.GET.get("salvato") == "1"))


@require_POST
@_accesso(solo_ufficio=True, solo_gestione=True)
def avvia_importazione(request, negozio_id):
    cond = get_object_or_404(Condivisione, negozio_id=negozio_id)
    lavoro = importazione.avvia_in_background(cond, completa=request.POST.get("completa") == "1")
    return redirect(f"/primanota/importazione/{lavoro}/")


@require_POST
@_accesso(solo_ufficio=True, solo_gestione=True)
def rielabora(request):
    return redirect(f"/primanota/importazione/{importazione.avvia_rielaborazione_in_background()}/")


@require_POST
@_accesso(solo_ufficio=True, solo_gestione=True)
def importa_tutti(request):
    lavoro = importazione.avvia_tutte_in_background(completa=request.POST.get("completa") == "1")
    return redirect(f"/primanota/importazione/{lavoro}/")


@_accesso(solo_ufficio=True, solo_gestione=True)
def stato_importazione(request, lavoro):
    stato = importazione.LAVORI.get(lavoro)
    if request.GET.get("formato") == "json" or request.method == "POST":
        if not stato:
            return JsonResponse({"stato": "sconosciuta"}, status=404)
        if request.method == "POST":
            stato["_stop"].set()
        return JsonResponse({k: v for k, v in stato.items() if not k.startswith("_")})
    if not stato:
        raise Http404
    return render(request, "primanota/importazione.html", _contesto(request, lavoro=lavoro, stato=stato))


# La stampa scarica e impagina gli allegati: si limita il periodo.
MAX_GIORNI_STAMPA = 31


@xframe_options_sameorigin  # il PDF si apre nella finestra di stampa della pagina stessa
@_accesso(solo_ufficio=True)
def stampa(request):
    """PDF A4 delle chiusure fiscali o POS (scansioni + estratti SysSpy), più documenti per foglio."""
    from .services import stampa as servizio

    sezione = request.GET.get("sezione", "fiscale")
    if sezione not in servizio.SEZIONI:
        raise Http404
    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    data_da = _data(request.GET.get("data_da"), ieri)
    data_a = _data(request.GET.get("data_a"), data_da)
    if (date.fromisoformat(data_a) - date.fromisoformat(data_da)).days >= MAX_GIORNI_STAMPA:
        return HttpResponse(f"Scegliere al massimo {MAX_GIORNI_STAMPA} giorni.", status=400)
    negozio_id = request.GET.get("negozio") or None
    try:
        per_pagina = int(request.GET.get("per_pagina", 4))
    except ValueError:
        per_pagina = 4
    contenuto = request.GET.get("contenuto", "tutto")
    try:
        voci = servizio.elementi(sezione, negozio_id=int(negozio_id) if negozio_id else None,
                                 data_da=data_da, data_a=data_a, contenuto=contenuto)
    except RuntimeError as exc:
        return HttpResponse(str(exc), status=502)
    titolo = f"{servizio.SEZIONI[sezione]['titolo']} dal {date.fromisoformat(data_da):%d/%m/%Y} al {date.fromisoformat(data_a):%d/%m/%Y}"
    pdf = servizio.genera_pdf(voci, per_pagina=per_pagina, titolo=titolo)
    risposta = HttpResponse(pdf, content_type="application/pdf")
    risposta["Content-Disposition"] = f'inline; filename="{sezione}_{data_da}_{data_a}.pdf"'
    return risposta

