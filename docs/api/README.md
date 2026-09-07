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
- Errors are RFC 7807 `problem+json` with stable `type` URIs — with the
  exceptions listed under "Validation errors" at the end of this file.
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

## Merchant outgoing webhooks — configuration (M3a)

`PUT /admin/merchants/{id}/webhook` points a merchant's webhook at a URL and
returns its signing secret **once**; `POST .../webhook/rotate-secret` mints a
replacement (also once); `DELETE .../webhook` disables it by setting
`disabled_at`; `GET .../webhook` returns the configuration plus the delivery
worker's health counters and has no `secret` field in its response model at
all. All four are admin-gated, and the three writes replay through per-resource
scopes (`merchants.webhook_set:{id}`, `…_rotate:{id}`, `…_disable:{id}`) with
the same `secret: null` snapshot rule the key mint uses.

One endpoint per merchant in v1 (unique on `merchant_id`), so `PUT` is an
upsert: the first call mints the secret, a later one edits the URL of the same
row and answers `secret: null` — changing where deliveries go must not silently
break a working verifier. Two operators saving at once (or one double-clicked
Save) both miss the pre-check and both insert; the loser resolves the
uniqueness violation by returning the **winner's** row with `secret: null`
rather than a 500 — the winner minted the key, so a second secret here would
sign nothing. Setting a URL also clears `disabled_at` and resets
`failure_streak`, which is how a hook the delivery worker auto-disabled is
brought back. The URL must be `https` with a public host, checked at save time
by the same validator the catalog's image URLs use; that check reads notation,
not resolved addresses, so it is not the DNS-rebinding control.

**There is deliberately no `/merchant/v1` write for this.** Configuration is
admin-only in M3a by owner decision and moves to the merchant's own cabinet in
M4: the only thing a machine-API write would buy is letting a stranger aim our
worker at an address of their choosing. Until M3a's delivery worker lands, a
configured endpoint is stored and not called — poll the order read.

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
would force somebody else's integration to move for our reasons.

