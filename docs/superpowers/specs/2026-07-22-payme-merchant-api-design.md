# Payme (Paycom) Merchant API Integration — Design Spec

- **Status:** Approved (brainstorm), ready for implementation plan
- **Date:** 2026-07-22
- **Author:** @jamaomonov
- **Surfaces:** API (`apps/api`), Scheduler (`apps/scheduler`), Mini App (`apps/miniapp`), Infra (Caddy)
- **Docs studied:** https://developer.help.paycom.uz/ (Merchant API, RU pages — protocol, all method pages, error tables, data types, sandbox, checkout initiation)

---

## 1. Goal

Accept UZS card payments via **Payme Business Merchant API** — the standard Payme
checkout where Payme hosts the payment form and fiscalizes the receipt, and drives
the transaction lifecycle by calling our JSON-RPC endpoint. Ship it **sandbox-ready**:
correct enough to pass Payme's automated sandbox test suite, then flip to production
keys to go live. (Merchant API was chosen over Subscribe API in the payments-provider
discussion: Payme fiscalizes, guarantees full cancellation, and fits our
webhook/JSON-RPC-server architecture; we don't need Subscribe's own-form / saved-cards
/ autopay features and its self-fiscalization + month-limited-hold burden.)

## 2. The key architectural fact (why Payme is different)

Our existing gateways (Octo, mock, wallet) follow: `create_intent` → redirect →
provider sends **one** webhook → `verify_webhook` → done. **Payme Merchant API does
not fit that.** Merchant API makes **us a JSON-RPC 2.0 server** that Payme calls with
seven methods; Payme owns the transaction lifecycle and **our server persists and
validates the Payme transaction state** (`1` created / `2` performed / `-1` cancelled
before perform / `-2` cancelled after perform). So `verify_webhook` is not used for
Payme — the integration needs a dedicated method-dispatching endpoint + its own state
table, plus the `create_intent` half (building the checkout redirect URL).

## 3. Decisions locked during brainstorming

