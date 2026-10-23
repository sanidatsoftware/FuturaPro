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
| **SystemAdministrator** | Piattaforma (chi gestisce l'installazione) | Tutto. Sceglie l'azienda dal selettore e opera nel suo contesto; crea clienti, Administrator, tecnici e altri SystemAdministrator («Utenti di piattaforma»); decide le abilitazioni di ogni cliente. |
| **Tecnico Teleassistenza** | Piattaforma | Designato dal SystemAdministrator. Apre sessioni remote sui player di **tutti** i clienti; legge l'elenco clienti e i monitor. Non gestisce contenuti né configurazioni. |
| **Administrator** | Un cliente | Amministra il proprio parco **entro le abilitazioni concesse**: sedi, gruppi, monitor, contenuti, gli User del cliente (gli Administrator li crea e li gestisce solo il SystemAdministrator). Legge le abilitazioni e il registro di audit e teleassistenza del cliente. Non avvia la teleassistenza. |
| **User** | Una sola azienda (quella di appartenenza) | Gestisce contenuti, playlist e programmazione. Facoltativamente limitato a certe sedi: allora vede solo quelle e i loro monitor. |

**Chi crea chi.** Solo il SystemAdministrator crea SystemAdministrator, Tecnici e Administrator;
l'Administrator crea, modifica e disattiva solo gli User della sua azienda (se l'abilitazione lo
consente) e non può promuoverli Administrator. Nessuno disattiva sé stesso né si cambia il ruolo.

**Profilo.** Ogni utente, SystemAdministrator compreso, cambia da sé nome utente, nome, cognome,
email e password nella scheda «Profilo» (menu Impostazioni, o clic sul proprio nome in alto;
`PATCH /api/io/`). Nome utente e password chiedono la password attuale; la password nuova ha almeno
10 caratteri e passa i controlli di Django; si resta collegati. I cambi finiscono nel registro.

**Pagina iniziale.** Dopo l'accesso si apre la pagina scelta nel Profilo («Pagina iniziale»,
`Utente.pagina_iniziale`), oppure quella consigliata per il ruolo: SystemAdministrator e
Administrator la «Panoramica» (il SystemAdministrator nella vista di tutte le aziende),
Tecnico «Stato e allarmi», User «Creazione palinsesto». Un indirizzo con `next` vale su tutto.

**Abilitazioni** (per cliente, le imposta solo il SystemAdministrator): numero massimo di
monitor e di utenti, spazio disponibile, se l'Administrator può gestire gli utenti, se può
abbinare/modificare/rimuovere i monitor. Si estenderanno con le funzioni (widget, video
wall, …) man mano che arrivano.

**Registro.** Ogni modifica finisce nel registro di audit del cliente, comprese quelle fatte
dalla piattaforma per suo conto (marcate `per_conto_piattaforma`). Ogni sessione di
teleassistenza è visibile all'Administrator: chi, quando, su quale monitor, perché.

Nelle installazioni presso il cliente il SystemAdministrator resta il gestore della piattaforma; il cliente ha
il proprio Administrator.

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
- **Immagine o video di default dello schermo** (nel pannello «default»; campo `immagine_riserva`
  del monitor, scheda Anagrafica Dispositivi Video). Si sceglie in due punti: il riquadro
  «Immagini o video di default» lo imposta in un colpo solo su tutti i totem e/o tutti i monitor
  («Applica a tutti»; se gli schermi ne hanno di diversi il menu propone «lasciali così» e quel
  gruppo non cambia), la colonna «Default (se non c'è nulla in onda)» dell'elenco lo cambia per un
  singolo schermo. Quando non
  c'è nessuna promozione in onda le slide mostrano questa immagine o questo video (es. il logo o
  uno spot istituzionale; il video ricomincia da capo) invece del nero. Si carica dal computer
  (`POST /api/contenuti/` con `uso=riserva`) ed è conservata a parte: non compare nella
  libreria (`?uso=libreria`), non scade con le promozioni e la pulizia non la tocca. Quando
  nessuno schermo la usa più (cambiata, tolta, schermo rimosso) viene cancellata dal server, e
  i player la tolgono dalla loro cache al palinsesto successivo. Le promozioni importate da
  CSV senza immagini sono bozze: nessun errore, e fino ad allora va in onda la riserva.
- **Sequenza della promozione** (timeline «🎬 Sequenza», in basso quando una promozione è
  aperta). Una corsia per i monitor (orizzontali e dirette) e una per i totem (verticali);
  ogni voce è un blocco lungo quanto resta in onda, con il righello dei tempi e la durata di un
  giro. Si selezionano una o più voci (clic, Ctrl/⇧), si trascinano per cambiare l'ordine (o
  con ← →), si tira il bordo destro per cambiare la durata (o la si scrive, anche per più voci
  insieme), si tolgono con Canc; Ctrl+Z annulla. Le immagini si trascinano anche dalla
  libreria direttamente nel punto voluto. Durate: quella propria della voce (`durate` della
  promozione), altrimenti i secondi della campagna per le immagini, il video intero per i video,
  5 minuti per le dirette. L'anteprima riproduce la corsia come lo schermo (stesse durate, poi
  da capo; dirette comprese), si può accelerare (2×, 4×, 10× per le immagini) e da lì si
  conferma il salvataggio.
