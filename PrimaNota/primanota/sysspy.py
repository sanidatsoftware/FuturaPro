"""
Lettura dei file SysSpy.AAAAMMGG.CASSA (giornale elettronico di cassa).

Ogni riga del file inizia con 4 caratteri tecnici che indicano il tipo di riga,
seguiti dal testo stampato. Esempi:

    9832 = stampa non fiscale (chiusura POS, inizio/fine attività cassiere)
    9899 = intestazione/chiusura di uno scontrino non fiscale (con data e ora)
    8232 = righe del documento commerciale (intestazione, piè di pagina, POS)
    8233 = articolo venduto            8234 = articolo stornato/annullato
    8236 = TOTALE EURO                 8239/8243 = pagamento
    9949..9964 = righe della chiusura fiscale (TOTALE GIORNALIERO, ...)
    1600 = OPERAZIONE ABORTITA

Il testo che si archivia e si mostra è sempre senza i 4 caratteri iniziali.
Questo modulo non dipende da Django: riceve i byte del file e restituisce dati.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Da aumentare quando cambia il modo di leggere i file: la rielaborazione dell'archivio
# rifà solo i file analizzati con una versione precedente.
VERSIONE_ANALISI = 4   # 3: cassiere e importo delle correzioni per scontrino; 4: chiusure POS con l'importo a capo

NOME_FILE_RE = re.compile(r"^SysSpy\.(\d{8})\.(\d+)$", re.I)
TIMESTAMP_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})")
DOC_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})\s+DOC\.(\S+)")
IMPORTO_RE = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}|-?\d+)\s*$")
# Il buono di reso stampato dalla cassa ha "MOTIVO DEL RESO" e le firme: non entra nel totale giornaliero.
RESO_RE = re.compile(r"\bRESO\b")
CASSIERE_RE = re.compile(r"^\s*CASSIERE (\d+)\s*$")
PAGAMENTO_ANNULLATO_RE = re.compile(r"^\s*\d+\s*x\s*[\d.,]+\s+\D")

# Righe della chiusura fiscale da memorizzare come valori, con il nome del campo.
VOCI_FISCALI = {
    "TOTALE GIORNALIERO": "totale_giornaliero",
    "GRAN TOTALE": "gran_totale",
    "TOTALE SCONTI": "totale_sconti",
    "TOTALE MAGGIORAZ.": "totale_maggiorazioni",
    "TOTALE ANNULLI": "totale_annulli",
    "TOTALE RESI": "totale_resi",
    "CORRISP. RISCOSSO": "corrisp_riscosso",
    "CORRISP. NON RISCOSSI": "corrisp_non_riscosso",
    "NUM. SCONTRINI FISCALI": "num_scontrini_fiscali",
    "MATRICOLA STAMPANTE": "matricola_stampante",
    "NUMERO CASSA": "numero_cassa",
}
VOCI_INTERE = {"num_scontrini_fiscali", "numero_cassa"}


def importo(testo):
    """'2.400,30' -> Decimal('2400.30'); None se non è un importo."""
    if testo is None:
        return None
    m = IMPORTO_RE.search(testo.strip())
    if not m:
        return None
    valore = m.group(1).replace(".", "").replace(",", ".")
    try:
        return Decimal(valore)
    except InvalidOperation:
        return None


def decodifica(raw):
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def righe(raw):
    """Elenco di (codice, testo) con il testo già privo delle prime 4 colonne."""
    testo = decodifica(raw) if isinstance(raw, bytes) else raw.lstrip("﻿")
    out = []
    for linea in testo.splitlines():
        out.append((linea[:4], linea[4:].rstrip()))
    return out


def testo_pulito(elenco):
    return "\n".join(t for _, t in elenco)


def data_e_cassa_da_nome(nome_file):
    m = NOME_FILE_RE.match(nome_file or "")
    if not m:
        return None, None
    try:
        data = datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        data = None
    return data, int(m.group(2))


def _e_timestamp(codice_testo):
    return bool(TIMESTAMP_RE.match(codice_testo[1]))


def _fine_stampa_non_fiscale(elenco, da):
    """Indice della riga 9899 con data/ora che chiude la stampa non fiscale."""
    for i in range(da, len(elenco)):
        if elenco[i][0] == "9899" and _e_timestamp(elenco[i]):
            return i
    return len(elenco) - 1


def _inizio_stampa_non_fiscale(elenco, da):
    """Indice della riga 'NON  FISCALE' che apre la stampa che contiene la riga 'da'."""
    for i in range(da, -1, -1):
        if elenco[i][0] == "9899" and "NON  FISCALE" in elenco[i][1]:
            return i
    return da


def _testo(elenco, inizio, fine):
    return "\n".join(t for _, t in elenco[inizio:fine + 1]).strip("\n")


# «TOTALE POS EUR 2.047,31» su una riga, oppure (altri terminali) «TOTALE POS» e sotto «EUR 2.377,06».
TOTALE_POS_RE = re.compile(r"^TOTALE POS(\s+EUR\b.*)?$")


def _totale_etichetta(elenco, i, etichetta):
    """Importo della riga i che inizia con l'etichetta, o della riga «EUR …» subito sotto se è andato a capo."""
    valore = importo(elenco[i][1].strip()[len(etichetta):])
    if valore is None and i + 1 < len(elenco) and elenco[i + 1][1].strip().startswith("EUR"):
        valore = importo(elenco[i + 1][1])
    return valore


