"""Plugin «Filtro contenuti»: niente nudo né contenuti espliciti sugli schermi.

Il modello è CLIP (ViT-B/32, licenza MIT; vedi ``modello/LEGGIMI.md``): ogni immagine si confronta
con quattro descrizioni fisse (``modello/frasi.json``) — «persona nuda», «persona in intimo o
costume», «persona vestita», «nessuna persona» — e si ottiene la probabilità di ognuna. Si blocca
solo il nudo; l'intimo e i costumi passano, a qualunque severità. La severità decide quanto il
modello deve esserne sicuro e, per video e dirette, quanti fotogrammi si guardano.

- Immagini e video si controllano al caricamento. Un'immagine vietata non si salva (in coda va
  la successiva). Un video si salva, ma i suoi tratti vietati sullo schermo restano coperti
  dall'immagine di riserva dello schermo, senza audio (``coperture``).
- Le dirette si controllano dopo, in sottofondo (``controlla_dirette``, dal pianificatore):
  vanno in onda solo dopo un controllo riuscito; quelle in onda si ricontrollano ogni pochi
  minuti (secondo la severità), le altre ogni qualche ora. Una diretta bloccata sparisce dagli
  schermi al successivo aggiornamento del palinsesto, e non torna più.
- In una diretta (o un'immagine animata) un fotogramma dubbio da solo non basta per bloccarla:
  servono due fotogrammi di fila oltre la soglia, oppure uno quasi certo (``SOGLIA_CERTA``).
  Così un movimento o un'inquadratura ambigua non fanno togliere un canale dagli schermi.

Nessuna eccezione: quello che il filtro vieta non si sblocca.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from django.utils import timezone

logger = logging.getLogger(__name__)

CARTELLA_MODELLO = Path(__file__).resolve().parent / "modello"
MODELLO = CARTELLA_MODELLO / "clip_visione.onnx"
CLASSI = CARTELLA_MODELLO / "clip_classi.npy"
CATEGORIE = ["nudo", "intimo", "vestito", "altro"]
LATO = 224
# Fino a questo rapporto tra i lati basta il quadrato centrale; oltre si guarda a pezzi.
RAPPORTO_UN_PEZZO = 1.15
# CLIP: la «temperatura» con cui le somiglianze diventano probabilità, e la normalizzazione dei pixel.
SCALA = 100.0
MEDIA_PIXEL = (0.48145466, 0.4578275, 0.40821073)
DEVIAZIONE_PIXEL = (0.26862954, 0.26130258, 0.27577711)

# soglia: probabilità di «nudo» da cui un'immagine è vietata (misurata su quadri di nudo, foto di
# intimo e abiti: vedi LEGGIMI). ogni_secondi: un fotogramma ogni tanti secondi di video.
# fotogrammi_diretta: quanti se ne guardano a ogni controllo di una diretta, uno ogni due secondi
# circa. ricontrollo: ogni quanti minuti si ricontrolla una diretta in onda (sorveglianza continua).
SEVERITA = {
    "bassa": {"soglia": 0.70, "ogni_secondi": 5, "fotogrammi_diretta": 4, "ricontrollo": 15},
    "media": {"soglia": 0.50, "ogni_secondi": 2, "fotogrammi_diretta": 6, "ricontrollo": 5},
    "alta": {"soglia": 0.35, "ogni_secondi": 1, "fotogrammi_diretta": 10, "ricontrollo": 2},
}
# In video e dirette un fotogramma solo basta se è quasi certo.
SOGLIA_CERTA = 0.90
# Un video lungo non si guarda tutto a un fotogramma al secondo: al massimo tanti fotogrammi,
# distribuiti su tutta la durata.
MASSIMO_FOTOGRAMMI_VIDEO = 600
MASSIMO_FOTOGRAMMI_GIF = 30
# Una diretta: quanto si aspetta per collegarsi e per leggere i fotogrammi.
ATTESA_DIRETTA = 15
DURATA_MASSIMA_DIRETTA = 45
# Dopo tanti tentativi falliti di fila, una diretta in verifica è «non verificabile».
TENTATIVI_DIRETTA = 3
# Le dirette che non sono in onda si ricontrollano solo ogni tanti minuti.
RICONTROLLO_FUORI_ONDA = 360
# Quante dirette si controllano insieme (soprattutto attesa di rete).
CONTROLLI_PARALLELI = 4


class FiltroNonDisponibile(RuntimeError):
    """Il modello non c'è o non parte: con il filtro attivo non si accetta nulla di non controllato."""


