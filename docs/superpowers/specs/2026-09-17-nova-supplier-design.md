# Design: NOVA (nova-gifts.com) as a reserve supplier and a player-check fallback

**Date:** 2026-09-17
**Status:** Approved in brainstorming (owner: «ок») — this document records the design, with two
deviations from the sketch flagged in §5
**Branch:** `feat/nova-supplier`
**Surface:** API (`fulfillment.suppliers`, `integrations.player_check`, `sourcing`, `core.config`),
scheduler (one reconcile job), admin SPA (supplier lists), catalog data on prod (mappings), docs
**New ADR:** 0081

---

## 1. Problem

Two independent pressures, one supplier answers both.

**Fulfilment has no reserve for game top-ups.** G2B is the only route for every game brand we
sell. When G2B is out of stock on a denomination, short on balance, or down, the order lands in
the manual admin queue and a human finishes it. G-Engine is a second source, but only for Steam
and a handful of titles (ADR-0052); it does not cover MLBB, PUBG, Free Fire or the rest.

**The player check has no fallback at all.** `POST /catalog/products/{id}/check-player` and
`POST /merchant/v1/validate/player` both end at G2B. When G2B rate-limits us, errors, or is
unreachable, every check answers `error` — the storefront shows "не удалось проверить" and the
reseller cabinet shows nothing. Merchants are about to start calling the same endpoint, on the
same G2B bucket, which makes the rate limit a shared resource we will hit sooner.

NOVA sells both: 306 top-up categories covering essentially our whole game catalogue, and a
`validate-id` endpoint for five games — two of which are the region-split pair (Magic Chess Go Go
Global / RU) that our own catalogue splits the same way.

## 2. Facts established

Probed live against `https://nova-gifts.com` on 2026-09-17 with our API key (key never printed,
passed through an environment variable).

| Fact                   | Value                                                                                                                                     |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Auth                   | `X-API-Key: ng_…` header (legacy `X-App-API-Key` also accepted)                                                                           |
| Base URL               | `https://nova-gifts.com`, paths under `/api/v2`                                                                                           |
| Our balance            | `{"ok":true,"balance":"0.0000","currency":"USD"}` — **zero; nothing can be ordered yet**                                                  |
| Our order history      | `GET /api/v2/orders` → `{"items":[],"total":0}` — no order has ever been placed                                                           |
| Top-up categories      | 306, cursor-paged, `category_id` + `name`                                                                                                 |
| Offers                 | `GET /api/v2/topups/offers?category_id=…` → `offers[] = {offer_id, name, price_usd}` and `fields[] = {key, label, type}`                  |
| Field keys             | `player_id`, `server_id` — the same names our own forms use                                                                               |
| Order create           | `POST /api/v2/topups/order {category_id, offer_id, fields}` + `Idempotency-Key` header                                                    |
| Order object           | **untyped** in their OpenAPI (`order: {}` with `additionalProperties: true`)                                                              |
| Error envelope         | `{"ok":false,"error":"…","code":"…"}`; 403 adds `blockReason` and `code: subscription_inactive`                                           |
| Documented rate limits | one only, on `GET /steam-gifts/games` (1 request / 3 min). Nothing on validate or order                                                   |
| Validate games         | `pubg_mobile`, `free_fire`, `mobile_legends`, `magic_chess_gogo_global`, `magic_chess_gogo_ru`                                            |
| Validate call          | `POST /api/v2/topups/validate-id {category_id, fields}` → `{ok, valid, player_name, player_id, region}`; `422` = "could not be confirmed" |
| Steam login check      | `POST /api/v2/steam-topup/check-login {steamLogin}` → `{ok, can_refill}`                                                                  |

Two observed verdicts, both under `category_id: "mobile_legends"`:

```
{"player_id":"1313232551","zone_id":"6618"} → {"valid":true,"player_name":"blood moon","region":"Russia"}
pubg_mobile, {"player_id":"1"}              → {"valid":false,"player_name":null}
```

Catalogue coverage against our brands (matched by name from their 306 categories):

