"""Campagne e promozioni: da ciò che si sceglie nel pannello alle pubblicazioni che vanno al player.

Una campagna raggruppa più promozioni e tiene ciò che hanno in comune (destinatari,
priorità, secondi per immagine). Ogni promozione ha le sue date e le sue immagini e
diventa una pubblicazione per orientamento: le immagini verticali vanno solo ai
totem, quelle orizzontali solo ai monitor, i contenuti senza misure a tutti.
Il player non sa nulla di campagne e promozioni: riceve pubblicazioni come sempre.
"""

import csv
import io
import re
from datetime import date, datetime, time

from django.db.models import Q

from .models import Campagna, Contenuto, ContenutoPromozione, Orientamento, Playlist, Promozione, Pubblicazione

ETICHETTE = {Orientamento.VERTICALE: "totem", Orientamento.ORIZZONTALE: "monitor", "": "tutti"}


def salva_contenuti(promozione, contenuti):
    ContenutoPromozione.objects.filter(promozione=promozione).delete()
    ContenutoPromozione.objects.bulk_create(
        ContenutoPromozione(cliente_id=promozione.cliente_id, promozione=promozione, contenuto=c, ordine=i)
        for i, c in enumerate(contenuti)
    )


def gruppi_per_orientamento(contenuti) -> dict[str, list]:
    orientati = {o: [c for c in contenuti if c.orientamento == o] for o in (Orientamento.VERTICALE, Orientamento.ORIZZONTALE)}
    neutri = [c for c in contenuti if c.orientamento is None]
    if not any(orientati.values()):
        return {"": neutri} if neutri else {}
    # I neutri seguono l'ordine della promozione insieme a quelli del loro orientamento.
    return {
        o: [c for c in contenuti if c.orientamento in (o, None)]
        for o, elenco in orientati.items()
        if elenco
    }


def ha_destinatari(campagna) -> bool:
    return campagna.insegne.exists() or campagna.gruppi.exists() or campagna.monitor.exists()


def sincronizza(promozione):
    """Crea, aggiorna o toglie le pubblicazioni della promozione. Da chiamare dopo ogni modifica."""
    from .api import salva_elementi

    campagna = promozione.campagna
    contenuti = [v.contenuto for v in promozione.voci.select_related("contenuto").order_by("ordine")]
    gruppi = gruppi_per_orientamento(contenuti)
    # Senza destinatari la promozione è una bozza: nessuna pubblicazione.
    if not ha_destinatari(campagna):
        gruppi = {}

    esistenti = {p.orientamento: p for p in promozione.pubblicazioni.select_related("playlist")}
    for orientamento, pubblicazione in esistenti.items():
        if orientamento not in gruppi:
            pubblicazione.playlist.delete()  # porta via anche la pubblicazione

    for orientamento, elenco in gruppi.items():
        nome = f"{campagna.nome} · {promozione.nome} · {ETICHETTE[orientamento]}"[:200]
        pubblicazione = esistenti.get(orientamento)
        if pubblicazione is None:
            playlist = Playlist.objects.create(nome=nome, descrizione=f"Promozione «{promozione.nome}»")
            pubblicazione = Pubblicazione(promozione=promozione, orientamento=orientamento, playlist=playlist)
        else:
            Playlist.objects.filter(id=pubblicazione.playlist_id).update(nome=nome)
        for campo in ("data_inizio", "data_fine", "ora_inizio", "ora_fine", "giorni"):
            setattr(pubblicazione, campo, getattr(promozione, campo))
        pubblicazione.priorita = campagna.priorita
        pubblicazione.nome = nome
        pubblicazione.attiva = True
        pubblicazione.save()
        pubblicazione.insegne.set(campagna.insegne.all())
        pubblicazione.gruppi.set(campagna.gruppi.all())
        pubblicazione.monitor.set(campagna.monitor.all())
        salva_elementi(pubblicazione.playlist, [{"contenuto": c, "durata": campagna.durata} for c in elenco])


def sincronizza_campagna(campagna):
    for promozione in campagna.promozioni.all():
        sincronizza(promozione)


def elimina_promozione(promozione):
    for pubblicazione in promozione.pubblicazioni.select_related("playlist"):
        pubblicazione.playlist.delete()
    promozione.delete()


def stato(promozione, oggi: date) -> str:
    if promozione.data_fine and promozione.data_fine < oggi:
        return "conclusa"
    if not promozione.voci.exists() or not promozione.pubblicazioni.exists():
        return "bozza"
    if promozione.data_inizio and promozione.data_inizio > oggi:
        return "programmata"
    return "in_onda"


def stato_campagna(stati: list[str]) -> str:
    for possibile in ("in_onda", "programmata", "bozza"):
        if possibile in stati:
            return possibile
    return "conclusa" if stati else "bozza"


