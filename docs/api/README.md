# YuPay API

The single source of truth for the API surface is **`docs/api/openapi.json`**, regenerated
by CI on every PR from the FastAPI app via `make gen-api`. Don't hand-edit it.

## How the schema flows

```
apps/api  ──▶  FastAPI.openapi()  ──▶  docs/api/openapi.json
                                       │
                                       └──▶ @hey-api/openapi-ts ──▶ packages/api-client/src/generated/
                                                                     ▼
                                                       imported by apps/web and apps/miniapp
```

## Conventions

- All endpoints live under `/api/v1/`. Webhooks live under `/webhooks/{provider}` (no auth
  header — signature-verified instead).
- JSON only; `snake_case` keys; ISO-8601 timestamps; cursor pagination
  (`?cursor=...&limit=...`).
- Errors are RFC 7807 `problem+json` with stable `type` URIs.
- All write endpoints accept an `Idempotency-Key` header (>=16 chars). Enforced today on
  `POST /orders`, `POST /payments/intents`, `POST /admin/payments/{id}/refund` —
  **missing/short key → 422**; a repeated key replays the original result.
- Money is `{ "amount": "12345.678", "currency": "USD" }` — strings to preserve precision.

## Content-managed brand SEO copy

Brand marketing copy — `brand_translations.highlights` (the value-prop chips), plus
`short_description` / `description` / `instructions`, and the `brand_faqs` — is **content,
not fixtures**. It is not populated by `scripts/seed.py` and not shipped as an Alembic data
migration. It lives in idempotent seed SQL under `scripts/seed/` and is applied by an operator
(psql), gated by the standing deploy rule.

The `steam` brand's pack is `scripts/seed/steam_seo.sql` (ru/en/uz): it `UPDATE`s the three
`brand_translations` rows in place and rebuilds the FAQs via delete-then-insert, all inside a
single transaction. Re-running yields identical content. It depends on migration
`0032_brand_highlights` (adds the `highlights` column) being applied first.

## Auth

| Surface                     | Header                                                          |
| --------------------------- | --------------------------------------------------------------- |
| Web (logged-in user)        | `Authorization: Bearer <access-jwt>`                            |
| Web (guest checkout)        | `Authorization: Guest <guest-token>`                            |
| Telegram Mini App           | `Authorization: tma <raw initData>` (HMAC-verified server-side) |
| Service-to-service (future) | `Authorization: Service <signed-jwt>`                           |

## WebSocket

`POST /api/v1/realtime/handshake` (normal `Authorization: Bearer <access-jwt>` auth) mints a
60-second, single-purpose `kind="ws"` token scoped to the caller's own channel
(`channel="user:{id}"`). The client then opens
`wss://api.yupay.uz/api/v1/realtime/ws/orders?token=<ws-token>` — the browser `WebSocket` API
can't set headers, so the token rides the query string (60s TTL; tradeoff documented in
`docs/security/threat-model.md` and ADR-0040). The server verifies the token, subscribes the
socket to the Redis pub/sub channel `realtime:user:{id}`, and forwards every published message
plus a 25-second keepalive ping. The protocol is a discriminated-union JSON envelope; see
`packages/api-client/src/realtime/messages.ts`.

This endpoint pair doesn't fully show up in `openapi.json`: OpenAPI 3.1 has no WebSocket
operation object, so FastAPI omits `@router.websocket(...)` routes from the generated schema —
only `POST /realtime/handshake` (a normal HTTP route) appears there and regenerates like any
other endpoint. Guests never connect (`useOrderSocket` mounts only for a logged-in user, and
`publish_order_event` no-ops for guest orders), so guest checkout keeps polling
`GET /orders/{id}` unchanged. See `docs/decisions/0040-order-realtime-ws.md` and
`apps/api/src/yupay/modules/realtime/README.md`.

## Webhooks per provider

