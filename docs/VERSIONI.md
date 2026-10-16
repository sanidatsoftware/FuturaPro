# Versioni di FuturaPro

La versione si legge nella pagina di accesso e nella barra del pannello, accanto al nome
(es. **ver. 1.6.072 · 20261015**): `RELEASE.build · AAAAMMGG`.

- **RELEASE** (`1.6`) si cambia a mano in `server/futurapro/versione.py` quando si battezza una
  release, e si annota qui sotto.
- **build** cresce da solo: è il numero di modifiche del codice (commit). Sul server lo scrive
  `deploy/aggiorna.sh` a ogni aggiornamento.
- **AAAAMMGG** è la data (anno, mese, giorno) dell'ultima modifica del codice installato.
- Il player web porta la stessa release più un'impronta dei suoi file (es. `web-1.6-3600b30`) e
  si aggiorna da solo; il servizio code del totem ha il suo numero (`code-totem.ps1`).

## 1.6 — 15 ottobre 2026

Prima release con numero di versione visibile. Oltre alla base (contenuti, campagne e promozioni,
layout video, eliminacode, player per monitor e totem, teleassistenza, registro), comprende:

- **Panoramica** come pagina iniziale, con gli avvisi da guardare e il riepilogo di schermi,
  contenuti, palinsesto, code, plugin e spazio; vista di tutte le aziende per il SystemAdministrator.
- **Distribuzione contenuti**: avanzamento dei download per schermo, negozio e promozione, e cosa
  va in onda.
- **Plugin** Info Prezzo e Info Ingredienti, con copia dei file dal PC del negozio e prova di accesso.
- **Layout Ticket** componibile, guidato o libero, con ridimensionamento a mano.
- **Pagina di accesso** componibile, con gli stili «Oro» e «Oro con sfondo animato»; icona
  della piattaforma.
- **Profilo** personale e **utenti di piattaforma** (altri SystemAdministrator e tecnici).
- **Player**: aggiornamento automatico alle versioni nuove, funzionamento senza server anche dopo
  un riavvio, download senza tenere i file in memoria; **guardiano** di Windows che riapre il
  browser se la pagina si blocca.
- **Installazione** dei PC con i comandi pronti nel pannello: le impronte dei certificati le
  controlla lo script.

### Dopo la 1.6

- **Stampanti Epson di rete** (servizio code `1.6.5`): il totem stampa passando dal suo servizio
  code, che chiama la stampante in HTTP sulla rete locale. Dal browser in HTTPS la stampante
  rifiutava la chiamata per il suo certificato autofirmato («Failed to fetch»). Se la stampante rimanda all'HTTPS (le Epson recenti lo fanno di fabbrica), il servizio la chiama in HTTPS accettandone il certificato. Serve rilanciare
  sul totem il comando di installazione del pannello; i messaggi distinguono «non raggiungibile»
  da «ePOS-Print non attivo».
- **Stampanti dei biglietti: due tipi nuovi** (servizio code `1.8`).
  - *Stampante di Windows*: il driver installato sul totem, scelto **per nome** (non serve che
    sia la predefinita). Il player disegna il biglietto e il servizio code lo stampa con il driver.
    I totem riferiscono le stampanti installate e il pannello le propone nel campo.
  - *Di rete senza driver*: il totem manda il biglietto all'IP della stampante sulla **porta 9100**
    in comandi ESC/POS (Epson TM e compatibili), senza installare nulla in Windows e senza ePOS.
  - Il Layout Ticket vale per tutti i tipi; senza layout si stampa il biglietto semplice.
  - *Predefinita di Windows*: sul totem la stampa ora il servizio code sulla predefinita
    dell'utente collegato, senza l'anteprima che il browser mostra per un istante; senza
    servizio si usa la stampa del browser come prima.
- **Pulsanti «Info Prezzo» e «Info Ingredienti» sul totem** (servizio code `1.9.1`): due zone
  facoltative del layout, da mettere dove si vuole, anche sopra altre zone, con colori, forma
  (rettangolo, angoli arrotondati, pillola, cerchio), contorno, ombra e scritta personalizzabili.
  Al tocco si apre una casella di 13 caratteri con la tastiera sullo schermo: un codice EAN
  cerca il prodotto, delle lettere cercano per descrizione (spazi = più parole, es. «MOZZ BUF») e
  mostrano l'elenco da toccare. Il lettore di codici a barre resta automatico: legge, cerca e
  mostra il prodotto senza toccare nulla, anche con la ricerca aperta. La ricerca per descrizione
  c'è con EvoPos, DIGI e le mappature; con una query scritta a mano si cerca solo per codice.
