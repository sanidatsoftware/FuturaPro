"""Campagne: dalla campagna (date, destinatari, contenuti) alle pubblicazioni che vanno al player.

Una campagna diventa una pubblicazione per orientamento: le immagini verticali
vanno solo ai totem, quelle orizzontali solo ai monitor. I contenuti senza
orientamento (pagine web, video di cui non si conoscono le misure) vanno a tutti.
Il player non sa nulla delle campagne: riceve pubblicazioni come sempre.
"""

import csv
import io
import re
from datetime import date, datetime, time

from .models import Campagna, ContenutoCampagna, Orientamento, Playlist, Pubblicazione

ETICHETTE = {Orientamento.VERTICALE: "totem", Orientamento.ORIZZONTALE: "monitor", "": "tutti"}


def salva_contenuti(campagna, contenuti):
    ContenutoCampagna.objects.filter(campagna=campagna).delete()
    ContenutoCampagna.objects.bulk_create(
        ContenutoCampagna(cliente_id=campagna.cliente_id, campagna=campagna, contenuto=c, ordine=i)
        for i, c in enumerate(contenuti)
    )


def gruppi_per_orientamento(contenuti) -> dict[str, list]:
    orientati = {o: [c for c in contenuti if c.orientamento == o] for o in (Orientamento.VERTICALE, Orientamento.ORIZZONTALE)}
    neutri = [c for c in contenuti if c.orientamento is None]
    if not any(orientati.values()):
        return {"": neutri} if neutri else {}
    # I neutri seguono l'ordine della campagna insieme a quelli del loro orientamento.
    return {
        o: [c for c in contenuti if c.orientamento in (o, None)]
        for o, elenco in orientati.items()
        if elenco
    }


def sincronizza(campagna):
    """Crea, aggiorna o toglie le pubblicazioni della campagna. Da chiamare dopo ogni modifica."""
    from .api import salva_elementi

    contenuti = [v.contenuto for v in campagna.voci.select_related("contenuto").order_by("ordine")]
    gruppi = gruppi_per_orientamento(contenuti)
    # Senza destinatari la campagna è una bozza: nessuna pubblicazione.
    if not (campagna.insegne.exists() or campagna.gruppi.exists() or campagna.monitor.exists()):
        gruppi = {}

    esistenti = {p.orientamento: p for p in campagna.pubblicazioni.select_related("playlist")}
    for orientamento, pubblicazione in esistenti.items():
        if orientamento not in gruppi:
            pubblicazione.playlist.delete()  # porta via anche la pubblicazione

    for orientamento, elenco in gruppi.items():
        nome = f"{campagna.nome} · {ETICHETTE[orientamento]}"
        pubblicazione = esistenti.get(orientamento)
        if pubblicazione is None:
            playlist = Playlist.objects.create(nome=nome, descrizione=f"Campagna «{campagna.nome}»")
            pubblicazione = Pubblicazione(campagna=campagna, orientamento=orientamento, playlist=playlist)
        else:
            Playlist.objects.filter(id=pubblicazione.playlist_id).update(nome=nome)
        for campo in ("data_inizio", "data_fine", "ora_inizio", "ora_fine", "giorni", "priorita"):
            setattr(pubblicazione, campo, getattr(campagna, campo))
        pubblicazione.nome = nome
        pubblicazione.attiva = True
        pubblicazione.save()
        pubblicazione.insegne.set(campagna.insegne.all())
        pubblicazione.gruppi.set(campagna.gruppi.all())
        pubblicazione.monitor.set(campagna.monitor.all())
        salva_elementi(pubblicazione.playlist, [{"contenuto": c, "durata": campagna.durata} for c in elenco])


def stato(campagna, oggi: date) -> str:
    if not campagna.voci.exists() or not campagna.pubblicazioni.exists():
        return "bozza"
    if campagna.data_fine and campagna.data_fine < oggi:
        return "conclusa"
    if campagna.data_inizio and campagna.data_inizio > oggi:
        return "programmata"
    return "in_onda"


# --- Importazione da CSV --------------------------------------------------------

COLONNE = [
    "nome", "codice", "data_inizio", "data_fine", "insegne", "gruppi", "monitor",
    "ora_inizio", "ora_fine", "giorni", "priorita", "durata", "colore", "note",
]
OBBLIGATORIE = {"nome", "data_inizio", "data_fine"}
GIORNI = {"lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6}

MODELLO = (
    ";".join(COLONNE) + "\r\n"
    "Volantino 1 - Gennaio;V01;02/01/2026;15/01/2026;Tocal;;;;;;0;10;#ec6a1f;Saldi di inizio anno\r\n"
    "Speciale San Valentino;SV;07/02/2026;14/02/2026;Tocal|Tocal Express;Casse;;08:00;21:00;;5;8;#c62828;\r\n"
    "Weekend griglia;WG;01/06/2026;30/06/2026;;Tutti;;;;sab|dom;0;;#2a6f97;Solo sabato e domenica\r\n"
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
    return [v.strip() for v in re.split(r"[|]", testo) if v.strip()]


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
        riga = {"riga": numero, "nome": valori["nome"], "errori": []}
        try:
            if not valori["nome"]:
                raise ErroreRiga("manca il nome")
            if len(valori["nome"]) > 200:
                raise ErroreRiga("nome troppo lungo (massimo 200 caratteri)")
            if valori["nome"].casefold() in visti:
                raise ErroreRiga("nome ripetuto nel file")
            visti.add(valori["nome"].casefold())
            inizio, fine = _data(valori["data_inizio"]), _data(valori["data_fine"])
            if not inizio or not fine:
                raise ErroreRiga("date di inizio e fine obbligatorie")
            if fine < inizio:
                raise ErroreRiga("la data di fine precede quella di inizio")
            colore = valori["colore"] or None
            if colore and not re.fullmatch(r"#[0-9a-fA-F]{6}", colore):
                raise ErroreRiga(f"colore «{colore}» non valido (es. #ec6a1f)")
            riga["dati"] = {
                "nome": valori["nome"],
                "codice": valori["codice"][:50],
                "data_inizio": inizio,
                "data_fine": fine,
                "ora_inizio": _ora(valori["ora_inizio"]),
                "ora_fine": _ora(valori["ora_fine"]),
                "giorni": _giorni(valori["giorni"]),
                "priorita": _intero(valori["priorita"], "priorità", -100, 100) or 0,
                "durata": _intero(valori["durata"], "durata", 1, 3600),
                "note": valori["note"][:500],
                **({"colore": colore} if colore else {}),
            }
            riga["insegne"] = _per_nome(_elenco(valori["insegne"]), archivi[0], "insegna")
            riga["gruppi"] = _per_nome(_elenco(valori["gruppi"]), archivi[1], "gruppo")
            riga["monitor"] = _per_nome(_elenco(valori["monitor"]), archivi[2], "monitor")
        except ErroreRiga as errore:
            riga["errori"].append(str(errore))
        righe.append(riga)
    return righe


def importa(righe) -> list[Campagna]:
    """Crea le campagne nuove e aggiorna date e destinatari di quelle con lo stesso nome."""
    salvate = []
    esistenti = {c.nome.casefold(): c for c in Campagna.objects.all()}
    for riga in righe:
        campagna = esistenti.get(riga["nome"].casefold()) or Campagna()
        for campo, valore in riga["dati"].items():
            setattr(campagna, campo, valore)
        campagna.save()
        campagna.insegne.set(riga["insegne"])
        campagna.gruppi.set(riga["gruppi"])
        campagna.monitor.set(riga["monitor"])
        sincronizza(campagna)
        salvate.append(campagna)
    return salvate
