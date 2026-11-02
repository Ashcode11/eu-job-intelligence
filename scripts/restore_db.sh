#!/usr/bin/env bash
# Restore a dump produced by backup_db.sh. Overwrites existing data. Usage: scripts/restore_db.sh backups/<file>.dump
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:?usage: $0 <dump file>}"
read -r -p "This replaces all data in the eujobs database. Type 'restore' to continue: " ok
[ "$ok" = "restore" ] || { echo "aborted"; exit 1; }
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$file"
echo "restored $file"
