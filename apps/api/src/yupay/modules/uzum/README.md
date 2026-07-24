# `uzum` — Uzum Bank Merchant API

Uzum Bank's hosted-checkout acquirer for the UZ market — the third Uzbek
acquirer alongside Octo and Payme. Like Payme, Uzum does not deliver a
webhook to us — **we are Uzum's Merchant API server**: Uzum calls five plain
HTTP/JSON endpoints against our server over the full life of a transaction,
and **we** own the transaction state machine and its idempotency (unlike
Payme, where Payme's own state machine is authoritative). See
[ADR-0035](../../../../../../docs/decisions/0035-uzum-merchant-api.md) for the
full rationale, and `apps/api/src/yupay/modules/payme/README.md` for the
sibling integration this one mirrors.

## Endpoints + auth

```
POST /api/v1/payments/uzum/check
POST /api/v1/payments/uzum/create
POST /api/v1/payments/uzum/confirm
POST /api/v1/payments/uzum/reverse
POST /api/v1/payments/uzum/status
```

- **Transport:** plain HTTP `POST`, `Content-Type: application/json`. Any
  other method on any of these paths → `10003` (invalid operation), never a
  405 — the route layer registers a catch-all handler for
  `GET`/`PUT`/`PATCH`/`DELETE`/`HEAD`/`OPTIONS` that answers `10003` at HTTP 200.
- **Always HTTP 200.** Uzum reads any non-200 as a transport failure, so
  auth failures, bad JSON, missing fields, and internal errors all come back
  **200** with a `{"status": "FAILED", "errorCode": ...}` body — never a
  raised HTTP exception. The route layer parses the raw body itself (never a
  Pydantic request model) so a malformed body is `10002`, not FastAPI's
  automatic 422.
- **Auth:** `Authorization: Basic base64("<login>:<password>")`. The pair
  must match **either** the production credentials (`uzum_login`/
  `uzum_password`) **or** the sandbox credentials (`uzum_test_login`/
  `uzum_test_password`) — both checked so one deployed endpoint serves
  sandbox and production traffic without a code branch. A pair with either
  side blank is never accepted (an unconfigured acquirer rejects every
  request). Failure → `10001`.
- **`serviceId`:** every request body carries `serviceId` (int64); it must
  equal the configured `uzum_service_id` — mismatch, or nothing configured,
  → `10006`.

## Amounts and account

- Amounts are **sums** (integer major UZS units), **not tiyin** — Uzum's
  `amount` is an `int64` count of sums. Our `order.total_charged` is a
  `Decimal` in major UZS units, already rounded to whole sums at order
  creation (`orders.service._round_to_payable` uses a `Decimal("1")` quantum
  for UZS — tiyin coins are defunct), so the expected amount is
  `int(total_charged)`, required to be a **whole** number of sums — any
  fractional-sum mismatch is `10011`, never silently rounded.
- `params.order_id` = our `order.id`. No other `params`/account fields are
  interpreted.

## The five webhooks

All request/response shapes below are the JSON body shapes; errors are
raised as `UzumError` and rendered via `to_response(**echo)`, which echoes
back `serviceId` (and `transId` when the request carried one).

### `POST /check`

- **Request:** `{"serviceId", "timestamp", "params": {"order_id"}}`.
- **Success:** `{"serviceId", "timestamp", "status": "OK", "data": {"amount": {"value": "<sums>"}}}`.
  - **`timestamp`** is our **response** time (epoch ms), *not* the request's
    echoed value — Uzum wants the moment we answered.
  - **`data.amount.value`** carries the order's charge in **sums** (major UZS
    units, as a string — e.g. `"130000"`; fractional sums keep their decimals)
    so Uzum's app prefills the amount when the buyer opens checkout. Built by
    `service._amount_value` from `order.total_charged`. (The `amount` field on
    `/create` is likewise in **sums** — the whole integration is
    sum-denominated.)
- **Errors:** `10007` (unknown order), `10008` (already paid), `10009`
  (cancelled/expired/refunded/otherwise not payable). No amount is sent *by
  Uzum* on `/check`, so there is no amount check here — we only *report* the
  order's amount back in `data`.

### `POST /create`

- **Request:** `{"serviceId", "timestamp", "transId", "params": {"order_id"}, "amount"}`.
- **Success:** `{"serviceId", "transId", "status": "CREATED", "transTime", "amount"}`. No `data` — it is only returned by `/check` and `/status` (optional elsewhere).
- **Idempotency:** a `transId` that already has a `UzumTransaction` row is
  refused outright with **`10010`** — Uzum's own replay signal, not an echo
  (contrast Payme, which re-returns the stored result on a `CreateTransaction`
  replay). A concurrent duplicate `/create` that races the insert surfaces as
  a `trans_id` unique-constraint `IntegrityError`; the handler catches it and
  reports the same `10010` rather than letting it escape as `99999`.
- **Errors:** `10010` (replay), `10007`/`10008`/`10009` (order-state check,
  same as `/check`), `10011` (amount mismatch against
  `order.total_charged * 100`).
