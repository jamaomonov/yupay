# Payment Provider Admin Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins disable a payment provider or put it into "maintenance" (тех. работы), with per-provider analytics, enforced so disabled/maintenance providers accept no new payments while in-flight payments still settle.

**Architecture:** A new `payment_provider_states` table (one row per gateway slug, default = `active`) is the single source of truth. A `payments/provider_state.py` module maps logical providers → slugs, reads/writes state, and resolves the customer-facing status. `create_intent` and `GET /payments/providers` consult it; webhooks do not. Admin endpoints under `/admin/payments/providers` expose the list, per-provider analytics, and a set-state action. Web + miniapp render `maintenance` methods as non-clickable; the Admin SPA gets a providers screen.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2 (backend); React 19 + Vite + generated `@hey-api` client (admin); Next.js 15 (web); Vite + wouter (miniapp).

## Global Constraints

- Python: ruff `line-length=100`, `target-version=py312`; mypy --strict, full annotations, no `Any` without inline justification; Google docstrings on public defs; async on the request path; no business logic in routers.
- Payments module test coverage gate: **≥ 95%**.
- Money in minor-unit-safe `Decimal` (Python); never floats. Do not net refunds here.
- All write endpoints accept `Idempotency-Key` and persist results keyed by it (use `load_replay`/`save_replay`, scope string per action).
- Never log PII (email, phone, tg id, IP, card data). Order ids, amounts, provider slugs are OK.
- i18n: any new user-facing string added to **ru + en + uz** in the same change. Web strings → `packages/i18n/locales/{ru,en,uz}/web.json`; miniapp strings → `apps/miniapp/src/lib/i18n/messages.ts` (existing `MessageKey` catalog).
- TS: `strict`, no `any`, explicit prop interfaces.
- New endpoint / changed response shape → regenerate `docs/api/openapi.json` + `packages/api-client` (Task 7). Frontend tasks depend on that.
- Manageable providers (logical → slugs): `click → [click, click_miniapp]`, `payme → [payme]`, `uzum → [uzum]`, `octo → [octo]`, `crypto → [crypto]`. Never `wallet`, `mock`, `yookassa`, `tinkoff`.
- States are mutually exclusive: `active | disabled | maintenance`. Absence of a row = `active`.
- Enforcement blocks **new intents only**; webhook/callback routes are untouched (in-flight payments settle).

---

### Task 1: `payment_provider_states` model + migration

**Files:**
- Modify: `apps/api/src/yupay/modules/payments/models.py` (append `PaymentProviderState`)
- Create: `apps/api/migrations/versions/0037_payment_provider_states.py`
- Test: `apps/api/tests/integration/test_payment_provider_state_model.py`

**Interfaces:**
- Produces: `PaymentProviderState` ORM model with columns `provider: str` (PK), `state: str`, `changed_by: str | None`, `changed_at: datetime | None`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_payment_provider_state_model.py
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.modules.payments.models import PaymentProviderState

pytestmark = pytest.mark.asyncio


async def test_provider_state_row_roundtrips(db_session: AsyncSession) -> None:
    db_session.add(
        PaymentProviderState(provider="payme", state="maintenance", changed_by=None, changed_at=now())
    )
    await db_session.commit()
    row = (
        await db_session.execute(
            select(PaymentProviderState).where(PaymentProviderState.provider == "payme")
        )
    ).scalar_one()
    assert row.state == "maintenance"
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_provider_state_model.py -q`
Expected: FAIL (ImportError: cannot import name `PaymentProviderState`, or missing table).

- [ ] **Step 3: Add the model**

Append to `apps/api/src/yupay/modules/payments/models.py` (match the file's existing imports — `Mapped`, `mapped_column`, `String`, `DateTime`, `UUID`, `datetime`):

```python
class PaymentProviderState(Base):
    """Admin-controlled runtime state for a payment gateway slug.

    Orthogonal to a gateway's config-availability (are the keys set): this row
    lets an operator take a provider offline (`disabled`) or flag it as under
    maintenance (`maintenance`) without a code/config change. Absence of a row
    means `active`. One row per slug — the admin layer writes every slug in a
    logical provider's group together (see ``provider_state.LOGICAL_PROVIDERS``).
    """

    __tablename__ = "payment_provider_states"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True
    )
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Create the migration**

```python
# apps/api/migrations/versions/0037_payment_provider_states.py
"""Admin-controlled payment provider states.

Backs the disable / maintenance controls. One row per gateway slug; absence of a
row means `active`, so nothing is seeded — a provider only gets a row once an
operator changes its state.

Revision ID: 0037_payment_provider_states
Revises: 0036_grandfather_email_verified
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0037_payment_provider_states"
down_revision: str | None = "0036_grandfather_email_verified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_provider_states",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("changed_by", UUID(as_uuid=False), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('active', 'disabled', 'maintenance')",
            name="ck_payment_provider_states_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("payment_provider_states")
```

- [ ] **Step 5: Run test, verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_payment_provider_state_model.py -q`
Expected: PASS (testcontainers applies migrations before the suite).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/payments/models.py apps/api/migrations/versions/0037_payment_provider_states.py apps/api/tests/integration/test_payment_provider_state_model.py
git commit -m "feat(api/payments): payment_provider_states table + model"
```

---

### Task 2: `provider_state` service module

**Files:**
- Create: `apps/api/src/yupay/modules/payments/provider_state.py`
- Test: `apps/api/tests/integration/test_provider_state_service.py`

