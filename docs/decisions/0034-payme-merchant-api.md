# 0034. Payme (Paycom) Merchant API integration

- **Status**: Accepted
- **Date**: 2026-07-22
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | integrations

## Context and problem statement

YuPay needed a second Uzbek card acquirer alongside Octo (ADR-0020). Payme
(Paycom) is the obvious choice — dominant in UZ, and unlike Octo its
**Merchant API** does not fit our existing gateway shape at all: every other
gateway (`mock`, `wallet`, `octo`) follows `create_intent` → redirect →
provider POSTs **one** signed webhook → `verify_webhook` → done, with the
provider a passive caller of our generic
`POST /api/v1/webhooks/payments/{provider}` route.

Payme's Merchant API inverts that. Payme calls **seven** JSON-RPC 2.0 methods
against a single endpoint of ours, over the full life of the transaction —
`CheckPerformTransaction`, `CreateTransaction`, `PerformTransaction`,
`CancelTransaction`, `CheckTransaction`, `GetStatement`, `SetFiscalData` — and
Payme, not us, owns the authoritative transaction state machine
(`1` created / `2` performed / `-1` cancelled-before-perform / `-2`
cancelled-after-perform). We are not receiving a webhook; **we are the
provider's JSON-RPC server.**

## Decision drivers

- `payments.service._mark_payment_succeeded` must stay the single place an
  order moves to `paid` — Payme must not become a second code path.
- The integration must survive **replays**: Payme retries any method call it
  didn't get a confirmed response for, so every method must be idempotent on
  its own terms, not just via the generic webhook-dedup table (which doesn't
  apply here at all).
- Money-safety: a refund must never claw back money for a code the customer
  already holds, even on a partially-fulfilled multi-item order.
- The official docs (RU pages, `developer.help.paycom.uz`) leave some
  merchant-side conventions unstated; those gaps must be resolved as
  configuration, not silently hardcoded assumptions.

## Considered options

1. **Merchant API** — Payme hosts the checkout form and fiscalizes the
   receipt; we run a JSON-RPC server that Payme drives through the
   transaction lifecycle.
2. **Subscribe API** — our own payment form, saved cards, one-click pay,
   autopay/invoices; we self-fiscalize and hold funds under a month-limited
   authorization window.
3. **Bolt the new lifecycle onto the existing `verify_webhook` contract**
   (treat each Payme call as a webhook delivery).

## Decision outcome

**Chosen option: 1 (Merchant API)**, implemented as a **dedicated module**,
`apps/api/src/yupay/modules/payme/`, rather than another
`payments/gateways/*.py` file alone.

### Why Merchant API over Subscribe (vs. Option 2)

Subscribe API buys us a custom payment UI, saved cards, and autopay — none of
which the product needs today — at the cost of: self-fiscalization (we'd have
to generate compliant fiscal receipts ourselves), a month-limited hold on
authorized-but-uncaptured funds, and a materially larger surface to build and
certify. Merchant API gives us the two things that matter for a digital-goods
storefront that already earns its margin at wholesale, not at checkout UX:
Payme hosts and fiscalizes the receipt, and Payme **guarantees full
cancellation** of a transaction it hasn't performed. We took the smaller,
better-fitting surface.

### Why a dedicated module, not another gateway file (vs. Option 3)

Every other acquirer is "implement `PaymentGateway`, register the slug,
done" (ADR-0012, ADR-0020). Payme cannot be, because `verify_webhook` assumes
we receive occasional callbacks about a transaction _we_ created and control;
Payme's Merchant API makes **Payme's own transaction record** the source of
truth, arriving via **repeated** calls (Create, then later Perform _or_
Cancel — possibly replayed) rather than one terminal delivery. Modeling that
as a webhook would have forced a fake `external_event_id` scheme and lost the
protocol's own idempotency key (`payme_id`). Instead:

- `payme/models.py` — `PaymeTransaction`, keyed `UNIQUE(payme_id)`, mirrors
  Payme's state machine verbatim (migration `0027`).
