#!/usr/bin/env bash
# Restore a Postgres dump (encrypted .age) into the target DB.
# Usage: restore.sh /path/to/backup.dump.age
# Expects env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, BACKUP_AGE_IDENTITY (path).

set -euo pipefail

src="${1:?usage: restore.sh <backup.dump.age>}"

# It drops the database first. Name it back, so a wrong terminal or a wrong
# `file=` cannot wipe production by accident.
if [ "${CONFIRM_DB:-}" != "$PGDATABASE" ]; then
    echo "[restore] refusing: this DROPS database '${PGDATABASE}' on ${PGHOST:-local}." >&2
    echo "[restore] set CONFIRM_DB=${PGDATABASE} to go ahead (make restore ... confirm=${PGDATABASE})." >&2
    exit 1
fi

tmp_dump="$(mktemp /tmp/yupay-restore-XXXXXX.dump)"
trap 'rm -f "$tmp_dump"' EXIT

echo "[restore] decrypting ${src} ..."
age --decrypt --identity "$BACKUP_AGE_IDENTITY" --output "$tmp_dump" "$src"

echo "[restore] dropping & recreating ${PGDATABASE} ..."
# psql :"var" interpolation quotes the identifier server-side — a PGDATABASE
# with spaces/metacharacters can't break out of the statement.
psql -d postgres -v db="$PGDATABASE" -c 'DROP DATABASE IF EXISTS :"db";'
psql -d postgres -v db="$PGDATABASE" -c 'CREATE DATABASE :"db";'

echo "[restore] pg_restore ..."
pg_restore --no-owner --no-privileges --dbname "$PGDATABASE" "$tmp_dump"

echo "[restore] done"
