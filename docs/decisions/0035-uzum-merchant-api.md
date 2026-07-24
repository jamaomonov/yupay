# 0035. Uzum Bank Merchant API integration

- **Status**: Accepted
- **Date**: 2026-07-22
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | integrations

## Context and problem statement

YuPay needed a third Uzbek acquirer alongside Octo (ADR-0020) and Payme
(ADR-0034). Uzum Bank is a natural fit for the UZ market — and like Payme,
its **Merchant API** does not fit our existing gateway shape at all: every
classic gateway (`mock`, `wallet`, `octo`) follows `create_intent` →
redirect → provider POSTs **one** signed webhook → `verify_webhook` → done,
with the provider a passive caller of our generic
`POST /api/v1/webhooks/payments/{provider}` route.

Uzum's Merchant API inverts that, the same way Payme's does. Uzum calls
**five** plain HTTP/JSON `POST` endpoints against our server, over the full
life of a transaction — `/check`, `/create`, `/confirm`, `/reverse`,
`/status` — authenticated with HTTP Basic auth plus a `serviceId`. Unlike
Payme, though, **we** own the transaction state machine and its idempotency
(`UzumTransaction.status`: `CREATED`/`CONFIRMED`/`REVERSED`/`FAILED`) — Uzum
does not echo back a protocol state we must mirror; it just drives our own
FSM and expects a dedicated error code when it replays a call.

## Decision drivers

- `payments.service.settle_provider_payment` (and its `reverse_provider_
payment`/`cancel_pending_provider_payment` siblings) must stay the single
  place an order moves to `paid`/`refunded`/`cancelled` — Uzum must not
  become a third code path (after Octo and Payme) that flips order status
  or posts the ledger.
- The integration must survive **replays**: Uzum's own spec mandates
  dedicated "already-X" error codes for a repeat call, not silent
  re-acknowledgement, so every handler must branch on the transaction's
  stored status rather than assume a call is happening for the first time.
- Money-safety: a `/reverse` on a `CONFIRMED` transaction must never claw
  back money for a code the customer already holds, even on a
  partially-fulfilled multi-item order — the same invariant Payme's
  `CancelTransaction`/`-31007` enforces.
- Several merchant-side conventions are left unstated by Uzum's docs and the
  informal engineer chat that supplemented them; those gaps must become
  configuration or explicitly-flagged open questions, not silently hardcoded
  assumptions (see "Documentation gaps" below).

## Considered options

1. **Merchant API (five inverted webhooks)** — implement all five endpoints
   as a dedicated module, mirroring the Payme module's shape with Uzum's own
   verbs, statuses, and error codes.
2. **Bolt the new lifecycle onto the existing `verify_webhook` contract**
   (treat each Uzum call as a webhook delivery through the generic
   `payments/gateways` route).
3. **Wait for Uzum's newer "intents" checkout API**
   (`/processing/api/v1/intents`) instead of the webhook Merchant API.

## Decision outcome

**Chosen option: 1 (Merchant API)**, implemented as a **dedicated module**,
`apps/api/src/yupay/modules/uzum/`, structured exactly like `payme/`:
`models.py` (`UzumTransaction`, migration `0028`), `errors.py` (18 factories

- `to_response()`), `service.py` (the 5 handlers + `build_checkout_url`),
  `routes.py` (Basic auth + `serviceId` guard, always-HTTP-200 JSON), `api.py`
  (public surface).

### Why the webhook model, not the generic `verify_webhook` route (vs. Option 2)