**Interfaces:**
- Consumes: `PaymentProviderState` (Task 1); `REGISTRY` from `payments.gateways`.
- Produces:
  - `ProviderState = Literal["active", "disabled", "maintenance"]`
  - `LOGICAL_PROVIDERS: dict[str, LogicalProvider]` where `LogicalProvider` has `.display_name: str` and `.slugs: list[str]`
  - `SLUG_TO_LOGICAL: dict[str, str]`
  - `async def get_states(db, slugs: list[str]) -> dict[str, ProviderState]` (defaults missing slugs to `"active"`)
  - `async def set_logical_state(db, *, provider: str, state: ProviderState, changed_by: str | None) -> None` (writes every slug in the group; raises `NotFoundError` for unknown logical provider)
  - `def customer_status(slug: str, state: ProviderState) -> Literal["active", "maintenance"] | None` (None = hide; also returns None if the gateway is not config-available)

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_provider_state_service.py
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import NotFoundError
from yupay.modules.payments import provider_state as ps

pytestmark = pytest.mark.asyncio


async def test_default_state_is_active(db_session: AsyncSession) -> None:
    states = await ps.get_states(db_session, ["payme", "uzum"])
    assert states == {"payme": "active", "uzum": "active"}


async def test_set_logical_state_writes_all_slugs(db_session: AsyncSession) -> None:
    await ps.set_logical_state(db_session, provider="click", state="disabled", changed_by=None)
    await db_session.commit()
    states = await ps.get_states(db_session, ["click", "click_miniapp"])
    assert states == {"click": "disabled", "click_miniapp": "disabled"}


