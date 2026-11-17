#!/usr/bin/env bash
# Logical backup of the Kokila database. Usage: scripts/backup.sh [output_dir]
set -euo pipefail
OUT="${1:-./backups}"
mkdir -p "$OUT"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT/kokila-$TS.dump"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-kokila}" -d "${POSTGRES_DB:-kokila}" -Fc > "$FILE"
sha256sum "$FILE" > "$FILE.sha256"
echo "Backup written: $FILE"
# Copy off-host (e.g. encrypted object storage) — retention is the operator's responsibility.
