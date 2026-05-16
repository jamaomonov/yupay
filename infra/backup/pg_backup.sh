#!/usr/bin/env bash
# Nightly Postgres backup: pg_dump -> age -> rclone -> Cloudflare R2.
# Expected env vars (mounted via /opt/yupay/secrets/backup.env):
#   PGHOST=postgres
#   PGUSER=...
#   PGPASSWORD=...
#   PGDATABASE=yupay
#   BACKUP_AGE_RECIPIENT=age1...
#   RCLONE_REMOTE=r2:yupay-backups

set -euo pipefail

date_dir="$(date -u +%Y-%m-%d)"
file_ts="$(date -u +%FT%H-%M-%SZ)"
tmp_dir="${TMPDIR:-/tmp/backup}"
mkdir -p "$tmp_dir"

dump="${tmp_dir}/yupay-${file_ts}.dump"
enc="${dump}.age"

echo "[backup] dumping ${PGDATABASE} ..."
pg_dump --format=custom --no-owner --no-privileges --file "$dump"

echo "[backup] encrypting ..."
age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$enc" "$dump"
rm -f "$dump"

echo "[backup] uploading to ${RCLONE_REMOTE}/${date_dir}/ ..."
rclone copyto "$enc" "${RCLONE_REMOTE}/${date_dir}/$(basename "$enc")"

rm -f "$enc"
echo "[backup] done"
