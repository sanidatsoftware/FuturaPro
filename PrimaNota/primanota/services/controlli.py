"""
Controlli di quadratura di una cassa in una giornata, con la spiegazione in chiaro.

Sul SysSpy si confrontano tre fonti indipendenti:
- la chiusura POS (stampata dal terminale bancario: quanto ha incassato con le carte);
- la chiusura fiscale (stampata dalla cassa: totale giornaliero, corrispettivo non riscosso);
- gli scontrini emessi nella giornata (somma dei totali e come sono stati pagati).
Sui file verificati (Motta, Adrano, Librino) Carta Credito + Bancomat negli scontrini =
chiusura POS, e la somma degli scontrini (esclusi abortiti e buoni di reso) = TOTALE GIORNALIERO.
Il CORRISP. NON RISCOSSI dipende da come è configurata la cassa: carte, oppure buoni pasto + crediti.
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

    # 1. POS: quanto ha incassato il terminale bancario = Carta Credito + Bancomat negli scontrini.
    pos, scontrini = f.totale_pos, f.pagato_pos
    valori = [("Chiusura POS (terminale bancario)", pos), ("Carta Credito + Bancomat negli scontrini", scontrini)]
    if pos is None:
        out.append({"nome": "POS", "esito": INFO, "titolo": "Chiusura POS non nel SysSpy",
                    "spiegazione": "In questa giornata la cassa non ha stampato la chiusura del terminale "
                                   "(«CHIUSURA ... TOTALE POS EUR»): può essere stata fatta direttamente sul terminale, "
                                   "il giorno dopo, o da un'altra cassa. Le carte registrate negli scontrini sono "
                                   f"{_euro(scontrini)}: confrontarle con la scansione della chiusura POS.",
                    "valori": valori})
    elif scontrini is None or pos == scontrini:
        out.append({"nome": "POS", "esito": OK, "titolo": "POS quadrato",
                    "spiegazione": "Il terminale bancario ha incassato esattamente le carte registrate negli scontrini.",
                    "valori": valori})
    else:
        diff = pos - scontrini
        out.append({"nome": "POS", "esito": ATTENZIONE, "titolo": f"Differenza POS {_euro(diff)}",
                    "spiegazione": f"Il terminale ha incassato {_euro(abs(diff))} {'in più' if diff > 0 else 'in meno'} "
                                   "delle carte registrate negli scontrini. Cause tipiche: terminale usato anche da "
                                   "un'altra cassa, carta passata senza registrarla in cassa (o registrata come "
                                   "contanti), chiusura POS che comprende anche il giorno prima." + _indizio(f, diff, 3, dettagli),
                    "valori": valori})

    # 2. Corrispettivo non riscosso della chiusura fiscale: le casse sono configurate in due modi.
    nr = f.corrisp_non_riscosso
    if nr is not None:
        valori = [("Corrisp. non riscosso (chiusura fiscale)", nr),
                  ("Carta Credito + Bancomat negli scontrini", f.pagato_pos),
                  ("Buoni Pasto + Credito negli scontrini", f.buoni_e_crediti)]
        configurazione = f.configurazione_non_riscosso
        if configurazione == "carte":
            out.append({"nome": "Non riscosso", "esito": OK, "titolo": "Non riscosso = carte",
                        "spiegazione": "Questa cassa registra come «non riscosso» i pagamenti con carta "
                                       "(i buoni pasto sono conteggiati come riscosso).", "valori": valori})
        elif configurazione == "buoni":
            out.append({"nome": "Non riscosso", "esito": OK, "titolo": "Non riscosso = buoni e crediti",
                        "spiegazione": "Questa cassa registra come «non riscosso» buoni pasto e vendite a credito "
                                       "(le carte sono conteggiate come riscosso).", "valori": valori})
        else:
            out.append({"nome": "Non riscosso", "esito": ATTENZIONE, "titolo": f"Non riscosso {_euro(nr)} non spiegato",
                        "spiegazione": "Il corrispettivo non riscosso della chiusura fiscale non corrisponde né alle carte né "
                                       "a buoni pasto + crediti registrati negli scontrini: verificare le forme di "
                                       "pagamento usate nella giornata.", "valori": valori})

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
                                       "dopo l'emissione o stampato dopo la chiusura). I buoni di reso sono già esclusi dalla somma."
                                       + _indizio(f, diff, 2, dettagli), "valori": valori})
        else:
            out.append({"nome": "Scontrini", "esito": ATTENZIONE, "titolo": f"Scontrini {_euro(diff)}",
                        "spiegazione": f"Al file mancano scontrini per {_euro(-diff)} rispetto al totale fiscale: "
                                       "il SysSpy è incompleto oppure una parte della giornata è in un altro file.",
                        "valori": valori})

    return out


def quadrato(f):
    return all(c["esito"] != ATTENZIONE for c in controlli(f, dettagli=False))

