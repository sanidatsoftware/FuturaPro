"""
Prelievo dei SysSpy dalle condivisioni dei negozi e archiviazione.

Per ogni file nuovo o modificato:
- copia l'originale in <archivio>/<negozio>/<AAAA>/<MM>/<GG>/cassa_<n>/;
- salva accanto il testo senza le prime 4 colonne (.txt.gz);
- registra nel DB data, cassa, chiusure, valori e documenti particolari.
I file già archiviati con la stessa dimensione e data di modifica si saltano.
"""

import base64
import fcntl
import gzip
import hashlib
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .. import sr_file, sri, sysspy
from ..models import Condivisione, DocumentoSysSpy, FileSR, FileSRI, FileSysSpy, Pianificazione, ScontrinoSospeso

log = logging.getLogger(__name__)

NOME_RE = re.compile(r"^SysSpy\.\d{8}\.\d+$", re.I)


def _da_leggere(nome):
    """I file della condivisione che interessano: SysSpy e scontrini sospesi (CPaammgg.SRI.CassaN)."""
    return bool(NOME_RE.match(nome) or sri.NOME_RE.match(nome))

_lock_negozi = {}
_lock_globale = threading.Lock()
# Stato delle importazioni avviate dal portale, per la pagina di avanzamento.
LAVORI = {}


def archivio_dir():
    return Path(getattr(settings, "PRIMANOTA_ARCHIVIO_DIR", Path(settings.BASE_DIR) / "primanota_archivio"))


