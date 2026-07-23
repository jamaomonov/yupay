# Click (Shop API) Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept UZS payments via the Click Shop API — expose two form-encoded webhooks (`/prepare`, `/complete`) Click drives through the payment, verify the MD5 `sign_string`, reconcile via the shared payments hooks, and build the `my.click.uz` pay link for both surfaces (web + mini app).

**Architecture:** Click is the inverted-webhook twin of the shipped Payme/Uzum modules. Build `modules/click/` mirroring `modules/uzum/`, reuse the existing `payments` lifecycle hooks (`settle_provider_payment` / `cancel_pending_provider_payment`) and the refund-guard money-safety rule. **Do not rebuild the payments hooks or the config — both already exist.**

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, APScheduler; miniapp Vite/React + web Next.js + i18n JSON.

**Reference spec:** `docs/superpowers/specs/2026-07-23-click-shop-api-design.md` (read it — exact Prepare/Complete contracts, both `sign_string` formulas, the 0/-1..-9 error catalogue).

**Reference twin (the template to mirror):** `apps/api/src/yupay/modules/uzum/` and its tests `apps/api/tests/{unit,integration}/test_uzum_*.py`. Every Click file has a Uzum sibling; the plan gives the exact Click deltas.

## Global Constraints

- **Endpoints:** `POST /api/v1/payments/click/{prepare,complete}`. Body is **`application/x-www-form-urlencoded`** (NOT JSON — read form fields). Response is **JSON**. Always respond **HTTP 200** with a JSON body carrying `error`/`error_note` (+ echo fields) — a signature/validation failure is a negative `error` at HTTP 200, never a 4xx/5xx.
- **Signature (per-service secret):** every request carries `service_id`, `sign_time`, `sign_string`. Pick the secret by `service_id` (`click_service_id_web`→`click_secret_key_web`, `click_service_id_bot`→`click_secret_key_bot`); unknown service → `-1`. Build MD5 over the **raw wire string values** in the documented order:
  - Prepare: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time)`
  - Complete: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + merchant_prepare_id + amount + action + sign_time)`
    Constant-time compare (`hmac.compare_digest`) to the received `sign_string` (case-insensitive hex); mismatch → `-1`. The `amount` in the hash is the RAW request string — never reformat it.
- **Amount:** soums (major units). Compare `Decimal(str(raw_amount))` to `order.total_charged` / `txn.amount`; mismatch → `-2`. Never float `==`.
- **Ids:** `merchant_trans_id` = our `orders.id` (str). `merchant_prepare_id` = our integer (`ClickTransaction` bigint identity). `merchant_confirm_id` = same numeric id.
- **Error codes (exact notes):** `0` Success · `-1` `SIGN CHECK FAILED!` · `-2` `Incorrect parameter amount` · `-3` `Action not found` · `-4` `Already paid` · `-5` `User does not exist` · `-6` `Transaction does not exist` · `-7` `Failed to update user` · `-8` `Error in request from click` · `-9` `Transaction cancelled`.
- **Negative inbound `error`:** if a request's own `error < 0`, cancel our side (cancel-pending IF the txn/payment is still pending) and return `-9`.
- **Statuses:** `ClickTransaction.status` ∈ `PREPARED` / `CONFIRMED` / `CANCELLED`.
- **Idempotency:** Prepare replay (same `click_trans_id`+`service_id`) → same `merchant_prepare_id`; Complete replay on CONFIRMED → `-4`; concurrent Prepare INSERT race → catch `IntegrityError` on `(click_trans_id, service_id)`, re-read (savepoint pattern from Uzum §12).
- **Two providers:** `"click"` (web, `click_service_id_web`/`click_secret_key_web`) and `"click_miniapp"` (bot, `click_service_id_bot`/`click_secret_key_bot`). Each frontend selects its own provider id.
- **Money-safety (from the Uzum final review):** `_ensure_payment` reuse means a payment can be shared across transactions — the cancel path (negative error, stale sweep) MUST guard `payment.status == "pending"` before cancel-pending; never cancel a shared succeeded payment.
- **Reuse, do NOT rebuild:** `payments.service.settle_provider_payment` / `cancel_pending_provider_payment` (already exist); `Settings.click_*` config (already landed, commit `1efe80e`).
- Money as `Decimal`, never float. mypy --strict, ruff (line 100), Google docstrings. `prettier --write` every touched markdown/JSON (CI runs `prettier --check .`). All three locales (`ru`/`en`/`uz`) for any new user-facing string. Coverage ≥ 95% for this payments-adjacent code.

