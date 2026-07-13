# Runbook — Telegram Bot API connectivity

Every container that calls the Telegram Bot API depends on the host's egress path to
`api.telegram.org`:

- `bot` — long-poll `getUpdates` + `sendMessage` (user-facing `/start`).
- `api` / `worker` / `scheduler` — admin alerts & order notifications.

**The correct configuration depends entirely on the host.** Read the next section before
changing anything: the workaround that fixes one host is exactly what breaks the other.

## Current host (`152.228.137.175`) — IPv4, direct, no workarounds

This host reaches Telegram over **IPv4** (302 in ~60 ms) and has **no global IPv6 address at
all**. So the stack runs with no special networking:

- `bot` is a normal bridge container (no `network_mode: host`).
- The `default` network is a plain bridge — no `enable_ipv6`, no ULA subnet, no MTU pin.
- No `gai.conf` mount, no `tcp_mtu_probing` sysctls.
- `TELEGRAM_PROXY_URL` is **empty** — no outbound proxy. The code path still exists
  (`telegram_proxy_url` in `core/config.py`, `AiohttpSession(proxy=…)` in the bot), so a future
  host that needs one can set it without a code change.

Confirm the assumption on any new host before trusting it:

```sh
curl -4 -m 10 -sS -o /dev/null -w 'v4: %{http_code} in %{time_total}s\n' https://api.telegram.org
curl -6 -m 10 -sS -o /dev/null -w 'v6: %{http_code} in %{time_total}s\n' https://api.telegram.org
ip -6 addr show scope global    # empty on this host
```

Expected here: `v4: 302` fast, `v6:` fails, no global IPv6. If that still holds, any Telegram
timeout is **not** a routing problem — check the bot token, `TG_ALERT_CHAT_ID`, and whether the
container can resolve DNS at all.

## If you move to a host where Telegram's IPv4 is blocked (RU clouds)

This was the situation before 2026-07-13, and the workarounds are preserved here because they
are non-obvious and took a while to get right. They were removed from
`docker-compose.prod.yml` (see [ADR-0030](../decisions/0030-shared-edge-proxy-on-a-co-hosted-vps.md))
— **do not re-add them speculatively.** On a host with no global IPv6 they turn working egress
into connect timeouts.

### Diagnosis

```sh
curl -4 -m 10 -sS -o /dev/null -w '%{http_code} %{time_total}\n' https://api.telegram.org   # times out
curl -6 -m 10 -sS -o /dev/null -w '%{http_code} %{time_total}\n' https://api.telegram.org   # 302 in ~0.1s
```

If `-4` hangs and `-6` returns fast, Telegram IPv4 is blocked. (If both fail, it's a full
egress outage — different problem.) Symptoms: `/start` never gets a reply, the bot logs
`TelegramNetworkError: Request timeout`, admin alerts silently fail. Note that `getUpdates` /
`get_me` may still appear to work (small packets) — outbound `sendMessage` is what times out.

### The three-part fix

1. **`bot` → `network_mode: host`.** It is outbound-only with no internal-network dependencies,
   so it can borrow the host netns and use the host's working IPv6 directly. (Host networking
   forbids namespaced `net.*` sysctls, so `tcp_mtu_probing` cannot be set on it.)

2. **`api` / `worker` / `scheduler` → IPv6 egress on the bridge.** They need `postgres` /
   `redis` service-name DNS, so they stay on the bridge; give the `default` network
   `enable_ipv6: true` and a ULA subnet (e.g. `fd00:c0de:cafe::/64`). Docker ≥ 27 NAT66-
   masquerades ULA to the host's global IPv6 by default; on older Docker set
   `"ip6tables": true` in `/etc/docker/daemon.json` and restart the daemon, otherwise the
   containers get ULA addresses with no route out.

3. **`/etc/gai.conf` on api/worker/scheduler.** NAT66 alone is necessary but not sufficient. A
   bridge container's only IPv6 _source_ is the ULA (`fc00::/7`), which under RFC 6724's default
   label table carries label 6, while a global IPv6 destination carries label 1. Destination
   Rule 5 ("prefer matching label") demotes the global-IPv6 destination and `getaddrinfo` hands
   back the **blocked IPv4** first. `infra/docker/gai.conf` reproduces the default table with
   one change — relabel `fc00::/7` to 1 — so IPv6 sorts first.

   This bites httpx but not aiogram: aiohttp does Happy Eyeballs (races v4/v6), while httpx's
   anyio backend connects **sequentially** and `ConnectTimeout`s on IPv4 before ever trying
   IPv6. So the bot looks fine while admin alerts silently fail.

   Reproduce from inside a bridge container (`urllib` / `curl -6` are _not_ representative —
   they fall through to IPv6 and mask the bug):

   ```sh
   docker compose -f docker-compose.prod.yml exec -T api python - <<'PY'
   import time, httpx
   t = time.monotonic()
   try:
       r = httpx.get("https://api.telegram.org", timeout=5)
       print("ok", r.status_code, round(time.monotonic() - t, 2))
   except Exception as e:
       print("FAIL", type(e).__name__, round(time.monotonic() - t, 2))
   PY
   # Broken: "FAIL ConnectTimeout ~5.0". Fixed: "ok 302 ~0.2".
   ```

Payment providers are unaffected by any of this: UZ/RU acquirers are IPv4-only (no AAAA), so
there is no IPv6 destination to reorder.

An MTU pin (`com.docker.network.driver.mtu: "1450"`) and `net.ipv4.tcp_mtu_probing=2` were also
carried for Yandex Cloud, whose VPC path MTU is below 1500: small packets (TLS handshakes,
`getUpdates`) survive while a larger `sendMessage` POST with an inline keyboard is dropped.
Symptom — only _outgoing_ messages time out while `get_me` works.

### Why not host networking for api/worker too?

They reach `postgres` / `redis` by Docker service name over the bridge, and those datastores
publish no host ports. Host networking would break that DNS and force publishing the datastores
to the host — a security regression. Only the dependency-free `bot` can use it.

## Verify after deploy (any host)

```sh
# Bot replies to /start in Telegram. Then, from inside a bridge container:
docker compose -f docker-compose.prod.yml exec -T api \
  python -c "import urllib.request as u; print(u.urlopen('https://api.telegram.org', timeout=10).status)"
# Expect 200/302 quickly.
```