def _fernet():
    chiave = hashlib.sha256(("primanota:" + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(chiave))


def cifra(valore):
    return _fernet().encrypt(valore.encode()).decode() if valore else ""


def decifra(valore):
    if not valore:
        return ""
    try:
        return _fernet().decrypt(valore.encode()).decode()
    except InvalidToken:
        log.warning("Password della condivisione illeggibile (SECRET_KEY cambiata?): reinserirla.")
        return ""


def _file_condivisione(cond, percorso=None, accetta=None):
    """
    (percorso, nome, dimensione, mtime, lettore) per ogni SysSpy e file dei sospesi della condivisione,
    oppure, con percorso e accetta, per i file di un'altra cartella (stesse credenziali).
    """
    percorso = (percorso or cond.percorso).strip()
    accetta = accetta or _da_leggere
    if percorso.startswith("\\\\") or percorso.startswith("//"):
        import smbclient

        server = re.split(r"[\\/]+", percorso.strip("\\/"))[0]
        smbclient.register_session(server, username=cond.utente or None, password=decifra(cond.password_cifrata) or None)
        for radice, _, nomi in smbclient.walk(percorso):
            for nome in nomi:
                if not accetta(nome):
                    continue
                completo = radice.rstrip("\\/") + "\\" + nome
                st = smbclient.stat(completo)

                def leggi(p=completo):
                    with smbclient.open_file(p, "rb") as fh:
                        return fh.read()

                yield completo, nome, st.st_size, st.st_mtime, leggi
    else:
        radice = Path(percorso)
        if not radice.is_dir():
            raise RuntimeError(f"Percorso non raggiungibile: {percorso}")
        for f in radice.rglob("*"):
            if f.is_file() and accetta(f.name):
                st = f.stat()
                yield str(f), f.name, st.st_size, st.st_mtime, f.read_bytes


def _analizza_archiviato(percorso, nome):
    """Per la rielaborazione in parallelo: legge e analizza un originale già archiviato."""
    dati = Path(percorso).read_bytes()
    return sysspy.analizza(nome, dati), hashlib.sha256(dati).hexdigest()


def archivia(cond, origine, nome, dimensione, mtime, dati=None, analisi=None, sha=None, originale=None):
    """
    Archivia un file: l'originale una volta sola, poi una riga per ogni giornata contenuta
    nel file (con il suo testo pulito). Restituisce le righe salvate. Nella rielaborazione
    si passano l'analisi già fatta e il percorso dell'originale, che non si riscrive.
    """
    a = analisi or sysspy.analizza(nome, dati)
    data_file = a["data_file"]
    if originale is None:
        cartella = archivio_dir() / cond.codice_negozio
        cartella = cartella / (data_file.strftime("%Y/%m/%d") if data_file else "senza_data") / f"cassa_{a['cassa'] or 0}"
        cartella.mkdir(parents=True, exist_ok=True)
        originale = cartella / nome
        if not originale.exists() or originale.read_bytes() != dati:
            originale.write_bytes(dati)
    originale = Path(originale)
    cartella = originale.parent
    sha = sha or hashlib.sha256(dati).hexdigest()

    salvati = []
    with transaction.atomic():
        # Le giornate di una lettura precedente dello stesso file si rifanno da capo.
        FileSysSpy.objects.filter(negozio_id=cond.negozio_id, percorso_origine=origine).delete()
        for g in a["giornate"]:
            giorno = g["data"]
            suffisso = "" if giorno == data_file else f".{giorno:%Y%m%d}"
            testo = cartella / f"{nome}{suffisso}.txt.gz"
            # Compressione leggera: il testo compresso resta piccolo e si scrive molto più in fretta.
            with gzip.open(testo, "wt", encoding="utf-8", compresslevel=3) as fh:
                fh.write(g["testo"])
            v = g["valori_fiscali"]
            pos = g["chiusure_pos"]
            f = FileSysSpy.objects.create(
                negozio_id=cond.negozio_id,
                percorso_origine=origine,
                codice_negozio=cond.codice_negozio,
                data=giorno,
                data_file=data_file,
                cassa=a["cassa"],
                nome_file=nome,
                percorso_archivio=str(originale),
                percorso_testo=str(testo),
                dimensione=dimensione,
                modificato_il=mtime,
                sha256=sha,
                righe=g["righe"],
                codice_negozio_letto=a["codice_negozio"],
                chiusura_pos="\n\n".join(p["testo"] for p in pos),
                chiusura_fiscale=g["chiusura_fiscale"]["testo"] if g["chiusura_fiscale"] else "",
                totale_pos=g["totale_pos"],
                totale_host=sum((p["totale_host"] for p in pos if p["totale_host"] is not None), start=0) if pos else None,
                totale_giornaliero=v.get("totale_giornaliero"),
                totale_annulli=v.get("totale_annulli"),
                totale_resi=v.get("totale_resi"),
                corrisp_riscosso=v.get("corrisp_riscosso"),
                corrisp_non_riscosso=v.get("corrisp_non_riscosso"),
                num_scontrini_fiscali=v.get("num_scontrini_fiscali"),
                matricola_stampante=v.get("matricola_stampante") or "",
                scontrini_trovati=len(g["scontrini"]),
                totale_scontrini=g["totale_scontrini"],
                pagamenti={k: str(val) for k, val in g["pagamenti"].items()},
                versione_analisi=sysspy.VERSIONE_ANALISI,
                # [numero, ora, totale, pagato POS, abortito, cassiere, reso, correzioni (n), correzioni (€)]
                elenco_scontrini=[
                    [d["numero"], d["ora"], str(d["totale"]) if d["totale"] is not None else None,
                     str(sum((v for k, v in d["pagamenti"].items() if k in sysspy.PAGAMENTI_POS), start=0)),
                     d["abortito"], d["cassiere"], d["reso"], d["storni"] + d["annullamenti_riga"], str(d["correzioni"])]
                    for d in g["scontrini"]],
                cassieri=a["cassieri"],
            )
            documenti = []
            for d in g["scontrini"]:
                if d["abortito"]:
                    tipi = [DocumentoSysSpy.ABORTITO]
                else:
                    tipi = ([DocumentoSysSpy.RESO] if d["reso"] else []) \
                        + ([DocumentoSysSpy.STORNO] if d["storni"] else []) \
                        + ([DocumentoSysSpy.ANNULLAMENTO] if d["annullamenti_riga"] else [])
                for tipo in tipi:
                    documenti.append(DocumentoSysSpy(
                        file=f, tipo=tipo, numero=d["numero"], ora=d["ora"], importo=d["totale"], testo=d["testo"]))
            for n in g["pos_negate"]:
                documenti.append(DocumentoSysSpy(file=f, tipo=DocumentoSysSpy.POS_NEGATO, ora=n["ora"], testo=n["testo"]))
            DocumentoSysSpy.objects.bulk_create(documenti)
            salvati.append(f)
    return salvati


def rielabora_archivio(negozio_id=None, scrivi=None, stato=None, stop=None, processi=None):
    """
    Rilegge i SysSpy già archiviati (senza andare sulle condivisioni) con le regole attuali.
    Lavora solo sui file analizzati con una versione precedente: se viene interrotta,
    alla ripartenza continua da dove era arrivata. L'analisi gira su più processi.
    """
    from concurrent.futures import ProcessPoolExecutor

    righe = (FileSysSpy.objects.filter(versione_analisi__lt=sysspy.VERSIONE_ANALISI)
             .order_by("negozio_id", "percorso_origine")
             .values("negozio_id", "percorso_origine", "percorso_archivio", "nome_file", "dimensione",
                     "modificato_il", "codice_negozio"))
    if negozio_id:
        righe = righe.filter(negozio_id=negozio_id)
    da_fare, visti = [], set()
    for f in righe:
        if (f["negozio_id"], f["percorso_origine"]) not in visti:
            visti.add((f["negozio_id"], f["percorso_origine"]))
            da_fare.append(f)
    stato = stato if stato is not None else {}
    stato.update(totale=len(da_fare), fatti=0, errori=0)
    condivisioni = {c.negozio_id: c for c in Condivisione.objects.all()}
    inizio = time.monotonic()
    processi = processi or max(1, min(4, (os.cpu_count() or 2) - 1))
    if scrivi:
        scrivi(f"File da rielaborare: {len(da_fare)} (con {processi} processi)")

    with ProcessPoolExecutor(max_workers=processi) as pool:
        # Si mandano ai processi blocchi di file e si salvano man mano nel DB (un solo scrittore).
        for blocco in range(0, len(da_fare), 200):
            if stop is not None and stop.is_set():
                break
            gruppo = da_fare[blocco:blocco + 200]
            futuri = [pool.submit(_analizza_archiviato, f["percorso_archivio"], f["nome_file"]) for f in gruppo]
            for f, futuro in zip(gruppo, futuri):
                cond = condivisioni.get(f["negozio_id"]) or Condivisione(
                    negozio_id=f["negozio_id"], codice_negozio=f["codice_negozio"])
                try:
                    analisi, sha = futuro.result()
                    archivia(cond, f["percorso_origine"], f["nome_file"], f["dimensione"], f["modificato_il"],
                             analisi=analisi, sha=sha, originale=f["percorso_archivio"])
                    stato["fatti"] += 1
                except Exception as exc:
                    log.exception("Rielaborazione di %s", f["percorso_archivio"])
                    stato["errori"] += 1
                    if scrivi:
                        scrivi(f"{f['percorso_archivio']}: {exc}")
            fatti = stato["fatti"] + stato["errori"]
            if scrivi and fatti:
                trascorsi = time.monotonic() - inizio
                mancano = trascorsi / fatti * (len(da_fare) - fatti)
                scrivi(f"{fatti} di {len(da_fare)} file, mancano circa {int(mancano // 60)} minuti")
    return {"file": stato["fatti"], "errori": stato["errori"]}


@contextmanager
def _blocco_negozio(negozio_id):
    """
    Un solo import per negozio alla volta, sia tra i thread del portale sia tra il
    portale e il comando lanciato dal crontab (lock su file). Restituisce False se occupato.
    """
    with _lock_globale:
        lock = _lock_negozi.setdefault(negozio_id, threading.Lock())
    if not lock.acquire(blocking=False):
        yield False
        return
    try:
        archivio_dir().mkdir(parents=True, exist_ok=True)
        with open(archivio_dir() / f".importazione_{negozio_id}.lock", "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
            yield True
    finally:
        lock.release()


def importa_condivisione(cond, completa=False, lavoro=None, stop=None):
    """Importa i file nuovi o modificati di una condivisione. completa=True rilegge tutto."""
    stato = lavoro if lavoro is not None else {}
    stato.update(stato="in corso", esaminati=0, importati=0, saltati=0, errori=0, messaggio="")
    with _blocco_negozio(cond.negozio_id) as libero:
        if not libero:
            stato.update(stato="errore", messaggio="Importazione già in corso per questo negozio")
            return stato
        _importa(cond, completa, stato, stop)
    cond.ultima_importazione = timezone.now()
    cond.ultimo_esito = (f"{stato['stato']}: {stato['importati']} importati, {stato['saltati']} già presenti, "
                         f"{stato['errori']} errori. {stato['messaggio']}").strip()
    if stato.get("sospesi_sr"):
        cond.ultimo_esito += f" · {stato['sospesi_sr']}"
    cond.save(update_fields=["ultima_importazione", "ultimo_esito"])
    return stato


def archivia_sri(cond, origine, nome, dimensione, mtime, dati):
    """
    Salva il file dei sospesi e aggiorna gli scontrini: la sospensione crea lo scontrino, il richiamo e
    la FINE RISTAMPA (emissione fiscale) lo completano, anche se arrivano dal file di un altro giorno o cassa.
    Rileggere lo stesso file non cambia niente.
    """
    a = sri.analizza(nome, dati)
    with transaction.atomic():
        FileSRI.objects.update_or_create(
            negozio_id=cond.negozio_id, percorso_origine=origine,
            defaults={"codice_negozio": cond.codice_negozio, "nome": nome, "data": a["data_file"], "cassa": a["cassa"],
                      "dimensione": dimensione, "modificato_il": mtime, "testo": a["testo"],
                      "righe_non_lette": a["non_lette"]})
        for e in a["eventi"]:
            s, _ = ScontrinoSospeso.objects.get_or_create(
                negozio_id=cond.negozio_id, identificativo=e["id"], defaults={"codice_negozio": cond.codice_negozio})
            if e["tipo"] == "sospeso":
                s.cassa, s.data, s.ora, s.numero, s.importo = e["cassa"], e["data"], e["ora"], e["numero"], e["importo"]
            elif e["tipo"] == "richiamato":
                s.richiamato_data, s.richiamato_ora, s.cassa_richiamo = e["data"], e["ora"], e["cassa"]
            else:
                s.emesso_data, s.emesso_ora, s.cassa_emissione = e["data"], e["ora"], e["cassa"]
                s.numero_emesso, s.importo_emesso = e["numero"], e["importo"]
            if s.data is None:   # richiamo letto prima della sospensione: data dall'identificativo
                s.data = sri.data_sospensione(e["id"], e["data"])
            s.save()
    return a


def importa_file_sr(cond, completa=False):
    """
    Legge la cartella dei file SR (scontrini sospesi ancora in cassa, .RICH se richiamati), ne archivia
    una copia, segna quelli spariti e aggiorna lo stato «in cassa» dei sospesi. Restituisce un messaggio.
    """
    from django.utils import timezone

    if not cond.percorso_sospesi.strip():
        return ""
    adesso = timezone.now()
    noti = {f.identificativo: f for f in FileSR.objects.filter(negozio_id=cond.negozio_id)}
    # Un file per identificativo: se per un momento ci sono sia «SR…289» sia «SR…289.RICH», vale il .RICH.
    per_ident = {}
    for voce in _file_condivisione(cond, cond.percorso_sospesi, sr_file.nome_valido):
        ident, richiamato = sr_file.identificativo(voce[1])
        if ident not in per_ident or richiamato:
            per_ident[ident] = voce
    visti, nuovi = set(per_ident), 0
    for ident, (origine, nome, dimensione, mtime, leggi) in per_ident.items():
        richiamato = sr_file.identificativo(nome)[1]
        f = noti.get(ident)
        if f and not completa and (f.dimensione, f.modificato_il, f.richiamato, f.presente) == (dimensione, mtime, richiamato, True):
            continue
        dati = leggi()
        a = sr_file.analizza(nome, dati)
        cartella = archivio_dir() / cond.codice_negozio / "sospesi_sr"
        cartella.mkdir(parents=True, exist_ok=True)
        copia = cartella / ident
        copia.write_bytes(dati)
        FileSR.objects.update_or_create(negozio_id=cond.negozio_id, identificativo=ident, defaults={
            "codice_negozio": cond.codice_negozio, "nome": nome, "richiamato": richiamato, "presente": True,
            "dimensione": dimensione, "modificato_il": mtime, "percorso_archivio": str(copia),
            "articoli": a["articoli"], "totale_lordo": a["totale_lordo"], "visto_il": adesso, "scomparso_il": None})
        nuovi += 1
    # Quelli che la cassa ha cancellato restano nell'archivio, segnati come non più presenti.
    spariti = FileSR.objects.filter(negozio_id=cond.negozio_id, presente=True).exclude(identificativo__in=visti)
    n_spariti = spariti.update(presente=False, scomparso_il=adesso)
    # Stato «in cassa» dei sospesi, per identificativo (è lo stesso del file SRI).
    stati = {f.identificativo: f.stato_in_cassa for f in FileSR.objects.filter(negozio_id=cond.negozio_id)}
    for s in ScontrinoSospeso.objects.filter(negozio_id=cond.negozio_id, identificativo__in=list(stati)):
        if s.in_cassa != stati[s.identificativo]:
            s.in_cassa = stati[s.identificativo]
            s.save(update_fields=["in_cassa"])
    return f"file SR: {len(visti)} in cassa, {nuovi} aggiornati, {n_spariti} non più presenti"


def _importa(cond, completa, stato, stop):
    try:
        noti = {} if completa else {
            o: (d, m) for o, d, m in FileSysSpy.objects.filter(negozio_id=cond.negozio_id)
            .values_list("percorso_origine", "dimensione", "modificato_il")}
        if not completa:
            noti.update({o: (d, m) for o, d, m in FileSRI.objects.filter(negozio_id=cond.negozio_id)
                         .values_list("percorso_origine", "dimensione", "modificato_il")})
        giorni_letti = set()
        for origine, nome, dimensione, mtime, leggi in _file_condivisione(cond):
            if stop is not None and stop.is_set():
                break
            stato["esaminati"] += 1
            if noti.get(origine) == (dimensione, mtime):
                stato["saltati"] += 1
                continue
            try:
                if sri.NOME_RE.match(nome):
                    giorni_letti.add(archivia_sri(cond, origine, nome, dimensione, mtime, leggi())["data_file"])
                else:
                    giorni_letti.update(f.data for f in archivia(cond, origine, nome, dimensione, mtime, leggi()))
                stato["importati"] += 1
            except Exception as exc:  # un file illeggibile non blocca gli altri
                log.exception("Errore archiviando %s", origine)
                stato["errori"] += 1
                stato["messaggio"] = f"{nome}: {exc}"
        stato["stato"] = "interrotta" if stop is not None and stop.is_set() else "completata"
        giorni_letti.discard(None)
        if cond.percorso_sospesi.strip() and not (stop is not None and stop.is_set()):
            try:
                stato["sospesi_sr"] = importa_file_sr(cond, completa)
            except Exception as exc:  # la cartella dei sospesi non deve bloccare i SysSpy
                log.exception("File SR del negozio %s non letti", cond.codice_negozio)
                stato["sospesi_sr"] = f"file SR non letti: {exc}"
        if stato["stato"] == "completata" and giorni_letti:
            # Sospesi senza richiamo: si cercano gli scontrini ribattuti a mano nei file appena letti
            # (dal giorno prima del più vecchio: il ribattuto può essere del giorno dopo la sospensione).
            from .sospesi import abbina_ribattuti
            try:
                abbina_ribattuti(cond.negozio_id, dal=min(giorni_letti) - timedelta(days=1))
            except Exception:  # l'abbinamento non deve far fallire l'importazione
                log.exception("Abbinamento dei ribattuti del negozio %s non riuscito", cond.codice_negozio)
    except Exception as exc:
        log.exception("Importazione negozio %s fallita", cond.codice_negozio)
        stato.update(stato="errore", messaggio=str(exc))


def importa_tutte(completa=False, lavoro=None, stop=None, scrivi=None):
    """Tutti i negozi con una condivisione attiva, uno dopo l'altro."""
    stato = lavoro if lavoro is not None else {}
    condivisioni = list(Condivisione.objects.filter(attiva=True).exclude(percorso=""))
    stato.update(stato="in corso", negozi=len(condivisioni), negozi_fatti=0, negozio_corrente="",
                 esaminati=0, importati=0, saltati=0, errori=0, messaggio="", esiti=[])
    for cond in condivisioni:
        if stop is not None and stop.is_set():
            break
        stato["negozio_corrente"] = cond.codice_negozio
        parziale = importa_condivisione(cond, completa, stop=stop)
        for k in ("esaminati", "importati", "saltati", "errori"):
            stato[k] += parziale[k]
        stato["esiti"].append(f"{cond.codice_negozio}: {cond.ultimo_esito}")
        stato["negozi_fatti"] += 1
        if scrivi:
            scrivi(f"{cond.codice_negozio}: {cond.ultimo_esito}")
    stato["negozio_corrente"] = ""
    stato["stato"] = "interrotta" if stop is not None and stop.is_set() else "completata"
    stato["messaggio"] = (f"{stato['negozi_fatti']} negozi: {stato['importati']} file importati, "
                          f"{stato['saltati']} già presenti, {stato['errori']} errori")
    return stato


def _ultimo_orario_passato(adesso, orari):
    """Il più recente tra gli orari (ore, minuti) di oggi e di ieri già passati."""
    candidati = []
    for giorni_fa in (0, 1):
        giorno = (adesso - timedelta(days=giorni_fa)).date()
        for ore, minuti in orari:
            momento = datetime.combine(giorno, datetime.min.time(), adesso.tzinfo).replace(hour=ore, minute=minuti)
            if momento <= adesso:
                candidati.append(momento)
    return max(candidati) if candidati else None


def esegui_pianificazione(adesso=None, scrivi=None):
    """
    Chiamata dal crontab ogni pochi minuti. Esegue l'importazione (o la ricostruzione
    settimanale) se è passato un orario non ancora eseguito. Restituisce cosa ha fatto.
    """
    from scansioni.services.baserow_scansioni import LOCAL_TZ

    piano = Pianificazione.corrente()
    if not piano.attiva:
        return "pianificazione disattivata"
    adesso = adesso or datetime.now(LOCAL_TZ)
    completa = False
    if piano.ricostruzione_attiva:
        ore, minuti = (int(x) for x in piano.ricostruzione_ora.split(":"))
        giorno = adesso.date() - timedelta(days=(adesso.weekday() - piano.ricostruzione_giorno) % 7)
        momento = datetime.combine(giorno, datetime.min.time(), adesso.tzinfo).replace(hour=ore, minute=minuti)
        if momento > adesso:
            momento -= timedelta(days=7)
        # Si recupera al massimo entro un giorno: una ricostruzione persa non parte giorni dopo.
        if adesso - momento < timedelta(days=1) and (not piano.ultima_ricostruzione or piano.ultima_ricostruzione < momento):
            completa = True
    if not completa:
        momento = _ultimo_orario_passato(adesso, piano.elenco_orari())
        if not momento or (piano.ultima_importazione and piano.ultima_importazione >= momento):
            return "niente da fare"
    stato = importa_tutte(completa=completa, scrivi=scrivi)
    if completa:
        piano.ultima_ricostruzione = adesso
    piano.ultima_importazione = adesso
    piano.ultimo_esito = f"{adesso:%d/%m/%Y %H:%M} {'ricostruzione' if completa else 'importazione'}: {stato['messaggio']}"
    piano.save()
    return piano.ultimo_esito


def avvia_in_background(cond, completa=False):
    """Avvia l'importazione in un thread e restituisce l'id per seguirne l'avanzamento."""
    lavoro_id = f"{cond.negozio_id}-{int(timezone.now().timestamp())}"
    stop = threading.Event()
    LAVORI[lavoro_id] = {"stato": "in corso", "negozio": cond.codice_negozio, "_stop": stop}

    def esegui():
        try:
            importa_condivisione(cond, completa, LAVORI[lavoro_id], stop)
        finally:
            close_old_connections()

    threading.Thread(target=esegui, daemon=True).start()
    return lavoro_id


def avvia_tutte_in_background(completa=False):
    """Importa o ricostruisce tutti i negozi in un thread; restituisce l'id del lavoro."""
    lavoro_id = f"tutti-{int(timezone.now().timestamp())}"
    stop = threading.Event()
    LAVORI[lavoro_id] = {"stato": "in corso", "negozio": "tutti i negozi", "_stop": stop}

    def esegui():
        try:
            importa_tutte(completa, LAVORI[lavoro_id], stop)
        finally:
            close_old_connections()

    threading.Thread(target=esegui, daemon=True).start()
    return lavoro_id


@contextmanager
def blocco_rielaborazione():
    """Una sola rielaborazione alla volta (comando, installazione o pulsante del portale)."""
    archivio_dir().mkdir(parents=True, exist_ok=True)
    with open(archivio_dir() / ".rielaborazione.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


def avvia_rielaborazione_in_background():
    lavoro_id = f"rielabora-{int(timezone.now().timestamp())}"
    stop = threading.Event()
    stato = LAVORI[lavoro_id] = {"stato": "in corso", "negozio": "archivio (rielaborazione)", "_stop": stop}

    def esegui():
        try:
            with blocco_rielaborazione() as libero:
                if not libero:
                    stato.update(stato="errore", messaggio="Rielaborazione già in corso (comando o installazione)")
                    return
                # Nel portale un solo processo: il comando da terminale usa più processi ed è più veloce.
                esito = rielabora_archivio(stato=stato, stop=stop, processi=1,
                                           scrivi=lambda t: stato.update(messaggio=t))
                stato.update(stato="interrotta" if stop.is_set() else "completata", importati=esito["file"],
                             errori=esito["errori"])
        except Exception as exc:
            stato.update(stato="errore", messaggio=str(exc))
        finally:
            close_old_connections()

    threading.Thread(target=esegui, daemon=True).start()
    return lavoro_id


def leggi_testo(f):
    with gzip.open(f.percorso_testo, "rt", encoding="utf-8") as fh:
        return fh.read()
