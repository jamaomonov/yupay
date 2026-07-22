# Uzum Bank Merchant API Integration — Design Spec

> Status: draft for review. Companion to the Payme Merchant API integration
> (`2026-07-22-payme-merchant-api-design.md`) — Uzum's Merchant API is the same
> _inverted_ webhook model, so this spec deliberately mirrors the Payme one and
> calls out only where Uzum differs.

**Source of truth:** Uzum Bank official docs, Merchant API (rendered from
`https://developer.uzumbank.uz/en/merchant/`), captured 2026-07-22. All request
/ response shapes, status strings, and error codes below are quoted from there.

---

## 1. Goal

Let a customer pay for a YuPay order with **Uzum Bank** (Uzbekistan). Uzum is a
new acquirer alongside Octo and Payme. Like Payme, it is an **inverted** API:
Uzum calls **us**. The integration must be **sandbox-ready** so Uzum's engineer
(manual tester) can drive our endpoints before go-live.

---

## 2. The key architectural fact (why Uzum, like Payme, is different)

Octo is a classic gateway: **we** call **it**, then it calls our webhook once.

Uzum inverts that. Uzum drives the whole payment by calling **five HTTPS
`POST` webhooks on our server** as the customer pays in the Uzum app:

- `POST /check` — may this order be paid for these params?
- `POST /create` — register a pending transaction (`transId`, `amount`).
- `POST /confirm` — Uzum debited the customer; deliver the goods.
- `POST /reverse` — cancel / refund a transaction.
- `POST /status` — report a transaction's current state.

We **own the transaction state machine** and its idempotency. Every webhook is
authenticated with HTTP Basic + a `serviceId`, and answered with a JSON body
carrying a `status` (or `status: FAILED` + `errorCode`).

This is the Payme model with different verbs. We reuse the exact same
`payments` provider-lifecycle chokepoints Payme uses, so a second acquirer never
becomes a second code path that flips order status or posts the ledger.

---

## 3. Decisions locked during brainstorming

1. **Full Merchant API + sandbox-ready.** Implement all five webhooks so Uzum's
   manual test suite passes end-to-end before go-live.
2. **`account` field = our `order_id`.** The `params` object Uzum sends on
   `/check` and `/create` carries the account attributes we configure with Uzum
   per service; we use **`order_id`** (exactly as we did for Payme's
   `account.order_id`).