async def test_set_logical_state_unknown_provider_raises(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await ps.set_logical_state(db_session, provider="paypal", state="disabled", changed_by=None)


def test_customer_status_hides_disabled_and_flags_maintenance() -> None:
    # mock/wallet aside, use a config-available acquirer under test env if needed;
    # here we test the state mapping directly with a config-available slug.
    assert ps.customer_status("payme", "disabled") is None
    assert ps.customer_status("payme", "maintenance") == "maintenance"
    assert ps.customer_status("payme", "active") == "active"
```

> Note: `customer_status` also returns `None` when the gateway is not config-available. In the test env acquirer keys may be unset, which would make even `active` return `None`. If that happens, set the relevant env in a fixture (e.g. `monkeypatch.setenv("PAYME_MERCHANT_ID", "x")` + `get_settings.cache_clear()`) OR split `customer_status` so the state-mapping part is unit-testable without config. Prefer the latter: see Step 3.

- [ ] **Step 2: Run it, verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_provider_state_service.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the module**

```python
# apps/api/src/yupay/modules/payments/provider_state.py
"""Admin-controlled provider state: the logical↔slug map, state read/write, and
the customer-facing status resolver.

Single source of truth consumed by ``create_intent`` (block new intents),
``GET /payments/providers`` (hide disabled, flag maintenance), and the admin
endpoints. Webhook paths deliberately do NOT consult this — in-flight payments
must settle regardless of admin state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.models import PaymentProviderState

ProviderState = Literal["active", "disabled", "maintenance"]
CustomerStatus = Literal["active", "maintenance"]

_VALID_STATES: frozenset[str] = frozenset({"active", "disabled", "maintenance"})


@dataclass(frozen=True)
class LogicalProvider:
    """A provider as an operator thinks of it — may map to >1 registry slug."""

    display_name: str
    slugs: list[str]


# Real acquirers only. Click spans two surface slugs but is one control.
LOGICAL_PROVIDERS: dict[str, LogicalProvider] = {
    "click": LogicalProvider("Click", ["click", "click_miniapp"]),
    "payme": LogicalProvider("Payme", ["payme"]),
    "uzum": LogicalProvider("Uzum", ["uzum"]),
    "octo": LogicalProvider("Octo", ["octo"]),
    "crypto": LogicalProvider("USDT (crypto)", ["crypto"]),
}

SLUG_TO_LOGICAL: dict[str, str] = {
    slug: logical for logical, lp in LOGICAL_PROVIDERS.items() for slug in lp.slugs
}


async def get_states(db: AsyncSession, slugs: list[str]) -> dict[str, ProviderState]:
    """Return the state of each slug, defaulting missing rows to ``active``."""
    rows = (
        await db.execute(
            select(PaymentProviderState).where(PaymentProviderState.provider.in_(slugs))
        )
    ).scalars()
    stored = {r.provider: _coerce(r.state) for r in rows}
    return {slug: stored.get(slug, "active") for slug in slugs}


async def get_state(db: AsyncSession, slug: str) -> ProviderState:
    """State of a single slug (``active`` if no row)."""
    return (await get_states(db, [slug]))[slug]


async def set_logical_state(
    db: AsyncSession, *, provider: str, state: ProviderState, changed_by: str | None
) -> None:
    """Set every slug of a logical provider to ``state`` (upsert).

    Raises:
        NotFoundError: ``provider`` is not a known logical provider.
    """
    lp = LOGICAL_PROVIDERS.get(provider)
    if lp is None:
        raise NotFoundError("unknown payment provider", extra={"provider": provider})
    stamp = now()
    existing = {
        r.provider: r
        for r in (
            await db.execute(
                select(PaymentProviderState).where(PaymentProviderState.provider.in_(lp.slugs))
            )
        ).scalars()
    }
    for slug in lp.slugs:
        row = existing.get(slug)
        if row is None:
            db.add(
                PaymentProviderState(
                    provider=slug, state=state, changed_by=changed_by, changed_at=stamp
                )
            )
        else:
            row.state = state
            row.changed_by = changed_by
            row.changed_at = stamp
    await db.flush()


def state_status(state: ProviderState) -> CustomerStatus | None:
    """Pure state→customer-status mapping (ignores config-availability).

    ``disabled`` → None (hide). Unit-testable without env/config.
    """
    if state == "disabled":
        return None
    return "maintenance" if state == "maintenance" else "active"


def customer_status(slug: str, state: ProviderState) -> CustomerStatus | None:
    """Customer-facing status: None means "don't show".

    None when the gateway is not config-available (no keys) OR when ``state`` is
    ``disabled``; otherwise the state's status.
    """
    gw = REGISTRY.get(slug)
    if gw is None or not gw.available:
        return None
    return state_status(state)


def _coerce(raw: str) -> ProviderState:
    return raw if raw in _VALID_STATES else "active"  # type: ignore[return-value]
```

> Adjust the test from Step 1 to call `ps.state_status(...)` for the pure mapping assertions (config-independent), and keep `customer_status` covered by the integration tests in Task 4 where env is set.

- [ ] **Step 4: Update the test to use `state_status` for pure assertions, run, verify pass**

Replace the `test_customer_status_...` body with:

```python
def test_state_status_hides_disabled_and_flags_maintenance() -> None:
    assert ps.state_status("disabled") is None
    assert ps.state_status("maintenance") == "maintenance"
    assert ps.state_status("active") == "active"
```

Run: `cd apps/api && uv run pytest tests/integration/test_provider_state_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/payments/provider_state.py apps/api/tests/integration/test_provider_state_service.py
git commit -m "feat(api/payments): provider_state module (logical map + state read/write)"
```

---

### Task 3: Enforce state in `create_intent` (+ in-flight money-safety test)

**Files:**
- Modify: `apps/api/src/yupay/modules/payments/service.py` (in `create_intent`, after the `gw.available` check ~line 163)
- Test: `apps/api/tests/integration/test_provider_state_enforcement.py`

**Interfaces:**
- Consumes: `provider_state.get_state` (Task 2); existing `ConflictError`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_provider_state_enforcement.py
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.modules.payments import provider_state as ps
from yupay.modules.payments import service as pay_svc

pytestmark = pytest.mark.asyncio


async def _seed_pending_order(db: AsyncSession) -> str:
    """Create a pending_payment order payable via the mock gateway; return its id.

    Reuse the existing order/checkout seeding helper used by other payments
    integration tests (see tests/integration/test_payments_*.py). Return an order
    whose status is 'pending_payment'.
    """
    ...  # follow the existing helper in the payments integration tests


@pytest.mark.parametrize("bad_state", ["disabled", "maintenance"])
async def test_create_intent_rejected_when_not_active(
    db_session: AsyncSession, bad_state: str
) -> None:
    order_id = await _seed_pending_order(db_session)
    await ps.set_logical_state(db_session, provider="click", state=bad_state, changed_by=None)
    await db_session.commit()
    with pytest.raises(ConflictError) as ei:
        await pay_svc.create_intent(
            db_session, order_id=order_id, provider="click", return_url=None, idempotency_key="k1"
        )
    assert ei.value.extra.get("reason") in {"provider_disabled", "provider_maintenance"}
```

> Also add a money-safety test asserting an in-flight webhook still settles a payment whose provider was disabled *after* the intent was created. Model it on the existing webhook/settlement integration test for the mock or click gateway (find it under `tests/integration/`), disabling the provider via `ps.set_logical_state(...)` between intent creation and the webhook call, and assert the payment reaches `succeeded` and the order settles.

- [ ] **Step 2: Run, verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_provider_state_enforcement.py -q`
Expected: FAIL (intent created instead of rejected).

- [ ] **Step 3: Add the enforcement**

In `apps/api/src/yupay/modules/payments/service.py`, right after the existing block:

```python
    gw = get_gateway(provider)
    if not gw.available:
        raise ConflictError(
            "payment provider not available",
            extra={"provider": gw.provider},
        )
```

insert:

```python
    state = await provider_state.get_state(db, gw.provider)
    if state != "active":
        raise ConflictError(
            "payment provider is not accepting new payments",
            extra={
                "provider": gw.provider,
                "reason": "provider_disabled" if state == "disabled" else "provider_maintenance",
            },
        )
```

Add the import at the top of `service.py`: `from yupay.modules.payments import provider_state`.

- [ ] **Step 4: Run tests, verify pass**

Run: `cd apps/api && uv run pytest tests/integration/test_provider_state_enforcement.py -q`
Expected: PASS (both rejection and money-safety tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/payments/service.py apps/api/tests/integration/test_provider_state_enforcement.py
git commit -m "feat(api/payments): block new intents for disabled/maintenance providers"
```

---

### Task 4: `GET /payments/providers` returns `[{slug, status}]`

**Files:**
- Modify: `apps/api/src/yupay/modules/payments/routes.py` (the `/providers` route ~line 95)
- Modify: `apps/api/src/yupay/modules/payments/schemas.py` (add `ProviderStatusOut`, `ProvidersOut`)
- Test: `apps/api/tests/integration/test_providers_endpoint.py`

**Interfaces:**
- Consumes: `provider_state.customer_status`, `LOGICAL_PROVIDERS`/`SLUG_TO_LOGICAL`, `REGISTRY`, `get_states`.
- Produces: response `{"providers": [{"slug": str, "status": "active" | "maintenance"}]}`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_providers_endpoint.py
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.payments import provider_state as ps

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _acquirer_env(monkeypatch: pytest.MonkeyPatch):
    # Make Payme + Uzum config-available so they appear in the list.
    monkeypatch.setenv("PAYME_MERCHANT_ID", "m")
    monkeypatch.setenv("PAYME_KEY", "k")
    monkeypatch.setenv("UZUM_SERVICE_ID", "1")
    monkeypatch.setenv("UZUM_LOGIN", "l")
    monkeypatch.setenv("UZUM_PASSWORD", "p")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def test_providers_hides_disabled_and_flags_maintenance(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await ps.set_logical_state(db_session, provider="payme", state="disabled", changed_by=None)
    await ps.set_logical_state(db_session, provider="uzum", state="maintenance", changed_by=None)
    await db_session.commit()

    r = await integration_client.get("/api/v1/payments/providers")
    assert r.status_code == 200
    by_slug = {p["slug"]: p["status"] for p in r.json()["providers"]}
    assert "payme" not in by_slug  # disabled → hidden
    assert by_slug.get("uzum") == "maintenance"
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_providers_endpoint.py -q`
Expected: FAIL (old shape returns `list[str]`; `p["slug"]` KeyError, or uzum not flagged).

- [ ] **Step 3: Add schemas**

In `apps/api/src/yupay/modules/payments/schemas.py`:

```python
class ProviderStatusOut(BaseModel):
    """A payment provider slug the storefront may show, and whether it's usable."""

    slug: str
    status: Literal["active", "maintenance"]


class ProvidersOut(BaseModel):
    providers: list[ProviderStatusOut]
```

(Import `Literal` from `typing` if not already imported.)

- [ ] **Step 4: Rewrite the route**

In `apps/api/src/yupay/modules/payments/routes.py`, replace the `/providers` handler:

```python
@router.get("/providers", response_model=ProvidersOut, summary="Payment providers the storefront may show")
async def list_providers(db: Annotated[AsyncSession, Depends(db_session)]) -> ProvidersOut:
    slugs = list(SLUG_TO_LOGICAL.keys())
    states = await provider_state.get_states(db, slugs)
    out: list[ProviderStatusOut] = []
    for slug in slugs:
        status_ = provider_state.customer_status(slug, states[slug])
        if status_ is not None:
            out.append(ProviderStatusOut(slug=slug, status=status_))
    return ProvidersOut(providers=out)
```

Add imports: `from yupay.modules.payments import provider_state`, `from yupay.modules.payments.provider_state import SLUG_TO_LOGICAL`, `from yupay.modules.payments.schemas import ProviderStatusOut, ProvidersOut`, and `db_session`/`Depends`/`Annotated`/`AsyncSession` if not present. Remove the now-unused `available_providers` import if nothing else uses it.

> This intentionally lists only managed real-acquirer slugs (Task's Global Constraints), not `mock`/`wallet`. If any existing test/consumer relied on `mock` appearing here, adjust: the web fallback to `mock` (PurchasePanel) is dev-only — see Task 8.

- [ ] **Step 5: Run test, verify pass**

Run: `cd apps/api && uv run pytest tests/integration/test_providers_endpoint.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole payments suite (nothing else broke)**

Run: `cd apps/api && uv run pytest tests/ -k "payment or provider or intent or click or payme or uzum or octo" -q`
Expected: PASS. Fix any consumer that assumed the old `list[str]` shape.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/payments/routes.py apps/api/src/yupay/modules/payments/schemas.py apps/api/tests/integration/test_providers_endpoint.py
git commit -m "feat(api/payments): /providers returns {slug,status}, hides disabled, flags maintenance"
```

---

### Task 5: Admin list + set-state endpoints

**Files:**
- Modify: `apps/api/src/yupay/modules/payments/routes.py` (`admin_router`, prefix `/admin/payments`)
- Modify: `apps/api/src/yupay/modules/payments/schemas.py` (admin DTOs)
- Modify: `apps/api/src/yupay/modules/payments/service.py` (list/set service fns) — or a new `payments/provider_admin.py` if `service.py` is near its length limit; check LOC first.
- Test: `apps/api/tests/integration/test_admin_providers.py`

**Interfaces:**
- Consumes: `provider_state` (Task 2), `require_admin`, `load_replay`/`save_replay`, `IDEMPOTENCY_HEADER`, `normalize_idempotency_key`.
- Produces:
  - `GET /admin/payments/providers` → `AdminProviderListOut { providers: list[AdminProviderSummary] }`
  - `PUT /admin/payments/providers/{provider}/state` body `SetProviderStateIn { state }` → `AdminProviderSummary`
  - `AdminProviderSummary { provider, display_name, slugs, config_available: bool, state, changed_by, changed_at }`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_admin_providers.py
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _admin_token(client: AsyncClient, db: AsyncSession) -> str:
    """Log in a Telegram user and grant admin. Reuse the helpers from
    tests/integration/test_g2b_fulfillment.py (_login_user + _grant_admin)."""
    ...


async def test_admin_can_list_and_set_provider_state(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session)
    h = {"Authorization": f"Bearer {token}"}

    lst = await integration_client.get("/api/v1/admin/payments/providers", headers=h)
    assert lst.status_code == 200
    names = {p["provider"] for p in lst.json()["providers"]}
    assert {"click", "payme", "uzum", "octo", "crypto"} <= names
    click = next(p for p in lst.json()["providers"] if p["provider"] == "click")
    assert click["slugs"] == ["click", "click_miniapp"]
    assert click["state"] == "active"

    put = await integration_client.put(
        "/api/v1/admin/payments/providers/click/state",
        headers={**h, "Idempotency-Key": "set-1"},
        json={"state": "maintenance"},
    )
    assert put.status_code == 200
    assert put.json()["state"] == "maintenance"

    lst2 = await integration_client.get("/api/v1/admin/payments/providers", headers=h)
    click2 = next(p for p in lst2.json()["providers"] if p["provider"] == "click")
    assert click2["state"] == "maintenance"
    assert click2["changed_at"] is not None


async def test_set_state_unknown_provider_404(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session)
    r = await integration_client.put(
        "/api/v1/admin/payments/providers/paypal/state",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "x"},
        json={"state": "disabled"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_admin_providers.py -q`
Expected: FAIL (routes missing → 404 on the list route).

- [ ] **Step 3: Add DTOs**

In `apps/api/src/yupay/modules/payments/schemas.py`:

```python
class AdminProviderSummary(BaseModel):
    provider: str
    display_name: str
    slugs: list[str]
    config_available: bool
    state: Literal["active", "disabled", "maintenance"]
    changed_by: str | None
    changed_at: datetime | None


class AdminProviderListOut(BaseModel):
    providers: list[AdminProviderSummary]


class SetProviderStateIn(BaseModel):
    state: Literal["active", "disabled", "maintenance"]
```

(Import `datetime` if not present.)

- [ ] **Step 4: Add service functions**

Add to `service.py` (or `provider_admin.py`):

```python
async def list_admin_providers(db: AsyncSession) -> list[AdminProviderSummary]:
    """One summary per logical provider (config-availability = any slug has keys)."""
    summaries: list[AdminProviderSummary] = []
    for logical, lp in provider_state.LOGICAL_PROVIDERS.items():
        states = await provider_state.get_states(db, lp.slugs)
        rows = await provider_state.get_state_rows(db, lp.slugs)  # see note
        config_available = any(
            (gw := REGISTRY.get(s)) is not None and gw.available for s in lp.slugs
        )
        # The group's state is uniform (we always write all slugs together); take
        # the first slug's state as canonical, plus its changed_by/at.
        canonical = rows.get(lp.slugs[0])
        summaries.append(
            AdminProviderSummary(
                provider=logical,
                display_name=lp.display_name,
                slugs=lp.slugs,
                config_available=config_available,
                state=states[lp.slugs[0]],
                changed_by=canonical.changed_by if canonical else None,
                changed_at=canonical.changed_at if canonical else None,
            )
        )
    return summaries


async def set_provider_state(
    db: AsyncSession, *, provider: str, state: str, changed_by: str | None
) -> AdminProviderSummary:
    await provider_state.set_logical_state(
        db, provider=provider, state=state, changed_by=changed_by  # type: ignore[arg-type]
    )
    await db.flush()
    summaries = await list_admin_providers(db)
    return next(s for s in summaries if s.provider == provider)
```

Add a small helper `get_state_rows` to `provider_state.py`:

```python
async def get_state_rows(db: AsyncSession, slugs: list[str]) -> dict[str, PaymentProviderState]:
    """Raw rows (for changed_by/at); missing slugs simply absent."""
    return {
        r.provider: r
        for r in (
            await db.execute(
                select(PaymentProviderState).where(PaymentProviderState.provider.in_(slugs))
            )
        ).scalars()
    }
```

- [ ] **Step 5: Add routes**

In `routes.py` under `admin_router`:

```python
@admin_router.get("/providers", response_model=AdminProviderListOut)
async def admin_list_providers(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminProviderListOut:
    return AdminProviderListOut(providers=await svc.list_admin_providers(db))


@admin_router.put("/providers/{provider}/state", response_model=AdminProviderSummary)
async def admin_set_provider_state(
    provider: str,
    body: SetProviderStateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminProviderSummary:
    key = normalize_idempotency_key(idempotency_key)
    scope = "payments.set_provider_state"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return AdminProviderSummary.model_validate(cached.body)
    out = await svc.set_provider_state(db, provider=provider, state=body.state, changed_by=admin.id)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out
```

Match the exact import names used by the fulfillment admin routes for `require_admin`, `IDEMPOTENCY_HEADER`, `normalize_idempotency_key`, `load_replay`, `save_replay`, `User`, `Header`.

- [ ] **Step 6: Run tests, verify pass**

Run: `cd apps/api && uv run pytest tests/integration/test_admin_providers.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/payments/routes.py apps/api/src/yupay/modules/payments/schemas.py apps/api/src/yupay/modules/payments/service.py apps/api/src/yupay/modules/payments/provider_state.py apps/api/tests/integration/test_admin_providers.py
git commit -m "feat(api/payments): admin list + set-state provider endpoints"
```

---

### Task 6: Admin per-provider analytics detail endpoint

**Files:**
- Modify: `apps/api/src/yupay/modules/payments/routes.py` (`admin_router`)
- Modify: `apps/api/src/yupay/modules/payments/schemas.py` (analytics DTOs)
- Create: `apps/api/src/yupay/modules/payments/provider_analytics.py`
- Test: `apps/api/tests/integration/test_admin_provider_detail.py`

**Interfaces:**
- Produces: `GET /admin/payments/providers/{provider}?window=today|7d|30d` → `AdminProviderDetailOut` with `summary` (Task 5's `AdminProviderSummary`), `volume: list[{currency, amount, count}]`, `success_rate: {succeeded, failed, pending, success_pct}`, `recent: list[{id, order_id, status, amount, currency, created_at}]`, `incidents: {stuck_pending, failed_webhooks}`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_admin_provider_detail.py
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_provider_detail_returns_analytics_blocks(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # reuse _admin_token + a helper that seeds a few Payment rows for provider
    # 'payme' with mixed statuses/currencies (see other payments integration tests).
    token = await _admin_token(integration_client, db_session)  # noqa: F821 - defined as in Task 5
    r = await integration_client.get(
        "/api/v1/admin/payments/providers/payme?window=30d",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["provider"] == "payme"
    assert "volume" in body and "success_rate" in body
    assert "recent" in body and "incidents" in body


async def test_provider_detail_zero_payments_ok(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _admin_token(integration_client, db_session)  # noqa: F821
    r = await integration_client.get(
        "/api/v1/admin/payments/providers/octo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["success_rate"]["succeeded"] == 0
    assert r.json()["volume"] == []
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_admin_provider_detail.py -q`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement analytics helper**

```python
# apps/api/src/yupay/modules/payments/provider_analytics.py
"""Read-only per-provider analytics for the admin detail screen.

Aggregates the ``payments`` table (and ``payment_webhooks`` for incidents) over
a window, scoped to a logical provider's slug set. No PII in the recent list.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.modules.payments.models import Payment, PaymentWebhook

Window = Literal["today", "7d", "30d"]
_WINDOWS: dict[str, timedelta] = {"today": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}
_SUCCEEDED = {"succeeded", "paid"}   # confirm exact status vocab from Payment usage
_FAILED = {"failed", "cancelled", "expired"}
_PENDING = {"pending", "created", "processing"}


def window_start(window: str) -> "datetime":
    return now() - _WINDOWS.get(window, _WINDOWS["7d"])


async def volume_by_currency(db: AsyncSession, *, slugs: list[str], since) -> list[dict[str, object]]:
    rows = (
        await db.execute(
            select(Payment.currency, func.sum(Payment.amount), func.count())
            .where(Payment.provider.in_(slugs), Payment.created_at >= since,
                   Payment.status.in_(_SUCCEEDED))
            .group_by(Payment.currency)
        )
    ).all()
    return [{"currency": c, "amount": str(a or Decimal(0)), "count": int(n)} for c, a, n in rows]


async def success_rate(db: AsyncSession, *, slugs: list[str], since) -> dict[str, object]:
    rows = (
        await db.execute(
            select(Payment.status, func.count())
            .where(Payment.provider.in_(slugs), Payment.created_at >= since)
            .group_by(Payment.status)
        )
    ).all()
    succ = sum(int(n) for s, n in rows if s in _SUCCEEDED)
    fail = sum(int(n) for s, n in rows if s in _FAILED)
    pend = sum(int(n) for s, n in rows if s in _PENDING)
    total = succ + fail + pend
    pct = round(100 * succ / total, 1) if total else 0.0
    return {"succeeded": succ, "failed": fail, "pending": pend, "success_pct": pct}


async def recent(db: AsyncSession, *, slugs: list[str], limit: int = 20) -> list[dict[str, object]]:
    rows = (
        await db.execute(
            select(Payment).where(Payment.provider.in_(slugs))
            .order_by(Payment.created_at.desc()).limit(limit)
        )
    ).scalars()
    return [
        {"id": p.id, "order_id": p.order_id, "status": p.status,
         "amount": str(p.amount), "currency": p.currency,
         "created_at": p.created_at.isoformat()}
        for p in rows
    ]


async def incidents(db: AsyncSession, *, slugs: list[str], stuck_after_minutes: int = 30) -> dict[str, int]:
    cutoff = now() - timedelta(minutes=stuck_after_minutes)
    stuck = (
        await db.execute(
            select(func.count()).select_from(Payment)
            .where(Payment.provider.in_(slugs), Payment.status.in_(_PENDING),
                   Payment.created_at < cutoff)
        )
    ).scalar_one()
    # Failed webhooks: adapt to PaymentWebhook's actual "failed"/processed columns —
    # inspect models.py PaymentWebhook before finalizing this filter.
    failed_wh = (
        await db.execute(
            select(func.count()).select_from(PaymentWebhook)
            .where(PaymentWebhook.provider.in_(slugs))  # + a not-processed / error flag
        )
    ).scalar_one()
    return {"stuck_pending": int(stuck), "failed_webhooks": int(failed_wh)}
```

> Before finalizing: open `payments/models.py` and confirm the exact `Payment.status` vocabulary and `PaymentWebhook`'s columns (provider, processed/failed flag). Align `_SUCCEEDED/_FAILED/_PENDING` and the failed-webhook filter to reality — reuse whatever `admin.triage_payments` already uses so the definitions match the triage screen.

- [ ] **Step 4: Add DTOs + route**

Add DTOs to `schemas.py` (`VolumeRow`, `SuccessRate`, `RecentPayment`, `Incidents`, `AdminProviderDetailOut`) matching the helper's shapes, then the route:

```python
@admin_router.get("/providers/{provider}", response_model=AdminProviderDetailOut)
async def admin_provider_detail(
    provider: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    window: Annotated[Literal["today", "7d", "30d"], Query()] = "7d",
) -> AdminProviderDetailOut:
    lp = provider_state.LOGICAL_PROVIDERS.get(provider)
    if lp is None:
        raise NotFoundError("unknown payment provider", extra={"provider": provider})
    since = provider_analytics.window_start(window)
    summaries = await svc.list_admin_providers(db)
    summary = next(s for s in summaries if s.provider == provider)
    return AdminProviderDetailOut(
        summary=summary,
        volume=await provider_analytics.volume_by_currency(db, slugs=lp.slugs, since=since),
        success_rate=await provider_analytics.success_rate(db, slugs=lp.slugs, since=since),
        recent=await provider_analytics.recent(db, slugs=lp.slugs),
        incidents=await provider_analytics.incidents(db, slugs=lp.slugs),
    )
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd apps/api && uv run pytest tests/integration/test_admin_provider_detail.py -q`
Expected: PASS.

- [ ] **Step 6: Full payments suite + lint + types**

Run: `cd apps/api && uv run pytest tests/ -k "payment or provider" -q && cd /Users/macbook_uz/Projects/yupay && uv run ruff check apps && uv run mypy apps`
Expected: PASS / clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/payments/provider_analytics.py apps/api/src/yupay/modules/payments/routes.py apps/api/src/yupay/modules/payments/schemas.py apps/api/tests/integration/test_admin_provider_detail.py
git commit -m "feat(api/payments): admin per-provider analytics detail endpoint"
```

---

### Task 7: Regenerate OpenAPI + TS API client

**Files:**
- Modify: `docs/api/openapi.json` (generated)
- Modify: `packages/api-client/**` (generated)

- [ ] **Step 1: Regenerate**

Run: `make gen-api`
Expected: `docs/api/openapi.json` updates with the new admin endpoints + changed `/payments/providers` schema; `packages/api-client` regenerates.

- [ ] **Step 2: Typecheck the client consumers**

Run: `pnpm --filter @yupay/admin exec tsc --noEmit && pnpm --filter @yupay/web exec tsc --noEmit && pnpm --filter @yupay/miniapp exec tsc --noEmit`
Expected: may surface the `/payments/providers` shape change in web/miniapp — that's fixed in Tasks 8–9. Admin should be clean.

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.json packages/api-client
git commit -m "chore(api-client): regenerate for provider admin endpoints + providers shape"
```

---

### Task 8: Web — hide disabled, render maintenance non-clickable

**Files:**
- Modify: `apps/web/src/components/store/PurchasePanel.tsx:440-446` (provider fetch/parse)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (maintenance string)
- Test: `apps/web/src/components/store/PurchasePanel.test.tsx` (or nearest existing test) — a focused unit test of the provider-parsing/rendering helper.

**Interfaces:**
- Consumes: `GET /api/v1/payments/providers` new shape `{providers: {slug, status}[]}`.

- [ ] **Step 1: Update the fetch/parse**

Replace the typed fetch:

```tsx
const providers = await fetch(`${API}/api/v1/payments/providers`)
  .then((r) => r.json() as Promise<{ providers: { slug: string; status: "active" | "maintenance" }[] }>)
  .catch(() => ({ providers: [] as { slug: string; status: "active" | "maintenance" }[] }));

const bySlug = new Map(providers.providers.map((p) => [p.slug, p.status]));
const wantedStatus = bySlug.get(wanted);
// Only 'active' is selectable; 'maintenance' is shown-but-disabled; absent = hidden.
```

Update the downstream selection logic that currently does `providers.providers.includes(wanted)` to use `bySlug`. Where a method is `maintenance`, render its option **disabled** with the localized maintenance label; where absent, don't render it. Keep the dev-only `mock` fallback behavior if the web checkout relies on it (guard on `import.meta`/env as the existing code does).

- [ ] **Step 2: Add i18n string (all three locales)**

In `packages/i18n/locales/{ru,en,uz}/web.json`, add under the payments namespace:
- ru: `"payment.maintenance": "Технические работы"`
- en: `"payment.maintenance": "Under maintenance"`
- uz: `"payment.maintenance": "Texnik ishlar"`

(Match the existing key nesting/namespace convention in those files.)

- [ ] **Step 3: Write/adjust a focused test**

Add a unit test asserting: given a providers payload with one `active`, one `maintenance`, one absent — the active is selectable, the maintenance renders disabled with the maintenance label, the absent is not rendered. If `PurchasePanel` is hard to unit-test wholesale, extract the pure mapping into a helper (e.g. `lib/payment-providers.ts`) and test that.

- [ ] **Step 4: Run web tests + typecheck**

Run: `pnpm --filter @yupay/web test && pnpm --filter @yupay/web exec tsc --noEmit`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/store/PurchasePanel.tsx packages/i18n/locales/ru/web.json packages/i18n/locales/en/web.json packages/i18n/locales/uz/web.json apps/web/src/**/payment-providers*.ts*
git commit -m "feat(web/checkout): hide disabled providers, show maintenance as non-clickable"
```

---

### Task 9: Mini App — hide disabled, render maintenance non-clickable

**Files:**
- Modify: `apps/miniapp/src/lib/orders.ts:87-101,145-165` (`ProvidersOut` type + `useAvailableProviders` + the pre-submit provider guard)
- Modify: `apps/miniapp/src/pages/TopUp.tsx` (render maintenance method disabled) and `WalletTopUp` if it lists methods
- Modify: `apps/miniapp/src/lib/i18n/messages.ts` (maintenance `MessageKey` in ru/en/uz)
- Test: nearest existing miniapp test for the payment-method list, or a new focused test.

**Interfaces:**
- Consumes: new `/payments/providers` shape.

- [ ] **Step 1: Update the provider type + hook**

In `apps/miniapp/src/lib/orders.ts`:

```ts
export interface ProviderStatus { slug: string; status: "active" | "maintenance" }
interface ProvidersOut { providers: ProviderStatus[] }

export function useAvailableProviders() {
  return useQuery({
    queryKey: ["payments", "providers"],
    queryFn: async () => {
      const data = await apiGet<ProvidersOut>("/api/v1/payments/providers");
      return data.providers; // ProviderStatus[]
    },
  });
}
```

Update the pre-submit guard (lines ~145-165) that resolves the live providers list: a method is submittable only when its slug is present **and** `status === "active"`. Keep the race guard behavior.

- [ ] **Step 2: Render maintenance in the method list**

In `TopUp.tsx` (and `WalletTopUp` if applicable), for each `PAYMENT_METHOD` compute its status from the hook: absent → don't render; `maintenance` → render the card disabled/non-clickable with the maintenance label; `active` → normal.

- [ ] **Step 3: Add the i18n key (ru/en/uz)**

In `apps/miniapp/src/lib/i18n/messages.ts`, add a `payment.maintenance` (or namespaced) `MessageKey` with ru `Технические работы`, en `Under maintenance`, uz `Texnik ishlar`, matching the file's structure. Ensure `messages.test.ts` (parity test) still passes.

- [ ] **Step 4: Run miniapp tests + typecheck**

Run: `pnpm --filter @yupay/miniapp test && pnpm --filter @yupay/miniapp exec tsc --noEmit`
Expected: PASS / clean (incl. the i18n parity test).

- [ ] **Step 5: Commit**

```bash
git add apps/miniapp/src/lib/orders.ts apps/miniapp/src/pages/TopUp.tsx apps/miniapp/src/lib/i18n/messages.ts
git commit -m "feat(miniapp/checkout): hide disabled providers, show maintenance as non-clickable"
```

---

### Task 10: Admin SPA — payment providers screen

**Files:**
- Create: `apps/admin/src/features/payments/providers/ProvidersPage.tsx` (list)
- Create: `apps/admin/src/features/payments/providers/ProviderDetailDrawer.tsx` (analytics + actions)
- Modify: `apps/admin/src/routes/*` (register the route) + the payments feature index/nav
- Test: `apps/admin/src/features/payments/providers/*.test.tsx` (list renders, action calls the client)

**Interfaces:**
- Consumes: generated `@yupay/api-client` methods for `GET /admin/payments/providers`, `GET /admin/payments/providers/{provider}`, `PUT /admin/payments/providers/{provider}/state`.

- [ ] **Step 1: List page**

Follow the existing pattern in `apps/admin/src/features/payments` (look at a sibling feature page for query hooks, table, and layout). Render a table/cards of providers: display_name, state badge (active/disabled/maintenance), config_available, changed_at. Row click → open the detail drawer. Use TanStack Query via the generated client.

- [ ] **Step 2: Detail drawer with analytics + actions**

Fetch `GET /admin/payments/providers/{provider}?window=` (window switch: today/7d/30d). Render the four blocks: volume (by currency + count), success rate (succeeded/failed/pending + %), tech/config (slugs, config_available, state, changed_by/at), recent payments (table) + incidents counters. Three action buttons wired to `PUT .../state` with a generated `Idempotency-Key` (uuid): **Отключить** (`disabled`), **Тех. работы** (`maintenance`), **Включить** (`active`, shown when not active). Confirm dialog before disabling. Invalidate the list + detail queries on success.

- [ ] **Step 3: Register route + nav entry**

Add the route under the admin router (`apps/admin/src/routes`) and a nav/menu entry in the payments feature, following the existing registration pattern.

- [ ] **Step 4: Test**

Add a component test: the list renders providers from a mocked client; clicking **Отключить** calls the set-state client method with `state: "disabled"` and the provider id. Follow the admin app's existing test setup (mocked api-client).

- [ ] **Step 5: Run admin tests + typecheck + lint**

Run: `pnpm --filter @yupay/admin test && pnpm --filter @yupay/admin exec tsc --noEmit && pnpm --filter @yupay/admin lint`
Expected: PASS / clean.

- [ ] **Step 6: Commit**

```bash
git add apps/admin/src/features/payments/providers apps/admin/src/routes
git commit -m "feat(admin/payments): provider management screen (list + analytics + disable/maintenance)"
```

---

### Task 11: Docs — ADR + runbook + module-map

**Files:**
- Create: `docs/decisions/00NN-admin-payment-provider-controls.md` (next ADR number — check `ls docs/decisions/`)
- Create: `docs/runbooks/payment-provider-controls.md`
- Modify: `docs/architecture/module-map.md` (payments public surface note)

- [ ] **Step 1: ADR**

Use the MADR template (`docs/decisions/0000-template.md`). Capture: the `active/disabled/maintenance` model; the in-flight safety invariant (**webhooks/callbacks never consult provider state — new intents only**); Click one-button-two-slugs grouping; state layered on config-availability; why a DB table (operator control without redeploy). List alternatives considered (config-only flag; hard block incl. webhooks) and why rejected.

- [ ] **Step 2: Runbook**

`docs/runbooks/payment-provider-controls.md`: how to disable / set maintenance / re-enable via the admin screen (and the direct `PUT /admin/payments/providers/{provider}/state` fallback with `Idempotency-Key`); what each state does on the storefront and to new-vs-in-flight payments; how to read the analytics/incidents blocks; the caution that disabling does NOT cancel in-flight payments (they still settle).

- [ ] **Step 3: module-map**

Add a line to `docs/architecture/module-map.md` noting payments now owns admin-controlled provider state (`provider_state.py`) consulted by checkout + the storefront `/providers` endpoint.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions docs/runbooks/payment-provider-controls.md docs/architecture/module-map.md
git commit -m "docs(payments): ADR + runbook for admin provider controls"
```

---

## Self-Review notes (for the executor)

- **Status vocabulary (Tasks 3, 6):** before writing analytics/enforcement, open `payments/models.py` + `payments/service.py` and confirm the real `Payment.status` values and `PaymentWebhook` columns; align the `_SUCCEEDED/_FAILED/_PENDING` sets and the failed-webhook filter with `admin.triage_payments` so definitions match the existing triage screen.
- **Seeding helpers (Tasks 3, 5, 6):** reuse existing integration seeding (`_login_user`/`_grant_admin` from `test_g2b_fulfillment.py`; order/checkout seeders from `test_payments_*`) rather than hand-rolling; the `...` placeholders in test snippets mark exactly those reuse points.
- **`service.py` length:** if adding the admin service fns pushes `service.py` past ~500 LOC, put `list_admin_providers`/`set_provider_state` in `payments/provider_admin.py` and import from there.
- **Coverage gate ≥ 95% (payments):** ensure the new modules (`provider_state`, `provider_analytics`, `provider_admin`) are covered — the tasks' tests target each; add cases for `_coerce` fallback and the zero-payments analytics path.
