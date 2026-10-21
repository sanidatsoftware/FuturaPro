"""
Consultazione della Prima Nota dalla cassa centrale (ONLCassaCentrale), come la «Registrazione
movimenti da modello: PRIMA NOTA» del gestionale: per punto vendita e giorno, le causali del
modello con entrate, uscite ed evidenze, i movimenti di ogni causale e i riepiloghi
Ripresa / Periodo / Progressivo.

Colonna dal campo segno: «+» entrate, «-» uscite, «E» evidenze. Le righe annullate
(data_ann valorizzata) non si contano.
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from .cassa_centrale import NON_CONFIGURATO, configurazione, esegui

ZERO = Decimal("0")

# Causali del modello PRIMA NOTA, nell'ordine del gestionale. Descrizioni di riserva se manca TBCausCC.
MODELLO = [
    (1, "CORRISPETTIVI FISCALI"), (15, "SCONTRINI DI RESO"), (14, "DOCUMENTI DA SCONTRINO"),
    (16, "DOCUMENTI A CREDITO"), (2, "CONTANTI"), (3, "ASSEGNI"), (4, "BANCOMAT"), (5, "CARTE DI CREDITO"),
    (6, "BUONI SCONTO"), (7, "BUONI PASTO"), (18, "B.Pasto EDENRED"), (19, "B.Pasto DAY"),
    (20, "B.Pasto PELLEGRINI"), (21, "B.Pasto PLUXEE"), (22, "B.Pasto 365 WELFARE"), (23, "B.Pasto EP"),
    (24, "B.Pasto POSTE WELFARE"), (25, "B.Pasto CLIK APP TODUBA"), (8, "COUPON"), (9, "CREDITO"),
    (10, "AMMANCHI"), (11, "ESUBERI"), (12, "VERSAMENTO BANCA"), (13, "SPESE DEL GIORNO"),
    (17, "SPESE DEL GIORNO CON FATTURA"),
]
COLONNA = {"+": "entrate", "-": "uscite", "E": "evidenze"}
NON_ANNULLATA = "ISNULL(r.data_ann, 0) = 0"

QUERY_MOVIMENTI = """
SELECT r.*, caus.descr AS causale_descr, n.NomeNegozio AS nome_negozio
  FROM WEBNETSRV.newdis.dbo.ONLCassaCentrale AS r
  LEFT JOIN WEBNETSRV.newdis.dbo.TBCausCC AS caus ON caus.codice = r.Causale
  LEFT JOIN Statistiche.dbo.Negozi AS n ON n.CodiceNegozio = r.pv
 WHERE r.data BETWEEN %s AND %s
   AND {non_annullata}
   {filtro_pv}
 ORDER BY r.pv, r.data, r.progressivo
"""

# Totali di tutti i movimenti precedenti al primo giorno: la «Ripresa».
QUERY_RIPRESA = """
SELECT r.pv,
       SUM(CASE WHEN r.segno = '+' THEN r.importo ELSE 0 END) AS entrate,
       SUM(CASE WHEN r.segno = '-' THEN r.importo ELSE 0 END) AS uscite,
       SUM(CASE WHEN r.segno = 'E' THEN r.importo ELSE 0 END) AS evidenze,
       COUNT(*) AS movimenti
  FROM WEBNETSRV.newdis.dbo.ONLCassaCentrale AS r
 WHERE r.data < %s
   AND {non_annullata}
   {filtro_pv}
 GROUP BY r.pv
