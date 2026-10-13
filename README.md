# FuturaPro

Piattaforma di videocomunicazione per più aziende clienti: pannello web, player Windows e
Android, teleassistenza remota proprietaria.

- **Installazione** (server Ubuntu, monitor e totem Windows, bilance e pulsanti):
  [`docs/INSTALLAZIONE.md`](docs/INSTALLAZIONE.md).
- **Specifica tecnica** (architettura, ruoli, isolamento tra clienti, eliminacode, teleassistenza,
  roadmap): [`docs/SPECIFICA.md`](docs/SPECIFICA.md).

## Struttura

- `server/` — API Django: clienti, utenti e ruoli, sedi, monitor e abbinamento dei player,
  contenuti, playlist e palinsesto, layout grafici, audit, teleassistenza.
- `server/player/` — motore di rendering e player nel browser (`/player/`).
- `server/eliminacode/` — code dei reparti, pagina del banco (`/banco/`), pulsantiere e totem.
- `deploy/` — installazione del server (Docker Compose, Caddy per HTTPS, backup, aggiornamenti) e,
  in `deploy/installa/`, lo script per i PC Windows e quello per i pulsanti.
- `docs/` — specifica e guida di installazione.

## Avvio in sviluppo

Serve PostgreSQL 16 (l'isolamento tra clienti usa la sua Row-Level Security).

```bash
docker compose -f server/sviluppo/docker-compose.yml up -d   # oppure un PostgreSQL locale con server/sviluppo/crea-ruolo.sql
cd server
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export FUTURAPRO_DEBUG=1
python manage.py migrate
python manage.py crea_admin_assoluto admin
python manage.py runserver
```

Per vedere subito qualcosa: `python manage.py dati_dimostrativi --password "…"` crea il cliente
«Demo» (utente `demo_admin`) con layout, slide e notizie. Apri <http://localhost:8000/player/>:
mostra un codice; abbinalo dal pannello (<http://localhost:8000/pannello/>, sezione Monitor).

L'API è navigabile su <http://localhost:8000/api/> dopo il login su `/api/sessione/login/`.
Gli utenti di piattaforma scelgono il cliente con l'intestazione `X-Cliente: <uuid>`.

## Test

```bash
cd server && FUTURAPRO_DEBUG=1 python manage.py test
node --test server/player/static/player/regole.test.mjs   # dalla radice del repository
```

L'utente del database non deve essere superuser né avere `BYPASSRLS`:
`python manage.py check --database default` lo verifica.
