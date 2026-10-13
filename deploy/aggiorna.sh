#!/bin/bash
# Aggiorna FuturaPro all'ultima versione: scarica il codice, ricostruisce e riavvia.
# Il database si aggiorna da solo all'avvio (migrazioni). Prima fa un backup.
set -euo pipefail
cd "$(dirname "$0")"
./backup.sh
if git -C .. rev-parse --git-dir > /dev/null 2>&1; then
    git -C .. pull --ff-only
else
    echo "Codice non scaricato con git: copia la nuova versione in $(cd .. && pwd) e rilancia."
fi
docker compose up -d --build
docker image prune -f > /dev/null
echo "Aggiornamento completato."