| Provider | Path                          | Signature header                                                   |
| -------- | ----------------------------- | ------------------------------------------------------------------ |
| Stripe   | `/webhooks/payments/stripe`   | `Stripe-Signature`                                                 |
| PayPal   | `/webhooks/payments/paypal`   | `PAYPAL-AUTH-ALGO` + `PAYPAL-CERT-URL` + `PAYPAL-TRANSMISSION-SIG` |
| YooKassa | `/webhooks/payments/yookassa` | IP allowlist + HMAC over body                                      |
| Click    | `/webhooks/payments/click`    | HMAC over body                                                     |
| Payme    | `/webhooks/payments/payme`    | Basic auth + signed payload                                        |
| Uzum     | `/webhooks/payments/uzum`     | HMAC over body                                                     |
| Crypto   | `/webhooks/payments/crypto`   | HMAC over body                                                     |

Each webhook is documented in detail in `apps/api/src/yupay/modules/payments/gateways/<provider>.py`
(docstring on the gateway class).

## Reviews

Public: `GET /reviews/brands/{slug}` (published reviews + aggregate, keyset
`cursor`), `POST /reviews` (body `{order_id, brand_slug, rating, body?}`;
**requires `Idempotency-Key`**; a repeat for the same `(order, brand)` returns
`409 already_reviewed` — the client treats that as "already submitted"),
`GET /reviews/mine`, `POST /reviews/{id}/report` (auth, Idempotency-Key).
Admin: `GET /admin/reviews?status=&reported=` + `POST /admin/reviews/{id}/{hide,unhide,remove}`
(each requires `Idempotency-Key`; the actions are naturally idempotent). Catalog
brand DTOs (`GET /catalog/brands`, `/catalog/brands/{slug}`) carry an optional
`rating: {avg, count}`. See `docs/decisions/0039-reviews-and-ratings.md`.

`POST /reviews` accepts **either** a logged-in user (`Authorization: Bearer
<access-jwt>`) **or a guest** (`Authorization: Guest <guest-jwt>` +
`X-Guest-Email: <email>`) — the same dual-actor resolution
(`resolve_request_actor`) as guest order-view (see the Auth table above); the
guest JWT's `email_hash` claim is cross-checked against the `X-Guest-Email`
header server-side. `GET /reviews/mine` and `POST /reviews/{id}/report` stay
Bearer-only — a guest cannot list their reviews across orders or report
another review. Web only; the Mini App has no guest checkout.

`GET /reviews/eligibility?order_id=<id>` runs the same actor resolution as
`POST /reviews` (Bearer or Guest+`X-Guest-Email`) against the given order and
returns `{brand_slug: string | null, delivered: boolean, already_reviewed:
boolean}`, letting the client gate a "rate your purchase" CTA/form without a
failed POST. `guest_email` is a capability credential only — it is never
returned in any reviews response body and never logged.

## Steam gifts catalog

`GET /gifts/catalog`, `GET /gifts/catalog/hot`, `GET /gifts/catalog/{app_id}`,
`GET /gifts/catalog/{app_id}/dlc` — a live, Redis-cached proxy of G-Engine's
`/gifts/*` catalog (~4 200 Steam games/DLC, region-priced). **No auth** —
same posture as the rest of public catalog browsing. **No dedicated rate
limit bucket** — the app-wide slowapi defaults apply, same as
`catalog/routes.py`.

**404 while disabled.** Every route under `/gifts/*` is gated by a single
router-level dependency on `STEAM_GIFTS_ENABLED` — while the flag is off
(the default) the whole surface answers `404`, not an empty list, so a
client can't distinguish "no results" from "feature not live" by design.
A new route added under this router inherits the guard automatically; see
`docs/runbooks/steam-gifts.md` for the flip procedure.

