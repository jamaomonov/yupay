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

They live in `secrets/` **inside the checkout**, next to `docker-compose.prod.yml`, which
mounts them by relative path (`env_file: ./secrets/api.env`). Owned by the deploy user so no
`sudo` is needed to edit them, and readable by nobody else:

```bash
install -d -m 0700 /home/ubuntu/opt/yupay/secrets   # files inside: 0600
```

They are kept out of git by `/secrets/` in `.gitignore`, backed up by `gitleaks` in
pre-commit; and the server's deploy key is **read-only**, so nothing can be pushed from there
even if a file did get staged. The server holds the only copy — losing the box loses the
secrets, so keep an offline copy of anything you cannot regenerate.

Eight files are required; `infra/secrets-example/` holds the templates and
`infra/secrets-example/README.md` documents every key:

| File                    | Consumed by                        |
| ----------------------- | ---------------------------------- |
| `postgres.env`          | postgres                           |
| `postgres-exporter.env` | postgres-exporter                  |
| `redis.env`             | redis, redis-exporter              |
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

YuPay is then unreachable (its Caddy publishes nothing), but no state is lost: the Postgres and
Redis volumes are untouched, and media lives in Cloudflare R2, off-box entirely. To restore YuPay instead, re-add `ports: 80/443` to its Caddy
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

## Putting YuPay behind Cloudflare

On 2026-08-15 every YuPay hostname went unreachable **from Uzbekistan** while the
box itself was healthy: `marketing.kolikosoft.com` on the same VPS kept serving,
because it is fronted by Cloudflare and its visitors never touch the OVH IP.
Ours resolved straight to `152.228.137.175`, so a broken UZ↔OVH transit took the
storefront down — and, worse, took Payme's webhooks with it, which surfaced to
customers as «нет ответа от поставщика» on real payments.

The domain's DNS already lives at Cloudflare, so the switch is per-record
("proxied" / orange cloud) and needs no deploy. What it _does_ need is that the
edge already knows how to read the client IP from behind Cloudflare — that is
the two-`handle` split in `infra/edge/Caddyfile`, which works in both states, so
records can be flipped either way at any time.

**Flip the record only after confirming these, or payments break differently:**

| Cloudflare setting   | Required value                     | Why                                                                                                                              |
| -------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| SSL/TLS mode         | **Full (strict)**                  | The origin serves a real Let's Encrypt cert. "Flexible" makes CF talk cleartext to an HTTPS origin and loops the redirect        |
| Bot Fight Mode / WAF | **no challenge on `api.yupay.uz`** | A challenge page returned to Payme/Click/Uzum is an unanswered webhook. Add a skip rule for `/api/v1/payments/*` before flipping |
| Caching              | leave API uncached                 | CF caches by extension by default, so JSON is untouched — but do not add a blanket cache rule on `api.`                          |
| WebSockets           | on (default)                       | `wss://api.yupay.uz` carries order status                                                                                        |

Verify after flipping — the Payme allowlist in `Caddyfile.prod` is the canary,
since it 403s the moment the client IP stops being the real one:

```bash
# real client IP must survive the extra hop, not become a Cloudflare address
curl -sI https://api.yupay.uz/healthz
docker compose -f docker-compose.prod.yml logs caddy --tail 50 | grep -i 'client_ip\|403'
```

A 403 on `/api/v1/payments/payme/merchant` for a genuine Payme call means
`CF-Connecting-IP` is not reaching the stack: check that the request arrived over
a Cloudflare range the edge matcher knows (ranges are pinned in the Caddyfile and
do drift — refresh from `https://www.cloudflare.com/ips-v4`).
