"""
Prelievo dei SysSpy dalle condivisioni dei negozi e archiviazione.

Per ogni file nuovo o modificato:
- copia l'originale in <archivio>/<negozio>/<AAAA>/<MM>/<GG>/cassa_<n>/;
- salva accanto il testo senza le prime 4 colonne (.txt.gz);
- registra nel DB data, cassa, chiusure, valori e documenti particolari.
I file già archiviati con la stessa dimensione e data di modifica si saltano.
"""

import base64
import gzip
import hashlib
import logging
import re
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .. import sysspy
from ..models import DocumentoSysSpy, FileSysSpy

log = logging.getLogger(__name__)

NOME_RE = re.compile(r"^SysSpy\.\d{8}\.\d+$", re.I)

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


def _file_condivisione(cond):
    """(percorso, nome, dimensione, mtime, lettore) per ogni SysSpy della condivisione."""
    percorso = cond.percorso.strip()
    if percorso.startswith("\\\\") or percorso.startswith("//"):
        import smbclient

        server = re.split(r"[\\/]+", percorso.strip("\\/"))[0]
        smbclient.register_session(server, username=cond.utente or None, password=decifra(cond.password_cifrata) or None)
        for radice, _, nomi in smbclient.walk(percorso):
            for nome in nomi:
                if not NOME_RE.match(nome):
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
        for f in radice.rglob("SysSpy.*"):
            if f.is_file() and NOME_RE.match(f.name):
                st = f.stat()
                yield str(f), f.name, st.st_size, st.st_mtime, f.read_bytes


def archivia(cond, origine, nome, dimensione, mtime, dati):
    """Archivia un file già letto. Restituisce il FileSysSpy salvato."""
    a = sysspy.analizza(nome, dati)
    giorno = a["data"]
    cartella = archivio_dir() / cond.codice_negozio
    cartella = cartella / (giorno.strftime("%Y/%m/%d") if giorno else "senza_data") / f"cassa_{a['cassa'] or 0}"
    cartella.mkdir(parents=True, exist_ok=True)
    originale = cartella / nome
    originale.write_bytes(dati)
    testo = cartella / (nome + ".txt.gz")
    with gzip.open(testo, "wt", encoding="utf-8") as fh:
        fh.write(a["testo"])

    v = a["valori_fiscali"]
    pos = a["chiusure_pos"]
    campi = dict(
        codice_negozio=cond.codice_negozio,
        data=giorno,
        cassa=a["cassa"],
        nome_file=nome,
        percorso_archivio=str(originale),
        percorso_testo=str(testo),
        dimensione=dimensione,
        modificato_il=mtime,
        sha256=hashlib.sha256(dati).hexdigest(),
        righe=a["righe"],
        codice_negozio_letto=a["codice_negozio"],
        chiusura_pos="\n\n".join(p["testo"] for p in pos),
        chiusura_fiscale=a["chiusura_fiscale"]["testo"] if a["chiusura_fiscale"] else "",
        totale_pos=a["totale_pos"],
        totale_host=sum((p["totale_host"] for p in pos if p["totale_host"] is not None), start=0) if pos else None,
        totale_giornaliero=v.get("totale_giornaliero"),
        totale_annulli=v.get("totale_annulli"),
        totale_resi=v.get("totale_resi"),
        corrisp_riscosso=v.get("corrisp_riscosso"),
        corrisp_non_riscosso=v.get("corrisp_non_riscosso"),
        num_scontrini_fiscali=v.get("num_scontrini_fiscali"),
        matricola_stampante=v.get("matricola_stampante") or "",
        scontrini_trovati=len(a["scontrini"]),
        totale_scontrini=a["totale_scontrini"],
    )
    with transaction.atomic():
        f, _ = FileSysSpy.objects.update_or_create(
            negozio_id=cond.negozio_id, percorso_origine=origine, defaults=campi)
        f.documenti.all().delete()
        documenti = []
        for s in a["scontrini"]:
            if s["abortito"]:
                tipi = [DocumentoSysSpy.ABORTITO]
            else:
                tipi = ([DocumentoSysSpy.RESO] if s["reso"] else []) \
                    + ([DocumentoSysSpy.STORNO] if s["storni"] else []) \
                    + ([DocumentoSysSpy.ANNULLAMENTO] if s["annullamenti_riga"] else [])
            for tipo in tipi:
                documenti.append(DocumentoSysSpy(
                    file=f, tipo=tipo, numero=s["numero"], ora=s["ora"], importo=s["totale"], testo=s["testo"]))
        for n in a["pos_negate"]:
            documenti.append(DocumentoSysSpy(file=f, tipo=DocumentoSysSpy.POS_NEGATO, ora=n["ora"], testo=n["testo"]))
        DocumentoSysSpy.objects.bulk_create(documenti)
    return f


def importa_condivisione(cond, completa=False, lavoro=None, stop=None):
    """Importa i file nuovi o modificati di una condivisione. completa=True rilegge tutto."""
    stato = lavoro if lavoro is not None else {}
    stato.update(stato="in corso", esaminati=0, importati=0, saltati=0, errori=0, messaggio="")
    with _lock_globale:
        lock = _lock_negozi.setdefault(cond.negozio_id, threading.Lock())
    if not lock.acquire(blocking=False):
        stato.update(stato="errore", messaggio="Importazione già in corso per questo negozio")
        return stato
    try:
        noti = {} if completa else {
            o: (d, m) for o, d, m in FileSysSpy.objects.filter(negozio_id=cond.negozio_id)
            .values_list("percorso_origine", "dimensione", "modificato_il")}
        for origine, nome, dimensione, mtime, leggi in _file_condivisione(cond):
            if stop is not None and stop.is_set():
                break
            stato["esaminati"] += 1
            if noti.get(origine) == (dimensione, mtime):
                stato["saltati"] += 1
                continue
            try:
                archivia(cond, origine, nome, dimensione, mtime, leggi())
                stato["importati"] += 1
            except Exception as exc:  # un file illeggibile non blocca gli altri
                log.exception("Errore archiviando %s", origine)
                stato["errori"] += 1
                stato["messaggio"] = f"{nome}: {exc}"
        stato["stato"] = "interrotta" if stop is not None and stop.is_set() else "completata"
    except Exception as exc:
        log.exception("Importazione negozio %s fallita", cond.codice_negozio)
        stato.update(stato="errore", messaggio=str(exc))
    finally:
        lock.release()
    cond.ultima_importazione = timezone.now()
    cond.ultimo_esito = (f"{stato['stato']}: {stato['importati']} importati, {stato['saltati']} già presenti, "
                         f"{stato['errori']} errori. {stato['messaggio']}").strip()
    cond.save(update_fields=["ultima_importazione", "ultimo_esito"])
    return stato


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


def leggi_testo(f):
    with gzip.open(f.percorso_testo, "rt", encoding="utf-8") as fh:
        return fh.read()
