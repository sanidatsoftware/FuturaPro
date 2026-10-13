#!/bin/bash
# Backup giornaliero (lo lancia cron, vedi /etc/cron.d/futurapro): database e
# contenuti caricati, conservati per 14 giorni in deploy/backup/.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backup
oggi=$(date +%F)
docker compose exec -T db pg_dump -U postgres --format=custom futurapro > "backup/database-$oggi.dump"
docker run --rm -v futurapro_media:/media:ro -v "$PWD/backup:/backup" alpine \
    tar czf "/backup/contenuti-$oggi.tar.gz" -C /media .
find backup -type f -mtime +14 -delete
