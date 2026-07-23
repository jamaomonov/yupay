# 0036. Click Shop API integration

- **Status**: Accepted
- **Date**: 2026-07-23
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | integrations

## Context and problem statement

YuPay needed a fourth acquirer alongside Octo (ADR-0020), Payme (ADR-0034),
and Uzum (ADR-0035): Click, one of the most widely used payment systems in
Uzbekistan, on **both** surfaces — the web storefront (`yupay.uz`) and the
Telegram mini app (`yupayapp_bot`). Click gave us **two services sharing one
merchant** (`merchant_id = 63276`): `service_id 108149` for the web surface,
`service_id 108150` for the bot surface, each with its own `SECRET_KEY`.

Like Payme and Uzum, Click's **Shop API** does not fit our classic gateway
shape (`create_intent` → redirect → provider POSTs one signed webhook →
`verify_webhook` → done, with the provider a passive caller of our generic
`POST /api/v1/webhooks/payments/{provider}` route). Click inverts it the same
way: Click calls **two** plain HTTP endpoints against our server — `/prepare`
(`action = 0`) then `/complete` (`action = 1`) — over the life of a
transaction, as the customer pays in Click Up or on `my.click.uz`. **We own
the transaction state machine** and its idempotency
(`ClickTransaction.status`: `PREPARED`/`CONFIRMED`/`CANCELLED`), the same
ownership model Uzum's Merchant API established (contrast Payme, where
Payme's own protocol state is authoritative).

Two things are genuinely new here, with no exact twin in Payme/Uzum:

1. **Transport.** Click sends `application/x-www-form-urlencoded` POSTs, not
   JSON, and authenticates with an **MD5 `sign_string`** built from the raw
   wire field values — not HTTP Basic auth.
2. **Two independent services sharing one merchant** — a shape neither Payme
   nor Uzum has (each is a single `service_id`/service pair).

## Decision drivers

- `payments.service.settle_provider_payment` (and its
  `cancel_pending_provider_payment` sibling) must stay the single place an
  order moves to `paid`/`cancelled` — Click must not become a fourth code
  path that flips order status or posts the ledger.
- The signature check must hash the **exact raw wire strings** Click sent
  (not a reformatted `Decimal`/`int`) — Click computes its own MD5 over those
  same bytes, so any reformatting here (e.g. re-serializing the amount)
  produces a hash that never matches.
- Money-safety, carried forward from the Uzum final-review Critical: a
  cancel path (negative-inbound-`error`, or the stale-prepare sweep) must
  never claw back a payment a **sibling** transaction on the same order
  already settled — only cancel a payment that is still `pending`.
- The two-service shape must not force two near-duplicate gateway classes or
  two near-duplicate webhook route modules; one module, one gateway class
  parametrised by surface.
- Click's own spec is explicit that a negative `error` **in the request**
  means the merchant must cancel and answer a dedicated code (`-9`) — this is
  a first-class rule, not an incidental edge case, and needed to be modeled
  as such rather than folded into a generic "bad request" branch.

## Considered options

1. **Shop API (two inverted webhooks) + the pay link, both surfaces** —
   implement `/prepare`/`/complete` as a dedicated module mirroring
   `uzum/`'s shape, and route the two Click services through **two**
   `PaymentGateway` provider ids (`"click"` web / `"click_miniapp"` bot).
2. **Click Merchant API** (invoice creation, `/payment/status`, `/cancel`,
   card tokens) instead of the Shop API.
3. **Telegram Bot Payments API** (BotFather provider token, in-Telegram card
   entry) for the mini-app surface instead of the pay link.
4. **Single `click` provider + a `channel` hint** threaded through
   `payments.service.create_intent`, instead of two provider ids, to route
   the two services.

## Decision outcome

**Chosen option: 1 (Shop API, two provider ids)**, implemented as a
**dedicated module**, `apps/api/src/yupay/modules/click/`, structured exactly
like `uzum/`: `models.py` (`ClickTransaction`, migration `0029`), `errors.py`
(`0`/`-1..-9` factories + `to_response()`), `signature.py` (the two
`sign_string` formulas + per-service secret lookup + constant-time verify),
`service.py` (`prepare`/`complete`/`cancel` handlers + `build_checkout_url`),
`routes.py` (form-encoded, always-HTTP-200 JSON, sign + action guards), `api.py`
(public surface). `ClickGateway` (`payments/gateways/click.py`) is
parametrised by `provider: Literal["click", "click_miniapp"]` and registered
twice in `payments/gateways/__init__.py:REGISTRY`.