3. **Refund policy mirrors Payme.** `/reverse` on a confirmed transaction whose
   goods are **already delivered** is refused with **`10017`** (the "transaction
   cannot be cancelled in its current state" code) — the same money-safety rule
   as Payme's `-31007`. A confirmed-but-not-yet-delivered order reverses cleanly
   (ledger reversal via the shared payments hook).
4. **Idempotency follows Uzum's spec, not Payme's echo.** Uzum signals replays
   with **dedicated codes**: repeat `/create` → `10010`, repeat `/confirm` on a
   confirmed tx → `10016`, repeat `/reverse` on a reversed tx → `10018`. `/status`
   is the reconciliation channel (Uzum retries it up to 10× after a `/confirm`
   error/timeout). See §12.
5. **Credentials are env-configured on our side.** For the sandbox / manual test
   we generate the Basic `login`/`password` and a placeholder `serviceId`
   ourselves and hand them to Uzum. Uzum's docs say credentials are "provided by
   our team" for production; the chat with their engineer says we define them for
   testing. We make all three env-configurable so either model works, and confirm
   the production source with Uzum (§16).
6. **Amount is exact tiyin.** `amount` is `int64` tiyin. Expected value is
   `int(order.total_charged * 100)`; a non-integral product is corrupt data →
   `10011` (invalid amount). Order totals are already rounded to whole so'm at
   checkout (`orders.service._round_to_payable`), so every tiyin value is exact.

---

## 4. Architecture overview

New module `apps/api/src/yupay/modules/uzum/`, structured exactly like `payme/`:

```
modules/uzum/
├── api.py        # public interface (re-exports service + gateway wiring)
├── models.py     # UzumTransaction (migration 0028)
├── errors.py     # UzumError(code, message) + to_response() + factories
├── service.py    # 5 handlers + build_checkout_url
├── routes.py     # POST /check /create /confirm /reverse /status, Basic auth
├── README.md
└── tests/        # (tests live under apps/api/tests/, per repo convention)
```

Mounted under `apps/api/src/yupay/api/v1/__init__.py` at
`/api/v1/payments/uzum/*`. Reuses the payments lifecycle hooks:

- `payments.service.settle_provider_payment` — on `/confirm`.
- `payments.service.reverse_provider_payment` — on `/reverse` of a confirmed tx.
- `payments.service.cancel_pending_provider_payment` — on `/reverse` of a
  created-but-unconfirmed tx (no ledger, no refund).

`UzumGateway` (in `payments/gateways/uzum.py`, registered in the gateway
`REGISTRY` under `"uzum"`) implements the `create_intent` half — it builds the
Uzum deep-link/checkout URL. `verify_webhook` raises `PaymentNotIntegratedError`
(Uzum uses the dedicated `/payments/uzum/*` routes, not the generic webhook).
`refund` raises (reversal is reconciled through `/reverse`, initiated by Uzum).

---

## 5. Data model

`UzumTransaction` (Alembic migration `0028`), mirroring `PaymeTransaction`:

| Column                    | Type                       | Notes                                                           |
| ------------------------- | -------------------------- | --------------------------------------------------------------- |
| `id`                      | str PK                     | our id (`new_id()`)                                             |
| `trans_id`                | str UNIQUE                 | Uzum's `transId` (UUID string) — the idempotency key            |
| `order_id`                | str FK→orders              | from `params.order_id`                                          |
| `payment_id`              | str FK→payments (SET NULL) | the backing `payments` row                                      |
| `amount_tiyin`            | bigint                     | `amount` from `/create`                                         |
| `status`                  | str CHECK                  | `CREATED` / `CONFIRMED` / `REVERSED` / `FAILED`                 |
| `service_id`              | bigint                     | echoed `serviceId` (audit)                                      |
| `create_time`             | bigint                     | our `transTime` (epoch ms)                                      |
| `confirm_time`            | bigint null                | set on `/confirm`                                               |
| `reverse_time`            | bigint null                | set on `/reverse`                                               |
| `payment_source`          | jsonb                      | `paymentSource` + `tariff`/`phone`/`cardType`/… from `/confirm` |
| `created_at`/`updated_at` | timestamptz                | standard                                                        |

Status is our own machine (Uzum's wire statuses `OK`/`CREATED`/`CONFIRMED`/
`REVERSED`/`FAILED` map onto it). Indexed on `trans_id` (unique) and `order_id`.

---

## 6. Transport + auth

- **Transport:** HTTPS `POST`, `Content-Type: application/json`; responses also
  `application/json`. Any non-`POST` → error `10003`.
- **Auth:** `Authorization: Basic base64(login:password)`. We verify against the
  configured `uzum_login` / `uzum_password` (accepting prod OR test creds, same
  pattern as Payme's two-key acceptance). Missing/invalid → error `10001`.
- **serviceId:** every request carries `serviceId` (int64). We verify it matches
  the configured `uzum_service_id`; unknown → error `10006`.
- **Raw-body middleware** is not needed (Uzum uses no body-signature; auth is the
  Basic header). Requests are parsed as JSON; malformed JSON → error `10002`.
- **HTTP status:** we always return **HTTP 200** with a JSON body (mirrors the
  Payme "always answer on the wire" rule) — success statuses carry the result,
  failures carry `status: FAILED` + `errorCode`. (Confirm with Uzum whether they
  prefer a non-2xx for `10001`; see §16.)

---

## 7. The five webhooks (exact contract)

All requests carry `serviceId` (int64) and `timestamp` (epoch ms). All success
responses echo `serviceId`. `data` is an optional object we may populate with
display info (customer/order label); we return `{}` unless a field is useful.

### `POST /check` — verify payment possibility

**Request:** `{ "serviceId": 101202, "timestamp": 1698361456728, "params": { "order_id": "<uuid>" } }`

**Success (`200`):** `{ "serviceId": 101202, "timestamp": <ms>, "status": "OK", "data": {} }`

**Logic:** resolve the order by `params.order_id`. Order missing → `10007`
(additional payment attribute not found). Order already paid → `10008` (payment
already made). Order cancelled/expired → `10009` (payment cancelled). Otherwise
`status: OK`. (Amount is not sent on `/check`, so no amount check here.)

### `POST /create` — create the transaction

**Request:** `{ "serviceId": 101202, "timestamp": <ms>, "transId": "5c398d7e-…", "params": { "order_id": "<uuid>" }, "amount": 2500000 }`

**Success (`200`):** `{ "serviceId": 101202, "transId": "5c398d7e-…", "status": "CREATED", "transTime": <ms>, "data": {}, "amount": 2500000 }`

**Logic:**

1. If a `UzumTransaction` with this `transId` already exists → `10010`
   (transaction already created). _(This is Uzum's replay signal — not an echo.)_
2. Resolve order by `params.order_id`; missing → `10007`; already paid → `10008`;
   cancelled/expired → `10009`.
3. `amount != int(order.total_charged * 100)` → `10011` (invalid amount).
   (`10012`/`10013` min/max are service-level bounds Uzum enforces; we may also
   assert configured per-order bounds — see §16.)
4. Ensure/attach a pending `payments` row (provider `"uzum"`), insert the
   `UzumTransaction` (status `CREATED`, `create_time = transTime`), return
   `CREATED`.

### `POST /confirm` — deliver the goods

**Request:** `{ "serviceId": 101202, "timestamp": <ms>, "transId": "5c398d7e-…", "paymentSource": "INSTALLMENT", "tariff": "003", "processingReferenceNumber": "000", "phone": "998901234567", "cardType": 2 }`

**Success (`200`):** `{ "serviceId": 101202, "transId": "5c398d7e-…", "status": "CONFIRMED", "confirmTime": <ms>, "data": {}, "amount": 2500000 }`

**Logic:** load tx by `transId`; missing → `10014`. If already `CONFIRMED` →
`10016`. If `REVERSED`/`FAILED` → `10015` (cancelled, cannot confirm). Otherwise:
store the `paymentSource` block, settle the backing payment through
`settle_provider_payment` (payment → succeeded, order → paid, fulfilment
started), set status `CONFIRMED` + `confirm_time`, return `CONFIRMED`.

### `POST /reverse` — cancel / refund

**Request:** `{ "serviceId": 101202, "timestamp": <ms>, "transId": "5c398d7e-…" }`

**Success (`200`):** `{ "serviceId": 101202, "transId": "5c398d7e-…", "status": "REVERSED", "reverseTime": <ms>, "data": {}, "amount": 2500000 }`

**Logic:** load tx by `transId`; missing → `10014`. If already `REVERSED` →
`10018`. Route by current status:

- `CREATED` (not yet confirmed) → `cancel_pending_provider_payment` (no ledger),
  status `REVERSED`.
- `CONFIRMED` → **refund guard:** if any goods delivered (`order.status` in
  `{fulfilled, delivered}` **or** any `FulfillmentTask.status == "succeeded"`),
  refuse with **`10017`** (cannot be cancelled in current state). Otherwise
  `reverse_provider_payment` (ledger reversal), status `REVERSED`.

### `POST /status` — report state

**Request:** `{ "serviceId": 101202, "timestamp": <ms>, "transId": "5c398d7e-…" }`

**Success (`200`):** `{ "serviceId": 101202, "transId": "5c398d7e-…", "status": "CONFIRMED", "transTime": <ms>, "confirmTime": <ms>, "reverseTime": null, "data": {}, "amount": 2500000 }`

**Logic:** load tx by `transId`; missing → `10014`. Return its stored status and
the three timestamps (`transTime` = `create_time`; `confirmTime`/`reverseTime`
`null` when unset). This is Uzum's reconciliation path after a failed `/confirm`.

---

## 8. Error catalogue (`errors.py`)

`UzumError(code: int, message: str)` with `.to_response(**echo)` rendering
`{ "status": "FAILED", "errorCode": <code>, ...echo }` (echoing `serviceId`/
`transId`/`timestamp` as appropriate). Factory functions, one per code:

| Code    | Meaning                                             | Endpoints                |
| ------- | --------------------------------------------------- | ------------------------ |
| `10001` | Access denied (bad/missing Basic auth)              | all                      |
| `10002` | JSON parsing error                                  | all                      |
| `10003` | Invalid operation (non-`POST`)                      | all                      |
| `10005` | Missing required parameters                         | all                      |
| `10006` | Invalid `serviceId`                                 | check, create            |
| `10007` | Additional payment attribute not found (`order_id`) | check, create            |
| `10008` | Payment already made                                | check, create            |
| `10009` | Payment cancelled                                   | check, create            |
| `10010` | Transaction with this `transId` already created     | create                   |
| `10011` | Invalid amount                                      | create                   |
| `10012` | Amount below minimum                                | create                   |
| `10013` | Amount exceeds maximum                              | create                   |
| `10014` | Transaction `transId` does not exist                | confirm, reverse, status |
| `10015` | Transaction cancelled (cannot confirm)              | confirm                  |
| `10016` | Transaction already confirmed                       | confirm                  |
| `10017` | Transaction cannot be cancelled in current state    | reverse                  |
| `10018` | Transaction already cancelled                       | reverse                  |
| `99999` | Internal server error                               | all                      |

---

## 9. Payment initiation (the `create_intent` half)

`UzumGateway.create_intent(order, return_url)`:

- Guard `order.currency == "UZS"` (Uzum is UZS-only), `total_charged > 0`,
  `amount = int(total_charged * 100)` exact-tiyin.
- Build the Uzum deep-link/checkout URL that launches the Uzum app / hosted page:
  `https://www.uzumbank.uz/open-service?serviceId=<id>&order_id=<order.id>&amount=<tiyin>&redirectUrl=<return_url>`
  (exact host/params confirmed with Uzum — see §16). On mobile this deep-links
  into the Uzum app; the miniapp now opens it via `openLink` (external browser /
  app), so app-switch works.
- Return `PaymentIntent(external_id="uzum:<order.id>", intent_url=<url>,
status="pending", extra_metadata={"amount_tiyin": amount})`.

No prepare-payment call at intent time — money moves later via the webhooks.

---

## 10. State machine + timeouts

```
/create  → CREATED
/confirm → CONFIRMED   (settle: order paid, fulfilment started)
/reverse → REVERSED    (from CREATED: cancel pending; from CONFIRMED: ledger reversal)
30-min no-confirm → FAILED
```

- **30-minute rule:** if a `CREATED` transaction receives no `/confirm` within
  30 minutes, Uzum treats it as unsuccessful and we set it `FAILED`. A scheduler
  job (`apps/scheduler/.../jobs/uzum_timeout.py`, mirroring `payme_timeout.py`)
  sweeps `CREATED` transactions older than `1_800_000` ms → `FAILED` +
  `cancel_pending_provider_payment` on the backing payment.
- **`/status` reconciliation:** after a failed/timed-out `/confirm`, Uzum retries
  `/status` up to 10× until we return `CONFIRMED` (or a terminal state). Because
  `/confirm` settles inside one DB transaction, a `CONFIRMED` row is durable
  before we answer, so `/status` reports it correctly on the retry.

---

## 11. Config (`core/config.py`)

```
uzum_service_id: int | None      # our serviceId (placeholder in sandbox; Uzum-issued in prod)
uzum_login: str                  # Basic auth username (we set)
uzum_password: str               # Basic auth password (we set)
uzum_test_login / uzum_test_password  # optional sandbox creds, accepted alongside prod
uzum_open_service_url: str = "https://www.uzumbank.uz/open-service"
```

`UzumGateway.available` is `bool(uzum_service_id and uzum_login and
uzum_password)`. Secrets added to `core/logging.py` `REDACTED_KEYS`
(`uzum_password`, `uzum_test_password`) and to `infra/secrets-example/api.env`
with a filled-out comment block (like the Payme block).

---

## 12. Error handling / edge cases

- **Idempotency is code-signalled, not echoed.** Unlike Payme (which re-returned
  the stored result on replay), Uzum wants the dedicated "already-X" codes:
  repeat `/create` → `10010`, repeat `/confirm` (confirmed) → `10016`, repeat
  `/reverse` (reversed) → `10018`. We look up by `trans_id` and branch on stored
  status.
- **Row-lock on create/confirm/reverse** (`SELECT … FOR UPDATE` on the tx, and on
  the order for `/create`) so concurrent webhooks serialise — same pattern as
  Payme. A concurrent duplicate `/create` that races the INSERT surfaces as an
  `IntegrityError` on `trans_id`; catch it and re-read → `10010`.
- **Commit inside the try/except**, rendering `99999` (internal error) at HTTP 200
  if the commit itself fails (mirrors Payme's `-32400` fix).
- **Partial delivery money-safety:** the `/reverse` guard checks
  `_any_goods_delivered`, not just `order.status`, so a multi-item order resting
  at `fulfilling` with one code already shipped is refused (`10017`), never
  auto-refunded.
- **`data`/`params` envelopes:** `params` carries only `order_id` for us (other
  account attributes are service-config); `data` we return as `{}` unless a
  display label is worth sending.

---

## 13. Testing

Coverage gate for `payments`-adjacent code is **≥ 95 %**. Integration tests
(testcontainers Postgres), mirroring `test_payme_service.py` /
`test_payme_merchant.py`:

- Each webhook: success + every error code it can emit.
- `/check`: OK / `10007` / `10008` / `10009`.
- `/create`: CREATED / `10010` replay / `10011` wrong amount / `10007` unknown
  order / reuse of the pending payment row / concurrent-create IntegrityError →
  `10010`.
- `/confirm`: CONFIRMED + settle (order paid) / `10014` / `10015` / `10016`
  replay / partial-delivery still confirms.
- `/reverse`: from CREATED → REVERSED (cancel pending) / from CONFIRMED →
  REVERSED (ledger reversal) / `10017` when delivered / `10018` replay / `10014`.
- `/status`: the full field shape for CREATED / CONFIRMED / REVERSED.
- Auth: `10001` no/blocked auth, `10006` bad serviceId, `10003` non-POST,
  `10002` bad JSON.
- Gateway unit tests: `available` gating, `create_intent` builds the exact
  open-service URL, tiyin exactness.
- Scheduler: 30-min timeout sweep `CREATED` → `FAILED`.

Assert `refund_admin` and the shared payments hooks are byte-for-byte unchanged
(the Payme work already extracted `_apply_refund_reversal`).

---

## 14. Docs

- ADR `docs/decisions/0035-uzum-merchant-api.md` (MADR): why webhook model,
  refund-via-reverse, idempotency-by-code, credential source.
- Runbook `docs/runbooks/uzum-troubleshooting.md`: error-code operator table,
  the `/status` reconciliation loop, the 30-min timeout.
- Sequence diagram `docs/architecture/sequence-diagrams/uzum-payment.mmd`.
- `docs/architecture/module-map.md` + module `README.md`.
- Regenerate `docs/api/openapi.json` via `make gen-api`; TS client regenerated.
- **Postman collection** `docs/api/uzum.postman_collection.json` — the artifact
  we hand Uzum's tester (all 5 endpoints, Basic auth, example bodies).

---

## 15. Out of scope (v1)

- Uzum's newer "intents" checkout API (`/processing/api/v1/intents`) — a separate
  flow; not needed for the webhook merchant integration.
- Nasiya/installment-specific logic beyond storing `paymentSource` (we accept and
  store the installment metadata; we do not branch pricing on it).
- Partner-initiated refunds (Uzum reconciles reversal through `/reverse`).
- Fiscalisation (if Uzum requires a fiscal receipt callback, add later like
  Payme's `SetFiscalData` — none seen in the merchant webhook set).

---

## 16. Documentation gaps flagged (not silently assumed)

1. **Credential source in prod:** docs say Uzum issues `login`/`password`; the
   engineer says we set them for testing. We make them env-configurable and
   confirm the prod source with Uzum before go-live.
2. **Exact `open-service` URL + params:** taken from a third-party library; the
   canonical host/param names (`serviceId`/`order_id`/`amount`/`redirectUrl`) must
   be confirmed with Uzum.
3. **HTTP status for `10001`:** whether Uzum expects HTTP 401 or a 200 body with
   `errorCode: 10001` for auth failures — confirm; default is 200-body.
4. **`params` account envelope:** we assume `params.order_id`; confirm the exact
   account-attribute key(s) Uzum will send for our service.
5. **Min/max amount (`10012`/`10013`):** whether Uzum enforces service bounds or
   expects us to; we can assert per-order bounds if required.
6. **Source IPs:** Uzum's webhook source IPs for a Caddy allowlist (added later,
   like Payme; app-layer `10001` auth is the real gate meanwhile).

---

## 17. Build order (feeds the plan)

1. Migration `0028_uzum_transactions` + `UzumTransaction` model.
2. `errors.py` (18 factories + `to_response`).
3. `service.py` — 5 handlers + `build_checkout_url` (reuse payments hooks).
4. `routes.py` — Basic auth + serviceId + JSON parse guards, always-200.
5. `UzumGateway` + registry wiring + `core/config.py` + `core/logging.py`.
6. Scheduler `uzum_timeout.py` (30-min sweep).
7. Tests (≥95%).
8. Docs (ADR, runbook, sequence diagram, module map, README) + Postman
   collection artifact.
9. Mount router; `make gen-api`.

---

## 18. Artifacts to hand Uzum (after sandbox deploy)

Once the module is built + deployed, send Uzum's tester:

1. **Callback base URL:** `https://api.yupay.uz/api/v1/payments/uzum` (endpoints
   `/check` `/create` `/confirm` `/reverse` `/status`).
2. **Basic auth** `login` / `password` (we generate; stored in prod env).
3. **`serviceId`** (our placeholder; Uzum replaces with the real one after test).
4. **Postman collection** (`docs/api/uzum.postman_collection.json`).
