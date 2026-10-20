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

# A failed night used to be one echo nobody reads; a rotated R2 key or a
# changed password then failed every night until a restore was needed. Tell
# the ops chat (the alert bot from secrets/alertmanager.env). Best effort:
# without the two variables, or with Telegram down, the log line remains.
alert() {
    if [ -n "${ALERT_BOT_TOKEN:-}" ] && [ -n "${ALERT_CHAT_ID:-}" ]; then
        curl -fsS -m 15 -o /dev/null \
            --data-urlencode "chat_id=${ALERT_CHAT_ID}" \
            --data-urlencode "text=$1" \
            "https://api.telegram.org/bot${ALERT_BOT_TOKEN}/sendMessage" ||
            echo "[backup] could not deliver the alert"
    fi
}

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
        rc=$?
        echo "[backup] NIGHTLY RUN FAILED rc=${rc} — investigate before the next cycle"
        alert "YuPay: ночной бэкап базы не прошёл (rc=${rc}). Логи: сервис backup."
    fi
done
