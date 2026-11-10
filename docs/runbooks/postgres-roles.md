# Postgres roles

Since the 2026-11-10 audit the application no longer connects as the Postgres
superuser.

| Role            | Privileges                                                 | Who connects                                                  |
| --------------- | ---------------------------------------------------------- | ------------------------------------------------------------- |
| `yupay_app`     | SUPERUSER (bootstrap, OID 10 — cannot be demoted)          | operators, `docker compose exec postgres psql` (local socket) |
| `yupay_api`     | owns the `yupay` database, `public` and every object in it | api, worker, scheduler, bot, migrations, backups              |
| `yupay_monitor` | `pg_monitor` only, no table access                         | postgres-exporter                                             |

Why: as superuser, any SQL injection — or a compromise of the third-party
exporter image — was `COPY … TO PROGRAM`, a shell in the database container.
As owner, `yupay_api` can still run every migration (`ALTER TABLE`, indexes,
the trusted extensions `pgcrypto`, `citext`, `pg_trgm`, `btree_gin`) and
`pg_dump` everything. Rehearsed on a copy of the dev database: migrations up
and down, `pg_dump`, `COPY TO PROGRAM` refused, the monitor role refused
table reads.

## Switching (one time)

After a deploy that ships `infra/postgres/least-privilege.*`, at a quiet hour,
check `skin_trades` and `fulfillment_tasks` first (the four services restart),
then on the host:

```bash
cd ~/opt/yupay
bash infra/postgres/least-privilege.sh
```

It creates the two roles with random passwords (stdin, never argv), moves
ownership, rewrites `DATABASE_URL` in `api.env`, `PGUSER`/`PGPASSWORD` in
`backup.env` and `DATA_SOURCE_NAME` in `postgres-exporter.env` (originals kept
as `secrets/*.env.bak-<stamp>`), recreates api, worker, scheduler, bot, backup
and postgres-exporter on the running `IMAGE_TAG`, waits for `/readyz` and
prints connections per role. It is idempotent and reuses passwords on file.

**Rollback:** copy the `.bak-<stamp>` files back over the three env files and
recreate the same six services with `IMAGE_TAG` set. Nothing else to undo —
`yupay_app` can still read and write everything `yupay_api` owns.

## New objects

Migrations run as `yupay_api`, so everything they create is already its own.
An object created by hand as `yupay_app` is not — re-run the script, which
moves it.