| Our brand                      | NOVA `category_id`                                                          |
| ------------------------------ | --------------------------------------------------------------------------- |
| `mobile-legends`               | `mobile_legends_global`                                                     |
| `mobile-legends-ru`            | `mobile_legends_ru`                                                         |
| `magic-chess-gogo`             | `magic_chess_gogo_global`                                                   |
| `magic-chess-gogo-ru`          | `magic_chess_gogo_ru`                                                       |
| `pubg-mobile`                  | `pubg_mobile_auto` (also `_fast`, `_manual`, `_reserve` — four speed tiers) |
| `free-fire`                    | one of eleven regional categories (`free_fire_cis`, `_eu`, `_br`, …)        |
| `blood-strike`                 | `blood_strike`                                                              |
| `delta-force`                  | `delta_force`                                                               |
| `arena-breakout` / `-infinite` | `arena_breakout` / `arena_breakout_infinite`                                |
| `genshin-impact`               | `genshin_impact_global`                                                     |
| `honkai-star-rail`             | `honkai_star_rail_global`                                                   |
| `whiteout-survival`            | `whiteout_survival`                                                         |
| `oxide-survival-island`        | `oxide_survival_island`                                                     |

Not covered: Roblox, Standoff 2, Telegram Stars / Premium (they have a separate Fragment API
namespace, out of scope here).

**Two namespaces, not one.** A validate `category_id` is not a top-up `category_id`:
`mobile_legends` validates, `mobile_legends_global` and `mobile_legends_ru` sell. Nothing in the
API links them. Any code that reuses one id for the other is wrong.

**The idempotency contract contradicts itself.** The endpoint description says a repeated
`Idempotency-Key` "returns the original order instead of charging/fulfilling again"; the
parameter description on the same endpoint says "Reusing the same key is rejected to prevent
duplicate purchases". With a zero balance we cannot find out which is true. §4.2 is built so that
either answer is safe.

## 3. Scope

**In:** a `nova` supplier client and fulfiller for **game top-ups** (`kind="game"` mappings), a
reconcile job, the reserve role in sourcing, a player-check fallback over their `validate-id`, and
a Steam-login fallback over their `check-login`.

**Out:** gift cards, game keys, Steam gifts, manual services, the Fragment (Telegram) API, Steam
wallet top-ups through NOVA, any automatic supplier→supplier failover chain, and any change to
what a customer sees.

## 4. Design

### 4.1 Client — `fulfillment/suppliers/nova_client.py`

Transport only, the shape `gengine_client.py` established: `httpx.AsyncClient` per call, the key
from settings, `NovaError(message, status, code, body)` for a refusal that arrived, and
`NovaUnavailableError` for one that did not (network, DNS, timeout). Every response carries
`ok`, so `ok: false` on an HTTP 200 is a refusal too and is raised as `NovaError`.

Methods, one per endpoint we use: `get_balance`, `list_topups` (cursor-paged, for the catalogue
sync and the seed), `get_offers`, `create_topup_order`, `get_order`, `validate_id`,
`check_steam_login`.

`create_topup_order` always sends `Idempotency-Key`. Retries: the same conservative rule as the
other clients — a GET may be retried, a POST that can spend money is sent **once**.

### 4.2 Fulfiller — `fulfillment/suppliers/nova.py`

Registered in `REGISTRY` as `nova`; `available` reads `settings.nova_api_key` per call, so a
hot-reloaded key needs no restart. Added to `MAPPING_REQUIRED_SUPPLIERS`, so forcing a SKU onto
NOVA without a mapping is refused at the moment the operator says so rather than at the first sale.

**Mapping.** `sku_supplier_mapping(sku_id, supplier_slug='nova', kind='game')` with
`external_product_id = category_id` and `external_variant_id = offer_id`. Both are required: their
docs state the pair is unique and that an `offer_id` string may repeat across categories.

**Fields.** `item.fulfillment_data` → their `fields`, through an explicit map:
`player_id|account → player_id`, `server|server_id|zone|zone_id → server_id`. Only keys we
recognise are forwarded, exactly as the G-Engine adapter does — an unmapped key is more likely a
form we have not taught this adapter about than something NOVA wants.

**Money.** Their words: "Balance is charged immediately; then `processing` until
completed/refund." So unlike G-Engine, **the create spends**, and this adapter follows Waxpeer's
grading rather than G-Engine's:

| Exit                                                                                                                                       | `MoneyOutcome`                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| Key missing, no mapping, no usable fields — refusals before any call                                                                       | `RETURNED`                                                     |
| `NovaError` 400/403/404 — a refusal of the request itself (unknown category or offer, bad field, `subscription_inactive`, blocked account) | `RETURNED`                                                     |
| `NovaError` 409 (their idempotency refusal, whichever way it means it)                                                                     | `UNKNOWN`                                                      |
| Their refusal reads as "not enough balance"                                                                                                | not a failure — the saga's `supplier_low_balance` stall, below |
| `NovaError` 5xx, or `NovaUnavailableError`, on the create                                                                                  | `UNKNOWN`                                                      |
| Order reported `refunded`                                                                                                                  | `RETURNED`                                                     |
| Order reported `failed` / `error` / `cancelled` with no refund marker                                                                      | `UNKNOWN`                                                      |

