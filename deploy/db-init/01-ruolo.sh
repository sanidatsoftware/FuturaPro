#!/bin/bash
# Primo avvio del database: il ruolo dell'applicazione NON è superuser e non ha
# BYPASSRLS, altrimenti la Row-Level Security non lo vincolerebbe.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username postgres <<EOSQL
CREATE ROLE futurapro LOGIN PASSWORD '${FP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
CREATE DATABASE futurapro OWNER futurapro;
EOSQL
