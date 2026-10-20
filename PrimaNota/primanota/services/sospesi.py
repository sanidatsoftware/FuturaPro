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

@lru_cache(maxsize=64)
def _documenti_del_file(percorso, _modificato):
    """{(«gg/mm/aaaa», numero documento): documento} di tutti i documenti di un SysSpy archiviato."""
    elenco = sysspy.righe(Path(percorso).read_bytes())
    return {(d["data"], d["numero"]): d for d in sysspy.scontrini(elenco)}


def _documenti(negozio_id, giorno, cassa=None):
    """[(cassa, documento)] dei SysSpy archiviati del negozio per quel giorno (una cassa o tutte)."""
    files = FileSysSpy.objects.filter(negozio_id=negozio_id, data=giorno)
    if cassa is not None:
        files = files.filter(cassa=cassa)
    data = giorno.strftime("%d/%m/%Y")
    out, visti = [], set()
    for f in files.only("cassa", "percorso_archivio"):
        percorso = Path(f.percorso_archivio)
        if not percorso.is_file() or (f.cassa, str(percorso)) in visti:
            continue
        visti.add((f.cassa, str(percorso)))
        for (data_doc, _), d in _documenti_del_file(str(percorso), percorso.stat().st_mtime).items():
            if data_doc == data:
                out.append((f.cassa, d))
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
    for _, d in _documenti(negozio_id, giorno, cassa):
        if _numero_coincide(d["numero"], numero):
            return d["testo"]
    return None


def scontrini(s):
    """Il documento sospeso e (se c'è) quello emesso dopo il richiamo, con didascalia e testo."""
    out = {"sospeso": {"titolo": f"Sospeso · cassa {s.cassa} · documento {s.numero} · {s.data:%d/%m/%Y} {s.ora:%H:%M}"
                                 if s.data and s.ora else "Sospeso",
                       "testo": testo_scontrino(s.negozio_id, s.data, s.cassa, s.numero)}}
    if s.ribattuto and not s.emesso_data:
        etichetta = "Ribattuto" if s.ribattuto == s.RIBATTUTO else "Probabilmente ribattuto"
        out["emesso"] = {"titolo": f"{etichetta} · cassa {s.rib_cassa} · scontrino {s.rib_numero} · "
                                   f"{s.rib_data:%d/%m/%Y} {s.rib_ora}",
                         "motivo": s.rib_motivo, "altri": s.rib_altri,
                         "testo": testo_scontrino(s.negozio_id, s.rib_data, s.rib_cassa, s.rib_numero)}
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
        elif s.ribattuto:
            chiavi.add((s.negozio_id, s.rib_data, s.rib_cassa))
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
                   nome(s.negozio_id, s.emesso_data, s.cassa_emissione, s.numero_emesso) if s.emesso_data
                   else nome(s.negozio_id, s.rib_data, s.rib_cassa, s.rib_numero)) for s in sospesi}


def _numero(numero_doc):
    """«1107-0081» → «81»."""
    return str(numero_doc).rsplit("-", 1)[-1].lstrip("0")



# ---------------------------------------------------------------- scontrini ribattuti a mano

SOGLIA_STESSI_ARTICOLI = 0.8   # stesso totale e almeno l'80% di articoli in comune: ribattuto
SOGLIA_TOTALE_DIVERSO = 0.6    # totale diverso ma almeno il 60% di articoli in comune: probabilmente ribattuto


def _articoli(doc):
    """Descrizioni degli articoli (senza importi) come multinsieme, per il confronto."""
    out = {}
    for riga in doc.get("articoli") or []:
        descrizione = " ".join(re.sub(r"-?\d+,\d{2}\s*$", "", riga).split()).upper()
        if descrizione:
            out[descrizione] = out.get(descrizione, 0) + 1
    return out


def _somiglianza(a, b):
    """Articoli in comune sul totale del più lungo dei due scontrini (0-1); None se uno dei due non ne ha."""
    if not a or not b:
        return None
    comuni = sum(min(n, b.get(k, 0)) for k, n in a.items())
    return comuni / max(sum(a.values()), sum(b.values()))


def _ora_minuti(testo):
    try:
        ore, minuti = str(testo).split(":")[:2]
        return int(ore) * 60 + int(minuti)
    except ValueError:
        return None