## File Structure

- Create `apps/api/src/yupay/modules/click/{__init__.py,api.py,models.py,errors.py,signature.py,service.py,routes.py,README.md}`
- Create `apps/api/migrations/versions/0029_click_transactions.py`
- Create `apps/api/src/yupay/modules/payments/gateways/click.py`
- Create `apps/scheduler/src/yupay_scheduler/jobs/click_timeout.py`
- Create `docs/decisions/0036-click-shop-api.md`, `docs/runbooks/click-troubleshooting.md`, `docs/architecture/sequence-diagrams/click-payment.mmd`
- Create tests: `apps/api/tests/unit/{test_click_errors.py,test_click_signature.py,test_click_gateway.py}`, `apps/api/tests/integration/{test_click_service.py,test_click_webhook.py,test_click_timeout.py}`
- Modify `apps/api/src/yupay/api/v1/__init__.py` (mount), `apps/api/src/yupay/modules/payments/gateways/__init__.py` (REGISTRY: two providers), `apps/scheduler/.../main.py` (prime models + register job), `docs/architecture/module-map.md`
- Frontend: `apps/miniapp/src/lib/payment-methods.ts` (+ provider mapping), a web equivalent if the web app has its own method list, `packages/i18n/locales/{ru,en,uz}/*.json`

---

## Task 1: Migration + `ClickTransaction` model

**Files:**

- Create: `apps/api/src/yupay/modules/click/models.py`, `apps/api/src/yupay/modules/click/__init__.py`
- Create: `apps/api/migrations/versions/0029_click_transactions.py`
- Test: `apps/api/tests/integration/test_click_service.py` (model round-trip smoke test)

**Interfaces:**

- Produces: `ClickTransaction` ORM model — columns from spec §5: `id` (PK str `new_id()`), `merchant_prepare_id` (BigInteger, **DB IDENTITY / autoincrement sequence**, unique), `click_trans_id` (BigInteger), `service_id` (BigInteger), `order_id` (FK orders.id), `payment_id` (FK payments.id, ON DELETE SET NULL, nullable), `amount` (Numeric(20,6)), `status` (String, CHECK in `('PREPARED','CONFIRMED','CANCELLED')`), `click_paydoc_id` (BigInteger nullable), `prepare_time`/`complete_time`/`cancel_time` (timestamptz nullable), `created_at`/`updated_at` (timestamptz server_default now()). Unique index on `(click_trans_id, service_id)`; index on `order_id`.

**Steps:**