- `payme/routes.py` — `POST /api/v1/payments/payme/merchant`, one endpoint,
  JSON-RPC dispatch, HTTP Basic auth (`Paycom:<key>`), **always HTTP 200**
  (Payme reads any non-200 as transport error `-32400`, so auth failures, bad
  JSON, unknown methods and internal errors all render as a 200 body with an
  `error` object rather than an HTTP exception).
- `payme/service.py` — the seven handlers plus `build_checkout_url` (the
  `create_intent` half — a client-side base64 URL, no prepare-payment API
  call, unlike Octo).
- `payme/errors.py` — the exact Payme error catalogue (trilingual messages).
- `payments/gateways/payme.py` (`PaymeGateway`) stays thin: `create_intent`
  delegates to `payme.service.build_checkout_url`, `verify_webhook` is
  intentionally unreachable (`PaymentNotIntegratedError` — Payme never calls
  the generic webhook route), and `refund` always raises (see below). The
  `REGISTRY["payme"]` slot (reserved as a stub since ADR-0012) now points at
  the real adapter.
- Every state-2 transition Payme calls back into (`PerformTransaction`,
  `CancelTransaction`) funnels through `payments.service`'s existing
  provider-lifecycle chokepoints — `settle_provider_payment`,
  `reverse_provider_payment`, `cancel_pending_provider_payment` — the same
  `_mark_payment_succeeded` / `_apply_refund_reversal` cores admin refunds and
  every other gateway already use. Payme reuses the whole downstream
  (order FSM, ledger, fulfilment) unchanged; only the _trigger_ is new.

### Refunds: cabinet-initiated, auto-reconciled

Merchant API has **no merchant→Payme refund call**. A refund is initiated by
an operator in the **Payme cabinet**; Payme then calls our
`CancelTransaction` on the performed transaction (state `2`→`-2`), which we
auto-reconcile through the same `_apply_refund_reversal` core an admin refund
uses (order → `refunded`, ledger reversal). Consequently
`PaymeGateway.refund()` always raises `PaymentGatewayError`, which the admin
refund endpoint surfaces as **409**, pointing the operator at the Payme
cabinet instead of a button that would silently do nothing. This mirrors how
Octo's refund is a direct API call — Payme's is a direct **cabinet** action
that reconciles through the JSON-RPC channel we already run.

### Amounts and account resolution

Payme moves money in **tiyin** (integer minor units); our `order.total_charged`
is a `Decimal` in major UZS units, so the expected amount is
`int(total_charged * 100)`, computed exactly — any non-integral result (data
corruption) is rejected as `-31001` rather than silently rounded.
`account.order_id` carries our `order.id` verbatim (a one-time account, one
per order) — Payme's generic `account` object is not otherwise interpreted.

### Partial-delivery money-safety (`-31007`)

`CancelTransaction` on a **performed** transaction routes to a refund only if
it's safe. The naive check — order status is `fulfilled`/`delivered` — misses
a multi-item order sitting at `fulfilling` with _some_ items already shipped.
`cancel_transaction` therefore also checks
`_any_goods_delivered`: **any** succeeded `FulfillmentTask` for the order
blocks the auto-refund with `-31007`, even if the order as a whole hasn't
reached a terminal fulfilled state. A `FulfillmentTask` reaches `succeeded`
atomically with its `Delivery`, so this is proof-positive the customer already
holds at least one code; refunding the whole order in that state would claw
back money for goods already handed over. Such a case is left for manual
reconciliation (Payme cabinet + admin), never auto-full-refunded.

### Documentation gaps made configurable

The Payme docs' prose is incomplete in three places we would otherwise have
had to guess at; each became a config value instead of a hardcoded
assumption:

- **Basic-auth login** — every official Payme template uses `Paycom`, but the
  docs never state it as a contractual value → `payme_login`, default
  `"Paycom"`.
