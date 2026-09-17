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

**Where to look:** Admin → Интеграции → NOVA. The card probes
`GET /api/v1/admin/integrations/nova/health`, which calls
`NovaFulfiller.health()` and reports three things in one line — whether the
key is set, whether NOVA accepted it, and the balance behind it. That probe
exists because NOVA is a reserve: nothing routes to it on an ordinary day, so
a dead key or an empty balance would otherwise be discovered at the moment
somebody needs to switch a SKU to it.

The same answer from a shell, when the admin is not to hand:

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
`external_variant_id` — or run the seed for a whole brand at once:

```bash
docker compose -f docker-compose.prod.yml exec -T api \
  python - < scripts/seed/2026-09-17_nova_mappings.py
```

It pairs our `denomination` with a NOVA offer name on both the number and the
unit ("1800 UC" is not "1800 WOW Coins", and NOVA sells both under one PUBG
category), writes an ACTIVE mapping only where exactly one offer matches and
exactly one of our SKUs claims it, then prints two tables: `matched` (`sku_code`, NOVA's offer
name, our `cost_usdt` beside their `price_usd` — compare before trusting a
margin) and `unmatched` (`sku_code`, `denomination`, why) for an operator to
finish by hand in the admin. Writing mappings active is safe on its own —
auto sourcing skips reserve suppliers entirely (`RESERVE_SUPPLIERS`), so
nothing routes to NOVA until `force_supplier` says so, whatever else changes
about the SKU's other mappings.

**PUBG Mobile is a guess, check it before trusting it.** NOVA sells PUBG
under four speed tiers (`pubg_mobile_auto`/`_fast`/`_manual`/`_reserve`,
same game, different fulfilment speed and price); the seed picks `_auto`
on a hunch. Confirm that's the right tier against the `matched` table's
price column, and edit the mapping by hand if not.

**Switch it on:** Admin → **Sourcing** (`/sourcing`) → pick the SKU → mode
**"Только поставщик"** (`force_supplier`) → choose **NOVA** → Save. Every
new order for that SKU now routes to NOVA; nothing already in flight moves.

**Switch it back:** same page — either pick **"Авто"** (deletes the rule;
the SKU falls back to `sourcing._resolve_auto`, which skips NOVA as a reserve
and picks the **oldest** of its remaining active mappings, i.e. the original
incumbent, per ADR-0081 — nothing to double-check), or force it onto a
specific supplier again. A SKU whose only active mapping was NOVA lands in
the manual queue rather than back on NOVA, which is the intended answer: a
reserve is never the automatic route.

**A task that already failed elsewhere** (G2B out of stock, low balance,
etc.) does not need a sourcing-rule change — that only affects orders that
don't exist yet. Reassign the one stuck task instead: Fulfilment
(`/fulfillment`) → **"Failed"** tab → open the task → **«Сменить
поставщика»** → NOVA. This calls `POST /tasks/{id}/reassign {"supplier":
"nova"}`, which is refused the same way (no mapping, unknown slug, same
supplier) and otherwise runs the order on NOVA immediately.

## The first live order — done, 2026-09-17

**It has been placed.** One 60 UC top-up for PUBG Mobile, on the owner's own
test account, against `pubg_mobile_auto`. It completed in **8 seconds**. What
follows is not a form to fill in any more; it is what their API actually does,
and it corrected two things this integration had guessed.

```
Order id:      "ord-1372576"       (key: `id`, a prefixed string, not a number)
Charged:       $0.901476 on create — balance 10.0000 -> 9.0985
Statuses:      created -> processing -> completed      (8s end to end)
```

The order object, in full, is the shape `nova.py` reads:

- `id`, `status`, `kind`, `title` — plus `category_id`, `offer_id`,
  `offer_name`, `category_name`, `fields` (our submitted `player_id`),
  `price_usd`, `total_usd`, `created_at`, `completed_at`.
- **`fail_reason`** — `null` on a healthy order. On a failure this is the only
  thing that says _why_, which is why `nova.py` copies it into `task.last_error`
  and into `nova_fail_reason` on the task's metadata.
- **`status_history`** — `[{status, at}, …]`, the whole path. Useful when an
  order sat somewhere: it timestamps each step.
- The `GET` adds money fields the create response does not carry
  (`amountUsd`, `chargedUsd`, `charged_usd`, `customerAmountUsd`,
  `novaAmountUsd`, `totalUsd`) — all equal to the price here, and none of them
  read by our adapter.

**All three observed statuses were already in the allow-list** (`created` and
`processing` in-flight, `completed` success), so no correction was needed
there.

### What it corrected

**1. A reused `Idempotency-Key` is refused, not replayed.** Their endpoint
description says a repeat "returns the original order instead of
charging/fulfilling again"; their parameter description says it "is rejected".
The parameter description is the true one:

```
409  {"message":"This Idempotency-Key was already used for a purchase. Create a
      new key for a new purchase.","error":"Conflict","statusCode":409}
```

So **a create is never safely retried under the same key** — which is what
`nova.py` already assumed by grading a 409 `UNKNOWN`. It also means a create
whose response we lost cannot be recovered by replaying it: find the order in
`GET /api/v2/orders` instead, matching `fields.player_id`, `offer_id` and
`created_at`, and settle the task by hand.

The header is genuinely **required** — without it, `400 Idempotency-Key header
is required for purchase requests`.

**2. Their real error envelope is not the documented one.** Their OpenAPI
describes `{"ok": false, "error": "…", "code": "…"}`. A live 400/409/502
returns `{"message": "…", "error": "<status name>", "statusCode": N}` — no
`ok`, and `error` holding the word "Conflict" rather than the reason. The
client reads `message` first for exactly this reason (`_message_of`);
otherwise `task.last_error` would have said "Conflict" and nothing more.

**3. A bad `offer_id` answers `502`, not `404`.**
`{"message":"Unable to determine the current product price","error":"Bad
Gateway","statusCode":502}` — and the balance does **not** move. `nova.py`
grades a 502 `UNKNOWN`, so a mistyped mapping produces one task asking a human
to chase money that was never spent. That is the safe direction and it is
deliberate: no status alone can tell "they refused before charging" from "they
broke while charging". If you see that sentence in the inbox, the fix is the
mapping, not the money.

### While you are there: the PUBG tier

NOVA sells PUBG under four tiers. Measured 60 UC, same day:

| tier                  | 60 UC     |
| --------------------- | --------- |
| `pubg_mobile_auto`    | $0.901476 |
| `pubg_mobile_reserve` | $0.901476 |
| `pubg_mobile_manual`  | $0.915552 |
| `pubg_mobile_fast`    | $0.924222 |

`_auto` is the cheapest and it delivered in 8 seconds, so the seed's default
is confirmed rather than guessed. `_fast` costs 2.5% more for no observed
benefit at this denomination.

### Repeating this for another game

Place it the same way — through a switched SKU and a real checkout, not by
hand — and add a line here if the game behaves differently. A game whose
fulfilment is slower is the case most likely to show a status we have not
seen; `nova.unknown_order_status` in the logs names it and says which of the
four sets to add it to.

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