`verify_webhook` assumes we receive an occasional callback about a
transaction _we_ created and control, terminating in one delivery per event.
Uzum's Merchant API instead makes **our own** `UzumTransaction` row the
source of truth, arriving via **repeated** calls (`/create`, then later
`/confirm` _or_ `/reverse`, `/status` polled independently) each keyed by
Uzum's own `transId`. Modeling that as a webhook would have forced a fake
`external_event_id` scheme onto the generic `payment_webhooks` dedup table
and lost the protocol's own idempotency key. Instead, every state-changing
call funnels through `payments.service`'s existing provider-lifecycle
chokepoints — `settle_provider_payment` (`/confirm`),
`reverse_provider_payment` (`/reverse` of a `CONFIRMED` tx),
`cancel_pending_provider_payment` (`/reverse` of a `CREATED`/`FAILED` tx) —
the same cores Octo, Payme, and admin refunds already use. Uzum reuses the
whole downstream (order FSM, ledger, fulfilment) unchanged; only the
_trigger_ is new.

### Why not wait for the intents API (vs. Option 3)

The intents API (`/processing/api/v1/intents`) is a separate, newer flow not
required for a webhook-driven merchant integration, and Uzum's manual
sandbox tester exercises the Merchant API's five webhooks specifically. Out
of scope for v1 (design spec §15); revisit only if Uzum deprecates the
webhook Merchant API in favor of intents.

### Refunds: reverse-based, with the delivered-goods guard

Merchant API has **no merchant→Uzum refund call** at all — unlike Payme
(cabinet-initiated) there isn't even an operator-facing trigger on our side.
A refund is reconciled entirely by Uzum calling `/reverse` on a `CONFIRMED`
transaction. `/reverse` routes strictly by the transaction's current status:

- **`CREATED`** (never confirmed) or **`FAILED`** (already timed out — an
  idempotent no-op) → `cancel_pending_provider_payment`. No ledger, no
  refund.
- **`CONFIRMED`** → a refund via `reverse_provider_payment`, **refused with
  `10017`** ("transaction cannot be cancelled in current state") if the
  order's goods are already delivered — either the whole order is
  `fulfilled`/`delivered`, or _any single_ `FulfillmentTask` for the order
  has already reached `succeeded`. A multi-item order can sit at
  `fulfilling` with one item already shipped; the naive whole-order-status
  check misses that, so `_any_goods_delivered` also gates on the
  fine-grained per-task signal — the same money-safety pattern Payme's
  `-31007` guard established (ADR-0034). Such an order is never
  auto-refunded; it needs manual reconciliation.

Consequently `UzumGateway.refund()` always raises `PaymentGatewayError` —
there is no "issue a refund" admin action to build for Uzum at all, since
Uzum itself is always the one calling `/reverse`.

### Idempotency signalled by dedicated codes, not an echo (vs. Payme)

Payme's `CreateTransaction`/`PerformTransaction`/`CancelTransaction` all
re-return the stored result on a replay. Uzum's own spec instead mandates
**dedicated error codes** for a duplicate call: repeat `/create` on an
existing `transId` → `10010`; repeat `/confirm` on an already-`CONFIRMED`
transaction → `10016`; repeat `/reverse` on an already-`REVERSED`
transaction → `10018`. Every handler looks up the row by `trans_id` first
and branches on its stored status — a lookup-then-branch shape, not a
lookup-then-echo one. `/status` is the read-only reconciliation channel:
Uzum retries it up to 10× after a failed or timed-out `/confirm` until we
report a terminal state; because `/confirm` settles inside one DB
transaction, a `CONFIRMED` row is durable before we ever answer it, so the
retry always sees it correctly.

`/create`'s pre-check (`SELECT ... FOR UPDATE` keyed on `trans_id`) is not a
lock against a not-yet-existing row, so two concurrent first-time `/create`
calls for the same `transId` can both pass it and both reach the insert. The
loser's flush raises `IntegrityError` on the unique `trans_id`; the handler
catches it and reports `10010` — the same code the pre-check would have
produced — rather than letting it escape as `99999`.

### Credentials are env-configurable, source confirmed later

