import json
import logging
import re
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .models import (Condivisione, DestinatarioEmail, DocumentoSysSpy, Emergenza, FileSysSpy, GiornataLavorazione, Nota, ScontrinoSospeso,
                     Pianificazione, RegolaDocumento)
from .services.allegati import ottimizza
from .services.giornate import stato as giornate_stato
from .services.regole import NON_RICHIESTA, obbligatoria, stato_giornate
from .services import importazione
from .services.accesso import (
    can_access_primanota,
    can_manage_primanota,
    can_see_versamenti,
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
    FATTURE_SPESE,
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


log = logging.getLogger(__name__)

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
    # I versamenti contante li vede la sede (non i negozi): hanno sezione e monitor propri.
    return {"utente": user, "puo_gestire": can_manage_primanota(user), "puo_versamenti": can_see_versamenti(user),
            "utente_negozio": is_store_user(user),
            "tipi_documento": [t for t in TIPI_DOCUMENTO if t["id"] != VERSAMENTO_CONTANTE],
            "tipi_documento_tutti": TIPI_DOCUMENTO, **altro}


def _negozio_consentito(request, negozio_id):
    """Il negozio vede solo le proprie giornate e i propri SysSpy; la sede tutto."""
    user = request.utente_primanota
    return not is_store_user(user) or str(negozio_id) == str(get_user_store_id(user))


def _giornate_recenti(negozio_id, giorni=14):
    """
    Ultime giornate del negozio per la pagina di caricamento: totali e controlli dei SysSpy e
    scansioni obbligatorie (secondo le regole di Amministratore e Direttore) non ancora caricate.
    """
    ieri = timezone.localdate() - timedelta(days=1)
    dal = ieri - timedelta(days=giorni - 1)
    per_giorno = OrderedDict()
    for i in range(giorni):
        d = ieri - timedelta(days=i)
        per_giorno[d] = {"data": d, "casse": 0, "totale": Decimal("0"), "pos": Decimal("0"), "anomalie": [],
                         "fiscale": 0, "chiusure_pos": 0, "mancanti": []}
    for f in FileSysSpy.objects.filter(negozio_id=negozio_id, data__range=(dal, ieri)).order_by("cassa"):
        if f.cassa_vuota:
            continue
        g = per_giorno[f.data]
        g["casse"] += 1
        g["totale"] += f.totale_giornaliero or f.totale_scontrini or 0
        g["pos"] += f.totale_pos or 0
        g["fiscale"] += bool(f.chiusura_fiscale)
        g["chiusure_pos"] += bool(f.chiusura_pos)
        g["anomalie"] += [f"Cassa {f.cassa}: {c['titolo']}" for c in f.controlli if c["esito"] == "attenzione"]
    try:
        caricate = elenco_scansioni(negozio_id=negozio_id, data_da=dal.isoformat(), data_a=ieri.isoformat())
    except RuntimeError:
        return list(per_giorno.values())   # Baserow non risponde: non si segnala niente come mancante
    for d, voci in stato_giornate(negozio_id, dal, ieri, caricate).items():
        per_giorno[d]["mancanti"] = [v["tipo"]["label"] for v in voci if v["manca"]]
    return list(per_giorno.values())


def _voci_caricamento(negozio_id, giorno):
    """Generi della giornata per il modulo del negozio: stato secondo le regole e scansioni già caricate."""
    d = date.fromisoformat(giorno)
    caricate = elenco_scansioni(negozio_id=negozio_id, data_da=giorno, data_a=giorno)
    return stato_giornate(negozio_id, d, d, caricate)[d]


def _blocco_prima_nota(negozio_id, giorno):
    """Messaggio se la prima nota della giornata non c'è o non è certificata (le scansioni si inviano dopo)."""
    from .services.prima_nota import prima_nota_pronta
    d = date.fromisoformat(giorno)
    if Emergenza.objects.filter(negozio_id=negozio_id, data=d).exists():
        return None   # il negozio ha dichiarato l'Emergenza: le scansioni si inviano senza prima nota
    stato = prima_nota_pronta((negozio(negozio_id) or {}).get("codice"), d)
    if stato == "mancante":
        return (f"La prima nota del {d:%d/%m/%Y} non è ancora presente: compila e certifica prima la prima nota, "
                "poi invia le scansioni.")
    if stato == "non_certificata":
        from .services.prima_nota import non_certificati
        movimenti = non_certificati((negozio(negozio_id) or {}).get("codice"), d)
        dettaglio = "; ".join(f"n. {m['progressivo']} delle {m['ora']} {m['causale_descr'] or m['causale']} "
                              + f"{m['importo']:.2f} €".replace(".", ",") for m in movimenti[:5])
        if len(movimenti) > 5:
            dettaglio += f" e altri {len(movimenti) - 5}"
        return (f"La prima nota del {d:%d/%m/%Y} non è ancora certificata: certificala prima, poi invia le scansioni."
                + (f" Movimenti senza certificazione: {dettaglio}." if dettaglio else ""))
    return None


def _salva_giornata(request, user, negozio_id):
    """
    Salva le scansioni della giornata, una per genere, e la nota per l'ufficio scritta sotto. Non salva
    scansioni se manca un allegato obbligatorio (secondo le regole), se si allega un genere non richiesto o se
    la prima nota della giornata non è ancora certificata. La sola nota si salva sempre. Restituisce l'errore o None.
    """
    giorno = _data(request.POST.get("data_documento"))
    if not giorno:
        return "Indica la data del documento."
    voci = _voci_caricamento(negozio_id, giorno)
    file_per_tipo = {v["tipo"]["id"]: request.FILES.get(f"documento_{v['tipo']['chiave']}") for v in voci}
    note = request.POST.get("note", "").strip()
    tipo_nota = request.POST.get("tipo_nota") if request.POST.get("tipo_nota") in dict(TIPI_NOTA_CON_VERSAMENTO) else Nota.NOTA

    def salva_nota():
        if tipo_nota == NOTA_VERSAMENTO:
            _nota_versamento(user, negozio_id, giorno, note)
        else:
            Nota.objects.create(negozio_id=negozio_id, data=giorno, tipo=tipo_nota, testo=note, creata_da=nome_utente(user))
    da_salvare = [v for v in voci if file_per_tipo[v["tipo"]["id"]]]
    if not da_salvare:
        if not note:
            return "Allega almeno un documento o scrivi una nota."
        salva_nota()
        return None
    blocco = _blocco_prima_nota(negozio_id, giorno)
    if blocco:
        return blocco
    mancanti = [v["tipo"]["label"] for v in voci if v["manca"] and not file_per_tipo[v["tipo"]["id"]]]
    if mancanti:
        return "Mancano gli allegati obbligatori: " + ", ".join(mancanti) + ". Nessun documento è stato salvato."
    non_richiesti = [v["tipo"]["label"] for v in voci if v["stato"] == NON_RICHIESTA and file_per_tipo[v["tipo"]["id"]]]
    if non_richiesti:
        return "Documenti non previsti per questa giornata: " + ", ".join(non_richiesti) + "."
    casse = {}
    for v in da_salvare:
        cassa = request.POST.get(f"cassa_{v['tipo']['chiave']}", "").strip()
        if cassa and not cassa.isdigit():
            return f"{v['tipo']['label']}: la cassa deve essere un numero."
        casse[v["tipo"]["id"]] = int(cassa) if cassa else None
    salvati = []
    for v in da_salvare:
        t = v["tipo"]["id"]
        try:
            risultato = crea_scansione(user, negozio_id, giorno, t, ottimizza(file_per_tipo[t]), cassa=casse[t], note=note)
        except RuntimeError as exc:
            risultato = {"error": str(exc)}
        if "error" in risultato:
            gia = f" Salvati: {', '.join(salvati)}." if salvati else ""
            return f"{v['tipo']['label']}: {str(risultato['error']).rstrip('.')}.{gia}"
        salvati.append(v["tipo"]["label"])
    if note:
        salva_nota()
    return None


# Nei moduli delle note, oltre ai tipi normali: la nota sul versamento contante, inviata per email.
NOTA_VERSAMENTO = "VERSAMENTO"
TIPI_NOTA_CON_VERSAMENTO = Nota.TIPI + [(NOTA_VERSAMENTO, "Nota sul versamento (inviata per email)")]


def _nota_versamento(user, negozio_id, giorno, testo, scansione=None):
    """
    Nota sul versamento contante della giornata, inviata per email a tutti i destinatari attivi con la
    scansione del versamento in allegato (se c'è). Restituisce "inviata", "nota" (nessun destinatario) o "noninviata".
    """
    if scansione is None:
        try:
            scansione = next((s for s in elenco_scansioni(negozio_id=negozio_id, data_da=giorno, data_a=giorno)
                              if s["versamento"]), None)
        except RuntimeError:
            scansione = None
    nota = Nota.objects.create(negozio_id=negozio_id, data=giorno, tipo=Nota.NOTA, testo=testo, creata_da=nome_utente(user),
                               versamento=True, scansione_id=scansione["id"] if scansione else None)
    destinatari = list(DestinatarioEmail.objects.filter(attivo=True))
    if not destinatari:
        return "nota"
    oggetto = f"Versamento contante {etichetta_negozio(negozio(negozio_id))} del {date.fromisoformat(str(giorno)):%d/%m/%Y}"
    corpo = (f"{oggetto}\n\nNota di {nome_utente(user)}:\n{testo}\n\n"
             + ("In allegato la scansione del versamento." if scansione else "Scansione del versamento non ancora caricata."))
    try:
        from .services.posta import invia
        invia([d.email for d in destinatari], oggetto, corpo,
              allegato_url=((scansione or {}).get("anteprima") or {}).get("url"),
              allegato_nome=(scansione["documento"][0]["visible_name"] if scansione and scansione["documento"] else None))
        nota.esito_invio, esito = "Inviata", "inviata"
    except Exception as exc:
        nota.esito_invio, esito = f"Invio non riuscito: {exc}", "noninviata"
    nota.inviata_a = ", ".join(d.email for d in destinatari)
    nota.save(update_fields=["inviata_a", "esito_invio"])
    return esito


@_accesso()
def home(request):
    """Documenti Amministrativi: il negozio va al caricamento, la sede sceglie la sezione."""
    if is_store_user(request.utente_primanota):
        return redirect("/primanota/upload/")
    return render(request, "primanota/home.html", _contesto(
        request, note_chiusure=Nota.objects.filter(versamento=False, chiusa=False).count(),
        note_versamenti=Nota.objects.filter(versamento=True, chiusa=False).count()))


@_accesso()
def upload(request):
    user = request.utente_primanota
    if not is_store_user(user):
        return redirect("/primanota/monitor/")
    negozio_id = get_user_store_id(user)
    error = None

    if request.method == "POST" and request.POST.get("azione") == "nota_versamento":
        testo = request.POST.get("testo", "").strip()
        try:
            s = leggi_scansione(int(request.POST.get("scansione_id", "")))
        except (ValueError, RuntimeError):
            s = None
        if not s or s["negozio_id"] != negozio_id or not s["versamento"] or not testo:
            error = "Scrivi il testo della nota sul versamento."
        else:
            esito = _nota_versamento(user, negozio_id, s["data_documento"], testo, s)
            return redirect(f"/primanota/upload/?versamento={esito}")
    elif request.method == "POST" and request.POST.get("azione") == "emergenza":
        giorno = _data(request.POST.get("data"))
        motivo = request.POST.get("motivo", "").strip()
        if not giorno or not motivo:
            error = "Per attivare l'Emergenza scrivi il motivo."
        else:
            _, nuova = Emergenza.objects.get_or_create(negozio_id=negozio_id, data=giorno, defaults={
                "motivo": motivo, "attivata_da": nome_utente(user)})
            if nuova:
                # La sede lo vede subito tra le note e anomalie, oltre che nel monitor.
                Nota.objects.create(negozio_id=negozio_id, data=giorno, tipo=Nota.ANOMALIA, creata_da=nome_utente(user),
                                    testo=f"Modalità Emergenza attivata: prima nota non disponibile. Motivo: {motivo}")
            return redirect(f"/primanota/upload/?data={giorno}")
    elif request.method == "POST":
        error = _salva_giornata(request, user, negozio_id)
        if not error:
            # Post/Redirect/Get come in Scansioni PV: niente doppi invii.
            return redirect(f"/primanota/upload/?uploaded=1&data={request.POST.get('data_documento')}")

    try:
        scansioni = elenco_scansioni(negozio_id=negozio_id, max_risultati=50)
    except RuntimeError as exc:
        scansioni, error = [], error or str(exc)
    note_versamenti = {}
    for nota in Nota.objects.filter(negozio_id=negozio_id, versamento=True, scansione_id__isnull=False):
        note_versamenti.setdefault(nota.scansione_id, []).append(nota)
    for s in scansioni:
        s["note_versamento"] = note_versamenti.get(s["id"], [])
    message = None
    if request.GET.get("uploaded") == "1":
        message = "Giornata salvata correttamente."
    elif request.GET.get("nota") == "1":
        message = "Segnalazione inviata."
    elif request.GET.get("versamento") == "inviata":
        message = "Nota sul versamento salvata e inviata per email."
    elif request.GET.get("versamento") == "nota":
        message = "Nota sul versamento salvata."
    elif request.GET.get("versamento") == "noninviata":
        error = "Nota salvata, ma l'invio email non è riuscito: avvisare la sede."
    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    giorno = _data(request.POST.get("data_documento") or request.GET.get("data"), ieri)
    try:
        voci = _voci_caricamento(negozio_id, giorno)
    except RuntimeError as exc:
        voci, error = [], error or str(exc)
    return render(request, "primanota/upload.html", _contesto(
        request, scansioni=scansioni, error=error, message=message, ieri=ieri, giorno=giorno, voci=voci,
        blocco_prima_nota=_blocco_prima_nota(negozio_id, giorno),
        emergenza=Emergenza.objects.filter(negozio_id=negozio_id, data=giorno).first(),
        tipi_nota=TIPI_NOTA_CON_VERSAMENTO, note=Nota.objects.filter(negozio_id=negozio_id, versamento=False)[:30],
        destinatari=DestinatarioEmail.objects.filter(attivo=True), giornate=_giornate_recenti(negozio_id),
        negozio_id=negozio_id,
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
    # I versamenti hanno la loro sezione (Versamenti), riservata a Direttori e Amministratori.
    scansioni = [s for s in scansioni if not s["versamento"]]
    if filtro_tipo:
        scansioni = [s for s in scansioni if s["tipo_documento"] == filtro_tipo]
    # Raggruppate per giornata di prima nota (negozio + data), come la vista per negozio di Scansioni.
    negozi = {n["id"]: n for n in negozi_attivi_ordinati()}
    giornate = OrderedDict()
    for s in sorted(scansioni, key=lambda s: (s["data_documento"], str((negozi.get(s["negozio_id"]) or {}).get("codice", ""))), reverse=True):
        chiave = (s["negozio_id"], s["data_documento"])
        g = giornate.setdefault(chiave, {
            "negozio_id": s["negozio_id"], "data": s["data_documento"], "data_fmt": s["data_documento_fmt"],
            "negozio": etichetta_negozio(negozi.get(s["negozio_id"])) or s["negozio_id"], "scansioni": []})
        g["scansioni"].append(s)
    # «Lavorato» è della giornata intera: «solo da lavorare» lascia le giornate non lavorate (né chiuse).
    righe_stato = GiornataLavorazione.mappa(date.fromisoformat(data_da), date.fromisoformat(data_a))
    for g in giornate.values():
        g["stato"] = giornate_stato(g["negozio_id"], date.fromisoformat(g["data"]), righe_stato, con_scansioni=True)
    if solo_non_lavorati:
        giornate = OrderedDict((k, g) for k, g in giornate.items() if g["stato"]["stato"] == GiornataLavorazione.NON_LAVORATO)
    for g in giornate.values():
        g["scansioni"].sort(key=lambda s: ([t["id"] for t in TIPI_DOCUMENTO].index(s["tipo_documento"])
                                           if s["tipo_documento"] in TIPI_VALIDI else 99, s["cassa"] or 0))

    return render(request, "primanota/admin.html", _contesto(
        request, giornate=list(giornate.values()), negozi=list(negozi.values()), error=error,
        filtro_negozio=filtro_negozio, filtro_tipo=filtro_tipo, data_da=data_da, data_a=data_a,
        solo_non_lavorati=solo_non_lavorati, conteggio=sum(len(g["scansioni"]) for g in giornate.values()), per_foglio=[1, 2, 4, 6, 8, 9],
        note_negozi=_note_negozi(request, filtro_negozio, negozi)))


def _note_negozi(request, filtro_negozio, negozi):
    """Segnalazioni dei negozi ancora da lavorare, dalla più recente: in testa al riepilogo."""
    note = Nota.objects.filter(chiusa=False, versamento=False)
    if filtro_negozio.isdigit():
        note = note.filter(negozio_id=int(filtro_negozio))
    return [(n, etichetta_negozio(negozi.get(n.negozio_id)) or n.negozio_id) for n in note[:50]]


@_accesso()
def giornata(request, negozio_id, giorno):
    """Riepilogo di una giornata. Il negozio vede la propria in sola lettura (e può scrivere note)."""
    giorno = _data(giorno)
    if not giorno:
        raise Http404
    if not _negozio_consentito(request, negozio_id):
        return HttpResponseForbidden("Puoi vedere solo le giornate del tuo negozio.")
    n = negozio(negozio_id)
    if not n:
        raise Http404("Negozio non trovato")
    error = None

    # Le note sui versamenti le vedono il negozio e la sede che gestisce i versamenti.
    vede_versamenti = is_store_user(request.utente_primanota) or can_see_versamenti(request.utente_primanota)
    if request.method == "POST":
        testo = request.POST.get("testo", "").strip()
        tipo = request.POST.get("tipo")
        if testo and tipo == NOTA_VERSAMENTO and vede_versamenti:
            _nota_versamento(request.utente_primanota, negozio_id, giorno, testo)
        elif testo and tipo in dict(Nota.TIPI):
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
        # Le sospensioni dello scontrino (stampate come operazione abortita) sono negli scontrini sospesi.
        TRANSAZIONI_ABORTITE: [(f"Cassa {d.file.cassa} · {d.numero} · {d.ora}", d.testo) for d in docs(DocumentoSysSpy.ABORTITO)
                               if "SOSPENSIONE SCONTRINO" not in d.testo],
        VERSAMENTO_CONTANTE: [],
        FATTURE_SPESE: [],
    }
    # Spese del giorno con fattura dalla prima nota: chiedono la scansione della fattura.
    fatture_errore = None
    try:
        from .services.prima_nota import spese_con_fattura
        for m in spese_con_fattura(n.get("codice"), giorno):
            righe = [f"Importo: {m['importo']:.2f} €".replace(".", ",")]
            righe += [x for x in (m["descrizione"], m["documento"] and f"Documento: {m['documento']}") if x]
            if m["note"]:
                righe.append(f"Note: {m['note']}")
            anteprime[FATTURE_SPESE].append((f"Prima nota · n. {m['progressivo']} · {m['ora']}", "\n".join(righe)))
    except RuntimeError as exc:
        fatture_errore = str(exc)
    regole = RegolaDocumento.mappa()
    sezioni = []
    for t in TIPI_DOCUMENTO:
        if t["id"] == VERSAMENTO_CONTANTE:
            continue   # nella sezione Versamenti
        sezioni.append({
            "tipo": t,
            "scansioni": [s for s in scansioni if s["tipo_documento"] == t["id"]],
            "anteprime": anteprime[t["id"]],
            "versamento": t["id"] == VERSAMENTO_CONTANTE,
            "fonte": "prima nota" if t["id"] == FATTURE_SPESE else "SysSpy",
            "errore_fonte": fatture_errore if t["id"] == FATTURE_SPESE else None,
            "obbligatoria": obbligatoria(regole.get(t["id"]), bool(anteprime[t["id"]])),
        })
    altre = [s for s in scansioni if s["tipo_documento"] not in TIPI_VALIDI]   # i versamenti sono in Gestione Versamenti

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
            configurazioni.setdefault(f.configurazione_non_riscosso, []).append(
                f"{f.cassa} (matricola {f.matricola_stampante})" if f.matricola_stampante else str(f.cassa))
    configurazioni_diverse = len(configurazioni) > 1 and {
        "carte": ", ".join(configurazioni["carte"]), "buoni": ", ".join(configurazioni["buoni"])}
    corrente = date.fromisoformat(giorno)
    return render(request, "primanota/giornata.html", _contesto(
        request, configurazioni_diverse=configurazioni_diverse, negozio=n, negozio_label=etichetta_negozio(n), negozio_id=negozio_id,
        giorno=giorno, giorno_fmt=corrente.strftime("%d/%m/%Y"),
        precedente=(corrente - timedelta(days=1)).isoformat(), successivo=(corrente + timedelta(days=1)).isoformat(),
        sezioni=sezioni, altre=altre, files=files, casse=casse, error=error,
        storni=docs(DocumentoSysSpy.STORNO, DocumentoSysSpy.ANNULLAMENTO), pos_negate=docs(DocumentoSysSpy.POS_NEGATO),
        sospesi=ScontrinoSospeso.objects.filter(negozio_id=negozio_id, data=giorno).order_by("ora"),
        emergenza=Emergenza.objects.filter(negozio_id=negozio_id, data=giorno).first(),
        stato_giornata=giornate_stato(negozio_id, corrente, con_scansioni=bool(scansioni)), avviso_stato=request.GET.get("avviso_stato") == "1",
        note=Nota.objects.filter(negozio_id=negozio_id, data=giorno, **({} if vede_versamenti else {"versamento": False})),
        tipi_nota=TIPI_NOTA_CON_VERSAMENTO if vede_versamenti else Nota.TIPI,
        destinatari=DestinatarioEmail.objects.filter(attivo=True) if vede_versamenti else []))


@require_POST
@_accesso(solo_ufficio=True)
def stato_giornata(request, negozio_id, giorno):
    """Lavorato, Non lavorato o Giornata chiusura per tutta la giornata del negozio (si può sempre cambiare)."""
    from .services import giornate
    giorno = _data(giorno)
    nuovo = request.POST.get("stato")
    if not giorno or nuovo not in dict(GiornataLavorazione.STATI):
        raise Http404
    try:
        errori = giornate.imposta(request.utente_primanota, negozio_id, date.fromisoformat(giorno), nuovo,
                                  nome_utente(request.utente_primanota))
    except RuntimeError as exc:
        errori = [str(exc)]
    ritorno = request.POST.get("ritorno", "")
    if not url_has_allowed_host_and_scheme(ritorno, allowed_hosts={request.get_host()}) or not ritorno.startswith("/"):
        ritorno = f"/primanota/giornata/{negozio_id}/{giorno}/"
    if errori:
        ritorno += ("&" if "?" in ritorno else "?") + "avviso_stato=1"
    return redirect(ritorno)


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


def _elenco_note(request, versamento):
    """Segnalazioni dei negozi dalla più recente; di default solo quelle da lavorare."""
    lavorate = request.GET.get("lavorate") == "1"
    tutte = Nota.objects.filter(versamento=versamento)
    negozi = {n["id"]: etichetta_negozio(n) for n in negozi_attivi_ordinati()}
    elenco = [(nota, negozi.get(nota.negozio_id, nota.negozio_id))
              for nota in tutte.filter(chiusa=lavorate).order_by("-creata_il")[:300]]
    return render(request, "primanota/note.html", _contesto(
        request, elenco=elenco, lavorate=lavorate, da_lavorare=tutte.filter(chiusa=False).count(),
        note_versamenti=versamento))


@_accesso(solo_ufficio=True)
def note(request):
    """Note e anomalie delle Chiusure Fiscali (quelle sui versamenti sono in Gestione Versamenti)."""
    return _elenco_note(request, versamento=False)


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


STATI_SOSPESI = OrderedDict([("", "Tutti"), ("sospeso", "Ancora sospesi"), ("richiamato", "Richiamati ma non emessi"),
                              ("emesso", "Richiamati ed emessi"), ("ribattuto", "Ribattuti a mano"),
                              ("probabile", "Probabilmente ribattuti")])


@xframe_options_sameorigin  # il PDF si apre nella finestra di stampa della pagina stessa
@_accesso(solo_ufficio=True)
def sospesi(request):
    """Scontrini sospesi dalle casse: quelli ancora sospesi e quelli richiamati ed emessi fiscalmente."""
    from .models import FileSRI

    oggi = timezone.localdate()
    data_a = _data(request.GET.get("data_a"), oggi.isoformat())
    data_da = _data(request.GET.get("data_da"), (oggi - timedelta(days=30)).isoformat())
    filtro_negozio = request.GET.get("negozio", "")
    stato = request.GET.get("stato", "") if request.GET.get("stato", "") in STATI_SOSPESI else ""
    elenco = ScontrinoSospeso.objects.filter(data__range=(data_da, data_a))
    if filtro_negozio.isdigit():
        elenco = elenco.filter(negozio_id=int(filtro_negozio))
    tutti = list(elenco)
    riepilogo = OrderedDict((k, {"etichetta": v, "numero": 0, "importo": Decimal("0")})
                            for k, v in STATI_SOSPESI.items() if k)
    for s in tutti:
        riepilogo[s.stato]["numero"] += 1
        riepilogo[s.stato]["importo"] += s.importo or 0
    negozi = negozi_attivi_ordinati()
    etichette = {n["id"]: etichetta_negozio(n) for n in negozi}
    righe = [s for s in tutti if not stato or s.stato == stato]
    from .services.sospesi import cassieri
    nomi_cassieri = cassieri(righe[:2000])
    for s in righe:
        s.negozio_label = etichette.get(s.negozio_id, s.codice_negozio)
        s.cassiere, s.cassiere_emissione = nomi_cassieri.get(s.id, ("", ""))

    if request.GET.get("formato") == "pdf":
        # Gli scontrini interi, più per foglio, con un foglio nuovo per ogni punto vendita.
        from .services import sospesi as servizio
        from .services.stampa import GRIGLIE, genera_pdf
        ordine = {n["id"]: i for i, n in enumerate(negozi)}
        voci = []
        for s in sorted(righe, key=lambda s: (ordine.get(s.negozio_id, 9999), s.data, s.ora)):
            stato_testo = {"sospeso": "ancora sospeso", "richiamato": "richiamato, non emesso", "emesso": "emesso",
                           "ribattuto": "ribattuto a mano", "probabile": "probabilmente ribattuto"}[s.stato]
            didascalia = (f"{s.data:%d/%m/%Y} {s.ora:%H:%M:%S} · cassa {s.cassa}"
                          + (f" · {s.cassiere}" if s.cassiere else "") + f" · documento {s.numero} · "
                          f"{str(s.importo).replace('.', ',')} EUR · {stato_testo}")   # il carattere della stampa non ha l'euro
            voci.append((s.negozio_label, didascalia, "testo",
                         servizio.testo_scontrino(s.negozio_id, s.data, s.cassa, s.numero)
                         or servizio.testo_da_file_sr(s) or servizio.NON_TROVATO))
        try:
            per_pagina = int(request.GET.get("per_pagina", 4))
        except ValueError:
            per_pagina = 4
        n = negozio(int(filtro_negozio)) if filtro_negozio.isdigit() else None
        nome = "_".join(re.sub(r"[^\w-]+", "_", t).strip("_") for t in (
            "Scontrini_sospesi", etichetta_negozio(n) if n else "Tutti_i_negozi", f"dal {data_da} al {data_a}",
            STATI_SOSPESI[stato] if stato else "tutti")) + ".pdf"
        pdf = genera_pdf(voci, per_pagina=per_pagina if per_pagina in GRIGLIE else 4,
                         titolo=f"Scontrini sospesi dal {date.fromisoformat(data_da):%d/%m/%Y} al {date.fromisoformat(data_a):%d/%m/%Y}",
                         nome=nome)
        risposta = HttpResponse(pdf, content_type="application/pdf")
        risposta["Content-Disposition"] = f'inline; filename="{nome}"'
        return risposta
    file_letti = FileSRI.objects.filter(data__range=(data_da, data_a))
    if filtro_negozio.isdigit():
        file_letti = file_letti.filter(negozio_id=int(filtro_negozio))
    return render(request, "primanota/sospesi.html", _contesto(
        request, righe=righe[:2000], riepilogo=riepilogo, stati=STATI_SOSPESI, stato=stato, negozi=negozi,
        filtro_negozio=filtro_negozio, data_da=data_da, data_a=data_a, file_letti=file_letti.count(),
        per_foglio=[1, 2, 4, 6, 8, 9]))


@_accesso(solo_ufficio=True)
def sospeso_scontrini(request, sospeso_id):
    """Il documento sospeso e quello emesso dopo il richiamo, per affiancarli nella pagina."""
    from .services import sospesi as servizio

    s = get_object_or_404(ScontrinoSospeso, pk=sospeso_id)
    dati = servizio.scontrini(s)
    for v in dati.values():
        v["trovato"] = bool(v["testo"])
        v["testo"] = v["testo"] or servizio.NON_TROVATO
    return JsonResponse(dati)


@_accesso()
def sysspy_dettaglio(request, file_id):
    f = get_object_or_404(FileSysSpy, pk=file_id)
    if not _negozio_consentito(request, f.negozio_id):
        raise Http404
    try:
        testo = importazione.leggi_testo(f)
    except OSError:
        testo = "File di testo non trovato nell'archivio."
    return render(request, "primanota/sysspy_dettaglio.html", _contesto(
        request, f=f, testo=testo, negozio_label=etichetta_negozio(negozio(f.negozio_id)) or f.codice_negozio,
        documenti=f.documenti.all()))


@_accesso()
def sysspy_scarica(request, file_id):
    f = get_object_or_404(FileSysSpy, pk=file_id)
    if not _negozio_consentito(request, f.negozio_id):
        raise Http404
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
            cond.percorso_sospesi = request.POST.get("percorso_sospesi", "").strip()
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
        salvato=request.GET.get("salvato") == "1", errore_periodo=request.GET.get("errore_periodo"),
        oggi=timezone.localdate().isoformat(), disco=_stato_disco(request.GET.get("disco") == "aggiorna")))