### Form-encoded + MD5 signature, not JSON + Basic auth (vs. adapting Payme/Uzum's transport)

Click's Shop API contract is fixed by Click, not a choice we get to make: the
official docs and the `click-llc/click-integration-php` reference library
both post `application/x-www-form-urlencoded` bodies signed with an MD5
`sign_string` keyed on a per-service `SECRET_KEY`:

- Prepare: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time)`
- Complete: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + merchant_prepare_id + amount + action + sign_time)`

`signature.py` builds these over the **raw string values exactly as Click
sent them** — no rounding, no re-serializing `amount` through `Decimal` before
hashing — because Click's own MD5 is computed over those same wire bytes. The
route layer reads form fields itself (never a Pydantic request model, so a
missing field is our own `-8`, never FastAPI's automatic 422) and verifies
with `hmac.compare_digest` (case-insensitive, constant-time, fails closed on
non-ASCII input) before any business logic runs. This has no exact precedent
in Payme (HMAC-SHA256 over the JSON-RPC body) or Uzum (HTTP Basic auth) —
it's a new pattern in this codebase, isolated entirely inside
`click/signature.py`.

### Two services sharing one merchant → two gateway providers routed by surface

Click's two services (`108149` web / `108150` bot) each carry their own
`SECRET_KEY`, so a signature check must know up front which secret to try.
Rather than thread a `channel` hint through `payments.service.create_intent`
(option 4) — which would require every other gateway's `create_intent` call
site to also learn about a parameter it never needs — we register **two**
`PaymentGateway` instances under **two** provider slugs, `"click"` (web) and
`"click_miniapp"` (bot), both backed by the same `ClickGateway` class
parametrised by `provider`. Each frontend surface picks its own provider id
at checkout time (the web app's shared payment-method list already maps
`click` → `"click"`; the mini app overrides that one entry to
`"click_miniapp"` at its own checkout call site — see
`apps/miniapp/src/pages/TopUp.tsx`). This keeps `create_intent`'s signature
untouched for every gateway and reuses the exact registry mechanism that
already backs every other acquirer.

On the **inbound** side, this outbound routing choice is irrelevant: `/prepare`
and `/complete` always resolve which secret to verify against, and which
provider the backing `Payment` row uses, purely from the request's own
`service_id` field (`signature.secret_for_service`,
`service._provider_for_service`) — never from which provider slug initiated
the checkout. A customer retrying checkout on the _other_ surface gets its
own pending payment (`_ensure_payment` is keyed by `provider`), never
confused with the first attempt.

### Amounts in soums, compared as `Decimal`

Click's `amount` wire field is soums (major units, e.g. `"1000.00"`) —
**unlike** the tiyin every other UZ acquirer here (Octo, Payme, Uzum) uses.
`order.total_charged` is already whole-so'm-rounded at checkout
(`orders.service._round_to_payable`), so both `service.prepare` and
`service.complete` compare `Decimal(str(amount))` against it directly — never
`* 100`, never a float `==`. A mismatch is `-2` (`Incorrect parameter
amount`), on both webhooks.

### The negative-inbound-`error` → cancel + `-9` rule

Click's docs are explicit: "Upon receiving a negative error code [in the
request], the Merchant must cancel the payment in the billing system and
return error code `-9`." Both webhooks implement this as the **first**
business check after signature/action validation — ahead of any order-state
or amount check — via a single `service.cancel()` helper shared by both
routes and by the stale-prepare sweep (below). `cancel()` is a no-op if there
is nothing to cancel, or the row is already `CANCELLED`; it never touches a
`CONFIRMED` transaction (Click v1 has no merchant-initiated reversal, so a
settled transaction is left alone rather than "cancelled" out from under a
paid order).

