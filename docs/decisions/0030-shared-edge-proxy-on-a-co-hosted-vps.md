# 0030. Shared edge proxy on a co-hosted VPS

- **Status**: Accepted
- **Date**: 2026-07-13
- **Deciders**: @jamaomonov
- **Tags**: infra

## Context and problem statement

Production moved to a VPS (`152.228.137.175`) that already hosts an unrelated compose stack,
`streamers-parser`. That stack's Caddy binds `:80` and `:443` and serves a single hostname
(`marketing.kolikosoft.com`) behind Cloudflare with a self-signed origin certificate.

YuPay's `docker-compose.prod.yml` also published `:80` and `:443` from its own Caddy. Two
processes cannot bind the same privileged ports, so the second stack to start simply fails.
YuPay genuinely needs those ports: it serves five hostnames (`yupay.uz`, `www`, `app`, `admin`,
`api`, `grafana`) with real Let's Encrypt certificates, and ACME's HTTP-01 challenge is only
answerable on `:80`.

Nothing else collides. Every other YuPay service (Postgres, Redis, MinIO, Prometheus, Grafana,
Loki) is reachable only inside the compose network and publishes no host port, so the ports
`streamers-parser` occupies (3000–3004, 5432, 8000, 9090, 3100) are irrelevant to us.

The same move surfaced a second, unrelated problem. The compose file carried a pile of
workarounds for the previous RU-cloud host, where Telegram's IPv4 ranges were blocked: an
IPv6-enabled bridge with a ULA subnet, a `gai.conf` that re-labels `fc00::/7` so `getaddrinfo`
prefers IPv6, `network_mode: host` on the bot, and a 1450-byte MTU. The new host is the exact
inverse — `api.telegram.org` answers over IPv4 in 60 ms and the host has **no global IPv6
address at all**. Left in place, `gai.conf` would push every outbound resolution toward an IPv6
path that dead-ends, turning Telegram alerts and supplier calls into connect timeouts.

## Decision drivers

- Both stacks must keep serving their own hostnames with their own TLS story.
- Neither stack's deploy or restart may take the other one's TLS down.
- Each stack should keep owning its routing rules (CSP, WebSocket, basic-auth, header policy)
  in its own repository — copying YuPay's Caddyfile into a neighbouring project's config is a
  maintenance trap.
- Certificate state must live somewhere with a clear owner; Let's Encrypt rate limits
  (50 certs/week/domain) make "just re-issue" a poor recovery plan.

## Considered options

1. **YuPay's Caddy becomes the single edge** — take `:80`/`:443` from `streamers-parser` and
   move its hostname into YuPay's Caddyfile.
2. **`streamers-parser`'s Caddy stays the edge** — it terminates TLS for `*.yupay.uz` and
   forwards to YuPay's internal Caddy.
3. **A standalone edge proxy** — a third, minimal compose project owns `:80`/`:443` and
   forwards each hostname to the owning stack's internal Caddy.

## Decision outcome

**Chosen option: Option 3 — a standalone edge proxy** (`infra/edge/`).

A third `caddy:2-alpine` container is the sole owner of `:80`/`:443`. It terminates TLS and
forwards cleartext HTTP over a shared external docker network (`yupay-edge`) to whichever
stack owns the hostname. Both application stacks drop their host port bindings and keep their
own Caddy as an internal host-router:

```
edge-caddy :80/:443
├── yupay.uz, www, app, admin, api, grafana  → yupay-caddy:80      (Let's Encrypt)
└── marketing.kolikosoft.com                 → streamers-caddy:80  (tls internal, Cloudflare)
```

The upstreams are network _aliases_, not service names: both stacks call their proxy `caddy`,
so on a shared network the bare name would be ambiguous. YuPay registers `yupay-caddy` and
`streamers-parser` registers `streamers-caddy`.

Two consequences follow for YuPay's own Caddy, and both are load-bearing:

- `auto_https off` — certificates are the edge's job. Without it, Caddy tries to solve ACME
  challenges on ports it cannot bind and the config never becomes ready.
- `trusted_proxies static private_ranges` — the edge is the only hop in front of us, so its
  `X-Forwarded-{For,Proto,Host}` must be preserved rather than overwritten. Otherwise every
  request reaches FastAPI as plain `http` originating from the proxy's own container IP, which
  breaks scheme-aware URL building and makes slowapi's per-IP rate limiting bucket the whole
  internet into one key.

Alongside this, the RU-cloud egress workarounds were removed: no `enable_ipv6`/ULA subnet, no
`gai.conf` mount, no `network_mode: host` on the bot, no MTU pin, no Telegram proxy.

### Positive consequences

- Neither stack can take the other's TLS down; the edge's lifecycle is independent of both.
- Each stack keeps its routing rules in its own repo. The edge only maps hostname → stack.
- Symmetric: adding a third stack later is one more block in the edge Caddyfile.
- All certificates live in one clearly-owned volume (`edge_caddy-data`).

### Negative consequences

- One extra proxy hop (loopback-local, sub-millisecond) and one extra container.
- Requires an out-of-band `docker network create yupay-edge` before the first deploy, and a
  matching edit to a _second_ repository (`streamers-parser`'s compose) that is not versioned
  here. That edit is documented in `docs/runbooks/deploy-shared-vps.md`.
- `X-Forwarded-*` correctness now depends on `trusted_proxies` being right. Get it wrong and
  the failure is silent — wrong client IPs in rate limits rather than an error.

## Validation

- `curl -fsS https://api.yupay.uz/healthz` and `/readyz` return 200 with a valid LE certificate.
- `https://marketing.kolikosoft.com` keeps serving through Cloudflare after the cutover.
- Restarting the YuPay stack does not interrupt `marketing.kolikosoft.com`, and vice versa.
- The API sees real client IPs: `X-Forwarded-For` in the access log is the caller, not the
  edge container's address.

## Alternatives considered (detail)

### Option 1 — YuPay's Caddy as the single edge

Fewest containers and no extra hop. Rejected because it makes YuPay's Caddyfile the owner of a
foreign project's routing rules: any change to `marketing.kolikosoft.com` would land in this
repo, and a YuPay redeploy would drop that site's TLS. It also inverts responsibility — the
neighbouring stack would depend on ours for something it used to own.

### Option 2 — `streamers-parser`'s Caddy as the edge

Cheapest to set up (it already binds the ports). Rejected for the mirror-image reason: YuPay's
Let's Encrypt certificates and account key would live in a volume owned by an unrelated
project, and any restart or `docker volume prune` there would take YuPay's TLS with it, into
Let's Encrypt's rate limit. It also puts a stack we do not control on the critical path of
every payment webhook.

## References

- `infra/edge/Caddyfile`, `infra/edge/docker-compose.yml`
- `infra/caddy/Caddyfile.prod` — the YuPay stack's internal host-router
- `docs/runbooks/deploy-shared-vps.md` — cutover procedure and rollback
- `docs/runbooks/telegram-connectivity.md` — the egress workarounds this ADR retires
- Caddy: [`trusted_proxies`](https://caddyserver.com/docs/caddyfile/options#trusted-proxies),
  [`auto_https`](https://caddyserver.com/docs/caddyfile/options#auto-https)