**Low balance is a stall, not a failure.** Our NOVA balance is `$0.0000`, so the first order will
be refused for exactly that reason. Waxpeer's precedent applies unchanged: a refusal whose text
reads as "insufficient balance" returns `fulfillment.service`'s `supplier_low_balance` sentinel
with no money outcome, which keeps the customer on "в обработке", parks the task in the admin
inbox and alerts ops, instead of failing an order that a top-up would have completed.

**Quantity.** Their order endpoint has no quantity field: one call buys one offer. An item with
`qty > 1` is refused before any call (`RETURNED`) rather than silently under-delivering.

The 409 line is the contradiction from §2 made harmless: if a reused key returns the original
order we never see a 409; if it is rejected we do, and "rejected" does not tell us whether the
first attempt charged us. `UNKNOWN` is the honest answer and it never triggers an automatic
refund.

**Status vocabulary.** Their order object is untyped, so the mapping is a small explicit table
and **everything unrecognised is `in_progress`** — Waxpeer's rule, for Waxpeer's reason: reading
an unknown status as success marks undelivered goods delivered, and reading it as failure starts
reconciliation on money that may still complete normally.

```
in flight : pending, preparing, prepared, debited, processing, in_progress, created, queued, new
success   : completed, success, delivered, done
failure   : failed, error, cancelled, canceled  → money UNKNOWN
refunded  : refunded, refund                    → money RETURNED
```

The status is read from `status`, falling back to `state`, lowercased and stripped. The order id
is read from `id`, falling back to `order_id`, `public_id`, `uuid`. Both helpers log once, at
warning, when they find nothing — that log line is how we learn their real shape from the first
live order.

**Artifact.** A top-up has no code to hand over: `topup_receipt` with supplier, external order id
and status, same as G-Engine's `_receipt`.

`check_status` re-reads `GET /api/v2/orders/{id}` and maps it through the same table.
`cancel` raises `FulfillerNotIntegratedError(money_outcome=UNKNOWN)` — they expose no cancel, and
by the time anything cancels, the order was already bought.

### 4.3 Reconcile job — `apps/scheduler/.../jobs/nova_reconcile.py`

NOVA has no webhook and their orders sit in `processing`. A copy of `gengine_reconcile.py` with
`_SUPPLIER = "nova"` and a 60-second interval, registered in `scheduler/main.py`. Same isolation
(one session per task, one bad task never aborts the sweep) and the same page ceiling.

### 4.4 Sourcing: the reserve role, and a determinism bug it exposes

NOVA is a **reserve**, exactly as G-Engine is for Steam: the mapping is active, the sourcing rule
stays on the incumbent, and switching is an admin action (`force_supplier = nova`), not an
automatic chain. No supplier→supplier failover is built here.

That role exposes a real defect in `sourcing.service._resolve_auto`. For a `top_up` SKU with no
sourcing rule it picks the supplier like this:

```python
select(SkuSupplierMapping.supplier_slug)
    .where(sku_id == …, is_active.is_(True))
    .limit(1)
```

No `ORDER BY`. Today every top-up SKU has exactly one active mapping, so the answer is stable by
accident. Add a NOVA mapping beside the G2B one and the primary route becomes whichever row
Postgres returns first — it can change after a `VACUUM`, and nothing would announce it.

**Fix, in this branch:** order the query by `created_at ASC, supplier_slug ASC`. The incumbent
mapping is the older row, so today's routing is preserved for every SKU, and a reserve mapping
added later can never take the route by being added. A regression test asserts it with two
mappings on one SKU.

### 4.5 Player-check fallback

**Trigger.** Only a primary `error`. `valid` and `invalid` are returned untouched, and the
fallback is never called when the primary answered. This keeps ADR-0031's contract: the check is
advisory, `invalid` is the only verdict that blocks Pay, and adding a second supplier must not
add a second way to block a customer.

**The fallback can answer `valid` or `error`. It never answers `invalid`.** Reasons, in order of
weight:

1. It only runs when we have no primary verdict, so its `invalid` would be the sole basis for
   blocking a paying customer, on a supplier we have never validated against our brand namespaces.
2. Their `mobile_legends` is one category for a catalogue we split into two brands, and the
   `region` field it returns ("Russia") is of unproven meaning — see the open question in §10.
3. It matches how this module already treats an answer it cannot read: `_map_response` returns
   `error`, not `invalid`, for an unrecognised G2B verdict, precisely to avoid becoming a fake
   rejecter.

