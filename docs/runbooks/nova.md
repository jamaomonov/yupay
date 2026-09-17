# Runbook — NOVA (nova-gifts.com)

NOVA is a **reserve** supplier for game top-ups and a **fallback** for the
player-id check. It never receives an order or a check on its own — an
operator switches a SKU to it, or the primary check has already failed.
Design: [ADR-0081](../decisions/0081-nova-reserve-supplier.md). Code:
`apps/api/src/yupay/modules/fulfillment/suppliers/nova.py` (fulfiller),
`nova_client.py` (transport), `apps/api/src/yupay/modules/integrations/player_check_nova.py`
(check fallback), `apps/scheduler/src/yupay_scheduler/jobs/nova_reconcile.py`
(reconcile job).

## What NOVA is for

A second place to buy essentially the whole game top-up catalogue (306
categories, matched against our brands) when G2B is out of stock, short on
balance, or down, **and** a second opinion for the storefront/reseller
player-id check when the primary (G2B for a game, Waxpeer for Steam)
answers `error`. Nothing routes to NOVA automatically in either role — see
"Switching a SKU" and "The check fallback" below.

## Funding

NOVA quotes its balance in USD (`GET /api/v2/balance` →
`{"ok":true,"balance":"…","currency":"USD"}`); how the owner actually funds
it (bank, card, USDT) is between them and NOVA, not something this repo
does. **As of 2026-09-17 the balance is `$0.0000` and no order has ever been
placed on this key** — the adapter is wired but cannot fulfil anything until
someone funds it and runs the first live order below.

