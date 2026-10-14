"""Gli annunci registrati dei numeri: un file audio per numero, raccolti in serie.

I nomi dei file decidono tutto, come nei pacchetti già in uso nei negozi:
«SALUMERIA_27.mp3» è il 27 della serie «SALUMERIA»; un file senza numero caricato in
una serie (es. «DEFAULT.mp3») vale per i numeri che non hanno il loro.
"""

import re
import unicodedata
from pathlib import Path

from contenuti.file import impronta_e_dimensione

from .models import FileAnnuncio, Reparto, SerieAnnunci

MASSIMO_FILE = 3 * 1024 * 1024
NUMERO_MASSIMO = 999
_NOME = re.compile(r"^(?P<serie>.*?)[\s_\-.#]*(?P<numero>\d{1,4})$")


def leggi_nome(nome_file: str) -> tuple[str, int | None]:
    """(«SALUMERIA», 27) da «SALUMERIA_27.mp3»; ("", 5) da «5.mp3»; («DEFAULT», None) senza numero."""
    radice = Path(nome_file).stem.strip()
    trovato = _NOME.match(radice)
    if trovato:
        return trovato["serie"].strip(" _-.#"), int(trovato["numero"])
    return radice, None


def normalizza(testo: str) -> str:
    """Per confrontare i nomi: «Salumeria», «SALUMERIA» e «salumería» sono lo stesso reparto."""
    senza_accenti = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", senza_accenti.lower())


def formato_audio(file) -> str | None:
    """L'estensione giusta guardando il contenuto, non il nome: mp3, wav o ogg."""
    file.seek(0)
    # Molti mp3 registrati iniziano con qualche centinaio di byte a zero prima del primo frame.
    testa = file.read(4096).lstrip(b"\0")[:12]
    file.seek(0)
    if testa[:3] == b"ID3" or (len(testa) > 1 and testa[0] == 0xFF and testa[1] & 0xE0 == 0xE0):
        return ".mp3"
    if testa[:4] == b"RIFF" and testa[8:12] == b"WAVE":
        return ".wav"
    if testa[:4] == b"OggS":
        return ".ogg"
    return None


def salva_file(serie, numero, file) -> FileAnnuncio:
    """Aggiunge o sostituisce il file di quel numero (None: il predefinito) nella serie."""
    estensione = formato_audio(file)
    impronta, dimensione = impronta_e_dimensione(file)
    vecchio = FileAnnuncio.objects.filter(serie=serie, numero=numero).first()
    if vecchio is not None:
        if vecchio.sha256 == impronta:
            return vecchio  # lo stesso file: nulla da fare
        vecchio.delete()
    file.name = f"annuncio{estensione}"
    return FileAnnuncio.objects.create(
        cliente_id=serie.cliente_id, serie=serie, numero=numero, file=file,
        nome_originale=getattr(file, "nome_originale", "")[:200], sha256=impronta, dimensione=dimensione,
    )


def collega_reparti(serie) -> list[Reparto]:
    """I reparti con lo stesso nome della serie, ancora senza annunci, la usano da subito."""
    chiave = normalizza(serie.nome)
    collegati = [r for r in Reparto.objects.filter(annunci__isnull=True) if normalizza(r.nome) == chiave]
    for reparto in collegati:
        reparto.annunci = serie
        reparto.save(update_fields=["annunci"])
    return collegati


def importa(files, serie=None) -> dict:
    """Carica molti file in una volta. Senza ``serie`` la serie viene dal nome di ogni file
    (e si crea se non c'è); con ``serie`` vanno tutti lì, e un file senza numero è il predefinito."""
    esito = {"caricati": 0, "uguali": 0, "scartati": [], "serie": {}}
    per_nome = {normalizza(s.nome): s for s in SerieAnnunci.objects.all()}
    for file in files:
        nome = file.name
        prefisso, numero = leggi_nome(nome)
        if file.size > MASSIMO_FILE:
            esito["scartati"].append({"file": nome, "motivo": "più di 3 MB"})
            continue
        if formato_audio(file) is None:
            esito["scartati"].append({"file": nome, "motivo": "non è un file audio mp3, wav o ogg"})
            continue
        if numero is not None and numero > NUMERO_MASSIMO:
            esito["scartati"].append({"file": nome, "motivo": f"numero oltre {NUMERO_MASSIMO}"})
            continue
        destinazione = serie
        if destinazione is None:
            if numero is None or not prefisso:
                esito["scartati"].append({
                    "file": nome,
                    "motivo": "senza numero o senza nome del reparto: caricalo dentro una serie (vale per i numeri senza file)"
                    if numero is None else "senza nome del reparto (es. SALUMERIA_5.mp3): caricalo dentro una serie",
                })
                continue
            destinazione = per_nome.get(normalizza(prefisso))
            if destinazione is None:
                destinazione = SerieAnnunci.objects.create(nome=prefisso[:60])
                per_nome[normalizza(prefisso)] = destinazione
        file.nome_originale = nome
        prima = FileAnnuncio.objects.filter(serie=destinazione, numero=numero).values_list("sha256", flat=True).first()
        nuovo = salva_file(destinazione, numero, file)
        esito["uguali" if prima == nuovo.sha256 else "caricati"] += 1
        riepilogo = esito["serie"].setdefault(str(destinazione.id), {"id": str(destinazione.id), "nome": destinazione.nome, "file": 0})
        riepilogo["file"] += 1
    for riepilogo in esito["serie"].values():
        collegati = collega_reparti(SerieAnnunci.objects.get(id=riepilogo["id"]))
        riepilogo["collegati"] = [f"{r.nome} ({r.sede.nome})" for r in collegati]
    esito["serie"] = list(esito["serie"].values())
    return esito


def annunci_della_sede(sede_id) -> dict:
    """Per il manifest: quale serie usa ogni reparto, e i file di ogni serie (id e impronta,
    così il player li tiene in cache e li riconosce)."""
    reparti = dict(
        Reparto.objects.filter(sede_id=sede_id, annunci__isnull=False).values_list("id", "annunci_id")
    )
    if not reparti:
        return {}
    serie = {}
    for f in FileAnnuncio.objects.filter(serie_id__in=set(reparti.values())).order_by("serie_id", "numero"):
        voce = serie.setdefault(str(f.serie_id), {"numeri": {}, "predefinito": None})
        if f.numero is None:
            voce["predefinito"] = [str(f.id), f.sha256]
        else:
            voce["numeri"][str(f.numero)] = [str(f.id), f.sha256]
    return {
        "reparti": {str(r): str(s) for r, s in reparti.items() if str(s) in serie},
        "serie": serie,
    }