- **Il servizio code del totem si aggiorna da solo** (dalla `1.8`): ogni 10 minuti guarda se sul
  server c'è una versione nuova (in HTTPS), la installa quando da due minuti nessuno prende un
  biglietto e si riavvia; se la nuova versione non risponde entro un minuto e mezzo torna a
  quella di prima e non la riprova. I totem con una versione precedente alla 1.8 vanno
  aggiornati a mano una volta (comando di installazione del totem).
- **Biglietto più rapido**: il numero compare sullo schermo appena emesso e la stampa avviene
  intanto; logo e QR del biglietto si preparano all'avvio; il servizio tiene in memoria
  l'elenco delle stampanti.
- **Player che non parte**: i moduli hanno la versione nell'indirizzo, quindi il browser non può
  più mescolare file vecchi e nuovi; se comunque resta su «Avvio…» l'errore compare sullo schermo.
- **Accesso automatico di Windows** (`accesso-automatico.ps1`): password nei segreti di sistema,
  orario di attività di Windows Update sull'apertura del negozio.

### Come ci si è arrivati: le tappe della 1.6 (ricostruite dallo storico)

Prima della 1.6 non c'erano numeri di versione: le tappe sono indicate con i numeri di build
(il «xxx» di `1.6.xxx`) e la data. Il dettaglio di ogni build è nello storico di git.

**Build 001–015 · 20261013 — La base**
- Server con aziende clienti, ruoli e isolamento dei dati tra aziende; contenuti, playlist e
  pubblicazione sugli schermi.
- Layout grafici a zone (orientamento, meteo, notizie) ed editor visuale per monitor e totem.
- Motore di rendering e player nel browser, con anteprima.
- Eliminacode: reparti, banco, pulsantiere e totem; numeri sugli schermi.
- Installazione: server Ubuntu con un comando, player su Windows; backup.

**Build 016–019 · 20261014 — Negozio autonomo**
- Code gestite dal totem del negozio; player che funziona senza rete.
- Adattamenti delle immagini (sfondo sfocato, allunga) e formati standard nell'editor.

**Build 020–035 · 20261014 — Palinsesto e contenuti**
- Pagina «Creazione palinsesto»: libreria, cartelle, campagne che raggruppano promozioni, insegne,
  calendario, import da CSV; pagina di accesso con nome e logo; tema chiaro/scuro.
- Immagine o video di riserva (poi «di default») per ogni schermo.
- Dirette in streaming (liste M3U, intermezzi, audio per diretta).
- Fotografia vera dello schermo su richiesta; timeline della sequenza delle promozioni.
- Annunci registrati dei numeri delle code; eventi straordinari con precedenza su tutto.

**Build 036–048 · 20261014 — Gestione e controllo**
- Menu a gruppi; accensione e spegnimento degli schermi per orari, chiusure e festività.
- Stato degli schermi, storico e allarmi email; fasce di download con velocità massima.
- Listini prezzi; registro dei biglietti, tempi d'attesa, coda sul telefono con QR.
- Registro di messa in onda con rapporti; email per azienda e rapporti automatici.
- Ruoli SystemAdministrator e Administrator; gruppo «Report & Log» con registro operazioni e
  storico allarmi.

**Build 049–056 · 20261015 — Hardware, stampanti e plugin**
- Menu Hardware: anagrafica dei dispositivi video e delle stampanti ticket; Totem Master per sede;
  ruolo User.
- Plugin Info Prezzo e Info Ingredienti (gestionali EvoPos e DIGI, copie dei file per orari).
- Layout Ticket componibile per stampante (Epson TM-T20IV); spiegazioni su tutti i controlli.
- Layout Video e Banchi Code dentro il pannello; anteprime in un riquadro.

**Build 057–062 · 20261015 — Pannello per chi gestisce**
- Distribuzione contenuti, profilo personale, utenti di piattaforma, prova di accesso dei plugin.
- Layout Ticket libero e ridimensionabile; icona della piattaforma.
- Pagina di accesso con gli stili «Oro» e «Oro con sfondo animato».
- Panoramica come pagina iniziale.

**Build 063–070 · 20261015 — Player e installazione robusti**
- Player con versione calcolata dai file e aggiornamento automatico; download senza tenere i file
  in memoria; cache permanente.
- Guardiano di Windows che riapre il browser se la pagina si blocca.
- Script di installazione più chiaro; comandi pronti nel pannello con le impronte dei certificati
  controllate dallo script.

**Build 071–072 · 20261015 — Release 1.6**
- Numero di versione visibile nella pagina di accesso e nel pannello (`1.6.xxx · AAAAMMGG`).
