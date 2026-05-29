# Runbook — Telegram Bot API connectivity (IPv4 blocked)

The prod host (RU cloud) cannot reach `api.telegram.org` over **IPv4** — the
range is blocked at the network egress. It is reachable only over **IPv6**.
Every container that calls the Telegram Bot API is affected:

- `bot` — long-poll `getUpdates` + `sendMessage` (user-facing `/start`).
- `api` / `worker` / `scheduler` — admin alerts & order notifications.

## Symptom

- `/start` (or any bot reply) never arrives; the bot logs
  `aiogram.exceptions.TelegramNetworkError: Request timeout`.
- Admin Telegram alerts/notifications from api/worker silently fail to send.
- Long-poll `getUpdates` / `get_me` may still appear to "work" intermittently
  (small packets), which is misleading — outbound `sendMessage` is what times
  out.

## Diagnosis (run on the host)

```sh
# IPv4 is blocked, IPv6 works → this is the failure mode:
curl -4 -m 10 -sS -o /dev/null -w '%{http_code} %{time_total}\n' https://api.telegram.org   # times out
curl -6 -m 10 -sS -o /dev/null -w '%{http_code} %{time_total}\n' https://api.telegram.org   # 302 in ~0.1s
```

If `-4` hangs and `-6` returns fast, Telegram IPv4 is blocked and the fix below
applies. (If both fail, it's a full egress outage — different problem.)

## Fix (already in `docker-compose.prod.yml`)

The history here matters: an earlier fix **disabled** IPv6 in every container
(`net.ipv6.conf.*.disable_ipv6=1`) on the theory that the bridge had no IPv6
route and happy-eyeballs was hanging on a dead AAAA. The real situation is the
opposite — IPv6 is the **only** working path — so that fix was removed and
replaced with:

- **`bot` → `network_mode: host`.** The bot is outbound-only with no
  internal-network dependencies, so it borrows the host network namespace and
  uses the host's working IPv6 directly. (Host networking forbids namespaced
  `net.*` sysctls, so `tcp_mtu_probing` is dropped on the bot — the host sets
  its own.)
- **`api` / `worker` / `scheduler` → IPv6 egress on the bridge.** They keep the
  bridge network (they need `postgres` / `redis` / `api` service-name DNS), and
  the `default` network now has `enable_ipv6: true` + a ULA subnet
  (`fd00:c0de:cafe::/64`). Docker NAT66-masquerades the ULA to the host's
  global IPv6. The old `disable_ipv6` sysctls were dropped; `tcp_mtu_probing=2`
  is kept (`x-mtu-probe` anchor) for the remaining IPv4 egress (payment
  providers).

### Docker version requirement (NAT66)

The bridge IPv6 egress depends on Docker masquerading the ULA subnet:

```sh
docker version --format '{{.Server.Version}}'
```

- **Docker ≥ 27** — `ip6tables` is on by default and NAT66 for ULA subnets
  works out of the box. Nothing else to do.
- **Docker < 27** — add `"ip6tables": true` to `/etc/docker/daemon.json` and
  restart the daemon (`systemctl restart docker`), otherwise the containers get
  ULA addresses with no route out and Telegram calls from api/worker keep
  failing (the bot is unaffected — it's on host networking).

The host itself must have a working IPv6 default route — the `curl -6` check
above confirms it.

## Verify after deploy

```sh
# Bot replies to /start in Telegram. Then from inside a bridge container:
docker compose -p yupay-prod exec -T api \
  python -c "import urllib.request as u; print(u.urlopen('https://api.telegram.org', timeout=10).status)"
# Expect 200/302 quickly. A timeout means NAT66 isn't working → check Docker
# version / ip6tables above.
```

Confirm the container actually got an IPv6 address:

```sh
docker compose -p yupay-prod exec -T api ip -6 addr show eth0   # should list an fd00:c0de:cafe::/64 address
```

## Why not host networking for api/worker too?

`api`/`worker`/`scheduler` reach `postgres`/`redis`/`api` by Docker service
name over the bridge; those backing services are **not** published to host
ports. Host networking would break that DNS and force publishing the datastores
to the host (a security regression). So only the dependency-free `bot` uses host
networking; the rest get IPv6 on the bridge.

## Rollback

If the IPv6 change misbehaves (e.g. NAT66 not available and outbound to
IPv4-only providers regresses), revert `docker-compose.prod.yml` to the
`x-no-ipv6` anchor + `sysctls` on all four services and redeploy. The bot will
go back to being broken on `/start`, but api/worker return to their prior state.
Prefer fixing the Docker `ip6tables` setting over rolling back.
