#!/bin/bash
# Installazione del server FuturaPro su Ubuntu Server 22.04 o 24.04.
#
#   sudo ./installa.sh
#
# Senza domande (per esempio da uno script), con le variabili d'ambiente:
#   sudo FP_INDIRIZZO=10.0.100.41 FP_BANCO_HTTP=si FP_ADMIN=admin FP_ADMIN_PASSWORD='…' FP_DEMO=no ./installa.sh
#
# Rilanciarlo è sicuro: le password già generate (in .env) restano, Caddyfile
# viene riscritto con le risposte date, i dati non si toccano.
set -euo pipefail
cd "$(dirname "$0")"
DEPLOY=$(pwd)

blu() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
errore() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || errore "Lancia lo script con sudo: sudo ./installa.sh"
grep -qi ubuntu /etc/os-release || errore "Questo script è per Ubuntu Server."

# --- 1. Docker ------------------------------------------------------------------
if ! command -v docker > /dev/null || ! docker compose version > /dev/null 2>&1; then
    blu "Installo Docker…"
    apt-get update -q
    apt-get install -y -q docker.io docker-compose-v2 curl openssl
    systemctl enable --now docker
fi

# --- 2. Domande -------------------------------------------------------------------
precedente() { grep -s "^$1=" .env | cut -d= -f2- || true; }

