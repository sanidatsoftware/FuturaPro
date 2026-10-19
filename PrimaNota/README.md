# Documentale Prima Nota v1

Portale Flask/Docker per:
- scansioni: chiusura fiscale, POS bancari, resi, transazioni abortite, versamenti contante;
- flag `lavorato` separato per i versamenti;
- note, anomalie e richieste di contatto;
- monitor tabellare per negozio/data;
- acquisizione automatica e archiviazione del pregresso `SysSpy.YYYYMMDD.CASSA` da una condivisione per negozio;
- salvataggio del testo con rimozione delle prime 4 colonne e anteprima Consolas Regular 11pt;
- estrazione automatica delle sezioni Chiusura POS e Chiusura Fiscale;
- indicizzazione persistente e ricerca nel testo/numero scontrino;
- modulo `Ricerca Matricole` protetto da permesso amministrativo, collegato a SQL Server e alla stored procedure `dbo.RicercaMatricole` del vecchio programma VB.NET.

## Installazione

```bash
cd /opt/tocal
unzip DocumentalePrimaNota_v1.zip
cd DocumentalePrimaNota_v1
chmod +x genera_env.sh
./genera_env.sh
nano .env
# cambiare ADMIN_PASSWORD

docker compose up -d --build
```

Aprire `http://IP_SERVER:8096`.

## Primo avvio
1. Login con utente admin configurato in `.env`.
2. **Negozi**: censire codice, descrizione e percorso condiviso di ogni negozio. Per SMB si può usare `\\server\share\cartella`; utente/password vengono salvati cifrati.
3. Premere **Importa nuovi/pregresso** sul negozio. La prima esecuzione importa tutto lo storico; le successive saltano i files già archiviati in base a percorso/dimensione/mtime.
4. **Ricerca testi** consente ricerca per parole chiave o numero scontrino sul testo pulito.
5. **Utenti**: abilitare per singolo utente il permesso “Ricerca Matricole”.
6. **DB legacy**: configurare SQL Server del database `Scontrini`. Nessuna password è hardcoded nel progetto.

## Archivio
Il file originale viene copiato in `archive/<negozio>/<YYYYMMDD>/<cassa>/`.
Nel DB viene salvato anche il testo pulito (prime quattro colonne rimosse). L'indice SQLite FTS è persistente in `data/documentale.sqlite3`.

## Nota rete SMB
Il container deve poter raggiungere il server SMB sulla porta TCP 445. In alternativa è possibile montare la share sul Linux host e indicare un percorso locale, ad esempio `/mnt/negozi/5048/sys_spy`, aggiungendo il relativo bind mount al `docker-compose.yml`.