@dataclass
class Esito:
    vietato: bool
    # La probabilità di nudo più alta trovata (0–1) e le categorie di quel fotogramma.
    punteggio: float = 0.0
    categorie: dict = field(default_factory=dict)
    fotogrammi: int = 0
    # Secondo del video (o della diretta) del fotogramma peggiore.
    secondo: float | None = None
    # Video: i tratti da coprire sullo schermo, [da, a] in secondi.
    coperture: list = field(default_factory=list)

    def come_dati(self) -> dict:
        return {
            "vietato": self.vietato, "punteggio": round(self.punteggio, 3), "fotogrammi": self.fotogrammi,
            "categorie": {k: round(v, 3) for k, v in self.categorie.items()},
            "secondo": None if self.secondo is None else round(self.secondo, 1),
            "coperture": self.coperture,
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
def _modello():
    try:
        import numpy
        import onnxruntime

        opzioni = onnxruntime.SessionOptions()
        # Pochi thread: il server intanto risponde a pannello e player.
        opzioni.intra_op_num_threads = 2
        opzioni.inter_op_num_threads = 1
        sessione = onnxruntime.InferenceSession(str(percorso_modello()), opzioni, providers=["CPUExecutionProvider"])
        return sessione, numpy.load(CLASSI)
    except Exception as errore:  # modello mancante o danneggiato, libreria assente
        raise FiltroNonDisponibile(f"Il modello del filtro non si avvia: {errore}") from errore


def percorso_modello() -> Path:
    """Nell'immagine (scaricato alla costruzione) oppure nella cartella dei dati (scaricato all'avvio)."""
    from django.conf import settings

    riserva = Path(settings.MEDIA_ROOT) / "plugin" / MODELLO.name
    return MODELLO if MODELLO.exists() or not riserva.exists() else riserva


def disponibile() -> bool:
    try:
        _modello()
        return True
    except FiltroNonDisponibile:
        return False


def _quadrati(immagine) -> list:
    """I pezzi quadrati da guardare: CLIP vede solo un quadrato, e un ritaglio centrale di
    un'immagine larga (un video 16:9) lascerebbe fuori i lati. Così l'immagine è coperta tutta,
    con pezzi sovrapposti lungo il lato lungo; quasi quadrata, basta il centro."""
    rgb = immagine.convert("RGB")
    larghezza, altezza = rgb.size
    lato = min(larghezza, altezza)
    lungo = max(larghezza, altezza)
    quanti = 1 if lungo <= lato * RAPPORTO_UN_PEZZO else math.ceil(lungo / lato)
    passo = (lungo - lato) / (quanti - 1) if quanti > 1 else (lungo - lato) / 2
    pezzi = []
    for n in range(quanti):
        inizio = round(passo * n if quanti > 1 else passo)
        riquadro = (inizio, 0, inizio + lato, lato) if larghezza >= altezza else (0, inizio, lato, inizio + lato)
        pezzi.append(rgb.crop(riquadro))
    return pezzi


def _pixel(quadrato):
    """Come la preparazione di CLIP (bicubica a 224, normalizzazione), per un pezzo già quadrato."""
    import numpy

    from PIL import Image

    x = numpy.asarray(quadrato.resize((LATO, LATO), Image.BICUBIC), dtype=numpy.float32) / 255.0
    x = (x - numpy.array(MEDIA_PIXEL, dtype=numpy.float32)) / numpy.array(DEVIAZIONE_PIXEL, dtype=numpy.float32)
    return x.transpose(2, 0, 1)


def categorie(immagine) -> dict:
    """Le probabilità di «nudo», «intimo», «vestito», «altro» per un'immagine di Pillow: quelle
    del pezzo con più nudo (vedi ``_quadrati``)."""
    import numpy

    sessione, classi = _modello()
    ingresso = numpy.stack([_pixel(pezzo) for pezzo in _quadrati(immagine)])
    vettori = sessione.run(None, {sessione.get_inputs()[0].name: ingresso})[0]
    vettori = vettori / numpy.linalg.norm(vettori, axis=1, keepdims=True)
    logit = SCALA * vettori @ classi.T
    esponenziali = numpy.exp(logit - logit.max(axis=1, keepdims=True))
    probabilita = esponenziali / esponenziali.sum(axis=1, keepdims=True)
    peggiore = probabilita[int(numpy.argmax(probabilita[:, CATEGORIE.index("nudo")]))]
    return {nome: float(v) for nome, v in zip(CATEGORIE, peggiore)}


def punteggio(probabilita: dict) -> float:
    return probabilita["nudo"]


class _Raccolta:
    """Tiene il fotogramma peggiore e decide se è vietato.

    Un'immagine sola (``sequenza=False``) è vietata appena supera la soglia; in una sequenza
    (video, animazione, diretta) servono due fotogrammi di fila oltre la soglia, o uno oltre
    ``SOGLIA_CERTA``.
    """

    def __init__(self, severita: str, sequenza: bool = True):
        self.soglia = SEVERITA[severita]["soglia"]
        self.sequenza = sequenza
        self.di_fila = 0
        # Ogni fotogramma guardato, in ordine: (secondo, oltre la soglia) — per i tratti di un video.
        self.campioni = []
        self.esito = Esito(vietato=False)

    def aggiungi(self, immagine, secondo=None) -> bool:
        probabilita = categorie(immagine)
        valore = punteggio(probabilita)
        self.esito.fotogrammi += 1
        if valore >= self.esito.punteggio:
            self.esito.punteggio, self.esito.categorie, self.esito.secondo = valore, probabilita, secondo
        self.di_fila = self.di_fila + 1 if valore >= self.soglia else 0
        if secondo is not None:
            self.campioni.append((secondo, valore >= self.soglia))
        if not self.sequenza and valore >= self.soglia:
            self.esito.vietato = True
        elif self.sequenza and (self.di_fila >= 2 or valore >= max(self.soglia, SOGLIA_CERTA)):
            self.esito.vietato = True
        return self.esito.vietato


# --- Immagini e video caricati ----------------------------------------------------------------


def controlla_immagine(file, severita: str) -> Esito:
    """Un'immagine caricata; delle GIF e WebP animate si guardano fotogrammi lungo tutta l'animazione."""
    from PIL import Image, ImageSequence

    file.seek(0)
    try:
        with Image.open(file) as immagine:
            totale = getattr(immagine, "n_frames", 1) or 1
            raccolta = _Raccolta(severita, sequenza=totale > 1)
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
    """Un video caricato: un fotogramma ogni pochi secondi, su tutta la durata.

    Il video non si rifiuta: ogni fotogramma oltre la soglia diventa un tratto da coprire sullo
    schermo (``coperture``), dal fotogramma guardato prima a quello dopo, perché il nudo potrebbe
    cominciare e finire tra un controllo e l'altro. ``vietato`` vuol dire «ha tratti coperti».
    """
    raccolta = _Raccolta(severita)
    durata = None
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
                    trovato = _fotogramma_a(contenitore, flusso, durata * n / passi)
                    if trovato is not None:
                        raccolta.aggiungi(*trovato)
    finally:
        file.seek(0)
    if raccolta.esito.fotogrammi == 0:
        raise ValueError("Nessun fotogramma leggibile nel video.")
    raccolta.esito.coperture = tratti(raccolta.campioni, durata)
    raccolta.esito.vietato = bool(raccolta.esito.coperture)
    return raccolta.esito


def tratti(campioni: list, durata: float | None) -> list:
    """I tratti da coprire: per ogni fotogramma oltre la soglia, dal fotogramma guardato prima a
    quello guardato dopo (il nudo può cominciare e finire tra un controllo e l'altro); uniti se si
    toccano. ``campioni``: (secondo, oltre la soglia) in ordine."""
    campioni = sorted(set(campioni))
    risultato = []
    for indice, (secondo, sopra) in enumerate(campioni):
        if not sopra:
            continue
        da = campioni[indice - 1][0] if indice else 0.0
        a = campioni[indice + 1][0] if indice + 1 < len(campioni) else max(durata or 0.0, secondo) + 1
        if risultato and da <= risultato[-1][1]:
            risultato[-1][1] = max(risultato[-1][1], a)
        else:
            risultato.append([da, a])
    return [[round(da, 2), round(a, 2)] for da, a in risultato]


def _durata(contenitore, flusso) -> float | None:
    if flusso.duration and flusso.time_base:
        return float(flusso.duration * flusso.time_base)
    if contenitore.duration:
        return contenitore.duration / 1_000_000
    return None


def _fotogramma_a(contenitore, flusso, secondo: float):
    """Il primo fotogramma dal secondo indicato (si salta al fotogramma chiave precedente), con il
    suo istante vero: (immagine, secondo), oppure None."""
    try:
        contenitore.seek(int(secondo / flusso.time_base), stream=flusso, backward=True, any_frame=False)
        for fotogramma in contenitore.decode(flusso):
            if fotogramma.time is None or fotogramma.time >= secondo - 0.05:
                return fotogramma.to_image(), (fotogramma.time if fotogramma.time is not None else secondo)
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
        raccolta.aggiungi(fotogramma.to_image(), istante)
        if raccolta.esito.fotogrammi >= limite:
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


def dirette_in_onda(adesso=None) -> set:
    """Le dirette del cliente corrente che possono andare in onda adesso o a breve: nelle
    sequenze delle promozioni non finite, nelle playlist e negli eventi non ancora finiti."""
    from contenuti.models import ContenutoPromozione, ElementoPlaylist, EventoStraordinario, Tipo

    adesso = adesso or timezone.now()
    oggi = timezone.localdate(adesso)
    promozioni = ContenutoPromozione.objects.filter(contenuto__tipo=Tipo.DIRETTA).exclude(promozione__data_fine__lt=oggi)
    elementi = ElementoPlaylist.objects.filter(contenuto__tipo=Tipo.DIRETTA)
    eventi = EventoStraordinario.objects.filter(contenuto__tipo=Tipo.DIRETTA, fine__gte=adesso)
    return {
        *promozioni.values_list("contenuto_id", flat=True),
        *elementi.values_list("contenuto_id", flat=True),
        *eventi.values_list("contenuto_id", flat=True),
    }


def da_controllare(contenuto, severita: str, in_onda: bool, adesso=None) -> bool:
    """Una diretta va controllata adesso? Quelle in verifica sempre; quelle in onda di continuo
    (ogni pochi minuti, secondo la severità); le altre ogni qualche ora."""
    from contenuti.models import Controllo

    if contenuto.controllo in ("", Controllo.BLOCCATA):
        return False
    if contenuto.controllo == Controllo.ATTESA or contenuto.controllo_il is None:
        return True
    minuti = SEVERITA[severita]["ricontrollo"] if in_onda else RICONTROLLO_FUORI_ONDA
    return contenuto.controllo_il <= (adesso or timezone.now()) - timedelta(minutes=minuti)


def _esegui(url: str, severita: str):
    """Il controllo vero e proprio (rete e modello, niente database): può girare in un thread."""
    try:
        return controlla_diretta(url, severita)
    except DirettaIrraggiungibile as errore:
        return errore


def applica(contenuto, severita: str, esito, utente=None) -> None:
    """Aggiorna lo stato della diretta con l'esito di un controllo; una bloccata resta bloccata per sempre."""
    from audit.models import registra
    from contenuti.models import Controllo

    esito_prima = contenuto.controllo_esito or {}
    contenuto.controllo_il = timezone.now()
    if isinstance(esito, DirettaIrraggiungibile):
        tentativi = int(esito_prima.get("tentativi", 0)) + 1
        contenuto.controllo_esito = {**esito_prima, "tentativi": tentativi, "errore": str(esito)}
        # Anche una diretta già verificata: se non si riesce più a controllarla, non resta in onda alla cieca.
        if tentativi >= TENTATIVI_DIRETTA:
            contenuto.controllo = Controllo.NON_VERIFICABILE
        contenuto.save(update_fields=["controllo", "controllo_il", "controllo_esito"])
        return
    contenuto.controllo_esito = {**esito.come_dati(), "severita": severita, "tentativi": 0, "canale": esito_prima.get("canale")}
    contenuto.controllo = Controllo.BLOCCATA if esito.vietato else Controllo.OK
    contenuto.save(update_fields=["controllo", "controllo_il", "controllo_esito"])
    if esito.vietato:
        registra(utente, "diretta_bloccata_filtro", contenuto, nome=contenuto.nome, url=contenuto.url, **esito.come_dati())


def verifica_diretta(contenuto, severita: str, utente=None) -> None:
    applica(contenuto, severita, _esegui(contenuto.url, severita), utente)


def controlla_dirette(budget_secondi: float = 50, adesso=None) -> dict:
    """Il giro del pianificatore (ogni minuto): le dirette in verifica, poi quelle in onda da
    ricontrollare, poi le altre, di tutti i clienti con il filtro attivo per le dirette. Si
    controllano in parallelo; quello che non entra nel tempo si riprende al giro dopo."""
    from concurrent.futures import ThreadPoolExecutor

    from django.db.models import F

    from contenuti.models import Contenuto, Controllo, Tipo
    from core.contesto import contesto_cliente, contesto_piattaforma

    from .models import FiltroContenuti

    if not disponibile():
        return {"errore": "modello non disponibile"}
    inizio = time.monotonic()
    with contesto_piattaforma():
        clienti = list(FiltroContenuti.objects.filter(dirette=True).values_list("cliente_id", "severita_dirette"))
    totale = {"controllate": 0, "bloccate": 0}
    if clienti:
        # Il database dei bollini dei canali, una volta al giorno.
        from . import canali

        try:
            totale.update(canali.aggiorna())
        except (OSError, ValueError) as errore:
            logger.warning("database dei canali non aggiornato: %s", errore)
    with ThreadPoolExecutor(max_workers=CONTROLLI_PARALLELI) as esecutore:
        for cliente_id, severita in clienti:
            with contesto_cliente(cliente_id):
                in_onda = dirette_in_onda(adesso)
                dirette = Contenuto.objects.filter(tipo=Tipo.DIRETTA).exclude(controllo__in=["", Controllo.BLOCCATA])
                scadute = [c for c in dirette.order_by(F("controllo_il").asc(nulls_first=True)) if da_controllare(c, severita, c.id in in_onda, adesso)]
                # Prima quelle in verifica, poi quelle in onda.
                scadute.sort(key=lambda c: (c.controllo != Controllo.ATTESA, c.id not in in_onda))
                for gruppo in (scadute[n:n + CONTROLLI_PARALLELI] for n in range(0, len(scadute), CONTROLLI_PARALLELI)):
                    if time.monotonic() - inizio > budget_secondi:
                        return totale
                    esiti = list(esecutore.map(lambda c: _esegui(c.url, severita), gruppo))
                    for contenuto, esito in zip(gruppo, esiti):
                        applica(contenuto, severita, esito)
                        totale["controllate"] += 1
                        totale["bloccate"] += contenuto.controllo == Controllo.BLOCCATA
    return totale
