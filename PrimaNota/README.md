# Prima Nota

Modulo Django del portale (accanto a Scansioni PV) per la documentazione di prima nota dei negozi.
Stesso login, stessi utenti Negozio/Ufficio e stessi negozi Baserow di Scansioni PV.

- **Negozio** (`/primanota/upload/`): carica le scansioni per genere — Chiusura fiscale, Chiusure POS
  bancari, Resi, Transazioni abortite, Versamenti contante — con data, cassa facoltativa e note.
  Invia note, anomalie e richieste di contatto all'ufficio.
- **Ufficio** (`/primanota/admin/`): scansioni raggruppate per negozio e giornata, flag *Lavorato*
  come in Scansioni PV; i Versamenti contante hanno in più il flag separato *Versamento lavorato*.
- **Giornata** (`/primanota/giornata/<negozio>/<data>/`): per ogni genere, le scansioni affiancate
  ai dati del SysSpy di ogni cassa (chiusura fiscale, chiusura POS, transazioni abortite, resi),
  con le quadrature: totale POS = corrispettivo non riscosso; somma scontrini = totale giornaliero.
- **Monitor** (`/primanota/monitor/`): tabella negozi × giorni come il Monitor Trasmissioni PV,
  con in più versamenti da lavorare, note aperte e casse SysSpy (in rosso se non quadrano).
- **Archivio SysSpy** (`/primanota/sysspy/`): file archiviati per negozio, data e cassa; ricerca nel
  testo; testo completo e download dell'originale.
- **Condivisioni negozi** (`/primanota/condivisioni/`, solo Amministratore): cartella di ogni
  negozio da cui prelevare i SysSpy, importazione di un negozio o di tutti, ricostruzione, orari
  dell'importazione automatica.

Chi vede la Prima Nota: gli utenti con la casella **Menu_PrimaNota** spuntata nella tabella Utenti
(Baserow) e sempre gli Amministratori.

## File SysSpy

Il nome `SysSpy.20260528.2` dà la data (28/05/2026) e la cassa (2); il negozio è quello della
condivisione da cui il file è prelevato (il codice letto nel file è solo un controllo).
Le prime 4 colonne di ogni riga (codice tecnico) vengono tolte nel testo archiviato e nelle anteprime,
mostrate in Consolas Regular 11 pt.

Dal file si estraggono: chiusura POS (con il foglio C.C.D. del cassiere), chiusura fiscale e i suoi
valori, gli scontrini con `OPERAZIONE ABORTITA`, storni, annullamenti di riga e pagamenti POS negati.
Il riconoscimento dei **resi** cerca la parola `RESO` nello scontrino: va verificato con un file che
contenga un reso vero.

L'originale è copiato in `<PRIMANOTA_ARCHIVIO_DIR>/<negozio>/<AAAA>/<MM>/<GG>/cassa_<n>/` con accanto
il testo pulito compresso (`.txt.gz`). Nel database restano solo i dati estratti, perché un file può
superare le 16.000 righe. Un file modificato in negozio viene riletto e sostituisce il precedente.

## Installazione nel portale

1. Copiare la cartella `primanota/` accanto a `scansioni/` nel progetto Django.
2. In `settings.py`:
   ```python
   INSTALLED_APPS += ["primanota"]
   BASEROW_PRIMANOTA_TABLE_ID = 000          # id della nuova tabella (punto 4)
   PRIMANOTA_ARCHIVIO_DIR = "/opt/tocal/primanota_archivio"
   # Facoltativo: campo booleano "Menu_PrimaNota" della tabella Utenti.
   # Se non impostato, vede la Prima Nota chi vede Scansioni PV.
   BASEROW_UTENTE_MENU_PRIMANOTA_FIELD = "field_0000"
   ```
3. In `urls.py`: `path("primanota/", include("primanota.urls")),`
4. In Baserow creare la tabella **Prima Nota Scansioni** con questi campi (i nomi devono essere
   esattamente questi, gli id non servono):

   | Campo | Tipo |
   |---|---|
   | Data Documento | Data |
   | Negozio | Collegamento a Negozi |
   | Attivo | Booleano |
   | Tipo Documento | Testo a riga singola |
   | Cassa | Numero |
   | Documento | File |
   | Note | Testo lungo |
   | Caricato Da | Collegamento a Utenti |
   | Data Upload | Data con ora |
   | Lavorato | Booleano |
   | Lavorato Da | Collegamento a Utenti |
   | Data Lavorazione | Data con ora |
   | Versamento Lavorato | Booleano |
   | Versamento Lavorato Da | Collegamento a Utenti |
   | Data Lavorazione Versamento | Data con ora |

5. Dipendenze: `pip install smbprotocol cryptography` (se non già presenti), poi
   `python manage.py migrate primanota`.
6. Nel menu del portale (`scansioni/menu.html`) aggiungere il link a `/primanota/`.
7. Importazione automatica dei SysSpy la sera, per avere tutto pronto il mattino dopo, ad esempio
   ogni 30 minuti dalle 20 alle 23 e una volta alle 6:
   ```
   */30 20-23 * * *  cd /opt/tocal/portale && python manage.py importa_sysspy >> /var/log/primanota.log 2>&1
   0 6 * * *         cd /opt/tocal/portale && python manage.py importa_sysspy >> /var/log/primanota.log 2>&1
   ```
   Se il portale gira in Docker: `docker compose exec -T <servizio> python manage.py importa_sysspy`.

Il server deve raggiungere le condivisioni SMB sulla porta 445; in alternativa montare le cartelle sul
server e indicare il percorso locale (es. `/mnt/negozi/5048`).

Non cambiare la `SECRET_KEY` del portale: cifra le password delle condivisioni.

## Test

```bash
pip install "Django>=4.2" requests cryptography
DJANGO_SETTINGS_MODULE=tests.settings python -m django test tests
```

I test usano una copia di `scansioni/services` del portale (`tests/portale/`), un Baserow finto in
memoria e un SysSpy ridotto e anonimizzato (`tests/dati/`).
