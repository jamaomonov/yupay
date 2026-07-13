# Runbook — Restore Postgres from backup

> Drilled quarterly. If it has been > 90 days since the last drill, the deploy workflow
> will flag the runbook as stale.

## Where backups come from

The `backup` service in `docker-compose.prod.yml` is long-running
(`restart: unless-stopped`): `infra/backup/run_nightly.sh` sleeps until
`BACKUP_HOUR_UTC` (default **02:00 UTC**) and runs `pg_backup.sh`
(pg_dump → age → rclone → R2) every night. A failed run is logged as
`[backup] NIGHTLY RUN FAILED` — Loki picks it up; check it after any
postgres maintenance. `make backup` still works for a one-off run
(it overrides the container command).

## Preconditions

- The **private** age key, `~/yupay-backup.key` on the operator's machine. It exists nowhere
  else — not on the server, not in the repo. Without it the backups are unreadable, and no
  amount of access to R2 or the VPS changes that.
- `age` locally (`brew install age`).
- SSH access to the prod VPS.

`rclone` locally is optional: the backup container already has a working R2 remote, so you can
pull the object through it and never configure rclone on your laptop.

## Procedure

```bash
# 1. List backups (through the container's remote — no local rclone needed)
ssh ubuntu@152.228.137.175 'cd ~/opt/yupay && docker compose -f docker-compose.prod.yml \
  exec -T backup rclone lsf r2:yupay-backups/ --recursive' | grep '.dump.age' | sort | tail -20

# 2. Choose the backup to restore
BACKUP="2026-05-14/yupay-2026-05-14T02-00-00Z.dump.age"

# 3. Stream it down and decrypt LOCALLY — the ciphertext leaves R2, the key never leaves you
mkdir -p /tmp/restore
ssh ubuntu@152.228.137.175 "cd ~/opt/yupay && docker compose -f docker-compose.prod.yml \
  exec -T backup rclone cat r2:yupay-backups/$BACKUP" > /tmp/restore/backup.age
age --decrypt -i ~/yupay-backup.key -o /tmp/restore/yupay.dump /tmp/restore/backup.age

# 3b. Confirm the dump is intact BEFORE touching prod
pg_restore --list /tmp/restore/yupay.dump | head    # or: docker run --rm -v /tmp/restore:/b:ro \
                                                    #   postgres:16-alpine pg_restore --list /b/yupay.dump

# 4. Stop the app (API, worker, scheduler, bot — keep DB up)
ssh ubuntu@152.228.137.175 'cd ~/opt/yupay && docker compose -f docker-compose.prod.yml stop api worker scheduler bot'

# 5. Rename current DB and restore into a fresh one
docker compose -f docker-compose.prod.yml exec -T postgres psql -U postgres <<'SQL'
ALTER DATABASE yupay RENAME TO yupay_quarantine_$(date +%Y%m%d);
CREATE DATABASE yupay OWNER yupay_app;
SQL

# 6. Restore
cat /tmp/restore/yupay.dump | docker compose -f docker-compose.prod.yml exec -T postgres pg_restore -U yupay_app -d yupay --no-owner --no-privileges

# 7. Run migrations to bring schema to head (idempotent)
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

# 8. Bring app back up
docker compose -f docker-compose.prod.yml up -d

# 9. Smoke checks
curl -fsS https://api.yupay.uz/readyz
```

## Drill checklist (quarterly)

- [ ] Restore the latest backup to a **scratch** Postgres (NOT prod) using the above steps.
- [ ] Run `make test-py` against the restored DB to confirm no schema drift.
- [ ] Record the drill date and outcome in `docs/runbooks/restore-drill-log.md`.
- [ ] If anything failed, file a SEV2 issue.