def chiusure_pos(elenco):
    """Ogni chiusura POS: dal 'NON  FISCALE' che la apre fino alla stampa del cassiere che la segue."""
    out = []
    for i, (codice, testo) in enumerate(elenco):
        if codice != "9832" or not TOTALE_POS_RE.match(testo.strip()):
            continue
        inizio = i
        for j in range(i, max(i - 80, -1), -1):
            if elenco[j][1].strip() == "CHIUSURA":
                inizio = _inizio_stampa_non_fiscale(elenco, j)
                break
        fine = _fine_stampa_non_fiscale(elenco, i)
        # Subito dopo la cassa stampa il foglio C.C.D. con cassiere, cassa e negozio:
        # fa parte della chiusura come la vede l'operatore.
        dopo = _fine_stampa_non_fiscale(elenco, fine + 1)
        if dopo - fine <= 25 and any("CASSIERE" in t for _, t in elenco[fine + 1:dopo + 1]):
            fine = dopo
        host = None
        for j in range(i, fine + 1):
            if elenco[j][1].strip().startswith("TOTALE HOST"):
                host = _totale_etichetta(elenco, j, "TOTALE HOST")
                break
        out.append({
            "testo": _testo(elenco, inizio, fine),
            "totale_pos": _totale_etichetta(elenco, i, "TOTALE POS"),
            "totale_host": host,
            "esito": "ESEGUITA" if any("OPERAZIONE ESEGUITA" in t for _, t in elenco[i:fine + 1]) else "",
        })
    return out


def circuiti_pos(testo):
    """
    Importi per tipologia di transazione (circuito) dal testo delle chiusure POS: {"UC Mastercard": Decimal, …}.
    Il nome è la riga sopra «Pagamenti …»; l'importo è il «Totale EUR» del circuito (al netto degli storni),
    o in mancanza quello dei pagamenti. Più chiusure nello stesso testo si sommano.
    """
    righe = [r.strip() for r in (testo or "").splitlines()]
    piene = [r for r in righe if r]
    out = {}
    for i, riga in enumerate(piene[:-1]):
        if not piene[i + 1].upper().startswith("PAGAMENTI") or riga.startswith("(") or riga.upper().startswith(("PAGAMENTI", "TOTALE")):
            continue
        valore = importo(piene[i + 1])
        for j in range(i + 2, len(piene)):
            alto = piene[j].upper()
            prossimo_circuito = j + 1 < len(piene) and piene[j + 1].upper().startswith("PAGAMENTI")
            if prossimo_circuito or alto.startswith(("TOTALE POS", "TOTALE HOST", "TRANSAZIONI", "(TRANSAZIONI")):
                break
            if re.match(r"^TOTALE\s+EUR\b", alto):
                valore = importo(piene[j])
                break
        if valore is not None:
            out[riga] = out.get(riga, Decimal("0")) + valore
    return out


