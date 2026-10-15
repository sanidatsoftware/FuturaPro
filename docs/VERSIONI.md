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
