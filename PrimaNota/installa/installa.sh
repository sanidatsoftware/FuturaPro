#!/bin/sh
# Installa la Prima Nota nel portale TOCAL (/opt/tocal). Vedi LEGGIMI.txt.
cd "$(dirname "$0")" || exit 1
exec python3 installa.py "$@"