- **Effect:** reuses the order's existing pending `uzum` `Payment` row if one
  exists, else creates one; inserts the `UzumTransaction` (status `CREATED`).

### `POST /confirm`

- **Request:** `{"serviceId", "timestamp", "transId", "paymentSource", "tariff", "processingReferenceNumber", "phone", "cardType", ...}`.
- **Success:** `{"serviceId", "transId", "status": "CONFIRMED", "confirmTime", "amount"}`. No `data` — only `/check` and `/status` return it.
- **Effect:** stores the payment-source block verbatim on the transaction row
  (audit only — no pricing branches on it), settles the backing payment
  through `payments.service.settle_provider_payment` — the same chokepoint
  every gateway uses, which flips the order to `paid` and starts fulfilment.
- **Errors:** `10014` (unknown `transId`), `10016` (already `CONFIRMED` —
  replay), `10015` (transaction is `REVERSED`/`FAILED` — cannot confirm a
  cancelled transaction).

### `POST /reverse`

- **Request:** `{"serviceId", "timestamp", "transId"}`.
- **Success:** `{"serviceId", "transId", "status": "REVERSED", "reverseTime", "amount"}`. No `data` — only `/check` and `/status` return it.
- **Routes strictly by the transaction's current status** — this is where
  money-safety lives:
  - **`CREATED`** (never confirmed), or **`FAILED`** (already timed out by
    the 30-min sweep — an idempotent no-op) → calls
    `payments.service.cancel_pending_provider_payment`. No ledger, no
    refund; the backing payment moves to `cancelled`.
  - **`CONFIRMED`** → a **refund**. Calls
    `payments.service.reverse_provider_payment` (ledger reversal). **Refused
    with `10017`** if the order's goods are already delivered — either the
    order status is `fulfilled`/`delivered`, or _any single_
    `FulfillmentTask` for the order has already reached `succeeded` (a
    multi-item order can sit at `fulfilling` with one item already shipped;
    this guard catches that case even though the whole-order status
    wouldn't). Such an order is never auto-refunded; it needs manual
    reconciliation.
- **Idempotent:** a replay on an already-`REVERSED` transaction → `10018`.
- **Errors:** `10014` (unknown `transId`), `10018` (already reversed),
  `10017` (goods already delivered).

### `POST /status`

- **Request:** `{"serviceId", "timestamp", "transId"}`.
- **Success:** `{"serviceId", "transId", "status", "transTime", "confirmTime", "reverseTime", "data": {}, "amount"}` —
  `confirmTime`/`reverseTime` are `null` until set.
- **Effect:** read-only; reports the transaction's current stored status and
  timestamps. This is Uzum's reconciliation channel — it retries `/status` up
  to 10× after a failed/timed-out `/confirm` until we report a terminal
  state. Because `/confirm` settles inside one DB transaction, a `CONFIRMED`
  row is durable before we answer it, so a `/status` retry always sees it.
- **Errors:** `10014` (unknown `transId`).

## State machine

```
/create  → CREATED
CREATED  --/confirm--> CONFIRMED   -- settle_provider_payment: order paid, fulfilment starts
CREATED  --/reverse--> REVERSED    -- cancel_pending_provider_payment, no ledger
CONFIRMED --/reverse--> REVERSED   -- reverse_provider_payment, ledger reversal (refused 10017 if delivered)
CREATED  --30-min no-confirm--> FAILED   -- scheduler sweep, cancel_pending_provider_payment
FAILED   --/reverse--> REVERSED    -- idempotent no-op cancel (already-cancelled payment)
```

`UzumTransaction.status` is our own machine (`CREATED` / `CONFIRMED` /
`REVERSED` / `FAILED`, enforced by a `CHECK` constraint), keyed `UNIQUE` on
`trans_id` — Uzum's own transaction id — so every method is idempotent
against replays.

### 30-minute auto-fail

`apps/scheduler/src/yupay_scheduler/jobs/uzum_timeout.py` runs every 5
minutes and fails (status → `FAILED`) any transaction still `CREATED` older
than `TIMEOUT_MS` (1,800,000 ms = 30 min) — a buyer who opened Uzum's
checkout and never completed (or abandoned) it, so Uzum never called
`/confirm` at all. Each stale row is re-checked `FOR UPDATE` immediately
before writing (a concurrent `/confirm` or `/reverse` may have already
resolved it) and is failed in its own session so one bad row never blocks the
rest of the sweep. Cancels the backing payment via
`cancel_pending_provider_payment` — the same hook `/reverse` uses for a
`CREATED`-state cancel, just self-driven instead of provider-driven.

## Error catalogue (`errors.py`)

| Code    | Meaning                                             | Can be emitted by                       |
| ------- | --------------------------------------------------- | --------------------------------------- |
| `10001` | Access denied (bad/missing Basic auth)              | all                                     |
| `10002` | JSON parsing error                                  | all                                     |
| `10003` | Invalid operation (non-`POST`)                      | all                                     |
| `10005` | Missing required parameters                         | all                                     |
| `10006` | Invalid `serviceId`                                 | check, create, confirm, reverse, status |
| `10007` | Additional payment attribute not found (`order_id`) | check, create                           |
| `10008` | Payment already made                                | check, create                           |
| `10009` | Payment cancelled                                   | check, create                           |
| `10010` | Transaction with this `transId` already created     | create                                  |
| `10011` | Invalid amount                                      | create                                  |
| `10012` | Amount below minimum                                | _defined, not yet raised_               |
| `10013` | Amount exceeds maximum                              | _defined, not yet raised_               |
| `10014` | Transaction `transId` does not exist                | confirm, reverse, status                |
| `10015` | Transaction cancelled (cannot confirm)              | confirm                                 |
| `10016` | Transaction already confirmed                       | confirm                                 |
| `10017` | Transaction cannot be cancelled in current state    | reverse                                 |
| `10018` | Transaction already cancelled                       | reverse                                 |
| `99999` | Internal server error                               | all                                     |

`10012`/`10013` have factory functions and are unit-tested at the
error-object level, but `service.py` never raises them today — the design
spec (§16 gap #5) leaves open whether Uzum enforces amount bounds
server-side or expects us to; the codes are reserved for that once
confirmed, not silently wired to a guessed threshold.

## Checkout initiation (`build_checkout_url`)

`UzumGateway.create_intent` (in `payments/gateways/uzum.py`) never calls a
Uzum API — like Payme, the checkout link is an **open-service deep link**
built entirely client-side:

```
https://www.uzumbank.uz/open-service?serviceId=<uzum_service_id>&order_id=<order.id>&amount=<amount_sum>[&redirectUrl=<return_url>]
```

`redirectUrl` is omitted entirely when no `return_url` is given. The gateway
validates `order.currency == "UZS"`, `total_charged > 0`, and that
`total_charged` is a whole number of sums before building the URL (Uzum is
offered only for UZS orders). `verify_webhook` on this gateway always raises
`PaymentNotIntegratedError` (Uzum never calls the generic
`/webhooks/payments/{provider}` route), and `refund()` always raises
`PaymentGatewayError` — see "Refunds" below.

## Refunds

Merchant API has **no merchant→Uzum refund call**. A refund is reconciled
entirely through Uzum calling `/reverse` on a `CONFIRMED` transaction (see
above) — there is no operator-facing "issue a refund" action on our side to
trigger it, unlike Payme's cabinet-initiated flow. `UzumGateway.refund()`
therefore always raises `PaymentGatewayError`. See
`docs/runbooks/uzum-troubleshooting.md` for the operator-facing flow.

## Config (`core/config.py`)

| Setting                 | Default                                  | Notes                                                                  |
| ----------------------- | ---------------------------------------- | ---------------------------------------------------------------------- |
| `uzum_service_id`       | `None`                                   | Empty/blank → gateway `available=False`, method hidden in the miniapp. |
| `uzum_login`            | `""`                                     | Production/cabinet Basic-auth username.                                |
| `uzum_password`         | `""`                                     | Production/cabinet Basic-auth password.                                |
| `uzum_test_login`       | `""`                                     | Sandbox Basic-auth username.                                           |
| `uzum_test_password`    | `""`                                     | Sandbox Basic-auth password.                                           |
| `uzum_open_service_url` | `"https://www.uzumbank.uz/open-service"` | The open-service checkout host.                                        |

`uzum_password`/`uzum_test_password` are in the structured-log redactor
(`core/logging.py`) — never logged. All five settings are also present in
`infra/secrets-example/api.env`.

## Files

```
apps/api/src/yupay/modules/uzum/
  models.py    -- UzumTransaction (migration 0028; amount_sum rename 0030)
  errors.py    -- the error catalogue above (pure, no I/O)
  service.py   -- the 5 webhook handlers + build_checkout_url
  routes.py    -- POST /check /create /confirm /reverse /status, Basic auth, always-200
  api.py       -- public surface (router + UzumTransaction)
```

Plus, outside this module:

- `apps/api/src/yupay/modules/payments/gateways/uzum.py` — the
  `PaymentGateway` adapter (registered as `"uzum"` in
  `payments/gateways/__init__.py:REGISTRY`).
- `apps/scheduler/src/yupay_scheduler/jobs/uzum_timeout.py` — the 30-min
  auto-fail job.
- `infra/caddy/Caddyfile.prod` — a commented-out, **not yet active** IP
  allowlist block for `/api/v1/payments/uzum/*`, pending Uzum publishing its
  webhook source IPs (design spec §16 gap #6). Basic auth (`10001`) is the
  only gate on this path meanwhile.

## Testing

`apps/api/tests/integration/test_uzum_webhook.py` and
`test_uzum_service.py` post directly at the endpoints and cover every
webhook, every error code it can emit, idempotent replay of
create/confirm/reverse, the concurrent-create `IntegrityError` → `10010`
path, and the commit-failure-still-200 path.
`apps/api/tests/integration/test_uzum_timeout.py` covers the 30-min sweep;
`apps/api/tests/unit/test_uzum_gateway.py` and `test_uzum_config.py` cover
the gateway and config gating. `payments` + `wallet` are a ≥95% coverage
tier (CLAUDE.md §8); this module is in that tier.
