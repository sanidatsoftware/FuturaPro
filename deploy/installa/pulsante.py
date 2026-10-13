#!/usr/bin/env python3
"""Pulsante dell'eliminacode FuturaPro: sostituisce gli script py/*+.py e *-.py.

    python pulsante.py https://SERVER CHIAVE avanti
    python pulsante.py https://SERVER CHIAVE indietro
    python pulsante.py https://SERVER CHIAVE ripeti
    python pulsante.py https://SERVER CHIAVE imposta 27

La CHIAVE è quella del reparto: nel pannello, Reparti -> «Crea collegamento»; è
la parte dopo «#chiave=» del collegamento. Se il server usa il certificato
interno, scaricalo da http://SERVER/futurapro-ca.crt e passalo con --ca.
Solo libreria standard di Python 3: niente da installare.
"""

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description="Pulsante dell'eliminacode FuturaPro")
    parser.add_argument("server", help="es. https://10.0.100.41")
    parser.add_argument("chiave")
    parser.add_argument("operazione", choices=["avanti", "indietro", "ripeti", "azzera", "imposta"])
    parser.add_argument("numero", nargs="?", type=int, help="solo per imposta")
    parser.add_argument("--ca", help="certificato del server (futurapro-ca.crt) se è interno")
    argomenti = parser.parse_args()

    server = argomenti.server if "://" in argomenti.server else f"https://{argomenti.server}"
    corpo = json.dumps({"numero": argomenti.numero} if argomenti.operazione == "imposta" else {}).encode()
    richiesta = urllib.request.Request(
        f"{server.rstrip('/')}/api/eliminacode/pulsante/{argomenti.operazione}/",
        data=corpo,
        method="POST",
        headers={"Authorization": f"Pulsante {argomenti.chiave}", "Content-Type": "application/json"},
    )
    contesto = ssl.create_default_context(cafile=argomenti.ca) if argomenti.ca else None
    try:
        with urllib.request.urlopen(richiesta, timeout=10, context=contesto) as risposta:
            stato = json.load(risposta)
    except urllib.error.HTTPError as errore:
        sys.exit(f"Errore {errore.code}: {errore.read().decode(errors='replace')}")
    except (urllib.error.URLError, TimeoutError) as errore:
        sys.exit(f"Server non raggiungibile: {errore}")
    print(f"{stato['nome']}: numero {stato['numero']}, in coda {stato['in_coda']}")


if __name__ == "__main__":
    main()
