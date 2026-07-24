# Uzum Bank Merchant API Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Post-implementation correction (2026-07-24):** this plan was written assuming
> Uzum's `amount` is in **tiyin**, but Uzum actually charges in **sums** (major
> UZS units). The shipped code uses sums: `amount = int(order.total_charged)`,
> the column is `amount_sum` (migration `0030`), `build_checkout_url`'s param is
> `amount_sum`, and the gateway metadata key is `amount_sum`. Read every "tiyin"
> / `amount_tiyin` / `total_charged * 100` mention below as its sum equivalent.

**Goal:** Accept UZS payments via the Uzum Bank Merchant API — expose five HTTPS webhook endpoints (`/check /create /confirm /reverse /status`) Uzum drives through the transaction lifecycle, build the Uzum deep-link checkout, reconcile confirm/reverse through the shared payments hooks, and be sandbox-ready for Uzum's manual test.

**Architecture:** Uzum is the inverted-webhook twin of the already-shipped Payme module. Build `modules/uzum/` mirroring `modules/payme/`, reuse the existing `payments` provider-lifecycle hooks (`settle_provider_payment` / `reverse_provider_payment` / `cancel_pending_provider_payment`) and the refund-guard money-safety rule. **Do not rebuild the payments hooks — they already exist and are proven.**

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, APScheduler; miniapp Vite/React + next-intl-style i18n JSON.

**Reference spec:** `docs/superpowers/specs/2026-07-22-uzum-merchant-api-design.md` (read it — it holds the exact request/response schemas and the full error catalogue).

**Reference twin (the template to mirror):** `apps/api/src/yupay/modules/payme/` and its tests `apps/api/tests/{unit,integration}/test_payme_*.py`. Every Uzum file has a Payme sibling; the plan gives the exact Uzum deltas.

## Global Constraints