Uzum's docs state credentials are "provided by our team" for production, but
the informal engineer chat says we generate them ourselves for sandbox
testing. Rather than hardcode either assumption, `uzum_login`/
`uzum_password` (production) and `uzum_test_login`/`uzum_test_password`
(sandbox) are both configurable, and the route accepts **either** pair —
mirroring Payme's two-key acceptance so the same deployed endpoint serves
sandbox and production without a code branch. `uzum_service_id` is likewise
config, generated as a placeholder for sandbox and swapped for Uzum's
real value at go-live. The actual production credential-issuance model is
confirmed with Uzum before go-live (design spec §16 gap #1), not assumed.

### 30-minute timeout, not 12 hours

Uzum's own spec (§10) treats an unconfirmed transaction as failed after 30
minutes — much tighter than Payme's 12-hour window, reflecting Uzum's
checkout being a single in-app flow rather than a hosted page a buyer might
leave open. `apps/scheduler/src/yupay_scheduler/jobs/uzum_timeout.py` mirrors
`payme_timeout.py`'s per-row session isolation (`FOR UPDATE`, re-checked
immediately before writing, one bad row never blocks the sweep) but with
`TIMEOUT_MS = 1_800_000` (30 min) instead of 12h, sweeping every 5 minutes.
Only `CREATED` transactions are ever in scope — a `CONFIRMED` transaction's
payment is already `succeeded`, and `cancel_pending_provider_payment` (no
ledger reversal) would be the wrong hook for that; the listing query and the
per-row re-check both guard against a race that would otherwise let a
just-confirmed row slip into the sweep.

### Reuse of the shared payments hooks

Every money-moving effect — settle, reverse, cancel-pending — funnels
through the exact same `payments.service` functions Octo, Payme, and admin
refunds already call. Nothing new was added to that surface; Uzum is purely
a new _caller_ of an existing chokepoint. This is validated by asserting
`refund_admin` and the shared payments hooks are byte-for-byte unchanged
across the whole branch (design spec §13, task-11 final verification).

### Positive consequences

- A third acquirer with its own inverted callback lifecycle reuses the exact
  pattern Payme established (ADR-0034) — a sibling module + a thin
  `PaymentGateway` adapter — rather than inventing a new shape.
- The delivered-goods `10017` guard reuses `_any_goods_delivered`
  proof-positive logic Payme's `-31007` guard already validated; no new
  money-safety code, just a new caller of it.
- Code-signalled idempotency (`10010`/`10016`/`10018`) makes replay handling
  explicit in the wire contract itself, rather than relying on callers to
  notice an echoed result looks identical to a fresh one.

### Negative consequences

- A third payments module now speaks "provider called us" instead of the
  generic `verify_webhook` contract — a future maintainer must know both
  Payme and Uzum are exceptions before reaching for the generic webhook
  route.
- The Uzum endpoints must always return HTTP 200, a deliberate departure
  from the project's default (raise, let FastAPI render the status) that
  needs its own comment at the route so it isn't "fixed" back to raising.
- Several merchant-side conventions (credential-issuance model, exact
  open-service URL/params, HTTP status expected for auth failures, the
  `params` account-attribute key, and whether Uzum or we enforce amount
  min/max) are unconfirmed with Uzum as of this ADR — see "Documentation
  gaps" below. `10012`/`10013` (amount below/above bounds) have factory
  functions and are unit-tested at the error-object level but are not wired
  into `service.py` today, pending gap #5.

## Documentation gaps flagged (not silently assumed)

Mirroring how ADR-0034 flagged Payme's unstated conventions, the design spec
(§16) flags six gaps in Uzum's docs/engineer chat rather than guessing:

1. **Credential source in production** — docs say Uzum issues
   `login`/`password`; the engineer says we set them for sandbox testing.
   Both are env-configurable; the production source is confirmed with Uzum
   before go-live.
2. **Exact open-service URL/params** — taken from a third-party library;
   `serviceId`/`order_id`/`amount`/`redirectUrl` and the host are confirmed
   with Uzum, not assumed final.
3. **HTTP status for `10001`** — whether Uzum expects a non-2xx or a 200
   body with `errorCode: 10001` for auth failures. Default is the 200-body
   form (matches every other error code); confirm with Uzum.