def abbina_ribattuti(negozio_id, dal=None):
    """
    Per gli scontrini sospesi e non emessi del negozio cerca lo scontrino fiscale ribattuto a mano:
    stesso negozio, giorno della sospensione (dopo l'ora) o successivo, qualsiasi cassa. Stesso totale e
    stessi articoli: ribattuto; stesso totale ma articoli diversi o non leggibili, oppure totale diverso
    con molti articoli in comune: probabilmente ribattuto. Ogni scontrino fiscale si usa una volta sola.
    """
    from datetime import timedelta

    from django.utils import timezone

    from ..models import ScontrinoSospeso

    dal = dal or timezone.localdate() - timedelta(days=60)
    sospesi = list(ScontrinoSospeso.objects.filter(negozio_id=negozio_id, data__gte=dal).order_by("data", "ora"))
    # Gli scontrini emessi con FINE RISTAMPA non sono ribattuti di nessuno.
    usati = {(s.emesso_data, s.cassa_emissione, str(s.numero_emesso)) for s in sospesi if s.emesso_data}
    documenti = {}

    def del_giorno(giorno):
        if giorno not in documenti:
            documenti[giorno] = _documenti(negozio_id, giorno)
        return documenti[giorno]

    for s in sospesi:
        if s.emesso_data or not s.data:
            if s.ribattuto:   # emesso nel frattempo con il richiamo
                s.ribattuto = ""
                s.save(update_fields=["ribattuto"])
            continue
        originale = next((d for c, d in del_giorno(s.data) if c == s.cassa and _numero_coincide(d["numero"], s.numero)), None)
        articoli = _articoli(originale) if originale else {}
        ora_sospensione = s.ora.hour * 60 + s.ora.minute if s.ora else 0
        candidati = []
        for giorno in (s.data, s.data + timedelta(days=1)):
            for cassa, d in del_giorno(giorno):
                if d["abortito"] or d["reso"] or d["totale"] is None or d is originale:
                    continue
                numero = str(d["numero"]).rsplit("-", 1)[-1].lstrip("0")
                if (giorno, cassa, numero) in usati:
                    continue
                ora = _ora_minuti(d["ora"])
                if giorno == s.data and ora is not None and ora < ora_sospensione:
                    continue
                somiglianza = _somiglianza(articoli, _articoli(d))
                stesso_totale = s.importo is not None and d["totale"] == s.importo
                if stesso_totale and somiglianza is not None and somiglianza >= SOGLIA_STESSI_ARTICOLI:
                    livello, motivo = 0, "stesso totale e stessi articoli"
                elif stesso_totale:
                    livello, motivo = 1, ("stesso totale, articoli diversi" if somiglianza is not None
                                          else "stesso totale, articoli non confrontabili")
                elif somiglianza is not None and somiglianza >= SOGLIA_TOTALE_DIVERSO:
                    livello, motivo = 2, f"totale diverso, {round(somiglianza * 100)}% di articoli in comune"
                else:
                    continue
                distanza = (giorno - s.data).days * 24 * 60 + (ora or 0) - ora_sospensione
                candidati.append((livello, -(somiglianza or 0), distanza, giorno, cassa, numero, d, motivo, somiglianza))
        candidati.sort(key=lambda c: c[:3])
        if candidati:
            livello, _, _, giorno, cassa, numero, d, motivo, somiglianza = candidati[0]
            usati.add((giorno, cassa, numero))
            s.ribattuto = s.RIBATTUTO if livello == 0 and len([c for c in candidati if c[0] == 0]) == 1 else s.PROBABILE
            if livello == 0 and s.ribattuto == s.PROBABILE:
                motivo += " (più scontrini uguali)"
            s.rib_data, s.rib_ora, s.rib_cassa, s.rib_numero = giorno, d["ora"], cassa, int(numero or 0)
            s.rib_importo, s.rib_somiglianza, s.rib_motivo = d["totale"], somiglianza, motivo
            s.rib_altri = [{"data": c[3].isoformat(), "cassa": c[4], "numero": c[5], "ora": c[6]["ora"],
                            "importo": str(c[6]["totale"]), "motivo": c[7]} for c in candidati[1:6]]
        else:
            s.ribattuto, s.rib_data, s.rib_ora, s.rib_cassa, s.rib_numero = "", None, "", None, None
            s.rib_importo, s.rib_somiglianza, s.rib_motivo, s.rib_altri = None, None, "", []
        s.save()
