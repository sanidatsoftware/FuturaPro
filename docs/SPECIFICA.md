# FuturaPro — Specifica tecnica

Piattaforma di videocomunicazione (digital signage) per più aziende clienti, con player
Windows e Android e teleassistenza remota proprietaria. Documento di riferimento del
progetto: le scelte qui sotto valgono finché non le cambiamo esplicitamente.

## 1. Principi

1. **Semplice prima di tutto.** Il flusso base è *carica un contenuto → scegli i monitor →
   Pubblica*. Layout a zone, widget e regole avanzate stanno in una modalità avanzata,
   mai sul percorso principale.
2. **Lo schermo non resta mai nero.** Il player funziona offline per settimane con
   l'ultima programmazione ricevuta.
3. **Isolamento tra clienti assoluto.** Un cliente non vede né deduce l'esistenza
   degli altri. Lo garantiscono due barriere indipendenti (§4).
4. **Sicurezza progettata, non aggiunta.** La teleassistenza non presidiata richiede
   identità forti per dispositivi e operatori fin dal primo giorno.
5. **Crittografia standard.** Il protocollo e l'infrastruttura sono nostri, gli algoritmi
   no: TLS 1.3, DTLS-SRTP, certificati X.509, WebAuthn.

## 2. Componenti

| Componente | Tecnologia | Stato |
|---|---|---|
| Server / API | Django 5.2 + Django REST Framework, PostgreSQL 16 | **in sviluppo** (`server/`) |
| Comandi in tempo reale | Django Channels + Redis (WebSocket) | da fare |
| Pannello web | React + TypeScript, in italiano | da fare |
| Motore di rendering | JavaScript senza dipendenze, condiviso da player nel browser, app native e anteprima | **in sviluppo** (`server/player/`) |
| Player Android | Kotlin, WebView per i layout + Media3/ExoPlayer per i video, device owner | da fare |
| Player Windows | Servizio .NET 8 (watchdog, aggiornamenti, teleassistenza) + app WebView2 | da fare |
| Teleassistenza | Segnalazione WSS con mTLS, WebRTC, relay coturn nostro | da fare |
| Distribuzione | Docker Compose: un unico pacchetto per cloud e installazione presso il cliente | da fare |

Dimensionamento: centinaia di schermi per installazione. Basta un server
(PostgreSQL + Redis + coturn), senza Kubernetes.

**Server centrale (riferimento).** Ubuntu Server 24.04 LTS; 4 vCPU, 8 GB RAM; un disco di
sistema (~40 GB) e uno separato per i contenuti (200–500 GB, espandibile); IP pubblico statico e
nome DNS per il certificato HTTPS. Porte: TCP 443 (pannello e player), TCP 80 (solo rinnovo del
certificato), UDP/TCP 3478 e un intervallo UDP ristretto (es. 49160–49200) per il relay della
teleassistenza.

## 3. Ruoli e permessi

| Ruolo | Livello | Può |
|---|---|---|
| **Administrator Assoluto** | Piattaforma (Sanidat) | Tutto. Sceglie l'azienda dal selettore e opera nel suo contesto; crea clienti, AdminCliente, tecnici; decide le abilitazioni di ogni cliente. |
| **Tecnico Teleassistenza** | Piattaforma | Designato dall'Administrator Assoluto. Apre sessioni remote sui player di **tutti** i clienti; legge l'elenco clienti e i monitor. Non gestisce contenuti né configurazioni. |
| **AdminCliente** | Un cliente | Amministra il proprio parco **entro le abilitazioni concesse**: sedi, gruppi, monitor, contenuti, utenti del cliente. Legge le abilitazioni e il registro di audit e teleassistenza del cliente. Non avvia la teleassistenza. |
| **UserCliente** | Un cliente | Gestisce contenuti, playlist e programmazione. Facoltativamente limitato a certe sedi: allora vede solo quelle e i loro monitor. |

