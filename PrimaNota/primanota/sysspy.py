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

NOME_FILE_RE = re.compile(r"^SysSpy\.(\d{8})\.(\d+)$", re.I)
TIMESTAMP_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})")
DOC_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})\s+DOC\.(\S+)")
IMPORTO_RE = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}|-?\d+)\s*$")
RESO_RE = re.compile(r"\bRESO\b")

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


def chiusure_pos(elenco):
    """Ogni chiusura POS: dal 'NON  FISCALE' che la apre fino alla stampa del cassiere che la segue."""
    out = []
    for i, (codice, testo) in enumerate(elenco):
        if codice != "9832" or not testo.strip().startswith("TOTALE POS EUR"):
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
        for _, t in elenco[i:fine + 1]:
            if t.strip().startswith("TOTALE HOST EUR"):
                host = importo(t)
                break
        out.append({
            "testo": _testo(elenco, inizio, fine),
            "totale_pos": importo(testo),
            "totale_host": host,
            "esito": "ESEGUITA" if any("OPERAZIONE ESEGUITA" in t for _, t in elenco[i:fine + 1]) else "",
        })
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
            "numero": m.group(3),
            "ora": m.group(2),
            "totale": totale,
            "abortito": any(c == "1600" or "OPERAZIONE ABORTITA" in t for c, t in blocco),
            "annullato": any("SCONTRINO ANNULLATO" in t for t in testi),
            "storni": sum("Inizio Storno" in t for t in testi),
            "annullamenti_riga": sum("INIZIO ANNULLAMENTO" in t for t in testi),
            "reso": any(RESO_RE.search(t.upper()) for c, t in blocco if c != "9949"),
            "testo": _testo(elenco, inizio, i),
        })
        inizio = i + 1
    return out


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


def analizza(nome_file, raw):
    """
    Analizza un file SysSpy e restituisce tutto ciò che serve all'archivio:
    testo pulito, data, cassa, chiusure, valori e documenti particolari.
    """
    elenco = righe(raw)
    data, cassa = data_e_cassa_da_nome(nome_file)
    fiscale = chiusura_fiscale(elenco)
    valori = fiscale["valori"] if fiscale else {}
    if cassa is None and valori.get("numero_cassa"):
        cassa = valori["numero_cassa"]
    if data is None:
        for _, t in elenco:
            m = TIMESTAMP_RE.match(t)
            if m:
                data = datetime.strptime(m.group(1), "%d/%m/%Y").date()
                break
    pos = chiusure_pos(elenco)
    totale_pos = sum((p["totale_pos"] for p in pos if p["totale_pos"] is not None), Decimal("0")) if pos else None
    docs = scontrini(elenco)
    # Gli scontrini abortiti non entrano nel totale giornaliero della cassa.
    totale_scontrini = sum((d["totale"] for d in docs if d["totale"] is not None and not d["abortito"]), Decimal("0"))
    return {
        "data": data,
        "cassa": cassa,
        "codice_negozio": codice_negozio(elenco),
        "testo": testo_pulito(elenco),
        "righe": len(elenco),
        "chiusure_pos": pos,
        "totale_pos": totale_pos,
        "chiusura_fiscale": fiscale,
        "valori_fiscali": valori,
        "scontrini": docs,
        "totale_scontrini": totale_scontrini,
        "pos_negate": pos_negate(elenco),
    }


def quadratura_pos(totale_pos, non_riscosso):
    """
    Il pagato con POS deve coincidere con il 'CORRISP. NON RISCOSSI' della chiusura
    fiscale. Restituisce la differenza (0 = quadra) o None se manca un dato.
    """
    if totale_pos is None or non_riscosso is None:
        return None
    return Decimal(totale_pos) - Decimal(non_riscosso)
