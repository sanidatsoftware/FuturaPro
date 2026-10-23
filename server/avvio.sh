#!/bin/sh
# Avvio del container: aggiorna il database, pubblica i file statici, parte il server.
# migrate esegue anche i controlli sul database: si ferma se l'utente PostgreSQL
# potesse aggirare la Row-Level Security (futurapro.E001).
set -e
# Il modello del Filtro contenuti, se non è arrivato con l'immagine (non blocca l'avvio).
timeout 300 python plugin/modello/scarica_modello.py "${FUTURAPRO_MEDIA_ROOT:-/dati/media}/plugin" || true
python manage.py migrate --noinput
python manage.py collectstatic --noinput -v 0
exec gunicorn futurapro.wsgi \
    --bind 0.0.0.0:8000 \
    --workers "${FUTURAPRO_PROCESSI:-3}" \
    --threads 4 \
    --timeout 300 \
    --access-logfile - \
    --forwarded-allow-ips '*'
