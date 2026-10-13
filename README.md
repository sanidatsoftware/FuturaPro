# FuturaPro

Piattaforma di videocomunicazione per più aziende clienti: pannello web, player Windows e
Android, teleassistenza remota proprietaria.

La specifica tecnica (architettura, ruoli, isolamento tra clienti, teleassistenza, roadmap) è in
[`docs/SPECIFICA.md`](docs/SPECIFICA.md).

## Struttura

- `server/` — API Django: clienti, utenti e ruoli, sedi, monitor e abbinamento dei player,
  contenuti, playlist e palinsesto, layout grafici, audit, teleassistenza.
- `server/player/` — motore di rendering e player nel browser (`/player/`).
- `docs/` — specifica.

## Avvio in sviluppo

Serve PostgreSQL 16 (l'isolamento tra clienti usa la sua Row-Level Security).

```bash
docker compose up -d db          # oppure un PostgreSQL locale con server/sviluppo/crea-ruolo.sql
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
mostra un codice; abbinalo con `POST /api/monitor/abbina/` (codice, nome, sede e gruppo «Tutti»).

L'API è navigabile su <http://localhost:8000/api/> dopo il login su `/api/sessione/login/`.
Gli utenti di piattaforma scelgono il cliente con l'intestazione `X-Cliente: <uuid>`.

## Test

```bash
cd server && FUTURAPRO_DEBUG=1 python manage.py test
node --test server/player/static/player/regole.test.mjs   # dalla radice del repository
```

L'utente del database non deve essere superuser né avere `BYPASSRLS`:
`python manage.py check --database default` lo verifica.
