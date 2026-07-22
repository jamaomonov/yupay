# Payme Merchant API Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept UZS payments via Payme Business Merchant API — expose a JSON-RPC merchant endpoint Payme drives through the transaction lifecycle, build the checkout redirect, auto-reconcile cancels/refunds, and be sandbox-ready to pass Payme's automated test suite.

**Architecture:** New `payme` module owns a `payme_transactions` state table + the seven JSON-RPC method handlers + a dedicated Basic-auth JSON-RPC endpoint. A thin `PaymeGateway` plugs into the existing `payments.gateways` registry for checkout-URL creation; `PerformTransaction`/`CancelTransaction` reuse the existing single paid/refund chokepoints in `payments.service`. A scheduler job auto-cancels 12h-stale transactions.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / Pydantic v2 / APScheduler / httpx-free (we are the server). React (miniapp — minimal). No new dependency.

**Spec:** `docs/superpowers/specs/2026-07-22-payme-merchant-api-design.md` — read it; it carries the exact Payme contract and the rationale.

## Global Constraints

- **We are a JSON-RPC 2.0 server.** Endpoint `POST /api/v1/payments/payme/merchant`. Envelope in `{method, params, id}`; out `{result, id}` or `{error:{code, message, data}, id}`. **Always HTTP 200** (Payme reads any non-200 as `-32400`).
- **Auth:** HTTP Basic `Authorization: Basic base64("<login>:<key>")`, login default `Paycom` (configurable). The key must equal **either** `payme_key` (prod) **or** `payme_test_key` (test) — both configured, so one endpoint serves sandbox + prod. Mismatch/missing → error **-32504**.
- **Amounts are tiyin** (integer, 1 so'm = 100 tiyin). `order.total_charged` is a `Decimal` in major UZS units. Expected tiyin = `int(total_charged * 100)`, exact — reject any mismatch with **-31001**.
- **`account.order_id`** = our `order.id` (one-time account per order).
- **Transaction states:** `1` created, `2` performed, `-1` cancelled-before-perform, `-2` cancelled-after-perform. **Reasons:** `1,2,3,4,5,10` (4 = timeout, 5 = refund). Transitions: Create→`1`; Perform `1`→`2`; Cancel `1`→`-1` or `2`→`-2`.
- **Error codes (exact):** `-31001` invalid amount, `-31003` tx not found, `-31007` already-delivered can't cancel, `-31008` op not permitted, `-31050` order not found (`data:"order_id"`), `-31051` order not payable/already paid (`data:"order_id"`), `-32504` auth, `-32300` non-POST, `-32700` bad JSON, `-32600` bad RPC fields, `-32601` unknown method, `-32400` internal, `-32001` SetFiscalData receipt not found. `error.message` is a `{ru, uz, en}` object; `error.data` names the offending field where applicable.
- **Idempotency is protocol-mandated:** Create/Perform/Cancel must be safe to replay (Payme retries on lost response). Enforced by `UNIQUE(payme_id)` + state guards + `FOR UPDATE` row claim per method.
- **12h auto-cancel:** a transaction in state `1` older than `43_200_000 ms` → `-1`, reason `4`.
- **Currency:** Payme only for UZS orders. Payme is UZS-only.
- **PII/secrets:** never log the Basic-auth key, card data, or the raw account; log `payme_id` + method + code only. `payme_key`/`payme_test_key` in the log redactor.
- **Coverage:** `payments` + this integration are the **≥ 95%** tier (CLAUDE.md §8). No money as float; money is `Decimal`; tiyin is `int`.
- **The `PaymentGateway` protocol** (`payments/gateways/base.py`): `provider: str`, `available: bool`, `create_intent(*, db, order, return_url) -> PaymentIntent`, `verify_webhook(*, headers, body) -> WebhookEvent`, `refund(*, payment, amount) -> RefundResult`. `PaymentIntent(external_id, intent_url, status, extra_metadata)`. `WebhookEvent(external_event_id, external_payment_id, outcome, raw)`.

---

## File Structure

**New backend module `apps/api/src/yupay/modules/payme/`**

- `__init__.py`
- `errors.py` — `PaymeError` exception + the exact-code catalogue (pure).
- `models.py` — `PaymeTransaction` ORM.
- `service.py` — the 7 method handlers + validation + checkout-URL builder.
- `routes.py` — the JSON-RPC endpoint (Basic auth + dispatch).
- `api.py` — public surface (`router`, `PaymeTransaction`).
- `README.md`.

**Edits**

- `apps/api/src/yupay/modules/payments/service.py` — add public provider-lifecycle hooks (`settle_provider_payment`, `reverse_provider_payment`, `cancel_pending_provider_payment`); extract the refund-reversal core.
- `apps/api/src/yupay/modules/payments/gateways/payme.py` — new `PaymeGateway`.
- `apps/api/src/yupay/modules/payments/gateways/__init__.py` — REGISTRY `"payme"` → `PaymeGateway()`.
- `apps/api/src/yupay/core/config.py` — `payme_*` settings.
- `apps/api/src/yupay/core/logging.py` — redactor keys.
- `apps/api/src/yupay/api/v1/__init__.py` — mount the payme router.
- `apps/api/migrations/versions/NNNN_payme_transactions.py`.
- `apps/scheduler/src/yupay_scheduler/jobs/payme_timeout.py` + `main.py`.
- `docker-compose.yml`, `infra/secrets-example/api.env`, `infra/caddy/Caddyfile.prod`.
- `apps/miniapp/src/lib/payment-methods.ts` (payme slot currency gating) + i18n (already has `payment.payme.sub`).

**Docs**

- `docs/decisions/0034-payme-merchant-api.md`, `apps/api/src/yupay/modules/payme/README.md`, `docs/runbooks/payme-troubleshooting.md`, `docs/architecture/sequence-diagrams/payme-payment.mmd`, `docs/architecture/module-map.md`.

---

## Task 1: Migration + `PaymeTransaction` model

**Files:**

- Create: `apps/api/src/yupay/modules/payme/__init__.py` (empty), `apps/api/src/yupay/modules/payme/models.py`
- Create: `apps/api/migrations/versions/NNNN_payme_transactions.py` (chain from the current head `0026_broadcasts` — run `make migration name=payme_transactions` or hand-write with `down_revision="0026_broadcasts"`)
- Modify: `apps/scheduler/src/yupay_scheduler/main.py` (model-touch import)
- Test: `apps/api/tests/integration/test_payme_models.py`

**Interfaces produced:** `PaymeTransaction` ORM.

**Columns** (mirror `payments/models.py` idioms — `UUID(as_uuid=False)`, `server_default=text(...)`):
`id` uuid PK; `payme_id` `String(64)` **UNIQUE** (`uq_payme_transactions_payme_id`) not null; `order_id` uuid FK `orders.id` (ondelete RESTRICT) not null; `payment_id` uuid FK `payments.id` (ondelete SET NULL) nullable; `amount_tiyin` `BigInteger` not null; `state` `Integer` not null; `reason` `Integer` nullable; `create_time` `BigInteger` not null server_default `'0'`; `perform_time` `BigInteger` not null server_default `'0'`; `cancel_time` `BigInteger` not null server_default `'0'`; `fiscal_data` `JSONB` not null server_default `text("'{}'::jsonb")`; `created_at`/`updated_at` timestamptz server_default CURRENT_TIMESTAMP. CHECK `state IN (1,2,-1,-2)` (`ck_payme_transactions_state`). Index `ix_payme_transactions_order` on `order_id`. Index `ix_payme_transactions_state_create` on `(state, create_time)` (for the 12h sweep).

- [ ] **Step 1: Write `models.py`** (`PaymeTransaction`).
- [ ] **Step 2: Generate + fill the migration** (`op.create_table` with the columns, UNIQUE, CHECK, indices, FKs; `downgrade` drops the table). `down_revision = "0026_broadcasts"`.
- [ ] **Step 3: Model-touch** — add `from yupay.modules.payme import models as _payme_models  # noqa: F401` to `apps/scheduler/src/yupay_scheduler/main.py` (the scheduler job imports these).
- [ ] **Step 4: Failing integration test** — insert a `PaymeTransaction`, assert `UNIQUE(payme_id)` raises on a dup, and the `state` CHECK rejects `3`.
- [ ] **Step 5: Run** `make migrate` then `cd apps/api && uv run pytest tests/integration/test_payme_models.py -v`; `uv run mypy apps`; `uv run ruff check`.
- [ ] **Step 6: Commit** `feat(payme): payme_transactions model + migration`.

---

## Task 2: Payme error catalogue (`errors.py`)

**Files:**

- Create: `apps/api/src/yupay/modules/payme/errors.py`
- Test: `apps/api/tests/unit/test_payme_errors.py`

**Interfaces produced:**

```python
class PaymeError(Exception):
    def __init__(self, code: int, message: dict[str, str], data: str | None = None) -> None: ...
    code: int
    message: dict[str, str]   # {"ru":..,"uz":..,"en":..}
    data: str | None
    def to_rpc_error(self) -> dict[str, Any]:   # {"code":..,"message":{...},"data":..}
        ...

# Factory helpers returning a ready-to-raise PaymeError with the exact code + localized message:
def invalid_amount() -> PaymeError                      # -31001
def transaction_not_found() -> PaymeError               # -31003
def cannot_cancel_delivered() -> PaymeError             # -31007
def operation_not_permitted() -> PaymeError             # -31008
def order_not_found() -> PaymeError                     # -31050, data="order_id"
def order_not_payable() -> PaymeError                   # -31051, data="order_id"
def unauthorized() -> PaymeError                        # -32504
def method_not_post() -> PaymeError                     # -32300
def bad_json() -> PaymeError                            # -32700
def bad_rpc_fields() -> PaymeError                      # -32600
def method_not_found() -> PaymeError                    # -32601
def internal_error() -> PaymeError                      # -32400
def fiscal_receipt_not_found() -> PaymeError            # -32001
```

Each message a `{ru,uz,en}` dict (use the docs' RU strings; sensible uz/en). `to_rpc_error` returns the exact wire shape.

- [ ] **Step 1: Failing unit tests** — each factory returns the exact `code`; `order_not_found().data == "order_id"`; `to_rpc_error()` shape has `code`/`message` (a dict with ru/uz/en)/`data`; `invalid_amount().to_rpc_error()["code"] == -31001`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `errors.py`.**
- [ ] **Step 4: Run** → PASS; mypy + ruff.
- [ ] **Step 5: Commit** `feat(payme): error catalogue`.

---

## Task 3: Config + log redactor + infra env

**Files:**

- Modify: `apps/api/src/yupay/core/config.py`, `apps/api/src/yupay/core/logging.py`, `docker-compose.yml`, `infra/secrets-example/api.env`
- Test: `apps/api/tests/unit/test_payme_config.py`

**Config (after the octo block, ~line 286):**

```python
# --- acquirer: Payme (Paycom) Merchant API ---
payme_merchant_id: str = Field(default="")
payme_key: str = Field(default="")          # production/cabinet key
payme_test_key: str = Field(default="")     # sandbox key
payme_login: str = Field(default="Paycom")  # Basic-auth username (convention)
payme_checkout_url: str = Field(default="https://checkout.paycom.uz")
```

- `logging.py`: add `"payme_key"`, `"payme_test_key"` to `REDACTED_KEYS`.
- `docker-compose.yml`: pass `PAYME_MERCHANT_ID`, `PAYME_KEY`, `PAYME_TEST_KEY`, `PAYME_LOGIN`, `PAYME_CHECKOUT_URL` (mirror the octo block; default checkout to `https://checkout.paycom.uz`).
- `infra/secrets-example/api.env`: a Payme block (empty placeholders + a note: sandbox = test key + `test.paycom.uz`; go-live = prod key + `checkout.paycom.uz`).

- [ ] **Step 1: Failing test** — `get_settings().payme_login == "Paycom"`, `payme_checkout_url` default; setting `PAYME_TEST_KEY` env is read (clear the settings cache in a `yield` fixture — clear on BOTH sides, mirror `tests/conftest.py`).
- [ ] **Step 2–4:** implement; run; mypy + ruff.
- [ ] **Step 5: Commit** `feat(payme): config + secrets + log redactor`.

---

## Task 4: Payments provider-lifecycle hooks

**Files:**

- Modify: `apps/api/src/yupay/modules/payments/service.py` (+ `__all__`)
- Test: `apps/api/tests/integration/test_payments_provider_hooks.py`

**Why:** Payme's `PerformTransaction`/`CancelTransaction` must reuse the single paid/refund chokepoints (never a second code path that flips order status or posts the ledger). Expose three public helpers and share the refund-reversal core.

**Interfaces produced (public, add to `__all__`):**

```python
async def settle_provider_payment(db, *, payment: Payment, external_event_id: str) -> None:
    """Provider-driven success (e.g. Payme PerformTransaction). Builds a synthetic
    WebhookEvent(outcome='succeeded', external_event_id=...) and calls the existing
    _mark_payment_succeeded — order → paid + fulfilment saga. Idempotent: no-op if
    payment.status is already 'succeeded'."""

async def reverse_provider_payment(db, *, payment: Payment, external_event_id: str, actor: str = "payme") -> None:
    """Provider-driven refund of a SUCCEEDED payment (e.g. Payme CancelTransaction on a
    performed tx, state 2→-2). Runs the SAME ledger reversal + order→refunded as
    refund_admin (shared core). Idempotent: no-op if already 'refunded'."""

async def cancel_pending_provider_payment(db, *, payment: Payment, actor: str = "payme") -> None:
    """Provider-driven cancel of a PENDING payment (e.g. Payme CancelTransaction on an
    unperformed tx, state 1→-1). Marks the payment 'cancelled'; no ledger, no fulfilment.
    Idempotent."""
```

Refactor: extract the ledger-reversal + order-walk block from `refund_admin` into a private `_apply_refund_reversal(db, *, payment, amount, actor, external_ref)`; both `refund_admin` and `reverse_provider_payment` call it. `settle_provider_payment` wraps `_mark_payment_succeeded` with a synthetic `WebhookEvent`.

- [ ] **Step 1: Failing integration tests** — `settle_provider_payment` on a pending Payme payment → payment succeeded + order paid + fulfilment started (assert order.status); second call is a no-op (idempotent). `reverse_provider_payment` on a succeeded payment → refunded + ledger reversed (assert the wallet/house posting like the existing refund tests). `cancel_pending_provider_payment` on a pending payment → cancelled, order NOT paid, no ledger.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the three helpers + the `_apply_refund_reversal` extraction; keep `refund_admin` behavior byte-for-byte (its existing tests must still pass).
- [ ] **Step 4: Run** the new tests **and** the existing `test_payments_error_paths.py` + refund tests → all PASS; mypy + ruff; confirm ≥95% on the touched service functions.
- [ ] **Step 5: Commit** `feat(payments): provider-lifecycle hooks (settle/reverse/cancel)`.

---

## Task 5: Payme service — the seven method handlers

**Files:**

- Create: `apps/api/src/yupay/modules/payme/service.py`
- Test: `apps/api/tests/integration/test_payme_service.py`

**Interfaces produced (each takes `db: AsyncSession` + the method's params, returns the RPC `result` dict, raises `PaymeError`):**

```python
async def check_perform_transaction(db, *, amount: int, account: dict[str, Any]) -> dict   # {"allow": True}
async def create_transaction(db, *, payme_id: str, time: int, amount: int, account: dict) -> dict  # {create_time, transaction, state}
async def perform_transaction(db, *, payme_id: str) -> dict                                 # {transaction, perform_time, state}
async def cancel_transaction(db, *, payme_id: str, reason: int) -> dict                     # {transaction, cancel_time, state}
async def check_transaction(db, *, payme_id: str) -> dict                                   # {create_time, perform_time, cancel_time, transaction, state, reason}
async def get_statement(db, *, from_ms: int, to_ms: int) -> dict                            # {"transactions": [...]}
async def set_fiscal_data(db, *, payme_id: str, type_: str, fiscal_data: dict) -> dict      # {"success": True}
def build_checkout_url(*, order_id: str, amount_tiyin: int, return_url: str | None, lang: str = "ru") -> str
```

**Validation logic (exact — this is the sandbox-critical part):**

- `_resolve_order(db, account)` — `account["order_id"]` missing/unknown → `order_not_found()` (-31050); load the order.
- `_expected_tiyin(order)` → `int(order.total_charged * 100)` (assert exact; the `*100` of a 6-dp Decimal must be integral).
- **check_perform:** order not found → -31050; order.status != `pending_payment` → `order_not_payable()` (-31051); `amount != expected_tiyin` → `invalid_amount()` (-31001); else `{"allow": True}`.
- **create_transaction:** claim any existing row by `payme_id` `FOR UPDATE`; if it exists → re-validate + return its `{create_time, transaction, state}` (idempotent). Else re-run check-perform validations; if the order already has a **different** active (state 1 or 2) payme transaction → `operation_not_permitted()` (-31008); create the `Payment` (via the pending intent, or a new `Payment(provider="payme", status="pending", amount=total_charged, currency="UZS")`) + the `PaymeTransaction(state=1, create_time=time, amount_tiyin=amount)`; return `{create_time: time, transaction: <row.id>, state: 1}`.
- **perform_transaction:** row by `payme_id` `FOR UPDATE`; not found → -31003; state 2 → return stored (idempotent); state < 0 → -31008; state 1 → set state 2, `perform_time = now_ms()`, call `payments.service.settle_provider_payment(db, payment=<row.payment>, external_event_id=payme_id)`; return `{transaction, perform_time, state: 2}`.
- **cancel_transaction:** row `FOR UPDATE`; not found → -31003; already `-1`/`-2` → return stored (idempotent); state 1 → set `-1`, `cancel_time`, `reason`, `cancel_pending_provider_payment`; state 2 → if order fully delivered (fulfilment terminal-delivered) → `cannot_cancel_delivered()` (-31007), else set `-2`, `cancel_time`, `reason`, `reverse_provider_payment`; return `{transaction, cancel_time, state}`.
- **check_transaction:** row by `payme_id`; not found → -31003; return the six fields (0 for unset times, `null` reason).
- **get_statement:** rows with `from_ms <= create_time <= to_ms`, asc by create_time; map each to `{id: payme_id, time: create_time, amount: amount_tiyin, account: {"order_id": order_id}, create_time, perform_time, cancel_time, transaction: id, state, reason, receivers: []}`.
- **set_fiscal_data:** row by `payme_id`; not found → `fiscal_receipt_not_found()` (-32001); store `fiscal_data` keyed by `type_` into `row.fiscal_data`; `{"success": True}`.
- `build_checkout_url`: param string `m=<merchant_id>;ac.order_id=<order_id>;a=<amount_tiyin>` (+ `;c=<return_url>` if given, `;l=<lang>`), `base64.b64encode(...)`, `f"{payme_checkout_url}/{b64}"`.
- Use `now_ms()` = `int(now().timestamp() * 1000)` (from `core.clock.now`).

- [ ] **Step 1: Failing integration tests** (`test_payme_service.py`) — seed a UZS order (`pending_payment`, `total_charged`). Cover: check_perform allow; wrong amount → -31001; unknown account → -31050; non-pending order → -31051; create → state 1 + idempotent replay (same payme_id → same result, one row); perform → state 2 + order paid (assert) + idempotent; cancel state1→-1; cancel state2→-2 (refund reconciled); check_transaction shape; get_statement window; set_fiscal_data stores; build_checkout_url exact base64 for a known input.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `service.py`.**
- [ ] **Step 4: Run** → PASS; mypy + ruff; ≥95% coverage on `service.py`.
- [ ] **Step 5: Commit** `feat(payme): merchant-api method handlers`.

---

## Task 6: JSON-RPC endpoint + auth + mount + OpenAPI

**Files:**

- Create: `apps/api/src/yupay/modules/payme/routes.py`, `apps/api/src/yupay/modules/payme/api.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (mount)
- Test: `apps/api/tests/integration/test_payme_merchant.py`

**Route:** `router = APIRouter(prefix="/payments/payme", tags=["payme"])`; `@router.post("/merchant")`. Reads the raw JSON body, validates Basic auth, dispatches by `method`, returns `{"result": ..., "id": <req_id>}` or `{"error": <PaymeError.to_rpc_error()>, "id": <req_id>}`, **HTTP 200 always** (use a `Response`/plain dict; do not raise HTTP exceptions).

**Auth helper:** parse `Authorization: Basic <b64>` → `base64decode` → `"<login>:<key>"`; require `login == settings.payme_login` and `key in {settings.payme_key, settings.payme_test_key}` (ignoring empty configured keys). On any failure → return `unauthorized()` (-32504) as an RPC error with HTTP 200.

**Dispatch:** map `method` → the `service.*` handler, translating `params` field names (`params["id"]` → `payme_id`, `params["from"]/["to"]` → `from_ms/to_ms`, `params["type"]` → `type_`). Missing/mistyped params → `bad_rpc_fields()` (-32600). Unknown method → `method_not_found()` (-32601). Body not JSON → `bad_json()` (-32700). Wrap all handler calls: `PaymeError` → its `to_rpc_error()`; any other exception → `internal_error()` (-32400) (logged, no PII).

- [ ] **Step 1: Failing integration tests** — the **two mandatory sandbox sequences** end-to-end over HTTP against the mounted app:
  1. _Unconfirmed_: wrong auth → `-32504`; `CheckPerformTransaction` bad amount → `-31001`; unknown account → `-31050`; then `CheckPerformTransaction`(ok) → `CreateTransaction` (state 1) → `CancelTransaction` (state -1).
  2. _Confirmed_: `CheckPerformTransaction` → `CreateTransaction` → `PerformTransaction` (order → paid, assert) → `CancelTransaction` (state -2, refund reconciled).
     Plus: non-JSON body → `-32700`; unknown method → `-32601`; a GET → `-32300` (or 405 handled → `-32300` in body); idempotent replay of Create/Perform/Cancel over HTTP returns the same result and makes no duplicate rows; every response is HTTP 200.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `routes.py` + `api.py`;** mount in `api/v1/__init__.py` (`from yupay.modules.payme.api import router as payme_router` + `router.include_router(payme_router)`).
- [ ] **Step 4: Run** → PASS; mypy + ruff.
- [ ] **Step 5: Regenerate OpenAPI** — `cd apps/api && uv run python -m yupay.scripts.export_openapi ../../docs/api/openapi.json && cd ../.. && pnpm --filter @yupay/api-client gen:api`.
- [ ] **Step 6: Commit** `feat(payme): JSON-RPC merchant endpoint + auth + mount` (incl regenerated files).

---

## Task 7: `PaymeGateway` adapter + REGISTRY swap

**Files:**

- Create: `apps/api/src/yupay/modules/payments/gateways/payme.py`
- Modify: `apps/api/src/yupay/modules/payments/gateways/__init__.py`
- Test: `apps/api/tests/unit/test_payme_gateway.py`

**`PaymeGateway`** implements `PaymentGateway`:

- `provider = "payme"`.
- `available` → `bool(settings.payme_merchant_id and (settings.payme_key or settings.payme_test_key))`.
- `create_intent(*, db, order, return_url)` → guard `order.currency == "UZS"` and `total_charged > 0` (else `PaymentGatewayError`); `amount_tiyin = int(order.total_charged * 100)`; `intent_url = payme.service.build_checkout_url(order_id=order.id, amount_tiyin=amount_tiyin, return_url=return_url)`; return `PaymentIntent(external_id=f"payme:{order.id}", intent_url=intent_url, status="pending", extra_metadata={"amount_tiyin": amount_tiyin})`. (The `payments.create_intent` service wraps this into a `Payment` row as it does for octo.)
- `verify_webhook` → raise `PaymentNotIntegratedError("Payme uses the /payments/payme/merchant JSON-RPC endpoint, not verify_webhook")` (Payme never hits the generic webhook route).
- `refund(*, payment, amount)` → raise `PaymentGatewayError("refund a Payme payment from the Payme cabinet; it reconciles via CancelTransaction")` → the admin refund path answers 409 (locked decision).

**Registry:** in `gateways/__init__.py`, replace the `"payme": StubGateway(...)` entry with `"payme": PaymeGateway()`, import `PaymeGateway`, add to `__all__`.

- [ ] **Step 1: Failing unit tests** — `available` reflects config (empty → False; merchant+test key → True); `create_intent` builds the expected `intent_url` (exact base64) and rejects non-UZS; `refund` raises; `verify_webhook` raises; `REGISTRY["payme"]` is a `PaymeGateway`. (Use the settings-cache `yield` fixture.)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** + registry swap. Avoid an import cycle: `gateways/payme.py` may import `payme.service.build_checkout_url` (pure, no route import) — confirm `payme.service` doesn't import `payments.gateways`.
- [ ] **Step 4: Run** → PASS; also run `test_adapter_stubs.py` (registry lookup) + `mypy apps` + ruff.
- [ ] **Step 5: Commit** `feat(payme): gateway adapter + registry`.

---

## Task 8: Scheduler 12h auto-cancel job

**Files:**

- Create: `apps/scheduler/src/yupay_scheduler/jobs/payme_timeout.py`
- Modify: `apps/scheduler/src/yupay_scheduler/main.py` (register)
- Test: `apps/api/tests/integration/test_payme_timeout.py`

**Job** (mirror `waxpeer_reconcile.py`): `register(scheduler)` → `add_job(run_payme_timeout, trigger="interval", seconds=300, id="payme.timeout", replace_existing=True, max_instances=1, coalesce=True)`. `run_payme_timeout()`: find `PaymeTransaction` rows with `state == 1` and `create_time < now_ms() - 43_200_000`; for each (own session, `FOR UPDATE`): set `state = -1`, `reason = 4`, `cancel_time = now_ms()`, and call `payments.service.cancel_pending_provider_payment` for its payment. Import from `payme.service`/`payments.service` **directly** (not `.api`/`.routes` — avoid the api→routes→api/v1 cycle, per `waxpeer_reconcile`'s note).

- [ ] **Step 1: Failing integration test** — seed a state-1 row with `create_time` 13h ago → one tick cancels it to `-1`/reason `4` and its payment → cancelled; a state-1 row 1h old is untouched; a state-2 row is untouched. Monkeypatch/pin any sleep; make the 12h constant a module const for a fast test.
- [ ] **Step 2–4:** implement; register; run; mypy + ruff.
- [ ] **Step 5: Commit** `feat(scheduler): payme 12h auto-cancel job`.

---

## Task 9: Mini App Payme method (UZS gating) + i18n

**Files:**

- Modify: `apps/miniapp/src/lib/payment-methods.ts` (confirm the `payme` slot's `currency` is `"UZS"`)
- Verify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` already have `payment.payme.sub` (they do). If any locale is missing it, add it.
- Test: none new required (the redirect path is identical to octo; `useAvailableProviders` already filters by the backend `available`).

**Behavior:** the `payme` slot already exists (`id/provider="payme"`, `subKey="payment.payme.sub"`, `paymeIcon`). Ensure its `currency` field is `"UZS"` so the method is shown only for UZS orders and hidden for USD/RUB, matching the existing per-currency gating. Once `PaymeGateway.available` is true (keys set), `GET /payments/providers` lists `payme` and the method renders; selecting it calls `create_intent` and redirects to `intent_url` — same code path as octo, no new UI.

- [ ] **Step 1:** confirm/set the payme slot `currency: "UZS"`; confirm i18n parity for `payment.payme.sub` across ru/en/uz.
- [ ] **Step 2:** `pnpm --filter @yupay/miniapp exec tsc --noEmit` + eslint + `pnpm exec prettier --check` on the touched files.
- [ ] **Step 3: Commit** `feat(miniapp): enable Payme method for UZS`.

---

## Task 10: Caddy IP allowlist for the merchant endpoint

**Files:**

- Modify: `infra/caddy/Caddyfile.prod` (and `Caddyfile.dev` if it proxies the API path)
- Test: manual (config change).

**Behavior:** restrict `POST /api/v1/payments/payme/merchant` to Payme's source IPs `185.234.113.1`–`185.234.113.15` (a `@payme_ips` matcher on `remote_ip 185.234.113.0/28` covers `.0–.15`; `.1–.15` are the documented set) → 403 otherwise. Keep the app-layer `-32504` auth as defense in depth (do NOT rely on IP alone).

- [ ] **Step 1:** add the matcher + `handle`/`respond 403` for non-Payme IPs on that path; keep the rest of the API open.
- [ ] **Step 2:** `caddy validate --config infra/caddy/Caddyfile.prod` (or `docker run caddy caddy fmt/validate`) to confirm the config parses.
- [ ] **Step 3: Commit** `chore(infra): restrict Payme merchant endpoint to Payme IPs`.

---

## Task 11: Documentation

**Files:**

- Create: `docs/decisions/0034-payme-merchant-api.md` (MADR), `apps/api/src/yupay/modules/payme/README.md`, `docs/runbooks/payme-troubleshooting.md`, `docs/architecture/sequence-diagrams/payme-payment.mmd`
- Modify: `docs/architecture/module-map.md`

**Content:**

- **ADR-0034** — the "we are the provider's JSON-RPC server" pattern (contrast with `verify_webhook`); why Merchant API over Subscribe; the refund-via-cabinet + auto-reconcile decision; amount/tiyin + `account.order_id`; the doc gaps made configurable (login `Paycom`, checkout host, no documented response timeout).
- **README** — the 7 methods, the state machine + reasons, the error catalogue, auth, config, the checkout-URL format.
- **runbook** — sandbox setup (register Endpoint URL + test key at `test.paycom.uz`, run the automated suite), go-live switch (prod key + `checkout.paycom.uz`), reading a stuck transaction, the refund-via-cabinet flow, the 12h job, the IP allowlist, what each error code means to an operator.
- **sequence diagram** — customer → intent → checkout → Payme → the Create/Perform (or Cancel) method calls → order paid/refunded.
- **module-map** — add `payme` with edges (payments, orders, fulfilment, scheduler).

- [ ] **Step 1–2:** write all five; `pnpm exec prettier --check` clean; Mermaid parses.
- [ ] **Step 3: Commit** `docs(payme): ADR-0034, README, runbook, sequence diagram, module-map`.

---

## Final verification (after all tasks)

- [ ] `make lint typecheck test` green (Python + TS).
- [ ] `make gen-api` — no drift.
- [ ] **Local integration**: the two sandbox sequences pass over HTTP (Task 6 tests).
- [ ] **Real sandbox** (once you provide `PAYME_MERCHANT_ID` + `PAYME_TEST_KEY`): point a public tunnel (or the deployed staging) at `/api/v1/payments/payme/merchant`, set that Endpoint URL + the test key in the Payme cabinet, run Payme's automated sandbox suite at `test.paycom.uz`, and confirm all checks pass. Then go-live: prod key + `checkout.paycom.uz`.