def _stato_disco(ricalcola):
    from .services import disco
    try:
        return disco.stato(ricalcola)
    except Exception:   # l'indicatore non deve bloccare le impostazioni
        log.exception("Spazio su disco non letto")
        return None


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
def rielabora_periodo(request):
    """
    Rielabora un negozio (o tutti) in un periodo: dall'archivio del portale (veloce, con le regole attuali)
    oppure rileggendo dalle casse i file originali di quei giorni.
    """
    dal, al = _data(request.POST.get("dal")), _data(request.POST.get("al"))
    if not dal or not al or dal > al:
        return redirect("/primanota/condivisioni/?errore_periodo=1")
    periodo = (date.fromisoformat(dal), date.fromisoformat(al))
    negozio_id = int(request.POST["negozio"]) if request.POST.get("negozio", "").isdigit() else None
    n = negozio(negozio_id) if negozio_id else None
    descrizione = f"{n['codice'] if n else 'tutti i negozi'} dal {periodo[0]:%d/%m/%Y} al {periodo[1]:%d/%m/%Y}"
    if request.POST.get("fonte") == "casse":
        if negozio_id:
            cond = Condivisione.objects.filter(negozio_id=negozio_id).exclude(percorso="").first()
            if not cond:
                return redirect("/primanota/condivisioni/?errore_periodo=2")
            lavoro = importazione.avvia_in_background(cond, periodo=periodo)
        else:
            lavoro = importazione.avvia_tutte_in_background(periodo=periodo)
    else:
        lavoro = importazione.avvia_rielaborazione_in_background(negozio_id, periodo, f"rielaborazione {descrizione}")
    return redirect(f"/primanota/importazione/{lavoro}/")


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
@_accesso()
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
    if is_store_user(request.utente_primanota):
        negozio_id = get_user_store_id(request.utente_primanota)   # il negozio stampa solo le proprie
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
    n = negozio(negozio_id) if negozio_id else None
    nome = servizio.nome_file(sezione, etichetta_negozio(n) if n else "", data_da, data_a, contenuto)
    pdf = servizio.genera_pdf(voci, per_pagina=per_pagina, titolo=titolo, nome=nome)
    risposta = HttpResponse(pdf, content_type="application/pdf")
    risposta["Content-Disposition"] = f'inline; filename="{nome}"'
    return risposta


