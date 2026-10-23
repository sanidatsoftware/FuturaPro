#!/bin/bash
# Backup giornaliero (lo lancia cron, vedi /etc/cron.d/futurapro): database e
# contenuti caricati, conservati per 14 giorni in deploy/backup/.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backup
oggi=$(date +%F)
docker compose exec -T db pg_dump -U postgres --format=custom futurapro > "backup/database-$oggi.dump"
docker compose exec -T app tar czf - -C /dati/media . > "backup/contenuti-$oggi.tar.gz"
# Controllo Remoto: database e certificati di MeshCentral (senza i programmi degli agenti, che si riscaricano).
docker compose exec -T meshcentral tar czf - -C /opt/meshcentral/meshcentral-data --exclude=./agentbuilds --exclude=./signedagents . \
    > "backup/controllo-remoto-$oggi.tar.gz" || true
find backup -type f -mtime +14 -delete
