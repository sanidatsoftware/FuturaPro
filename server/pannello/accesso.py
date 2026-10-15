"""Com'è fatta la pagina di accesso: posizione e grandezza del logo, righe di testo della vetrina.

La compone il SystemAdministrator (Impostazioni · Aspetto interfaccia); i valori si controllano
qui, sia quando si salvano sia nell'anteprima dal vivo (che non salva nulla).
"""

import re

COLORE = re.compile(r"^#[0-9a-fA-F]{6}$")
POSIZIONI_LOGO = ["in_alto", "nel_messaggio", "al_centro"]
ALLINEAMENTI = ["sinistra", "centro"]
PESI = ["normale", "grassetto"]
# Lo stile della vetrina: «classico» (sfondo nel colore della piattaforma) oppure «oro», con il
# titolo dorato che scintilla, e «oro_animato», con in più lo sfondo animato (onde, bagliori).
STILI = ["classico", "oro", "oro_animato"]
# Sopra il titolo degli stili «oro»: il simbolo di FuturaPro (disegnato, animato), il logo
# caricato, o niente.
SIMBOLI = ["futurapro", "logo", "nessuno"]


def predefinita(sottotitolo: str = "") -> dict:
    return {
        "logo": {"posizione": "in_alto", "altezza": 64, "mostra_nome": True, "riquadro_barra": False},
        "allineamento": "sinistra",
        "mostra_schermi": True,
        "stile": "classico",
        "simbolo": "futurapro",
        # «Powered by» con il logo di chi fornisce il servizio (immagine caricata a parte).
        "powered": {"mostra": False, "testo": "Powered by"},
        "righe": [
            {"testo": sottotitolo or "Videocomunicazione per il punto vendita", "dimensione": 44, "peso": "grassetto", "colore": "#ffffff"},
            {"testo": "Monitor, totem ed eliminacode di tutti i punti vendita, da un'unica console.", "dimensione": 17, "peso": "normale", "colore": "#dbe3ee"},
        ],
    }


def _numero(valore, minimo, massimo, predefinito):
    try:
        return max(minimo, min(massimo, int(valore)))
    except (TypeError, ValueError):
        return predefinito


def pulita(dati, sottotitolo: str = "") -> dict:
    """I valori controllati; quello che manca o non va prende il valore di partenza."""
    base = predefinita(sottotitolo)
    if not isinstance(dati, dict) or not dati:
        return base
    logo = dati.get("logo") if isinstance(dati.get("logo"), dict) else {}
    powered = dati.get("powered") if isinstance(dati.get("powered"), dict) else {}
    righe = []
    for riga in (dati.get("righe") if isinstance(dati.get("righe"), list) else base["righe"])[:8]:
        if not isinstance(riga, dict):
            continue
        righe.append({
            "testo": str(riga.get("testo") or "")[:200],
            "dimensione": _numero(riga.get("dimensione"), 10, 96, 18),
            "peso": riga.get("peso") if riga.get("peso") in PESI else "normale",
            "colore": riga.get("colore") if isinstance(riga.get("colore"), str) and COLORE.match(riga.get("colore")) else "#ffffff",
        })
    return {
        "logo": {
            "posizione": logo.get("posizione") if logo.get("posizione") in POSIZIONI_LOGO else "in_alto",
            "altezza": _numero(logo.get("altezza"), 24, 360, 64),
            "mostra_nome": bool(logo.get("mostra_nome", True)),
            # Nella barra del pannello il logo sta direttamente sul colore; un riquadro chiaro
            # dietro serve solo ai loghi scuri, che altrimenti non si vedono.
            "riquadro_barra": bool(logo.get("riquadro_barra", False)),
        },
        "allineamento": dati.get("allineamento") if dati.get("allineamento") in ALLINEAMENTI else "sinistra",
        "mostra_schermi": bool(dati.get("mostra_schermi", True)),
        "stile": dati.get("stile") if dati.get("stile") in STILI else "classico",
        "simbolo": dati.get("simbolo") if dati.get("simbolo") in SIMBOLI else "futurapro",
        "powered": {
            "mostra": bool(powered.get("mostra", False)),
            "testo": str(powered.get("testo") if powered.get("testo") is not None else "Powered by")[:40],
        },
        "righe": righe,
    }
