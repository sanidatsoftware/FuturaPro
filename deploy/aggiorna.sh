#!/bin/bash
# Aggiorna FuturaPro all'ultima versione: scarica il codice, ricostruisce e riavvia.
# Il database si aggiorna da solo all'avvio (migrazioni). Prima fa un backup.
set -euo pipefail
cd "$(dirname "$0")"
# Con sudo git rifiuta una cartella di un altro utente («dubious ownership»):
# la cartella dell'installazione è sicura per definizione.
git() { command git -c safe.directory="$(cd .. && pwd)" "$@"; }
if [ "${1:-}" != "--dopo-pull" ]; then
    ./backup.sh
    if git -C .. rev-parse --git-dir > /dev/null 2>&1; then
        prima=$(git -C .. rev-parse --short HEAD)
        git -C .. pull --ff-only
        echo "Codice: $prima -> $(git -C .. rev-parse --short HEAD) (ramo $(git -C .. rev-parse --abbrev-ref HEAD))"
        # Il pull può aver cambiato anche questo script: il resto lo fa la versione nuova.
        exec bash "$0" --dopo-pull
    else
        echo "Codice non scaricato con git: copia la nuova versione in $(cd .. && pwd) e rilancia."
    fi
fi
# Il numero di build della versione (es. 1.6.072 · 20261015) per il pannello: nel container git non c'è.
numero=$(git -C .. rev-list --count HEAD 2>/dev/null || true)
data=$(git -C .. log -1 --format=%cd --date=format:%Y%m%d 2>/dev/null || true)
if [ -n "$numero" ] && [ -f .env ]; then
    # .env contiene password: anche la copia temporanea è leggibile solo dal proprietario.
    (umask 077; { grep -v '^FP_BUILD=\|^FP_BUILD_DATA=' .env; echo "FP_BUILD=$numero"; echo "FP_BUILD_DATA=$data"; } > .env.nuovo) \
        && cat .env.nuovo > .env && rm -f .env.nuovo
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