def _solo_sede(view):
    """Versamenti: la sede (ufficio, Direttori, Amministratori)."""
    @wraps(view)
    def interna(request, *args, **kwargs):
        if not can_see_versamenti(request.utente_primanota):
            return HttpResponseForbidden("Sezione riservata alla sede.")
        return view(request, *args, **kwargs)
    return interna


@_accesso(solo_ufficio=True)
@_solo_sede
def versamenti_monitor(request):
    from .services.monitor import build_monitor_versamenti

    vista = request.GET.get("vista", "mese").strip().lower()
    try:
        dati = build_monitor_versamenti(year=request.GET.get("anno"), month=request.GET.get("mese"),
                                        view_mode="week" if vista in {"week", "settimana"} else "month",
                                        week_start=request.GET.get("settimana", "").strip() or None)
        error = None
    except RuntimeError as exc:
        dati, error = None, str(exc)
    return render(request, "primanota/monitor.html", _contesto(request, monitor=dati, error=error, versamenti_monitor=True))


@_accesso(solo_ufficio=True)
@_solo_sede
def versamenti(request):
    """Elenco dei versamenti con scansione, contanti attesi dal SysSpy, note del negozio e flag lavorato."""
    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    data_da = _data(request.GET.get("data_da"), ieri)
    data_a = _data(request.GET.get("data_a"), data_da)
    filtro_negozio = request.GET.get("negozio", "")
    solo_da_lavorare = (not request.GET) or request.GET.get("solo_da_lavorare") == "on"
    error = None
    try:
        scansioni = [s for s in elenco_scansioni(negozio_id=filtro_negozio or None, data_da=data_da, data_a=data_a)
                     if s["versamento"]]
    except RuntimeError as exc:
        scansioni, error = [], str(exc)
    if solo_da_lavorare:
        scansioni = [s for s in scansioni if not s["versamento_lavorato"]]
    negozi = {n["id"]: n for n in negozi_attivi_ordinati()}
    # Contanti attesi per negozio e giorno: somma dei contanti negli scontrini delle casse.
    contanti = {}
    for f in FileSysSpy.objects.filter(data__range=(data_da, data_a)).only("negozio_id", "data", "pagamenti"):
        chiave = (f.negozio_id, f.data.isoformat())
        contanti[chiave] = contanti.get(chiave, Decimal("0")) + Decimal(str((f.pagamenti or {}).get("Contanti", 0)))
    note = {}
    for nota in Nota.objects.filter(versamento=True, scansione_id__in=[s["id"] for s in scansioni]):
        note.setdefault(nota.scansione_id, []).append(nota)
    for s in scansioni:
        s["negozio_label"] = etichetta_negozio(negozi.get(s["negozio_id"])) or s["negozio_id"]
        s["contanti_attesi"] = contanti.get((s["negozio_id"], s["data_documento"]))
        s["note_versamento"] = note.get(s["id"], [])
    scansioni.sort(key=lambda s: (s["data_documento"], str((negozi.get(s["negozio_id"]) or {}).get("codice", ""))),
                   reverse=True)
    return render(request, "primanota/versamenti.html", _contesto(
        request, scansioni=scansioni, negozi=list(negozi.values()), error=error, filtro_negozio=filtro_negozio,
        data_da=data_da, data_a=data_a, solo_da_lavorare=solo_da_lavorare,
        note_da_lavorare=Nota.objects.filter(versamento=True, chiusa=False).count()))


