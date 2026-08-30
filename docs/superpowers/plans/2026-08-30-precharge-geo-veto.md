# Pre-charge geo veto + timed auto-refund — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse a stolen-card charge before money moves (country from `CF-IPCountry`, timezone fallback, trusted buyers exempt) and stop holding a victim's money past a deadline (auto-refund held orders).

**Architecture:** One pure decision (`_veto_decision`) with two feeders: enforcement point A inside the three acquirers' existing pre-charge stages (reusing each protocol's own "not payable" refusal), point B in the order-create route fed from the live request, answering 422 with a renderable error code. A scheduler sweep refunds `held_for_review` orders older than a deadline through the existing `refund_admin` path.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, apscheduler-style jobs in `apps/scheduler`, Vitest for the two frontends.

**Spec:** `docs/superpowers/specs/2026-08-30-precharge-geo-veto-design.md` — the binding authority; this plan implements it verbatim.

## Global Constraints

- mypy --strict, ruff line 100, Google docstrings; TS strict, no `any`.
- **Fail open, never blind:** the veto returns `None` on any internal error (savepoint + log, the `_gather` pattern) and never fires without a country or timezone in hand. The post-payment hold remains the net.
- **No PII widening:** country codes and timezones in payloads are fine; raw IPs stay in `order_evidence` only.
- Every new behaviour has an env switch: `RISK_PRECHARGE_VETO=false`, `RISK_HOME_COUNTRIES=` (empty), `RISK_HOLD_AUTO_REFUND_HOURS=0`.
- Webhook signature checks and idempotency semantics of the three acquirer protocols are untouched — the veto slots in beside the existing payability checks, after signature verification.
- i18n: every new user-facing string lands in ru/en/uz in the same task.
- Conventional Commits with the session trailers; one logical change per commit as marked.

---

### Task 1: `ip_country` on order evidence

**Files:**

- Modify: `apps/api/src/yupay/modules/evidence/models.py`, `apps/api/src/yupay/modules/evidence/service.py`, `apps/api/src/yupay/modules/evidence/schemas.py` (`OrderEvidenceOut`)
- Create: `apps/api/migrations/versions/0060_evidence_ip_country.py` (revises `0059_evidence_device_hash`)
- Test: `apps/api/tests/integration/test_order_evidence.py` (extend)

**Interfaces:**

- Produces: `OrderEvidence.ip_country: str | None` (2 chars, uppercase); pure `evidence.service.ip_country_from(raw: str | None) -> str | None`; `OrderEvidenceOut.ip_country`.

- [ ] **Step 1: Failing tests**

```python
from yupay.modules.evidence.service import ip_country_from


def test_ip_country_normalises_and_rejects_junk() -> None:
    assert ip_country_from("uz") == "UZ"
    assert ip_country_from("T1") == "T1"   # Tor sentinel is a signal, keep it
    assert ip_country_from("XX") == "XX"   # CF unknown sentinel, kept as-is
    assert ip_country_from(None) is None
    assert ip_country_from("") is None
    assert ip_country_from("USA") is None  # only two ASCII letters/digits
    assert ip_country_from("<script>") is None
```

Plus, in the existing capture test: send header `cf-ipcountry: NL` with the request and assert the stored row's `ip_country == "NL"`; assert the evidence pack DTO carries it.

- [ ] **Step 2: RED** — run `apps/api/tests/integration/test_order_evidence.py`, confirm failures.
- [ ] **Step 3: Implement.** Model column `ip_country: Mapped[str | None] = mapped_column(String(2), nullable=True)`; `ip_country_from` accepts exactly two chars matching `[A-Z0-9]{2}` after `.strip().upper()`; capture wires `ip_country=ip_country_from(request.headers.get("cf-ipcountry"))`. `OrderEvidenceOut` gains the field (a country code is not an address — say so in the docstring).
- [ ] **Step 4: Migration 0060** — additive column only, no backfill (docstring: historic rows stay NULL = "unknown"; the header did not exist then and NULL must never satisfy or fire any rule). Copy 0059's header style.
- [ ] **Step 5: Verify** — targeted tests, `uv run mypy apps`, ruff both.
- [ ] **Step 6: Commit** — `feat(api/evidence): capture the Cloudflare country on order evidence`

---

### Task 2: the veto decision

**Files:**

- Modify: `apps/api/src/yupay/core/config.py`, `apps/api/src/yupay/modules/orders/risk.py`
- Test: `apps/api/tests/unit/test_order_risk.py` (extend)

**Interfaces:**

- Produces:

```python
VETO_FOREIGN_COUNTRY = "precharge_foreign_country"
VETO_FOREIGN_TIMEZONE = "precharge_foreign_timezone"

def _veto_decision(is_trusted: bool, country: str | None, timezone: str | None, cfg: Settings) -> str | None
async def _is_trusted_buyer(db: AsyncSession, user_id: str | None) -> bool   # >=1 delivered order
async def precharge_veto(db: AsyncSession, order: Order, *, settings: Settings | None = None) -> str | None
```