- [ ] **Step 1:** Mirror `apps/api/src/yupay/modules/uzum/models.py` for `ClickTransaction`/table `click_transactions`, applying the column deltas above. `merchant_prepare_id` needs a DB-generated integer — use `BigInteger` with `autoincrement=True` as a dedicated `Identity()`/sequence column (SQLAlchemy `Column(BigInteger, Identity(), unique=True)`), NOT the string PK. Google docstring, `Mapped[...]` typing.
- [ ] **Step 2:** Write migration `0029_click_transactions.py`, `down_revision = "0028_uzum_transactions"` (verify it is the current head via `uv run alembic heads`). `op.create_table` with the identity column for `merchant_prepare_id`, the status CHECK, the unique `(click_trans_id, service_id)` index, the `order_id` index, and both FKs. `downgrade` drops the table.
- [ ] **Step 3:** Import `ClickTransaction` where `UzumTransaction` is imported to prime the mapper (check `uzum/models.py`'s import site + the scheduler `main.py` model-prime block).
- [ ] **Step 4:** Smoke test in `test_click_service.py`: insert a `ClickTransaction` for a seeded order, read it back, assert `merchant_prepare_id` was auto-assigned an int. Run: `uv run pytest apps/api/tests/integration/test_click_service.py -q`. Expected PASS (migrations apply to 0029).
- [ ] **Step 5:** Commit `feat(api/click): click_transactions model + migration 0029`.

---

## Task 2: Click error catalogue (`errors.py`)

**Files:**

- Create: `apps/api/src/yupay/modules/click/errors.py`
- Test: `apps/api/tests/unit/test_click_errors.py`

**Interfaces:**

- Produces: `class ClickError(Exception)` with `__init__(self, code: int, note: str)`, attributes `code`, `note`, and `to_response(self, **echo) -> dict` returning `{"error": self.code, "error_note": self.note, **echo}`. Factories (name → code, note verbatim from spec §8): `sign_check_failed`→(-1,`SIGN CHECK FAILED!`), `incorrect_amount`→(-2,`Incorrect parameter amount`), `action_not_found`→(-3,`Action not found`), `already_paid`→(-4,`Already paid`), `user_not_found`→(-5,`User does not exist`), `transaction_not_found`→(-6,`Transaction does not exist`), `failed_to_update`→(-7,`Failed to update user`), `bad_request`→(-8,`Error in request from click`), `transaction_cancelled`→(-9,`Transaction cancelled`). (Success `0`/`Success` is rendered directly by handlers, not via an error factory.)

**Steps:**

- [ ] **Step 1: Write failing test** in `test_click_errors.py` (mirror `test_uzum_errors.py`): assert each factory's `.code` and `.note`, and that `to_response(click_trans_id=1, merchant_trans_id="o")` yields `{"error":<code>,"error_note":<note>,"click_trans_id":1,"merchant_trans_id":"o"}`.
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/unit/test_click_errors.py -q`. Expected FAIL (module missing).
- [ ] **Step 3:** Implement `errors.py`; populate `__all__`.
- [ ] **Step 4:** Run the test. Expected PASS.
- [ ] **Step 5:** Commit `feat(api/click): error catalogue`.

---

## Task 3: Signature (`signature.py`)

**Files:**

- Create: `apps/api/src/yupay/modules/click/signature.py`
- Test: `apps/api/tests/unit/test_click_signature.py`

**Interfaces:**

- Produces:
  - `secret_for_service(service_id: int) -> str | None` — returns the configured secret for `click_service_id_web`/`_bot`, or `None` for an unknown service.
  - `prepare_sign(*, click_trans_id: str, service_id: str, secret: str, merchant_trans_id: str, amount: str, action: str, sign_time: str) -> str` — the MD5 hex for Prepare (concatenate the raw strings in order + secret in its documented slot).
  - `complete_sign(*, ...same..., merchant_prepare_id: str) -> str` — the MD5 hex for Complete (adds `merchant_prepare_id` after `merchant_trans_id`).
  - `verify(expected_hex: str, received: str) -> bool` — case-insensitive constant-time compare (`hmac.compare_digest(expected.lower(), received.lower())`).
    All inputs are the RAW request strings (the caller passes `form["amount"]` etc. untouched).

**Steps:**

- [ ] **Step 1: Write failing test** in `test_click_signature.py`: with a fixed secret, assert `prepare_sign(...)` equals a hand-computed `md5(click_trans_id+service_id+secret+merchant_trans_id+amount+action+sign_time)` (compute the expected with `hashlib.md5` in the test from the same raw strings); same for `complete_sign` (with `merchant_prepare_id`). Assert `verify` is true for the matching hex (any case) and false for a tampered one. Assert `secret_for_service` returns the web/bot secret for the two configured ids and `None` for an unknown id (set the ids/secrets via monkeypatch env + settings cache clear).
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/unit/test_click_signature.py -q`. Expected FAIL.
- [ ] **Step 3:** Implement `signature.py` using `hashlib.md5(concat.encode()).hexdigest()` and `hmac.compare_digest`. Read secrets/ids from `get_settings()`.
- [ ] **Step 4:** Run the test. Expected PASS.
- [ ] **Step 5:** Commit `feat(api/click): sign_string build + verify`.

---

## Task 4: Click service — prepare / complete + checkout URL

**Files:**

- Create: `apps/api/src/yupay/modules/click/service.py`
- Test: `apps/api/tests/integration/test_click_service.py` (extend)

**Interfaces:**

- Consumes: `payments.service.settle_provider_payment`, `cancel_pending_provider_payment`; `signature.*`; `errors.*`; `Order`, `Payment`, `FulfillmentTask`.
- Produces (all `async`, `db: AsyncSession`, raise `ClickError` on failure, `flush` not commit):
  - `now()` helper for the timestamps.
  - `prepare(db, *, click_trans_id, service_id, click_paydoc_id, merchant_trans_id, amount, sign_time, sign_string) -> dict` → `{"click_trans_id","merchant_trans_id","merchant_prepare_id","error":0,"error_note":"Success"}`.
  - `complete(db, *, click_trans_id, service_id, merchant_trans_id, merchant_prepare_id, amount, sign_time, sign_string) -> dict` → `{"click_trans_id","merchant_trans_id","merchant_confirm_id","error":0,"error_note":"Success"}`.
  - `build_checkout_url(*, provider: str, order_id: str, amount, return_url) -> str`.
    Note: the route (Task 5) does signature verification + the negative-`error`/action guards; the service does order/amount/state logic + the money moves. (Split is a plan choice; keep signature in the route where the raw form is available — pass the already-verified fields into the service.)

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_click_service.py` (mirror `test_uzum_service.py`), on a seeded `pending_payment` order with `total_charged` = a whole-so'm amount `A` (so `amount == str(A)`):
  - `prepare` → PREPARED (row inserted, `merchant_prepare_id` int assigned, pending payment ensured, provider `"click"`); replay same `click_trans_id`+`service_id` → same `merchant_prepare_id`; wrong amount → `-2`; unknown order → `-5`; already-paid order → `-4`; cancelled/expired order → `-9`.
  - `complete` → CONFIRMED + settle (order paid); unknown `merchant_prepare_id` → `-6`; replay on CONFIRMED → `-4`; on CANCELLED → `-9`; amount mismatch → `-2`.
  - the negative-inbound-`error` path (a helper `cancel(...)` or an `error<0` branch) → CANCELLED + `-9`, and on a CONFIRMED txn the shared payment stays succeeded (money-safety guard).
  - `build_checkout_url("click", ...)` → `{click_pay_url}?service_id=108149&merchant_id=63276&amount=<A>&transaction_param=<order_id>&return_url=<ret>`; `build_checkout_url("click_miniapp", ...)` uses `service_id=108150`.
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/integration/test_click_service.py -q`. Expected FAIL.
- [ ] **Step 3: Implement `service.py`** adapting `uzum/service.py`:
  - `_resolve_order`, `_ensure_payment` (provider from the surface — see routing note), `_load_txn` by `(click_trans_id, service_id)` or by `merchant_prepare_id`, `_any_goods_delivered` (reused idea; Click v1 has no merchant refund, but keep the cancel guard on `payment.status`).
  - `prepare`: replay check → same id; resolve order (missing→-5, paid→-4, cancelled/expired→-9); `Decimal(amount) != total_charged` → -2; ensure payment; insert `ClickTransaction(status="PREPARED", prepare_time=now())` inside a `begin_nested()` catching `IntegrityError` on `(click_trans_id, service_id)` → re-read (Uzum §12 pattern); return dict with the assigned `merchant_prepare_id`.
  - `complete`: load by `merchant_prepare_id`; missing→-6; CONFIRMED→-4; CANCELLED→-9; `Decimal(amount) != txn.amount` → -2; `settle_provider_payment(...external_event_id=str(click_trans_id))`; status CONFIRMED + complete_time; return `merchant_confirm_id`.
  - `cancel` helper: if txn PREPARED and `payment.status == "pending"` → `cancel_pending_provider_payment`; set CANCELLED; (never touch a succeeded payment). Used by the negative-error path and the timeout sweep (Task 7).
  - `build_checkout_url`: pick `service_id` by provider (`"click"`→web, `"click_miniapp"`→bot); urlencode.
  - Use `SELECT ... FOR UPDATE` on the txn (and order in prepare).
- [ ] **Step 4:** Run the tests. Expected PASS.
- [ ] **Step 5:** Commit `feat(api/click): prepare/complete handlers + checkout url`.

---

## Task 5: Webhook endpoints + signature guard + mount + OpenAPI

**Files:**

- Create: `apps/api/src/yupay/modules/click/routes.py`, `apps/api/src/yupay/modules/click/api.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py`
- Test: `apps/api/tests/integration/test_click_webhook.py`

**Interfaces:**

- Produces: `router` with `POST /prepare`, `POST /complete` under `/payments/click`, reading **form-encoded** bodies (`await request.form()` or FastAPI `Form(...)` params). Each route: read the raw form fields (as strings); pick the secret via `signature.secret_for_service(service_id)` (None → `-1`); compute the expected sign via `signature.prepare_sign`/`complete_sign` from the RAW strings and `verify` against `sign_string` (fail → `-1`); check `action` (0 for prepare, 1 for complete, else `-3`); if the inbound `error < 0` → dispatch the service `cancel` and return `-9`; else dispatch `service.prepare`/`complete`; **commit inside the try/except** (commit failure → `-7`); always return **HTTP 200** JSON. On `ClickError`, return `err.to_response(click_trans_id=..., merchant_trans_id=...)`. `api.py` re-exports the router; mount in `api/v1/__init__.py`.

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_click_webhook.py` (mirror `test_uzum_webhook.py`) hitting the real ASGI app with `application/x-www-form-urlencoded` bodies:
  - Valid signature + seeded order: `/prepare` → `error:0` + `merchant_prepare_id`; then `/complete` (with that `merchant_prepare_id` + a correct sign) → `error:0`, order becomes `paid`.
  - Tampered `sign_string` → `error:-1`; unknown `service_id` → `-1`.
  - `action` wrong (e.g. 5) → `-3`.
  - Wrong amount → `-2`; unknown order on prepare → `-5`.
  - Inbound `error=-5000` → `-9` and the txn/payment cancelled (if it existed).
  - Every response is HTTP 200 with the JSON `error` body. (Compute the test `sign_string` with the same `hashlib.md5` over the raw strings + the test secret — set the two service ids/secrets via env/settings.)
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/integration/test_click_webhook.py -q`. Expected FAIL.
- [ ] **Step 3: Implement `routes.py`** (form parsing, sign guard, always-200, commit-inside-guard) + `api.py`; mount in `api/v1/__init__.py` (mirror the uzum mount). Then `make gen-api` and commit the regenerated `docs/api/openapi.json`.
- [ ] **Step 4:** Run the tests. Expected PASS.
- [ ] **Step 5:** Commit `feat(api/click): prepare/complete endpoints + sign guard + mount + openapi`.

---

## Task 6: `ClickGateway` (two providers) + REGISTRY

**Files:**

- Create: `apps/api/src/yupay/modules/payments/gateways/click.py`
- Modify: `apps/api/src/yupay/modules/payments/gateways/__init__.py`
- Test: `apps/api/tests/unit/test_click_gateway.py`

**Interfaces:**

- Produces: `class ClickGateway(PaymentGateway)` parametrised by surface — provider `"click"` (web) and `"click_miniapp"` (bot). `available` = `click_merchant_id` + that surface's `service_id` + `secret` all set. `create_intent` (UZS guard; `amount = order.total_charged` soums; calls `service.build_checkout_url(provider=<self.provider>, ...)`; `PaymentIntent(external_id=f"click:{order.id}", intent_url=..., status="pending", extra_metadata={"amount_soums": str(amount)})`; deferred import to avoid the cycle). `verify_webhook` raises `PaymentNotIntegratedError`; `refund` raises `PaymentGatewayError`. Register BOTH `"click"` and `"click_miniapp"` in `REGISTRY`.

**Steps:**

- [ ] **Step 1: Write failing tests** (mirror `test_uzum_gateway.py`): `available` false unconfigured / true when merchant+web-service+web-secret set (and independently for the bot surface); `create_intent` builds the exact pay URL for each provider's `service_id`; non-UZS → `PaymentGatewayError`; `REGISTRY["click"]` and `REGISTRY["click_miniapp"]` are `ClickGateway` with the right provider + service.
- [ ] **Step 2:** Run: `uv run pytest apps/api/tests/unit/test_click_gateway.py -q`. Expected FAIL.
- [ ] **Step 3:** Implement `gateways/click.py`; register both providers in `gateways/__init__.py`.
- [ ] **Step 4:** Run the tests. Expected PASS.
- [ ] **Step 5:** Commit `feat(api/click): payment gateway (web + miniapp providers) + registry`.

---

## Task 7: Scheduler stale-prepare sweep

**Files:**

- Create: `apps/scheduler/src/yupay_scheduler/jobs/click_timeout.py`
- Modify: `apps/scheduler/src/yupay_scheduler/main.py`
- Test: `apps/api/tests/integration/test_click_timeout.py`

**Interfaces:**

- Produces: an idempotent async job that finds `ClickTransaction` rows with `status == "PREPARED"` older than the cutoff (default 30 min; make it a module constant — confirm Click's window, spec §16 #4), sets each `CANCELLED` and calls `cancel_pending_provider_payment` **only when the backing payment is still `pending`** (money-safety guard from the Uzum Critical — never cancel a shared succeeded payment). Registered on the scheduler mirroring `uzum_timeout`.

**Steps:**

- [ ] **Step 1: Write the failing test** (mirror `test_uzum_timeout.py`): stale PREPARED + pending payment → CANCELLED + payment cancelled; fresh PREPARED untouched; CONFIRMED untouched; a stale PREPARED whose payment is `succeeded` (shared) → txn CANCELLED but payment stays `succeeded`.
- [ ] **Step 2:** Run it. Expected FAIL.
- [ ] **Step 3:** Implement `click_timeout.py` (mirror `uzum_timeout.py` incl. the model-graph prime); register in `main.py`.
- [ ] **Step 4:** Run the test. Expected PASS.
- [ ] **Step 5:** Commit `feat(scheduler/click): stale-prepare sweep`.

---

## Task 8: Frontend Click method (web + miniapp) + i18n

**Files:**

- Modify: `apps/miniapp/src/lib/payment-methods.ts` (Click method already may exist — verify; ensure provider `"click_miniapp"` for the miniapp), the web app's payment-method list (find it — likely `apps/web/src/...`), `packages/i18n/locales/{ru,en,uz}/*.json`

**Interfaces:**

- Produces: a Click payment method on both surfaces, UZS-gated, mapping to provider `"click_miniapp"` in the mini app and `"click"` on the web. i18n key present in all three locales.

**Steps:**

- [ ] **Step 1:** Investigate the current state: does a `click` method already exist in `payment-methods.ts` (like `uzum`/`payme` did)? If so, ensure the miniapp entry maps to provider `"click_miniapp"`. Find the web app's payment-method list and ensure it maps to `"click"`. If the web uses the miniapp's list or a shared one, resolve how each surface sends its provider id (this is spec §16 #1 — implement the confirmed approach).
- [ ] **Step 2:** Add/adjust the method entries + provider mapping. Add the i18n label to `ru`/`en`/`uz` if missing.
- [ ] **Step 3:** Run `pnpm exec turbo run lint typecheck test --filter=@yupay/miniapp` (+ the web app + i18n completeness) and `prettier --check` the touched files.
- [ ] **Step 4:** Commit `feat(web,miniapp/click): click payment method (per-surface provider) + i18n`.

---

## Task 9: Documentation

**Files:**

- Create: `apps/api/src/yupay/modules/click/README.md`, `docs/decisions/0036-click-shop-api.md`, `docs/runbooks/click-troubleshooting.md`, `docs/architecture/sequence-diagrams/click-payment.mmd`
- Modify: `docs/architecture/module-map.md`

**Steps:**

- [ ] **Step 1:** Module `README.md` — the two webhooks, the state machine (PREPARED→CONFIRMED/CANCELLED), the `sign_string` formulas, the error table, `build_checkout_url`, the two-provider surface routing. Mirror `uzum/README.md`. Verify every code/status/endpoint against the shipped `click/{errors,service,routes,signature}.py`.
- [ ] **Step 2:** ADR `0036` (MADR) — webhook model, MD5 signature, two services/providers, soums, negative-error cancel, reuse of shared hooks + the money-safety guard.
- [ ] **Step 3:** Runbook `click-troubleshooting.md` — operator error table (0/-1..-9), sign-check debugging (per-service secret, raw-string hashing), the stale-prepare sweep, auth by `service_id`.
- [ ] **Step 4:** Sequence diagram `click-payment.mmd` (Mermaid) — customer → pay link → Click → /prepare → /complete → fulfilment; the cancel path. Render via `mmdc` to catch parse errors.
- [ ] **Step 5:** Add the `click` row to `module-map.md`.
- [ ] **Step 6:** `prettier --write` all touched markdown. Commit `docs(click): module readme, ADR-0036, runbook, sequence diagram, module map`.

---

## Final verification (after all tasks)

- [ ] `make lint typecheck test` green locally; `prettier --check .` clean.
- [ ] Coverage ≥ 95% on `modules/click/*` and `gateways/click.py` (run from repo root).
- [ ] OpenAPI + TS client regenerated, no drift.
- [ ] All three locales updated for the new method label.
- [ ] `refund_admin` + payments hooks byte-for-byte unchanged (diff-check).
- [ ] Whole-branch review (opus) — focus: money-safety of complete/cancel + the shared-payment guard, signature verification (raw strings, per-service secret, constant-time), always-200, the two-provider routing.
- [ ] Deploy sandbox → provide Click the callback URLs (`/api/v1/payments/click/prepare` + `/complete`) for both services (108149 web, 108150 bot); run a real `my.click.uz/services/pay` test payment per surface.
