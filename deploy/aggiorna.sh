#!/bin/bash
# Aggiorna FuturaPro all'ultima versione: scarica il codice, ricostruisce e riavvia.
# Il database si aggiorna da solo all'avvio (migrazioni). Prima fa un backup.
set -euo pipefail
cd "$(dirname "$0")"
./backup.sh
# Con sudo git rifiuta una cartella di un altro utente («dubious ownership»):
# la cartella dell'installazione è sicura per definizione.
git() { command git -c safe.directory="$(cd .. && pwd)" "$@"; }
if git -C .. rev-parse --git-dir > /dev/null 2>&1; then
    prima=$(git -C .. rev-parse --short HEAD)
    git -C .. pull --ff-only
    echo "Codice: $prima -> $(git -C .. rev-parse --short HEAD) (ramo $(git -C .. rev-parse --abbrev-ref HEAD))"
else
    echo "Codice non scaricato con git: copia la nuova versione in $(cd .. && pwd) e rilancia."
fi
# Installazioni precedenti: i file statici senza Cache-Control restavano nella cache
# del browser e le modifiche a pannello ed editor non si vedevano.
if [ -f Caddyfile ] && ! grep -q 'Cache-Control "no-cache"' Caddyfile; then
    sed -i 's|^\thandle /static/\* {$|&\n\t\theader Cache-Control "no-cache"|' Caddyfile
fi
docker compose up -d --build
# Caddy rilegge il Caddyfile solo se glielo si chiede.
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile < /dev/null || docker compose restart caddy
docker image prune -f > /dev/null
echo "Aggiornamento completato."
