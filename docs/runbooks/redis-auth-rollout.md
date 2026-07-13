# Runbook — Rolling out Redis authentication (requirepass)

> One-time migration. After this, Redis refuses unauthenticated clients.
> **Do the server prep (steps 1–2) BEFORE deploying the compose change** —
> `docker compose up` fails on the missing env file otherwise, and clients
> with old URLs lose Redis the moment the new container starts.

## Why

Redis previously ran with no password on the internal bridge network. The
`bot` container shares the host network namespace (IPv6 workaround), so a
compromised bot process could reach Redis through the bridge gateway —
giving it the Dramatiq queue, rate-limit state, and anything else cached
there. `requirepass` closes that door.

## Procedure

```bash
# 0. Generate a password (keep it; it goes in two files)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 1. Create the redis secrets file on the VPS
cat > secrets/redis.env <<'ENV'
REDIS_PASSWORD=<generated>
ENV
chmod 600 secrets/redis.env

# 2. Update the client URLs in secrets/api.env
#    (note the colon before the password — empty username)
REDIS_URL=redis://:<generated>@redis:6379/0
DRAMATIQ_BROKER_URL=redis://:<generated>@redis:6379/1

# 3. Deploy the compose change (or, manually):
docker compose -f docker-compose.prod.yml up -d redis redis-exporter
docker compose -f docker-compose.prod.yml up -d api worker scheduler bot

# 4. Verify
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli -a "<generated>" ping            # → PONG
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli ping                             # → NOAUTH (good)
curl -fsS https://api.yupay.uz/readyz
docker compose -f docker-compose.prod.yml logs --tail 20 worker  # broker connected
```

## Expected impact

Recreating `redis` drops in-flight connections for a few seconds; Dramatiq
and the API reconnect automatically. Queued Dramatiq jobs survive (AOF
persistence on the `redis-data` volume). Rate-limit counters are in-process
(ADR-0028) and unaffected.

## Rollback

Remove `--requirepass` from the compose command, restore the password-less
URLs in `api.env`, `up -d` the same services in the same order.
