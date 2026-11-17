#!/usr/bin/env bash
# Restore a backup into the running postgres service. DESTRUCTIVE: replaces current data.
# Usage: scripts/restore.sh backups/kokila-YYYYmmddTHHMMSSZ.dump
set -euo pipefail
FILE="${1:?backup file required}"
sha256sum -c "$FILE.sha256"
read -r -p "This will overwrite database ${POSTGRES_DB:-kokila}. Type RESTORE to continue: " ok
[ "$ok" = "RESTORE" ] || { echo "aborted"; exit 1; }
docker compose stop api worker beat
docker compose exec -T postgres pg_restore -U "${POSTGRES_USER:-kokila}" -d "${POSTGRES_DB:-kokila}" --clean --if-exists < "$FILE"
docker compose run --rm migrate
docker compose start api worker beat
echo "Restore complete."
