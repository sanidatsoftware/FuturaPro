"""
Il contenuto degli scontrini sospesi e di quelli emessi dopo il richiamo, dai SysSpy archiviati.

Nel file SRI «Sct» è il numero del documento della cassa in quel giorno: lo scontrino sospeso è
il documento DOC.zzzz-NNNN (stampato con «SOSPENSIONE SCONTRINO», «OPERAZIONE ABORTITA»), quello
emesso dopo il richiamo è il documento con il numero della riga FINE RISTAMPA.
"""

import re
from functools import lru_cache
from pathlib import Path

from .. import sysspy
from ..models import DocumentoSysSpy, FileSysSpy

DATA_DOC_RE = re.compile(r"(\d{2}/\d{2}/\d{4}) \d{2}:\d{2}\s+DOC\.(\S+)")


@lru_cache(maxsize=32)
def _documenti_del_file(percorso, _modificato):
    """{(«gg/mm/aaaa», numero documento): testo} di tutti i documenti di un SysSpy archiviato."""
    elenco = sysspy.righe(Path(percorso).read_bytes())
    out = {}
    for d in sysspy.scontrini(elenco):
        m = DATA_DOC_RE.search(d["testo"].splitlines()[-1] if d["testo"] else "")
        if m:
            out[(m.group(1), m.group(2))] = d["testo"]
    return out


def _numero_coincide(numero_doc, numero):
    return str(numero_doc).rsplit("-", 1)[-1].lstrip("0") == str(int(numero))


def testo_scontrino(negozio_id, giorno, cassa, numero):
    """Testo del documento numero «numero» della cassa nel giorno; None se il SysSpy non c'è o non lo contiene."""
    if not (giorno and cassa and numero):
        return None
    for d in DocumentoSysSpy.objects.filter(file__negozio_id=negozio_id, file__data=giorno, file__cassa=cassa):
        if _numero_coincide(d.numero, numero):
            return d.testo
    data = giorno.strftime("%d/%m/%Y")
    for f in FileSysSpy.objects.filter(negozio_id=negozio_id, data=giorno, cassa=cassa).only("percorso_archivio"):
        percorso = Path(f.percorso_archivio)
        if not percorso.is_file():
            continue
        for (data_doc, numero_doc), testo in _documenti_del_file(str(percorso), percorso.stat().st_mtime).items():
            if data_doc == data and _numero_coincide(numero_doc, numero):
                return testo
    return None


def scontrini(s):
    """Il documento sospeso e (se c'è) quello emesso dopo il richiamo, con didascalia e testo."""
    out = {"sospeso": {"titolo": f"Sospeso · cassa {s.cassa} · documento {s.numero} · {s.data:%d/%m/%Y} {s.ora:%H:%M}"
                                 if s.data and s.ora else "Sospeso",
                       "testo": testo_scontrino(s.negozio_id, s.data, s.cassa, s.numero)}}
    if s.emesso_data:
        out["emesso"] = {"titolo": f"Emesso · cassa {s.cassa_emissione} · scontrino {s.numero_emesso} · "
                                   f"{s.emesso_data:%d/%m/%Y} {s.emesso_ora:%H:%M}",
                         "testo": testo_scontrino(s.negozio_id, s.emesso_data, s.cassa_emissione, s.numero_emesso)}
    return out


NON_TROVATO = ("Scontrino non trovato nel SysSpy archiviato:\nil file di quella cassa e di quel giorno non è ancora\n"
               "stato importato, oppure il numero non corrisponde.")


def cassieri(sospesi):
    """
    Nome del cassiere di ogni scontrino sospeso e di quello emesso dopo il richiamo, dai SysSpy archiviati:
    {id: (cassiere sospensione, cassiere emissione)}. Gli scontrini fiscali hanno «CASSIERE nnn»; quello
    sospeso no, ma stampa il nome del cassiere: si cerca quello, altrimenti si prende il cassiere dello
    scontrino precedente della stessa cassa (indicato con «?»).
    """
    from django.db.models import Q

    chiavi = set()
    for s in sospesi:
        chiavi.add((s.negozio_id, s.data, s.cassa))
        if s.emesso_data:
            chiavi.add((s.negozio_id, s.emesso_data, s.cassa_emissione))
    chiavi = [k for k in chiavi if all(k)]
    per_file = {}   # (negozio, giorno, cassa) → {"ordine": [(numero, codice)], "nomi": {codice: nome}, "testi": {numero: testo}}
    for i in range(0, len(chiavi), 200):   # a blocchi, per non fare query troppo lunghe
        filtro = Q()
        for negozio_id, giorno, cassa in chiavi[i:i + 200]:
            filtro |= Q(negozio_id=negozio_id, data=giorno, cassa=cassa)
        files = list(FileSysSpy.objects.filter(filtro).only("id", "negozio_id", "data", "cassa", "elenco_scontrini", "cassieri"))
        for f in files:
            dati = per_file.setdefault((f.negozio_id, f.data, f.cassa), {"ordine": [], "nomi": {}, "testi": {}})
            dati["nomi"].update(f.cassieri or {})
            for riga in f.elenco_scontrini or []:
                dati["ordine"].append((_numero(riga[0]), riga[5] if len(riga) > 5 else ""))
        chiave_file = {f.id: (f.negozio_id, f.data, f.cassa) for f in files}
        for d in DocumentoSysSpy.objects.filter(file_id__in=chiave_file).only("file_id", "numero", "testo"):
            per_file[chiave_file[d.file_id]]["testi"][_numero(d.numero)] = d.testo

    def nome(negozio_id, giorno, cassa, numero):
        dati = per_file.get((negozio_id, giorno, cassa))
        if not dati or not numero:
            return ""
        numero = str(numero).lstrip("0")
        codici = dict(dati["ordine"])
        if codici.get(numero):
            return dati["nomi"].get(codici[numero]) or f"Cassiere {codici[numero]}"
        righe_testo = {r.strip().upper() for r in dati["testi"].get(numero, "").splitlines()}
        for codice, nome_cassiere in dati["nomi"].items():
            if nome_cassiere and nome_cassiere.strip().upper() in righe_testo:
                return nome_cassiere
        if numero not in codici:
            return ""
        precedente = ""
        for n, codice in dati["ordine"]:
            if n == numero:
                break
            precedente = codice or precedente
        return f"{dati['nomi'].get(precedente) or f'Cassiere {precedente}'} ?" if precedente else ""

    return {s.id: (nome(s.negozio_id, s.data, s.cassa, s.numero),
                   nome(s.negozio_id, s.emesso_data, s.cassa_emissione, s.numero_emesso)) for s in sospesi}


def _numero(numero_doc):
    """«1107-0081» → «81»."""
    return str(numero_doc).rsplit("-", 1)[-1].lstrip("0")
