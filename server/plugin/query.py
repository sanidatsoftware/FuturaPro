"""La query SQLite di ogni plugin: generata dalla mappatura (tabella e colonne) o scritta a mano.

La esegue il servizio code del Totem Master sulla sua copia del file, aperta in sola lettura,
con questi parametri: ``:codice`` (il codice letto), ``:codice_corto`` (senza zeri iniziali),
``:plu`` e ``:reparto`` (per i codici bilancia; vuoti per gli altri), ``:adesso`` (data e ora
locali del totem, «AAAA-MM-GG hh:mm:ss»: la SQLite di Windows non sa calcolare l'ora locale). Le colonne del risultato
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
# Facoltative, se la query le restituisce: reparto (il banco), note (es. origine), prezzo_bilancia,
# unita e prezzo_etichetta (il prezzo stampato sulla confezione).
USCITE_FACOLTATIVE = {
    "prezzo": ["prezzo_etichetta"],
    "ingredienti": ["reparto", "note", "prezzo_bilancia", "unita", "prezzo_etichetta"],
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


def genera_ricerca(tipo: str, m: dict) -> str:
    """La ricerca per descrizione (parametro ``:testo``, già con i «%»): più righe, in ordine.
    Il servizio code cerca la parola più lunga e tiene le righe che contengono tutte le parole."""
    uscite = [f"{colonna(m[c])} AS {c}" for c in USCITE[tipo] if m.get(c)]
    descrizione = colonna(m["descrizione"])
    return f"SELECT {', '.join(uscite)} FROM {colonna(m['tabella'])} WHERE {descrizione} LIKE :testo ORDER BY {descrizione} LIMIT 300"


def ricerca_di(impostazioni) -> str | None:
    """La query della ricerca per descrizione; None con una query scritta a mano (non si può derivare)."""
    pronta = RICERCHE.get(impostazioni.tipo, {}).get(impostazioni.formato)
    if pronta:
        return pronta
    if PREIMPOSTAZIONI.get(impostazioni.tipo, {}).get(impostazioni.formato) or impostazioni.query:
        return None
    try:
        mappatura = valida_mappatura(impostazioni.tipo, impostazioni.mappatura, obbligatoria=True)
    except ValueError:
        return None
    return genera_ricerca(impostazioni.tipo, mappatura)


def query_di(impostazioni) -> str | None:
    pronta = PREIMPOSTAZIONI.get(impostazioni.tipo, {}).get(impostazioni.formato)
    if pronta:
        return pronta[1]
    if impostazioni.query:
        return impostazioni.query
    try:
        mappatura = valida_mappatura(impostazioni.tipo, impostazioni.mappatura, obbligatoria=True)
    except ValueError:
        return None
    return genera(impostazioni.tipo, mappatura)


# Gestionali già conosciuti: la query è pronta, non serve la mappatura.
EVOPOS = """
SELECT a.Descrizione AS descrizione,
       p.Valore AS prezzo,
       CASE WHEN l.CodiceOfferta IS NOT NULL AND l.ValoreEffetto1 > 0 AND l.ValoreEffetto1 < p.Valore
            THEN round(p.Valore - l.ValoreEffetto1, 2) END AS prezzo_offerta,
       l.DataInizio AS offerta_dal,
       l.DataFine AS offerta_al,
       CASE WHEN a.Tipo = 'KG' THEN 'kg' ELSE '' END AS unita,
       CASE WHEN length(:codice) = 13 AND substr(:codice, 1, 1) = '2' AND e.Ean = substr(:codice, 1, 7)
            THEN CAST(substr(:codice, 8, 5) AS INTEGER) / 100.0 END AS prezzo_etichetta
FROM CodiceEan e
JOIN Articoli a ON a.Codice = e.CodiceArticolo
JOIN PrezziDiVendita p ON p.CodiceArticolo = a.Codice AND p.numeroPrezzo = 1
LEFT JOIN LinkArticoliLegacypromo k ON k.CodiceArticolo = a.Codice
LEFT JOIN LegacyPromo l ON l.CodiceOfferta = k.CodiceOfferta AND l.Attivo = 1 AND l.CodiceEffetto = 11
     AND coalesce(:adesso, datetime('now', 'localtime')) BETWEEN l.DataInizio AND l.DataFine
WHERE a.Stato = 1 AND (
      e.Ean IN (:codice, :codice_corto, substr('0000000000000' || :codice_corto, -13), substr('00000000000000' || :codice_corto, -14))
   OR (length(:codice) = 13 AND substr(:codice, 1, 1) = '2' AND e.Ean = substr(:codice, 1, 7)))
ORDER BY CASE WHEN e.Ean = substr(:codice, 1, 7) AND length(:codice) = 13 THEN 1 ELSE 0 END, l.ValoreEffetto1 DESC
LIMIT 1
""".strip()

DIGI = """
SELECT p.Label AS descrizione,
       d.Name AS reparto,
       trim(coalesce(i.Description, CASE WHEN t5.Message LIKE 'INGR%' THEN t5.Message END)) AS ingredienti,
       '' AS allergeni,
       '' AS conservazione,
       CASE WHEN t5.Message LIKE 'ORIGINE%' THEN t5.Message END AS note,
       p.SellPriceWithTaxes AS prezzo_bilancia,
       CASE WHEN p.QuantityType = 0 THEN 'kg' ELSE '' END AS unita,
       CASE WHEN length(:codice) = 13 THEN CAST(substr(:codice, 8, 5) AS INTEGER) / 100.0 END AS prezzo_etichetta