**Cache behaviour.** Every read goes through a `stale-while-error` Redis
cache: a fresh key (15 min for detail/search, 1 h for the default listing
and hot offers) is tried first, then G-Engine, then a same-shaped stale
key that outlives the fresh one by 24 h on an upstream failure, and only
then a `502`. A sustained run of `gifts.catalog_stale` log lines (see the
runbook) means G-Engine has been down long enough that the storefront is
showing day-old prices. Money on every DTO here is a `str`, not a
`Decimal` (AGENTS.md §9); `price_uzs` is `null` whenever FX was
unavailable for that request rather than a guessed conversion. Every
`gifts:*` Redis key is documented row-by-row in
`docs/architecture/cache-keys.md`.

Checkout for a Steam gift is not a separate endpoint — it rides the
normal `POST /orders`/`POST /payments/intents` pair with `sku_code:
"steam-gift"` and a `fulfillment_data` payload of `{app_id, package_id,
region, invite_url}` (the Telegram-Stars dynamic-SKU pattern, ADR-0054).
The server re-derives the price from the same cache above and only
accepts the client's quoted `amount_usd` within a ±2% tolerance band,
refusing (`422`, `extra.expected_amount_usd`) otherwise — see
[ADR-0066](../decisions/0066-steam-gifts-live-catalog.md) and
`docs/product/flows/steam-gifts.md`.

**`POST /gifts/steam-profile` `{invite_url}` — the pre-purchase recipient
check.** Before paying, the buyer presses «Проверить» next to the pasted
Steam link and sees the recipient's avatar and nickname, so a mistyped link
stops being an unrecoverable paid mistake. Server-side only: Steam sends no
CORS headers for our origin. Unlike the rest of this router, this endpoint
**does** carry its own `guard_ip` bucket (`"gifts-steam-profile"`) — it
proxies a third party on the public internet.

**A `POST` for what is logically a read, deliberately.** The link identifies
a _third party_, and the `api.yupay.uz` site block in `Caddyfile.prod` writes
an access log whose `uri` field records the query string verbatim, which
promtail ships to Loki — so `GET ...?invite_url=steamcommunity.com/id/{vanity}`
would put a recipient's identity in the logs, in the one module that goes out
of its way to log only a hash of that identifier. Filtering at the edge was
rejected: an unrelated Caddy edit undoes it silently, and it only ever covers
the place we remembered. Nothing is lost — the endpoint is not bookmarkable
and its caching is server-side in Redis. It writes nothing, so like
`POST /catalog/products/{id}/check-player` (the other advisory identity
lookup here) it takes **no** `Idempotency-Key`.

`invite_url` is validated and
canonicalised by the exact same `gifts.checkout.parse_invite_url` checkout
itself uses, so a link this endpoint accepts can never be rejected at
checkout and vice versa; an unrecognised shape is a `422`, same as checkout.

Response is `GiftProfileOut { status, steam_id, nickname, avatar_url }` with
`status` one of `found | not_found | unsupported | unavailable`. Only
`"not_found"` — Steam's own definitive "no such profile" — is meant to block
the buyer, and it comes from exactly two answers. For an `/id/{vanity}` link:
`ResolveVanityURL` reporting the documented `success: 42` ("No match") — any
other non-`1` value is an undocumented condition on Steam's side and reads as
`"unavailable"`. For a `/profiles/{steamid64}` link: `GetPlayerSummaries`
returning an empty `players` array, which is the only existence check that
shape ever gets. An empty `players` on the _vanity_ path is deliberately
**not** `not_found` — `ResolveVanityURL` has just certified that account, so
the two Steam services contradict each other rather than agreeing on a
negative, and a vanity that truly does not exist was already caught one call
earlier. The one verdict that hard-blocks a paying buyer earns the strictest
evidence.
The frontend treats `"found"`, `"unsupported"` (an `s.team` friend-invite
link, which the Web API cannot resolve at all — no Steam call is made for
that shape), and `"unavailable"` (no API key configured, Steam unreachable,
timed out, a response whose shape we could not trust, a player row carrying
neither a name nor an avatar — a `found` with nothing to render confirms
nothing — or the vanity contradiction above) identically: let the sale
proceed.
`found`/`not_found` verdicts are cached 6h under `gifts:steam_profile:*`
(never `"unavailable"` — that is our failure, not a fact about the
profile); see `docs/architecture/cache-keys.md`. `steam_id`/`nickname`/
`avatar_url` are PII and never reach the structured logs.

