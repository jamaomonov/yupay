# `payme` — Payme (Paycom) Merchant API

Payme's hosted-checkout acquirer for the UZ market. Unlike every other
`payments` gateway, Payme does not deliver a webhook to us — **we are Payme's
JSON-RPC server**: Payme calls seven methods against one endpoint over the
full life of a transaction, and its own protocol state (not ours) is
authoritative until the transaction settles. See
[ADR-0034](../../../../../../docs/decisions/0034-payme-merchant-api.md) for the
full rationale, and `apps/api/src/yupay/modules/payments/README.md` for the
generic gateway contract this module deliberately does not use for its
callback path.

## Endpoint + auth

```
POST /api/v1/payments/payme/merchant
GET  /api/v1/payments/payme/merchant   -- answers -32300 (not 405); Payme never calls it
```

- **Transport:** JSON-RPC 2.0. Request `{"method", "params", "id"}`; response
  `{"result": ..., "id": ...}` or `{"error": {"code", "message", "data"}, "id": ...}`.
- **Always HTTP 200.** Payme reads any non-200 as `-32400`, so auth failures,
  bad JSON, unknown methods, and internal errors all come back **200** with an
  `error` body — never a raised HTTP exception.
- **Auth:** `Authorization: Basic base64("<login>:<key>")`. `login` must equal
  `payme_login` (default `"Paycom"`); `key` must equal **either**
  `payme_key` (production) **or** `payme_test_key` (sandbox) — both are
  checked so the same deployed endpoint serves Payme's sandbox test suite and
  production traffic without a code branch. Empty configured keys never
  match. Failure → `-32504`.

## Amounts and account