blu "Configurazione"
echo "Indirizzo con cui monitor, totem e pannello raggiungeranno il server."
echo "  - un nome di dominio pubblico (es. signage.miodominio.it): certificato HTTPS gratuito Let's Encrypt;"
echo "  - oppure l'indirizzo IP della rete locale (es. 10.0.100.41): certificato interno, da installare sui player."
indirizzo_predefinito=$(precedente FP_INDIRIZZO)
[ -n "$indirizzo_predefinito" ] || indirizzo_predefinito=$(hostname -I | awk '{print $1}')
[ -n "${FP_INDIRIZZO:-}" ] || read -rp "Indirizzo [$indirizzo_predefinito]: " FP_INDIRIZZO
FP_INDIRIZZO=${FP_INDIRIZZO:-$indirizzo_predefinito}
FP_INDIRIZZO=${FP_INDIRIZZO#http://}; FP_INDIRIZZO=${FP_INDIRIZZO#https://}; FP_INDIRIZZO=${FP_INDIRIZZO%%/*}

if [[ "$FP_INDIRIZZO" =~ ^[0-9.]+$ ]] || [[ "$FP_INDIRIZZO" != *.* ]] || [[ "$FP_INDIRIZZO" == *.local ]] || [[ "$FP_INDIRIZZO" == *.lan ]]; then
    CERTIFICATO=interno
    echo "→ Certificato interno (rete locale)."
else
    CERTIFICATO=letsencrypt
    [ -n "${FP_EMAIL:-}" ] || read -rp "Email per Let's Encrypt (avvisi sul certificato): " FP_EMAIL
    echo "→ Let's Encrypt: il dominio deve puntare a questo server e le porte 80 e 443 devono essere raggiungibili da internet."
fi

echo
echo "Le bilance DIGI (e i dispositivi che non accettano il certificato interno) possono"
echo "chiamare i turni anche in HTTP semplice, solo dalla rete locale e solo per il banco."
risposta=${FP_BANCO_HTTP:-}
[ -n "$risposta" ] || read -rp "Abilitare il banco in HTTP per la rete locale? [S/n]: " risposta
[[ "${risposta:-S}" =~ ^[sSyY] ]] && BANCO_HTTP=si || BANCO_HTTP=no

# --- 3. Segreti (generati una volta sola) --------------------------------------------
segreto() { openssl rand -hex 32; }
FP_SECRET_KEY=$(precedente FP_SECRET_KEY); FP_SECRET_KEY=${FP_SECRET_KEY:-$(segreto)}
FP_DB_PASSWORD=$(precedente FP_DB_PASSWORD); FP_DB_PASSWORD=${FP_DB_PASSWORD:-$(segreto)}
FP_DB_SUPERPASSWORD=$(precedente FP_DB_SUPERPASSWORD); FP_DB_SUPERPASSWORD=${FP_DB_SUPERPASSWORD:-$(segreto)}

umask 077
cat > .env <<EOF
# Creato da installa.sh: contiene password. Non condividerlo.
FP_INDIRIZZO=$FP_INDIRIZZO
FP_SECRET_KEY=$FP_SECRET_KEY
FP_DB_PASSWORD=$FP_DB_PASSWORD
FP_DB_SUPERPASSWORD=$FP_DB_SUPERPASSWORD
EOF
umask 022

# --- 4. Caddy (HTTPS) --------------------------------------------------------------
if [ "$CERTIFICATO" = interno ]; then
    # Con un indirizzo IP il browser non manda il nome del server (SNI): senza
    # default_sni Caddy non saprebbe quale certificato usare e chiuderebbe la connessione.
    opzioni_globali="local_certs
	default_sni $FP_INDIRIZZO"
    tls="tls internal"
else
    opzioni_globali="email ${FP_EMAIL}"
    tls=""
fi

banco_http=""
if [ "$BANCO_HTTP" = si ]; then
    banco_http="
	@banco_statico {
		remote_ip private_ranges
		path /static/eliminacode/*
	}
	handle @banco_statico {
		root * /srv
		file_server
	}
	@banco {
		remote_ip private_ranges
		path /banco/ /api/eliminacode/pulsante/ /api/eliminacode/pulsante/*
	}
	handle @banco {
		reverse_proxy app:8000
	}"
fi

cat > Caddyfile <<EOF
# Creato da installa.sh.
{
	$opzioni_globali
}

# HTTP: installazione dei player, certificato interno, banco per le bilance; il resto va in HTTPS.
http://$FP_INDIRIZZO {
	handle /installa/* {
		root * /srv
		file_server
	}
	handle /futurapro-ca.crt {
		root * /data/caddy/pki/authorities/local
		rewrite * /root.crt
		header Content-Type application/x-x509-ca-cert
		file_server
	}$banco_http
	handle {
		redir https://{host}{uri} permanent
	}
}

https://$FP_INDIRIZZO {
	$tls
	encode zstd gzip
	handle /static/* {
		root * /srv
		file_server
	}
	handle {
		reverse_proxy app:8000
	}
}
EOF

# --- 5. Avvio ---------------------------------------------------------------------------
blu "Avvio FuturaPro (la prima volta ci vogliono alcuni minuti)…"
docker compose up -d --build < /dev/null
# Caddy rilegge il Caddyfile solo al riavvio: serve quando si rilancia l'installazione.
docker compose restart caddy < /dev/null > /dev/null

echo -n "Attendo che il server sia pronto"
for _ in $(seq 1 90); do
    if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/player/', timeout=3)" < /dev/null > /dev/null 2>&1; then
        pronto=si; break
    fi
    echo -n "."; sleep 2
done
echo
[ "${pronto:-}" = si ] || errore "Il server non risponde. Guarda i log con: docker compose -f $DEPLOY/docker-compose.yml logs app"

# --- 6. Primo amministratore -----------------------------------------------------------
if [ "$(docker compose exec -T app python manage.py shell -c 'from utenti.models import Utente; print(Utente.objects.filter(ruolo="admin_assoluto").count())' < /dev/null | tail -1)" = "0" ]; then
    blu "Crea l'Administrator Assoluto (l'utente con cui entri nel pannello)"
    amministratore=${FP_ADMIN:-}
    [ -n "$amministratore" ] || read -rp "Nome utente [admin]: " amministratore
    if [ -n "${FP_ADMIN_PASSWORD:-}" ]; then
        docker compose exec -T -e FUTURAPRO_ADMIN_PASSWORD="$FP_ADMIN_PASSWORD" app \
            python manage.py crea_admin_assoluto "${amministratore:-admin}" < /dev/null
    else
        docker compose exec app python manage.py crea_admin_assoluto "${amministratore:-admin}"
    fi
fi

risposta=${FP_DEMO:-}
[ -n "$risposta" ] || read -rp "Vuoi creare il cliente dimostrativo «Demo» (reparti, layout, slide di prova)? [s/N]: " risposta
if [[ "${risposta:-N}" =~ ^[sSyY] ]]; then
    docker compose exec -T app python manage.py dati_dimostrativi < /dev/null || true
fi

# --- 7. Backup giornaliero ----------------------------------------------------------------
cat > /etc/cron.d/futurapro <<EOF
# Backup di FuturaPro (database e contenuti), tenuti 14 giorni in $DEPLOY/backup
30 2 * * * root $DEPLOY/backup.sh > /var/log/futurapro-backup.log 2>&1
EOF

# --- 8. Riepilogo ----------------------------------------------------------------------------
blu "FuturaPro è installato"
echo "Pannello:        https://$FP_INDIRIZZO/pannello/"
echo "Player:          https://$FP_INDIRIZZO/player/"
echo "Banco:           https://$FP_INDIRIZZO/banco/"
[ "$BANCO_HTTP" = si ] && echo "Banco (bilance): http://$FP_INDIRIZZO/banco/   (solo dalla rete locale)"
echo
echo "Installazione su Windows (monitor e totem), in PowerShell come amministratore:"
echo "  irm http://$FP_INDIRIZZO/installa/player-windows.ps1 -OutFile \$env:TEMP\\futurapro.ps1; powershell -ExecutionPolicy Bypass -File \$env:TEMP\\futurapro.ps1 -Server $FP_INDIRIZZO"
if [ "$CERTIFICATO" = interno ]; then
    for _ in $(seq 1 15); do
        docker compose exec -T caddy test -f /data/caddy/pki/authorities/local/root.crt < /dev/null && break
        sleep 1
    done
    impronta=$(docker compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt < /dev/null | openssl x509 -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':')
    echo
    echo "Impronta del certificato interno (l'installazione sui player la mostra: devono coincidere):"
    echo "  $impronta"
fi
echo
echo "Backup ogni notte in $DEPLOY/backup · Aggiornamento: sudo $DEPLOY/aggiorna.sh"