**Do not trust the admin integrations health card for NOVA.** It will show
"Не настроен" (`reason: unknown supplier`) regardless of whether
`NOVA_API_KEY` is actually set: `GET /api/v1/admin/integrations/nova/health`
checks the slug against `_KNOWN_SUPPLIERS` in `integrations/routes.py`,
which does not include `"nova"`, and `NovaFulfiller` defines no `health()`
method for that route to call (unlike `g2b`/`gengine`/`waxpeer` — see
ADR-0081's consequences). Check funding directly instead:

```bash
curl -s https://nova-gifts.com/api/v2/balance -H "X-API-Key: $NOVA_API_KEY"
```

**Turning the key on/off.** `NOVA_API_KEY` lives in `secrets/api.env`
alongside every other supplier key. Settings are cached per-process
(`get_settings()`, `functools.lru_cache`), so editing the file is not
enough — a plain `restart` does not re-read `env_file` either:

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate api worker scheduler
```

`worker` needs the key because it is what actually calls `fulfill()` when
`FULFILMENT_ASYNC` is on; `scheduler` needs it because `nova_reconcile`
polls NOVA directly. Clearing `NOVA_API_KEY` (empty string) and
recreating those three turns NOVA off completely — no top-ups, no check
fallback — without touching code. See "The check fallback" below to turn
off only the check while keeping top-ups live.

A **zero or exhausted balance is not a code problem**: NOVA refuses the
create, the adapter recognises a refusal whose text contains "not enough
balance" / "insufficient balance" / "insufficient funds" (they document no
error code for this, so the match is on the message — see
`_LOW_BALANCE_HINTS` in `nova.py`), and turns it into the saga's existing
`supplier_low_balance` stall rather than a hard failure: the task lands in
the admin inbox (Fulfilment → "Failed" tab) with an ops alert
(`kind="supplier_low_balance"`), and the **order item stays `in_progress`**
so the storefront keeps saying "обработка" instead of erroring out. Top up,
then Retry the task. If NOVA ever refuses for low balance with wording
outside those three phrases, it will instead land as a normal `failed` task
graded `UNKNOWN` — same inbox, no alert distinction, worth widening
`_LOW_BALANCE_HINTS` if that phrase turns out to be common.

## Switching a SKU to NOVA and back

The exact mirror of the Steam (Waxpeer) / G-Engine procedure — nothing NOVA-
specific about the mechanism, only about what has to exist first.

**Prerequisite: an active mapping.** NOVA is in `MAPPING_REQUIRED_SUPPLIERS`,
so forcing a SKU onto it without one is refused immediately with

> `no active nova mapping for this SKU — create it under Integrations →
Mappings before routing orders there`

Create it at **Admin → Integrations → Mappings** — `category_id` (e.g.
`mobile_legends_ru`) into `external_product_id`, `offer_id` into
`external_variant_id` — or run the seed (`scripts/seed/2026-09-17_nova_mappings.py`,
inside the api container so it can reach NOVA) to bulk-match a brand's
offers by denomination and print what it could not match.

**Switch it on:** Admin → **Sourcing** (`/sourcing`) → pick the SKU → mode
**"Только поставщик"** (`force_supplier`) → choose **NOVA** → Save. Every
new order for that SKU now routes to NOVA; nothing already in flight moves.

**Switch it back:** same page — either pick **"Авто"** (deletes the rule;
the SKU falls back to `sourcing._resolve_auto`, which now deterministically
picks the **oldest** active mapping, i.e. the original incumbent, per
ADR-0081 — nothing to double-check), or force it onto a specific supplier
again.

**A task that already failed elsewhere** (G2B out of stock, low balance,
etc.) does not need a sourcing-rule change — that only affects orders that
don't exist yet. Reassign the one stuck task instead: Fulfilment
(`/fulfillment`) → **"Failed"** tab → open the task → **«Сменить
поставщика»** → NOVA. This calls `POST /tasks/{id}/reassign {"supplier":
"nova"}`, which is refused the same way (no mapping, unknown slug, same
supplier) and otherwise runs the order on NOVA immediately.

## The first live order (do this once, after funding)

Nothing in this integration has ever placed a real NOVA order — the balance
was `$0.0000` at every point during development, and no test does either
(see ADR-0081's Validation). Their order object is untyped in their own
OpenAPI, so the status table in `nova.py` and this repo's reading of their
idempotency contract are both educated guesses until one real order proves
or corrects them.

1. Fund the NOVA balance (see "Funding" above).
2. Pick the cheapest matched SKU from a seed run's printed table (e.g. the
   smallest Mobile Legends RU diamond pack).
3. Switch it to NOVA ("Switching a SKU" above).
4. Complete one real checkout for it — this spends real money at NOVA, on
   purpose, once.
5. Watch the task through `/fulfillment`, or the api/worker logs for
   `nova.request` and (if it stalls) `nova.unknown_order_status` /
   `nova.order_without_status` / `nova.order_without_id`.
6. **Record what actually happened, right here:**

   ```
   Date:                        ____________________
   Order object — real keys:    ____________________  (expected: id/order_id/public_id/uuid, status/state)
   Statuses observed, in order: ____________________
   Retried with the same Idempotency-Key — result:
     [ ] returned the original order        [ ] 409 rejected        [ ] not tested
   Anything nova.py's status allow-list got wrong:  ____________________
   ```

7. Switch the SKU back once satisfied (or leave it on NOVA deliberately —
   that's an operator call, not this runbook's).

Until this section has real values in it, treat any
`nova.unknown_order_status` warning in the logs as the expected first
signal that a guess needs correcting, not as a bug to chase blind — the
warning names the unrecognised status and says which of the four sets
(in-flight / success / refunded / failure) to add it to.

## The check fallback

Fires **only** when the primary check (G2B for a game, Waxpeer for Steam)
answers `error` — never instead of `valid`/`invalid`, and it can only turn
that `error` into `valid`, never into `invalid` (ADR-0081 Decision 2 — see
`docs/product/flows/player-check.md` for the sequence diagram). It covers
five brands through a code table (`NOVA_VALIDATE` in `player_check_nova.py`):
`mobile-legends-ru`, `pubg-mobile`, `free-fire`, `magic-chess-gogo`,
`magic-chess-gogo-ru`, plus a separate Steam-login branch. **Global Mobile
Legends is deliberately absent** — NOVA's single validate category has only
ever been observed answering for a Russian account, and a brand that can't
be told apart gets no fallback rather than a guess (open question, design
doc §10).

**Turn off only the check**, keep top-ups working:

```
NOVA_PLAYER_CHECK_ENABLED=false
```

in `secrets/api.env`, then `docker compose -f docker-compose.prod.yml up -d
--force-recreate api` — the check only runs inside API request handlers
(`/catalog/brands/{slug}/check-player`, `/merchant/v1/validate/player`), so
`worker` and `scheduler` never read this flag and don't need recreating.

**Turn off everything** (top-ups and the check): clear `NOVA_API_KEY` — see
"Funding" above.

Its own circuit (`nova:player_check`, Redis keys `breaker:nova:player_check:open`
/ `:fails`, same shape as `docs/runbooks/g2b-troubleshooting.md`'s breaker
section) opens after 3 consecutive failures for 30 s, its own cache
namespace (`playercheck:nova:*`, TTL 300 s, positive verdicts only — see
`docs/architecture/cache-keys.md`), and its own tighter timeout
(`nova_check_timeout_seconds`, default 4 s — the primary check measures
830 ms – 4.9 s in production, and the fallback must not double that wait).
Only 422/404/400/409 on the _check_ call count as "about what we sent" and
do **not** open the breaker (a customer's mistyped id must not silence the
fallback for everyone); a transport failure, a 5xx, 401, 403, or 429 does.

## What the logs say

| Event                                       | Level | Meaning                                                                                              |
| ------------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------- |
| `nova.request`                              | info  | One HTTP call to NOVA — `method`, `path`, `status`. Every call, including failed ones.               |
| `player_check`                              | info  | One fallback attempt completed — `provider=nova`, `category_id`, `player_id_hash`, `status`.         |
| `player_check_failed`                       | warn  | The fallback's call to NOVA raised — `provider=nova`, redacted `error`. Never contains the raw id.   |
| `player_check_fallback_region_mismatch`     | warn  | NOVA validated the id, but for a different region than the brand expects — downgraded to `error`.    |
| `player_check_fallback_short_circuited`     | info  | The breaker (`nova:player_check`) was open — no call made.                                           |
| `nova.unknown_order_status`                 | warn  | An order status outside the allow-list — still `in_progress`. The first-live-order signal.           |
| `nova.order_without_status` / `_without_id` | warn  | Their order object had no recognisable `status`/`state` or `id`/`order_id`/`public_id`/`uuid` field. |
| `nova_reconcile.tick`                       | info  | One 60 s sweep finished — `checked`, `reconciled`, `failed`.                                         |
| `nova_reconcile.task_failed`                | warn  | One task's reconciliation raised — the sweep continues past it.                                      |

`nova.request` at `info` is verbose by design — it is the only line that
shows every call, including the ones nothing else logs. For a specific
order, grep the task id or the api container's recent `nova.request` lines
by timestamp.

## Rate limits

NOVA documents exactly **one** rate limit, and it is on
`GET /steam-gifts/games` (1 request / 3 min) — an endpoint this integration
never calls. Nothing is documented for `validate-id`, `topups/order`, or
`topups/offers`.

If a 429 ever appears anyway: on the **check** path it counts against the
breaker (`_counts_against_supplier` treats 429 as "about NOVA's health", not
about our input — backing off is the point of a rate limit, and this whole
module exists because the _primary_ hit one), so the breaker absorbs it and
the fallback goes quiet for 30 s rather than retrying into the limit. On the
**order** path there is no retry budget by design — `create_topup_order` is
sent once, like every other supplier's money-spending call — so a 429 there
is graded `UNKNOWN` (not `RETURNED`: it isn't one of their 400/403/404
request refusals) and parks the task for a human, same as any other
unexplained create failure.

## Related

- [ADR-0081](../decisions/0081-nova-reserve-supplier.md) — design and the
  four decisions this runbook assumes.
- [ADR-0031](../decisions/0031-storefront-player-check.md),
  [ADR-0052](../decisions/0052-g-engine-as-a-second-source.md),
  [ADR-0079](../decisions/0079-region-brands-and-brand-level-player-check.md)
  — the check, the second-source precedent, and the brand-scoped check this
  fallback plugs into.
- `docs/product/flows/player-check.md` — the check sequence diagram,
  including the NOVA branch.
- `docs/runbooks/merchant-b2b.md` § `POST /merchant/v1/validate/player keeps
answering error` — the reseller-facing side of the same fallback.
- `docs/runbooks/g2b-troubleshooting.md` — the primary this fallback stands
  behind; its breaker section is the template this one follows.
- `apps/api/src/yupay/modules/fulfillment/README.md` § Поставщики,
  `apps/api/src/yupay/modules/sourcing/README.md` — the sourcing/fulfilment
  mechanics this runbook operates, in more detail.