# --- Pulizia dei contenuti delle promozioni scadute ------------------------------


def contenuti_scaduti(oggi: date):
    """I contenuti usati solo da promozioni concluse, e da nient'altro: si possono cancellare.

    Restano quelli di promozioni in corso o future, quelli nelle playlist fatte a mano
    (anche quelle fisse delle zone slide) e quelli usati dai layout.
    """
    from layout.models import Layout, Zona

    usati_in_promozioni = ContenutoPromozione.objects.values("contenuto_id")
    ancora_validi = ContenutoPromozione.objects.filter(
        Q(promozione__data_fine__isnull=True) | Q(promozione__data_fine__gte=oggi)
    ).values("contenuto_id")
    # Le playlist delle promozioni si rifanno da sole; le altre sono scelte di qualcuno.
    in_playlist_manuali = (
        Contenuto.objects.filter(
            id__in=Playlist.objects.exclude(pubblicazioni__promozione__isnull=False)
            .values("elementi__contenuto_id")
        ).values("id")
    )
    nei_layout = set(Layout.objects.exclude(immagine_sfondo__isnull=True).values_list("immagine_sfondo_id", flat=True))
    for configurazione in Zona.objects.filter(tipo="immagine").values_list("configurazione", flat=True):
        if configurazione.get("contenuto"):
            nei_layout.add(configurazione["contenuto"])
    return (
        Contenuto.objects.filter(id__in=usati_in_promozioni)
        .exclude(id__in=ancora_validi)
        .exclude(id__in=in_playlist_manuali)
        .exclude(id__in=[str(i) for i in nei_layout])
    )


# --- Importazione da CSV --------------------------------------------------------