@_accesso(solo_ufficio=True)
@_solo_sede
def versamenti_note(request):
    """Note dei negozi sui versamenti."""
    return _elenco_note(request, versamento=True)


MAX_GIORNI_STATISTICHE = 366


@_accesso(solo_ufficio=True, solo_gestione=True)
def statistiche_menu(request):
    """Statistiche (Direttori e Amministratori): finanziarie, vendite per fasce orarie, buoni pasto per emettitori."""
    if "data_da" in request.GET:   # vecchi collegamenti alle statistiche con i filtri
        return redirect("/primanota/statistiche/finanziarie/?" + request.GET.urlencode())
    return render(request, "primanota/statistiche_menu.html", _contesto(request))


def _statistiche_richieste(request):
    """Periodo e negozio dai filtri; dati None (con l'errore) se il periodo è troppo lungo."""
    from .services.statistiche import calcola

    oggi = timezone.localdate()
    data_a = _data(request.GET.get("data_a"), (oggi - timedelta(days=1)).isoformat())
    data_da = _data(request.GET.get("data_da"), (date.fromisoformat(data_a) - timedelta(days=29)).isoformat())
    filtro_negozio = request.GET.get("negozio", "")
    if date.fromisoformat(data_a) < date.fromisoformat(data_da):
        data_da, data_a = data_a, data_da
    if (date.fromisoformat(data_a) - date.fromisoformat(data_da)).days >= MAX_GIORNI_STATISTICHE:
        return data_da, data_a, filtro_negozio, None, f"Scegliere al massimo {MAX_GIORNI_STATISTICHE} giorni."
    dati = calcola(data_da, data_a, int(filtro_negozio) if filtro_negozio.isdigit() else None)
    return data_da, data_a, filtro_negozio, dati, None


