#!/usr/bin/env bash
# Restore a Postgres dump (encrypted .age) into the target DB.
# Usage: restore.sh /path/to/backup.dump.age
# Expects env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, BACKUP_AGE_IDENTITY (path).

set -euo pipefail

src="${1:?usage: restore.sh <backup.dump.age>}"

tmp_dump="$(mktemp /tmp/yupay-restore-XXXXXX.dump)"
trap 'rm -f "$tmp_dump"' EXIT

echo "[restore] decrypting ${src} ..."
age --decrypt --identity "$BACKUP_AGE_IDENTITY" --output "$tmp_dump" "$src"

echo "[restore] dropping & recreating ${PGDATABASE} ..."
psql -d postgres -c "DROP DATABASE IF EXISTS ${PGDATABASE};"
psql -d postgres -c "CREATE DATABASE ${PGDATABASE};"

echo "[restore] pg_restore ..."
pg_restore --no-owner --no-privileges --dbname "$PGDATABASE" "$tmp_dump"

echo "[restore] done"
