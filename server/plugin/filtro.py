"""Plugin «Filtro contenuti»: niente nudo né contenuti espliciti sugli schermi.

Il modello (``modello/nsfw.onnx``, vedi il suo LEGGIMI) mette ogni immagine in cinque categorie.
Si blocca solo il nudo e l'esplicito, anche disegnato (``porn`` + ``hentai``): l'intimo e i
costumi (``sexy``) passano, a qualunque severità. La severità decide quanto il modello deve
esserne sicuro e, per video e dirette, quanti fotogrammi si guardano.

- Immagini e video si controllano al caricamento: se il filtro li vieta, non si salvano.
- Le dirette si controllano dopo, in sottofondo (``controlla_dirette``, dal pianificatore):
  vanno in onda solo dopo un controllo riuscito, e si ricontrollano di continuo; una diretta
  bloccata sparisce dagli schermi al successivo aggiornamento del palinsesto.

Nessuna eccezione: quello che il filtro vieta non si sblocca.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from django.utils import timezone

logger = logging.getLogger(__name__)

MODELLO = Path(__file__).resolve().parent / "modello" / "nsfw.onnx"
CATEGORIE = ["drawings", "hentai", "neutral", "porn", "sexy"]
VIETATE = ("porn", "hentai")
LATO = 224

# soglia: «porn» + «hentai» da qui in su è vietato. ogni_secondi: un fotogramma ogni tanti secondi
# di video. fotogrammi_diretta: quanti se ne guardano a ogni controllo di una diretta, uno ogni
# due secondi circa. ricontrollo: ogni quanti minuti una diretta verificata si ricontrolla.
SEVERITA = {
    "bassa": {"soglia": 0.80, "ogni_secondi": 5, "fotogrammi_diretta": 2, "ricontrollo": 60},
    "media": {"soglia": 0.50, "ogni_secondi": 2, "fotogrammi_diretta": 4, "ricontrollo": 30},
    "alta": {"soglia": 0.30, "ogni_secondi": 1, "fotogrammi_diretta": 8, "ricontrollo": 15},
}
# Un video lungo non si guarda tutto a un fotogramma al secondo: al massimo tanti fotogrammi,
# distribuiti su tutta la durata.
MASSIMO_FOTOGRAMMI_VIDEO = 600
MASSIMO_FOTOGRAMMI_GIF = 30
# Una diretta: quanto si aspetta per collegarsi e per leggere i fotogrammi.
ATTESA_DIRETTA = 15
DURATA_MASSIMA_DIRETTA = 40
# Dopo tanti tentativi falliti di fila, una diretta in verifica è «non verificabile».
TENTATIVI_DIRETTA = 3


class FiltroNonDisponibile(RuntimeError):
    """Il modello non c'è o non parte: con il filtro attivo non si accetta nulla di non controllato."""


@dataclass
class Esito:
    vietato: bool
    # Il punteggio più alto di nudo/esplicito trovato (0–1) e le categorie di quel fotogramma.
    punteggio: float = 0.0
    categorie: dict = field(default_factory=dict)
    fotogrammi: int = 0
    # Secondo del video (o della diretta) del fotogramma peggiore.
    secondo: float | None = None

    def come_dati(self) -> dict:
        return {
            "vietato": self.vietato, "punteggio": round(self.punteggio, 3), "fotogrammi": self.fotogrammi,
            "categorie": {k: round(v, 3) for k, v in self.categorie.items()},
            "secondo": None if self.secondo is None else round(self.secondo, 1),
        }


def impostazioni():
    """Il filtro del cliente corrente, o None se non è mai stato configurato."""
    from .models import FiltroContenuti

    return FiltroContenuti.objects.first()


def severita_per(tipo: str) -> str | None:
    """La severità per «immagine», «video» o «diretta» se il filtro è attivo per quel tipo, altrimenti None."""
    filtro = impostazioni()
    campo = {"immagine": "immagini", "video": "video", "diretta": "dirette"}[tipo]
    if filtro is None or not getattr(filtro, campo):
        return None
    return getattr(filtro, f"severita_{campo}")


# --- Il modello -----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _sessione():
    try:
        import onnxruntime

        opzioni = onnxruntime.SessionOptions()
        # Pochi thread: il server intanto risponde a pannello e player.
        opzioni.intra_op_num_threads = 2
        opzioni.inter_op_num_threads = 1
        return onnxruntime.InferenceSession(str(MODELLO), opzioni, providers=["CPUExecutionProvider"])
    except Exception as errore:  # modello mancante o danneggiato, libreria assente
        raise FiltroNonDisponibile(f"Il modello del filtro non si avvia: {errore}") from errore


def disponibile() -> bool:
    try:
        _sessione()
        return True
    except FiltroNonDisponibile:
        return False


def categorie(immagine) -> dict:
    """Le probabilità delle cinque categorie per un'immagine di Pillow."""
    import numpy

    from PIL import Image

    rgb = immagine.convert("RGB").resize((LATO, LATO), Image.BILINEAR)
    ingresso = (numpy.asarray(rgb, dtype=numpy.float32) / 255.0)[None]
    sessione = _sessione()
    uscita = sessione.run(None, {sessione.get_inputs()[0].name: ingresso})[0][0]
    return {nome: float(valore) for nome, valore in zip(CATEGORIE, uscita)}