Admin: `GET`/`PATCH /admin/gifts/settings` (margin percent, region
config) — `PATCH` requires `Idempotency-Key`; a repeated key replays the
first response.

## Guest delivered-code access (magic link)

`GET /orders/{id}/deliveries` returns the order's delivered voucher/gift codes.
A logged-in owner uses `Authorization: Bearer <access>`. A **guest** must present
an order-scoped `guest_order` token (`Authorization: Guest <jwt>` + `X-Guest-Email`)
— **not** the freely-mintable email-only `guest` token, which no longer unlocks
codes. The `guest_order` token is minted server-side and delivered as the `?access=`
param of the link in the order's delivered email; it names the exact `order_id` it
unlocks, so knowing the buyer's email is not enough to read another order's codes.

`POST /orders/{id}/code-access` (body `{email}`) re-mails a fresh magic link + the
codes to the **order's own address**. It is **non-enumerating** (always `204`,
per-IP `guard_ip` throttled) and never mails the caller's input, so it cannot
exfiltrate codes to an attacker-controlled address. See
`docs/decisions/0042-guest-code-access-magic-link.md`.

## Merchant B2B admin (M1)

`/admin/merchants` (create, list-with-USD-balance, freeze/unfreeze,
deposit-credits, and the read-only per-merchant deposit ledger at
`GET /admin/merchants/{id}/transactions`) and the catalog B2B knobs (`PATCH /admin/catalog/skus/{id}/b2b`,
`POST /admin/catalog/b2b/bulk-markup`, `PATCH /admin/catalog/brands/{id}/b2b`)
— all admin-gated.

`POST /admin/merchants/{id}/deposit-credits` **requires** `Idempotency-Key`:
the header is the client half of the namespaced ledger key
(`merchant-credit:{merchant_id}:{client_key}`), so a retry replays the original
transaction instead of crediting twice. The ledger replays by key **without
comparing parameters** — the response's `amount` is the replayed transaction's
(original) amount, so a client that resubmits a key with an amended amount can
detect the mismatch. The other writes accept an optional `Idempotency-Key` and
replay via the generic `(scope, key)` store, whose scope is **per resource**
(`merchants.sku_b2b:{sku_id}` and so on) so one reused client key cannot replay
one SKU's response for another. See
`docs/architecture/sequence-diagrams/merchant-deposit-credit.mmd`.

## Merchant machine credentials (M2)

`POST /admin/merchants/{id}/api-keys` mints a key and returns
`{key_id, secret, …}`. **The secret appears in that one response and nowhere
else** — the row holds it **encrypted at rest** (`core/crypto.py`,
XSalsa20-Poly1305 under a purpose-derived key), not hashed: an HMAC cannot be
verified without the key material, so a digest would either forbid request
signing or become the signing key itself. Migration 0070 replaced 0065's
`secret_hash` with `secret_enc`/`secret_nonce`; the table was empty everywhere,
so there was no backfill and no integrator to break. A retry carrying the same
`Idempotency-Key` replays the original `key_id` with `secret: null`, because
`idempotent_responses` has no reaper and a usable credential must not sit there
in the clear; if the first response was lost, revoke and reissue.

`GET /admin/merchants/{id}/api-keys` lists every key ever issued (newest first,
revoked ones included) and its response model has no `secret` field at all.
`DELETE /admin/merchants/{id}/api-keys/{key_id}` sets `revoked_at`, is
naturally idempotent, and matches on `(merchant_id, key_id)` so one merchant's
id in the path cannot revoke another's key.

Requests to the machine API `/merchant/v1` carry `X-Merchant-Key`,
`X-Merchant-Timestamp` and
`X-Merchant-Signature = hex(HMAC_SHA256(secret, canonical))` where

```
canonical = {timestamp}\n{METHOD}\n{raw_path}\n{raw_query}\n{sha256_hex(body)}
```