# Una riga per promozione. Le colonne della campagna valgono per tutte le sue righe.
COLONNE = [
    "campagna", "promozione", "data_inizio", "data_fine", "insegne", "gruppi", "monitor",
    "ora_inizio", "ora_fine", "giorni", "priorita", "durata", "colore", "codice", "note",
]
OBBLIGATORIE = {"campagna", "promozione", "data_inizio", "data_fine"}
GIORNI = {"lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6}

MODELLO = (
    ";".join(COLONNE) + "\r\n"
    "Autunno 2026;Volantino 6-19 ottobre;06/10/2026;19/10/2026;Insegna A;;;;;;0;10;#ec6a1f;AUT26;\r\n"
    "Autunno 2026;Volantino 20 ott - 2 nov;20/10/2026;02/11/2026;Insegna A;;;;;;0;10;#ec6a1f;AUT26;\r\n"
    "Speciali;Black Friday;25/11/2026;30/11/2026;Insegna A|Insegna B;;;08:00;21:00;;5;8;#111111;BF;\r\n"
    "Speciali;Weekend griglia;01/06/2026;30/06/2026;;;;;;sab|dom;5;8;#111111;;Solo sabato e domenica\r\n"
)


class ErroreRiga(ValueError):
    pass


def _data(testo: str) -> date | None:
    testo = testo.strip()
    if not testo:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(testo, formato).date()
        except ValueError:
            pass
    raise ErroreRiga(f"data «{testo}» non valida (usa gg/mm/aaaa)")


def _ora(testo: str) -> time | None:
    testo = testo.strip()
    if not testo:
        return None
    try:
        return datetime.strptime(testo.replace(".", ":"), "%H:%M").time()
    except ValueError:
        raise ErroreRiga(f"ora «{testo}» non valida (usa hh:mm)")


def _intero(testo: str, campo: str, minimo: int, massimo: int) -> int | None:
    testo = testo.strip()
    if not testo:
        return None
    try:
        valore = int(testo)
    except ValueError:
        raise ErroreRiga(f"{campo} «{testo}» non è un numero")
    if not minimo <= valore <= massimo:
        raise ErroreRiga(f"{campo} deve stare tra {minimo} e {massimo}")
    return valore


def _elenco(testo: str) -> list[str]:
    return [v.strip() for v in testo.split("|") if v.strip()]


def _giorni(testo: str) -> list[int]:
    giorni = set()
    for voce in _elenco(testo):
        chiave = voce.lower()[:3]
        if chiave.isdigit() and 0 <= int(chiave) <= 6:
            giorni.add(int(chiave))
        elif chiave in GIORNI:
            giorni.add(GIORNI[chiave])
        else:
            raise ErroreRiga(f"giorno «{voce}» non valido (lun, mar, mer, gio, ven, sab, dom)")
    return sorted(giorni)


def _per_nome(nomi, archivio, cosa):
    trovati = []
    for nome in nomi:
        voce = archivio.get(nome.casefold())
        if voce is None:
            raise ErroreRiga(f"{cosa} «{nome}» inesistente")
        trovati.append(voce)
    return trovati


def leggi_csv(testo: str, insegne, gruppi, monitor) -> list[dict]:
    """Ogni riga del file, già convertita, con i suoi eventuali errori. Non salva nulla."""
    if testo.startswith("﻿"):
        testo = testo[1:]
    prima = testo.split("\n", 1)[0]
    separatore = ";" if prima.count(";") >= prima.count(",") else ","
    lettore = csv.DictReader(io.StringIO(testo), delimiter=separatore)
    intestazioni = [(c or "").strip().lower() for c in (lettore.fieldnames or [])]
    mancanti = OBBLIGATORIE - set(intestazioni)
    if mancanti:
        raise ErroreRiga(f"mancano le colonne: {', '.join(sorted(mancanti))}")
    lettore.fieldnames = intestazioni
    archivi = (
        {i.nome.casefold(): i for i in insegne},
        {g.nome.casefold(): g for g in gruppi},
        {m.nome.casefold(): m for m in monitor},
    )

    righe, visti = [], set()
    for numero, grezza in enumerate(lettore, start=2):
        valori = {c: (grezza.get(c) or "").strip() for c in COLONNE}
        if not any(valori.values()):
            continue
        riga = {"riga": numero, "campagna": valori["campagna"], "promozione": valori["promozione"], "errori": []}
        try:
            if not valori["campagna"] or not valori["promozione"]:
                raise ErroreRiga("mancano il nome della campagna o della promozione")
            if len(valori["campagna"]) > 200 or len(valori["promozione"]) > 200:
                raise ErroreRiga("nome troppo lungo (massimo 200 caratteri)")
            chiave = (valori["campagna"].casefold(), valori["promozione"].casefold())
            if chiave in visti:
                raise ErroreRiga("promozione ripetuta nel file")
            visti.add(chiave)
            inizio, fine = _data(valori["data_inizio"]), _data(valori["data_fine"])
            if not inizio or not fine:
                raise ErroreRiga("date di inizio e fine obbligatorie")
            if fine < inizio:
                raise ErroreRiga("la data di fine precede quella di inizio")
            colore = valori["colore"] or None
            if colore and not re.fullmatch(r"#[0-9a-fA-F]{6}", colore):
                raise ErroreRiga(f"colore «{colore}» non valido (es. #ec6a1f)")
            riga["promo"] = {
                "data_inizio": inizio,
                "data_fine": fine,
                "ora_inizio": _ora(valori["ora_inizio"]),
                "ora_fine": _ora(valori["ora_fine"]),
                "giorni": _giorni(valori["giorni"]),
            }
            riga["campagna_dati"] = {
                k: v
                for k, v in {
                    "codice": valori["codice"][:50] or None,
                    "note": valori["note"][:500] or None,
                    "colore": colore,
                    "priorita": _intero(valori["priorita"], "priorità", -100, 100),
                    "durata": _intero(valori["durata"], "durata", 1, 3600),
                }.items()
                if v is not None
            }
            riga["insegne"] = _per_nome(_elenco(valori["insegne"]), archivi[0], "insegna")
            riga["gruppi"] = _per_nome(_elenco(valori["gruppi"]), archivi[1], "gruppo")
            riga["monitor"] = _per_nome(_elenco(valori["monitor"]), archivi[2], "monitor")
        except ErroreRiga as errore:
            riga["errori"].append(str(errore))
        righe.append(riga)
    return righe


def importa(righe) -> tuple[int, int]:
    """Crea o aggiorna campagne e promozioni. I destinatari delle righe di una campagna si sommano.

    Restituisce (campagne, promozioni) toccate.
    """
    campagne = {c.nome.casefold(): c for c in Campagna.objects.all()}
    destinatari: dict[str, dict] = {}
    toccate = {}
    promozioni = 0
    for riga in righe:
        chiave = riga["campagna"].casefold()
        campagna = campagne.get(chiave)
        if campagna is None:
            campagna = campagne[chiave] = Campagna(nome=riga["campagna"])
        for campo, valore in riga["campagna_dati"].items():
            setattr(campagna, campo, valore)
        campagna.save()
        toccate[chiave] = campagna
        somma = destinatari.setdefault(chiave, {"insegne": set(), "gruppi": set(), "monitor": set()})
        for campo in somma:
            somma[campo].update(riga[campo])

        promozione = (
            Promozione.objects.filter(campagna=campagna, nome__iexact=riga["promozione"]).first()
            or Promozione(campagna=campagna, nome=riga["promozione"])
        )
        for campo, valore in riga["promo"].items():
            setattr(promozione, campo, valore)
        promozione.save()
        promozioni += 1

    for chiave, campagna in toccate.items():
        # Un file senza destinatari per una campagna non cancella quelli già scelti.
        for campo, valori in destinatari[chiave].items():
            if valori:
                getattr(campagna, campo).set(valori)
        sincronizza_campagna(campagna)
    return len(toccate), promozioni