def punteggio(probabilita: dict) -> float:
    return sum(probabilita[c] for c in VIETATE)


class _Raccolta:
    """Tiene il fotogramma peggiore; ``vietato`` appena uno supera la soglia."""

    def __init__(self, severita: str):
        self.soglia = SEVERITA[severita]["soglia"]
        self.esito = Esito(vietato=False)

    def aggiungi(self, immagine, secondo=None) -> bool:
        probabilita = categorie(immagine)
        valore = punteggio(probabilita)
        self.esito.fotogrammi += 1
        if valore >= self.esito.punteggio:
            self.esito.punteggio, self.esito.categorie, self.esito.secondo = valore, probabilita, secondo
        if valore >= self.soglia:
            self.esito.vietato = True
        return self.esito.vietato


# --- Immagini e video caricati ----------------------------------------------------------------


def controlla_immagine(file, severita: str) -> Esito:
    """Un'immagine caricata; delle GIF e WebP animate si guardano fotogrammi lungo tutta l'animazione."""
    from PIL import Image, ImageSequence

    raccolta = _Raccolta(severita)
    file.seek(0)
    try:
        with Image.open(file) as immagine:
            totale = getattr(immagine, "n_frames", 1) or 1
            passo = max(1, totale // MASSIMO_FOTOGRAMMI_GIF)
            for indice, fotogramma in enumerate(ImageSequence.Iterator(immagine)):
                if indice % passo == 0 and raccolta.aggiungi(fotogramma):
                    break
    finally:
        file.seek(0)
    return raccolta.esito


def _apri_video(file):
    import av

    percorso = getattr(file, "temporary_file_path", None)
    if percorso:
        return av.open(percorso())
    file.seek(0)
    return av.open(file)


def controlla_video(file, severita: str) -> Esito:
    """Un video caricato: un fotogramma ogni pochi secondi, su tutta la durata."""
    raccolta = _Raccolta(severita)
    try:
        with _apri_video(file) as contenitore:
            if not contenitore.streams.video:
                raise ValueError("Il file non contiene video.")
            flusso = contenitore.streams.video[0]
            flusso.thread_type = "AUTO"
            durata = _durata(contenitore, flusso)
            ogni = SEVERITA[severita]["ogni_secondi"]
            if not durata:
                # Durata sconosciuta: si leggono i fotogrammi in fila, uno ogni «ogni» secondi.
                _video_in_fila(contenitore, flusso, ogni, raccolta)
            else:
                passi = min(MASSIMO_FOTOGRAMMI_VIDEO, max(1, int(durata // ogni) + 1))
                for n in range(passi):
                    secondo = durata * n / passi
                    immagine = _fotogramma_a(contenitore, flusso, secondo)
                    if immagine is not None and raccolta.aggiungi(immagine, secondo):
                        break
    finally:
        file.seek(0)
    if raccolta.esito.fotogrammi == 0:
        raise ValueError("Nessun fotogramma leggibile nel video.")
    return raccolta.esito


def _durata(contenitore, flusso) -> float | None:
    if flusso.duration and flusso.time_base:
        return float(flusso.duration * flusso.time_base)
    if contenitore.duration:
        return contenitore.duration / 1_000_000
    return None


def _fotogramma_a(contenitore, flusso, secondo: float):
    """Il primo fotogramma dal secondo indicato (si salta al fotogramma chiave precedente)."""
    try:
        contenitore.seek(int(secondo / flusso.time_base), stream=flusso, backward=True, any_frame=False)
        for fotogramma in contenitore.decode(flusso):
            if fotogramma.time is None or fotogramma.time >= secondo - 0.05:
                return fotogramma.to_image()
    except Exception:  # un punto illeggibile non ferma il controllo del resto
        logger.debug("fotogramma illeggibile a %.1fs", secondo, exc_info=True)
    return None


def _video_in_fila(contenitore, flusso, ogni, raccolta, limite=MASSIMO_FOTOGRAMMI_VIDEO):
    prossimo = 0.0
    for fotogramma in contenitore.decode(flusso):
        istante = fotogramma.time or 0.0
        if istante + 1e-6 < prossimo:
            continue
        prossimo = istante + ogni
        if raccolta.aggiungi(fotogramma.to_image(), istante) or raccolta.esito.fotogrammi >= limite:
            return


# --- Dirette ------------------------------------------------------------------------------------


class DirettaIrraggiungibile(RuntimeError):
    pass


def controlla_diretta(url: str, severita: str) -> Esito:
    """Guarda alcuni fotogrammi di una diretta, uno ogni due secondi circa."""
    import av

    from layout.fonti import IndirizzoNonAmmesso, verifica_indirizzo

    try:
        # Come per i feed: il server non si collega alla propria rete interna.
        verifica_indirizzo(url)
    except IndirizzoNonAmmesso as errore:
        raise DirettaIrraggiungibile(f"indirizzo non raggiungibile dal server ({errore})") from errore
    quanti = SEVERITA[severita]["fotogrammi_diretta"]
    raccolta = _Raccolta(severita)
    inizio = time.monotonic()
    try:
        opzioni = {"rw_timeout": str(ATTESA_DIRETTA * 1_000_000), "protocol_whitelist": "http,https,tls,tcp,hls,crypto"}
        with av.open(url, options=opzioni, timeout=(ATTESA_DIRETTA, ATTESA_DIRETTA)) as contenitore:
            if not contenitore.streams.video:
                raise DirettaIrraggiungibile("nessun video nel flusso")
            flusso = contenitore.streams.video[0]
            prossimo = None
            for fotogramma in contenitore.decode(flusso):
                if time.monotonic() - inizio > DURATA_MASSIMA_DIRETTA:
                    break
                istante = fotogramma.time or 0.0
                if prossimo is not None and istante < prossimo:
                    continue
                prossimo = istante + 2
                if raccolta.aggiungi(fotogramma.to_image(), istante) or raccolta.esito.fotogrammi >= quanti:
                    break
    except DirettaIrraggiungibile:
        raise
    except Exception as errore:  # av.error.*, rete, formato
        raise DirettaIrraggiungibile(str(errore)[:200]) from errore
    if raccolta.esito.fotogrammi == 0:
        raise DirettaIrraggiungibile("nessun fotogramma ricevuto")
    return raccolta.esito


def da_controllare(contenuto, adesso=None) -> bool:
    """Una diretta va controllata adesso? Quelle in verifica sempre, le altre a scadenza."""
    from contenuti.models import Controllo

    if contenuto.controllo in ("", Controllo.BLOCCATA):
        return False
    # In verifica: subito (al massimo un tentativo al minuto). Verificate e non raggiungibili: a scadenza.
    if contenuto.controllo == Controllo.ATTESA or contenuto.controllo_il is None:
        return True
    severita = severita_per("diretta") or "media"
    adesso = adesso or timezone.now()
    return contenuto.controllo_il <= adesso - timedelta(minutes=SEVERITA[severita]["ricontrollo"])


def verifica_diretta(contenuto, severita: str, utente=None) -> None:
    """Controlla una diretta e ne aggiorna lo stato; una bloccata resta bloccata per sempre."""
    from audit.models import registra
    from contenuti.models import Controllo

    esito_prima = contenuto.controllo_esito or {}
    try:
        esito = controlla_diretta(contenuto.url, severita)
    except DirettaIrraggiungibile as errore:
        tentativi = int(esito_prima.get("tentativi", 0)) + 1
        contenuto.controllo_esito = {**esito_prima, "tentativi": tentativi, "errore": str(errore)}
        # Anche una diretta già verificata: se non si riesce più a controllarla, non resta in onda alla cieca.
        if tentativi >= TENTATIVI_DIRETTA:
            contenuto.controllo = Controllo.NON_VERIFICABILE
        contenuto.controllo_il = timezone.now()
        contenuto.save(update_fields=["controllo", "controllo_il", "controllo_esito"])
        return
    contenuto.controllo_esito = {**esito.come_dati(), "severita": severita, "tentativi": 0}
    contenuto.controllo_il = timezone.now()
    contenuto.controllo = Controllo.BLOCCATA if esito.vietato else Controllo.OK
    contenuto.save(update_fields=["controllo", "controllo_il", "controllo_esito"])
    if esito.vietato:
        registra(utente, "diretta_bloccata_filtro", contenuto, nome=contenuto.nome, url=contenuto.url, **esito.come_dati())


def controlla_dirette(budget_secondi: float = 45, adesso=None) -> dict:
    """Il giro del pianificatore: le dirette in verifica e quelle da ricontrollare, di tutti i
    clienti con il filtro attivo per le dirette, finché c'è tempo (si riprende al giro dopo)."""
    from django.db.models import F

    from contenuti.models import Contenuto, Tipo
    from core.contesto import contesto_cliente, contesto_piattaforma

    from .models import FiltroContenuti

    if not disponibile():
        return {"errore": "modello non disponibile"}
    inizio = time.monotonic()
    with contesto_piattaforma():
        clienti = list(FiltroContenuti.objects.filter(dirette=True).values_list("cliente_id", "severita_dirette"))
    totale = {"controllate": 0, "bloccate": 0}
    for cliente_id, severita in clienti:
        with contesto_cliente(cliente_id):
            dirette = Contenuto.objects.filter(tipo=Tipo.DIRETTA).exclude(controllo__in=["", "bloccata"]).order_by(F("controllo_il").asc(nulls_first=True))
            for contenuto in dirette:
                if time.monotonic() - inizio > budget_secondi:
                    return totale
                if not da_controllare(contenuto, adesso):
                    continue
                verifica_diretta(contenuto, severita)
                totale["controllate"] += 1
                totale["bloccate"] += contenuto.controllo == "bloccata"
    return totale