@_accesso(solo_ufficio=True, solo_gestione=True)
def statistiche(request):
    data_da, data_a, filtro_negozio, dati, error = _statistiche_richieste(request)
    return render(request, "primanota/statistiche.html", _contesto(
        request, dati=dati, error=error, data_da=data_da, data_a=data_a, filtro_negozio=filtro_negozio,
        negozi=negozi_attivi_ordinati(),
        grafici={"giorni": dati["giorni"],
                 "negozi": [{"etichetta": r["etichetta"], "valore": float(r["totale"])} for r in dati["negozi"]],
                 "pagamenti": [{"etichetta": r["voce"], "valore": float(r["importo"])} for r in dati["pagamenti"]]}
        if dati else {}))


@xframe_options_sameorigin  # il PDF si apre nella finestra di stampa della pagina stessa
@_accesso(solo_ufficio=True, solo_gestione=True)
def statistiche_pdf(request):
    """Le statistiche in PDF A4, con i tipi di grafico e la vista dell'andamento scelti nella pagina."""
    from .services import statistiche_pdf as servizio

    data_da, data_a, filtro_negozio, dati, error = _statistiche_richieste(request)
    if error:
        return HttpResponse(error, status=400)
    n = negozio(int(filtro_negozio)) if filtro_negozio.isdigit() else None
    etichetta = etichetta_negozio(n) if n else ""
    giorni = dati["giorni"]
    dal, al = _data(request.GET.get("vista_da")), _data(request.GET.get("vista_a"))
    if dal and al:
        giorni = [g for g in giorni if dal <= g["data"] <= al] or giorni
    da, a = date.fromisoformat(data_da), date.fromisoformat(data_a)
    nome = servizio.nome_file(etichetta, data_da, data_a)
    pdf = servizio.genera_pdf(
        dati, titolo="Statistiche finanziarie " + (etichetta or "tutti i negozi"),
        sottotitolo=f"dal {da:%d/%m/%Y} al {a:%d/%m/%Y}", nome=nome, giorni=giorni,
        andamento=request.GET.get("andamento", "linea"), negozi=request.GET.get("grafico_negozi", "barre"),
        pagamenti=request.GET.get("grafico_pagamenti", "barre"))
    risposta = HttpResponse(pdf, content_type="application/pdf")
    risposta["Content-Disposition"] = f'inline; filename="{nome}"'
    return risposta