Every endpoint sits behind `merchants.auth.merchant_auth` — `401` unsigned,
`403` `merchant_frozen` — and **none of them takes `Idempotency-Key`**. Four of
the five are reads, which is outside AGENTS.md §9's scope; `POST
/merchant/v1/orders` is a mutation and is exempt on purpose, being idempotent
on the caller's own `merchant_order_id` instead (spec §9.3, recorded as the
exception in AGENTS.md §9). All five endpoints landed by M2 Task 5. Spec §9.1
sketches a sixth row, `POST /merchant/v1/validate/…`, deliberately left out of
v1 — it is honest only for the SKUs a real player-check provider covers, and
the spec's own qualifier is "never a fake approver".

`GET /merchant/v1/me` returns `{merchant_id, title, status, balance_usd}`.
The balance is the deposit ledger's signed posting sum, read live; there is no
balance column to drift from it.

`GET /merchant/v1/catalog` returns brands → products → SKUs where
`brand.visible_b2b AND sku.visible_b2b` **and** the SKU is sellable. Retail
`active` is deliberately not read — it is the storefront's switch, and the
B2B flags (migration 0068) are the merchant catalog's. Three things make a SKU
unsellable, and each makes it **absent rather than cheap**:

- no `cost_usdt` — `pricing.effective_cost` returns `None`, meaning "not
  sellable B2B" (spec §8.2);
- a price that fails `pricing.violates_margin_floor`. Nothing floors
  `b2b_markup_pct` (the schemas accept `ge=-999.99` and 0068 adds no `CHECK`,
  deliberately — spec §8.3 makes the floor an application guard), so `0.5`
  typed for `5` would publish a SKU every order then refuses, and `-100`
  would publish a **free** one. Applying the floor here as well as at order
  time makes the two agree by construction. The withheld codes are logged
  once per request as `merchant_catalog_below_margin_floor`;
- `variable_amount` — the customer picks the amount, so `price_usd` on the row
  is not a price and cost × markup has nothing to work on. The order path
  refuses these with `item_unavailable` / `variable_amount`.

What is deliberately **not** filtered here is the difference worth
understanding: retail `active`, brand maintenance and supplier stock all move
between a merchant's poll and their order, so the order path is where a
merchant learns about them and a catalog absence would only be stale in the
other direction. `variable_amount` is a permanent structural property of the
SKU, which is why it belongs in the `WHERE` clause and they do not.

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
of spec §8.4's rule: drift within ±2% executes at **our** current price,
beyond it is `422 price_changed` carrying `current_price`. The band is an
accept/reject tolerance, never a bid — the merchant's number decides whether
the order proceeds and never what it costs.

The rule used to take the **lower** of the two, which is what spec §8.4 said
as written; the owner amended it on 2026-09-07 (ADR-0069's amendment, and the
reasoning in full at `pricing.price_to_charge`) because `/catalog` is
live-computed and never cached, so a merchant could read our price and always
send `current × 0.98` for a guaranteed 2% off wholesale — about 31% of the
margin at the default 7% markup, unbounded by `violates_margin_floor` (which
is evaluated on our price, before the drift rule, and never re-checks what was
charged), and invisible afterwards because no order stores what the merchant
quoted. It landed now, at zero integrators, for the same reason the `detail`
retyping did: after a pilot integrates it would be a `/merchant/v2`.

The margin floor is the same `pricing.violates_margin_floor` against the same
`settings.merchant_margin_floor_pct` the catalog applies, so a SKU the price
list withholds is a SKU this refuses.

The deposit debit is `merchants.deposit.charge_deposit`: `C merchant_deposit /
D house_payments_received` (the module README's posting table, not re-derived),
ledger key `merchant-order:{order_id}`, and `SELECT … FOR UPDATE` on the
deposit row before the balance is read. **That lock is the overdraw guard**;
the earlier balance read in the order path exists only to answer a clean
`409 insufficient_deposit` before any row is written.

**Fulfilment is always enqueued, never inline.** The call site passes
`start_for_order` a settings copy with `fulfilment_async` forced on
(`merchants/orders.py::_enqueue_only`), regardless of the deployment's flag —
which defaults off in code, whatever a given environment sets (production
sets it on; staging and a fresh deploy do not). With it off `process_task` runs
the supplier purchase inside this transaction, and it catches only
`FulfillerError` / `FulfillerNotIntegratedError`: anything raising after the
supplier is paid and before the commit rolls back the order, the debit and the
delivery while the supplier keeps the money, and the merchant then retries the
same `merchant_order_id` per our own contract, finds nothing, and buys it
twice. AGENTS §10 forbids synchronous external HTTP in a request handler for
this reason. Enqueue-only is contract-compatible today — the endpoint already
answers `status: "fulfilling"` and already tells resellers to poll — and the
two failure modes are not comparable: a stalled worker leaves an order visibly
`fulfilling` with the money correctly debited and everything recoverable. The
operational consequence (the merchant channel depends on the worker being up,
always) is in `docs/runbooks/fulfillment-queue.md`. Retail still follows the
flag.

Errors, all RFC 7807 with a `code`: `404 item_unavailable` (with a `reason` —
`unknown_sku`, `not_b2b_visible`, `out_of_stock`, `not_for_sale`, `no_cost`,
`variable_amount` — because the catalog does not consult stock and this is
where a reseller finds out), `422 price_changed`, `422 margin_floor`,
`409 insufficient_deposit`, `409 order_id_reused`, and `409 order_conflict` —
`create_order`'s residual write conflict, which now carries a code because it
surfaces on a machine surface whose published table discriminates every 409 by
one. The full table is in
`apps/api/src/yupay/modules/merchants/README.md`, which is the contract third
parties implement against.

**A merchant order never sends mail** (spec §9.5).
`notifications._delivery_recipient` returns `None` for one by an explicit
guard, not by falling off the end of a chain of NULL columns — every address
column happens to be NULL on a merchant order today, and "true by accident" is
not a rule. Nor does it publish to realtime: `user_id` is NULL by
construction.

### `GET /merchant/v1/orders/{merchant_order_id}` — the order read

Status, timeline, failure reason, refund mark and **the delivered voucher
code**. That last one is deliberate and is the reason this endpoint is the
reseller's delivery channel rather than a convenience: M3's
`order.status_changed` webhook (spec §10) will not carry the code, because a
webhook body lands in the receiver's logs and in ours and a voucher code is a
bearer instrument. A pull, over a signed request, scoped exactly like the
order. Drawn in
`docs/architecture/sequence-diagrams/merchant-order-read.mmd`.

The route's `:path` convertor is **greedy** — it compiles to `.*`, so
`/merchant/v1/orders/a/b/c/d` matches this handler and answers
`order_not_found`. Nothing else lives under `/orders/` today, but M3's
`/orders/{id}/refund` must be registered **above** it or Starlette will swallow
it silently (first full match in declaration order). Noted at the route and in
the module README's file map.

An id that could never have been stored — anything outside
`^[\x21-\x7e]{1,128}$`, the schema `POST /orders` writes through — is refused
before the database, with the same `404 order_not_found`. That keeps the "one
fewer 422 shape" argument intact and closes a real hole: the segment arrives
percent-decoded, so `GET /merchant/v1/orders/%00null` used to reach Postgres as
an invalid UTF-8 byte sequence and come back a bare **500**. No leak, but a
burnt connection and a rollback per request, trivially scriptable by an
authenticated merchant. Everything else thrown at the route (`..%2F..%2Fme`,
`a/b/c/d`, a 4000-character segment) already answered 404; only NUL escaped,
which is the shape of a check that was never written rather than one that was
wrong.

**The path segment is percent-decoded; the signature is not.**
`merchant_order_id` is `^[\x21-\x7e]+$`, which **includes `/`** (0x2F) — the
auth section's own worked example is `/merchant/v1/orders/my%2Forder`. So the
route is declared with Starlette's `:path` convertor
(`/orders/{merchant_order_id:path}`) and the decoded segment is matched against
the stored value. A plain `{param}` compiles to `[^/]+`, which would `404`
every order whose id contains a slash — and only those, which is why it is the
kind of bug that passes every test written with an id somebody made up. The
convertor changes nothing else: FastAPI's `path_format` still renders
`{merchant_order_id}` in the OpenAPI schema, and `auth.request_target` signs
the raw request line either way. Sign the bytes, match the value.

**Cross-merchant isolation is the security property here.** The lookup is
`orders.find_merchant_order(merchant_id=…, merchant_order_id=…)` — the same
scoped read the order path uses for its replay check — and the merchant half
comes from the signature, never from a parameter. An order belonging to another
merchant answers with the byte-identical `404 order_not_found` a nonexistent id
gets: a distinguishable "not yours" is an oracle, and a reseller could walk a
competitor's order numbering and read their volume off the status codes.

Three things are deliberately withheld. Event payloads: `order.paid`'s carries
the replay fingerprint of the reseller's own request and `order.failed`'s an
operator's free-text note, so the timeline is `{event, at}` and the kinds are an
allow-list (`order_events` is a general audit log and also holds
`admin.deliveries_viewed`, which records which operator read a customer's
codes). Supplier identity: the delivery artifact goes through
`fulfillment.buyer_safe_artifact` — the storefront's own allow-list, **moved
from `fulfillment/routes.py` into `fulfillment/service.py`** in this task so the
two surfaces share one list rather than two that drift in the dangerous
direction (a field added to one and not the other defaults to _visible_ on the
one that forgot it). And supplier errors: `failure_reason` is a closed
vocabulary, `fulfillment_failed` or `order_failed`.

`failure_reason` reads the **order item's** `fulfillment_state`, not the
fulfilment task's, and that inherits a rule rather than inventing one: when a
supplier refuses for lack of _our_ balance the task goes `failed` but the item
stays `in_progress` on purpose, so the storefront keeps saying "обработка"
while an operator tops up and retries. Telling a reseller "failed" there would
have them refund their end customer for an order we are about to deliver.
Anything the storefront shows as an error, this shows too — no more, no less.

`refunded_usd` is summed from the ledger (the debit legs on the merchant's
`merchant_deposit` for transactions referencing this order), not stored on a
flag. It reads a **direction, not an intent**, which is deliberate — it does
not have to know the name M3 gives a refund — so whatever M3 posts against the
order lands here without a contract change. The README therefore describes it
as "money that came back on this order" rather than as a refund.

It is `"0.00"` for every order today, and the reason is stronger than "refunds
are unbuilt": **no surface can book a transaction against an order's deposit at
all.** `POST /admin/merchants/{id}/deposit-credits` — the manual settlement
support performs for a failed delivery — posts
`reference=(merchant, merchant_id)`, not `(order, order_id)`, so it moves
`balance_usd` and appears on `/transactions` while leaving `refunded_usd` at
zero. `docs/runbooks/merchant-b2b.md` spells out the manual settlement with
that consequence attached, so an operator does not tell a merchant to look for
it on the order read.

### `GET /merchant/v1/transactions` — the deposit ledger

One page of the calling merchant's deposit movements, newest first, with a
signed `amount_usd` that sums to `/me`'s balance. Scoped by the authenticated
identity; no parameter names a merchant, and a cursor lifted from another
merchant's page is a timestamp, not a capability.

The grouped ledger sum is `merchants.deposit.list_deposit_transactions` —
M1's, written for the admin panel and **shared, not copied**: a second
normal-side-signed sum over the same postings is a second chance to get a
direction backwards, and two surfaces disagreeing about a merchant's ledger is
a bug discovered by an invoice. A bounded second statement maps the page's
`order` references back to each reseller's own `merchant_order_id`, one `IN`
over at most `limit` ids — pinned by a query-count test that pages 2 rows and
200 and asserts the counts are equal.

**Paging is keyset, not OFFSET, and this is a correctness property rather than
a performance one.** This ledger is written while it is read — the merchant
pulling a statement is the merchant placing orders — and every order appends a
row at the _head_ of a newest-first list. With `OFFSET`, one insertion between
page 1 and page 2 shifts every row down one and page 2 re-serves the last
charge of page 1, silently. The cursor is the last row's
`(created_at, transaction_id)` — the exact tuple the listing orders by, unique
because `id` is the primary key — compared as a SQL row value, so "older than
that row" is a fact about the data that no insertion can move. Rows created
after a walk begins are newer than its first page, which is the right answer
for a statement: the next poll picks them up. Falsified in the suite by
swapping the keyset for an OFFSET, which leaves the plain walk passing and
fails only `test_a_row_written_mid_walk_neither_skips_nor_repeats_an_older_one`.

State the guarantee precisely, because it is not "exactly once under every
interleaving". `WalletTransaction.created_at` is
`server_default CURRENT_TIMESTAMP`, which in Postgres is transaction _start_,
not commit, so a long-running transaction can commit a row that sorts inside a
range a walk has already passed. What holds is **exactly-once against
insertions at the head** — every ordinary write to this ledger, since an order
charge commits in milliseconds — which is strictly better than OFFSET, whose
blind spot is the same _plus_ the shift. Anything stronger needs a commit-order
sequence this ledger does not have, and a statement API does not need one: a
poller comes back.

`limit` is 1–200 and out of range is a `422`, matching the admin ledger route's
stated rule rather than clamping. A cursor we cannot read is
`422 invalid_cursor` — its own code because it is the one parameter a client
builds from our own output. Both parameters are in the query, so both are
covered by the signature (the raw query is the **fourth** of the canonical
string's five fields, and this endpoint is the first to exercise it).

**`decode_cursor` validates both halves, it does not merely parse them**, and
that is load-bearing rather than defensive: everything surviving it is bound
straight into a SQL comparison against a typed column. The id half must be a
UUID and is returned in **canonical** form (`UUID()` also accepts braced,
undashed and `urn:uuid:` spellings, which would parse and then fail one layer
down); the timestamp must be timezone-aware, because `created_at` is
`timestamptz` and every cursor we issue carries an offset. Without the UUID
check a _truncated_ cursor — a reseller's `VARCHAR(88)` column, a line-wrapped
URL in a retry — reached `uuid < $2`, asyncpg raised `DataError`, and it
escaped as a **500** from an endpoint whose published contract promises a
recoverable 422. That is the same class as the missing app-wide
`RequestValidationError` handler — since closed for this prefix, see
"Validation errors" below — one notch worse (a 500, not a non-conforming 422
body), and unlike the handler it was not pre-existing.

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

## Validation errors: problem+json under `/merchant/v1`, FastAPI's body elsewhere

"Conventions" above says errors are RFC 7807. That holds for every `AppError`
— `core.errors.app_error_handler` renders those. It does **not** hold for
`RequestValidationError`, which FastAPI raises before any of our code runs and
answers with `{"detail": [ … ]}` at `422`, `application/json`, no `type` and no
`code`.

That was fine while the only consumers were our own frontends. `/merchant/v1`
is the first surface whose error table is a **published contract**, so
`core.errors.problem_json_validation_handler` now renders those failures as
problem+json — `code: "invalid_request"`, a string `detail` summarising the
first few failures, and FastAPI's per-failure entries under a new `errors` key
rather than retyping `detail`. Two cases reach it in practice:
`GET /merchant/v1/transactions?limit=0` (or above 200), and any body
`machine_schemas.MerchantOrderCreateIn` rejects.

**It is registered app-wide and scoped in effect: every path outside
`/merchant/v1` is delegated to FastAPI's own handler, byte for byte.** The
scope is matched by path _segment_ — the path must equal the prefix or begin
with the prefix plus a slash — so a future `/merchant/v1beta` or
`/merchant/v10` does not inherit a published contract by being spelled like
this one. Two reasons the delegation is there, and the first is what would
make an app-wide replacement a mistake rather than a simplification:

- **The generated client would be silently falsified.** FastAPI documents every
  route's 422 as `HTTPValidationError`, and
  `packages/api-client/src/generated/types.gen.ts` types every operation from
  it. Changing the runtime body without changing the schema makes the client
  wrong for nearly every endpoint in the repo — and `openapi-drift` cannot
  catch it, because the schema has not moved. (For the merchant prefix the
  schema _does_ move: `machine_routes._VALIDATION_PROBLEM` overrides the 422
  response with the problem+json media type, so `openapi.json` and the client
  both follow. The generated client now types the merchant operations' error as
  the problem shape and every other operation's as `HTTPValidationError` —
  which is exactly the split.)
- **The storefront and admin SPA already read `detail[]`.** Retyping it is a
  breaking change to them for no gain.

The handler encodes `exc.errors()` with `jsonable_encoder` rather than handing
it to `json.dumps`: a `value_error` entry carries the original exception object
under `ctx["error"]`, so a naive version raises `TypeError` and turns a clean
422 into a 500 — on a non-UUID `sku_id`, which is one of the likeliest
integrator mistakes. `tests/integration/test_validation_problem_json.py` pins
the delegation byte for byte, the neighbouring prefixes that must not be in
scope, the problem+json body, and the `ctx` encoding;
`test_a_malformed_body_answers_problem_json_and_not_a_500` and
`test_an_out_of_range_limit_answers_the_published_error_shape` pin the two HTTP
cases.

Two answers still get past `app_error_handler`, both deliberately:

- **An unhandled exception.** Starlette's `ServerErrorMiddleware` answers a
  bare `Internal Server Error` as `text/plain`. Nothing raises the `AppError`
  base class directly, so `https://app.yupay.uz/errors/internal` is a type URI
  no response actually carries today.
- **slowapi's `429`.** `_rate_limit_exceeded_handler` writes its own body.
  `/merchant/v1` is exempt from that tier
  (`bootstrap._exempt_self_authenticating_routes`) precisely so its 429s stay
  problem+json; `/api/v1` is not, so the storefront's throttle body differs in
  shape from every other error it can return.
- **Routing's own `404` and `405`.** A path no route serves, or a method no
  route serves on a path some route does, is answered by FastAPI as
  `{"detail": "Not Found"}` / `{"detail": "Method Not Allowed"}` before any
  dependency runs — so on `/merchant/v1` they arrive without authentication
  having been attempted, and outside the published error table by
  construction. The merchant README says so in its error section.