— the path and query being the **raw, percent-encoded** bytes from the request
line, and the timestamp within ±300 s. A signature is deliberately **not**
single-use — see the module README's "Replay and retries".
**The contract third parties implement against is
`apps/api/src/yupay/modules/merchants/README.md`** — headers, canonical string,
runnable Python and Node examples, the full `type`-URI table, rate limits with
`Retry-After` — and it must not change without a new API version. Unknown key,
revoked key and a wrong signature all return one identical 401.

Application-level `429`s now carry a `Retry-After` header: any `AppError`
whose extras include an integer `retry_after` gets one
(`core.errors.app_error_handler`), which is what the auth IP guard and the
merchant per-key counter set.

## Merchant machine API (M2) — `/merchant/v1`

Mounted at **its own prefix**, not under `/api/v1`: it is a third-party
contract with its own version number, so a breaking change means
`/merchant/v2` rather than an edit, and tying it to the storefront's version
would force somebody else's integration to move for our reasons. Both
Every endpoint sits behind `merchants.auth.merchant_auth` — `401` unsigned,
`403` `merchant_frozen` — and **none of them takes `Idempotency-Key`**. The
two reads are reads, which is outside AGENTS.md §9's scope; `POST
/merchant/v1/orders` is a mutation and is exempt on purpose, being idempotent
on the caller's own `merchant_order_id` instead (spec §9.3, recorded as the
exception in AGENTS.md §9).

`GET /merchant/v1/me` returns `{merchant_id, title, status, balance_usd}`.
The balance is the deposit ledger's signed posting sum, read live; there is no
balance column to drift from it.

`GET /merchant/v1/catalog` returns brands → products → SKUs where
`brand.visible_b2b AND sku.visible_b2b` **and** the SKU is sellable. Retail
`active` is deliberately not read — it is the storefront's switch, and the
B2B flags (migration 0068) are the merchant catalog's. Two things make a SKU
unsellable, and both make it **absent rather than cheap**:

- no `cost_usdt` — `pricing.effective_cost` returns `None`, meaning "not
  sellable B2B" (spec §8.2);
- a price that fails `pricing.violates_margin_floor`. Nothing floors
  `b2b_markup_pct` (the schemas accept `ge=-999.99` and 0068 adds no `CHECK`,
  deliberately — spec §8.3 makes the floor an application guard), so `0.5`
  typed for `5` would publish a SKU every order then refuses, and `-100`
  would publish a **free** one. Applying the floor here as well as at order
  time makes the two agree by construction. The withheld codes are logged
  once per request as `merchant_catalog_below_margin_floor`.

Brands or products left with nothing purchasable are omitted rather than
returned empty. Each SKU carries `{sku_id, sku_code, name, price_usd,
updated_at}`, `price_usd` being _that merchant's_ price from
`merchants.pricing` — the one home for the formula. There are no price
webhooks: merchants poll and watch `updated_at` (spec §8.4). Three SQL
queries whatever the catalog's size, pinned by a test that measures two
catalog sizes and asserts the counts are equal — which catches a per-row
load, not a constant extra query.

**Money is a JSON string with exactly two decimals** on this surface
(`"1.06"`) — `machine_schemas.UsdBalance` and `machine_schemas.UsdPrice`,
separate because a
balance must round **down** (never advertise more than the merchant can
spend) and a price **up** (the direction `pricing.merchant_price` already
uses, so the advertised price can never sit below what the order charges).
The formatting itself is needed regardless: the ledger's `Numeric(20, 6)` sum
would otherwise serialise as `"42.500000"` while an untouched account
serialises as `"0"`, and a machine contract cannot hand a client two shapes
for the same quantity.

### `POST /merchant/v1/orders` — the money path

One SKU per order (spec §9.1's body shape: `merchant_order_id`, `sku_id`,
`expected_price`, `fulfillment_data`); no `qty`, no line array. The whole
flow rides **one transaction** — order INSERT, deposit debit, `paid`,
fulfilment start — so a failure anywhere leaves neither an order nor a debit.
Drawn in `docs/architecture/sequence-diagrams/merchant-order-create.mmd`.

The order is created by `orders.create_order`, **not** a B2B fork of it. The
only difference is a merchant-only `unit_price_usd_override` keyword carrying
the wholesale price: passing it with a non-merchant actor raises, which is
what stops a client-supplied price from ever reaching a retail order through
the same door. `create_order` also refuses an `affiliate_code` on the merchant
arm — `resolve_code` takes `user_id=actor.user_id`, NULL for a merchant, so a
code would resolve like a guest's and take a retail discount off an
already-wholesale price.

`expected_price` is reconciled by `pricing.price_to_charge`, the single home
of spec §8.4's rule: drift within ±2% executes at the **lower** of the two,
beyond it is `422 price_changed` carrying `current_price`. That is the spec as
written, and it is worth knowing what it permits: a merchant can read
`/catalog` (live-computed, never cached) and always send `current × 0.98`,
taking a guaranteed 2% off wholesale. On the default 7% markup that is about a
quarter of the margin, and the margin floor does not catch it. The rule came
from the Steam-gifts flow, where the counterparty is a human; here it is a
machine. Raised with the owner; until they rule, the spec governs, and
changing it is one line in `pricing.price_to_charge`.

The margin floor is the same `pricing.violates_margin_floor` against the same
`settings.merchant_margin_floor_pct` the catalog applies, so a SKU the price
list withholds is a SKU this refuses.

The deposit debit is `merchants.service.charge_deposit`: `C merchant_deposit /
D house_payments_received` (the module README's posting table, not re-derived),
ledger key `merchant-order:{order_id}`, and `SELECT … FOR UPDATE` on the
deposit row before the balance is read. **That lock is the overdraw guard**;
the earlier balance read in the order path exists only to answer a clean
`409 insufficient_deposit` before any row is written.

Errors, all RFC 7807 with a `code`: `404 item_unavailable` (with a `reason` —
`unknown_sku`, `not_b2b_visible`, `out_of_stock`, `not_for_sale`, `no_cost`,
`variable_amount` — because the catalog does not consult stock and this is
where a reseller finds out), `422 price_changed`, `422 margin_floor`,
`409 insufficient_deposit`, `409 order_id_reused`. The full table is in
`apps/api/src/yupay/modules/merchants/README.md`, which is the contract third
parties implement against.

**A merchant order never sends mail** (spec §9.5).
`notifications._delivery_recipient` returns `None` for one by an explicit
guard, not by falling off the end of a chain of NULL columns — every address
column happens to be NULL on a merchant order today, and "true by accident" is
not a rule. Nor does it publish to realtime: `user_id` is NULL by
construction.

**`/merchant/v1` is exempt from the coarse slowapi limiter**
(`bootstrap._exempt_self_authenticating_routes`, which walks the router so
later endpoints are covered on the day they are written). Throttling here is
the dependency's two Redis counters and nothing else. The earlier reading —
that the coarse tier applied but could never bind first, because it buckets
per IP **per endpoint** while the `merchant-api` bucket is one counter for
the whole prefix — is true only when a caller's traffic spreads across
endpoints. With both tiers at 600/60 s, a caller concentrated on one endpoint
advances both counters at the same rate; `limits` allows `count <= limit`
where `ip_guard.hit_counter` returns `count > limit`; and `SlowAPIMiddleware`
runs before any dependency, so they trip on the same request and the
middleware wins it. That caller is the documented one — the module README
tells resellers to poll `/catalog` because there are no price webhooks — and
slowapi's handler body carries no `type` and no `code`, which is a contract
we published and cannot revise inside `v1`. The exemption's argument is the
list's own: every route on it authenticates its own caller, so the per-IP
limit was never the control protecting it.

The full third-party contract, sample bodies included, is
`apps/api/src/yupay/modules/merchants/README.md`.