**Money-safety guard, carried forward from the Uzum final-review Critical:**
`_ensure_payment` can share one pending payment across several
`ClickTransaction` rows on the same order (a customer retrying checkout on
the same surface). `cancel()` only cancel-pends the backing payment while it
is still `pending` — if a **sibling** transaction already confirmed that
payment (→ succeeded, order → paid) while this one is still `PREPARED`,
cancelling here never claws that back. This is the exact same invariant
Uzum's `/reverse` and its stale-`CREATED` sweep enforce, reused verbatim
rather than re-derived.

### Refund is out of scope (v1) — Click-side only

Click's Shop API has **no merchant-initiated refund/cancel call** at all —
narrower even than Uzum, which at least has a merchant-visible `/reverse`
webhook Uzum itself drives. Reversal for Click happens entirely on Click's
side (their Merchant API `/cancel`, or the merchant cabinet) — out of scope
for this integration (design spec §15). Consequently `ClickGateway.refund()`
always raises `PaymentGatewayError`, mirroring Uzum's `refund()`. There is no
operator-facing "issue a refund" action to build for Click.

### Reuse of the shared payments hooks and the money-safety cancel guard

Every money-moving effect in this module — `settle_provider_payment` on
`/complete`, `cancel_pending_provider_payment` on the negative-error path and
the stale-prepare sweep — funnels through the exact same `payments.service`
functions Octo, Payme, Uzum, and admin refunds already call. Nothing new was
added to that surface; Click is purely a new _caller_. This is validated by
asserting `refund_admin` and the shared payments hooks are byte-for-byte
unchanged across the whole branch (final verification, mirroring ADR-0035's
same check for Uzum).

### Why not the Merchant API or Bot Payments API (vs. options 2/3)

Click's Merchant API (invoice creation, `/payment/status`, `/cancel`, card
tokens) and the Telegram Bot Payments API (BotFather provider token,
in-Telegram card entry) are both out of scope for v1 (design spec §15): the
Shop API's Prepare/Complete callbacks plus a plain `my.click.uz` pay link
already cover both surfaces — the mini app opens the pay link via
`openExternalLink` (already shipped for other acquirers), so a
Telegram-native payment flow would be redundant rather than additive. Revisit
only if Click deprecates Shop API callbacks or product requires in-Telegram
card entry specifically.

### Stale-prepare sweep, 30 minutes (unconfirmed window)

`apps/scheduler/src/yupay_scheduler/jobs/click_timeout.py` mirrors
`uzum_timeout.py`'s per-row session isolation (re-checked `FOR UPDATE`
immediately before writing, one bad row never blocks the rest of the sweep)
but cancels via the shared `click.service.cancel()` helper rather than
re-implementing the guard inline. The 30-minute cutoff is a **default**, not
a confirmed Click timeout — design spec §16 gap #4 flags this as pending
Click's own confirmation of their expected window.

### Positive consequences

- A fourth acquirer with its own inverted-callback lifecycle, and a genuinely
  new transport (form-encoded + MD5), still reuses the exact downstream shape
  Payme/Uzum established: one module, one thin `PaymentGateway` adapter, the
  same lifecycle chokepoints.
- The two-service/two-provider shape adds zero new concepts to
  `payments.service` or the gateway registry — it's two ordinary registrations
  of one parametrised class, not a special case threaded through shared code.
- The negative-error cancel rule and the stale-prepare sweep share **one**
  `cancel()` implementation, so the money-safety guard can never drift
  between the two call sites.

### Negative consequences

- A fourth payments module now speaks "provider called us" instead of the
  generic `verify_webhook` contract — a future maintainer must know Payme,
  Uzum, _and_ Click are all exceptions before reaching for the generic
  webhook route.
- Click's endpoints must always return HTTP 200, the same deliberate
  departure from the project's default (raise, let FastAPI render the
  status) as Payme/Uzum — needs its own comment at the route so it isn't
  "fixed" back to raising.
- Two configured services (four config keys just for ids/secrets) is more
  surface area to misconfigure than a single-service acquirer; a
  half-configured service fails closed (`available=False`, `-1` on inbound)
  rather than silently degrading, but it is still two things to keep in sync
  per environment.
- Several details are unconfirmed with Click as of this ADR — see
  "Documentation gaps" below.

## Documentation gaps flagged (not silently assumed)

