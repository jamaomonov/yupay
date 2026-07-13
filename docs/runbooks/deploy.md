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