def chiusura_fiscale(elenco):
    """La chiusura fiscale (l'ultima del file): intestazione, righe 9949..9964 e data/ora."""
    pos = None
    for i, (codice, testo) in enumerate(elenco):
        if testo.strip().startswith("TOTALE GIORNALIERO"):
            pos = i
    if pos is None:
        return None
    inizio = pos
    while inizio > 0 and elenco[inizio - 1][0] == "8232" and elenco[inizio - 1][1].strip() \
            and not DOC_RE.match(elenco[inizio - 1][1]):
        inizio -= 1
    fine = pos
    while fine + 1 < len(elenco) and elenco[fine + 1][0].isdigit() and 9940 <= int(elenco[fine + 1][0]) <= 9979:
        fine += 1
    if fine + 1 < len(elenco) and _e_timestamp(elenco[fine + 1]):
        fine += 1
    valori = {}
    for _, t in elenco[pos:fine + 1]:
        for etichetta, campo in VOCI_FISCALI.items():
            if t.strip().startswith(etichetta):
                if campo in VOCI_INTERE:
                    m = re.search(r"(\d+)\s*$", t)
                    valori[campo] = int(m.group(1)) if m else None
                elif campo == "matricola_stampante":
                    valori[campo] = t.strip()[len(etichetta):].strip()
                else:
                    valori[campo] = importo(t)
    return {"testo": _testo(elenco, inizio, fine), "valori": valori}


def scontrini(elenco):
    """
    Documenti commerciali della giornata. Ognuno termina con la riga
    'GG/MM/AAAA HH:MM   DOC.NNNN-NNNN' e inizia con l'intestazione del negozio
    (le righe 8232 che precedono 'Euro').
    """
    out = []
    inizio = 0
    for i, (codice, testo) in enumerate(elenco):
        if codice == "8232" and testo.strip() == "Euro":
            j = i
            while j > 0 and elenco[j - 1][0] == "8232" and elenco[j - 1][1].strip() \
                    and not DOC_RE.match(elenco[j - 1][1]):
                j -= 1
            inizio = j
            continue
        m = DOC_RE.match(testo) if codice == "8232" else None
        if not m:
            continue
        blocco = elenco[inizio:i + 1]
        testi = [t for _, t in blocco]
        totale = None
        for c, t in blocco:
            if c == "8236" and t.strip().startswith("TOTALE"):
                totale = importo(t)
        if totale is None:
            for t in testi:
                if t.strip().startswith("SUBTOT."):
                    totale = importo(t)
        out.append({
            "pagamenti": _pagamenti(blocco, totale),
            "numero": m.group(3),
            "ora": m.group(2),
            "totale": totale,
            "abortito": any(c == "1600" or "OPERAZIONE ABORTITA" in t for c, t in blocco),
            "annullato": any("SCONTRINO ANNULLATO" in t for t in testi),
            "storni": sum("Inizio Storno" in t for t in testi),
            "annullamenti_riga": sum("INIZIO ANNULLAMENTO" in t for t in testi),
            "reso": any(RESO_RE.search(t.upper()) for c, t in blocco if c != "9949"),
            "cassiere": next((m2.group(1) for m2 in (CASSIERE_RE.match(t) for t in testi) if m2), ""),
            # Articoli stornati o annullati (8234). Le righe «1 x 40,00 CASSA» sono pagamenti annullati e
            # ribattuti, non articoli: la cassa non li conta negli annulli e qui si escludono.
            "correzioni": sum((abs(importo(t)) for c, t in blocco
                               if c == "8234" and importo(t) is not None and not PAGAMENTO_ANNULLATO_RE.match(t)), Decimal("0")),
            "testo": _testo(elenco, inizio, i),
            # Righe articolo (descrizione e importo): servono a riconoscere uno scontrino ribattuto.
            "articoli": [t.strip() for c, t in blocco if c == "8233" and t.strip()],
            "data": m.group(1),
        })
        inizio = i + 1
    return out