- **Checkout host** — the docs show both `checkout.paycom.uz` and bare
  `paycom.uz` → `payme_checkout_url`, default `https://checkout.paycom.uz`
  (switched to `https://test.paycom.uz` for sandbox).
- **Merchant response timeout** — no documented SLA in seconds for how long
  Payme waits before treating our response as lost → not hardcoded anywhere;
  we simply answer fast and idempotently, since Payme's own retry-on-loss
  behavior is what the idempotency keying (`payme_id` UNIQUE) exists to
  survive.

The merchant endpoint accepts **either** the production key or the sandbox
test key (`payme_key` or `payme_test_key`), so the same deployed endpoint
serves Payme's sandbox test suite before production credentials exist, and
continues serving production after — no code path switches on environment,
only which key is configured for which cabinet.

### Positive consequences

- Adding a card acquirer that owns its own callback lifecycle is now a
  documented pattern (a sibling module + a `PaymentGateway` adapter that's
  mostly a thin front for it), not a one-off exception.
- Refund-via-cabinet + auto-reconcile means no new refund UI or ledger
  posting shape was needed — it's the exact same `_apply_refund_reversal` core.
- `-31007`'s any-item-delivered guard closes a money-safety gap that a
  naive whole-order-status check would have missed on multi-item orders.

### Negative consequences

- Two payments modules now speak "provider called us" instead of one uniform
  `verify_webhook` contract — a future maintainer must know Payme is the
  exception before reaching for the generic webhook route.
- The Payme endpoint must always return HTTP 200, which is a deliberate
  departure from the project's default (raise, let FastAPI render the status)
  and needs its own comment at the route to not be "fixed" back to raising.
- Config carries two live keys at once (`payme_key` + `payme_test_key`)
  indefinitely, rather than one key that's swapped at go-live — a slightly
  wider secret surface, accepted so sandbox and production share one endpoint.

## Validation

- `apps/api/tests/integration/test_payme_merchant.py` — every method, every
  error code, and Payme's own two mandatory sandbox sequences (Unconfirmed:
  bad auth → invalid amount → unknown account → Check/Create/Cancel;
  Confirmed: Check/Create/Perform → order paid → Cancel/refund reconciled),
  plus idempotent-replay and the 12h timeout job.
- Real validation milestone: point a public endpoint at Payme's sandbox
  cabinet (`test.paycom.uz`), run Payme's automated test suite against
  `/api/v1/payments/payme/merchant`, and confirm all checks pass before
  flipping `payme_checkout_url` to the production host.

## Alternatives considered (detail)

### Option 2 — Subscribe API

Pros: native payment UI, saved cards, one-click repeat purchases, autopay for
subscription-like products. Cons: self-fiscalization burden, month-limited
hold semantics on uncaptured authorizations, and a larger certification
surface — none of which pays for itself against a hosted-checkout digital
storefront. Rejected for v1; not precluded later if a subscription product
appears.

### Option 3 — model Payme as a webhook

Would have required inventing a synthetic `external_event_id` per JSON-RPC
call and fighting the generic `payment_webhooks` dedup table's assumptions
(one provider, one terminal delivery) instead of using Payme's own
`payme_id` idempotency key and multi-call lifecycle. Rejected — the fit was
worse, not just differently shaped.

## References

- [ADR-0012](./0012-payments-skeleton-and-provider-stubs.md) — payment gateway
  abstraction, stub registry
- [ADR-0020](./0020-octo-acquirer.md) — Octo, the first real UZ acquirer
  (contrast: fits the generic webhook route)
- [ADR-0023](./0023-wallet-refund-reversal.md) — `_apply_refund_reversal`
  shared core reused here
- `apps/api/src/yupay/modules/payme/README.md` — the 7 methods, state machine,
  error catalogue
- `docs/runbooks/payme-troubleshooting.md`
- `docs/architecture/sequence-diagrams/payme-payment.mmd`
- Payme docs studied: https://developer.help.paycom.uz/ (Merchant API, RU
  pages — protocol, method pages, error tables, data types, sandbox, checkout
  initiation)