@xframe_options_sameorigin  # il PDF si apre nella finestra di stampa della pagina stessa
@_accesso(solo_ufficio=True, solo_gestione=True)
def buoni_pasto(request):
    """Buoni pasto per emettitore: incassi per punto vendita e causale (18-25) dal database delle statistiche."""
    from .services import buoni_pasto as servizio

    oggi = timezone.localdate()
    data_da = _data(request.GET.get("data_da"), oggi.replace(day=1).isoformat() if oggi.day > 1
                    else (oggi - timedelta(days=1)).replace(day=1).isoformat())
    data_a = _data(request.GET.get("data_a"), (oggi - timedelta(days=1)).isoformat())
    if data_a < data_da:
        data_da, data_a = data_a, data_da
    negozi = negozi_attivi_ordinati()
    scelti = [p for p in request.GET.getlist("pv") if p.strip()]
    formato = request.GET.get("formato", "")
    risultato = error = None
    if "data_da" in request.GET:   # la query parte solo quando si preme «Cerca»
        try:
            risultato = servizio.riepilogo(servizio.interroga(data_da, data_a, scelti))
        except RuntimeError as exc:
            error = str(exc)
    da, a = date.fromisoformat(data_da), date.fromisoformat(data_a)
    periodo = f"dal {da:%d/%m/%Y} al {a:%d/%m/%Y}"
    nome_pv = {str(n.get("codice")): etichetta_negozio(n) for n in negozi}
    descrizione_pv = ", ".join(nome_pv.get(p, p) for p in scelti) if scelti else "Tutti i punti vendita"
    base_nome = "_".join(re.sub(r"[^\w-]+", "_", t).strip("_") for t in
                         ("Buoni_pasto_per_emettitore", "_".join(scelti) if scelti else "Tutti", f"dal {data_da} al {data_a}"))

    if formato in ("csv", "pdf"):
        if error or risultato is None:
            return HttpResponse(error or "Indicare il periodo.", status=502 if error else 400)
        if formato == "csv":
            risposta = HttpResponse(servizio.csv(risultato), content_type="text/csv; charset=utf-8")
            risposta["Content-Disposition"] = f'attachment; filename="{base_nome}.csv"'
            return risposta
        risposta = HttpResponse(servizio.pdf(risultato, periodo, descrizione_pv, base_nome + ".pdf"),
                                content_type="application/pdf")
        risposta["Content-Disposition"] = f'inline; filename="{base_nome}.pdf"'
        return risposta

    return render(request, "primanota/buoni_pasto.html", _contesto(
        request, risultato=risultato, error=error, data_da=data_da, data_a=data_a, negozi=negozi, scelti=scelti,
        periodo=periodo, descrizione_pv=descrizione_pv, configurato=bool(servizio.configurazione())))


