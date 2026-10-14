# Installare FuturaPro

Tre passi, in quest'ordine:

1. **il server** sulla macchina virtuale Ubuntu;
2. **i monitor** (PC Windows collegati agli schermi);
3. **i totem** (PC Windows touch con la stampante dei biglietti).

Poi si collegano **bilance DIGI** e **pulsanti** al banco (ultima sezione).

> Nella guida `SERVER` è l'indirizzo del server: l'IP della VM in rete locale
> (es. `10.0.100.41`) oppure il suo nome di dominio (es. `signage.miodominio.it`).

---

## 1. Server (Ubuntu Server 22.04 o 24.04)

### Prima di iniziare

- VM con **4 vCPU, 8 GB di RAM** e un disco di almeno **60 GB** (i contenuti crescono: meglio di più).
- **IP fisso**: un indirizzo statico o una prenotazione DHCP. Se l'IP cambia, monitor e totem
  non trovano più il server e il certificato va rifatto.
- Porte aperte verso la VM: **80** e **443** (TCP). Se sulla VM è attivo il firewall `ufw`:

  ```bash
  sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
  ```

- Per un **nome di dominio pubblico** (certificato Let's Encrypt): il dominio deve puntare alla VM
  e le porte 80 e 443 devono essere raggiungibili da internet.
  Per l'uso **solo in rete locale** basta l'IP: il server crea un certificato interno.

### Scaricare FuturaPro

Il repository è privato, quindi serve un **token di accesso GitHub in sola lettura**:

1. su GitHub: foto profilo → **Settings** → **Developer settings** → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**;
2. *Repository access*: **Only select repositories** → `sanidatsoftware/FuturaPro`;
3. *Permissions* → *Repository permissions* → **Contents: Read-only**;
4. genera e copia il token (inizia con `github_pat_`).

Poi, sulla VM:

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/sanidatsoftware/FuturaPro.git /opt/futurapro
```

Come *Username* scrivi il tuo utente GitHub, come *Password* incolla il token.

> In alternativa, senza token sulla VM: dalla pagina del repository su GitHub (ramo `main`),
> **Code → Download ZIP**; copia lo ZIP sulla VM (es. con WinSCP) ed estrailo in `/opt/futurapro`
> (`sudo apt install -y unzip && sudo unzip FuturaPro-*.zip -d /opt && sudo mv /opt/FuturaPro-* /opt/futurapro`).

### Installare

```bash
cd /opt/futurapro/deploy
sudo ./installa.sh
```

Lo script installa Docker (se manca) e poi chiede:

| Domanda | Cosa rispondere |
|---|---|
| Indirizzo | l'IP della VM (proposto) o il nome di dominio |
| Email per Let's Encrypt | solo con un dominio: un indirizzo a cui arrivano gli avvisi sul certificato |
| Banco in HTTP per la rete locale | **S** se usi le bilance DIGI (vedi sezione 4) |
| SystemAdministrator | nome utente e password (almeno 10 caratteri) con cui entri nel pannello |
| Cliente dimostrativo | **s** per avere subito reparti, layout e slide di prova |

La prima volta ci vogliono alcuni minuti. Alla fine lo script mostra:

- gli indirizzi di **pannello**, **player** e **banco**;
- il **comando per installare i PC Windows**;
- con il certificato interno, la sua **impronta**: **annotala**, la confronterai su ogni PC Windows.

Apri `https://SERVER/pannello/` ed entra con il SystemAdministrator. Con il certificato interno il
browser del tuo PC mostrerà un avviso finché non installi il certificato anche lì (vedi sotto).

### Primo giro nel pannello

1. **Clienti**: crea il cliente (es. «Nome azienda») e il suo primo Administrator.
2. In alto scegli il cliente, poi **Sedi e gruppi**: crea la sede (es. «Catania via Etnea») e un
   gruppo «Tutti».
3. **Reparti ed eliminacode**: crea Salumeria, Macelleria, Gastronomia… con i loro colori.
4. **Layout ↗**: parti da un modello (es. «Supermercato: offerte, ora, meteo e reparti» e
   «Totem eliminacode») e adattalo; segna come *Predefinito* quello orizzontale e quello verticale.
5. **Creazione palinsesto**: crea una campagna con i suoi destinatari (es. il gruppo «Tutti»),
   poi carica le immagini delle offerte e crea la promozione con le sue date.

### Gestione quotidiana

| Cosa | Comando (sulla VM) |
|---|---|
| Stato dei servizi | `cd /opt/futurapro/deploy && sudo docker compose ps` |
| Log del server | `sudo docker compose logs -f app` |
| Riavvio | `sudo docker compose restart` |
| Aggiornamento | `sudo ./aggiorna.sh` (fa prima un backup) |
| Backup manuale | `sudo ./backup.sh` |

I **backup** si fanno da soli ogni notte alle 2:30 in `/opt/futurapro/deploy/backup/` (database e
contenuti, tenuti 14 giorni). Copiali anche fuori dalla VM.

Rilanciare `sudo ./installa.sh` è sicuro: password e dati restano, si aggiornano solo le risposte
(per esempio un nuovo indirizzo).

### Coda sul telefono (facoltativo)

Per il QR sul biglietto i telefoni dei clienti devono raggiungere il server da internet:
1. un nome (es. `coda.miodominio.it`) che punti all'IP pubblico della sede del server;
2. porte 80 e 443 del router inoltrate alla VM;
3. in `/opt/futurapro/deploy/.env` la riga `FP_URL_PUBBLICO=https://coda.miodominio.it`;
4. `cd /opt/futurapro/deploy && sudo ./installa.sh` (rigenera la configurazione di Caddy).

Da internet si raggiungono solo la pagina del biglietto e i suoi dati, mai il pannello. Poi si
attiva dal pannello in «Code → Coda sul telefono». Sul totem va rilanciata l'installazione
(servizio code 1.2) perché il biglietto abbia il suo codice.

### Email (facoltativo)

Ogni azienda imposta il **suo** server di posta nel pannello, in «Impostazioni → Email (server di
posta)»: server SMTP, porta, utente, password (conservata cifrata) e mittente del proprio
dominio. Da lì partono allarmi degli schermi e rapporti automatici; i destinatari si scelgono in
ogni funzione. «Invia un'email di prova» verifica che funzioni.

Solo se serve un server di riserva per tutte le aziende che non ne impostano uno, si possono
aggiungere in fondo a `/opt/futurapro/deploy/.env`:

```
FP_EMAIL_HOST=smtp.miodominio.it
FP_EMAIL_PORT=587
FP_EMAIL_UTENTE=futurapro@miodominio.it
FP_EMAIL_PASSWORD=la-password
FP_EMAIL_MITTENTE=FuturaPro <futurapro@miodominio.it>
```

e poi `cd /opt/futurapro/deploy && sudo docker compose up -d`. Allarmi e rapporti li manda il
servizio `pianificatore`, ogni minuto (i rapporti dalle 7 del mattino).

---

## 2. Monitor (Windows 10/11)

> Se il negozio ha un **totem** per i biglietti, installa **prima il totem** (sezione 3): i monitor
> leggono i numeri dei reparti da lui, e la loro installazione ne chiede l'indirizzo.

Serve **Google Chrome** (consigliato) o Microsoft Edge, già presente su Windows.

1. Accedi a Windows con l'utente che userà il monitor (meglio un utente locale dedicato, es. «schermo»,
   amministratore solo per l'installazione).
2. Apri **PowerShell come amministratore** (tasto destro su Start → *Terminale (Amministratore)*).
3. Incolla il comando mostrato alla fine dell'installazione del server:

   ```powershell
   irm http://SERVER/installa/player-windows.ps1 -OutFile $env:TEMP\futurapro.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\futurapro.ps1 -Server SERVER
   ```

4. Alla domanda sul tipo rispondi **1 (monitor)**. Poi lo script chiede l'**IP del totem** del
   negozio (vuoto se non c'è) e ne mostra l'impronta del certificato: deve coincidere con quella
   mostrata alla fine dell'installazione del totem.
5. Con il certificato interno lo script mostra un'**impronta**: deve essere **identica** a quella
   annotata dall'installazione del server. Se coincide rispondi **S**.

Lo script:

- installa il certificato del server;
- fa partire il browser a schermo intero sul player a ogni accesso, e lo riapre se si chiude;
- disattiva sospensione e spegnimento dello schermo.

Sullo schermo compare un **codice di 6 cifre**. Nel pannello: **Monitor → Abbina uno schermo** →
codice, nome, sede, tipo *Monitor orizzontale*, gruppo «Tutti» → **Abbina**. In pochi secondi il
monitor mostra il layout.

**Accesso automatico** (così dopo un'interruzione di corrente riparte da solo): `Win+R` →
`netplwiz` → togli la spunta a *«Per utilizzare questo computer è necessario che l'utente immetta il
nome utente e la password»* → inserisci la password dell'utente. Nel BIOS del PC imposta anche
l'accensione automatica al ritorno della corrente (*Restore on AC power loss: Power On*).

Monitor montato in verticale? Nel pannello, in **Monitor**, scegli *Verticale* e la **rotazione**
(90° o 270°).

**Uscire dal player**: `Ctrl+Alt+Canc` → *Esci*, oppure Gestione attività.
**Toglierlo dal PC**: stesso comando, aggiungendo `-Rimuovi`.

---

## 3. Totem (Windows 10/11, touch, con stampante)

**Il totem gestisce le code del negozio.** Assegna i numeri dei biglietti, riceve le chiamate di
bilance e banchi, dà i numeri ai monitor: tutto nella rete del negozio, anche se il server centrale
non è raggiungibile. Dal server riceve solo la configurazione (nomi e colori dei reparti, chiavi
delle bilance) e i contenuti da mostrare.

Al totem serve un **IP fisso** (indirizzo statico o prenotazione DHCP): monitor e bilance lo
chiamano per indirizzo.

1. **Prima** installa la stampante dei biglietti in Windows e impostala come **predefinita**
   (Epson TM: driver *Epson Advanced Printer Driver*, carta 80 mm). Stampa una pagina di prova da
   Windows.
2. Lancia lo stesso comando PowerShell del monitor e alla domanda sul tipo rispondi **2 (totem)**.
   Lo script conferma l'IP del totem e installa, oltre al player:
   - il **servizio code** («FuturaPro Code»), che parte all'accensione anche senza nessuno collegato;
   - il suo certificato e le regole del firewall per le porte **8443** (monitor) e **8090** (bilance).

   Alla fine mostra l'**impronta del certificato del totem**: annotala, la chiederanno i monitor.
3. Nel pannello: **Sedi e gruppi → Totem delle code**, scrivi l'IP del totem accanto alla sede e
   **Salva**. Da quel momento le code della sede le tiene il totem.
4. Abbina il totem (**Monitor → Abbina**) con il tipo **Totem verticale**. Nel layout del totem
   (**Layout ↗** → zona *Prendi il numero*) imposta **Stampa del biglietto: Stampante di sistema**.

Lo stato delle code è salvato sul totem (`C:\FuturaPro\code\stato.json`) e sopravvive ai
riavvii; ogni giorno le code ripartono da 0. Registro delle operazioni:
`C:\FuturaPro\code\registro.log`.

La stampante non risponde? Il totem lo dice e mostra comunque il numero al cliente.

> **Stampante Epson di rete senza driver (ePOS).** Nel layout scegli *Stampante Epson di rete* e
> scrivi l'indirizzo IP della stampante. Siccome il player è in HTTPS, anche la stampante va usata in
> HTTPS: rilancia lo script con `-Configura`, apri `https://IP-STAMPANTE`, accetta il certificato,
> chiudi la finestra. La strada con il driver di Windows è più semplice e robusta.

---

## 4. Bilance DIGI e pulsanti del banco

**Non è identico a prima.** Oggi le bilance aprono le pagine `digi/*.php` del vecchio server; con
FuturaPro il browser della bilancia apre la **pagina del banco**, con gli stessi comandi: *Avanti*,
*Indietro*, *Ripeti*, *Imposta*, *Azzera*. Cambia solo l'indirizzo da impostare, e va fatto una volta
per bilancia.

1. Pannello → **Reparti ed eliminacode** → riga del reparto (es. Salumeria) → **Crea collegamento**.
2. Compaiono due indirizzi del tipo `…/banco/#chiave=…`. Il collegamento appare **solo ora**:
   copialo subito.
   - **Con il totem** (il caso normale): gli indirizzi puntano al totem. Per la bilancia usa il primo,
     `http://IP-TOTEM:8090/banco/#chiave=…`. Il totem riceve la nuova chiave entro mezzo minuto.
   - Senza totem puntano al server: usa quello **https** se il browser della bilancia accetta il
     certificato del server, altrimenti quello **http** (solo dalla rete del negozio, se
     all'installazione hai risposto **S** al banco in HTTP).
3. Sulla bilancia imposta quell'indirizzo come **pagina iniziale** del browser e aprilo una volta: la
   chiave resta salvata sulla bilancia e sparisce dall'indirizzo.

La chiave vale solo per quel reparto e solo per i comandi del banco. Bilancia persa o sostituita?
**Revoca** o **Nuovo collegamento** dal pannello: il vecchio smette subito di funzionare.

**Pulsanti fisici o script** (al posto di `py/salumeria+.py` e simili), con Python 3 e niente da
installare:

```bash
curl -O http://SERVER/installa/pulsante.py
python3 pulsante.py https://SERVER CHIAVE avanti      # oppure: indietro, ripeti, azzera, imposta 27
```

`CHIAVE` è la parte dopo `#chiave=` del collegamento. Con il certificato interno aggiungi
`--ca futurapro-ca.crt`, scaricato da `http://SERVER/futurapro-ca.crt`. **Con il totem** si chiama lui:
`python3 pulsante.py http://IP-TOTEM:8090 CHIAVE avanti --totem`.

**Dal banco con tablet o PC**: con il totem, lo stesso collegamento del reparto delle bilance
(`http://IP-TOTEM:8090/banco/#chiave=…`). Senza totem, `https://SERVER/banco/` con l'utente del
pannello (anche un UserCliente): mostra tutti i reparti della sede.

### Cosa funziona senza server centrale

| | Senza server centrale |
|---|---|
| Slide | continuano; il monitor si riaccende con l'ultimo palinsesto ricevuto |
| Orologio, meteo, notizie | orologio sì; meteo e notizie restano all'ultimo dato ricevuto |
| Biglietti, chiamate, numeri a schermo | sì, se c'è il totem (la rete del negozio basta) |
| Nuove pubblicazioni, abbinamenti, pannello | no: riprendono quando il server torna |

---

## Certificato interno sul tuo PC (per usare il pannello senza avvisi)

Solo se il server usa il certificato interno (installazione con l'IP). Sul PC Windows da cui usi il
pannello, in PowerShell come amministratore:

```powershell
irm http://SERVER/futurapro-ca.crt -OutFile $env:TEMP\futurapro-ca.crt
Import-Certificate -FilePath $env:TEMP\futurapro-ca.crt -CertStoreLocation Cert:\LocalMachine\Root
```

Prima del secondo comando confronta l'impronta, che deve coincidere con quella annotata:

```powershell
$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 "$env:TEMP\futurapro-ca.crt"
-join ([Security.Cryptography.SHA256]::Create().ComputeHash($c.RawData) | % { $_.ToString("X2") })
```

---

## Se qualcosa non va

| Problema | Cosa fare |
|---|---|
| Il player resta su «Server non raggiungibile» | Dal PC apri `https://SERVER/player/` nel browser: se dà errore di certificato, rilancia lo script di installazione; se non si apre, controlla rete e firewall della VM. |
| Lo schermo mostra il codice ma il pannello dice «Codice inesistente o scaduto» | Il codice vale 15 minuti; se è scaduto lo schermo ne mostra uno nuovo da solo. |
| Il totem non stampa | Stampa una pagina di prova da Windows; la stampante deve essere la *predefinita*; il layout deve avere *Stampante di sistema*. |
| La bilancia dice «Non collegato» | Il collegamento è stato revocato o rigenerato: creane uno nuovo dal pannello. |
| Lo script Windows dice che l'impronta non coincide | **Non proseguire**: il PC potrebbe non parlare con il tuo server. Controlla l'indirizzo. |
| Log del server | `sudo docker compose -f /opt/futurapro/deploy/docker-compose.yml logs --tail 200 app` |