4. **`params` account envelope** — we assume `params.order_id`; the exact
   account-attribute key(s) configured per-service on Uzum's side needs
   confirmation.
5. **Min/max amount (`10012`/`10013`)** — whether Uzum enforces these
   service-side bounds itself or expects us to assert them. Left unwired
   until confirmed rather than guessing a threshold.
6. **Source IPs** — no Caddy allowlist is active yet (unlike Payme's
   `185.234.113.0/28`); the commented-out block in
   `infra/caddy/Caddyfile.prod` is filled in once Uzum publishes a range.
   App-layer `10001` auth is the real gate meanwhile.

## Validation

- `apps/api/tests/integration/test_uzum_webhook.py` /
  `test_uzum_service.py` — every webhook, every error code it can emit,
  idempotent replay of create/confirm/reverse, the concurrent-create
  `IntegrityError` → `10010` race, and the commit-failure-still-`99999`-at-
  200 path.
- `apps/api/tests/integration/test_uzum_timeout.py` — the 30-min sweep.
- `apps/api/tests/unit/test_uzum_gateway.py` / `test_uzum_config.py` — the
  gateway's `available` gating and `create_intent` URL-building, and config
  defaults.
- Real validation milestone: hand Uzum's engineer the sandbox callback base
  URL, Basic credentials, `serviceId`, and the Postman collection (design
  spec §18) and confirm their manual test suite passes before flipping to
  production credentials.

## Amendments

- **2026-07-24 — `/check` response carries the amount and a response-time
  `timestamp`** (requested by Uzum's integration engineer). `/check` now
  returns `data.amount.value` = the order's charge in **sums** (major UZS
  units, string) so Uzum's app prefills the amount when the buyer opens
  checkout, and its `timestamp` is now our **response** time (epoch ms) rather
  than the request's echoed value. This is additive to the wire contract (the
  other four responses are unchanged; no state-machine or money-path change),
  so it does not warrant a superseding ADR — see
  `apps/api/src/yupay/modules/uzum/README.md` (`POST /check`) and design spec
  §11.

## Alternatives considered (detail)

### Option 2 — model Uzum as a webhook

Would have required inventing a synthetic `external_event_id` per Merchant
API call and fighting the generic `payment_webhooks` dedup table's
assumptions (one provider, one terminal delivery) instead of using Uzum's
own `transId` idempotency key and multi-call lifecycle, plus losing the
dedicated replay error codes Uzum's spec mandates. Rejected — same reasoning
ADR-0034 gave for rejecting this shape for Payme.

### Option 3 — wait for the intents API

Would delay a working UZ acquirer integration for a flow not documented as
required for merchant onboarding, on the assumption a newer API supersedes
the webhook one — unconfirmed and not worth blocking on. Rejected for v1;
revisit only if Uzum deprecates the Merchant API webhooks.

## References

- [ADR-0020](./0020-octo-acquirer.md) — Octo, the first real UZ acquirer
  (contrast: fits the generic webhook route)
- [ADR-0034](./0034-payme-merchant-api.md) — Payme Merchant API, the sibling
  inverted-webhook integration this one mirrors (echo-based idempotency,
  cabinet-initiated refunds — contrast with Uzum's code-signalled
  idempotency and reverse-based refunds)
- [ADR-0023](./0023-wallet-refund-reversal.md) — `_apply_refund_reversal`
  shared core, reused (via `reverse_provider_payment`) here
- `apps/api/src/yupay/modules/uzum/README.md` — the 5 webhooks, state
  machine, error catalogue
- `docs/runbooks/uzum-troubleshooting.md`
- `docs/architecture/sequence-diagrams/uzum-payment.mmd`
- `docs/superpowers/specs/2026-07-22-uzum-merchant-api-design.md` — the
  full design spec this ADR summarizes
- Uzum docs studied: `https://developer.uzumbank.uz/en/merchant/` (Merchant
  API, captured 2026-07-22)
