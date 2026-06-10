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

- You have `age` key in `~/.config/sops/age/keys.txt`.
- You have `rclone` configured for Cloudflare R2 (`rclone listremotes` shows `r2:`).
- You have write access to the prod VPS.

## Procedure

```bash
# 1. List backups
rclone lsf r2:yupay-backups/ --recursive | grep '.dump.age' | sort | tail -20

# 2. Choose the backup to restore
BACKUP="2026-05-14/yupay-2026-05-14T02-00-00Z.dump.age"

# 3. Download & decrypt to a working file
rclone copy "r2:yupay-backups/$BACKUP" /tmp/restore/
age --decrypt -i ~/.config/sops/age/keys.txt -o /tmp/restore/yupay.dump /tmp/restore/$(basename "$BACKUP")

# 4. Stop the app (API, worker, scheduler, bot — keep DB up)
ssh deploy@prod.yupay.io 'cd /opt/yupay && docker compose -f docker-compose.prod.yml stop api worker scheduler bot'

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
curl -fsS https://api.yupay.io/readyz
```

## Drill checklist (quarterly)

- [ ] Restore the latest backup to a **scratch** Postgres (NOT prod) using the above steps.
- [ ] Run `make test-py` against the restored DB to confirm no schema drift.
- [ ] Record the drill date and outcome in `docs/runbooks/restore-drill-log.md`.
- [ ] If anything failed, file a SEV2 issue.