- **Endpoints (REST, not JSON-RPC):** `POST /api/v1/payments/uzum/{check,create,confirm,reverse,status}`. Body `application/json`. Always respond **HTTP 200** with a JSON body (success status or `{status:"FAILED", errorCode:<int>}`). Non-`POST` reaching a handler → `10003`.
- **Auth:** `Authorization: Basic base64(login:password)` verified against `uzum_login`/`uzum_password` **and** the test pair `uzum_test_login`/`uzum_test_password` (accept either). Missing/invalid → `10001`. `serviceId` in body must equal `uzum_service_id` → else `10006`.
- **Amount:** `int64` tiyin. Expected = `int(order.total_charged * Decimal(100))`, asserted integral; mismatch/non-integral → `10011`.
- **Account field:** `params.order_id` (a string) → our `orders.id`.
- **Status strings (wire):** `OK` (check only), `CREATED`, `CONFIRMED`, `REVERSED`, `FAILED`. Our stored `UzumTransaction.status` ∈ `{CREATED, CONFIRMED, REVERSED, FAILED}`.
- **transId:** Uzum's UUID string, our unique idempotency key (column `trans_id`).
- **Idempotency by dedicated code (NOT echo):** repeat `/create` (same `transId`) → `10010`; `/confirm` on a CONFIRMED tx → `10016`; `/reverse` on a REVERSED tx → `10018`.
- **Refund guard (money-safety):** `/reverse` of a CONFIRMED tx whose goods are delivered (`order.status in {fulfilled, delivered}` OR any `FulfillmentTask.status == "succeeded"`) → `10017`.
- **Error codes (exact):** `10001` access denied · `10002` JSON parse · `10003` invalid operation (non-POST) · `10005` missing params · `10006` invalid serviceId · `10007` order not found · `10008` already paid · `10009` payment cancelled · `10010` transId already created · `10011` invalid amount · `10012` below min · `10013` above max · `10014` transId not found · `10015` cancelled, can't confirm · `10016` already confirmed · `10017` cannot cancel in current state · `10018` already cancelled · `99999` internal error.
- Money as `Decimal`/tiyin `int`, never float. mypy --strict, ruff (line 100). Docstrings Google-style. Run `prettier --write` on every touched markdown/JSON file (CI's TS-lint job runs `prettier --check .` over the whole repo).
- All three locales (`ru`/`en`/`uz`) updated for any new user-facing string, same PR.
- Coverage ≥ 95% for this payments-adjacent code.

## File Structure

- Create `apps/api/src/yupay/modules/uzum/__init__.py`, `api.py`, `models.py`, `errors.py`, `service.py`, `routes.py`, `README.md`
- Create `apps/api/migrations/versions/0028_uzum_transactions.py`
- Create `apps/api/src/yupay/modules/payments/gateways/uzum.py`
- Create `apps/scheduler/src/yupay_scheduler/jobs/uzum_timeout.py`
- Create `docs/api/uzum.postman_collection.json`
- Create `docs/decisions/0035-uzum-merchant-api.md`, `docs/runbooks/uzum-troubleshooting.md`, `docs/architecture/sequence-diagrams/uzum-payment.mmd`
- Create tests: `apps/api/tests/unit/test_uzum_errors.py`, `test_uzum_gateway.py`, `test_uzum_config.py`; `apps/api/tests/integration/test_uzum_service.py`, `test_uzum_webhook.py`
- Modify `apps/api/src/yupay/api/v1/__init__.py` (mount router), `apps/api/src/yupay/modules/payments/gateways/__init__.py` (REGISTRY), `apps/api/src/yupay/core/config.py`, `apps/api/src/yupay/core/logging.py`, `infra/secrets-example/api.env`, `infra/caddy/Caddyfile.prod`, `docs/architecture/module-map.md`
- Miniapp: `apps/miniapp/src/lib/payment-methods.ts` (+ `TopUp.tsx` provider map if needed), `packages/i18n/locales/{ru,en,uz}/*.json`

---

## Task 1: Migration + `UzumTransaction` model

**Files:**

- Create: `apps/api/src/yupay/modules/uzum/models.py`, `apps/api/src/yupay/modules/uzum/__init__.py`
- Create: `apps/api/migrations/versions/0028_uzum_transactions.py`
- Test: `apps/api/tests/integration/test_uzum_service.py` (model round-trip smoke test to start)

**Interfaces:**

- Produces: `UzumTransaction` ORM model with columns from spec §5: `id` (PK str), `trans_id` (str, UNIQUE), `order_id` (FK orders.id), `payment_id` (FK payments.id, ON DELETE SET NULL, nullable), `amount_tiyin` (BigInteger), `status` (str, CHECK in `('CREATED','CONFIRMED','REVERSED','FAILED')`), `service_id` (BigInteger, nullable), `create_time` (BigInteger), `confirm_time`/`reverse_time` (BigInteger, nullable), `payment_source` (JSONB, default `{}` — server_default `'{}'`), `created_at`/`updated_at` (timestamptz, server_default now()).

**Steps:**

- [ ] **Step 1:** Mirror `apps/api/src/yupay/modules/payme/models.py` exactly, renaming `PaymeTransaction`→`UzumTransaction`, table `payme_transactions`→`uzum_transactions`, `payme_id`→`trans_id`, the state `Integer` column → `status` `String` with CHECK `('CREATED','CONFIRMED','REVERSED','FAILED')`, `reason`→(drop), add `service_id` BigInteger nullable, `perform_time`→`confirm_time`, `cancel_time`→`reverse_time`, `fiscal_data`→`payment_source`. Keep `Mapped[...]` typing and `__table_args__` indexes (`trans_id` unique, `order_id`). Google docstring.
- [ ] **Step 2:** Write migration `0028_uzum_transactions.py` with `down_revision = "0027_payme_transactions"`, mirroring the Payme migration's `op.create_table` — same column types, the CHECK constraint on `status`, the unique index on `trans_id`, the index on `order_id`, FK to `orders.id` and `payments.id` (SET NULL). `downgrade` drops the table.
- [ ] **Step 3:** Import `UzumTransaction` where models are registered (mirror how `PaymeTransaction` is imported to prime the mapper — check `payme/models.py`'s import site).
- [ ] **Step 4:** Write a smoke test in `test_uzum_service.py`: insert an `UzumTransaction` for a seeded order, read it back, assert columns. Run: `uv run pytest apps/api/tests/integration/test_uzum_service.py -q`. Expected: PASS (migrations apply to `0028`).
- [ ] **Step 5:** Commit `feat(api/uzum): uzum_transactions model + migration 0028`.

---

## Task 2: Uzum error catalogue (`errors.py`)

**Files:**

- Create: `apps/api/src/yupay/modules/uzum/errors.py`
- Test: `apps/api/tests/unit/test_uzum_errors.py`

**Interfaces:**

- Produces: `class UzumError(Exception)` with `__init__(self, code: int, message: str)`, attributes `code`, `message`, and `to_response(self, **echo: Any) -> dict[str, Any]` returning `{"status": "FAILED", "errorCode": self.code, **echo}`. Plus one factory per error code (names below), each returning `UzumError`.

**Steps:**

- [ ] **Step 1: Write the failing test** in `test_uzum_errors.py`: assert each factory returns the exact code and that `to_response(serviceId=1)` yields `{"status":"FAILED","errorCode":<code>,"serviceId":1}`. Cover every factory. Example:

```python
from yupay.modules.uzum.errors import UzumError, order_not_found, invalid_amount

def test_order_not_found_code() -> None:
    assert order_not_found().code == 10007

def test_to_response_shape() -> None:
    r = invalid_amount().to_response(serviceId=101202, transId="t")
    assert r == {"status": "FAILED", "errorCode": 10011, "serviceId": 101202, "transId": "t"}
```

- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/unit/test_uzum_errors.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `errors.py`.** `UzumError` as above. Factories (name → code, message text is the operator-facing English from spec §8):
  - `access_denied` → 10001, `bad_json` → 10002, `invalid_operation` → 10003, `missing_params` → 10005, `invalid_service_id` → 10006, `order_not_found` → 10007, `payment_already_made` → 10008, `payment_cancelled` → 10009, `transaction_already_created` → 10010, `invalid_amount` → 10011, `amount_below_minimum` → 10012, `amount_above_maximum` → 10013, `transaction_not_found` → 10014, `transaction_cancelled` → 10015, `transaction_already_confirmed` → 10016, `transaction_cannot_be_cancelled` → 10017, `transaction_already_cancelled` → 10018, `internal_error` → 99999.
  - Populate `__all__`.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5:** Commit `feat(api/uzum): error catalogue`.

---

## Task 3: Config + log redactor + infra env

**Files:**

- Modify: `apps/api/src/yupay/core/config.py`, `apps/api/src/yupay/core/logging.py`, `infra/secrets-example/api.env`
- Test: `apps/api/tests/unit/test_uzum_config.py`

**Interfaces:**

- Produces on `Settings`: `uzum_service_id: int | None = None`, `uzum_login: str = ""`, `uzum_password: str = ""`, `uzum_test_login: str = ""`, `uzum_test_password: str = ""`, `uzum_open_service_url: str = "https://www.uzumbank.uz/open-service"`.

**Steps:**

- [ ] **Step 1: Write the failing test** (mirror `test_payme_config.py`): `uzum_open_service_url` defaults to `https://www.uzumbank.uz/open-service`; `uzum_password`/`uzum_test_password` are read from env (monkeypatch `setenv`); `uzum_service_id` parses from env as int.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Add the fields to `Settings` (mirror the Payme block). Add `"uzum_password"`, `"uzum_test_password"` to `REDACTED_KEYS` in `core/logging.py`. Add a `# ----- Acquirer: Uzum (Merchant API) -----` block to `infra/secrets-example/api.env` mirroring the Payme block (document sandbox vs go-live: fill `UZUM_SERVICE_ID`+`UZUM_TEST_LOGIN`+`UZUM_TEST_PASSWORD` for the manual test; add `UZUM_LOGIN`/`UZUM_PASSWORD` for prod).
- [ ] **Step 4:** Run the test + `uv run prettier`? (env is not prettier'd; skip). Expected: PASS.
- [ ] **Step 5:** Commit `feat(api/uzum): config + log redaction + infra env`.

---

## Task 4: Uzum service — the five handlers + checkout URL

**Files:**

- Create: `apps/api/src/yupay/modules/uzum/service.py`
- Test: `apps/api/tests/integration/test_uzum_service.py` (extend)

**Interfaces:**

- Consumes: `payments.service.settle_provider_payment(db, payment, external_event_id)`, `reverse_provider_payment(db, payment, external_event_id, actor)`, `cancel_pending_provider_payment(db, payment, actor)` (already exist — do not modify). `FulfillmentTask` (for the delivery guard). `Order`, `Payment`.
- Produces (all `async`, all take `db: AsyncSession`, all raise `UzumError` on failure, all `flush` not `commit`):
  - `now_ms() -> int`
  - `check(db, *, service_id: int, params: dict[str, Any]) -> dict[str, Any]` → `{"status":"OK","data":{}}` (route wraps serviceId/timestamp).
  - `create(db, *, service_id: int, trans_id: str, params: dict, amount: int) -> dict` → `{"transId":trans_id,"status":"CREATED","transTime":<ms>,"data":{},"amount":amount}`.
  - `confirm(db, *, trans_id: str, payment_source: dict) -> dict` → `{"transId":trans_id,"status":"CONFIRMED","confirmTime":<ms>,"data":{},"amount":<tiyin>}`.
  - `reverse(db, *, trans_id: str) -> dict` → `{"transId":trans_id,"status":"REVERSED","reverseTime":<ms>,"data":{},"amount":<tiyin>}`.
  - `status(db, *, trans_id: str) -> dict` → `{"transId":trans_id,"status":<stored>,"transTime":<ms>,"confirmTime":<ms|null>,"reverseTime":<ms|null>,"data":{},"amount":<tiyin>}`.
  - `build_checkout_url(*, order_id: str, amount_tiyin: int, return_url: str | None) -> str`.

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_uzum_service.py` (mirror `test_payme_service.py`), one per behaviour below, using a seeded `pending_payment` order with `total_charged` s.t. `EXPECTED_TIYIN = int(total_charged*100)`:
  - `check` OK; `check` unknown order → `10007`; `check` on a paid order → `10008`; on a cancelled/expired order → `10009`.
  - `create` → CREATED (row inserted, status CREATED, `create_time` set, pending payment reused/created); `create` replay same `trans_id` → `10010`; `create` wrong amount → `10011`; `create` unknown order → `10007`.
  - `confirm` → CONFIRMED, settles payment (order `paid`), stores `payment_source`; `confirm` unknown `trans_id` → `10014`; `confirm` already-confirmed → `10016`; `confirm` on a reversed tx → `10015`.
  - `reverse` from CREATED → REVERSED (cancel pending, no ledger); `reverse` from CONFIRMED (not delivered) → REVERSED (ledger reversal); `reverse` when delivered → `10017`; `reverse` replay → `10018`; `reverse` unknown → `10014`.
  - `status` returns the six-field shape for CREATED / CONFIRMED / REVERSED.
  - `build_checkout_url` yields `https://www.uzumbank.uz/open-service?serviceId=<id>&order_id=<oid>&amount=<tiyin>&redirectUrl=<ret>`.
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/integration/test_uzum_service.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `service.py`** by adapting `payme/service.py`:
  - Helpers `_expected_tiyin(order)` (identical to Payme), `_resolve_order(db, order_id, for_update)` (raise `order_not_found()`=10007 when missing — Uzum uses 10007, not 10050), `_load_tx(db, trans_id, for_update)`, `_load_payment`, `_ensure_payment` (provider `"uzum"`, `external_id=f"uzum:{order.id}"`), `_any_goods_delivered(db, order_id)` (identical to Payme).
  - `check`: resolve order; if `order.status == "paid"` → `payment_already_made()` (10008); if `order.status in {"cancelled","expired","refunded"}` → `payment_cancelled()` (10009); if not `pending_payment` and not paid → treat as not payable via `payment_cancelled()`; else `{"status":"OK","data":{}}`. (No amount on `/check`.)
  - `create`: `_load_tx(for_update)`; if exists → `transaction_already_created()` (10010). Resolve order `for_update`; status checks as in `check`; `amount != _expected_tiyin(order)` → `invalid_amount()` (10011). `_ensure_payment`; insert `UzumTransaction(status="CREATED", create_time=now_ms(), service_id=service_id, amount_tiyin=amount)`; flush; return CREATED dict.
  - `confirm`: `_load_tx(for_update)`; None → `transaction_not_found()` (10014). If `status=="CONFIRMED"` → `transaction_already_confirmed()` (10016). If `status in {"REVERSED","FAILED"}` → `transaction_cancelled()` (10015). Else: set `payment_source=payment_source`, `status="CONFIRMED"`, `confirm_time=now_ms()`; `settle_provider_payment(db, payment, external_event_id=trans_id)`; flush; return CONFIRMED dict.
  - `reverse`: `_load_tx(for_update)`; None → 10014. If `status=="REVERSED"` → `transaction_already_cancelled()` (10018). If `status=="CREATED"`: `cancel_pending_provider_payment`, set REVERSED. If `status=="CONFIRMED"`: delivery guard → `transaction_cannot_be_cancelled()` (10017) if delivered, else `reverse_provider_payment(...)`, set REVERSED. Set `reverse_time`, flush, return REVERSED dict.
  - `status`: `_load_tx`; None → 10014; return the six-field dict.
  - `build_checkout_url`: read `get_settings()`, urlencode params.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(api/uzum): five webhook handlers + checkout url`.

---

## Task 5: Webhook endpoints + auth + mount + OpenAPI

**Files:**

- Create: `apps/api/src/yupay/modules/uzum/routes.py`, `apps/api/src/yupay/modules/uzum/api.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py`
- Test: `apps/api/tests/integration/test_uzum_webhook.py`

**Interfaces:**

- Consumes: `service.check/create/confirm/reverse/status`, `UzumError`, config creds.
- Produces: `router` with `POST /check /create /confirm /reverse /status` under prefix `/payments/uzum`. A `_authenticate(request)` helper (Basic auth accepting prod or test creds → else raise `access_denied()`=10001) and a `_service_guard(body)` (serviceId match → else `invalid_service_id()`=10006). Each route: read raw body, parse JSON (fail → `bad_json()`=10002), authenticate, validate required params (missing → `missing_params()`=10005), dispatch to the service, **commit inside try/except** (commit failure → `internal_error()`=99999), always return HTTP 200 JSON. On `UzumError`, return `err.to_response(serviceId=<body serviceId>, ...)` echoing `serviceId` and (where relevant) `transId`/`timestamp`. On success, wrap the service dict with `serviceId` + `timestamp`.

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_uzum_webhook.py` (mirror `test_payme_merchant.py`), hitting the real ASGI app:
  - No/invalid `Authorization` → HTTP 200 body `{status:FAILED, errorCode:10001}`.
  - Valid test creds + unknown order on `/check` → `10007`.
  - Wrong `serviceId` → `10006`.
  - Malformed JSON body → `10002`.
  - Missing required field (e.g. `/create` without `amount`) → `10005`.
  - Full happy path across endpoints against a seeded order: `/check`→OK, `/create`→CREATED, `/confirm`→CONFIRMED (order becomes `paid`), `/status`→CONFIRMED, `/reverse` (fresh non-delivered order) → REVERSED.
  - Every response is HTTP 200.
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/integration/test_uzum_webhook.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `routes.py`** mirroring `payme/routes.py`'s structure (raw-body read, Basic auth parse, always-200, commit-inside-guard), adapted to five REST routes and the Uzum response envelope. `valid_login_pairs = {(l,p) for l,p in ((uzum_login,uzum_password),(uzum_test_login,uzum_test_password)) if l and p}`. Implement `api.py` re-exporting the router + service. Mount the router in `api/v1/__init__.py` (mirror how `payme` router is mounted). **Prime the model graph** with `import yupay.api.v1` where needed (the Payme cross-module cycle applies here too).
- [ ] **Step 4:** Run the tests. Expected: PASS. Then `make gen-api` to regenerate `docs/api/openapi.json` + TS client; commit the regenerated files.
- [ ] **Step 5:** Commit `feat(api/uzum): webhook endpoints + basic auth + mount + openapi`.

---

## Task 6: `UzumGateway` adapter + REGISTRY

**Files:**

- Create: `apps/api/src/yupay/modules/payments/gateways/uzum.py`
- Modify: `apps/api/src/yupay/modules/payments/gateways/__init__.py`
- Test: `apps/api/tests/unit/test_uzum_gateway.py`

**Interfaces:**

- Consumes: `uzum.service.build_checkout_url`, config.
- Produces: `class UzumGateway(PaymentGateway)` with `provider = "uzum"`, `available` = `bool(uzum_service_id and uzum_login and uzum_password)` (or test creds — mirror Payme's `available`), `create_intent` (UZS guard, tiyin exactness, builds open-service URL, returns `PaymentIntent(external_id=f"uzum:{order.id}", intent_url=..., status="pending", extra_metadata={"amount_tiyin": amount})`), `verify_webhook` raises `PaymentNotIntegratedError`, `refund` raises `PaymentGatewayError`. Registered in `REGISTRY` under `"uzum"`.

**Steps:**

- [ ] **Step 1: Write failing tests** (mirror `test_payme_gateway.py`): `available` false when unconfigured / true with service_id+creds; `create_intent` builds the exact open-service URL for a UZS order; non-UZS → `PaymentGatewayError`; fractional tiyin → `PaymentGatewayError`; REGISTRY has `"uzum"`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `gateways/uzum.py` mirroring `gateways/payme.py`; register in `gateways/__init__.py` REGISTRY.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(api/uzum): payment gateway adapter + registry`.

---

## Task 7: Scheduler 30-minute timeout job

**Files:**

- Create: `apps/scheduler/src/yupay_scheduler/jobs/uzum_timeout.py`
- Test: `apps/api/tests/integration/test_uzum_service.py` (add a timeout-sweep test) or a scheduler test mirroring the Payme timeout test.

**Interfaces:**

- Produces: an idempotent async job that finds `UzumTransaction` rows with `status == "CREATED"` and `create_time < now_ms() - 1_800_000` (30 min), sets them `FAILED`, and calls `cancel_pending_provider_payment` on the backing payment. Registered on the scheduler (mirror `payme_timeout.py`'s registration + cadence, e.g. every few minutes).

**Steps:**

- [ ] **Step 1: Write the failing test:** seed a `CREATED` tx with `create_time` 31 min old + a pending payment; run the job; assert tx `FAILED` and payment cancelled. A fresh (<30 min) tx is untouched.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `uzum_timeout.py` mirroring `payme_timeout.py` (including the `import yupay.api.v1` model-graph prime the Payme job needed). Register it in the scheduler.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5:** Commit `feat(scheduler/uzum): 30-minute unconfirmed-transaction sweep`.

---

## Task 8: Mini App Uzum payment method + i18n

**Files:**

- Modify: `apps/miniapp/src/lib/payment-methods.ts` (+ `apps/miniapp/src/pages/TopUp.tsx` provider map if it enumerates providers)
- Modify: `packages/i18n/locales/{ru,en,uz}/*.json`
- Test: existing miniapp payment-method tests if present (mirror the Payme method addition)

**Interfaces:**

- Produces: an `"uzum"` entry in the payment-method list (label, icon, provider id `"uzum"`), UZS-gated exactly like the Payme method. The checkout already opens `intent_url` via `openExternalLink` (shipped), so Uzum's deep-link works with no further miniapp change.

**Steps:**

- [ ] **Step 1:** Add the Uzum method to `payment-methods.ts` mirroring how Payme was added (same shape, `provider: "uzum"`, UZS gating). If `TopUp.tsx` maps method→provider (`PROVIDER_BY_METHOD_FULL`), add `uzum`.
- [ ] **Step 2:** Add the `payment.uzum` label key to `ru.json`, `en.json`, `uz.json` (all three).
- [ ] **Step 3:** Run: `pnpm exec turbo run lint typecheck --filter=@yupay/miniapp` + i18n key-completeness test. Expected: PASS.
- [ ] **Step 4:** Commit `feat(miniapp/uzum): uzum payment method + i18n`.

---

## Task 9: Postman collection artifact

**Files:**

- Create: `docs/api/uzum.postman_collection.json`

**Interfaces:**

- Produces: a Postman v2.1 collection with the 5 requests (`POST {{base}}/check|/create|/confirm|/reverse|/status`), Basic-auth at collection level (vars `{{login}}`/`{{password}}`), a `{{base}}` var (`https://api.yupay.uz/api/v1/payments/uzum`), and example bodies for each (from spec §7, with `{{serviceId}}`/`{{order_id}}`/`{{transId}}`/`{{amount}}` vars).

**Steps:**

- [ ] **Step 1:** Author the collection JSON with the 5 requests + example bodies + collection-level Basic auth + variables.
- [ ] **Step 2:** Validate it is well-formed JSON: `python -c "import json; json.load(open('docs/api/uzum.postman_collection.json'))"`. Run `prettier --write docs/api/uzum.postman_collection.json`.
- [ ] **Step 3:** Commit `docs(uzum): postman collection for the merchant webhooks`.

---

## Task 10: Caddy IP allowlist (deferred activation)

**Files:**

- Modify: `infra/caddy/Caddyfile.prod`

**Steps:**

- [ ] **Step 1:** Add a `@uzumMerchantBlocked` matcher for `path /api/v1/payments/uzum/*` + `not client_ip <UZUM_IPS>` → `respond 403`, mirroring the Payme `@paymeMerchantBlocked` block. Leave the IP list as a placeholder comment referencing spec §16 gap #6 — **do not activate** (do not `caddy reload`) until Uzum confirms their source IPs; the app-layer `10001` auth is the gate meanwhile.
- [ ] **Step 2:** `prettier`? (Caddyfile is not prettier'd). Commit `chore(infra/uzum): caddy allowlist scaffold (inactive until IPs confirmed)`.

---

## Task 11: Documentation

**Files:**

- Create: `apps/api/src/yupay/modules/uzum/README.md`, `docs/decisions/0035-uzum-merchant-api.md`, `docs/runbooks/uzum-troubleshooting.md`, `docs/architecture/sequence-diagrams/uzum-payment.mmd`
- Modify: `docs/architecture/module-map.md`

**Steps:**

- [ ] **Step 1:** Module `README.md` — the 5 endpoints, state machine, error table, checkout, mirroring `payme/README.md`.
- [ ] **Step 2:** ADR `0035` (MADR template) — webhook model, reverse-based refund, idempotency-by-code, credential source, why mirror Payme.
- [ ] **Step 3:** Runbook `uzum-troubleshooting.md` — operator error-code table (all 18 + 99999), the `/status` reconciliation loop, 30-min timeout, auth debugging.
- [ ] **Step 4:** Sequence diagram `uzum-payment.mmd` (Mermaid): customer → open-service → Uzum → check/create/confirm → our fulfilment; reverse path.
- [ ] **Step 5:** Add the `uzum` module row to `module-map.md`.
- [ ] **Step 6:** `prettier --write` all touched markdown. Commit `docs(uzum): module readme, ADR-0035, runbook, sequence diagram, module map`.

---

## Final verification (after all tasks)

- [ ] `make lint typecheck test` green locally (Python + TS).
- [ ] `prettier --check .` clean (CI's TS-lint job).
- [ ] Coverage ≥ 95% on `modules/uzum/*` and `gateways/uzum.py`.
- [ ] OpenAPI + TS client regenerated, no drift.
- [ ] All three locales updated for the new method label.
- [ ] `refund_admin` + payments hooks byte-for-byte unchanged (diff-check).
- [ ] Whole-branch review (opus) — focus: money-safety of `confirm`/`reverse`, the idempotency-by-code branches, auth/serviceId guards, always-200.
- [ ] Deploy sandbox → hand Uzum: callback URL `https://api.yupay.uz/api/v1/payments/uzum`, Basic `login`/`password`, `serviceId`, Postman collection (spec §18).
