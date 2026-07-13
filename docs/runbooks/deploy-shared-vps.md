# Runbook — deploying onto the shared VPS (edge proxy cutover)

**Applies to:** `152.228.137.175`, which hosts both YuPay and an unrelated stack,
`streamers-parser`. See [ADR-0030](../decisions/0030-shared-edge-proxy-on-a-co-hosted-vps.md)
for why the topology looks like this.

## Topology

```
                    :80 / :443
                        │
                   edge-caddy            ← project "edge", infra/edge/
                   (terminates TLS)
                        │  network: yupay-edge
        ┌───────────────┴────────────────┐
   yupay-caddy                    streamers-caddy      ← network aliases
   (project yupay-prod)           (project streamers-parser)
        │                                │
   web / miniapp / admin /          client-web / api /
   api / grafana                    admin-web
```

Only `edge-caddy` publishes host ports. Both application stacks bind nothing to the host, so
they cannot collide — not with each other, and not with anything else on the box.

## Invariants — break these and the site goes down

- **Exactly one process binds `:80`/`:443`.** If you re-add a `ports:` section to either
  stack's Caddy, the second one to start dies with `address already in use`.
- **The upstreams are network aliases, not service names.** Both stacks name their proxy
  service `caddy`; on the shared network that name is ambiguous. YuPay registers the alias
  `yupay-caddy`, `streamers-parser` registers `streamers-caddy`.
- **YuPay's Caddy runs with `auto_https off`.** It cannot solve ACME challenges — it does not
  own `:80`. Certificates are the edge's job.
- **Certificates live in the `edge_caddy-data` volume.** Deleting it means re-issuing every
  certificate; Let's Encrypt allows 50 per registered domain per week. Do not
  `docker volume prune` on this host without checking.

## First-time setup

### 1. The shared network

```bash
docker network create yupay-edge
```

Idempotent in the deploy workflow, but it must exist before either stack starts.

### 2. Secrets

They live in `/opt/yupay/secrets/` — **outside the checkout**, so they can never be swept into
a commit. Root-owned, group-readable by the deploy user, `0640`:

```bash
sudo install -d -o root -g ubuntu -m 0750 /opt/yupay/secrets
```

Nine files are required; `infra/secrets-example/` holds the templates and
`infra/secrets-example/README.md` documents every key:

| File                    | Consumed by                        |
| ----------------------- | ---------------------------------- |
| `postgres.env`          | postgres                           |
| `postgres-exporter.env` | postgres-exporter                  |
| `redis.env`             | redis, redis-exporter              |
| `minio.env`             | minio                              |
| `api.env`               | api, worker, scheduler, bot        |
| `web.env`               | web                                |
| `miniapp.env`           | miniapp                            |
| `grafana.env`           | grafana **and caddy** (basic-auth) |
| `backup.env`            | backup                             |

Cross-file consistency matters: the password in `postgres.env` must match the one embedded in
`DATABASE_URL` in `api.env`, and likewise `redis.env` ↔ `REDIS_URL` / `DRAMATIQ_BROKER_URL`.

### 3. GHCR access

The images are private. Authenticate once with a PAT carrying `read:packages`:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u <github-user> --password-stdin
```

### 4. Free the ports on `streamers-parser`

That stack is **not** in this repository, so this edit is manual and must be re-applied if its
compose file is ever restored from git. In its `docker-compose.prod.yml`, on the `caddy`
service:

- delete the `ports:` block (`80:80`, `443:443`);
- attach it to the shared network under the alias the edge proxies to:

```yaml
caddy:
  # ports: removed — the shared edge proxy owns :80/:443 (YuPay ADR-0030)
  networks:
    default: {}
    edge:
      aliases: [streamers-caddy]

networks:
  edge:
    external: true
    name: yupay-edge
```

Its own Caddyfile needs no change: it already declares both `http://` and `https://` for its
hostname, so it serves the edge's cleartext forward on `:80` as-is.

### 5. Bring it up, in order

```bash
docker compose -f infra/edge/docker-compose.yml up -d          # owns :80/:443
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
docker compose -f /home/ubuntu/opt/streamers-parser/docker-compose.prod.yml up -d
```

The edge starts fine even when a stack is down — Caddy resolves upstreams lazily, so an absent
stack is a 502 on its own hostnames and nothing more.

## Verification

```bash
curl -fsS https://api.yupay.uz/healthz            # 200, valid LE cert
curl -fsS https://api.yupay.uz/readyz             # 200 — db + redis reachable
curl -sI https://yupay.uz | head -1               # 200
curl -sI https://marketing.kolikosoft.com | head -1   # neighbour still alive
```

Confirm the API sees real client IPs rather than the edge's container address — if
`trusted_proxies` is wrong, this is the only place it shows, and it fails silently:

```bash
docker compose -f docker-compose.prod.yml logs api | grep -o '"client_ip":"[^"]*"' | tail -5
```

## Rollback

The cutover is reversible without touching data. To hand `:80`/`:443` back to
`streamers-parser`:

```bash
docker compose -f infra/edge/docker-compose.yml down
# restore the ports: block on the streamers-parser caddy service, then:
docker compose -f /home/ubuntu/opt/streamers-parser/docker-compose.prod.yml up -d
```

YuPay is then unreachable (its Caddy publishes nothing), but no state is lost: Postgres, Redis
and MinIO volumes are untouched. To restore YuPay instead, re-add `ports: 80/443` to its Caddy
service, revert `auto_https off` in `infra/caddy/Caddyfile.prod`, and stop the neighbouring
stack's Caddy.

## Failure modes

| Symptom                                    | Cause                                                                                                                                                       |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `address already in use` on the edge       | A stack still publishes `:80`/`:443`. Check `docker ps --format '{{.Names}} {{.Ports}}'`                                                                    |
| 502 on every yupay hostname                | The YuPay stack is down, or its `yupay-caddy` alias is not on `yupay-edge`                                                                                  |
| 502 on `marketing.kolikosoft.com` only     | The `streamers-caddy` alias is missing — step 4 was not applied                                                                                             |
| Certificate errors after a redeploy        | `edge_caddy-data` was pruned; re-issue and mind the LE rate limit                                                                                           |
| Rate limits triggering for unrelated users | `trusted_proxies` missing — every request looks like it comes from the edge                                                                                 |
| Telegram calls time out                    | An IPv6 workaround crept back in. This host has **no** global IPv6 and reaches Telegram over IPv4 — see [telegram-connectivity](./telegram-connectivity.md) |
