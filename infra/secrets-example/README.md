# Production secrets

`docker-compose.prod.yml` mounts env files from `./secrets/` — a git-ignored
directory next to it, inside the checkout on the server. **This folder is the
template**: copy each `.env` there, fill in real values, then `chmod 600` the lot.

The server holds the only copy. `/secrets/` is in `.gitignore` and the server's
deploy key is read-only, so these files cannot be pushed back — but that also
means nothing restores them for you. Keep an offline copy of whatever you cannot
regenerate (notably `JWT_PRIVATE_KEY`: rotating it invalidates every live session).

## On the host (one-time)

```bash
cd ~/opt/yupay          # the checkout
install -d -m 0700 secrets

# Copy the templates in, then fill in real values:
cp infra/secrets-example/*.env secrets/
$EDITOR secrets/postgres.env secrets/api.env secrets/grafana.env secrets/backup.env
chmod 600 secrets/*.env

# Sanity check — must return nothing:
grep -RIn 'CHANGE_ME' secrets/
```

## What lives where

| File                    | Consumed by                                                                                   |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| `postgres.env`          | `postgres` container — initial role/db creation                                               |
| `postgres-exporter.env` | `postgres-exporter` container (Prometheus scrape)                                             |
| `redis.env`             | `redis` (requirepass) + `redis-exporter`; password also goes into the Redis URLs in `api.env` |
| `api.env`               | `api`, `worker`, `scheduler`, `bot` (all share the same runtime env)                          |
| `web.env`               | `web` (Next.js storefront) — bundled into the JS, public                                      |
| `miniapp.env`           | `miniapp` (Vite mini app) — bundled into the JS, public                                       |
| `grafana.env`           | `grafana` admin creds + Caddy basic-auth hash                                                 |
| `backup.env`            | nightly `pg_dump → age → rclone` pipeline                                                     |

## Generating the bits inside

### Strong random strings (passwords, app secrets)

```bash
openssl rand -base64 32 | tr -d '+/='
```

### JWT keypair (Ed25519, base64-PEM)

```bash
# Private key (PKCS#8 PEM, base64-encoded one-liner)
openssl genpkey -algorithm Ed25519 \
  | base64 | tr -d '\n'
# Public key
openssl pkey -in /tmp/priv.pem -pubout \
  | base64 | tr -d '\n'
```

Put each into `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` in `api.env`. The
private key never leaves the server; the public key is also embedded
in the bot/miniapp/admin builds at runtime for token verification.

### AGE keypair for backup encryption

```bash
# On the operator's machine (NEVER on the production host):
brew install age   # or apt-get install age
age-keygen -o ~/yupay-backup.key
# The "public key" line goes into backup.env as BACKUP_AGE_RECIPIENT.
# The "AGE-SECRET-KEY-…" line stays OFFLINE on your machine; you'll
# need it to decrypt a backup during restore.
```

### Grafana basic-auth hash

Caddy needs a bcrypt hash, not the plaintext password:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps caddy \
  caddy hash-password --plaintext "the-real-password"
```

Paste the output into `GRAFANA_BASIC_AUTH_HASH` in `grafana.env`.

### rclone remote (Cloudflare R2)

On the host, one-time:

```bash
rclone config
# new remote → name "r2" → type "s3" → provider "Cloudflare" →
# paste R2 access key / secret / endpoint URL.
# Then create the bucket: rclone mkdir r2:yupay-backups
```

## Validation

Before the first `docker compose up`, sanity-check that nothing still
says `CHANGE_ME`:

```bash
cd ~/opt/yupay
grep -RIn 'CHANGE_ME' secrets/  # must return nothing
```

## Rotation

When a credential is compromised:

1. Generate the replacement (see sections above).
2. Update the relevant `.env`.
3. Restart only the affected services: `docker compose restart api worker scheduler bot`.
4. For Postgres password changes, also `ALTER ROLE yupay_app WITH PASSWORD '…'` first.