CODICI_PAGAMENTO = {"8239", "8238"}   # 8239 Carta Credito, Bancomat, Buoni Pasto...; 8238 Credito
# Pagamenti che passano dal POS bancario: la loro somma deve coincidere con la chiusura POS
# e con il "CORRISP. NON RISCOSSI" della chiusura fiscale (verificato sui file di Motta).
PAGAMENTI_POS = ("Carta Credito", "Bancomat")
# Su alcune casse il "CORRISP. NON RISCOSSI" è invece la somma di buoni pasto e crediti
# (Adrano cassa 3, 17-18/10/2026): la cassa è configurata in modo diverso.
PAGAMENTI_NON_RISCOSSI = ("Buoni Pasto", "Credito")


def _pagamenti(blocco, totale):
    """
    Come è stato pagato uno scontrino: {"Carta Credito": 18.00, "Contanti": 2.50, ...}.
    I pagamenti non in contanti sono le righe 8239; i contanti sono il resto del totale
    (così il resto dato al cliente è già escluso).
    """
    out = {}
    for c, t in blocco:
        if c not in CODICI_PAGAMENTO:
            continue
        valore = importo(t)
        if valore is not None:
            # "3 x 8,00 Buoni Pasto" -> "Buoni Pasto"
            voce = re.sub(r"^\d+\s*x\s*[\d.,]+\s*", "", IMPORTO_RE.sub("", t).strip()) or "Altro"
            out[voce] = out.get(voce, Decimal("0")) + valore
    if totale is not None:
        contanti = totale - sum(out.values(), Decimal("0"))
        if contanti:
            out["Contanti"] = contanti
    return out


def somma_pagamenti(docs):
    """Totale per tipo di pagamento degli scontrini validi (esclusi gli abortiti)."""
    out = {}
    for d in docs:
        if d["abortito"] or d["reso"]:
            continue
        for voce, valore in d["pagamenti"].items():
            out[voce] = out.get(voce, Decimal("0")) + valore
    return dict(sorted(out.items()))


def pos_negate(elenco):
    """Stampe non fiscali con 'TRANSAZIONE NEGATA' (pagamento POS rifiutato)."""
    out = []
    i = 0
    while i < len(elenco):
        if "TRANSAZIONE NEGATA" in elenco[i][1]:
            inizio = _inizio_stampa_non_fiscale(elenco, i)
            fine = _fine_stampa_non_fiscale(elenco, i)
            m = TIMESTAMP_RE.match(elenco[fine][1])
            out.append({"ora": m.group(2) if m else "", "testo": _testo(elenco, inizio, fine)})
            i = fine + 1
            continue
        i += 1
    return out


def nomi_cassieri(elenco):
    """{codice: nome} dalle stampe «INIZIO/FINE ATTIVITA' CASSIERE» (CODICE / DESCRIZIONE CASSIERE)."""
    out, codice = {}, None
    for i, (_, t) in enumerate(elenco[:-1]):
        voce, valore = t.strip(), elenco[i + 1][1].strip()
        if voce == "CODICE CASSIERE" and valore.isdigit():
            codice = valore
        elif voce == "DESCRIZIONE CASSIERE" and codice and valore:
            out[codice] = valore
            codice = None
    return out


def codice_negozio(elenco):
    for i, (codice, testo) in enumerate(elenco):
        if testo.strip() == "CODICE NEGOZIO" and i + 1 < len(elenco):
            valore = elenco[i + 1][1].strip()
            if valore.isdigit():
                return valore
        m = re.search(r"CASSA \d+ NEGOZIO (\d+)", testo)
        if m:
            return m.group(1)
    return ""


