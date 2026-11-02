#!/usr/bin/env bash
# Dump the database from the running compose stack to ./backups/eujobs-<timestamp>.dump
# Keeps the newest $KEEP dumps (default 14).
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP="${KEEP:-14}"
mkdir -p backups
ts="$(date -u +%Y%m%dT%H%M%SZ)"
out="backups/eujobs-${ts}.dump"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$out"
echo "wrote $out ($(du -h "$out" | cut -f1))"
ls -1t backups/eujobs-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm -f