The cost of this rule is a customer who mistypes an id during a G2B outage gets "не удалось
проверить" instead of "неверный ID" — which is exactly what they get today, so there is no
regression. The gain, a confirmed nickname while G2B is down, is kept in full.

**Which brands.** A module-level table in the fallback, keyed by brand slug, with at most the six
brands NOVA can validate:

```python
@dataclass(frozen=True)
class NovaValidateTarget:
    category_id: str          # their validate namespace, never the top-up one
    region_word: str | None   # what `region` must say for this brand, lowercased substring

NOVA_VALIDATE: dict[str, NovaValidateTarget] = {
    "mobile-legends-ru":     NovaValidateTarget("mobile_legends", "russia"),
    "pubg-mobile":           NovaValidateTarget("pubg_mobile", None),
    "free-fire":             NovaValidateTarget("free_fire", None),
    "magic-chess-gogo":      NovaValidateTarget("magic_chess_gogo_global", None),
    "magic-chess-gogo-ru":   NovaValidateTarget("magic_chess_gogo_ru", None),
}
```

`mobile-legends` (global) is deliberately **absent** until the open question in §10 is answered:
their single MLBB category has only ever been observed answering for a Russian account, and a
brand we cannot tell apart gets no fallback rather than a guess.

**Region guard.** When `region_word` is set and the answer's `region` does not contain it
(case-insensitive), the verdict is downgraded to `error` and logged once. Combined with the rule
above, the worst a region mismatch can cost is a missed `valid`.

**Steam.** The `waxpeer` branch gets the same treatment through
`POST /api/v2/steam-topup/check-login`: `can_refill: true → valid`, and `false` or anything else
→ `error`. `can_refill: false` is NOVA saying _they_ cannot refill that account, which is not the
same statement as "this login does not exist", so it may not become `invalid`.

**Cost control.** Its own breaker (`nova:player_check`, threshold 3, cooldown 30 s), its own cache
namespace (`playercheck:nova:{category_id}:{server or '-'}:{hash_short(player_id)}` and
`playercheck:nova:steam:{hash_short(login)}`, TTL 300 s, `valid` only — `_worth_caching`
unchanged), and its own tighter timeout `nova_check_timeout_seconds = 4.0`. The primary G2B check
takes 830 ms – 4.9 s on production; the tighter timeout is what keeps the two-supplier path from
doubling a customer's wait.

**Session.** The brand slug and the check field are read before any network call, and the session
is rolled back before the primary call as it is today. The fallback needs no database access.

**Kill switch.** `nova_player_check_enabled` (default `true`) disables the fallback without
touching top-ups; clearing `nova_api_key` disables everything.

### 4.6 Config

```python
nova_api_key: str = ""
nova_base_url: str = "https://nova-gifts.com"
nova_request_timeout_seconds: float = 20.0
nova_check_timeout_seconds: float = 4.0
nova_player_check_enabled: bool = True
```

`NOVA_API_KEY` goes into the prod env through `sops`, like every other supplier key. It is never
logged and never printed.

### 4.7 Admin

`apps/admin/src/features/integrations/types.ts`: `nova` added to `KNOWN_SUPPLIERS`, the label map
("NOVA"), the capability map (`catalogue: false` — no catalogue browser in this branch), and the
suppliers list (`external: true, mappings: true, note: "резерв: пополнения игр"`). The mapping
wizard needs no new shape: NOVA is a `game` mapping with a service id and a denomination id,
exactly the two fields it already collects.

## 5. Deviations from the approved sketch

Both narrow the design; neither widens it.

**1. The validate target is a code table, not a `kind="validate"` mapping row.** The sketch put
NOVA's validate category in `sku_supplier_mapping` with a new `kind`. Three things make that the
more expensive option: `ck_sku_supplier_mapping_kind` allows only `voucher|game|gift`, so it needs
a migration; `_resolve_auto` selects an active mapping **without filtering on kind**, so a
`validate` row on a top-up SKU would become a candidate fulfilment route; and the admin mapping
wizard coerces any loaded mapping to `voucher|game` (`MappingEditPage.tsx:108`), so opening and
saving such a row would silently rewrite its kind. Validation is brand-scoped, not SKU-scoped, and
NOVA validates five games — a reviewed table of at most six brand slugs is the smaller, safer
carrier. Adding a brand to it needs a deploy, which is correct: it also needs someone to think
about the region semantics.

**2. A region mismatch answers `error`, not `invalid`.** The sketch said a global brand whose
answer comes back `region: "Russia"` is `invalid`. See §4.5 for why no fallback verdict may block
Pay. The guard is unchanged in every other way.