# Righe con data e ora che chiudono una stampa: la stampa appartiene a quella data.
# Le ristampe (codice 9832) riportano la data del documento originale e non contano.
CODICI_DATA = {"9899", "9999", "8232"}
# Oltre questi giorni di distanza dalla data del nome file la data stampata si considera errata.
MAX_GIORNI_SCARTO = 7


def dividi_per_data(elenco, data_file=None):
    """
    Divide le righe per giornata. Un SysSpy può contenere anche le stampe dei giorni
    precedenti (cassa non chiusa, file del giorno mancante): ogni stampa va alla data
    e ora con cui termina. Restituisce [(data, righe)] in ordine di data.
    """
    giornate = {}
    ordine = []
    buffer = []
    ultima = data_file
    for riga in elenco:
        buffer.append(riga)
        m = TIMESTAMP_RE.match(riga[1]) if riga[0] in CODICI_DATA else None
        if not m:
            continue
        try:
            giorno = datetime.strptime(m.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue
        if data_file and abs((giorno - data_file).days) > MAX_GIORNI_SCARTO:
            giorno = data_file
        if giorno not in giornate:
            giornate[giorno] = []
            ordine.append(giorno)
        giornate[giorno].extend(buffer)
        buffer = []
        ultima = giorno
    if buffer:
        if ultima not in giornate:
            giornate[ultima] = []
            ordine.append(ultima)
        giornate[ultima].extend(buffer)
    return sorted(((g, giornate[g]) for g in ordine), key=lambda x: (x[0] is None, x[0]))


def analizza_giornata(elenco):
    """Chiusure, valori e documenti di una porzione di file (una giornata)."""
    fiscale = chiusura_fiscale(elenco)
    pos = chiusure_pos(elenco)
    docs = scontrini(elenco)
    return {
        "testo": testo_pulito(elenco),
        "righe": len(elenco),
        "chiusure_pos": pos,
        "totale_pos": sum((p["totale_pos"] for p in pos if p["totale_pos"] is not None), Decimal("0")) if pos else None,
        "chiusura_fiscale": fiscale,
        "valori_fiscali": fiscale["valori"] if fiscale else {},
        "scontrini": docs,
        # Abortiti e buoni di reso non entrano nel totale giornaliero della cassa.
        "totale_scontrini": sum((d["totale"] for d in docs if d["totale"] is not None and not d["abortito"] and not d["reso"]),
                                Decimal("0")),
        "pagamenti": somma_pagamenti(docs),
        "pos_negate": pos_negate(elenco),
    }


def analizza(nome_file, raw):
    """
    Analizza un file SysSpy: data e cassa dal nome, poi una voce per ogni giornata
    contenuta nel file (di solito una sola).
    """
    elenco = righe(raw)
    data, cassa = data_e_cassa_da_nome(nome_file)
    giornate = []
    for giorno, parte in dividi_per_data(elenco, data):
        g = analizza_giornata(parte)
        g["data"] = giorno or data
        giornate.append(g)
    if cassa is None:
        cassa = next((g["valori_fiscali"].get("numero_cassa") for g in giornate if g["valori_fiscali"].get("numero_cassa")), None)
    if data is None and giornate:
        data = giornate[-1]["data"]
    return {
        "data_file": data,
        "cassa": cassa,
        "codice_negozio": codice_negozio(elenco),
        "cassieri": nomi_cassieri(elenco),
        "testo": testo_pulito(elenco),
        "righe": len(elenco),
        "giornate": giornate,
    }


def quadratura_pos(totale_pos, non_riscosso):
    """
    Il pagato con POS deve coincidere con il 'CORRISP. NON RISCOSSI' della chiusura
    fiscale. Restituisce la differenza (0 = quadra) o None se manca un dato.
    """
    if totale_pos is None or non_riscosso is None:
        return None
    return Decimal(totale_pos) - Decimal(non_riscosso)
