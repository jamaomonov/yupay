# Runbook — Deploy

> Automated by `.github/workflows/deploy.yml`. This document describes the **manual**
> procedure for the rare case CI is unavailable.

## Preconditions

- You have `ssh` access to the production VPS with sudo.
- You have `gpg`/`age` keys to decrypt `infra/secrets/*.enc.env`.
- The image tag you want to deploy already exists in GHCR (`ghcr.io/yupay/<service>:vX.Y.Z`).

## Procedure

```bash
ssh deploy@prod.yupay.io

cd ~/opt/yupay
git fetch --all --tags
git checkout vX.Y.Z

# Refresh decrypted env files (if rotated)
sops -d infra/secrets/api.enc.env > secrets/api.env

# Pull new images
docker compose -f docker-compose.prod.yml pull

# Apply migrations (one-shot container)
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

# Restart services with rolling-friendly order
docker compose -f docker-compose.prod.yml up -d --remove-orphans

# Verify
curl -fsS https://api.yupay.io/healthz
curl -fsS https://api.yupay.io/readyz
docker compose -f docker-compose.prod.yml ps
```

## If `alembic upgrade head` fails with `lock_not_available`

A migration that takes a lock on a busy table sets `lock_timeout` so it gives
up rather than queueing behind an in-flight transaction — Postgres grants lock
requests FIFO, so a migration _waiting_ on `orders` also blocks every
`INSERT`/`UPDATE` that arrives after it, and the old api containers are still
serving traffic while this step runs. Failing fast trades a checkout write
stall for a failed deploy step.

Nothing is half-applied: the whole run is one transaction (`migrations/env.py`).

What to do:

1. Re-run the same command. Most waits are one slow transaction, already gone.
2. If it keeps failing, find what is holding the table and decide whether to
   wait for a quieter minute or end it:

   ```bash
   docker compose -f docker-compose.prod.yml exec postgres \
     psql -U yupay_app -d yupay -c \
     "SELECT pid, state, now() - xact_start AS age, left(query, 120) \
        FROM pg_stat_activity \
       WHERE state <> 'idle' AND xact_start IS NOT NULL \
       ORDER BY xact_start;"
   ```

3. Only then, and only for one that is genuinely stuck (minutes old, state
   `idle in transaction`), end it with `SELECT pg_terminate_backend(<pid>)`. A
   live checkout is a customer; let it finish.

Migrations carrying this guard today: `0069_orders_merchant_idempotency`.
Older index migrations on `orders` (0039, 0055) have the same exposure and no
timeout — they are already applied everywhere, so it is history rather than
risk.

## Rollback

```bash
git checkout vX.Y.<previous>
docker compose -f docker-compose.prod.yml pull
# Schema rollbacks are forbidden in normal flow; if a DB rollback is required,
# follow docs/runbooks/restore-from-backup.md instead.
docker compose -f docker-compose.prod.yml up -d
```

## Notifications

After a successful deploy, post the new tag to the ops Telegram channel via the bot:

```bash
make notify-ops msg="Deployed vX.Y.Z"
```
