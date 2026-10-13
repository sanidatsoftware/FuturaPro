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
| Motore di rendering | Libreria TypeScript condivisa tra anteprima del pannello e player | da fare |
| Player Android | Kotlin, WebView per i layout + Media3/ExoPlayer per i video, device owner | da fare |
| Player Windows | Servizio .NET 8 (watchdog, aggiornamenti, teleassistenza) + app WebView2 | da fare |
| Teleassistenza | Segnalazione WSS con mTLS, WebRTC, relay coturn nostro | da fare |
| Distribuzione | Docker Compose: un unico pacchetto per cloud e installazione presso il cliente | da fare |

Dimensionamento: centinaia di schermi per installazione. Basta un server
(PostgreSQL + Redis + coturn), senza Kubernetes.

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
si validano solo contro il cliente corrente. I file saranno salvati per cliente e serviti
con link firmati a scadenza.

**Fuori dalla RLS, di proposito:** `utenti_utente` (il login la legge prima di sapere chi è
l'utente; le viste la filtrano), `dispositivi_richiestaabbinamento` (un player non ancora
abbinato non ha cliente), `dispositivi_credenzialedispositivo` (dice a quale cliente appartiene
un player: va letta per prima). Contengono solo impronte, mai segreti.

**Test.** `server/core/tests/test_isolamento.py` prova ogni barriera da sola: togliendo l'una o
l'altra, falliscono test diversi. Un test che fallisce blocca il rilascio.

## 5. Player

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

**Funzionamento** (da fare): manifest della programmazione con hash dei file, download
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

## 6. Teleassistenza

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

## 7. Hardware Android — cosa verificare

- Android 11 o superiore (meglio 12–14).
- Decodifica hardware 4K H.264/H.265; almeno 32 GB eMMC; Ethernet.
- Accensione automatica al ritorno della corrente; watchdog hardware se disponibile.
- **Domanda al fornitore:** forniscono la firma di sistema per le app, oppure il dispositivo
  supporta il provisioning *device owner* via QR?
- Piattaforme consigliate: Rockchip RK3566/RK3568/RK3588.
- Attenzione: i monitor professionali Samsung (Tizen) e LG (webOS) **non sono Android**.

## 8. API disponibili

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
| `POST /api/player/abbinamento/`, `GET /api/player/stato/`, `POST /api/player/heartbeat/` | player |

## 9. Roadmap

1. **MVP (3–4 mesi)**
   - [x] Clienti, abilitazioni, ruoli, isolamento a due barriere, audit immutabile
   - [x] Sedi, gruppi, monitor, abbinamento con codice, heartbeat
   - [x] Registro e permessi della teleassistenza
   - [ ] Libreria contenuti (upload, anteprime, quote), playlist, programmazione a calendario
   - [ ] Flusso *carica → scegli monitor → Pubblica*
   - [ ] Pannello web React con selettore azienda
   - [ ] Player Android e Windows con cache offline
   - [ ] 2FA, Docker Compose, CI
2. **Teleassistenza (circa 2 mesi):** CA, mTLS, segnalazione WebSocket, WebRTC, coturn, agent
   Android e Windows, aggiornamenti remoti.
3. **Professionale:** prova di trasmissione, widget dati, avvisi, rilascio graduale, API pubbliche.
4. **Avanzato:** video wall sincronizzati, contenuti interattivi.
