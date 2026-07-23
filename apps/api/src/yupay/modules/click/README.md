# `click` — Click Shop API

Click's hosted-checkout acquirer for the UZ market — the fourth Uzbek acquirer
alongside Octo, Payme, and Uzum. Like Payme and Uzum, Click does not deliver a
webhook to us — **we are Click's Shop API server**: Click calls **two** plain
HTTP endpoints against our server as the customer pays, and **we own the
transaction state machine** and its idempotency (`ClickTransaction.status`),
the same shape Uzum's Merchant API established. See
[ADR-0036](../../../../../../docs/decisions/0036-click-shop-api.md) for the
full rationale, and `apps/api/src/yupay/modules/uzum/README.md` for the
sibling integration this one mirrors — adapted for Click's own transport
(form-encoded + MD5 signature instead of JSON + Basic auth) and its **two**
services sharing one merchant.

## Endpoints + auth

```
POST /api/v1/payments/click/prepare
POST /api/v1/payments/click/complete
```

- **Transport:** `application/x-www-form-urlencoded` `POST` (not JSON, unlike
  Payme/Uzum) — the route layer reads the raw form fields itself; FastAPI's
  request-model validation never fires, so a missing/malformed field is `-8`,
  never a 422. Response is JSON.
- **Always HTTP 200.** Click reads any non-200 as a transport failure, so
  signature failures, bad fields, and internal errors all come back **200**
  with `{"error": <int>, "error_note": <str>, ...echo}`, where `echo` carries
  back whichever of `click_trans_id`/`merchant_trans_id` the request supplied
  (built by `_echo()`, straight off the raw form — never off the parsed/typed
  fields, so it still works even when the field being validated is itself
  missing). A stray non-`POST` request on either path (`GET`/`PUT`/`PATCH`/
  `DELETE`/`HEAD`/`OPTIONS`) is answered **`-8`** (`bad_request`, "Error in
  request from click") at HTTP 200, `include_in_schema=False` — Click's
  catalogue has no dedicated "wrong method" code, and `-3` is reserved for the
  body's `action` field, not the transport verb.
- **Auth: MD5 `sign_string`**, keyed on a **per-service** `SECRET_KEY` — see
  "Signature" below. There is no Basic auth here (contrast Payme/Uzum).

## Amounts and the two services

- **`amount` is soums** (major units, e.g. `"1000.00"`) — unlike the tiyin
  every other Uzbek acquirer here uses. It is compared to `order.total_charged`
  (also soums) via `Decimal(str(amount))`, never float `==`.
- Click gave us **two services sharing one merchant** (`click_merchant_id`):
  the web storefront (`click_service_id_web`, secret `click_secret_key_web`)
  and the Telegram mini app (`click_service_id_bot`, secret
  `click_secret_key_bot`). The inbound `service_id` field picks:
  - which secret verifies the `sign_string` (`signature.secret_for_service`);
  - which `payments` provider backs the transaction — `"click"` for the web
    service, `"click_miniapp"` for the bot service
    (`service._provider_for_service`).

  `secret_for_service` returns `None` — treated as an unknown/unauthorized
  service, i.e. `-1` — when `service_id` matches neither configured id, or
  when it matches one but that service's secret is blank; a half-configured
  service never silently verifies against an empty key.

## Signature (`signature.py`)

Every request carries `sign_time` + `sign_string`. Verification:

1. `secret_for_service(service_id)` — `None` → **`-1`**.
2. Build the MD5 over the **raw wire string values** Click sent (never
   reformatted — Click's own MD5 is computed over those exact bytes):
   - **Prepare:**
     `md5(click_trans_id + service_id + secret + merchant_trans_id + amount + action + sign_time)`
   - **Complete:**
     `md5(click_trans_id + service_id + secret + merchant_trans_id + merchant_prepare_id + amount + action + sign_time)`
     (same formula, with `merchant_prepare_id` inserted right after
     `merchant_trans_id`).
3. `verify()` compares case-insensitively and constant-time
   (`hmac.compare_digest`), stripping incidental surrounding whitespace off
   the received `sign_string`. A non-ASCII `sign_string` would raise
   `TypeError` inside `compare_digest`; `verify()` catches it and fails closed
   (`False`) rather than letting it propagate — mismatch either way → **`-1`**
   (`SIGN CHECK FAILED!`).

## The two webhooks

All shapes below are the JSON response bodies; errors are raised as
`ClickError` and rendered via `to_response(**echo)`.

### `POST /prepare` (`action = 0`)

- **Request fields** (form-encoded): `click_trans_id`, `service_id`,
  `click_paydoc_id`, `merchant_trans_id`, `amount`, `action`, `error`,
  `error_note`, `sign_time`, `sign_string`. All required and non-empty — any
  missing/empty field, or one that fails `int()` parsing
  (`click_trans_id`/`service_id`/`click_paydoc_id`/`action`/`error`) → **`-8`**.
  `error_note` is required by contract but never read for any decision.
- **Success:**
  `{"click_trans_id", "merchant_trans_id", "merchant_prepare_id", "error": 0, "error_note": "Success"}`.
- **Logic** (`service.prepare`):
  1. Signature check → **`-1`**; `action != 0` → **`-3`**.
  2. Inbound `error < 0` (Click aborted) → `service.cancel` (by
     `click_trans_id`+`service_id`), commit, return **`-9`**
     (`transaction_cancelled`) — see "The negative-error rule" below.
  3. A row already exists for `(click_trans_id, service_id)` → return **that**
     row's response unchanged (idempotent replay; no error).
  4. Resolve the order by `merchant_trans_id` (`FOR UPDATE`); missing →
     **`-5`** (`user_not_found`).
  5. Order already `paid` → **`-4`** (`already_paid`); any other
     non-`pending_payment` status (cancelled/expired/refunded/further along)
     → **`-9`**.
  6. `Decimal(str(amount)) != order.total_charged` → **`-2`**
     (`incorrect_amount`).
  7. Resolve the provider from `service_id` (`"click"`/`"click_miniapp"`),
     reuse the order's existing pending payment for that provider or create
     one, insert the `ClickTransaction` (status `PREPARED`) inside a
     `SAVEPOINT` — a concurrent first-time Prepare for the same pair raises
     `IntegrityError` on the unique `(click_trans_id, service_id)`; the loser
     catches it, re-reads the winner's row, and returns **its**
     `merchant_prepare_id` instead of erroring (mirrors the Uzum §12
     savepoint fix).
  8. Return `error: 0` + the allocated `merchant_prepare_id`.
- Any other exception while committing → rolled back, rendered **`-7`**
  (`failed_to_update`) at HTTP 200, never a 500.

### `POST /complete` (`action = 1`)

- **Request fields**: `click_trans_id`, `service_id`, `click_paydoc_id`
  (required by contract, validated but never used by `complete()`),
  `merchant_trans_id`, `merchant_prepare_id`, `amount`, `action`, `error`,
  `error_note` (required, unused), `sign_time`, `sign_string`. Same `-8` rule
  for missing/malformed fields.
- **Success:**
  `{"click_trans_id", "merchant_trans_id", "merchant_confirm_id", "error": 0, "error_note": "Success"}` —
  `merchant_confirm_id` is the **same** numeric id as `merchant_prepare_id`,
  not a separate confirm sequence.
- **Logic** (`service.complete`):
  1. Signature check → **`-1`**; `action != 1` → **`-3`**.
  2. Inbound `error < 0` → `service.cancel` (by `merchant_prepare_id`), commit,
     return **`-9`**.
  3. Load the `ClickTransaction` by `merchant_prepare_id`; missing, or its
     stored `click_trans_id`/`service_id`/`order_id` don't match the request
     → **`-6`** (`transaction_not_found`).
  4. Already `CONFIRMED` → **`-4`** (`already_paid` — Click's replay signal).
     Already `CANCELLED` → **`-9`**.
  5. `Decimal(str(amount)) != txn.amount` → **`-2`**.
  6. `payments.service.settle_provider_payment` (payment → `succeeded`, order
     → `paid`, fulfilment starts); set `status = CONFIRMED` +
     `complete_time`.
  7. Return `error: 0` + `merchant_confirm_id`.
- Any other exception while committing → rolled back, rendered **`-7`** at
  HTTP 200.

### The negative-inbound-`error` cancel rule

Per Click's docs: on receiving a negative `error` in the **request**, the
merchant must cancel the payment and answer **`-9`**. Both webhooks implement
this identically, ahead of any other business check: `service.cancel()` looks
up the transaction (by `merchant_prepare_id` on Complete, or by
`(click_trans_id, service_id)` on Prepare — the only pair Click sends there),
and is a no-op if there's nothing to cancel or it's already `CANCELLED`.

**Money-safety** (carried forward from the Uzum final-review lesson):
`_ensure_payment` can share one pending payment across several transactions on
the same order (a customer retrying checkout). `cancel()` only ever
cancel-pends the backing payment while it is still `pending` — if a **sibling**
transaction already confirmed that payment while this one is still `PREPARED`,
cancelling here never claws back the now-succeeded payment. A transaction that
is itself already `CONFIRMED` is left entirely alone (Click v1 has no
merchant-initiated refund, so a settled transaction is never touched by this
path).

## State machine

```
/prepare  → PREPARED           -- idempotent replay on (click_trans_id, service_id)
/complete → CONFIRMED           -- settle_provider_payment: order paid, fulfilment starts
negative inbound error (either webhook) → CANCELLED -- cancel_pending_provider_payment guard, no ledger
PREPARED  --30-min stale sweep--> CANCELLED         -- click_timeout.py, same guard
```

`ClickTransaction.status` is our own machine (`PREPARED` / `CONFIRMED` /
`CANCELLED`, enforced by a `CHECK` constraint), `UNIQUE` on
`(click_trans_id, service_id)` so `/prepare` is idempotent against replays;
`/complete` is looked up by the `merchant_prepare_id` we issued. `CONFIRMED`
is terminal here — Click v1 has no merchant-initiated reversal; see "Refunds"
below.

### 30-minute stale-prepare sweep

`apps/scheduler/src/yupay_scheduler/jobs/click_timeout.py` runs every 5
minutes and cancels any `PREPARED` transaction whose `prepare_time` is older
than `TIMEOUT` (30 minutes — Click's own window is unconfirmed; §16 open
decision #4) — the dead-letter case where `/complete` never arrives (buyer
abandonment, dropped callback). Every stale row is routed through the exact
same `click.service.cancel()` helper the negative-error webhook path uses
(keyed by `merchant_prepare_id`), which re-checks the row is still `PREPARED`
under `FOR UPDATE` immediately before writing (a concurrent `/complete` may
have already confirmed it — left alone) and only cancels the backing payment
while it is still `pending`. Each stale transaction is cancelled in its own
session, so one bad row never blocks the rest of the sweep.

## Error catalogue (`errors.py`)

| Code | `error_note`                  | Emitted by        | When                                                                                    |
| ---- | ----------------------------- | ----------------- | --------------------------------------------------------------------------------------- |
| `0`  | `Success`                     | prepare, complete | operation ok                                                                            |
| `-1` | `SIGN CHECK FAILED!`          | prepare, complete | signature mismatch, or `service_id` matches no configured/secret-set service            |
| `-2` | `Incorrect parameter amount`  | prepare, complete | `amount` ≠ order's (`prepare`) / transaction's (`complete`) recorded amount             |
| `-3` | `Action not found`            | prepare, complete | `action` isn't `0` (prepare) / `1` (complete)                                           |
| `-4` | `Already paid`                | prepare, complete | order already `paid` (prepare); transaction already `CONFIRMED` (complete)              |
| `-5` | `User does not exist`         | prepare           | `merchant_trans_id` (order) not found                                                   |
| `-6` | `Transaction does not exist`  | complete          | `merchant_prepare_id` not found, or mismatched `click_trans_id`/`service_id`/`order_id` |
| `-7` | `Failed to update user`       | prepare, complete | unexpected exception, or commit failure, while prepare/complete/cancel run              |
| `-8` | `Error in request from click` | prepare, complete | missing/empty/malformed form field, unparseable body, or a non-`POST` request           |
| `-9` | `Transaction cancelled`       | prepare, complete | order not payable / already cancelled txn / negative inbound `error` → cancel           |

## Checkout initiation (`build_checkout_url`)

`ClickGateway.create_intent` (in `payments/gateways/click.py`) never calls a
Click API — the checkout link is a plain query-string GET URL built entirely
client-side, exactly like Payme/Uzum's own deep links:

```
https://my.click.uz/services/pay?service_id=<web 108149 | bot 108150>&merchant_id=<click_merchant_id>&amount=<amount>&transaction_param=<order.id>&return_url=<return_url>
```

`transaction_param` is our order id — Click echoes it back as
`merchant_trans_id` on both webhooks. The gateway guards
`order.currency == "UZS"` and `total_charged > 0` before building the URL.

### Two-provider surface routing

`ClickGateway` is parametrised by `provider` (`"click"` for the web storefront,
`"click_miniapp"` for the Telegram mini app) — **one class backs both**
registry entries (`payments/gateways/__init__.py:REGISTRY["click"]` /
`REGISTRY["click_miniapp"]`) instead of two near-duplicate files.
`build_checkout_url(provider=...)` picks `click_service_id_web` for `"click"`,
`click_service_id_bot` for `"click_miniapp"`, raising `ValueError` for any
other provider string. Each frontend surface selects its own provider id at
checkout (web → `click`, mini app → `click_miniapp`); the **inbound**
Prepare/Complete side is unaffected by this choice — it always routes purely
by the request's own `service_id` field (`signature.secret_for_service` /
`service._provider_for_service`).

`ClickGateway.verify_webhook` always raises `PaymentNotIntegratedError` (Click
never calls the generic `/webhooks/payments/{provider}` route), and
`refund()` always raises `PaymentGatewayError` — see "Refunds" below.

## Refunds

Click v1 has **no merchant-initiated refund call** — reversal is entirely
Click-side (their Merchant API `/cancel` or the merchant cabinet), out of
scope for this integration (design spec §15). `ClickGateway.refund()`
therefore always raises `PaymentGatewayError`, mirroring Uzum's `refund()`.
The only cancellation path this module implements is the negative-inbound-
`error` rule and the stale-prepare sweep above, both of which only ever
cancel a still-`pending` payment, never reverse a settled one.

## Config (`core/config.py`)

| Setting                      | Default                              | Notes                                                             |
| ---------------------------- | ------------------------------------ | ----------------------------------------------------------------- |
| `click_merchant_id`          | `None`                               | Shared across both services.                                      |
| `click_service_id_web`       | `None`                               | `yupay.uz` service (`108149`).                                    |
| `click_service_id_bot`       | `None`                               | Telegram mini-app service (`108150`).                             |
| `click_secret_key_web`       | `""`                                 | `SECRET_KEY` for the web service.                                 |
| `click_secret_key_bot`       | `""`                                 | `SECRET_KEY` for the bot service.                                 |
| `click_merchant_user_id_web` | `None`                               | `88645` — carried for reference; not read by this module's logic. |
| `click_merchant_user_id_bot` | `None`                               | `88644` — same.                                                   |
| `click_pay_url`              | `"https://my.click.uz/services/pay"` | The checkout host used by `build_checkout_url`.                   |

Blank/empty env values coerce to `None` for the int fields (same convention
as Uzum's service id). `click_secret_key_web`/`click_secret_key_bot` are in
the structured-log redactor (`core/logging.py`) — never logged.
`ClickGateway.available` (per provider instance) is `True` only when
`click_merchant_id` **and** that surface's own service id **and** secret are
all set — a half-configured service is unavailable, not silently accepting an
empty secret.

## Files

```
apps/api/src/yupay/modules/click/
  models.py     -- ClickTransaction (migration 0029)
  errors.py     -- the error catalogue above (pure, no I/O)
  signature.py  -- sign_string build (prepare/complete) + secret_for_service + verify
  service.py    -- prepare / complete / cancel handlers + build_checkout_url
  routes.py     -- POST /prepare /complete, form-encoded, MD5-signed, always-200
  api.py        -- public surface (router + ClickTransaction)
```

Plus, outside this module:

- `apps/api/src/yupay/modules/payments/gateways/click.py` — the
  `PaymentGateway` adapter, registered as both `"click"` and `"click_miniapp"`
  in `payments/gateways/__init__.py:REGISTRY`.
- `apps/scheduler/src/yupay_scheduler/jobs/click_timeout.py` — the 30-minute
  stale-prepare sweep.
- No Caddy IP allowlist is configured for this path — the signature is the
  gate (design spec §16 gap #6, same open question as Uzum's source IPs).

## Testing

`apps/api/tests/integration/test_click_webhook.py` and
`test_click_service.py` post directly at the endpoints and cover every
webhook, every error code it can emit, idempotent replay of prepare/complete,
the concurrent-prepare `IntegrityError` → same-id path, the negative-error
cancel rule, and the money-safety guard on a shared payment. `test_click_timeout.py`
covers the 30-min sweep; `test_click_signature.py` covers both `sign_string`
formulas, the per-service secret selection, and `verify()`'s constant-time /
fail-closed behaviour; `test_click_errors.py` covers the error catalogue;
`test_click_gateway.py` covers the two-provider gateway's `available` gating
and `create_intent` URL-building. `payments` + `wallet` are a ≥95% coverage
tier (CLAUDE.md §8); this module is in that tier.