- Consumes: `order_evidence.ip_country` (Task 1), existing `_csv`, `risk_home_timezones`.

- [ ] **Step 1: Settings** — after the ADR-0062 block:

```python
    risk_precharge_veto: bool = Field(default=True)
    risk_home_countries: str = Field(default="UZ")
    risk_hold_auto_refund_hours: int = Field(default=24)
```

(descriptions in the neighbours' voice: what it refuses, why trusted buyers pass, `0`/empty disables. The refund hours land here now so Task 5 needs no config edit.)

- [ ] **Step 2: Failing unit tests** — the decision table, pure:

```python
def test_foreign_country_vetoes_a_guest() -> None:
    assert _veto_decision(False, "NL", None, _cfg()) == VETO_FOREIGN_COUNTRY


def test_home_country_passes_whatever_the_timezone_says() -> None:
    # Country is the network's word, timezone the browser's; when both are
    # present the network wins — a VPN into UZ with a Kyiv clock is for the
    # post-payment hold to worry about, not a pre-charge refusal.
    assert _veto_decision(False, "UZ", "Europe/Kiev", _cfg()) is None


def test_timezone_is_only_a_fallback() -> None:
    assert _veto_decision(False, None, "Europe/Kiev", _cfg()) == VETO_FOREIGN_TIMEZONE
    assert _veto_decision(False, None, "Asia/Tashkent", _cfg()) is None


def test_no_signals_no_claim() -> None:
    assert _veto_decision(False, None, None, _cfg()) is None


def test_trusted_buyer_is_exempt() -> None:
    assert _veto_decision(True, "NL", "Europe/Amsterdam", _cfg()) is None


def test_tor_and_unknown_sentinels_veto() -> None:
    # T1/XX are never in a home list; they fall out of the same comparison.
    assert _veto_decision(False, "T1", None, _cfg()) == VETO_FOREIGN_COUNTRY
    assert _veto_decision(False, "XX", None, _cfg()) == VETO_FOREIGN_COUNTRY


def test_empty_home_list_and_kill_switch_disable() -> None:
    assert _veto_decision(False, "NL", None, _cfg(home_countries="")) is None
    assert _veto_decision(False, "NL", "Europe/Kiev", _cfg(veto=False)) is None
```

(extend `_cfg` with `home_countries="UZ"` / `veto=True` kwargs.) Empty `risk_home_countries` disables ONLY the country branch — the tz fallback still needs `risk_home_timezones`; kill switch disables both. Async wrapper tests: `precharge_veto` returns `None` for `purpose="wallet_topup"`; returns `None` when the DB explodes (reuse `_ExplodingDB`); trusted-buyer query counts only `delivered` orders (unit-test the SQL via the existing integration file if a fake can't express it honestly — implementer's call, say which).

- [ ] **Step 3: Implement.** `_veto_decision` order: kill switch → trusted → country present? (∉ `_csv(risk_home_countries)`, list non-empty → veto) → country absent: tz present ∧ home-tz list non-empty ∧ tz ∉ list → veto → `None`. `precharge_veto`: purpose gate → `begin_nested` savepoint + try/except fail-open (log `orders.risk.veto_failed`) → load evidence row by `order_id` → `_is_trusted_buyer` → `_veto_decision(trusted, row.ip_country, row.client_hints.get("timezone"), cfg)`. No evidence row → country=None, tz=None → no claim.
- [ ] **Step 4: Verify + commit** — `feat(api/orders): the pre-charge veto decision`

---

### Task 3: enforcement point A — the three acquirers

**Files:**

- Modify: `apps/api/src/yupay/modules/payme/service.py` (beside both `_check_perform` calls, lines ~235/~277), `apps/api/src/yupay/modules/click/service.py` (`prepare`, before allocating the transaction row), `apps/api/src/yupay/modules/uzum/service.py` (`check`, beside `_check_order_state`)
- Modify: `apps/api/src/yupay/modules/orders/risk.py` (event recorder)
- Test: one new case in each acquirer's existing integration suite

**Interfaces:**

- Produces: `async record_precharge_veto(db, order, reason, *, country, timezone) -> None` in `risk.py` — idempotent per order (skip if an `order.precharge_vetoed` event already exists), payload `{reason, country, timezone}` (codes, not addresses).
- Consumes: `precharge_veto` (Task 2).

- [ ] **Step 1: Failing integration tests** (one per acquirer, in their existing files, using their existing signed-request helpers). Shape, for Payme:

```python
async def test_check_perform_refuses_a_foreign_guest_order(...):
    # A guest order with evidence saying the buyer is not at home. The refusal
    # must be Payme's own -31051 — indistinguishable from any other unpayable
    # order — and no transaction row may exist afterwards.
    <create pending order + evidence row with ip_country="NL">
    resp = <CheckPerformTransaction call>
    assert resp["error"]["code"] == -31051
    <assert no PaymeTransaction row; assert exactly one order.precharge_vetoed event>
    <repeat the call; still one event>
```

Click asserts the same error object `prepare` already returns for a non-payable order and that no `ClickTransaction` row was allocated; Uzum asserts code `10009`. Each file also gets the mirror case: same order with `ip_country="UZ"` proceeds past the stage exactly as today. **Note for the implementer:** the suites' existing fixtures create orders with NO evidence row, and a missing row means no claim — so every existing test stays green untouched; do not "fix" fixtures that do not need it.

- [ ] **Step 2: RED, then implement.** Each service calls `veto = await precharge_veto(db, order)` immediately after its existing payability validation; on a reason: `await record_precharge_veto(...)` then raise/return that protocol's existing unpayable refusal — Payme `order_not_payable()` (-31051); Click and Uzum reuse exactly the error their stage already emits for a non-`pending_payment` order (read `prepare` and `_check_order_state` respectively; for Uzum that is the generic `10009` per the docstring). Never invent a new code. One comment at each call site: why the refusal is deliberately indistinguishable from "not payable" (an error that says "geo blocked" teaches the carder what to fix).
- [ ] **Step 3: Verify** — the three acquirer suites in full, mypy, ruff.
- [ ] **Step 4: Commit** — `feat(api/payments): refuse vetoed orders at the acquirers' pre-charge stage`

---

### Task 4: enforcement point B — order creation, with words

**Files:**

- Modify: `apps/api/src/yupay/core/errors.py` (new `PaymentUnavailableAbroadError`, status 422, `type_uri = "https://app.yupay.uz/errors/payment-unavailable-abroad"`), `apps/api/src/yupay/modules/orders/routes.py`, `apps/api/src/yupay/modules/orders/risk.py` (small feeder)
- Modify: `apps/web/src/components/store/PurchasePanel.tsx`, `apps/miniapp/src/pages/TopUp.tsx` (error mapping only), `packages/i18n/locales/{ru,en,uz}/{web,miniapp}.json`
- Test: `apps/api/tests/integration/test_orders_routes.py` (or the file where create-order tests live), web + miniapp unit tests for the mapping

**Interfaces:**

- Produces: API error slug `payment-unavailable-abroad`; i18n keys `web.store.errAbroad`, `topup.errAbroad`.
- Consumes: `_veto_decision`, `_is_trusted_buyer` (Task 2) — point B feeds them from the LIVE request, not the DB: `country = ip_country_from(request.headers.get("cf-ipcountry"))`, `timezone = body.client_hints.timezone if body.client_hints else None`.

- [ ] **Step 1: Failing API test** — guest create-order with header `cf-ipcountry: NL` → 422, problem+json `type` ends `/payment-unavailable-abroad`, and NO order row created (the transaction rolled back). Same request from a user with one delivered order → 201. Same guest request with `RISK_PRECHARGE_VETO=false` settings → 201.
- [ ] **Step 2: Implement.** In the create route, after `_resolve_actor` and BEFORE `svc.create_order`: resolve trusted (actor's user id or None), call the pure `_veto_decision`; on a reason raise `PaymentUnavailableAbroadError("payment from abroad requires a signed-in account with order history")`. Wrap the whole veto evaluation in the same fail-open try/except — a broken check must not stop checkout. Russian message lives client-side; the API carries only the slug.
- [ ] **Step 3: i18n** — ru: «Оплата из-за границы доступна после входа в аккаунт с историей заказов. Напишите в поддержку, если это ошибка.», en: "Paying from abroad requires a signed-in account with order history. Contact support if this looks wrong.", uz: "Chet eldan to'lash uchun buyurtmalar tarixi bo'lgan akkauntga kirish kerak. Xato bo'lsa, qo'llab-quvvatlashga yozing." — both catalogs (web + miniapp), all three locales, key sets equal.
- [ ] **Step 4: Frontends.** Where each checkout maps create-order failures, add: `ApiError.type` ends with `payment-unavailable-abroad` → render the new key near the pay button (web: the same error slot PurchasePanel already uses; miniapp: TopUp's existing error text path). One unit test each, following the surface's existing error-mapping tests.
- [ ] **Step 5: Verify** — API integration file, `pnpm --filter @yupay/web test`, `pnpm --filter @yupay/miniapp test`, typecheck both, prettier.
- [ ] **Step 6: Commit** — `feat(orders,web,miniapp): refuse foreign guest checkout with words, not a dead acquirer screen`

---

### Task 5: the auto-refund sweep + docs

**Files:**

- Create: `apps/scheduler/src/yupay_scheduler/jobs/held_order_refund.py` (register alongside the other jobs — copy `click_timeout.py`'s scaffolding and registration)
- Modify: `docs/runbooks/order-held-for-review.md` (deadline + veto sections, new env rows), `docs/decisions/0062-antifraud-identity-windows.md` is NOT touched — instead Create: `docs/decisions/0063-precharge-veto-and-auto-refund.md` (short MADR: refuse-before-charge, deadline-not-indefinite-hold, indistinguishable refusal; links the spec), `docs/architecture/module-map.md` (one line)
- Test: `apps/api/tests/integration/` — the sweep's core as a service-level function so it is testable from the api test suite (the job file stays a thin scheduler wrapper, the pattern the other jobs use)

**Interfaces:**

- Produces: `orders.risk.auto_refund_expired_holds(db, *, settings=None, limit=50) -> int` (returns how many refunded; the scheduler wrapper loops it).

- [ ] **Step 1: Failing integration tests**

```python
async def test_a_hold_past_the_deadline_is_refunded(...):
    <paid catalog order + held_for_review event dated 25h ago + succeeded mock payment>
    # `_cfg` here is the integration file's own settings helper (same shape as
    # the unit file's: get_settings().model_dump() + overrides) with an
    # `hours=` kwarg mapping to risk_hold_auto_refund_hours.
    n = await auto_refund_expired_holds(db, settings=_cfg(hours=24))
    assert n == 1
    <order refunded via the mock gateway; an order_events row records auto_refund_hold_expired>


async def test_fresh_holds_released_orders_and_wallet_topups_are_left_alone(...):
    <a 1h-old hold; a held order whose fulfilment already started; a wallet topup>
    assert await auto_refund_expired_holds(db, settings=_cfg(hours=24)) == 0


async def test_the_sweep_is_idempotent_across_ticks(...):
    <run twice; second tick refunds nothing, no second refund on the gateway>


async def test_zero_disables(...):
    assert await auto_refund_expired_holds(db, settings=_cfg(hours=0)) == 0
```

- [ ] **Step 2: Implement.** Selection: `status="paid"`, `purpose="catalog"`, an `order.held_for_review` event older than the deadline, and no fulfilment yet (reuse however the codebase distinguishes a released order — read `fulfillment.start_for_order`'s footprint; the FSM moves status off `paid`, so `status="paid"` alone may already imply un-released — the implementer verifies and documents which it is). Refund through `payments.service.refund_admin(db, payment_id=..., admin_id="auto-refund-sweep", reason="auto_refund_hold_expired", idempotency_key=f"auto-refund:{order.id}")` — full amount, and the idempotency key is what makes a crashed-and-rerun tick safe. Per-order try/except: one acquirer's refund API being down logs and moves on. One admin alert per refunded order (existing `send_admin_alert`, wording: what was refunded, which deadline expired, and that this is the configured policy). The scheduler wrapper mirrors `click_timeout.py`'s session/loop shape, every 15 min.
- [ ] **Step 3: Docs.** Runbook: the deadline (operator has `RISK_HOLD_AUTO_REFUND_HOURS` hours to release or the money goes back; `0` disables), the veto (what buyers see at each enforcement point, the Cloudflare toggle step, `RISK_HOME_COUNTRIES`), new env table rows. ADR-0063 short. Module map: one line. Prettier.
- [ ] **Step 4: Verify** — new tests + full risk/acquirer suites + mypy/ruff/prettier; risk.py coverage stays ≥ 95%.
- [ ] **Step 5: Commit** — `feat(scheduler): auto-refund held orders past their deadline` then `docs(orders): ADR-0063, runbook and module map for the pre-charge veto`

---

## Rollout (operator steps, post-deploy)

1. Deploy: veto live on tz-fallback only (country NULL until the toggle) — same signal the hold rule already proved.
2. Flip **IP Geolocation** in Cloudflare; verify one fresh order shows `ip_country`.
3. Watch `order.precharge_vetoed` counts and auto-refund alerts for a week; tune hours/lists by env.

## Self-review notes

- Existing acquirer tests survive untouched because their orders have no evidence rows and the veto never fires blind — checked against the fixtures before writing this plan.
- Point B runs on live headers because a refused creation rolls back the transaction (no evidence row would survive to read); the shared pure core keeps A and B from drifting.
- `refund_admin`'s actor stamp becomes `admin:auto-refund-sweep` — acceptable and grep-able; if the reviewer objects, the alternative is threading a system-actor variant through `refund_admin`, which is more surface than the stamp is worth.
- The sweep intentionally includes `REASON_PAID_AFTER_EXPIRY` holds (spec: same safe default).