Mirroring how ADR-0034/0035 flagged Payme/Uzum's unstated conventions, the
design spec (§16) flags six gaps rather than guessing:

1. **Two-service routing convention** — two provider ids (chosen here) vs. a
   single provider + channel hint; confirmed to work with how the web and
   mini-app checkouts each configure their own payment methods.
2. **Web's two Click buttons** — the exact `my.click.uz` URL/params for the
   standard CLICK button vs. "pay by card" are unconfirmed; both still settle
   through the same Prepare/Complete once launched.
3. **Content type** — assumed `application/x-www-form-urlencoded` per the
   PHP reference library; if any service is later configured for JSON, the
   route would need to accept both.
4. **Stale-prepare window** — 30 minutes is our default, not Click's
   confirmed timeout.
5. **`amount` wire format in the sign string** — assumed e.g. `"1000.00"`;
   the hash is built from the raw value regardless, but the exact format is
   worth confirming against a real sandbox request.
6. **Source IPs** — no Caddy allowlist is active (same open question as
   Uzum's); the MD5 signature is the only gate meanwhile.

## Validation

- `apps/api/tests/integration/test_click_webhook.py` /
  `test_click_service.py` — every webhook, every error code it can emit,
  idempotent replay of prepare/complete, the concurrent-prepare
  `IntegrityError` race, the negative-error cancel rule, and the
  money-safety guard on a shared payment.
- `apps/api/tests/integration/test_click_timeout.py` — the 30-min
  stale-prepare sweep.
- `apps/api/tests/unit/test_click_signature.py` — both `sign_string`
  formulas, per-service secret selection, `verify()`'s constant-time /
  fail-closed behaviour.
- `apps/api/tests/unit/test_click_errors.py` / `test_click_gateway.py` — the
  error catalogue, and the two-provider gateway's `available` gating and
  `create_intent` URL-building.
- Real validation milestone: deploy the sandbox and hand Click the callback
  URLs (`/api/v1/payments/click/prepare` + `/complete`) for both services,
  and run a real `my.click.uz/services/pay` test payment per surface before
  flipping to production credentials.

## Alternatives considered (detail)

### Option 2 — Click Merchant API instead of Shop API

Would require invoice-creation and card-tokenization flows not needed for a
webhook-driven pay-link integration, and Click's own manual sandbox testing
targets the Shop API's Prepare/Complete pair specifically for this kind of
integration. Rejected for v1; revisit only if Click deprecates Shop API
callbacks.

### Option 3 — Telegram Bot Payments API for the mini app

Would duplicate what the pay link already does inside the mini app
(`openExternalLink`), adding a BotFather provider-token integration and a
second in-Telegram payment UI for no functional gain over the existing deep
link. Rejected; revisit only if product specifically requires in-Telegram
card entry.

### Option 4 — single provider + channel hint

Would have kept `create_intent` to one provider slug but required every
gateway's call site (`payments.service.create_intent` and its callers) to
learn a new `channel` parameter only Click needs, and would have made the
web/mini-app payment-method configuration less explicit about which service
each surface actually pays through. Rejected in favor of two ordinary
registry entries, which needed zero changes to shared `payments.service`
code.

## References

- [ADR-0020](./0020-octo-acquirer.md) — Octo, the first real UZ acquirer
  (contrast: fits the generic webhook route)
- [ADR-0034](./0034-payme-merchant-api.md) — Payme Merchant API, echo-based
  idempotency, cabinet-initiated refunds
- [ADR-0035](./0035-uzum-merchant-api.md) — Uzum Merchant API, the sibling
  inverted-webhook integration this one mirrors most closely (code-signalled
  idempotency, reverse-based refunds — contrast Click's total absence of a
  merchant-initiated reversal)
- `apps/api/src/yupay/modules/click/README.md` — the 2 webhooks, state
  machine, error catalogue, both `sign_string` formulas
- `docs/runbooks/click-troubleshooting.md`
- `docs/architecture/sequence-diagrams/click-payment.mmd`
- `docs/superpowers/specs/2026-07-23-click-shop-api-design.md` — the full
  design spec this ADR summarizes
- Click docs studied: `https://docs.click.uz/en/shop-api/*` (Shop API,
  captured 2026-07-23) + the `click-llc/click-integration-php` reference
  library