| Question            | Decision                                                                                                                                                                                                                                                                                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Refunds**         | Merchant API has **no merchant→Payme refund call**. Refunds are initiated in the **Payme cabinet**; Payme then calls our `CancelTransaction` (state `2`→`-2`), and we **auto-reconcile** (reverse the order + wallet via the existing refund path). Our admin "Refund" button on a Payme payment returns **409** pointing the operator to the Payme cabinet. |
| **`account` field** | `account.order_id` = our `order.id` (one-time account, one per order).                                                                                                                                                                                                                                                                                       |
| **SetFiscalData**   | Implement: store the pushed `fiscal_data` on the transaction and ack `success: true`. We do **not** generate our own receipts (Payme fiscalizes — that's the point of Merchant API).                                                                                                                                                                         |
| **v1 scope**        | Full Merchant API + sandbox-ready: all 7 methods + checkout initiation + the 12h auto-cancel job + auto-reconcile on cancel + the Payme method in the miniapp.                                                                                                                                                                                               |
| **Currency**        | Payme is **UZS-only** (amounts in tiyin). The Payme method is offered only for UZS orders.                                                                                                                                                                                                                                                                   |

## 4. Architecture overview

New module **`apps/api/src/yupay/modules/payme/`**:

- `models.py` — the `payme_transactions` table (Payme-protocol state, source of truth).
- `service.py` — the seven method handlers + validation + the checkout-URL builder.
- `routes.py` — `POST /api/v1/payments/payme/merchant`: Basic-auth check, JSON-RPC
  dispatch, always HTTP 200.
- `errors.py` — the Payme error catalogue (exact codes + localized messages).
- `api.py` — public surface.

Plus:

- `apps/api/src/yupay/modules/payments/gateways/payme.py` — the `PaymentGateway`
  adapter (`create_intent` builds the checkout URL + a pending `Payment`; `refund`
  returns the cabinet-409; `available`).
- Registered in `payments/gateways/__init__.py` REGISTRY as `"payme"` (replacing the
  current `StubGateway` slot).
- `apps/scheduler/src/yupay_scheduler/jobs/payme_timeout.py` — the 12h auto-cancel job.

```
Customer checkout (UZS order, pending_payment)
   └─ POST /api/v1/payments/intents {provider:"payme"}
        └─ PaymeGateway.create_intent → Payment(provider=payme, pending)
           + build checkout URL: base64("m=<mid>;ac.order_id=<order.id>;a=<tiyin>")
           → intent_url = https://checkout.paycom.uz/<b64>   (redirect the customer)

Payme → POST /api/v1/payments/payme/merchant  (Basic Paycom:<key>)   [JSON-RPC]
   CheckPerformTransaction → validate order+amount → {allow:true}
   CreateTransaction(id,amount,account) → payme_transactions row (state 1) → {create_time,transaction,state:1}
   PerformTransaction(id) → state 2 → _mark_payment_succeeded → order paid → fulfilment saga → {transaction,perform_time,state:2}
   CancelTransaction(id,reason) → state 1→-1 (cancel) or 2→-2 (refund: reverse order+wallet) → {transaction,cancel_time,state}
   CheckTransaction(id) → {create_time,perform_time,cancel_time,transaction,state,reason}
   GetStatement(from,to) → {transactions:[...]}
   SetFiscalData(id,type,fiscal_data) → store → {success:true}

Scheduler: payme_timeout job → transactions in state 1 older than 12h → state -1, reason 4.
```

## 5. Data model

New table **`payme_transactions`** (one migration):

| Column                    | Type                         | Notes                                                                    |
| ------------------------- | ---------------------------- | ------------------------------------------------------------------------ |
| `id`                      | uuid PK                      | our row id                                                               |
| `payme_id`                | text UNIQUE                  | Payme's transaction `id` — **idempotency key** for Create/Perform/Cancel |
| `order_id`                | uuid FK → orders             | resolved from `account.order_id`                                         |
| `payment_id`              | uuid FK → payments, nullable | our `Payment` row (created with the transaction)                         |
| `amount_tiyin`            | bigint                       | Payme's `amount` (tiyin), verbatim                                       |
| `state`                   | int                          | `1` / `2` / `-1` / `-2` (CHECK-constrained)                              |
| `reason`                  | int nullable                 | cancellation reason (1,2,3,4,5,10)                                       |
| `create_time`             | bigint                       | Payme ms timestamp (0 = unset)                                           |
| `perform_time`            | bigint                       | 0 until performed                                                        |
| `cancel_time`             | bigint                       | 0 until cancelled                                                        |
| `fiscal_data`             | jsonb nullable               | payload from `SetFiscalData`                                             |
| `created_at`/`updated_at` | timestamptz                  |                                                                          |

`Payment` (existing, provider = `"payme"`) carries our generic payment status; the
`payme_transactions` row carries Payme's protocol state. `PerformTransaction` flips the
`Payment` to succeeded via the existing single `_mark_payment_succeeded` chokepoint
(order → paid → fulfilment), so Payme reuses the whole downstream unchanged.

## 6. JSON-RPC transport + auth

- **Endpoint:** `POST /api/v1/payments/payme/merchant`. JSON-RPC 2.0 envelope
  `{method, params, id}`; response `{result, id}` or `{error:{code, message, data}, id}`.
- **Always HTTP 200** — success and business-error alike. (Payme treats any non-200 as
  RPC error `-32400`.)
- **Auth:** HTTP Basic in the `Authorization` header — `Basic base64("<login>:<key>")`.
  Login defaults to `Paycom` (the universal convention in Payme's official templates;
  the docs prose only shows a placeholder, so make the login **configurable**, default
  `Paycom`). The presented key must equal **either** the production key **or** the test
  key (both configured) so one endpoint serves sandbox and production. On mismatch →
  error **-32504** ("Недостаточно привилегий").
- **Transport errors:** non-POST → `-32300`; unparseable JSON → `-32700`; missing/
  wrong-typed RPC fields → `-32600`; unknown `method` → `-32601`. `error.message` is a
  localized object `{ru, uz, en}`; `error.data` names the offending field where
  applicable.

## 7. The seven methods (exact contract)

Amounts are **tiyin** (integer, 1 so'm = 100 tiyin). Our `order.total_charged` is a
`Decimal` in **major** UZS units → expected tiyin = `int(total_charged * 100)` (exact;
reject on any fractional-tiyin mismatch).

### CheckPerformTransaction

- Params: `amount`, `account.order_id`.
- Validate: order exists (`account.order_id`) → else **-31050** ("заказ не найден",
  `data:"order_id"`); order is `pending_payment` (not already paid / cancelled) → else
  **-31051** ("заказ недоступен к оплате / уже оплачен", `data:"order_id"`); `amount == total_charged*100` → else **-31001**.
- Success: `{allow: true}`. (May include a `detail` fiscal breakdown later; not v1 —
  Payme fiscalizes from its own catalogue.)

### CreateTransaction

- Params: `id` (Payme tx id), `time` (ms), `amount`, `account.order_id`.
- Idempotent on `id`: if a `payme_transactions` row with this `payme_id` exists,
  re-validate and return its `{create_time, transaction, state}` — never create a
  duplicate. If a **different** active transaction already exists for this order →
  **-31008**. Re-run all CheckPerform validations first (amount/account).
- Effect: insert row (state `1`, `create_time = time`), create/attach the pending
  `Payment`, keep the order reserved in `pending_payment`.
- Success: `{create_time, transaction: <payme_transactions.id>, state: 1}`.

### PerformTransaction

- Params: `id`.
- If row not found → **-31003**. If state `1` → flip to `2`, set `perform_time`, call
  `_mark_payment_succeeded` (order → paid → fulfilment). If already state `2`
  (idempotent replay) → return the stored `{transaction, perform_time, state:2}`. If
  state `< 0` → **-31008**.
- Success: `{transaction, perform_time, state: 2}`.

### CancelTransaction

- Params: `id`, `reason`.
- If row not found → **-31003**. From state `1` → `-1` (mark `Payment` cancelled,
  release the order). From state `2` → `-2` = **refund**: reverse via the existing
  refund path (order → refunded, wallet reversal, fulfilment already-delivered guard) —
  but if the order/goods were already fully delivered and can't be pulled back →
  **-31007** ("Заказ выполнен. Невозможно отменить"). Idempotent: an already-cancelled
  row returns its stored `{transaction, cancel_time, state}`. Set `cancel_time`,
  `reason`.
- Success: `{transaction, cancel_time, state: -1 | -2}`.

### CheckTransaction

- Params: `id`. Not found → **-31003**.
- Success: `{create_time, perform_time, cancel_time, transaction, state, reason}`
  (timestamps `0` when unset; `reason` `null` when none).

### GetStatement

- Params: `from`, `to` (ms). Return all `payme_transactions` with `from <= create_time
<= to`, ascending by `create_time`, each as `{id: payme_id, time, amount, account,
create_time, perform_time, cancel_time, transaction, state, reason, receivers}`.
- Success: `{transactions: [...]}`.

### SetFiscalData

- Params: `id`, `type` (`"PERFORM"`/`"CANCEL"`), `fiscal_data` (receipt_id, status_code,
  message, terminal_id, fiscal_sign, qr_code_url, date). Store `fiscal_data` on the
  transaction (keyed by type). Unknown receipt id → **-32001**.
- Success: `{success: true}`.

## 8. Error catalogue (`errors.py`)

Exact codes (from the docs) with `{ru, uz, en}` messages:

- Transport: `-32300` (non-POST), `-32700` (bad JSON), `-32600` (bad RPC fields),
  `-32601` (unknown method), `-32504` (auth), `-32400` (internal/non-200 — we always
  200, but map unexpected exceptions to `-32400`).
- Business: `-31001` (invalid amount), `-31003` (tx not found), `-31007` (already
  delivered — can't cancel), `-31008` (operation not permitted for state),
  `-31050…-31099` (merchant-defined account errors: `-31050` order not found, `-31051`
  order not payable / already paid). `-32001` (SetFiscalData receipt not found).

## 9. Checkout initiation (the `create_intent` half)

`PaymeGateway.create_intent(order)`:

1. Guard: order currency must be UZS, `total_charged > 0`.
2. Create a pending `Payment(provider="payme", external_id=..., amount=total_charged,
currency="UZS", order)`.
3. Build the param string `m=<merchant_id>;ac.order_id=<order.id>;a=<tiyin>;c=<return_url>;l=<lang>`,
   base64-encode it, and return `intent_url = "<checkout_base>/<b64>"`
   (`checkout_base` = `https://checkout.paycom.uz`, configurable → `https://test.paycom.uz`
   for sandbox).
4. Return `PaymentIntent(intent_url=..., status="pending")`.

The miniapp's existing method list (which reserved a `payme` slot as a stub) redirects
to `intent_url` on selection, same as Octo. Payme method shown only for UZS.

## 10. State machine + timeouts

- States `1`/`2`/`-1`/`-2`; reasons `1,2,3,4,5,10` (4 = timeout, 5 = refund). Legal
  transitions: Create→`1`; Perform `1`→`2`; Cancel `1`→`-1` or `2`→`-2`.
- **12h auto-cancel** (`apps/scheduler/.../payme_timeout.py`, mirrors `waxpeer_reconcile`):
  a transaction still in state `1` after `43_200_000 ms` (12h) is cancelled to `-1`,
  `reason 4`, and its order released. Runs on an interval; own-session per row.

## 11. Config (`core/config.py`)

- `payme_merchant_id: str = ""`
- `payme_key: str = ""` (production/cabinet key)
- `payme_test_key: str = ""` (sandbox key)
- `payme_login: str = "Paycom"` (Basic-auth username; convention-configurable)
- `payme_checkout_url: str = "https://checkout.paycom.uz"`
- Empty `payme_merchant_id`/`payme_key` → gateway `available = False` (method hidden in
  the miniapp), while the merchant endpoint still accepts the **test** key so sandbox
  works before production keys are set.
- `payme_key`/`payme_test_key` added to the log redactor (`core/logging.py`), like the
  other acquirer secrets. Added to `docker-compose.yml` + `infra/secrets-example/api.env`.
- **Caddy (optional hardening):** restrict `POST /api/v1/payments/payme/merchant` to
  Payme's source IPs `185.234.113.1`–`185.234.113.15`.

## 12. Error handling / edge cases

- **Idempotency** is protocol-mandated: Create/Perform/Cancel must be safe to replay
  (Payme retries on a lost response). Enforced by the `UNIQUE(payme_id)` row + state
  guards.
- **Concurrency:** claim the `payme_transactions` row `FOR UPDATE` within each method so
  two concurrent Perform/Cancel calls for the same `id` serialize.
- **Never leak PII / secrets:** never log the Basic-auth key, card data, or the raw
  account; log `payme_id` + method + code only.
- **Amount exactness:** reject if `total_charged*100` is not an exact integer match to
  `amount` (no silent rounding).
- **Unexpected exceptions** inside a handler → catch and return `-32400` with HTTP 200
  (never a 5xx to Payme).

## 13. Testing

- **Integration tests** (`apps/api/tests/integration/test_payme_merchant.py`) — we are
  the server: POST JSON-RPC to the endpoint and assert responses for **every method +
  every error code**, plus Payme's **two mandatory sandbox sequences** verbatim:
  1. _Unconfirmed_: wrong auth (`-32504`), invalid amount (`-31001`), non-existent
     account (`-31050`), then CheckPerform → Create → Cancel (state `1`→`-1`).
  2. _Confirmed_: CheckPerform → Create (order→awaiting) → Perform (order→paid,
     fulfilment kicks) → Cancel (state `2`→`-2`, refund reconciled).
     Plus: idempotent replay of Create/Perform/Cancel; amount-mismatch; `GetStatement`
     window; `SetFiscalData` store; the 12h timeout job. `payments`/`wallet` coverage tier
     is **≥ 95%** (CLAUDE.md §8) — this module is in that tier.
- **Contract test** of the checkout-URL builder (exact base64 of a known param string).
- **Real sandbox** (`test.paycom.uz`): set the register's Endpoint URL + test key, run
  Payme's automated suite. Then **go-live**: production key + `checkout.paycom.uz`.

## 14. Docs

- **ADR-0034** — new `payme` module + the "we are the provider's JSON-RPC server"
  pattern (contrast with `verify_webhook`), the refund-via-cabinet decision, the
  amount/tiyin + account/order_id conventions, and why Merchant API over Subscribe.
- `apps/api/src/yupay/modules/payme/README.md` — the 7 methods, the state machine, the
  error catalogue, auth, config.
- `docs/runbooks/payme-troubleshooting.md` — sandbox setup, go-live switch, reading a
  stuck transaction, the refund-via-cabinet flow, the 12h job, IP allowlist.
- `docs/architecture/module-map.md` + a sequence diagram
  `docs/architecture/sequence-diagrams/payme-payment.mmd`.
- Regenerate `docs/api/openapi.json` (the merchant endpoint + intent provider).

## 15. Out of scope (v1)

- **Subscribe API** (own form, saved cards, one-click, autopay, invoices,
  self-fiscalization).
- **Our-side fiscal receipt generation** — Payme fiscalizes; we only store what
  `SetFiscalData` pushes.
- **`ChangePassword`** — absent from the current Payme method index; not implemented.
- **Split payments (`receivers`)** — we return no `receivers` (single-merchant); the
  field is echoed in `GetStatement` as empty.
- Programmatic merchant-initiated refunds (not offered by Merchant API — see §3).

## 16. Documentation gaps flagged (not silently assumed)

- **Basic-auth login string**: `Paycom` by strong convention (official templates), not
  quoted in the docs prose → made configurable (`payme_login`, default `Paycom`).
- **Merchant response timeout in seconds**: not stated in the docs → not hardcoded; we
  just answer fast and idempotently (Payme retries on loss).
- **Production checkout host**: docs show both `checkout.paycom.uz` and `paycom.uz` →
  configurable (`payme_checkout_url`), default `checkout.paycom.uz`.

## 17. Build order (feeds the plan)

1. Migration + `payme_transactions` model.
2. `errors.py` (Payme error catalogue) — pure.
3. `service.py` method handlers (TDD, each method + error).
4. `routes.py` JSON-RPC endpoint + Basic auth + dispatch + mount.
5. `gateways/payme.py` adapter (create_intent checkout URL + refund-409) + REGISTRY swap.
6. Scheduler 12h auto-cancel job + register.
7. Config + log redactor + compose + secrets-example + Caddy allowlist.
8. miniapp Payme method (UZS-only) + i18n ×3.
9. OpenAPI/client regen.
10. Docs (ADR-0034, README, runbook, sequence diagram, module-map).
