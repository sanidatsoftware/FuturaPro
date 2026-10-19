#!/bin/sh
set -eu
[ -f .env ] && { echo '.env esiste gia'; exit 0; }
SECRET=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)
cat > .env <<EOF2
APP_PORT=8096
APP_SECRET=$SECRET
ADMIN_USER=admin
ADMIN_PASSWORD=CAMBIA_QUESTA_PASSWORD
TZ=Europe/Rome
AUTO_IMPORT_MINUTES=60
EOF2
echo 'Creato .env. Modificare ADMIN_PASSWORD prima di avviare.'
