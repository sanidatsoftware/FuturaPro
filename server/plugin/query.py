"""La query SQLite di ogni plugin: generata dalla mappatura (tabella e colonne) o scritta a mano.

La esegue il servizio code del Totem Master sulla sua copia del file, aperta in sola lettura,
con questi parametri: ``:codice`` (il codice letto), ``:codice_corto`` (senza zeri iniziali),
``:plu`` e ``:reparto`` (per i codici bilancia; vuoti per gli altri). Le colonne del risultato
hanno nomi fissi (``descrizione``, ``prezzo``…): il player sa così cosa mostrare.
"""

import re

IDENTIFICATORE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]{0,63}$")

# (chiave, obbligatoria, spiegazione)
CAMPI = {
    "prezzo": [
        ("tabella", True, "Tabella degli articoli"),
        ("codice", True, "Colonna del codice a barre (EAN)"),
        ("descrizione", True, "Colonna della descrizione"),
        ("prezzo", True, "Colonna del prezzo"),
        ("prezzo_offerta", False, "Colonna del prezzo in offerta"),
        ("offerta_dal", False, "Colonna inizio offerta (data)"),
        ("offerta_al", False, "Colonna fine offerta (data)"),
        ("unita", False, "Colonna unità di misura (es. kg)"),
        ("plu", False, "Colonna PLU (per i prodotti a peso)"),
        ("reparto", False, "Colonna reparto/banco (per i prodotti a peso)"),
    ],
    "ingredienti": [
        ("tabella", True, "Tabella dei prodotti della bilancia"),
        ("plu", True, "Colonna PLU"),
        ("reparto", False, "Colonna reparto/banco"),
        ("descrizione", True, "Colonna della descrizione"),
        ("ingredienti", True, "Colonna degli ingredienti"),
        ("allergeni", False, "Colonna degli allergeni"),
        ("conservazione", False, "Colonna modalità di conservazione"),
    ],
}

# Le colonne del risultato, come le legge il player.
USCITE = {
    "prezzo": ["descrizione", "prezzo", "prezzo_offerta", "offerta_dal", "offerta_al", "unita"],
    "ingredienti": ["descrizione", "ingredienti", "allergeni", "conservazione"],
}


def colonna(nome: str) -> str:
    return '"' + nome.replace('"', "") + '"'


def valida_mappatura(tipo: str, mappatura: dict, obbligatoria: bool) -> dict:
    """La mappatura pulita; solleva ValueError({campo: messaggio}) se non va."""
    if not isinstance(mappatura, dict):
        raise ValueError({"mappatura": "Mappatura non valida."})
    pulita, errori = {}, {}
    for chiave, richiesta, _ in CAMPI[tipo]:
        valore = str(mappatura.get(chiave) or "").strip()
        if valore and not IDENTIFICATORE.match(valore):
            errori[chiave] = "Solo lettere, numeri, spazi e _ (es. prezzo_vendita)."
        elif richiesta and not valore and obbligatoria:
            errori[chiave] = "Obbligatoria."
        if valore:
            pulita[chiave] = valore
    if errori:
        raise ValueError(errori)
    return pulita


def valida_query(testo: str) -> str:
    testo = (testo or "").strip().rstrip(";").strip()
    if not testo:
        return ""
    if len(testo) > 4000:
        raise ValueError("Query troppo lunga.")
    if not re.match(r"(?is)^(select|with)\b", testo):
        raise ValueError("La query deve iniziare con SELECT (o WITH).")
    if ";" in testo:
        raise ValueError("Una sola query, senza «;».")
    return testo


def genera(tipo: str, m: dict) -> str:
    """La SELECT costruita dalla mappatura."""
    uscite = [f"{colonna(m[c])} AS {c}" for c in USCITE[tipo] if m.get(c)]
    tabella = colonna(m["tabella"])
    if tipo == "prezzo":
        condizione = f"(:plu = '' AND CAST({colonna(m['codice'])} AS TEXT) IN (:codice, :codice_corto))"
        if m.get("plu"):
            peso = f"CAST({colonna(m['plu'])} AS INTEGER) = CAST(:plu AS INTEGER)"
            if m.get("reparto"):
                peso += f" AND (:reparto = '' OR CAST({colonna(m['reparto'])} AS TEXT) = :reparto)"
            condizione += f" OR (:plu <> '' AND {peso})"
    else:
        condizione = f"CAST({colonna(m['plu'])} AS INTEGER) = CAST(:plu AS INTEGER)"
        if m.get("reparto"):
            condizione += f" AND (:reparto = '' OR CAST({colonna(m['reparto'])} AS TEXT) = :reparto)"
    return f"SELECT {', '.join(uscite)} FROM {tabella} WHERE {condizione} LIMIT 1"


def query_di(impostazioni) -> str | None:
    if impostazioni.query:
        return impostazioni.query
    try:
        mappatura = valida_mappatura(impostazioni.tipo, impostazioni.mappatura, obbligatoria=True)
    except ValueError:
        return None
    return genera(impostazioni.tipo, mappatura)
