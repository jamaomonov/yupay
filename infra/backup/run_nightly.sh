#!/bin/sh
# Self-scheduling wrapper: runs pg_backup.sh every night at BACKUP_HOUR_UTC
# (default 02:00 UTC), forever. POSIX sh + integer arithmetic only, so it works
# in busybox/alpine without GNU date.
#
# The container runs with `restart: unless-stopped`, so the loop survives
# reboots and crashes; a failed backup is logged (Loki picks it up) and the
# loop carries on to the next night instead of dying.

set -eu

HOUR="${BACKUP_HOUR_UTC:-2}"

echo "[backup] nightly scheduler started; next runs at ${HOUR}:00 UTC"

while :; do
    now="$(date -u +%s)"
    midnight="$((now - now % 86400))"
    target="$((midnight + HOUR * 3600))"
    if [ "$target" -le "$now" ]; then
        target="$((target + 86400))"
    fi
    echo "[backup] sleeping $((target - now))s until $(date -u -d "@${target}" 2>/dev/null || echo "${HOUR}:00 UTC")"
    sleep "$((target - now))"
    if bash /scripts/pg_backup.sh; then
        echo "[backup] nightly run ok"
    else
        echo "[backup] NIGHTLY RUN FAILED rc=$? — investigate before the next cycle"
    fi
done