"""

# Campi mostrati per primi nel dettaglio di un movimento, con un'etichetta leggibile.
ETICHETTE = OrderedDict([
    ("anno", "Anno"), ("progressivo", "Progressivo"), ("ora", "Ora"), ("causale", "Causale"),
    ("tender", "Tender"), ("aliq_iva", "Aliquota IVA"), ("cod_legge_iva", "Codice legge IVA"),
    ("imponibile", "Imponibile"), ("iva", "IVA"), ("importo", "Importo"), ("segno", "Segno"),
    ("importo_ori", "Importo originale"), ("int_tipo", "Intestatario: tipo"), ("int_cod", "Intestatario: codice"),
    ("int_ragsoc", "Intestatario / descrizione"), ("cod_fisc", "Codice fiscale"),
    ("tipo_doc_rif", "Tipo documento"), ("num_doc_rif", "Numero documento"), ("data_doc_rif", "Data documento"),
    ("cod_riferimento", "Codice riferimento"), ("conto_avere", "Conto avere"),
    ("anno_dist", "Anno distinta"), ("num_dist", "Numero distinta"), ("data_scadenza", "Scadenza"),
    ("data_incasso", "Data incasso"), ("flag_gen", "Flag generazione"),
    ("data_agg", "Aggiornato il"), ("ora_agg", "Aggiornato alle"), ("utente_agg", "Aggiornato da"),
    ("data_cert", "Certificato il"), ("ora_cert", "Certificato alle"), ("utente_cert", "Certificato da"),
    ("data_valid", "Validato il"), ("cod_valid", "Codice validazione"), ("iban", "IBAN"),
])
NON_IN_DETTAGLIO = {"pv", "data", "note", "causale_descr", "nome_negozio"}


def _testo(valore):
    return "" if valore is None else str(valore).strip()


def _data(valore):
    """20261019 o '20261019' → date; None se vuota (00000000)."""
    t = _testo(valore).split(".")[0].zfill(8)
    try:
        return date(int(t[:4]), int(t[4:6]), int(t[6:8])) if t.strip("0") else None
    except ValueError:
        return None


def _ora(valore):
    t = _testo(valore).split(".")[0]
    if not t.strip("0"):
        return ""
    t = t.zfill(6)
    return f"{t[:2]}:{t[2:4]}:{t[4:6]}"


def _importo(valore):
    try:
        return Decimal(str(valore if valore is not None else 0))
    except ArithmeticError:
        return ZERO


def _valore_dettaglio(chiave, valore):
    if chiave.startswith("data"):
        d = _data(valore)
        return d.strftime("%d/%m/%Y") if d else ""
    if chiave.startswith("ora"):
        return _ora(valore)
    if isinstance(valore, (int, float, Decimal)) and not isinstance(valore, bool):
        return "" if valore == 0 else str(valore)
    return _testo(valore)


def _dettagli(riga):
    """Tutti i campi valorizzati del movimento, prima quelli noti, poi gli altri."""
    out = []
    for chiave in list(ETICHETTE) + sorted(k for k in riga if k not in ETICHETTE):
        if chiave in NON_IN_DETTAGLIO or chiave not in riga:
            continue
        v = _valore_dettaglio(chiave, riga[chiave])
        if v:
            out.append((ETICHETTE.get(chiave, chiave.replace("_", " ").capitalize()), v))
    return out


def _movimento(riga):
    tipo, numero, data_doc = _testo(riga.get("tipo_doc_rif")), _testo(riga.get("num_doc_rif")), _data(riga.get("data_doc_rif"))
    numero_doc = " ".join(x for x in (tipo, numero) if x)
    documento = f"{numero_doc} del {data_doc:%d/%m/%Y}" if numero_doc and data_doc else numero_doc
    certificato = _data(riga.get("data_cert"))
    return {
        "numero_doc": numero_doc, "data_doc": data_doc,
        "certificato": (f"Certificato il {certificato:%d/%m/%Y} {_ora(riga.get('ora_cert'))} da {_testo(riga.get('utente_cert'))}"
                        if certificato else ""),
        "progressivo": riga.get("progressivo"), "ora": _ora(riga.get("ora")),
        "causale": int(riga.get("causale") or 0), "importo": _importo(riga.get("importo")),
        "colonna": COLONNA.get(_testo(riga.get("segno")).upper(), "evidenze"),
        "descrizione": _testo(riga.get("int_ragsoc")), "documento": documento,
        "note": " ".join(_testo(riga.get("note")).split()), "dettagli": _dettagli(riga),
    }


def _filtro(punti_vendita):
    return f"AND r.pv IN ({', '.join(['%s'] * len(punti_vendita))})" if punti_vendita else ""


def interroga(data_da, data_a, punti_vendita=()):
    """
    Giornate di prima nota (per punto vendita e giorno, solo quelle con movimenti), in ordine
    di punto vendita e data. Date ISO.
    """
    c = configurazione()
    if not c:
        raise RuntimeError(NON_CONFIGURATO)
    punti_vendita = [str(p).strip() for p in punti_vendita if str(p).strip()]
    filtro = _filtro(punti_vendita)
    da, a = data_da.replace("-", ""), data_a.replace("-", "")
    righe = esegui(c, QUERY_MOVIMENTI.format(non_annullata=NON_ANNULLATA, filtro_pv=filtro),
                   (da, a, *punti_vendita), dizionari=True)
    if not righe:
        return []
    pv_trovati = sorted({_testo(r.get("pv")) for r in righe})
    ripresa = {_testo(r[0]): {"entrate": _importo(r[1]), "uscite": _importo(r[2]), "evidenze": _importo(r[3]),
                              "movimenti": int(r[4] or 0)}
               for r in esegui(c, QUERY_RIPRESA.format(non_annullata=NON_ANNULLATA, filtro_pv=_filtro(pv_trovati)),
                               (da, *pv_trovati))}
    return componi(righe, ripresa)


def componi(righe, ripresa):
    """Righe della query (dict) → giornate; ripresa: totali per pv prima del primo giorno."""
    giornate = OrderedDict()
    for riga in righe:
        pv, giorno = _testo(riga.get("pv")), _data(riga.get("data"))
        g = giornate.setdefault((pv, giorno), {"pv": pv, "nome": _testo(riga.get("nome_negozio")), "data": giorno,
                                               "descrizioni": {}, "movimenti": []})
        m = _movimento(riga)
        g["movimenti"].append(m)
        if _testo(riga.get("causale_descr")):
            g["descrizioni"][m["causale"]] = _testo(riga.get("causale_descr"))
    progressivi = {pv: dict(v) for pv, v in ripresa.items()}
    out = []
    for (pv, giorno), g in giornate.items():
        rip = progressivi.get(pv, {"entrate": ZERO, "uscite": ZERO, "evidenze": ZERO, "movimenti": 0})
        g["ripresa"] = dict(rip, data=giorno - timedelta(days=1) if giorno else None)
        periodo = {"entrate": ZERO, "uscite": ZERO, "evidenze": ZERO, "movimenti": len(g["movimenti"])}
        for m in g["movimenti"]:
            periodo[m["colonna"]] += m["importo"]
        g["periodo"] = dict(periodo, data=giorno)
        g["progressivo"] = {k: rip[k] + periodo[k] for k in ("entrate", "uscite", "evidenze", "movimenti")}
        g["progressivo"]["data"] = giorno
        progressivi[pv] = {k: g["progressivo"][k] for k in ("entrate", "uscite", "evidenze", "movimenti")}
        g["causali"] = _causali(g)
        out.append(g)
    return out


def _causali(g):
    """Tutte le causali del modello (anche senza movimenti) e quelle extra trovate, con righe e totali."""
    per_causale = OrderedDict()
    for codice, descrizione in MODELLO:
        per_causale[codice] = {"codice": codice, "descrizione": g["descrizioni"].get(codice, descrizione), "movimenti": []}
    for m in g["movimenti"]:
        per_causale.setdefault(m["causale"], {"codice": m["causale"], "movimenti": [],
                                              "descrizione": g["descrizioni"].get(m["causale"], f"Causale {m['causale']}")})
        per_causale[m["causale"]]["movimenti"].append(m)
    for c in per_causale.values():
        for col in ("entrate", "uscite", "evidenze"):
            movimenti = [m for m in c["movimenti"] if m["colonna"] == col]
            c[col] = sum((m["importo"] for m in movimenti), ZERO) if movimenti else None
        c["note"] = sum(1 for m in c["movimenti"] if m["note"])
    return list(per_causale.values())


# ---------------------------------------------------------------- spese del giorno con fattura

CAUSALE_SPESE_FATTURA = 17

QUERY_PRESENZE = """
SELECT r.pv, r.data, COUNT(*),
       SUM(CASE WHEN r.causale = 17 THEN 1 ELSE 0 END),
       SUM(CASE WHEN r.causale = 17 THEN r.importo ELSE 0 END),
       SUM(CASE WHEN ISNULL(r.data_cert, 0) = 0 THEN 1 ELSE 0 END)
  FROM WEBNETSRV.newdis.dbo.ONLCassaCentrale AS r
 WHERE r.data BETWEEN %s AND %s
   AND {non_annullata}
   {filtro_pv}
 GROUP BY r.pv, r.data