## 6. Data changes

`scripts/seed/2026-09-17_nova_mappings.py`, run inside the api container so it can reach NOVA:

- reads the brand→category table for the **top-up** namespace (a separate table from §4.5's),
- fetches `GET /topups/offers` for each category,
- matches our SKUs to their offers by denomination — `Sku.units` when set, else the leading
  number in `Sku.denomination` / `sku_code` — and only on an exact numeric match,
- upserts `sku_supplier_mapping(nova, game, category_id, offer_id, is_active=true)`,
- prints a table: matched SKUs with our `cost_usdt` beside their `price_usd`, and every SKU it
  could not match, which an operator finishes by hand in the admin.

First wave: `mobile-legends-ru`, `mobile-legends`, `pubg-mobile`. The rest follow the same recipe
with no code change. No sourcing rule is touched: NOVA stays a reserve until an operator switches
a SKU to it.

## 7. Testing

- **Contract (respx), `tests/contract/test_nova_client.py`:** auth header, the `ok:false`-on-200
  refusal, cursor paging, the 403 `subscription_inactive` shape, `validate-id` success/negative/422,
  `check-login`, and `create_topup_order` sending `Idempotency-Key`.
- **Unit, `tests/unit/test_nova_fulfiller.py`:** every row of the money table in §4.2; the unknown
  status staying `in_progress`; field mapping; the missing-mapping refusal. Supplier adapters carry
  a ≥95 % coverage gate (AGENTS.md §8).
- **Unit, `tests/unit/test_player_check_nova_fallback.py`:** primary `valid`/`invalid` never call
  NOVA; primary `error` + NOVA `valid` → `valid` with the name; NOVA `invalid` → `error`; region
  mismatch → `error`; a brand absent from the table → `error` with no call; breaker open → no call;
  the Steam branch's `can_refill` both ways; the cache namespace.
- **Integration:** two active mappings on one SKU resolve deterministically to the older one
  (§4.4); `force_supplier = nova` is refused without a mapping and accepted with one.
- **Money-outcome matrix:** NOVA added to `tests/unit/test_supplier_money_outcome.py`.

No test places a real order: the balance is zero and the order object is unverified. §10 says what
the first funded order has to confirm.

## 8. Documentation

- ADR-0081 — NOVA as a reserve supplier and a player-check fallback (records §4.5's "never
  `invalid`" rule and §4.4's ordering fix).
- `docs/runbooks/nova.md` — funding, how to switch a SKU to NOVA and back, the reconcile job, what
  the first live order must confirm, what to do when the check misbehaves (the kill switch).
- `docs/product/flows/player-check.md` — the fallback in the sequence diagram.
- `docs/architecture/cache-keys.md` — the two `playercheck:nova:*` namespaces.
- `docs/architecture/module-map.md`, `fulfillment/README.md`, `sourcing/README.md` — one line each.
- `docs/runbooks/merchant-b2b.md` — the reseller-facing note that `validate/player` now survives a
  G2B outage for some brands.

## 9. Rollout

1. Merge the branch; deploy api + scheduler + admin.
2. Owner adds `NOVA_API_KEY` to the prod env and funds the NOVA balance (it is `$0.0000`).
3. Verify the check fallback first — it is the half that cannot spend money: set the key, confirm
   a brand in the table still answers `valid` while G2B is healthy (the fallback must not fire),
   then confirm `nova:player_check` stays closed in the logs.
4. Run the mapping seed; review its unmatched list.
5. Place **one** real order on a cheap denomination through `force_supplier = nova` on a test SKU,
   and record the order object's real shape in the runbook (§10).
6. Only then is NOVA a switchable reserve for the rest of the catalogue.

## 10. Open questions

- **What does `region` mean for `mobile_legends`?** The one observed answer was `region: "Russia"`
  for an account that validates against our RU brand. Whether their single category also validates
  global accounts — and what `region` says for one — is unknown, and it is why the global MLBB
  brand has no fallback yet. The test that settles it is one known-global MLBB id; a customer id
  from our own orders must not be used for it.
- **What does their order object look like?** Untyped in their spec, and we have never had one.
  Step 5 of the rollout records the real keys and statuses; the `_status_of` / `_order_id_of`
  warning logs are there to make that cheap.
- **Which way does their idempotency go?** §2. Until a live retry is observed, a 409 is `UNKNOWN`.
- **Which PUBG tier and which Free Fire region** match what we sell. An operator answers both by
  comparing denominations and prices when the seed prints its table.