**Abilitazioni** (per cliente, le imposta solo l'Administrator Assoluto): numero massimo di
monitor e di utenti, spazio disponibile, se l'AdminCliente può gestire gli utenti, se può
abbinare/modificare/rimuovere i monitor. Si estenderanno con le funzioni (widget, video
wall, …) man mano che arrivano.

**Registro.** Ogni modifica finisce nel registro di audit del cliente, comprese quelle fatte
dalla piattaforma per suo conto (marcate `per_conto_piattaforma`). Ogni sessione di
teleassistenza è visibile all'AdminCliente: chi, quando, su quale monitor, perché.

Nelle installazioni presso il cliente l'Administrator Assoluto resta Sanidat; il cliente ha
il proprio AdminCliente.

## 4. Isolamento tra clienti

Due barriere indipendenti; ognuna, da sola, impedisce di vedere i dati di un altro cliente.

**Barriera 1 — applicazione.** Ogni dato di un cliente eredita da `core.models.ModelloCliente`
(`cliente_id` obbligatorio). Il gestore `objects` filtra sul cliente del contesto corrente e,
senza contesto, **si rifiuta di eseguire la query** (`ContestoMancante`). Il salvataggio
rifiuta un oggetto di un altro cliente.

**Barriera 2 — database.** Su ogni tabella dei clienti PostgreSQL applica Row-Level Security
con `FORCE` (vale anche per il proprietario delle tabelle). Le policy leggono due variabili di
transazione, `app.cliente_id` e `app.piattaforma`, impostate dal contesto. Senza contesto non si
legge e non si scrive nulla. L'utente del database non è superuser né ha `BYPASSRLS`: lo
verificano un controllo di sistema (`futurapro.E001`) e un test.

**Il contesto** (`core.contesto`) lo stabilisce la vista dopo l'autenticazione:

- utente di un cliente → sempre il proprio cliente; l'intestazione `X-Cliente` è ignorata;
- utente di piattaforma su dati di un cliente → il cliente indicato in `X-Cliente`
  (il pannello la imposta dal selettore dell'azienda); senza, la richiesta è rifiutata;
- operazioni di piattaforma (anagrafica clienti, utenti di piattaforma) → contesto di piattaforma.

Il contesto vale una transazione (`ATOMIC_REQUESTS`) e viene azzerato all'inizio e alla fine di
ogni richiesta.

**Regole di contorno.** Identificativi UUID. Una risorsa di un altro cliente risponde **404**,
mai 403. I riferimenti nei dati in ingresso (sede di un monitor, monitor di una sessione…)
si validano solo contro il cliente corrente. I file sono salvati per cliente
(`clienti/<cliente>/contenuti/<uuid>.<ext>`) e non hanno indirizzi pubblici: li servono solo
viste che controllano prima il cliente (in produzione nginx con `X-Accel-Redirect`).

**Fuori dalla RLS, di proposito:** `utenti_utente` (il login la legge prima di sapere chi è
l'utente; le viste la filtrano), `dispositivi_richiestaabbinamento` (un player non ancora
abbinato non ha cliente), `dispositivi_credenzialedispositivo` (dice a quale cliente appartiene
un player: va letta per prima). Contengono solo impronte, mai segreti.

**Test.** `server/core/tests/test_isolamento.py` prova ogni barriera da sola: togliendo l'una o
l'altra, falliscono test diversi. Un altro test elenca le tabelle con `cliente_id` prive di
Row-Level Security: una tabella nuova dimenticata lo fa fallire. Un test che fallisce blocca
il rilascio.

## 5. Contenuti e palinsesto

**Libreria.** Ogni cliente ha la sua, condivisa fra i suoi utenti: immagini (JPEG, PNG, GIF,
WebP), video (MP4, MOV, WebM) e pagine web. Il formato si riconosce dai primi byte del file,
non dal nome. Al caricamento si calcolano dimensione e SHA-256 e si controlla lo spazio
concesso al cliente. Durata: per le immagini 10 secondi se non indicata, i video vanno fino
alla fine, le pagine web la richiedono.

**Playlist.** Sequenza ordinata di contenuti, ognuno con una durata facoltativa che prevale
su quella del contenuto. Il pannello manda sempre la sequenza intera (trascina e rilascia).

**Pubblicazione.** Una playlist su monitor e/o gruppi, con regole facoltative: date di inizio
e fine, giorni della settimana, fascia oraria, priorità.

**«Pubblica».** Il percorso semplice (`POST /api/pubblica/`): contenuti scelti + monitor scelti
→ il server crea la playlist e la pubblicazione in un passo. Calendario e priorità restano
facoltativi.

**Regole del palinsesto** (`server/contenuti/palinsesto.py`; il player le applica identiche):

1. una pubblicazione vale se è attiva, la data è fra inizio e fine (comprese), il giorno è fra
   quelli scelti (o non ne è scelto nessuno) e l'ora è in [inizio, fine); una fascia con fine
   prima dell'inizio scavalca la mezzanotte;
2. fra quelle valide vince la priorità più alta;
3. a pari priorità le playlist si accodano in ordine di creazione: pubblicare altro sugli
   stessi monitor lo aggiunge alla rotazione. Una pubblicazione «urgente» con priorità più
   alta sostituisce temporaneamente tutto il resto.

Date e orari sono nel fuso del server (`Europe/Rome`), indicato nel manifest.

**Utenti limitati a certe sedi.** Pubblicano solo sui singoli monitor delle loro sedi, non sui
gruppi (che possono comprendere altre sedi); vedono e modificano solo le pubblicazioni di
quei monitor.

**Manifest del player** (`GET /api/player/palinsesto/`). Contiene tutte le pubblicazioni del
monitor con le loro regole, le playlist e l'elenco dei file con SHA-256 e dimensione. Il player
valuta le regole da solo, quindi continua a seguire il palinsesto anche offline. La `versione`
dipende solo dal contenuto: con `If-None-Match` il server risponde 304 se non è cambiato
nulla. I file si scaricano da `/api/player/file/<id>/`, solo se pubblicati su quel monitor.

### Creazione palinsesto: campagne e promozioni

La pagina `/palinsesto/` (voce «Creazione palinsesto» del menu) è l'unico punto in cui si
decide cosa va in onda: la vecchia scheda «Contenuti e pubblicazioni» non c'è più e le
pubblicazioni fatte con lei sono diventate promozioni, ognuna nella sua campagna (migrazione
`contenuti.0008`). Calendario con lente (anno, 6 mesi, 3 mesi, mese, 2 settimane; anche
Ctrl + rotellina); un clic su una promozione ne mostra il dettaglio con le miniature. Le
promozioni attive e scadute si sfogliano come cartelle. Ogni funzione ha la sua spiegazione
al passaggio del mouse (`data-aiuto`, `pannello/static/pannello/aiuto.js`).

- **Campagna** (`/api/campagne/`): raggruppa più promozioni e tiene ciò che hanno in comune:
  validità dal/al (obbligatoria, es. tutto l'anno), destinatari (insegne, gruppi, singoli
  monitor e totem), colore, priorità, secondi per immagine, codice. Le date delle promozioni
  devono stare dentro la validità, che non si può stringere lasciandone fuori qualcuna.
- **Promozione** (`/api/promozioni/`): appartiene a una campagna; ha nome, date dal/al
  (obbligatorie), eventuali orari e giorni, e le sue immagini in ordine. Il server la traduce
  in una pubblicazione per orientamento: le immagini verticali vanno solo ai totem, le
  orizzontali solo ai monitor, i contenuti senza misure a tutti. Il player non cambia: riceve
  pubblicazioni come prima. Senza immagini, o con la campagna senza destinatari, la promozione
  è una **bozza** e non va in onda. Cambiando i destinatari della campagna si aggiornano tutte
  le sue promozioni.
- **Libreria.** Il server legge larghezza e altezza delle immagini (con la rotazione EXIF); per
  i video le misura il browser. Verticali e orizzontali sono mostrate a parte, con miniature
  create alla prima richiesta (`/api/contenuti/<id>/miniatura/`). Viste: *da assegnare* (in
  nessuna promozione: è quella iniziale), *nelle promozioni attive*, *promozioni scadute*, *tutti*.
- **Pulizia** (`/api/contenuti/pulizia/`: GET stima, POST cancella). Elimina, file compresi, i
  contenuti usati solo da promozioni concluse; restano quelli di promozioni in corso o future,
  delle playlist fatte a mano (anche quelle fisse delle zone slide) e dei layout.
- **Cartelle.** Si trascina o si sceglie un'intera cartella: i file vengono caricati tre alla
  volta e viene proposta una promozione con il nome della cartella (si sceglie la campagna).
- **Immagine di riserva** (campo `immagine_riserva` del monitor, scheda Monitor): quando non
  c'è nessuna promozione in onda le slide mostrano questa immagine (es. il logo) invece del
  nero. Va nel manifest (`riserva`) e la pulizia non la cancella mai. Le promozioni importate da
  CSV senza immagini sono bozze: nessun errore, e fino ad allora va in onda la riserva.
- **Dirette in streaming** (facoltative; tipo di contenuto `diretta`). Si aggiungono dal
  pulsante «📡 Dirette»: da una lista M3U/M3U8 (indirizzo o file; `POST /api/contenuti/m3u/`
  la legge e restituisce i canali senza salvarli) o da un singolo indirizzo `.m3u8`/video.
  Per aggiungerle va confermato che la riproduzione in pubblico è autorizzata (canone RAI
  speciale, SIAE/SCF, abbonamenti o permessi): `POST /api/contenuti/dirette/` con
  `autorizzazione: true`, registrato nel contenuto (`autorizzata_da`, `autorizzata_il`) e
  nell'audit; anche metterle in una promozione chiede conferma. In una promozione la diretta
  è una voce con la sua durata in minuti (`durate` della promozione, predefinita 5 minuti):
  da sola resta in onda di continuo, tra le immagini fa da intermezzo. Il server legge solo
  la lista: lo streaming lo scarica ogni player con la sua connessione a internet. Il player
  usa hls.js (`player/static/player/vendor`, licenza Apache 2.0) per l'HLS; se il canale non
  parte entro 15 secondi, o dà un errore certo, passa alla voce successiva; se cade durante
  la riproduzione si passa oltre e al giro dopo si riprova. L'audio della diretta è spento di
  serie e si accende voce per voce nella promozione (`audio` della promozione, 🔇/🔊 sulla
  miniatura); spento riguarda solo lo streaming: gli altri suoni del monitor (din-don dei
  numeri) restano attivi. Le
  dirette vanno ai monitor orizzontali e la pulizia non le cancella. Se il player è in https e il canale
  in http, il player prova lo stesso indirizzo in https (il browser blocca l'http). Il motivo di
  una diretta che non parte arriva al server con il segnale periodico e compare nella scheda
  Monitor; il pulsante ▶ sulla diretta, nella libreria, la prova dal browser del pannello.
- **Salvataggio**: i pulsanti «Salva» di campagna e promozione restano spenti finché non si
  cambia qualcosa; con modifiche in sospeso lampeggiano e compare il promemoria.
- **Insegne** (`/api/insegne/`, facoltative): ogni sede può avere un'insegna; una campagna su
  un'insegna raggiunge tutti i monitor e totem delle sue sedi.
- **Calendario**: anno o tre mesi, una fascia per campagna con le sue promozioni colorate per
  stato (in onda, programmata, bozza, conclusa).

**Importazione CSV** (`POST /api/campagne/importa/`, modello in `GET /api/campagne/modello/`).
Serve a caricare a inizio anno campagne e promozioni con le loro date; le immagini si
aggiungono dopo. Una riga per promozione; separatore `;` (Excel italiano) o `,`; prima riga
con i nomi delle colonne; UTF-8 o Windows-1252.

| Colonna | | Formato |
|---|---|---|
| `campagna` | obbligatoria | le righe con lo stesso nome vanno nella stessa campagna |
| `campagna_dal`, `campagna_al` | | validità della campagna; vuote: dalla prima all'ultima promozione |
| `promozione` | obbligatoria | se la campagna ha già una promozione con questo nome, viene aggiornata |
| `data_inizio`, `data_fine` | obbligatorie | `gg/mm/aaaa` (anche `aaaa-mm-gg`), fine compresa |
| `insegne`, `gruppi`, `monitor` | della campagna | nomi esistenti separati da `\|`; le righe di una campagna si sommano |
| `ora_inizio`, `ora_fine` | | `hh:mm` |
| `giorni` | | `lun\|mar\|mer\|gio\|ven\|sab\|dom`, vuoto = tutti |
| `priorita` | della campagna | da -100 a 100 |
| `durata` | della campagna | secondi per immagine |
| `colore`, `codice`, `note` | della campagna | `#rrggbb`; testo; testo |

Con `prova=1` il file viene solo controllato e l'esito torna riga per riga. Tutto o niente: se
una riga ha un errore non si salva nulla. È riservata a chi vede tutto il cliente.

**Tema delle pagine.** Ogni utente sceglie chiaro, scuro o automatico (segue il sistema) nella
scheda «Aspetto interfaccia» (`PATCH /api/io/`); vale per pannello, editor e palinsesto.

**Aspetto della piattaforma.** Nome dell'applicazione, frase, colore e logo (PNG, JPEG, GIF o
WebP; niente SVG) della pagina di accesso `/accesso/` e del pannello. Li cambia solo
l'Administrator Assoluto, nella scheda «Aspetto interfaccia» (`/api/piattaforma/aspetto/`).

## 6. Layout grafici

Ogni cliente ha i propri layout; l'AdminCliente li gestisce se l'Administrator Assoluto glielo
concede (abilitazione `admin_gestisce_layout`).

**Schermo.** Il layout ha un orientamento: orizzontale (palco 1920×1080) o verticale per i totem
(1080×1920). Le zone sono rettangoli in **percentuale** del palco, quindi valgono a qualunque
risoluzione; il player scala il palco sullo schermo reale. Ogni monitor ha un orientamento e una
**rotazione** (0/90/180/270): un totem nativo verticale resta a 0, un televisore orizzontale
montato in verticale usa 90 o 270 e il player ruota l'immagine. Il layout assegnato a un monitor
deve avere il suo stesso orientamento. Senza layout assegnato vale il predefinito del cliente per
quell'orientamento; se manca anche quello, le slide a tutto schermo.

**Zone** (`server/layout/zone.py`; il motore legge esattamente questi campi):

| Tipo | Configurazione |
|---|---|
| `slide` | `sorgente` (`palinsesto` o una playlist fissa), `transizione` (nessuna, dissolvenza, scorri_sinistra, scorri_alto, zoom), `durata_transizione` in ms, `adattamento` (adatta / riempi) |
| `orologio` | `secondi`, `mostra_data`, `colore`, `allineamento` |
| `meteo` | `localita`, `latitudine`, `longitudine`, `colore` |
| `notizie` | `feed` (fino a 5 RSS/Atom), `messaggi` propri, `velocita` in px/s, `aggiornamento_minuti`, `colore`, `sfondo` |
| `testo` | `testo`, `dimensione` (% dell'altezza della zona), `colore`, `sfondo`, `allineamento` |
| `immagine` | `contenuto` (un'immagine della libreria), `adattamento` |

Una sola zona `slide` per layout mostra il palinsesto; le altre possono girare playlist fisse.
Il layout ha anche colore e immagine di sfondo e il carattere.

**Editor visuale** (`/editor/`): elenco dei layout con anteprima in miniatura, creazione vuota o da
modello, e per ogni layout un palco a dimensione reale (1920×1080 o 1080×1920) dove si aggiungono
le zone, si spostano e si ridimensionano trascinandole (aggancio allo 0,5%, frecce per gli
spostamenti fini), si portano avanti o indietro, si duplicano e si configurano in un pannello
laterale con i campi del loro tipo: playlist, immagini, reparti e località si scelgono da elenchi.
Al salvataggio il server valida tutto e gli errori tornano sulla zona che li ha, evidenziata in
rosso. Gli utenti di piattaforma lo aprono con `?cliente=<id>`.

**Modelli pronti** (`POST /api/layout/da-modello/`): schermo intero; orizzontale con slide, ora,
meteo e rullo notizie; totem verticale con ora e meteo in alto, slide al centro e rullo in basso.
Per la località del meteo il pannello cerca la città per nome (`/api/meteo/localita/?nome=`).

**Meteo e notizie.** Li scarica il server, non i player: una richiesta per località o feed,
qualunque sia il numero di monitor, e i player non devono raggiungere internet. Meteo da
Open-Meteo (senza chiave, aggiornato ogni 15 minuti); notizie dai feed indicati, letti con
`defusedxml`. Se una fonte non risponde resta l'ultimo dato buono (fino a 48 ore). I feed non
possono puntare a indirizzi non pubblici, nemmeno attraverso un redirect: un AdminCliente non può
usarli per sondare la rete del server.

## 7. Eliminacode

**Dove stanno le code.** Se la sede ha un **totem** (campo *Totem delle code* della sede), le code le
tiene il **servizio code del totem** (`deploy/installa/code-totem.ps1`, attività di sistema
Windows): numeri, biglietti, chiamate di bilance e banchi, numeri per i monitor. Il negozio dà i
turni anche senza server centrale, che fornisce solo la configurazione (reparti, colori, impronte
delle chiavi) attraverso il manifest del totem. Per quella sede il server rifiuta le operazioni di
coda, così i numeri non stanno mai in due posti. Senza totem le code le tiene il server, come
descritto sotto.

Servizio code del totem:

| Porta | Chi | Cosa |
|---|---|---|
| 8443 HTTPS | monitor e totem | `GET /stato` (numeri, chiunque in rete); `POST /config` e `POST /emetti/<reparto>` (solo dal totem stesso, 127.0.0.1) |
| 8090 HTTP | bilance, banchi, pulsanti | `GET /banco/` (pagina), `GET /banco/stato/`, `POST /banco/{avanti,indietro,ripeti,azzera,imposta}/` con la chiave del reparto |

Il certificato del servizio è autofirmato, creato all'installazione del totem per il suo IP (e per
127.0.0.1), e reso attendibile su totem e monitor dopo il confronto dell'impronta. Lo stato si salva
in `stato.json` a ogni operazione (scrittura atomica); le richieste sono servite una alla volta.

FuturaPro gestisce le code dei banchi (salumeria, macelleria, gastronomia…) e le mostra sugli
stessi schermi delle offerte. Sostituisce il sistema attuale (server WebSocket PHP, file di
testo, script Python per i pulsanti, pagine per le bilance DIGI, totem con stampante Epson).

**Reparti.** Per sede: nome, colore di fondo e del testo, ordine, ultimo numero (99). Ogni
reparto conta, nella giornata, i biglietti emessi e le chiamate. I numeri vanno **da 0 a 99** e
poi ripartono da 0; siccome i contatori non girano, «clienti in coda» (emessi − chiamati) resta
giusto anche dopo il 99. Al primo uso di un nuovo giorno la coda riparte (disattivabile).
Ogni operazione blocca la riga del reparto: due banchi o due totem che premono insieme non
ottengono mai lo stesso numero (verificato con 40 emissioni in parallelo).

**Banco** (`/banco/`, su tablet, PC o browser della bilancia): avanti, indietro, ripeti,
imposta numero, azzera. Le chiamate le fa anche lo UserCliente; configurare i reparti è della
gestione. Il banco funziona con l'accesso al pannello oppure con la **chiave del reparto**.

**Pulsantiere, bilance, script.** Una chiave per reparto, generata nel pannello (se ne conserva
l'impronta, si revoca in ogni momento), vale solo per avanti / indietro / ripeti di quel reparto:

    curl -X POST -H "Authorization: Pulsante <chiave>" https://server/api/eliminacode/pulsante/avanti/

**Zone del layout.**

| Tipo | Configurazione |
|---|---|
| `coda` | `reparti` (vuoto = quelli della sede del monitor), `personalizza`, `disposizione` (automatica, colonna, riga, griglia), `testo_coda` (`{n}` = clienti in coda; vuoto = nascosto), `bordo`, `annuncio` (nessuno, suono, voce) |
| `prendi_numero` | `reparti`, `personalizza`, `titolo` (vuoto = senza barra), `colore`, `sfondo`, `sfondo_pulsanti`, `colonne` (0 = automatico), `arrotondamento`, `testo_coda`, `stampa` (nessuna, browser, epson), `stampante`, `intestazione`, `messaggio` |

`personalizza` cambia, solo in quella zona, etichetta e colori di singoli reparti: la stessa
salumeria può essere «Salumi e formaggi» in verde sul totem e un riquadro rosa sul display.
Con `reparti` vuoto un solo layout serve tutti i negozi: ognuno mostra i suoi banchi.

**Chiamata sui display.** Il riquadro lampeggia e, se la zona lo prevede, suona il «din-don»
(sintetizzato, nessun file) e la voce di sistema dice «Salumeria, numero 27». La voce italiana
c'è su Windows e Android; i file audio registrati del sistema attuale si potranno caricare come
alternativa. Conviene far annunciare un solo monitor per negozio.

**Totem.** Il cliente tocca il reparto, il server assegna il numero, lo schermo lo mostra con
le persone che lo precedono e il player stampa:

- `browser`: stampa di sistema; con Chrome avviato con `--kiosk --kiosk-printing` esce senza
  finestre sulla stampante predefinita (biglietto da 80 mm);
- `epson`: stampante di rete Epson TM con ePOS-Print (la stessa interfaccia del sistema
  attuale), all'indirizzo indicato. Se la pagina è in HTTPS anche la stampante va usata in HTTPS
  (il suo certificato si accetta una volta sul totem). Se la stampante non risponde il totem lo
  dice e mostra comunque il numero.

Le app native stamperanno direttamente sulla stampante (USB o rete).

**Modelli pronti** che ricalcano gli schermi dei supermercati: offerte con ora, meteo e reparti;
offerte e reparti; totem eliminacode.

**Dal sistema attuale.** Due problemi da non riportare: il server WebSocket accetta comandi da
chiunque sia in rete (avanti, azzera, imposta), e `php/salvadati.php` scrive un file il cui nome
arriva dalla richiesta, quindi chi è in rete può scrivere file arbitrari sul server.

## 8. Player

**Motore di rendering** (`server/player/static/player/`, JavaScript senza dipendenze né
compilazione). Disegna il layout del manifest e fa girare le zone: slide con transizioni e loro
durata, orologio nel fuso del manifest, meteo, rullo continuo (i titoli nuovi entrano al giro
successivo, senza salti), testi, immagini. Ogni testo esterno passa da `textContent`. Lo stesso
codice serve:

- il **player nel browser** (`/player/`): un PC Windows con il browser in modalità kiosk funziona
  già da player, con abbinamento, cache dei file (Cache API, su HTTPS) e ultimo manifest salvato,
  così riparte anche senza rete;
- le **app native**, che lo caricheranno in WebView (Android) e WebView2 (Windows);
- l'**anteprima** nel pannello (`/anteprima/<monitor>/`), con la sessione dell'utente.

**Offline.** Il player si salva nel browser con un service worker (`/player/sw.js`) e riparte
anche se all'accensione il server non risponde. Un nuovo palinsesto va in onda solo quando tutti i
suoi file sono scaricati; fino ad allora resta il precedente. Meteo, notizie e numeri dei reparti
tengono l'ultimo dato ricevuto. Il segnale periodico dice al server quale versione del palinsesto
è in onda: il pannello segnala i monitor non aggiornati.

`regole.js` replica le regole del palinsesto del server; `regole.test.mjs` verifica che diano gli
stessi risultati dei test Python.


**Abbinamento** (già implementato):

1. All'installazione il player genera un token casuale (32 byte) e lo conserva nell'archivio
   protetto del sistema (Android Keystore / Windows DPAPI-TPM).
2. `POST /api/player/abbinamento/` con token e piattaforma → riceve un codice di 6 cifre valido
   15 minuti e lo mostra a schermo (anche come QR). Il server conserva solo l'impronta SHA-256.
3. L'AdminCliente (o l'Administrator Assoluto) inserisce il codice nel pannello, sceglie nome e
   sede: `POST /api/monitor/abbina/`.
4. Il player interroga `GET /api/player/stato/` con `Authorization: Device <token>` e scopre di
   essere abbinato.

Il token non viaggia mai più, salvo come intestazione su TLS. Nella fase di teleassistenza
l'autenticazione passa a **certificati client** emessi dalla CA della piattaforma (mTLS); la
chiave privata nasce nel dispositivo e non lo lascia.

**Funzionamento** (da fare lato player; il manifest è già pronto, §5): download
differenziale e verificato, cache locale, riproduzione offline, `heartbeat` periodico (già
presente) con versione, spazio, temperatura e screenshot su richiesta, comandi in tempo reale via
WebSocket, prova di trasmissione.

**Aggiornamenti** (da fare): pacchetti firmati, rilascio graduale (prima una percentuale di
player), ritorno automatico alla versione precedente se il player non torna online.

**Android.** Provisioning *device owner* tramite QR alla prima accensione: avvio automatico,
modalità kiosk, aggiornamenti silenziosi, riavvio programmato. Video con Media3/ExoPlayer in
decodifica hardware.

**Windows.** Un servizio di sistema (LocalSystem) sorveglia l'app di riproduzione (WebView2),
la riavvia se si blocca, gestisce aggiornamenti e teleassistenza; funziona anche senza utenti
collegati.

## 9. Teleassistenza

**Chi.** Solo Administrator Assoluto e Tecnici Teleassistenza, su tutti i clienti. Accesso al
pannello con 2FA obbligatoria (WebAuthn, in alternativa TOTP). L'AdminCliente vede il registro,
non avvia sessioni. Già implementati: permessi, registro delle sessioni, audit.

**Come** (da fare):

1. Il tecnico apre una sessione dal pannello (`POST /api/teleassistenza/sessioni/`): il server
   emette un gettone di sessione firmato, monouso, valido 5 minuti e legato a quel monitor e
   a quel tecnico.
2. Il server avvisa il player sul suo canale WebSocket (autenticato con il certificato del
   dispositivo, mTLS).
3. Player e browser del tecnico negoziano una connessione **WebRTC** tramite la nostra
   segnalazione; il traffico passa dal **nostro relay coturn** quando la connessione diretta
   non è possibile. Cifratura DTLS-SRTP end-to-end.
4. Canali: video dello schermo (H.264 con encoder hardware), input mouse/tastiera, file,
   comandi di diagnostica (log, riavvio app/dispositivo, rete). Nessuna shell libera.
5. Accesso senza presenza sul posto (scelta di progetto), con sessione chiudibile da pannello,
   durata massima, eventuale registrazione video, revoca immediata del certificato di un
   dispositivo.

**Identità.** Ogni installazione (cloud o presso il cliente) ha **la propria CA**. Il player crea
la coppia di chiavi nel Keystore/TPM e invia una CSR durante l'abbinamento; la CA firma un
certificato legato a monitor e cliente.

**Requisiti di piattaforma.**

- Android: cattura con MediaProjection; input remoto con app *device owner* + servizio di
  accessibilità, oppure con firma di sistema del produttore. Da verificare per l'hardware scelto.
- Windows: servizio di sistema con Desktop Duplication API e iniezione input, gestione della
  schermata di login e dei prompt UAC (desktop sicuro).

**Installazioni presso il cliente.** Il cliente ha accesso fisico al server: non possiamo
impedirgli tecnicamente di alterare il proprio database. L'isolamento lì è comunque irrilevante
(c'è un solo cliente); la licenza firmata e il contratto regolano l'accesso di Sanidat.

## 10. Hardware Android — cosa verificare

- Android 11 o superiore (meglio 12–14).
- Decodifica hardware 4K H.264/H.265; almeno 32 GB eMMC; Ethernet.
- Accensione automatica al ritorno della corrente; watchdog hardware se disponibile.
- **Domanda al fornitore:** forniscono la firma di sistema per le app, oppure il dispositivo
  supporta il provisioning *device owner* via QR?
- Piattaforme consigliate: Rockchip RK3566/RK3568/RK3588.
- Attenzione: i monitor professionali Samsung (Tizen) e LG (webOS) **non sono Android**.

## 11. API disponibili

Autenticazione del pannello: sessione Django (`/api/sessione/login/`). Gli utenti di
piattaforma indicano il cliente con l'intestazione `X-Cliente: <uuid>`.

| Metodo e percorso | Chi |
|---|---|
| `GET /api/io/` | tutti gli autenticati |
| `GET/POST/PATCH /api/piattaforma/clienti/` | lettura: Assoluto, Tecnico — scrittura: Assoluto |
| `GET/POST/PATCH/DELETE /api/piattaforma/utenti/` | Assoluto |
| `GET /api/piattaforma/audit/` | Assoluto |
| `GET/PATCH /api/abilitazioni/` | lettura: Assoluto, AdminCliente — scrittura: Assoluto |
| `/api/sedi/`, `/api/gruppi/` | lettura: tutti — scrittura: Assoluto, AdminCliente |
| `GET/PATCH/DELETE /api/monitor/`, `POST /api/monitor/abbina/` | lettura: tutti — scrittura: Assoluto, AdminCliente (se abilitato) |
| `/api/utenti/` | Assoluto, AdminCliente (se abilitato) |
| `GET /api/audit/` | Assoluto, AdminCliente |
| `GET /api/teleassistenza/sessioni/` | Assoluto, Tecnico, AdminCliente |
| `POST /api/teleassistenza/sessioni/`, `POST …/{id}/chiudi/` | Assoluto, Tecnico |
| `/api/contenuti/` (upload multipart), `GET /api/contenuti/{id}/file/` | lettura: tutti — scrittura: Assoluto, AdminCliente, UserCliente |
| `/api/playlist/`, `/api/pubblicazioni/` | lettura: tutti — scrittura: Assoluto, AdminCliente, UserCliente |
| `POST /api/pubblica/` | Assoluto, AdminCliente, UserCliente |
| `GET /api/anteprima/{monitor}/?quando=` | tutti |
| `/api/layout/`, `POST /api/layout/da-modello/`, `GET /api/layout/modelli/` | lettura: tutti — scrittura: Assoluto, AdminCliente (se abilitato) |
| `GET /api/zone/{id}/dati/`, `GET /api/anteprima/{monitor}/manifest/` | tutti (anteprima) |
| `GET /api/meteo/localita/?nome=` | Assoluto, AdminCliente |
| `POST /api/player/abbinamento/`, `GET /api/player/stato/`, `POST /api/player/heartbeat/` | player |
| `GET /api/player/zone/{id}/dati/`, `POST /api/player/zone/{id}/emetti/` | player |
| `/api/reparti/` | lettura: tutti — scrittura: Assoluto, AdminCliente |
| `POST /api/reparti/{id}/avanti/` (anche `indietro`, `ripeti`, `imposta`, `azzera`, `emetti`) | Assoluto, AdminCliente, UserCliente |
| `POST/DELETE /api/reparti/{id}/chiave/` | Assoluto, AdminCliente |
| `GET /api/eliminacode/pulsante/`, `POST /api/eliminacode/pulsante/{avanti,indietro,ripeti}/` | chiave del reparto |
| `GET /api/player/palinsesto/`, `GET /api/player/file/{id}/` | player |

## 12. Roadmap

1. **MVP (3–4 mesi)**
   - [x] Clienti, abilitazioni, ruoli, isolamento a due barriere, audit immutabile
   - [x] Sedi, gruppi, monitor, abbinamento con codice, heartbeat
   - [x] Registro e permessi della teleassistenza
   - [x] Libreria contenuti (upload, formato verificato, quote), playlist, programmazione a calendario
   - [x] Flusso *carica → scegli monitor → Pubblica*, anteprima, manifest e download per il player
   - [ ] Miniature dei contenuti e durata dei video letta dal file
   - [ ] Notifica immediata ai player via WebSocket (oggi il player interroga il manifest)
   - [x] Layout grafici per cliente: zone, orientamento e rotazione, meteo, notizie, modelli pronti
   - [x] Motore di rendering e player nel browser (kiosk), anteprima grafica
   - [x] Eliminacode: reparti, banco, chiavi per pulsantiere e bilance, display, totem con stampa
   - [ ] Eliminacode: file audio propri, statistiche di attesa, coda seguita dal telefono (QR)
   - [x] Editor visuale dei layout (zone da trascinare e configurare, orizzontale e verticale)
   - [ ] Pannello web completo con selettore azienda (contenuti, monitor, utenti, reparti)
   - [ ] Player Android e Windows con cache offline
   - [ ] 2FA, Docker Compose, CI
2. **Teleassistenza (circa 2 mesi):** CA, mTLS, segnalazione WebSocket, WebRTC, coturn, agent
   Android e Windows, aggiornamenti remoti.
3. **Professionale:** prova di trasmissione, widget dati, avvisi, rilascio graduale, API pubbliche.
4. **Avanzato:** video wall sincronizzati, contenuti interattivi.