"""


def presenze(dal, al, codici=(), fresca=False):
    """
    {(pv, giorno): {"movimenti", "fatture", "importo_fatture", "certificata"}} per sapere quali giornate hanno
    la prima nota (e se è certificata: tutti i movimenti con data di certificazione) e spese del giorno con fattura (causale 17). None se il database non è configurato o non risponde:
    in quel caso la scansione della fattura resta caricabile ma non obbligatoria. Risultato tenuto 10 minuti;
    fresca=True rilegge comunque il database (per sapere subito se il negozio ha appena certificato).
    """
    from django.core.cache import cache

    c = configurazione()
    if not c:
        return None
    codici = sorted({str(x).strip() for x in codici if str(x).strip()})
    chiave = f"primanota:presenze2:{dal}:{al}:{','.join(codici)}"
    trovato = cache.get(chiave)
    if trovato == "non raggiungibile":
        return None
    if trovato is not None and not fresca:
        return trovato
    try:
        righe = esegui(c, QUERY_PRESENZE.format(non_annullata=NON_ANNULLATA, filtro_pv=_filtro(codici)),
                       (str(dal).replace("-", ""), str(al).replace("-", ""), *codici))
    except RuntimeError:
        # Database non raggiungibile: si riprova fra due minuti, senza far aspettare ogni pagina.
        cache.set(chiave, "non raggiungibile", 120)
        return None
    out = {}
    for pv, giorno, movimenti, fatture, importo, *resto in righe:
        g = _data(giorno)
        if g:
            out[(_testo(pv), g)] = {"movimenti": int(movimenti or 0), "fatture": int(fatture or 0),
                                    "importo_fatture": _importo(importo),
                                    "certificata": bool(movimenti) and not int((resto or [0])[0] or 0)}
    cache.set(chiave, out, 600)
    return out


def spese_con_fattura(codice_pv, giorno):
    """Movimenti «spese del giorno con fattura» di un punto vendita e giorno (descrizione, documento, importo, note)."""
    c = configurazione()
    if not c:
        raise RuntimeError(NON_CONFIGURATO)
    data = str(giorno).replace("-", "")
    righe = esegui(c, QUERY_MOVIMENTI.format(non_annullata=NON_ANNULLATA, filtro_pv="AND r.pv = %s AND r.causale = %s"),
                   (data, data, str(codice_pv), CAUSALE_SPESE_FATTURA), dizionari=True)
    return [_movimento(r) for r in righe]


def prima_nota_pronta(codice_pv, giorno):
    """
    Se il negozio può caricare le scansioni della giornata: la prima nota deve esserci ed essere certificata.
    None se non si può sapere (database non configurato o non raggiungibile): allora non si blocca niente.
    """
    p = presenze(giorno, giorno, [codice_pv], fresca=True)
    if p is None:
        return None
    g = p.get((str(codice_pv).strip(), giorno))
    if not g:
        return "mancante"
    return "pronta" if g["certificata"] else "non_certificata"


def non_certificati(codice_pv, giorno):
    """I movimenti della giornata ancora senza certificazione (data_cert vuota), per dire al negozio quali sono."""
    c = configurazione()
    if not c:
        return []
    data = str(giorno).replace("-", "")
    try:
        righe = esegui(c, QUERY_MOVIMENTI.format(non_annullata=NON_ANNULLATA,
                                                 filtro_pv="AND r.pv = %s AND ISNULL(r.data_cert, 0) = 0"),
                       (data, data, str(codice_pv)), dizionari=True)
    except RuntimeError:
        return []
    return [{**_movimento(r), "causale_descr": _testo(r.get("causale_descr"))} for r in righe]