MAX_GIORNI_FASCE = 366


@xframe_options_sameorigin  # il PDF si apre nella finestra di stampa della pagina stessa
@_accesso(solo_ufficio=True, solo_gestione=True)
def fasce_orarie(request):
    """Vendite per fasce orarie, per punto vendita o per reparto (database Statistiche)."""
    from .services import cassa_centrale
    from .services import fasce_orarie as servizio

    oggi = timezone.localdate()
    data_a = _data(request.GET.get("data_a"), (oggi - timedelta(days=1)).isoformat())
    data_da = _data(request.GET.get("data_da"), (date.fromisoformat(data_a) - timedelta(days=6)).isoformat())
    if data_a < data_da:
        data_da, data_a = data_a, data_da
    vista = request.GET.get("vista") if request.GET.get("vista") in servizio.VISTE else "negozi"
    misura = request.GET.get("misura") if request.GET.get("misura") in servizio.MISURE else "valore"
    media = request.GET.get("media") == "1"
    dalle = servizio.minuti(request.GET.get("dalle"), 7 * 60)
    alle = servizio.minuti(request.GET.get("alle"), 22 * 60)
    if alle <= dalle:
        dalle, alle = 0, 24 * 60
    try:
        passo = int(request.GET.get("passo", 15))
    except ValueError:
        passo = 15
    passo = passo if passo in servizio.PASSI else 15
    scelti = [p for p in request.GET.getlist("pv") if p.strip()]
    reparti_scelti = [r for r in request.GET.getlist("reparto") if r.strip()]
    negozi = negozi_attivi_ordinati()
    nome_pv = {str(n.get("codice")): etichetta_negozio(n) for n in negozi}
    risultato = error = None
    formato = request.GET.get("formato", "")
    # La query parte solo con «Cerca» o con la stampa: cambiare vista ricarica solo i filtri (e i reparti).
    if request.GET.get("cerca") or formato in ("csv", "pdf"):
        if (date.fromisoformat(data_a) - date.fromisoformat(data_da)).days >= MAX_GIORNI_FASCE:
            error = f"Scegliere al massimo {MAX_GIORNI_FASCE} giorni."
        else:
            try:
                righe, clienti = servizio.interroga(data_da, data_a, vista, scelti, reparti_scelti if vista == "reparti" else ())
                risultato = servizio.componi(righe, clienti, dalle=dalle, alle=alle, passo=passo)
            except RuntimeError as exc:
                error = str(exc)
    da, a = date.fromisoformat(data_da), date.fromisoformat(data_a)
    periodo = f"dal {da:%d/%m/%Y} al {a:%d/%m/%Y}"
    descrizione = ", ".join(nome_pv.get(p, p) for p in scelti) if scelti else "Tutti i punti vendita"
    titolo = f"Vendite per fasce orarie {servizio.VISTE[vista].lower()}"
    sottotitolo = (f"{periodo} · dalle {servizio.orario(dalle)} alle {servizio.orario(alle)} · fasce di "
                   f"{servizio.PASSI[passo]} · {descrizione} · {servizio.MISURE[misura]}"
                   + (" (media giornaliera)" if media else ""))
    base_nome = "_".join(re.sub(r"[^\w-]+", "_", t).strip("_") for t in
                         ("Fasce_orarie", vista, "_".join(scelti) if scelti else "Tutti", f"dal {data_da} al {data_a}", misura))

    if formato in ("csv", "pdf"):
        if error or risultato is None:
            return HttpResponse(error or "Indicare il periodo.", status=502 if error else 400)
        if formato == "csv":
            risposta = HttpResponse(servizio.csv(risultato, misura, media, vista), content_type="text/csv; charset=utf-8")
            risposta["Content-Disposition"] = f'attachment; filename="{base_nome}.csv"'
            return risposta
        risposta = HttpResponse(servizio.pdf(risultato, misura, media, vista, titolo, sottotitolo, base_nome + ".pdf"),
                                content_type="application/pdf")
        risposta["Content-Disposition"] = f'inline; filename="{base_nome}.pdf"'
        return risposta

    elenco_reparti = []
    if vista == "reparti":
        try:
            elenco_reparti = servizio.elenco_reparti(scelti)
        except RuntimeError as exc:
            error = error or str(exc)
    tab = servizio.tabella(risultato, misura, media) if risultato else None
    return render(request, "primanota/fasce_orarie.html", _contesto(
        request, data_da=data_da, data_a=data_a, vista=vista, misura=misura, media=media, scelti=scelti,
        reparti_scelti=reparti_scelti, negozi=negozi, elenco_reparti=elenco_reparti, risultato=risultato, tab=tab,
        error=error, viste=servizio.VISTE, misure=servizio.MISURE, passi=servizio.PASSI, passo=passo,
        dalle=servizio.orario(dalle), alle=servizio.orario(alle), sottotitolo=sottotitolo, scala=servizio.SCALA,
        scure=servizio.SCURE, configurato=bool(cassa_centrale.configurazione()),
        grafico={"fasce": tab["fasce"], "valori": [float(v) for v in tab["colonne"]]} if tab else {}))