- **Eventi straordinari** (pulsante «⚡ Eventi straordinari» della pagina palinsesto,
  `/api/eventi/`). Un evento ha nome, inizio (giorno e ora), durata, cosa va in onda (una
  diretta, un video o un'immagine), audio sì/no con il suo volume, destinatari (insegne,
  gruppi, schermi; un utente di sede solo i suoi schermi) e può essere sospeso. Ha la
  precedenza su tutte le promozioni: il manifest elenca gli eventi non finiti dei prossimi
  120 giorni (`eventi`, con inizio e fine assoluti) e il player li controlla ogni secondo,
  anche senza rete. All'inizio interrompe la slide in corso nella zona slide principale (la più
  grande con il palinsesto) o, se scelto, la allarga a tutto lo schermo; un video più corto
  ricomincia finché dura l'evento; alla fine la playlist riparte da capo. Il video dell'evento
  arriva al player in anticipo e la pulizia non lo cancella. I numeri delle code continuano, con
  il loro volume (`volume_annunci` della zona code, a parte da quello dell'evento). Nel
  calendario gli eventi hanno una fascia propria.
- **Dirette in streaming** (facoltative; tipo di contenuto `diretta`). Si aggiungono dal
  pulsante «📡 Dirette»: da una lista M3U/M3U8 (indirizzo o file; `POST /api/contenuti/m3u/`
  la legge e restituisce i canali senza salvarli) o da un singolo indirizzo `.m3u8`/video.
  Per aggiungerle va confermato che la riproduzione in pubblico è autorizzata (canone RAI
  speciale, SIAE/SCF, abbonamenti o permessi): `POST /api/contenuti/dirette/` con
  `autorizzazione: true`, registrato nel contenuto (`autorizzata_da`, `autorizzata_il`) e
  nell'audit; anche metterle in una promozione chiede conferma. In una promozione la diretta
  è una voce con la sua durata in minuti (`durate` della promozione, predefinita 5 minuti):
  da sola resta in onda di continuo, tra le immagini fa da intermezzo. Il server legge solo
  la lista: lo streaming lo scarica ogni player con la sua connessione a internet. Per l'HLS il player
  prova due lettori: quello del browser (come aprire il link nella barra degli indirizzi: non
  serve il permesso CORS del canale) e hls.js (`player/static/player/vendor`, licenza Apache
  2.0), prima quello che il browser dichiara di avere; se il canale non
  parte entro 15 secondi, o dà un errore certo, passa alla voce successiva; se cade durante
  la riproduzione si passa oltre e al giro dopo si riprova. L'audio della diretta è spento di
  serie e si accende voce per voce nella promozione (`audio` della promozione, 🔇/🔊 sulla
  miniatura); spento riguarda solo lo streaming: gli altri suoni del monitor (din-don dei
  numeri) restano attivi. Le
  dirette vanno ai monitor orizzontali e la pulizia non le cancella. Se il player è in https e il canale
  in http, il player prova lo stesso indirizzo in https (il browser blocca l'http). Il motivo di
  una diretta che non parte arriva al server con il segnale periodico e compare nella scheda
  Monitor; il pulsante ▶ sulla diretta, nella libreria, la prova dal browser del pannello.
- **Fotografia dello schermo** (scheda Monitor, clic sulla sagoma): il pannello la chiede
  (`POST /api/monitor/<id>/schermata/`), il player se ne accorge entro 8 secondi
  (`GET /api/player/schermata/`), fotografa il palco alla misura vera con html2canvas
  (`player/static/player/vendor`, licenza MIT) ricopiando i fotogrammi di video e dirette, e la
  manda in JPEG (`POST /api/player/schermata/`). Una diretta di un altro sito che non concede
  la copia compare come riquadro con il suo nome. L'ultima foto resta, con la sua ora.
- **Giro di una promozione**: nel riquadro della promozione, per totem e monitor, la sequenza
  che ogni schermo ripete e quanto dura un giro; avvisa se la diretta è l'unica voce.
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
WebP fino a 3 MB; niente SVG) della pagina di accesso `/accesso/` e del pannello. Li cambia solo
il SystemAdministrator, nella scheda «Aspetto interfaccia» (`/api/piattaforma/aspetto/`).
L'**icona** (ICO, SVG, PNG o JPG fino a 1 MB, meglio quadrata; `/aspetto/icona/`) è distinta dal
logo: compare nella barra del pannello e del palinsesto e come icona della scheda del browser;
senza icona la barra mostra il logo, direttamente sul colore (un riquadro chiaro dietro si accende
con «Riquadro chiaro dietro al logo», per i loghi scuri). Un SVG si accetta solo senza codice
(niente script, eventi, collegamenti esterni, DTD) e si serve comunque in sandbox. La
pagina di accesso è componibile (`Aspetto.accesso`): posizione del logo (in alto, nel messaggio,
al centro) e altezza (24–360 px), con o senza il nome accanto, allineamento a sinistra o al
centro, fino a 8 righe di testo ognuna con grandezza, peso e colore propri; l'anteprima nel
pannello si aggiorna mentre si modifica, senza salvare.

**Stili della pagina di accesso** (`accesso.stile`): *Classico* (sfondo nel colore della
piattaforma) oppure *Oro* e *Oro con sfondo animato*, ripresi dai bozzetti «Con Powered by»: fondo
scuro, il nome della piattaforma in grande in lettere dorate con un riflesso che scorre, sopra il
**simbolo** (quello di FuturaPro, disegnato e con una stellina che brilla, oppure il logo caricato, o
niente), un separatore, le righe di testo (la prima maiuscola e spaziata) e in basso, facoltativo,
**«Powered by»** con il logo di chi fornisce il servizio (`Aspetto.logo_powered`, `/aspetto/powered/`).
Lo sfondo animato ha bagliori che fluttuano, una trama di puntini, onde concentriche, archi che
ruotano e stelline; anche il modulo di accesso si intona (fondo scuro, pulsante dorato). Tutto è
CSS e SVG nella pagina (`accesso-sfondo.html`, `accesso-simbolo.html`), senza script; i caratteri
Cinzel e Montserrat (SIL OFL) sono serviti dal server (`pannello/static/pannello/font/`). Con
«riduci movimento» del sistema le animazioni si fermano.

### Schermi: accensione, stato e allarmi

- **Accensione e spegnimento** (facoltativi; `/api/orari/`). Un orario ha fasce per giorno della
  settimana (anche oltre la mezzanotte) e giorni di chiusura (con le festività nazionali pronte),
  e vale per insegne, gruppi o schermi; vince il più preciso (schermo, poi gruppo, poi insegna).
  Il manifest lo porta in `accensione`; il player lo controlla ogni secondo anche offline e fuori
  orario riposa: schermo nero, niente audio né dirette, e libera il blocco dello schermo (Wake
  Lock), così il sistema può spegnere il monitor se le impostazioni di risparmio lo prevedono.
  Un evento straordinario lo riaccende. Senza orario: sempre acceso.
- **Stato e allarmi** (`/api/stato-schermi/`). Ogni segnale periodico (uno al minuto) aggiunge
  un minuto allo storico del giorno (`PresenzaSchermo`, con i minuti a riposo a parte): la
  disponibilità è il tempo in linea sul tempo in cui lo schermo doveva essere acceso. Gli allarmi
  email sono facoltativi (indirizzi, dopo quanti minuti, solo in orario, avviso di ritorno):
  li controlla il servizio `pianificatore` (`manage.py pianificatore`), una email per
  scollegamento; lo storico (`EventoSchermo`) resta anche senza server email.
- **Fasce di download** (facoltative; `/api/download/`). Fascia oraria e velocità massima per
  schermo (`download` nel manifest). Fuori fascia il player non scarica: tiene in onda il
  palinsesto precedente, ricorda quello nuovo (chiedendo solo se è cambiato, con l'ETag) e lo
  manda in onda appena i suoi file sono arrivati; nel pannello lo schermo risulta «aspetta la
  fascia di download». Scaricano subito: uno schermo appena installato, i file degli eventi
  straordinari delle prossime 24 ore e tutti per due ore dopo «Scarica adesso». La velocità si
  rispetta leggendo i file a pezzi.
- **Controlli degli schermi** (stessa pagina e stessa API, «Impostazioni → Download e
  aggiornamenti»). Ogni quanti secondi ogni schermo chiede se il palinsesto è cambiato (nuove
  pubblicazioni, variazioni; da 10 secondi a un'ora, predefinito 30) e se c'è una versione nuova
  del player (da un minuto a un giorno, predefinito un minuto): `controlli` nel manifest, valgono
  dal controllo successivo. Il segnale periodico resta al minuto, perché su quello contano lo
  stato «in linea», i minuti di collegamento, gli allarmi e il guardiano di Windows.

### Registro di messa in onda

Ogni zona slide annota cosa è rimasto sullo schermo e per quanto (contenuto, playlist o evento
o riserva, inizio, secondi). Il player tiene i passaggi in memoria anche dopo un riavvio (fino a
20.000) e li manda ogni 2 minuti a `POST /api/player/passaggi/`; il server li riassume per
giorno, schermo, contenuto e promozione (`MessaInOnda`), risalendo da playlist a promozione,
campagna e fornitore (campo «Fornitore / sponsor» della campagna) e conservando i nomi anche se
poi vengono cancellati. `/api/messa-in-onda/` dà i rapporti per periodo, raggruppati per
campagna, promozione, fornitore, contenuto, negozio, schermo o giorno, con filtri e
`?formato=csv`; nel pannello si stampano o salvano in PDF.

### Email e rapporti automatici

Il server di posta è **dell'azienda** (`pannello.ImpostazioniEmail`, uno per cliente, da
«Impostazioni → Email»; password cifrata con una chiave derivata da `SECRET_KEY`, mai restituita
dall'API); le variabili `FUTURAPRO_EMAIL_…` del server fanno solo da riserva. Tutte le email
passano da `core.email.invia`, nel contesto del cliente. I destinatari li sceglie ogni
funzione: allarmi degli schermi, e i rapporti automatici (`/api/invii-rapporti/`: messa in
onda con raggruppamento e filtri, tempi d'attesa, disponibilità degli schermi), ognuno con
nome, indirizzi e frequenza (ogni mattina il giorno prima, ogni lunedì la settimana prima, il
primo del mese il mese prima), testo riassuntivo e CSV allegato. Li manda `manage.py
pianificatore` (servizio `pianificatore`, ogni minuto, dalle 7): una volta per periodo, con un
nuovo tentativo dopo 30 minuti se il server di posta non risponde. «Invia adesso» manda subito
il periodo appena concluso.

### Spiegazioni al passaggio del mouse

Ogni controllo del pannello, della creazione palinsesto e degli editor (layout e ticket) ha una
spiegazione al passaggio del mouse (`data-aiuto`). Quelle dei campi stanno in
`pannello/static/pannello/aiuti-campi.js`, scheda per scheda, e si applicano da sole anche ai
controlli che compaiono dopo (es. le proprietà dell'elemento scelto): la chiave è l'etichetta del
campo, il testo del pulsante, l'intestazione della colonna della tabella o il testo di esempio.
I campi delle zone dei layout le hanno in `AIUTI_CAMPI` di `layout/static/layout/editor.js`. Una
funzione nuova deve aggiungere le sue spiegazioni lì.

### Menu del pannello

- **Hardware**: Anagrafica Dispositivi Video (abbinamento, sede, layout anche diverso per ogni
  schermo, riserva, Totem Master, stampante abbinata), Anagrafica Stampanti Ticket.
- **Contenuti**: Creazione palinsesto, Listini.
- **Code**: Reparti ed eliminacode, Coda sul telefono.
- **Plugin** (facoltativi): Info Prezzo, Info Ingredienti.
- **Panoramica** (prima voce, la pagina iniziale).
- **Report & Log**: Stato e allarmi, Distribuzione contenuti, Messa in onda, Tempi d'attesa, Registro operazioni,
  Storico allarmi.
- **Impostazioni**: Layout Video, Layout Ticket, Sedi e gruppi, Utenti, Email, Accensione e
  spegnimento, Download e aggiornamenti, Banchi Code, Aspetto interfaccia, Utenti di piattaforma (solo
  SystemAdministrator), Profilo.

Tutte le voci si aprono nella stessa pagina: «Layout Video» (l'editor, `/editor/`) e «Banchi
Code» (`/banco/`) sono mostrate dentro il pannello, sotto il menu. Le pagine di prova e le
anteprime (anteprima di uno schermo, pagina del biglietto sul telefono, pagina di accesso) si
aprono in un riquadro chiudibile (✕, Esc o clic fuori), mai in una scheda nuova del browser
(`pannello/static/pannello/riquadro.js`). Queste pagine permettono di essere incorporate solo dallo
stesso sito (`X-Frame-Options: SAMEORIGIN`); tutte le altre restano `DENY`.

### Report & Log

Il gruppo di menu «Report & Log» raccoglie stato e allarmi, messa in onda, tempi d'attesa, il **registro delle
operazioni** (`/api/audit/` per l'azienda, `/api/piattaforma/audit/` per il SystemAdministrator
con «tutta la piattaforma»; filtri per periodo, utente e testo, 100 righe per pagina, CSV) e lo
**storico degli allarmi** (`/api/storico-allarmi/`: eventi per periodo e schermo, con il
riepilogo di scollegamenti e tempo fuori linea, anche se lo schermo è ancora scollegato; CSV).

### Panoramica

La prima voce del menu e la pagina iniziale di SystemAdministrator e Administrator
(`schede-panoramica.js`, `GET /api/panoramica/`, `pannello/panoramica.py`). In cima **«Da guardare»**:
gli avvisi, prima i critici, ognuno con un clic sulla pagina dove si sistema: schermi non in
linea (e da quanto), schermi che non riescono a scaricare, schermi accesi senza nulla in onda,
promozioni che finiscono nei prossimi giorni senza che ne parta un'altra, copie o prove di accesso
dei plugin non riuscite, spazio oltre il 90%. Sotto, una scheda per argomento con il collegamento
al dettaglio: **Schermi** (in linea, fuori orario, in allarme, quelli spenti), **Contenuti sugli
schermi** (quota aggiornati, banda degli stati con legenda, promozioni non ancora arrivate
dappertutto), **Palinsesto** (in onda adesso, partono nei prossimi 7 giorni, finiscono nei
prossimi 3), **Code di oggi** (biglietti, in coda, attesa media per reparto), **Plugin** (ultima
copia, errori), **Spazio** e, per chi gestisce, **Ultime operazioni**. Lo User vede solo le sue
sedi. Il SystemAdministrator (e il Tecnico) ha anche «Tutte le aziende»
(`GET /api/piattaforma/panoramica/`): i totali della piattaforma e una riga per azienda con
semaforo, numeri e primi avvisi, prima quelle con qualcosa di critico; «Apri» sceglie l'azienda e
ne mostra la Panoramica. La pagina si aggiorna da sola ogni 30 secondi.

### Distribuzione contenuti

«Report & Log → Distribuzione contenuti» risponde a: le immagini del palinsesto o della promozione
appena salvata sono arrivate agli schermi? E cosa va in onda?

- **Il player riferisce** a ogni segnale periodico (e ogni 10 secondi mentre scarica) quanti file
  e byte del palinsesto più recente ha già nella cache, quali mancano, il file in corso con i
  byte ricevuti, la velocità media e i file non riusciti; e per ogni zona slide il contenuto in
  onda con la playlist e da che ora (`info_dispositivo.distribuzione` e `in_onda`).
- **Il server confronta** con il manifest che lo schermo dovrebbe avere adesso
  (`dispositivi/distribuzione.py`): stato per schermo (*aggiornato*, *file arrivati*, *in
  scaricamento*, *attende la fascia*, *download non riuscito*, *in arrivo*, *non in linea*, *mai
  collegato*), percentuale in byte, per negozio e per promozione (su quanti schermi destinatari
  sono arrivati tutti i suoi file e su quanti è in onda).
- **Il pannello** (`schede-distribuzione.js`) mostra anello e cartellini dei totali, la banda
  degli stati, le promozioni con la loro barra e, per negozio, una tessera per schermo con la
  miniatura di ciò che è in onda, la barra dei file, il file in corso con velocità e la fascia di
  download se si aspetta quella. Si aggiorna da sola ogni 10 secondi; filtri «Da completare» e
  «Non in linea» e ricerca.
- **Administrator** (e User, limitati alle loro sedi): la propria azienda, `GET /api/distribuzione/`.
  **SystemAdministrator e Tecnico**: anche «Tutte le aziende», `GET /api/piattaforma/distribuzione/`,
  con i totali della piattaforma e una riga per azienda che si apre su promozioni, negozi e schermi.

### Listini prezzi (facoltativi)

`/api/listini/`: tabelle di prodotti (prodotto, prezzo, unità, nota, evidenza, visibile) mostrate
dalla zona «Listino prezzi» del layout, a pagine (righe per pagina automatiche o scelte, secondi
per pagina, la pagina nuova spinge via la vecchia), con colori propri e le righe in evidenza.
Si compilano nel pannello, si importano da CSV (intestazione facoltativa, separatore `;` `,` o
tabulazione, prezzo con virgola o euro) e si esportano. Dal gestionale: un indirizzo internet
pubblico riletto ogni N minuti (si rifiutano gli indirizzi della rete interna, come per i feed)
oppure l'invio `POST /api/listini/carica/` con `Authorization: Listino <chiave>` e il CSV nel
corpo, per il gestionale in rete locale. Il player li riceve con i dati della zona (ogni minuto)
e li tiene per l'uso senza rete.

## 6. Layout grafici

Ogni cliente ha i propri layout; l'Administrator li gestisce se il SystemAdministrator glielo
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
possono puntare a indirizzi non pubblici, nemmeno attraverso un redirect: un Administrator non può
usarli per sondare la rete del server.

## 7. Eliminacode

**Dove stanno le code.** Se la sede ha un **totem** (campo *Totem delle code* della sede), le code le
tiene il **servizio code del totem** (`deploy/installa/code-totem.ps1`, attività di sistema
Windows): numeri, biglietti, chiamate di bilance e banchi, numeri per i monitor. Il negozio dà i
turni anche senza server centrale, che fornisce solo la configurazione (reparti, colori, impronte
delle chiavi) attraverso il manifest del totem. Per quella sede il server rifiuta le operazioni di
coda, così i numeri non stanno mai in due posti. Senza totem le code le tiene il server, come
descritto sotto.

**Totem Master (server code).** In un negozio ci possono essere più totem, ma i turni li detiene
uno solo: il **Totem Master**, segnato con la spunta in *Anagrafica Dispositivi Video*
(`Monitor.totem_master`, uno per sede: sceglierne un altro toglie il segno al precedente). L'IP
della sede (*Totem Master (server code)* in *Sedi e gruppi*) è il suo. Solo il manifest del master
porta la configurazione dei reparti (e copia gli annunci, inoltra il registro dei biglietti); i
totem secondari ricevono una chiave della sede (HMAC della chiave del server) e chiedono i numeri
al servizio code del master con `Authorization: Totem <chiave>`; al master arriva solo
l'impronta. Senza nessun master indicato vale il comportamento precedente: ogni totem con la zona
«prendi il numero» tiene le code in locale (va bene con un solo totem).

Servizio code del totem:

| Porta | Chi | Cosa |
|---|---|---|
| 8443 HTTPS | monitor e totem | `GET /stato` (numeri, chiunque in rete); `POST /config` (solo dal totem stesso, 127.0.0.1); `POST /emetti/<reparto>` (dal totem stesso o da un totem secondario con la chiave della sede) |
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
imposta numero, azzera. Le chiamate le fa anche lo User; configurare i reparti è della
gestione. Il banco funziona con l'accesso al pannello oppure con la **chiave del reparto**.

**Pulsantiere, bilance, script.** Una chiave per reparto, generata nel pannello (si riconosce
dall'impronta, si revoca in ogni momento), vale solo per avanti / indietro / ripeti di quel reparto.
La chiave è conservata anche cifrata (con una chiave derivata da `SECRET_KEY`): «🔗 Collegamento»
nella riga del reparto la rimostra alla gestione (`GET /api/reparti/{id}/chiave/`, annotato nel
registro) da copiare o da provare in una finestra (`#chiave=…&prova=1`: la pagina del banco la usa
senza salvarla). Un collegamento nuovo serve solo quando una bilancia si perde o si sostituisce. Le
chiavi create prima della 1.6 non sono state conservate: vanno ricreate una volta.

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
c'è su Windows e Android. Conviene far annunciare un solo monitor per negozio. L'annuncio parte
a ogni chiamata: avanti, indietro, ripeti e imposta.

**Annunci registrati** (scheda «Reparti ed eliminacode»). Un file audio per numero, come nei
pacchetti già in uso: «SALUMERIA_27.mp3» è il 27 della serie «SALUMERIA» (mp3, wav, ogg; anche
con byte a zero in testa). Si carica l'intera cartella (`POST /api/annunci/importa/`, a pezzi di
40 file): le serie si creano dal nome e si collegano da sole ai reparti con lo stesso nome; le
altre si collegano dalla colonna «Annunci (mp3)» (campo `annunci` del reparto). Una serie può
servire i reparti di più sedi. Un file senza numero caricato dentro una serie (es. «DEFAULT.mp3»)
vale per i numeri senza file. Nel pannello ogni serie mostra la griglia dei numeri: clic per
ascoltare, Alt+clic per togliere. Alla chiamata il monitor suona il file del numero (in coda,
uno dopo l'altro, se due banchi chiamano insieme); se manca, il din-don. Il manifest elenca i
file (`annunci`: reparto → serie, numero → id e impronta) e il player li tiene nella sua cache:
si sentono anche senza server. Con il totem, il player del totem li copia nel servizio code
(`C:\FuturaPro\code\annunci`, `GET/POST /annunci/<sha256>`, cancellati quando non servono
più) e i monitor del negozio li prendono da lì prima che dal server (`/api/player/annunci/<id>/`).

**Registro, tempi d'attesa e coda sul telefono.** Ogni biglietto (`Biglietto`: progressivo
della giornata, numero, emesso/chiamato, codice casuale di 10 caratteri) e ogni chiamata
(`ChiamataCoda`: avanti, indietro, ripeti, imposta, azzera, con il totale dei chiamati) resta
nel registro. Con le code sul server lo scrivono le operazioni stesse; con il totem lo scrive il
servizio code (`eventi.jsonl`, `GET /eventi?dopo=N` solo dal totem) e il player del totem lo
inoltra a `POST /api/player/code/eventi/` appena c'è rete (gli eventi già registrati non si
duplicano). Le statistiche (`/api/statistiche-code/`) danno per reparto biglietti, serviti,
attesa media, 90° percentile e massima, rinunce e serviti all'ora, la mappa giorno × ora e
l'andamento giornaliero, con le fasce da rinforzare. La coda sul telefono (facoltativa,
`/api/coda-telefono/`) stampa sul biglietto un QR (Epson: lo disegna la stampante; browser:
`player/vendor/qrcode.js`, licenza MIT) verso `FUTURAPRO_URL_PUBBLICO/b/<codice>`: una pagina
pubblica senza dati personali che legge `/api/pubblico/biglietti/<codice>/` ogni 5–15 secondi
(limite per codice, non per IP), mostra numero, servito, davanti e attesa stimata (mediana degli
intervalli di chiamata dell'ultima mezz'ora) e suona e vibra a N numeri dal turno. Il telefono
usa la sua rete dati: l'indirizzo pubblico va esposto su internet (installa.sh aggiunge a Caddy
un sito che serve solo `/b/` e `/api/pubblico/`, con certificato Let's Encrypt). `/b/prova`
mostra un biglietto inventato.

**Totem.** Il cliente tocca il reparto, il server assegna il numero, lo schermo lo mostra con
le persone che lo precedono e il player stampa:

- `browser`: stampa di sistema; con Chrome avviato con `--kiosk --kiosk-printing` esce senza
  finestre sulla stampante predefinita (biglietto da 80 mm);
- `epson`: stampante di rete Epson TM con ePOS-Print (la stessa interfaccia del sistema
  attuale), all'indirizzo indicato. Se la pagina è in HTTPS anche la stampante va usata in HTTPS
  (il suo certificato si accetta una volta sul totem). Se la stampante non risponde il totem lo
  dice e mostra comunque il numero.

**Layout Ticket** (menu **Impostazioni**, `/api/layout-ticket/`, modello `LayoutTicket`): com'è
fatto il biglietto. Elementi in colonna, nell'ordine in cui escono dalla carta: logo,
intestazione, reparto (il tasto toccato sul totem), numero, persone in coda, testo di fine
biglietto, data e ora, QR della coda sul telefono, testi liberi e linee. Due disposizioni
(`LayoutTicket.disposizione`):

- **Guidata** (in colonna): l'ordine si cambia trascinando gli elementi nell'elenco oppure
  direttamente sull'anteprima del biglietto (la linea blu mostra dove cadono; lasciandoli a
  sinistra, al centro o a destra se ne cambia anche l'allineamento).
- **Libera**: ogni elemento ha il suo riquadro (`x`, `y`, `w` in punti) e si trascina dove si
  vuole, anche affiancato ad altri; si aggancia alla griglia di 1 mm e al centro della carta (Alt:
  senza aggancio), le frecce lo spostano di un punto (Maiusc: 1 mm), e X, Y e larghezza si possono
  anche scrivere. Il testo va a capo e si allinea dentro il suo riquadro; il biglietto è lungo
  quanto serve. Passando a «Libera» ogni elemento parte da dove stava in colonna.

In entrambe un clic sull'anteprima sceglie l'elemento, e le **maniglie blu** lo ridimensionano
con il mouse: a destra la larghezza (logo e QR, e ogni riquadro nella libera), in basso la
grandezza del carattere (o lo spessore della linea), nell'angolo entrambe; logo e QR restano
proporzionati. Totem e anteprima usano lo stesso disegno (`player/ticket.js`). Per ogni elemento:
visibile, carattere, grandezza (in punti della stampante, 8 = 1 mm), grassetto, corsivo,
maiuscolo, bianco su nero, allineamento, spazio sotto; per logo e QR la larghezza. Carta 80 mm
di riferimento (80 o 58 mm); la larghezza vera è quella della stampante che lo usa: il catalogo
dei modelli (`ticket.MODELLI`, `GET /api/stampanti/modelli/`) dà i punti stampabili per carta.
**Epson TM-T20IV**: 203 dpi, 80 mm → 576 punti (72 mm, 48 colonne da 12 punti), 58 mm → 420
punti (35 colonne); con la scheda Ethernet si usa come «Epson di rete» (ePOS-Print), in USB come
«stampante di sistema» con il driver Epson APD. Le altre stampanti: 576 / 384 punti. L'editor del pannello ha l'elenco da trascinare, le proprietà
dell'elemento scelto e l'anteprima, in cui un clic sceglie l'elemento. Il logo caricato diventa
un PNG in scala di grigi alla larghezza della carta. Ogni stampante sceglie il suo layout (vuoto:
biglietto semplice). Il totem disegna il biglietto come immagine (`player/ticket.js`, lo stesso
codice dell'anteprima) e lo manda alla Epson come immagine raster ePOS-Print a strisce, o alla
stampante di sistema come immagine: esce identico con qualsiasi carattere. Il logo è retinato
(Floyd-Steinberg) perché la stampante fa solo punti neri. Intestazione e messaggio scritti
sulla stampante valgono sopra quelli del layout.

**Anagrafica Stampanti Ticket** (menu **Hardware**, `/api/stampanti/`, modello
`StampanteTicket`): l'elenco delle stampanti dei negozi — nome, sede, tipo (Epson di rete o di
sistema), indirizzo, modello, note, intestazione e messaggio facoltativi. La gestiscono
Administrator e tecnici. Ogni totem si abbina alla sua stampante in **Anagrafica Dispositivi
Video** (`Monitor.stampante`, solo una stampante della stessa sede); il manifest del totem applica
tipo e indirizzo della stampante, e intestazione/messaggio se compilati, sopra la zona «prendi il
numero». Senza stampante abbinata vale la zona del layout. La **stampa di prova**
(`POST /api/stampanti/<id>/prova/`, la può chiedere chiunque veda la stampante) la esegue un totem
abbinato e in linea — il server non vede la rete del negozio: il totem la scopre nella domanda
periodica `/api/player/schermata/` (`prova_stampa`, con i dati della stampante), stampa un
biglietto «PROVA STAMPA» che non consuma numeri e riferisce l'esito a `/api/player/prova-stampa/`
(la richiesta vale due minuti).

Le app native stamperanno direttamente sulla stampante (USB o rete).

**Modelli pronti** che ricalcano gli schermi dei supermercati: offerte con ora, meteo e reparti;
offerte e reparti; totem eliminacode.

**Dal sistema attuale.** Due problemi da non riportare: il server WebSocket accetta comandi da
chiunque sia in rete (avanti, azzera, imposta), e `php/salvadati.php` scrive un file il cui nome
arriva dalla richiesta, quindi chi è in rete può scrivere file arbitrari sul server.

## 7bis. Plugin: Info Prezzo e Info Ingredienti (facoltativi)

Li abilita il SystemAdministrator per l'azienda (`Abilitazioni.plugin_prezzo`,
`plugin_ingredienti`); l'Administrator li attiva e li configura (menu **Plugin**,
`/api/plugin/<tipo>/`, `/api/fonti-plugin/`). Senza abilitazione e attivazione non cambia nulla.

- **Info Prezzo**: un lettore di codici a barre USB (che scrive come una tastiera) collegato a un
  totem o a un monitor; letto il codice, lo schermo mostra descrizione e prezzo. In offerta
  (prezzo offerta più basso, nel periodo dal/al se indicato) compare il banner «Offerta» con il
  prezzo pieno barrato e il prezzo in offerta colorato e lampeggiante.
- **Info Ingredienti**: per i codici bilancia, riconosciuti dal **prefisso** (es. 20, 21, 22:
  ogni prefisso è un banco, perché lo stesso PLU può esistere in banchi diversi). Il PLU sta in
  una posizione configurabile (predefinita: dalla 3ª cifra, 5 cifre). Mostra ingredienti,
  allergeni e conservazione e, se richiesto e se Info Prezzo è attivo, anche il prezzo.
- Il riquadro resta per un tempo configurabile; una nuova lettura chiude quello aperto e mostra
  la nuova risposta. Carattere, grandezza, larghezza, posizione, colori, testo e colori del banner
  e lampeggio sono configurabili, con l'anteprima nel pannello.

**Dove stanno i dati.** In un file SQLite su un PC del negozio, in una cartella condivisa
(`\\indirizzo\condivisione\…\file.db`, con utente e password). Il server centrale non lo vede:
lo copia il **servizio code del Totem Master** (`code-totem.ps1` 1.6), ogni N minuti e solo se è
cambiato (dimensione e data, anche del `-wal`), in un processo a parte per non fermare le code;
dopo la copia un `PRAGMA quick_check`: se il file era in scrittura e la copia non è integra, la si
scarta, resta la precedente e si riprova dopo 2 minuti. Perché non leggerlo direttamente dalla
cartella condivisa: SQLite su una condivisione di rete non ha lock affidabili (lo sconsiglia la
documentazione di SQLite, e il modo WAL non funziona in rete), quindi si rischierebbero errori
«database is locked» proprio mentre la cassa lavora; inoltre ogni ricerca dipenderebbe dalla rete e
dal PC del negozio acceso. La copia locale è letta in sola lettura con `winsqlite3.dll` (presente in Windows 10/11,
`FpSqlite.cs`). I dispositivi del negozio interrogano `GET /plugin/prezzo` e
`GET /plugin/ingredienti` del master (`codice`, `plu`, `reparto`, `prezzo=1`), senza
internet. La password arriva solo al master (nel suo manifest, mai nell'anteprima del pannello) e
sul totem resta cifrata con DPAPI. Il master riferisce nel segnale di vita quando ha copiato il
file e gli eventuali errori, che il pannello mostra per negozio.

**Dove sono i dati nel file.** Mappatura di tabella e colonne (il server genera la SELECT con
parametri `:codice`, `:codice_corto`, `:plu`, `:reparto`) oppure una query scritta a mano (solo
SELECT, una sola istruzione). Le colonne del risultato hanno nomi fissi: `descrizione`, `prezzo`,
`prezzo_offerta`, `offerta_dal`, `offerta_al`, `unita` per Info Prezzo; `descrizione`,
`ingredienti`, `allergeni`, `conservazione` per Info Ingredienti. La mappatura predefinita
va adattata al file del gestionale.

**Gestionali pronti.** Per **EvoPos** (`evoPosDb.db`) basta scegliere «Gestionale: EvoPos»: la
query è già pronta (`plugin/query.py`, `EVOPOS`). Codici in `CodiceEan` (anche salvati a 14 cifre
con zeri davanti: si provano le varianti), articolo attivo (`Articoli.Stato = 1`), prezzo n. 1 di
`PrezziDiVendita` (al kg per gli articoli di tipo `KG`), offerte «SCONTO OFFERTA» (effetto 11)
attive oggi da `LegacyPromo` tramite `LinkArticoliLegacypromo`, con `ValoreEffetto1` sconto in
euro (prezzo in offerta = prezzo − sconto) e la data di fine. Le etichette della bilancia
(EAN-13 che inizia per 2) si cercano con le prime 7 cifre (prefisso + PLU), come le registra EvoPos.

Per **DIGI** (`DigiProject.db`, «Gestionale: DIGI» in Info Ingredienti): il PLU si trova con le
prime 7 cifre dell'etichetta, uguali a quelle del suo `Plus.BarCode1` (es. `21 1 0162` = PLU 162
della Macelleria, `21 2 0254` = Salumeria; verificato su 20.000 etichette vere); le cifre 8-12
sono il prezzo della confezione (verificato su 50.000), mostrato come «Questa confezione». Banco
da `PluDepartments` → `Departments`, ingredienti da `Ingredients` (o dal testo 5 se inizia con
«INGR»), prezzo al kg della bilancia come riserva se Info Prezzo non trova il prodotto. I testi
DIGI sono in righe da 50 caratteri spezzate anche a metà parola: il player le ricompone (circa il
91% degli a capo ricostruiti come nel testo originale, il resto è ambiguo anche a occhio), toglie
il prefisso «INGREDIENTI:», separa la parte «ALLERGENI: …» e mette in evidenza le parole in
MAIUSCOLO (gli allergeni, come in etichetta).

**Quando copiare.** Per ogni file (negozio e plugin): agli **orari** indicati e/o **ogni N
minuti**, almeno uno; il file si copia solo se è cambiato. Il file DIGI cambia a ogni pesata e può
superare 1,5 GB: meglio uno o due orari fissi e il pulsante **Aggiorna adesso** del pannello
(`POST /api/fonti-plugin/<id>/aggiorna/`) quando servono subito le modifiche. La firma dell'ultima
copia resta sul totem (`plugin/copie.json`): dopo un riavvio un file uguale non si ricopia e,
con gli orari, si aspetta l'orario. Sul totem serve spazio libero per due volte il file.

**Prova accesso.** Accanto a cartella, file, utente e password di ogni negozio, il pulsante
«Prova accesso» salva i dati e chiede al Totem Master del negozio di provarli
(`POST /api/fonti-plugin/<id>/prova/`): il totem lo vede entro pochi secondi, apre la cartella
condivisa con quelle credenziali, controlla che il file ci sia e sia un database SQLite e
riferisce (`POST /api/player/prova-plugin/`). Il LED diventa verde («Accesso riuscito: file di
… MB, modificato il …») o rosso con il motivo (cartella non raggiungibile o credenziali errate,
file mancante, file che non è SQLite); lampeggia giallo mentre si aspetta, e se in 2 minuti il
totem non risponde lo dice.

**Più totem.** Solo il Totem Master legge i file; gli altri totem e i monitor del negozio
chiedono prezzi e ingredienti al suo servizio (`https://IP-master:8443/plugin/…`).

**File troppo grandi da spedire.** `deploy/installa/struttura-sqlite.ps1` scrive struttura e
righe di esempio in un testo di pochi KB e cerca dei codici in tutte le colonne.

## 8. Player

**Certificati senza confronti a occhio.** Lo script di Windows deve fidarsi del certificato
interno del server e di quello del Totem Master. Il pannello (in HTTPS, quindi già sicuro) mostra
in Anagrafica Dispositivi Video i comandi pronti per negozio (`GET /api/installazione/`,
`dispositivi/installazione.py`) con dentro le impronte: `-Impronta` (calcolata dal certificato di
Caddy, che l'app chiede a Caddy allo stesso indirizzo da cui lo scaricano i player,
`FUTURAPRO_CA_URL`, perché la cartella di Caddy non le è leggibile) e, per i monitor,
`-ImprontaTotem`, che il player del Totem Master calcola dal `certificato.cer` del suo servizio
code e manda con il segnale periodico (`info_dispositivo.impronta_totem`). Lo script confronta da
solo e si ferma se non coincidono; un certificato già presente tra quelli attendibili del PC
(reinstallazione) non chiede nulla; senza impronta nel comando resta il confronto a mano.

**Guardiano della postazione (Windows).** Lo script di installazione dà a ogni PC un codice
casuale (`impostazioni.json`, resta uguale se si reinstalla) e lo passa al player nell'indirizzo
(`/player/?postazione=…`, poi salvato nel browser); il player lo manda con il segnale periodico e
il server ne conserva solo l'impronta e l'ora (`SegnalePostazione`, fuori dalla RLS perché non ha
dati dell'azienda). Il guardiano (`C:\FuturaPro\avvia.ps1`) riapre il browser se si chiude e ogni
2 minuti chiede `GET /api/player/postazione/<codice>/` (senza credenziali, con un limite di
richieste): se il server risponde che il player tace da più di 5 minuti — pagina bloccata o in
crash — chiude il browser, che riparte da solo; dopo un avvio aspetta 10 minuti prima di
controllare di nuovo. Se il server non risponde, o la postazione non si è ancora abbinata (404),
non fa nulla.

**Senza server.** Il player conserva manifest (`localStorage`), file (Cache API, chiesta come
persistente con `navigator.storage.persist()`) e pagina (service worker): a server spento, anche
dopo un riavvio del PC, riparte con il palinsesto salvato e lo segue da solo con le sue regole di
date e orari fino alla fine delle promozioni già scaricate, poi mostra il default. Meteo, notizie
e listini usano l'ultimo dato ricevuto; le code restano sul Totem Master.

**Versione e aggiornamento automatico.** La versione del player web si calcola da sola dal
contenuto dei suoi file (`player/versione.py`: `web-<BASE>-<impronta>`, es. `web-1.5-3b4875b`):
ogni modifica a pagina, motore, stili o service worker dà una versione nuova, senza numeri da
ricordarsi di cambiare; anche la cache del service worker prende quel nome. Il player la manda a
ogni segnale periodico e il server risponde con quella attuale (`{"versione_player": …}`): se è
diversa il player aggiorna il service worker e si ricarica (il palinsesto riparte subito dalla
copia salvata); verso la stessa versione riprova al massimo ogni 30 minuti, così non si ricarica
all'infinito se qualcosa va storto. Ogni quanto guardare la versione (e il palinsesto) lo decide il
pannello: vedi «Controlli degli schermi». In «Stato e allarmi» la colonna Player mostra la versione che
gira davvero su ogni schermo, con «da aggiornare» se non è l'ultima; la Panoramica avvisa degli
schermi rimasti indietro. I player di una versione precedente alla 1.5 non hanno ancora questo
meccanismo: vanno riavviati una volta a mano, poi si aggiornano da soli.

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
3. L'Administrator (o il SystemAdministrator) inserisce il codice nel pannello, sceglie nome e
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

**Chi.** Solo SystemAdministrator e Tecnici Teleassistenza, su tutti i clienti. Accesso al
pannello con 2FA obbligatoria (WebAuthn, in alternativa TOTP). L'Administrator vede il registro,
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
(c'è un solo cliente); la licenza firmata e il contratto regolano l'accesso del gestore della piattaforma.

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
| `GET/POST/PATCH /api/piattaforma/clienti/` | lettura: SystemAdministrator, Tecnico — scrittura: SystemAdministrator |
| `GET/POST/PATCH/DELETE /api/piattaforma/utenti/` | SystemAdministrator |
| `GET /api/piattaforma/audit/` | SystemAdministrator |
| `PATCH /api/io/` (profilo: tema, nome utente, nome, email, password con `password_attuale`) | tutti gli autenticati, per sé |
| `GET /api/distribuzione/` | tutti (User: le sue sedi) |
| `GET /api/panoramica/` | tutti (User: le sue sedi, senza registro) |
| `GET /api/piattaforma/panoramica/` | SystemAdministrator, Tecnico |
| `GET /api/piattaforma/distribuzione/` | SystemAdministrator, Tecnico |
| `GET/PATCH /api/abilitazioni/` | lettura: SystemAdministrator, Administrator — scrittura: SystemAdministrator |
| `/api/sedi/`, `/api/gruppi/` | lettura: tutti — scrittura: SystemAdministrator, Administrator |
| `GET/PATCH/DELETE /api/monitor/`, `POST /api/monitor/abbina/` | lettura: tutti — scrittura: SystemAdministrator, Administrator (se abilitato) |
| `/api/utenti/` | SystemAdministrator, Administrator (se abilitato; solo gli User) |
| `GET /api/audit/` | SystemAdministrator, Administrator |
| `GET /api/teleassistenza/sessioni/` | SystemAdministrator, Tecnico, Administrator |
| `POST /api/teleassistenza/sessioni/`, `POST …/{id}/chiudi/` | SystemAdministrator, Tecnico |
| `/api/contenuti/` (upload multipart), `GET /api/contenuti/{id}/file/` | lettura: tutti — scrittura: SystemAdministrator, Administrator, User |
| `/api/playlist/`, `/api/pubblicazioni/` | lettura: tutti — scrittura: SystemAdministrator, Administrator, User |
| `POST /api/pubblica/` | SystemAdministrator, Administrator, User |
| `GET /api/anteprima/{monitor}/?quando=` | tutti |
| `/api/layout/`, `POST /api/layout/da-modello/`, `GET /api/layout/modelli/` | lettura: tutti — scrittura: SystemAdministrator, Administrator (se abilitato) |
| `GET /api/zone/{id}/dati/`, `GET /api/anteprima/{monitor}/manifest/` | tutti (anteprima) |
| `GET /api/meteo/localita/?nome=` | SystemAdministrator, Administrator |
| `POST /api/player/abbinamento/`, `GET /api/player/stato/`, `POST /api/player/heartbeat/` | player |
| `GET /api/player/zone/{id}/dati/`, `POST /api/player/zone/{id}/emetti/` | player |
| `/api/reparti/` | lettura: tutti — scrittura: SystemAdministrator, Administrator |
| `POST /api/reparti/{id}/avanti/` (anche `indietro`, `ripeti`, `imposta`, `azzera`, `emetti`) | SystemAdministrator, Administrator, User |
| `GET/POST/DELETE /api/reparti/{id}/chiave/` | SystemAdministrator, Administrator |
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
   - [x] Eliminacode: file audio propri (annunci registrati, copiati sul totem)
   - [ ] Eliminacode: statistiche di attesa, coda seguita dal telefono (QR)
   - [x] Editor visuale dei layout (zone da trascinare e configurare, orizzontale e verticale)
   - [ ] Pannello web completo con selettore azienda (contenuti, monitor, utenti, reparti)
   - [ ] Player Android e Windows con cache offline
   - [ ] 2FA, Docker Compose, CI
2. **Teleassistenza (circa 2 mesi):** CA, mTLS, segnalazione WebSocket, WebRTC, coturn, agent
   Android e Windows, aggiornamenti remoti.
3. **Professionale:** prova di trasmissione, widget dati, avvisi, rilascio graduale, API pubbliche.
4. **Avanzato:** video wall sincronizzati, contenuti interattivi.
