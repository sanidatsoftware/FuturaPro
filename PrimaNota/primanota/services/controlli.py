"""
Controlli di quadratura di una cassa in una giornata, con la spiegazione in chiaro.

Sul SysSpy si confrontano tre fonti indipendenti:
- la chiusura POS (stampata dal terminale bancario: quanto ha incassato con le carte);
- la chiusura fiscale (stampata dalla cassa: totale giornaliero, corrispettivo non riscosso);
- gli scontrini emessi nella giornata (somma dei totali e come sono stati pagati).
Sui file verificati (Motta, 28/05/2026) Carta Credito + Bancomat negli scontrini =
chiusura POS = CORRISP. NON RISCOSSI, e la somma degli scontrini = TOTALE GIORNALIERO.
"""

from decimal import Decimal

OK = "ok"
ATTENZIONE = "attenzione"
INFO = "info"


def _euro(valore):
    if valore is None:
        return "—"
    testo = f"{Decimal(valore):,.2f}"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _scontrini_con_importo(f, importo, indice):
    """Scontrini del file il cui importo (indice 2 = totale, 3 = pagato POS) è uguale alla differenza."""
    out = []
    for riga in f.elenco_scontrini or []:
        valore = riga[indice]
        if valore is not None and abs(Decimal(valore)) == abs(importo) and not riga[4]:
            out.append(f"DOC.{riga[0]} delle {riga[1]}")
    return out


def _indizio(f, differenza, indice, dettagli=True):
    if not dettagli:
        return ""
    candidati = _scontrini_con_importo(f, differenza, indice)
    if not candidati:
        return ""
    if len(candidati) > 3:
        return f" Ci sono {len(candidati)} scontrini di {_euro(abs(differenza))}: aprire il testo completo per verificarli."
    return f" Importo uguale a: {', '.join(candidati)}."


def controlli(f, dettagli=True):
    """Elenco di dict {nome, esito, titolo, spiegazione, valori: [(etichetta, importo)]}."""
    if f.cassa_vuota:
        return [{"nome": "Cassa", "esito": INFO, "titolo": "Cassa non usata",
                 "spiegazione": "Chiusura fiscale a zero e nessuno scontrino nel file: la cassa è rimasta chiusa "
                                "(il numero scontrini fiscali 1 è la chiusura stessa).", "valori": []}]
    out = []

    # 1. POS: terminale bancario, cassa (fiscale) e scontrini devono dire la stessa cifra.
    pos, fiscale, scontrini = f.totale_pos, f.corrisp_non_riscosso, f.pagato_pos
    valori = [("Chiusura POS (terminale bancario)", pos),
              ("Corrisp. non riscosso (chiusura fiscale)", fiscale),
              ("Carta Credito + Bancomat negli scontrini", scontrini)]
    if pos is None:
        out.append({"nome": "POS", "esito": INFO, "titolo": "Chiusura POS non trovata",
                    "spiegazione": "Nel SysSpy di questa giornata non c'è la stampa «CHIUSURA ... TOTALE POS EUR». "
                                   "Può essere stata fatta il giorno dopo (controllare la giornata successiva) "
                                   "o direttamente sul terminale senza stampa in cassa.", "valori": valori})
    elif fiscale is None:
        out.append({"nome": "POS", "esito": INFO, "titolo": "Chiusura fiscale non trovata",
                    "spiegazione": "Senza chiusura fiscale non si può confrontare il POS.", "valori": valori})
    elif pos == fiscale and (scontrini is None or scontrini == pos):
        out.append({"nome": "POS", "esito": OK, "titolo": "POS quadrato",
                    "spiegazione": "Terminale bancario, chiusura fiscale e scontrini riportano lo stesso importo "
                                   "pagato con carte.", "valori": valori})
    else:
        diff = pos - fiscale
        if scontrini is not None and scontrini == pos:
            causa = ("Gli scontrini confermano l'importo del terminale: è la chiusura fiscale a riportare un "
                     "«non riscosso» diverso. Verificare che la chiusura fiscale sia stata fatta dopo l'ultima "
                     "vendita e che le forme di pagamento della cassa siano configurate correttamente.")
        elif scontrini is not None and scontrini == fiscale:
            causa = (f"Cassa e scontrini sono d'accordo tra loro, ma il terminale POS ha incassato "
                     f"{_euro(abs(diff))} {'in più' if diff > 0 else 'in meno'}. Cause tipiche: il terminale è "
                     "condiviso con un'altra cassa, una carta è stata passata senza registrarla in cassa "
                     "(o registrata come contanti), oppure la chiusura POS comprende anche il giorno prima.")
            causa += _indizio(f, diff, 3, dettagli)
        else:
            causa = ("Le tre cifre sono tutte diverse: confrontare la chiusura POS con le singole transazioni "
                     "nel testo completo del SysSpy.")
        out.append({"nome": "POS", "esito": ATTENZIONE, "titolo": f"Differenza POS {_euro(diff)}",
                    "spiegazione": causa, "valori": valori})

    # 2. Somma degli scontrini = TOTALE GIORNALIERO della chiusura fiscale.
    totale, somma = f.totale_giornaliero, f.totale_scontrini
    valori = [("Totale giornaliero (chiusura fiscale)", totale),
              ("Somma degli scontrini nel file (esclusi abortiti)", somma)]
    if totale is not None and somma is not None:
        diff = somma - totale
        if diff == 0:
            out.append({"nome": "Scontrini", "esito": OK, "titolo": "Scontrini quadrati",
                        "spiegazione": "La somma degli scontrini del file è uguale al totale della chiusura fiscale.",
                        "valori": valori})
        elif diff > 0:
            out.append({"nome": "Scontrini", "esito": ATTENZIONE, "titolo": f"Scontrini +{_euro(diff)}",
                        "spiegazione": f"Nel file ci sono scontrini per {_euro(diff)} in più del totale fiscale: "
                                       "di solito uno scontrino che la cassa non conta nel giornaliero (annullato "
                                       "dopo l'emissione, documento di annullo/reso, o stampato dopo la chiusura)."
                                       + _indizio(f, diff, 2, dettagli), "valori": valori})
        else:
            out.append({"nome": "Scontrini", "esito": ATTENZIONE, "titolo": f"Scontrini {_euro(diff)}",
                        "spiegazione": f"Al file mancano scontrini per {_euro(-diff)} rispetto al totale fiscale: "
                                       "il SysSpy è incompleto oppure una parte della giornata è in un altro file.",
                        "valori": valori})

    # 3. Numero di documenti: la chiusura fiscale conta anche se stessa.
    if f.num_scontrini_fiscali:
        attesi = f.num_scontrini_fiscali - 1
        if f.scontrini_trovati != attesi:
            out.append({"nome": "Documenti", "esito": ATTENZIONE,
                        "titolo": f"Documenti {f.scontrini_trovati} su {attesi}",
                        "spiegazione": f"La chiusura fiscale indica {f.num_scontrini_fiscali} documenti "
                                       f"(chiusura compresa), cioè {attesi} scontrini; nel file ne risultano "
                                       f"{f.scontrini_trovati}. "
                                       + ("C'è uno scontrino in più nel file: probabilmente quello che spiega la "
                                          "differenza sugli scontrini." if f.scontrini_trovati > attesi else
                                          "Mancano scontrini nel file."),
                        "valori": []})
    return out


def quadrato(f):
    return all(c["esito"] != ATTENZIONE for c in controlli(f, dettagli=False))