FROM Plus p
LEFT JOIN Ingredients i ON i.Id = p.IngredientId
LEFT JOIN Texts t5 ON t5.Id = p.Text5Id
LEFT JOIN PluDepartments pd ON pd.PluId = p.Id
LEFT JOIN Departments d ON d.Id = pd.DepartmentId
WHERE p.IsEnabled = 1 AND (
      (length(:codice) >= 7 AND substr(p.BarCode1, 1, 7) = substr(:codice, 1, 7))
   OR (length(:codice) < 7 AND :plu <> '' AND p.Code = CAST(:plu AS INTEGER)))
ORDER BY (i.Id IS NOT NULL) DESC, p.UpdatedAt DESC
LIMIT 1
""".strip()

PREIMPOSTAZIONI = {
    "prezzo": {
        # EvoPos (evoPosDb.db): codici in CodiceEan (anche a 14 cifre con zeri davanti), prezzo n. 1 in
        # PrezziDiVendita, offerte «SCONTO OFFERTA» (effetto 11) in LegacyPromo: ValoreEffetto1 è lo
        # sconto in euro. Le etichette della bilancia (EAN-13 che inizia per 2) sono registrate con le
        # prime 7 cifre (prefisso + PLU); il prezzo è al kg per gli articoli di tipo KG.
        "evopos": ("EvoPos (evoPosDb.db)", EVOPOS),
    },
    "ingredienti": {
        # DIGI (DigiProject.db): il PLU si trova con le prime 7 cifre dell'etichetta, uguali a quelle
        # del suo BarCode1 (es. 21 1 0162 = PLU 162 della Macelleria); le cifre 8-12 sono il
        # prezzo della confezione. Ingredienti in Ingredients (o nel testo 5 se inizia con
        # «INGR»), in righe da 50 caratteri che il player ricompone; banco da PluDepartments.
        "digi": ("DIGI (DigiProject.db)", DIGI),
    },
}


# La ricerca per descrizione nei gestionali conosciuti (stesse colonne della ricerca per codice).
EVOPOS_RICERCA = """
SELECT a.Descrizione AS descrizione,
       p.Valore AS prezzo,
       (SELECT round(p.Valore - l.ValoreEffetto1, 2) FROM LinkArticoliLegacypromo k
          JOIN LegacyPromo l ON l.CodiceOfferta = k.CodiceOfferta
         WHERE k.CodiceArticolo = a.Codice AND l.Attivo = 1 AND l.CodiceEffetto = 11
           AND coalesce(:adesso, datetime('now', 'localtime')) BETWEEN l.DataInizio AND l.DataFine
           AND l.ValoreEffetto1 > 0 AND l.ValoreEffetto1 < p.Valore
         ORDER BY l.ValoreEffetto1 DESC LIMIT 1) AS prezzo_offerta,
       (SELECT l.DataInizio FROM LinkArticoliLegacypromo k
          JOIN LegacyPromo l ON l.CodiceOfferta = k.CodiceOfferta
         WHERE k.CodiceArticolo = a.Codice AND l.Attivo = 1 AND l.CodiceEffetto = 11
           AND coalesce(:adesso, datetime('now', 'localtime')) BETWEEN l.DataInizio AND l.DataFine
           AND l.ValoreEffetto1 > 0 AND l.ValoreEffetto1 < p.Valore
         ORDER BY l.ValoreEffetto1 DESC LIMIT 1) AS offerta_dal,
       (SELECT l.DataFine FROM LinkArticoliLegacypromo k
          JOIN LegacyPromo l ON l.CodiceOfferta = k.CodiceOfferta
         WHERE k.CodiceArticolo = a.Codice AND l.Attivo = 1 AND l.CodiceEffetto = 11
           AND coalesce(:adesso, datetime('now', 'localtime')) BETWEEN l.DataInizio AND l.DataFine
           AND l.ValoreEffetto1 > 0 AND l.ValoreEffetto1 < p.Valore
         ORDER BY l.ValoreEffetto1 DESC LIMIT 1) AS offerta_al,
       CASE WHEN a.Tipo = 'KG' THEN 'kg' ELSE '' END AS unita
FROM Articoli a
JOIN PrezziDiVendita p ON p.CodiceArticolo = a.Codice AND p.numeroPrezzo = 1
WHERE a.Stato = 1 AND a.Descrizione LIKE :testo
ORDER BY a.Descrizione
LIMIT 300
""".strip()

DIGI_RICERCA = """
SELECT p.Label AS descrizione,
       substr(p.BarCode1, 1, 7) AS codice,
       max(d.Name) AS reparto,
       trim(coalesce(i.Description, CASE WHEN t5.Message LIKE 'INGR%' THEN t5.Message END)) AS ingredienti,
       '' AS allergeni,
       '' AS conservazione,
       CASE WHEN t5.Message LIKE 'ORIGINE%' THEN t5.Message END AS note,
       p.SellPriceWithTaxes AS prezzo_bilancia,
       CASE WHEN p.QuantityType = 0 THEN 'kg' ELSE '' END AS unita
FROM Plus p
LEFT JOIN Ingredients i ON i.Id = p.IngredientId
LEFT JOIN Texts t5 ON t5.Id = p.Text5Id
LEFT JOIN PluDepartments pd ON pd.PluId = p.Id
LEFT JOIN Departments d ON d.Id = pd.DepartmentId
WHERE p.IsEnabled = 1 AND p.Label LIKE :testo
GROUP BY p.Label
ORDER BY p.Label
LIMIT 300
""".strip()

RICERCHE = {"prezzo": {"evopos": EVOPOS_RICERCA}, "ingredienti": {"digi": DIGI_RICERCA}}