- Amounts are **tiyin** (integer minor units, 1 so'm = 100 tiyin). Our
  `order.total_charged` is a `Decimal` in major UZS units; the expected
  amount is `int(total_charged * 100)`, required to be an **exact** integer —
  any fractional-tiyin mismatch is `-31001`, never silently rounded.
- `account.order_id` = our `order.id` (one-time account, one per order). No
  other `account` fields are interpreted.

## The seven methods

All params/results below are the JSON-RPC `params`/`result` object shapes;
errors are raised as `PaymeError` and rendered via `to_rpc_error()`.

### `CheckPerformTransaction`

- **Params:** `amount` (tiyin), `account.order_id`.
- **Result:** `{"allow": true}`.
- **Errors:** `-31050` (unknown order), `-31051` (order not `pending_payment`
  — not payable or already paid), `-31001` (amount mismatch).

### `CreateTransaction`

- **Params:** `id` (Payme's transaction id), `time` (epoch ms), `amount`,
  `account.order_id`.
- **Result:** `{"create_time", "transaction", "state": 1}`.
- **Idempotent** on `id`: a replay re-validates the amount and echoes the
  stored row rather than creating a duplicate. A **different** active
  transaction already open on the same order → `-31099` (Payme mandates an
  account-range code, not `-31008`, for a busy order — the sandbox asserts this).
- **Errors:** `-31050`/`-31051`/`-31001` (same validation as
  `CheckPerformTransaction`), `-31099` (another active transaction exists for
  this order).

### `PerformTransaction`

- **Params:** `id`.
- **Result:** `{"transaction", "perform_time", "state": 2}`.
- **Effect:** state `1` → `2`; calls
  `payments.service.settle_provider_payment` — the payment is marked
  succeeded through the same chokepoint every gateway uses, which flips the
  order to `paid` and starts fulfilment. A replay on an already-performed
  transaction echoes the stored result (no double-settle).
- **Errors:** `-31003` (unknown transaction), `-31008` (transaction already
  cancelled, state `< 0`).

### `CancelTransaction`

- **Params:** `id`, `reason` (Payme's cancellation reason code, stored as-is).
- **Result:** `{"transaction", "cancel_time", "state": -1 | -2}`.
- **Routes strictly by the transaction's current state** — this is where
  money-safety lives:
  - **state `1`** (created, never performed) → `-1`. No ledger, no refund;
    calls `payments.service.cancel_pending_provider_payment` (payment →
    `cancelled`, order stays `pending_payment`, released for retry).
  - **state `2`** (performed) → `-2`, a **refund**. Calls
    `payments.service.reverse_provider_payment`, which reuses the same
    `_apply_refund_reversal` core an admin refund uses (order → `refunded`,
    ledger reversal). **Refused with `-31007`** if the order is
    `fulfilled`/`delivered` **or** if _any single_ `FulfillmentTask` for the
    order has already reached `succeeded` — a multi-item order can sit at
    `fulfilling` with one item already shipped, and this guard catches that
    case even though the whole-order status wouldn't. Such an order is never
    auto-refunded; it needs manual reconciliation.
- **Idempotent:** a replay on an already-cancelled transaction (`-1` or `-2`)
  echoes the stored result.
- **Errors:** `-31003` (unknown transaction), `-31007` (goods already
  delivered).

### `CheckTransaction`

- **Params:** `id`.
- **Result:** `{"create_time", "perform_time", "cancel_time", "transaction", "state", "reason"}` —
  unset timestamps are `0`; `reason` is `null` until cancelled.
- **Errors:** `-31003` (unknown transaction).

### `GetStatement`

- **Params:** `from`, `to` (epoch ms window, inclusive both ends).
- **Result:** `{"transactions": [...]}`, ascending by `create_time`. Each row:
  `{id, time, amount, account, create_time, perform_time, cancel_time, transaction, state, reason, receivers}`.
  `receivers` is always `[]` — YuPay is a single-merchant integration, no
  split payments.

### `SetFiscalData`

- **Params:** `id`, `type` (`"PERFORM"` / `"CANCEL"`), `fiscal_data` (Payme's
  receipt payload — `receipt_id`, `status_code`, `message`, `terminal_id`,
  `fiscal_sign`, `qr_code_url`, `date`).
- **Result:** `{"success": true}`.
- **Effect:** stores `fiscal_data` on the transaction, keyed by `type`. YuPay
  never generates its own fiscal receipt — Payme fiscalizes; we only persist
  what it pushes.
- **Errors:** `-32001` (no matching transaction).

## State machine

```
Create → state 1 (created)
   1 --Perform--> 2 (performed)         -- order paid, fulfilment starts
   1 --Cancel----> -1 (cancelled, never performed)  -- no ledger
   2 --Cancel----> -2 (cancelled after performed)   -- refund, ledger reversed
```

`reason` codes are Payme's own (`1, 2, 3, 4, 5, 10`); this integration sets
`reason = 4` itself for the scheduler's timeout cancel (below) and otherwise
stores whatever Payme sends verbatim.

### 12h auto-cancel

`apps/scheduler/src/yupay_scheduler/jobs/payme_timeout.py` runs every 5
minutes and cancels any transaction still in state `1` older than
`TIMEOUT_MS` (43,200,000 ms = 12h) — a buyer who opened Payme's checkout UI
and never completed or abandoned it, so Payme never called back at all. Each
stale transaction is re-checked `FOR UPDATE` immediately before writing (a
concurrent `PerformTransaction`/`CancelTransaction` may have already resolved
it) and is cancelled in its own session so one bad row never blocks the rest
of the sweep. Sets state `-1`, `reason 4`.

## Error catalogue (`errors.py`)

Every error carries a trilingual `{ru, uz, en}` message; `data` names the
offending field where Payme's spec calls for it.

| Code     | Meaning                                                |
| -------- | ------------------------------------------------------ |
| `-31001` | Invalid amount (mismatch vs. `order.total_charged`)    |
| `-31003` | Transaction not found                                  |
| `-31007` | Order already delivered — cannot cancel/refund         |
| `-31008` | Operation not permitted for the transaction's state    |
| `-31050` | Order not found (`account.order_id`)                   |
| `-31051` | Order not payable, or already paid                     |
| `-31099` | Order already has a different in-progress transaction  |
| `-32001` | `SetFiscalData`: no matching fiscal receipt            |
| `-32300` | Request was not an HTTP POST                           |
| `-32400` | Internal error (unexpected exception; always HTTP 200) |
| `-32504` | Basic-auth credentials invalid                         |
| `-32600` | JSON-RPC envelope missing/mistyped required fields     |
| `-32601` | Unknown `method`                                       |
| `-32700` | Request body is not valid JSON                         |

## Checkout initiation (`build_checkout_url`)

`PaymeGateway.create_intent` (in `payments/gateways/payme.py`) never calls a
Payme API — the checkout link is built **entirely client-side**:

```
params = "m=<payme_merchant_id>;ac.order_id=<order.id>;a=<amount_tiyin>[;c=<return_url>];l=<lang>"
intent_url = "<payme_checkout_url>/" + base64(params)
```

The gateway validates `order.currency == "UZS"` and that
`total_charged * 100` is an exact integer before building the URL (Payme is
offered only for UZS orders). `refund()` on this gateway always raises
`PaymentGatewayError` — see "Refunds" below.

## Refunds

Merchant API has **no merchant→Payme refund call**. An operator refunds from
the **Payme cabinet**; Payme then calls our `CancelTransaction` on the
performed transaction (state `2`→`-2`), which auto-reconciles the order and
ledger (see `CancelTransaction` above). The admin "Refund" button on a Payme
payment therefore returns **409**, directing the operator to the cabinet
instead of silently doing nothing. See
`docs/runbooks/payme-troubleshooting.md` for the operator-facing flow.

## Config (`core/config.py`)

| Setting              | Default                        | Notes                                                                                         |
| -------------------- | ------------------------------ | --------------------------------------------------------------------------------------------- |
| `payme_merchant_id`  | `""`                           | Empty → gateway `available=False`, method hidden in the miniapp.                              |
| `payme_key`          | `""`                           | Production/cabinet key.                                                                       |
| `payme_test_key`     | `""`                           | Sandbox key. Endpoint accepts this even with prod creds unset — sandbox works before go-live. |
| `payme_login`        | `"Paycom"`                     | Basic-auth username; not documented as contractual, but universal in Payme's own templates.   |
| `payme_checkout_url` | `"https://checkout.paycom.uz"` | Set to `https://test.paycom.uz` for sandbox.                                                  |

`payme_key`/`payme_test_key` are in the structured-log redactor
(`core/logging.py`) — never logged. Both are also present in
`docker-compose.yml` and `infra/secrets-example/api.env`.

## Files

```
apps/api/src/yupay/modules/payme/
  models.py    -- PaymeTransaction (migration 0027)
  errors.py    -- the error catalogue above (pure, no I/O)
  service.py   -- the 7 method handlers + build_checkout_url
  routes.py    -- POST /api/v1/payments/payme/merchant, Basic auth, JSON-RPC dispatch
  api.py       -- public surface (router + PaymeTransaction)
```

Plus, outside this module:

- `apps/api/src/yupay/modules/payments/gateways/payme.py` — the
  `PaymentGateway` adapter (registered as `"payme"` in
  `payments/gateways/__init__.py:REGISTRY`).
- `apps/scheduler/src/yupay_scheduler/jobs/payme_timeout.py` — the 12h
  auto-cancel job.
- `infra/caddy/Caddyfile.prod` — restricts the merchant path to Payme's
  source IPs `185.234.113.0/28` via `client_ip` (defense-in-depth alongside
  the Basic-auth check; does not replace it).

## Testing

`apps/api/tests/integration/test_payme_merchant.py` posts JSON-RPC directly at
the endpoint and covers every method, every error code, both of Payme's
mandatory sandbox sequences (unconfirmed and confirmed), idempotent replay of
Create/Perform/Cancel, and the commit-failure-still-200 path. `payments` +
`wallet` are a ≥95% coverage tier (CLAUDE.md §8); this module is in that tier.