MAX_GIORNI_PRIMA_NOTA = 31


@xframe_options_sameorigin  # il PDF si apre nella finestra di stampa della pagina stessa
@_accesso(solo_ufficio=True)
def prima_nota(request):
    """Consultazione della prima nota (cassa centrale) per punto vendita e giorno; stampa PDF per più PV e giorni."""
    from .services import cassa_centrale
    from .services import prima_nota as servizio

    ieri = (timezone.localdate() - timedelta(days=1)).isoformat()
    negozi = negozi_attivi_ordinati()
    nome_pv = {str(n.get("codice")): etichetta_negozio(n) for n in negozi}

    if request.GET.get("formato") == "pdf":
        from .services.prima_nota_pdf import genera_pdf
        data_da = _data(request.GET.get("dal"), ieri)
        data_a = _data(request.GET.get("al"), data_da)
        if data_a < data_da:
            data_da, data_a = data_a, data_da
        if (date.fromisoformat(data_a) - date.fromisoformat(data_da)).days >= MAX_GIORNI_PRIMA_NOTA:
            return HttpResponse(f"Scegliere al massimo {MAX_GIORNI_PRIMA_NOTA} giorni.", status=400)
        scelti = [p for p in request.GET.getlist("pv") if p.strip()]
        try:
            giornate = servizio.interroga(data_da, data_a, scelti)
        except RuntimeError as exc:
            return HttpResponse(str(exc), status=502)
        for g in giornate:
            g["nome"] = g["nome"] or nome_pv.get(g["pv"], "")
        periodo = data_da if data_da == data_a else f"dal {data_da} al {data_a}"
        nome = "_".join(re.sub(r"[^\w-]+", "_", t).strip("_")
                        for t in ("Prima_nota", "_".join(scelti) if scelti else "Tutti_i_PV", periodo)) + ".pdf"
        risposta = HttpResponse(genera_pdf(giornate, "Prima nota", nome), content_type="application/pdf")
        risposta["Content-Disposition"] = f'inline; filename="{nome}"'
        return risposta

    giorno = _data(request.GET.get("data"), ieri)
    pv = request.GET.get("pv", "").strip()
    giornata = error = None
    cercato = bool(pv) and "data" in request.GET   # la query parte solo con «Cerca»
    if cercato:
        try:
            giornate = servizio.interroga(giorno, giorno, [pv])
            giornata = giornate[0] if giornate else None
        except RuntimeError as exc:
            error = str(exc)
        if giornata:
            giornata["nome"] = giornata["nome"] or nome_pv.get(pv, "")
    corrente = date.fromisoformat(giorno)
    return render(request, "primanota/prima_nota.html", _contesto(
        request, negozi=negozi, giorno=giorno, pv=pv, giornata=giornata, error=error, cercato=cercato, ieri=ieri,
        precedente=(corrente - timedelta(days=1)).isoformat(), successivo=(corrente + timedelta(days=1)).isoformat(),
        nome_pv=nome_pv.get(pv, pv), configurato=bool(cassa_centrale.configurazione()),
        riepilogo=[("Ripresa", giornata["ripresa"]), ("Periodo", giornata["periodo"]),
                   ("Progressivo", giornata["progressivo"])] if giornata else []))


@_accesso(solo_ufficio=True, solo_gestione=True)
def buoni_pasto_collegamento(request):
    """Server, database, utente e password del database dei buoni pasto: solo Direttore e Amministratore."""
    from .models import CollegamentoBuoniPasto
    from .services import cassa_centrale as servizio

    c = CollegamentoBuoniPasto.corrente()
    messaggio = errore = None
    if request.method == "POST":
        c.host = request.POST.get("host", "").strip()
        c.database = request.POST.get("database", "").strip() or "Scontrini"
        c.utente = request.POST.get("utente", "").strip()
        if request.POST.get("password"):   # vuota = resta quella salvata
            c.password_cifrata = importazione.cifra(request.POST["password"])
        if not c.host or not c.utente:
            errore = "Indicare almeno server e utente."
        else:
            c.modificato_da = nome_utente(request.utente_primanota)
            c.modificato_il = timezone.now()
            c.save()
            messaggio = "Collegamento salvato."
            if request.POST.get("azione") == "prova":
                try:
                    servizio.prova(servizio.configurazione())
                    messaggio = "Collegamento salvato e provato: il database risponde."
                except RuntimeError as exc:
                    errore = f"Salvato, ma la prova non è riuscita: {exc}"
                    messaggio = None
    return render(request, "primanota/buoni_pasto_collegamento.html", _contesto(
        request, c=c, messaggio=messaggio, errore=errore))


@_accesso(solo_ufficio=True, solo_gestione=True)
def impostazioni_email(request):
    """Destinatari delle note sui versamenti; la posta è quella configurata nel portale."""
    from .services import posta

    messaggio = errore = None
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "aggiungi":
            nome, email = request.POST.get("nome", "").strip(), request.POST.get("email", "").strip()
            if nome and "@" in email:
                DestinatarioEmail.objects.create(nome=nome, email=email)
            else:
                errore = "Indicare nome ed email del destinatario."
        elif azione == "attiva":
            d = get_object_or_404(DestinatarioEmail, pk=request.POST.get("id"))
            d.attivo = not d.attivo
            d.save()
        elif azione == "elimina":
            DestinatarioEmail.objects.filter(pk=request.POST.get("id")).delete()
        elif azione == "prova":
            try:
                posta.invia([request.POST.get("email", "").strip()], "Prova invio Documenti Amministrativi",
                            "Messaggio di prova dal portale TO.CAL (Documenti Amministrativi).")
                messaggio = "Email di prova inviata."
            except Exception as exc:
                errore = f"Invio non riuscito: {exc}"
    return render(request, "primanota/impostazioni_email.html", _contesto(
        request, posta=posta.stato(), destinatari=DestinatarioEmail.objects.all(), messaggio=messaggio, errore=errore))

