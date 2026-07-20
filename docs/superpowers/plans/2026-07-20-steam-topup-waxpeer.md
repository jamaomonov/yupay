# Steam Wallet Top-Up via Waxpeer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell Steam wallet top-ups where the customer types a Steam login and a
dollar amount, sees a UZS price derived from a marked-up FX rate, and gets the
money credited by Waxpeer.

**Architecture:** A new `variable_amount` flavour of SKU whose price is computed
at checkout (`amount × market_rate × multiplier`) instead of being read off the
row. The market rate passes a trust gate before it may set a price. Delivery is
a new `WaxpeerFulfiller` behind the existing `Fulfiller` protocol; login
validation reuses the existing check-player endpoint with a new provider.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2,
httpx, respx, pytest; React (miniapp/admin), Next.js (web).

**Spec:** `docs/superpowers/specs/2026-07-20-steam-topup-waxpeer-design.md`

## Global Constraints

- Money is `Decimal` server-side, never float. Waxpeer's unit is `1000 = $1`, so
  one cent is 10 units.
- Gross conversion rounds **up** to the Waxpeer unit — the customer must never
  receive less than promised.
- The client never sets a price. The server recomputes from `amount_usd`.
- Every supplier call is version-agnostic HTTP with an explicit timeout; the API
  key comes from settings at call time (hot-reloadable), never captured at
  import.
- Adapter coverage ≥95% (project rule for supplier adapters and payments).
- All user-facing strings land in `ru`, `en`, `uz` in the same change.
- `ruff check`, `ruff format --check`, `mypy apps`, `prettier --check .` must all
  pass before every commit.

---

### Task 1: Waxpeer HTTP client

Thin transport over the four endpoints. No business rules here — mapping and
policy live in the fulfiller (Task 6).

**Files:**

- Create: `apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer_client.py`
- Modify: `apps/api/src/yupay/core/config.py` (after the `g2b_*` block, ~line 235)
- Test: `apps/api/tests/contract/test_waxpeer_client.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `WaxpeerError(status: int, body: str)`, `WaxpeerUnavailableError(message: str)`
  - `WaxpeerTopup` frozen dataclass: `id: int`, `custom_id: str | None`,
    `status: WaxpeerStatus`, `amount_units: int`, `give_amount_units: int`,
    `steam_login: str`
  - `WaxpeerStatus = Literal["created", "sending", "completed", "canceled", "error"]`
  - `WaxpeerClient(api_key, base_url, timeout_seconds, client=None)` with
    `async validate_login(steam_login) -> tuple[bool, str | None]`,
    `async create_topup(*, steam_login, amount_units, custom_id) -> WaxpeerTopup`,
    `async get_topup(*, custom_id) -> WaxpeerTopup`,
    `async get_balance_units() -> int`

- [ ] **Step 1: Add settings**

In `apps/api/src/yupay/core/config.py`, directly below `g2b_request_timeout_seconds`:

```python
    # Waxpeer — Steam wallet top-ups. Empty key disables the supplier the same
    # way an empty g2b key does.
    waxpeer_api_key: str = Field(default="")
    waxpeer_base_url: str = Field(default="https://api.waxpeer.com/v1")
    waxpeer_request_timeout_seconds: float = Field(default=20.0)
    # Waxpeer's cut of a top-up. 0 today; a non-zero value makes us gross the
    # amount up so the customer still receives what they asked for.
    waxpeer_fee_rate: Decimal = Field(default=Decimal("0"), ge=0, lt=1)
```

`Decimal` is already imported in that module; if not, add `from decimal import Decimal`.

- [ ] **Step 2: Write the failing contract tests**

Create `apps/api/tests/contract/test_waxpeer_client.py`:

```python
"""Recorded Waxpeer shapes — taken from https://api.waxpeer.com/docs/json."""

from __future__ import annotations

import httpx
import pytest
import respx

from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerClient,
    WaxpeerError,
)

BASE = "https://api.waxpeer.test/v1"


def _client() -> WaxpeerClient:
    return WaxpeerClient(api_key="k", base_url=BASE, timeout_seconds=5.0)


@respx.mock
async def test_validate_login_accepts_supported_account() -> None:
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": True})
    )
    valid, message = await _client().validate_login("gaben")
    assert valid is True
    assert message is None


@respx.mock
async def test_validate_login_reports_the_reason() -> None:
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(
            200, json={"success": True, "valid": False, "msg": "account not found"}
        )
    )
    valid, message = await _client().validate_login("nobody")
    assert valid is False
    assert message == "account not found"


@respx.mock
async def test_create_topup_parses_the_topup_object() -> None:
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "msg": None,
                "topup": {
                    "id": 812345,
                    "custom_id": "order-123",
                    "status": "created",
                    "amount": 5000,
                    "give_amount": 5000,
                    "steam_login": "gaben",
                },
            },
        )
    )
    topup = await _client().create_topup(
        steam_login="gaben", amount_units=5000, custom_id="order-123"
    )
    assert topup.id == 812345
    assert topup.status == "created"
    assert topup.amount_units == 5000
    assert topup.give_amount_units == 5000


@respx.mock
async def test_create_topup_raises_on_api_level_failure() -> None:
    # HTTP 200 with success=false is how Waxpeer reports a refusal.
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "not enough balance"})
    )
    with pytest.raises(WaxpeerError) as exc:
        await _client().create_topup(steam_login="gaben", amount_units=5000, custom_id="c1")
    assert "not enough balance" in str(exc.value)


@respx.mock
async def test_get_topup_by_custom_id() -> None:
    route = respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "topup": {
                    "id": 1,
                    "custom_id": "c1",
                    "status": "completed",
                    "amount": 1000,
                    "give_amount": 1000,
                    "steam_login": "gaben",
                },
            },
        )
    )
    topup = await _client().get_topup(custom_id="c1")
    assert topup.status == "completed"
    assert route.calls.last.request.url.params["custom_id"] == "c1"


@respx.mock
async def test_get_balance_units() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "user": {"wallet": 123456}})
    )
    assert await _client().get_balance_units() == 123456
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/contract/test_waxpeer_client.py -q`
Expected: FAIL — `ModuleNotFoundError: yupay.modules.fulfillment.suppliers.waxpeer_client`

- [ ] **Step 4: Implement the client**

Create `apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer_client.py`:

```python
"""HTTP client for Waxpeer's Steam wallet top-up API.

Transport only: it speaks the wire format and raises on refusals. Status
interpretation, gross-up and reconciliation live in :mod:`waxpeer`.

Two things about this API drive the shape below:

* Refusals arrive as **HTTP 200 with ``success: false``**, so the status code
  alone never tells you whether a call worked.
* ``amount`` is denominated in units where ``1000 = $1``, i.e. a cent is 10.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

WaxpeerStatus = Literal["created", "sending", "completed", "canceled", "error"]


class WaxpeerError(Exception):
    """Waxpeer refused the call (transport ok, business failure)."""

    def __init__(self, message: str, *, status: int = 200) -> None:
        super().__init__(message)
        self.status = status


class WaxpeerUnavailableError(Exception):
    """Waxpeer could not be reached at all."""


@dataclass(frozen=True)
class WaxpeerTopup:
    """One top-up as Waxpeer reports it."""

    id: int
    custom_id: str | None
    status: WaxpeerStatus
    amount_units: int
    give_amount_units: int
    steam_login: str


class WaxpeerClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client  # injected in tests; None ⇒ transient per request

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            yield client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        query = {"api": self._api_key, **(params or {})}
        try:
            async with self._session() as client:
                resp = await client.request(method, url, params=query, json=json)
        except httpx.HTTPError as exc:
            raise WaxpeerUnavailableError(str(exc)) from exc
        if resp.status_code >= 400:
            raise WaxpeerError(resp.text[:500], status=resp.status_code)
        body: dict[str, Any] = resp.json()
        if not body.get("success", False):
            raise WaxpeerError(str(body.get("msg") or "waxpeer refused the request"))
        return body

    @staticmethod
    def _parse_topup(body: dict[str, Any]) -> WaxpeerTopup:
        raw = body.get("topup") or {}
        return WaxpeerTopup(
            id=int(raw["id"]),
            custom_id=raw.get("custom_id"),
            status=raw["status"],
            amount_units=int(raw["amount"]),
            give_amount_units=int(raw.get("give_amount", raw["amount"])),
            steam_login=str(raw.get("steam_login", "")),
        )

    async def validate_login(self, steam_login: str) -> tuple[bool, str | None]:
        body = await self._request(
            "GET", "/steam-topup/validate", params={"steam_login": steam_login}
        )
        return bool(body.get("valid", False)), body.get("msg")

    async def create_topup(
        self, *, steam_login: str, amount_units: int, custom_id: str
    ) -> WaxpeerTopup:
        body = await self._request(
            "POST",
            "/steam-topup",
            json={
                "steam_login": steam_login,
                "amount": amount_units,
                "custom_id": custom_id,
            },
        )
        return self._parse_topup(body)

    async def get_topup(self, *, custom_id: str) -> WaxpeerTopup:
        body = await self._request("GET", "/steam-topup", params={"custom_id": custom_id})
        return self._parse_topup(body)

    async def get_balance_units(self) -> int:
        body = await self._request("GET", "/user")
        user = body.get("user") or {}
        return int(user.get("wallet", 0))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/contract/test_waxpeer_client.py -q`
Expected: PASS, 6 passed

If `test_get_balance_units` fails on the response shape, fix the **test** to
match the real `GET /v1/user` payload (dump it once against the live API with
the real key) and keep the client aligned — do not guess a second shape.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer_client.py \
        apps/api/tests/contract/test_waxpeer_client.py \
        apps/api/src/yupay/core/config.py
git commit -m "feat(api/waxpeer): HTTP client for the Steam top-up API"
```

---

### Task 2: Variable-amount SKU columns

**Files:**

- Modify: `apps/api/src/yupay/modules/catalog/models.py` (class `Sku`)
- Create: `apps/api/migrations/versions/0025_variable_amount_skus.py`
- Modify: `apps/api/src/yupay/modules/catalog/schemas.py` (`SkuOut`)
- Test: `apps/api/tests/integration/test_catalog_variable_sku.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `Sku.variable_amount: bool`, `Sku.min_amount_usd: Decimal | None`,
  `Sku.max_amount_usd: Decimal | None`, `Sku.rate_multiplier: Decimal | None`;
  the same four fields on `SkuOut`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/integration/test_catalog_variable_sku.py`:

```python
"""A SKU whose amount the customer chooses."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.catalog.models import Sku


async def test_variable_amount_columns_round_trip(db_session: AsyncSession) -> None:
    sku = (await db_session.execute(__import__("sqlalchemy").select(Sku).limit(1))).scalar_one()
    sku.variable_amount = True
    sku.min_amount_usd = Decimal("1.00")
    sku.max_amount_usd = Decimal("300.00")
    sku.rate_multiplier = Decimal("1.0800")
    await db_session.flush()
    await db_session.refresh(sku)
    assert sku.variable_amount is True
    assert sku.min_amount_usd == Decimal("1.00")
    assert sku.rate_multiplier == Decimal("1.0800")


async def test_fixed_skus_default_to_non_variable(db_session: AsyncSession) -> None:
    sku = (await db_session.execute(__import__("sqlalchemy").select(Sku).limit(1))).scalar_one()
    assert sku.variable_amount is False
    assert sku.min_amount_usd is None
```

Replace the inline `__import__` with a normal `from sqlalchemy import select`
import at the top when writing the file — it is spelled out here only to keep
the snippet self-contained.

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_catalog_variable_sku.py -q`
Expected: FAIL — `AttributeError: 'Sku' object has no attribute 'variable_amount'`

- [ ] **Step 3: Add the columns to the model**

In `apps/api/src/yupay/modules/catalog/models.py`, inside `class Sku`, after
`cost_usdt`:

```python
    # Variable-amount SKUs (Steam wallet): the customer picks the amount, so
    # ``price_usd`` is not the price — it is computed at checkout from the
    # amount, the guarded FX rate and ``rate_multiplier``. The bounds are the
    # supplier's per-transaction limits.
    variable_amount: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    min_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    # Margin: the customer-facing rate is the market rate times this.
    rate_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
```

Add to `__table_args__`:

```python
        CheckConstraint(
            "NOT variable_amount OR ("
            " min_amount_usd IS NOT NULL AND max_amount_usd IS NOT NULL"
            " AND rate_multiplier IS NOT NULL AND min_amount_usd > 0"
            " AND max_amount_usd >= min_amount_usd AND rate_multiplier > 0)",
            name="ck_skus_variable_amount_complete",
        ),
```

- [ ] **Step 4: Write the migration**

Create `apps/api/migrations/versions/0025_variable_amount_skus.py`:

```python
"""Variable-amount SKUs: the customer chooses how much to buy.

Steam wallet top-ups are sold by amount, not by denomination, so the price is
computed at checkout instead of read off the row. The CHECK keeps a variable
SKU from existing without the bounds and multiplier that pricing needs.

Revision ID: 0025_variable_amount_skus
Revises: 0024_promo_codes
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_variable_amount_skus"
down_revision: str | None = "0024_promo_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skus",
        sa.Column("variable_amount", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("skus", sa.Column("min_amount_usd", sa.Numeric(20, 6), nullable=True))
    op.add_column("skus", sa.Column("max_amount_usd", sa.Numeric(20, 6), nullable=True))
    op.add_column("skus", sa.Column("rate_multiplier", sa.Numeric(10, 4), nullable=True))
    op.create_check_constraint(
        "ck_skus_variable_amount_complete",
        "skus",
        "NOT variable_amount OR ("
        " min_amount_usd IS NOT NULL AND max_amount_usd IS NOT NULL"
        " AND rate_multiplier IS NOT NULL AND min_amount_usd > 0"
        " AND max_amount_usd >= min_amount_usd AND rate_multiplier > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_variable_amount_complete", "skus", type_="check")
    op.drop_column("skus", "rate_multiplier")
    op.drop_column("skus", "max_amount_usd")
    op.drop_column("skus", "min_amount_usd")
    op.drop_column("skus", "variable_amount")
```

- [ ] **Step 5: Expose the fields on `SkuOut`**

In `apps/api/src/yupay/modules/catalog/schemas.py`, add to `SkuOut`:

```python
    variable_amount: bool = False
    min_amount_usd: Decimal | None = None
    max_amount_usd: Decimal | None = None
```

`rate_multiplier` is **not** exposed publicly — it is our margin. It goes on the
admin schema only (Task 10).

- [ ] **Step 6: Run tests**

Run: `cd apps/api && uv run pytest tests/integration/test_catalog_variable_sku.py -q`
Expected: PASS, 2 passed

- [ ] **Step 7: Regenerate the API client and commit**

```bash
make gen-api
git add apps/api/src/yupay/modules/catalog apps/api/migrations/versions/0025_variable_amount_skus.py \
        apps/api/tests/integration/test_catalog_variable_sku.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/catalog): variable-amount SKUs"
```

---

### Task 3: FX trust gate

A rate may only set a price after it clears freshness, deviation and an
absolute band. Anything else pulls the product from sale.

**Files:**

- Create: `apps/api/src/yupay/modules/pricing/__init__.py`
- Create: `apps/api/src/yupay/modules/pricing/fx_guard.py`
- Modify: `apps/api/src/yupay/core/config.py`
- Test: `apps/api/tests/unit/test_fx_guard.py`

**Interfaces:**

- Consumes: `yupay.modules.fx.service` (`build_default_service`, `FxUnavailableError`).
- Produces:
  - `RateRejected(Exception)` with `.reason: Literal["unavailable","stale","deviation","out_of_band","non_positive"]`
  - `check_rate(rate: Decimal, *, fetched_at: datetime, previous: Decimal | None, now_: datetime, settings) -> None` — raises `RateRejected`
  - `async guarded_usd_rate(db, *, quote: str) -> Decimal`

- [ ] **Step 1: Add settings**

In `apps/api/src/yupay/core/config.py`, next to the other FX settings:

```python
    # Trust gate for rates that set a customer-facing price. A plausible but
    # wrong rate is worse than no rate: we would apply the margin multiplier to
    # it and keep selling. Failing closed costs a sale; failing open costs the
    # difference on every order.
    pricing_fx_max_age_seconds: int = Field(default=6 * 3600)
    pricing_fx_max_deviation_pct: Decimal = Field(default=Decimal("15"))
    pricing_fx_min_rate_uzs: Decimal = Field(default=Decimal("8000"))
    pricing_fx_max_rate_uzs: Decimal = Field(default=Decimal("25000"))
```

- [ ] **Step 2: Write the failing tests**

Create `apps/api/tests/unit/test_fx_guard.py`:

```python
"""The gate a rate must pass before it may price an order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from yupay.core.config import get_settings
from yupay.modules.pricing.fx_guard import RateRejected, check_rate

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
GOOD = Decimal("13000")


def _check(rate: Decimal, *, age: timedelta = timedelta(0), previous: Decimal | None = GOOD):
    check_rate(
        rate,
        fetched_at=NOW - age,
        previous=previous,
        now_=NOW,
        settings=get_settings(),
    )


def test_accepts_a_fresh_plausible_rate() -> None:
    _check(Decimal("13100"))  # no exception


def test_rejects_a_non_positive_rate() -> None:
    with pytest.raises(RateRejected) as exc:
        _check(Decimal("0"))
    assert exc.value.reason == "non_positive"


def test_rejects_a_stale_rate() -> None:
    with pytest.raises(RateRejected) as exc:
        _check(GOOD, age=timedelta(hours=7))
    assert exc.value.reason == "stale"


def test_rejects_a_rate_that_halved() -> None:
    # The failure that motivated the gate: a provider returns a number that
    # looks like a rate but is half the real one.
    with pytest.raises(RateRejected) as exc:
        _check(GOOD / 2)
    assert exc.value.reason == "deviation"


def test_rejects_a_rate_outside_the_absolute_band() -> None:
    with pytest.raises(RateRejected) as exc:
        _check(Decimal("1000"), previous=None)
    assert exc.value.reason == "out_of_band"


def test_accepts_a_first_ever_rate_inside_the_band() -> None:
    # No previous value to compare against — the band is the only guard.
    _check(Decimal("13000"), previous=None)


def test_allows_movement_within_the_threshold() -> None:
    _check(GOOD * Decimal("1.10"))
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd apps/api && uv run pytest tests/unit/test_fx_guard.py -q`
Expected: FAIL — `ModuleNotFoundError: yupay.modules.pricing`

- [ ] **Step 4: Implement**

Create `apps/api/src/yupay/modules/pricing/__init__.py` (empty) and
`apps/api/src/yupay/modules/pricing/fx_guard.py`:

```python
"""Trust gate for rates that set customer-facing prices.

The FX layer already fails over between providers, caches, and rejects
non-positive numbers. What it cannot see is a rate that *parses* fine but is
wrong — half the real value, or yesterday's. Applying our margin multiplier to
such a number and continuing to sell is how a pricing bug becomes a refund
queue, so pricing runs rates through here first and refuses to sell when a
rate cannot be trusted.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import structlog

from yupay.core.config import Settings, get_settings
from yupay.core.time import now
from yupay.modules.fx.service import FxUnavailableError, build_default_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

RejectReason = Literal["unavailable", "stale", "deviation", "out_of_band", "non_positive"]


class RateRejected(Exception):
    """The rate must not be used to price anything."""

    def __init__(self, reason: RejectReason, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason: RejectReason = reason


def check_rate(
    rate: Decimal,
    *,
    fetched_at: datetime,
    previous: Decimal | None,
    now_: datetime,
    settings: Settings,
) -> None:
    """Raise :class:`RateRejected` unless ``rate`` may set a price."""
    if rate <= 0:
        raise RateRejected("non_positive", f"rate={rate}")

    age = (now_ - fetched_at).total_seconds()
    if age > settings.pricing_fx_max_age_seconds:
        raise RateRejected("stale", f"age={age:.0f}s")

    if not (settings.pricing_fx_min_rate_uzs <= rate <= settings.pricing_fx_max_rate_uzs):
        raise RateRejected("out_of_band", f"rate={rate}")

    if previous is not None and previous > 0:
        deviation = abs(rate - previous) / previous * Decimal("100")
        if deviation > settings.pricing_fx_max_deviation_pct:
            raise RateRejected("deviation", f"{deviation:.1f}% from {previous}")


async def guarded_usd_rate(db: AsyncSession, *, quote: str) -> Decimal:
    """USD→``quote`` rate that has passed the gate, or :class:`RateRejected`."""
    settings = get_settings()
    fx = build_default_service()
    try:
        snap = await fx.snapshot(db, base="USD", quote=quote)
    except FxUnavailableError as exc:
        raise RateRejected("unavailable", str(exc)) from exc

    previous = await _previous_rate(db, quote=quote, exclude_id=snap.id)
    try:
        check_rate(
            snap.rate,
            fetched_at=snap.fetched_at,
            previous=previous,
            now_=now(),
            settings=settings,
        )
    except RateRejected as exc:
        # Loud on purpose: this is money, and the product disappears from sale
        # until someone looks.
        log.error("pricing.rate_rejected", reason=exc.reason, quote=quote, detail=str(exc))
        raise
    return snap.rate
```

Implement `_previous_rate` as a `SELECT rate FROM fx_rates WHERE base='USD' AND
quote=:quote AND id != :exclude_id ORDER BY fetched_at DESC LIMIT 1`, returning
`Decimal | None`. Confirm the attribute names on the object `fx.snapshot()`
returns (`.id`, `.rate`, `.fetched_at`) by reading
`apps/api/src/yupay/modules/fx/service.py` before writing it; adjust if they
differ.

- [ ] **Step 5: Run tests**

Run: `cd apps/api && uv run pytest tests/unit/test_fx_guard.py -q`
Expected: PASS, 7 passed

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/pricing apps/api/tests/unit/test_fx_guard.py \
        apps/api/src/yupay/core/config.py
git commit -m "feat(api/pricing): trust gate for rates that set prices"
```

---

### Task 4: Variable-amount pricing

**Files:**

- Create: `apps/api/src/yupay/modules/pricing/variable.py`
- Test: `apps/api/tests/unit/test_variable_pricing.py`

**Interfaces:**

- Consumes: Task 3 (`guarded_usd_rate`), Task 2 (`Sku.rate_multiplier`).
- Produces:
  - `UNITS_PER_USD = 1000`
  - `to_units(amount_usd: Decimal, *, fee_rate: Decimal) -> int`
  - `display_rate(market_rate: Decimal, multiplier: Decimal) -> Decimal`
  - `price_in_quote(amount_usd: Decimal, *, display_rate: Decimal) -> Decimal`
  - `validate_amount(amount_usd: Decimal, *, minimum: Decimal, maximum: Decimal) -> None` raising `ValidationError`

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/unit/test_variable_pricing.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest

from yupay.core.errors import ValidationError
from yupay.modules.pricing.variable import (
    display_rate,
    price_in_quote,
    to_units,
    validate_amount,
)


def test_whole_dollars_convert_exactly() -> None:
    assert to_units(Decimal("5"), fee_rate=Decimal("0")) == 5000


def test_cents_convert_exactly() -> None:
    # 1000 units = $1, so a cent is 10 units and two decimals are exact.
    assert to_units(Decimal("10.50"), fee_rate=Decimal("0")) == 10500


def test_fee_is_grossed_up_so_the_customer_still_receives_the_amount() -> None:
    # 5% fee: send enough that ~$10 survives it.
    assert to_units(Decimal("10"), fee_rate=Decimal("0.05")) == 10527


def test_gross_up_rounds_up_never_short_changing_the_customer() -> None:
    units = to_units(Decimal("9.99"), fee_rate=Decimal("0.03"))
    assert units * (Decimal("1") - Decimal("0.03")) >= Decimal("9.99") * 1000


def test_display_rate_applies_the_margin() -> None:
    assert display_rate(Decimal("13000"), Decimal("1.08")) == Decimal("14040")


def test_price_is_amount_times_display_rate() -> None:
    assert price_in_quote(Decimal("10"), rate=Decimal("14025")) == Decimal("140250")


def test_amount_below_minimum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_amount(Decimal("0.50"), minimum=Decimal("1"), maximum=Decimal("300"))


def test_amount_above_maximum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_amount(Decimal("301"), minimum=Decimal("1"), maximum=Decimal("300"))


def test_more_than_two_decimals_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_amount(Decimal("10.123"), minimum=Decimal("1"), maximum=Decimal("300"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/api && uv run pytest tests/unit/test_variable_pricing.py -q`
Expected: FAIL — `ModuleNotFoundError: ...pricing.variable`

- [ ] **Step 3: Implement**

Create `apps/api/src/yupay/modules/pricing/variable.py`:

```python
"""Pricing for SKUs whose amount the customer chooses.

Two conversions live here and nowhere else:

* **amount → supplier units.** Waxpeer counts in thousandths of a dollar, and
  any fee it charges must be grossed up so the customer still receives what
  they asked for. Rounding is always up: the most we lose is a cent, and the
  customer is never short-changed.
* **amount → price.** The customer-facing rate is the market rate times the
  SKU's multiplier, which is where our margin lives — there is no separate
  percentage shown anywhere.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from yupay.core.errors import ValidationError

UNITS_PER_USD = 1000
_CENT = Decimal("0.01")


def to_units(amount_usd: Decimal, *, fee_rate: Decimal) -> int:
    """Supplier units to send so the wallet receives ``amount_usd``."""
    if fee_rate < 0 or fee_rate >= 1:
        raise ValidationError("fee rate must be in [0, 1)", extra={"fee_rate": str(fee_rate)})
    gross = amount_usd / (Decimal("1") - fee_rate)
    return int((gross * UNITS_PER_USD).to_integral_value(rounding=ROUND_CEILING))


def display_rate(market_rate: Decimal, multiplier: Decimal) -> Decimal:
    """Rate shown to the customer — margin included."""
    return market_rate * multiplier


def price_in_quote(amount_usd: Decimal, *, rate: Decimal) -> Decimal:
    """What the customer pays, in the quote currency's own units.

    ``rate`` is the customer-facing rate from :func:`display_rate`, not the raw
    market rate — the parameter is deliberately not called ``display_rate`` so
    it cannot shadow that function at call sites.
    """
    return (amount_usd * rate).quantize(Decimal("1.000000"), rounding=ROUND_HALF_UP)


def validate_amount(amount_usd: Decimal, *, minimum: Decimal, maximum: Decimal) -> None:
    """Reject anything the supplier or the SKU will not accept."""
    if amount_usd.quantize(_CENT) != amount_usd:
        raise ValidationError(
            "amount supports at most two decimals", extra={"amount": str(amount_usd)}
        )
    if amount_usd < minimum or amount_usd > maximum:
        raise ValidationError(
            "amount is outside the allowed range",
            extra={"amount": str(amount_usd), "min": str(minimum), "max": str(maximum)},
        )
```

- [ ] **Step 4: Run tests**

Run: `cd apps/api && uv run pytest tests/unit/test_variable_pricing.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/pricing/variable.py apps/api/tests/unit/test_variable_pricing.py
git commit -m "feat(api/pricing): amount→units and amount→price for variable SKUs"
```

---

### Task 5: Checkout accepts a customer-chosen amount

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/schemas.py` (`OrderItemIn`, ~line 25)
- Modify: `apps/api/src/yupay/modules/orders/service.py` (pricing block, ~lines 182-238)
- Test: `apps/api/tests/integration/test_checkout_variable_amount.py`

**Interfaces:**

- Consumes: Tasks 2, 3, 4.
- Produces: `OrderItemIn.amount_usd: Decimal | None`; order items whose
  `unit_price_usd` is the chosen amount and whose `extra_metadata` carries the
  rate sold at.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/integration/test_checkout_variable_amount.py` covering:

```python
async def test_variable_sku_prices_from_the_amount(...) -> None:
    """$10 at a guarded market rate of 13000 and multiplier 1.08 charges 140 400 UZS."""


async def test_amount_is_required_for_a_variable_sku(...) -> None:
    """Omitting amount_usd is a 422, not a silent zero."""


async def test_amount_is_rejected_for_a_fixed_sku(...) -> None:
    """Sending amount_usd for a normal SKU is a 422 — no ambiguity about price."""


async def test_amount_outside_the_sku_bounds_is_rejected(...) -> None:
    """$301 against a $1–$300 SKU is a 422."""


async def test_client_supplied_price_is_ignored(...) -> None:
    """The order total comes from the server's computation, never the request."""


async def test_rejected_rate_makes_checkout_fail_closed(...) -> None:
    """With the FX guard tripped, checkout answers 502 and no order is created."""
```

Write the bodies following the existing style in
`apps/api/tests/integration/test_orders_*.py`: build a variable SKU via the
catalog fixtures, patch the FX service factory to return a fixed rate, POST
`/api/v1/orders`, assert on the response and on the persisted row.

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/api && uv run pytest tests/integration/test_checkout_variable_amount.py -q`
Expected: FAIL — `extra fields not permitted: amount_usd`

- [ ] **Step 3: Extend the request schema**

In `apps/api/src/yupay/modules/orders/schemas.py`:

```python
class OrderItemIn(BaseModel):
    """One line of a new-order request."""

    model_config = ConfigDict(extra="forbid")

    sku_id: str
    qty: int = Field(ge=1, le=100)
    fulfillment_data: dict[str, Any] = Field(default_factory=dict)
    # Set only for variable-amount SKUs (Steam wallet): how many dollars the
    # customer is buying. The price is derived from it server-side; the client
    # never sends a price.
    amount_usd: Decimal | None = Field(default=None, gt=0)
```

- [ ] **Step 4: Price variable lines in the service**

In `apps/api/src/yupay/modules/orders/service.py`, inside the item loop that
currently reads:

```python
        sku = skus[line.sku_id]
        product: Product = sku.product
        cleaned = validate_fulfillment_data(product=product, data=line.fulfillment_data)
```

insert the amount resolution immediately after `cleaned = ...`:

```python
        if sku.variable_amount:
            if line.amount_usd is None:
                raise ValidationError(
                    "amount is required for this product", extra={"sku_id": sku.id}
                )
            validate_amount(
                line.amount_usd,
                minimum=sku.min_amount_usd or Decimal("0"),
                maximum=sku.max_amount_usd or Decimal("0"),
            )
            unit_price_usd = line.amount_usd
        else:
            if line.amount_usd is not None:
                raise ValidationError(
                    "this product has a fixed price", extra={"sku_id": sku.id}
                )
            unit_price_usd = sku.price_usd
```

then replace the two uses of `sku.price_usd` in that loop with `unit_price_usd`
(`OrderItem(..., unit_price_usd=unit_price_usd, ...)` and
`total_usd += unit_price_usd * line.qty`).

In the per-currency block, a variable line must use the guarded rate times the
multiplier instead of the plain FX snapshot. Inside the `for line in body.items`
loop of step 3 of that function, before the override lookup:

```python
            if sku.variable_amount:
                try:
                    market = await guarded_usd_rate(db, quote=currency)
                except RateRejected as exc:
                    raise UpstreamUnavailableError(
                        "Цена временно недоступна. Попробуйте позже.",
                        base="USD",
                        quote=currency,
                        reason=exc.reason,
                    ) from exc
                rate = display_rate(market, sku.rate_multiplier or Decimal("1"))
                total_charged += price_in_quote(
                    line.amount_usd or Decimal("0"), rate=rate
                ) * line.qty
                continue
```

Add the imports at the top of the module:

```python
from yupay.modules.pricing.fx_guard import RateRejected, guarded_usd_rate
from yupay.modules.pricing.variable import display_rate, price_in_quote, validate_amount
```

- [ ] **Step 5: Run tests**

Run: `cd apps/api && uv run pytest tests/integration/test_checkout_variable_amount.py -q`
Expected: PASS, 6 passed

Then the whole order suite, since the pricing loop changed:
Run: `cd apps/api && uv run pytest tests/integration -k order -q`
Expected: PASS, no regressions

- [ ] **Step 6: Preflight the supplier balance**

We must not take money for something we cannot deliver. The existing gateway
preflight in this same function is the precedent.

Test first, in the same file:

```python
async def test_checkout_refused_when_supplier_balance_is_short(...) -> None:
    """Waxpeer balance below the gross needed ⇒ 502 and no order row."""
```

Then, after the amount is validated and before the order is persisted, for
variable lines whose SKU routes to `waxpeer`:

```python
        fulfiller = SUPPLIERS.get(mapping.supplier)
        if sku.variable_amount and isinstance(fulfiller, WaxpeerFulfiller):
            needed = to_units(unit_price_usd, fee_rate=get_settings().waxpeer_fee_rate)
            if not await fulfiller.has_balance(needed * line.qty):
                raise UpstreamUnavailableError(
                    "Пополнение временно недоступно. Попробуйте позже.",
                    supplier="waxpeer",
                )
```

`has_balance(units: int) -> bool` is added to `WaxpeerFulfiller` in Task 6; it
wraps `get_balance_units()` and answers `False` on any transport error — an
unreachable supplier is not a sellable one.

- [ ] **Step 7: Hide the product when the rate cannot be trusted**

A tripped gate must remove the product from sale, not surface a wrong price.

Test, in `apps/api/tests/integration/test_catalog_variable_sku.py`:

```python
async def test_variable_sku_reports_no_price_when_the_rate_is_rejected(...) -> None:
    """With the FX guard tripped the SKU comes back with display_price=None so
    the storefront renders "temporarily unavailable" instead of a zero."""
```

In the catalog read path that populates `display_price`, wrap the variable-SKU
branch in `try/except RateRejected` and leave `display_price` as `None` on
rejection. Do not fall back to the raw market rate: selling without the margin
is the loss the gate exists to prevent.

- [ ] **Step 8: Run the suites and commit**

Run: `cd apps/api && uv run pytest tests/integration/test_checkout_variable_amount.py tests/integration/test_catalog_variable_sku.py -q`
Expected: PASS

```bash
make gen-api
git add apps/api/src/yupay/modules/orders apps/api/src/yupay/modules/catalog \
        apps/api/tests/integration/test_checkout_variable_amount.py \
        apps/api/tests/integration/test_catalog_variable_sku.py \
        docs/api/openapi.json packages/api-client
git commit -m "feat(api/orders): price variable-amount lines from the customer's amount"
```

---

### Task 6: WaxpeerFulfiller

**Files:**

- Create: `apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer.py`
- Modify: `apps/api/src/yupay/modules/fulfillment/suppliers/__init__.py`
- Test: `apps/api/tests/contract/test_waxpeer_fulfiller.py`

**Interfaces:**

- Consumes: Task 1 (`WaxpeerClient`, `WaxpeerTopup`, `WaxpeerError`), Task 4
  (`to_units`, `UNITS_PER_USD`).
- Produces: `WaxpeerFulfiller` registered as `"waxpeer"` in the supplier registry.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/contract/test_waxpeer_fulfiller.py` covering, with respx:

```python
async def test_fulfill_sends_the_grossed_up_amount_and_the_order_key() -> None:
    """$10 with fee 0 posts amount=10000 and custom_id=<idempotency key>."""


async def test_fulfill_is_in_progress_until_steam_is_credited() -> None:
    """status=created ⇒ outcome "in_progress", external id recorded."""


async def test_completed_maps_to_succeeded_with_a_receipt() -> None:
    """status=completed ⇒ "succeeded" and a topup_receipt artifact."""


async def test_canceled_maps_to_failed_and_says_the_supplier_refunded() -> None:
    """status=canceled ⇒ "failed"; metadata marks the money as returned to us."""


async def test_error_maps_to_failed_and_flags_manual_reconciliation() -> None:
    """status=error ⇒ "failed" with needs_reconciliation, because Waxpeer does
    not refund this case automatically."""


async def test_short_give_amount_is_flagged_not_swallowed() -> None:
    """give_amount below the promise records a discrepancy — this is how a
    newly-introduced supplier fee surfaces before customers complain."""


async def test_repeated_fulfill_reuses_the_existing_topup() -> None:
    """Same custom_id ⇒ Waxpeer returns the original; we must not treat the
    replay as a second delivery."""


async def test_unavailable_without_an_api_key() -> None:
    """No key configured ⇒ available is False and fulfill raises FulfillerError."""
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/api && uv run pytest tests/contract/test_waxpeer_fulfiller.py -q`
Expected: FAIL — `ModuleNotFoundError: ...suppliers.waxpeer`

- [ ] **Step 3: Implement the fulfiller**

Create `apps/api/src/yupay/modules/fulfillment/suppliers/waxpeer.py` following
`g2b.py`'s shape (transient client from settings, `available` gated on the key).
The status mapping is the substance:

```python
_TERMINAL_OK = "completed"
_IN_FLIGHT = ("created", "sending")


def _status_to_outcome(status: WaxpeerStatus) -> FulfillOutcome:
    if status == _TERMINAL_OK:
        return "succeeded"
    if status in _IN_FLIGHT:
        return "in_progress"
    return "failed"
```

`fulfill` reads the amount from `item.unit_price_usd` (the chosen dollars),
converts with `to_units(..., fee_rate=settings.waxpeer_fee_rate)`, posts with
`custom_id=idempotency_key`, and returns:

```python
        promised_units = int(item.unit_price_usd * UNITS_PER_USD)
        shortfall = promised_units - topup.give_amount_units
        extra: dict[str, Any] = {
            "waxpeer_status": topup.status,
            "amount_units": topup.amount_units,
            "give_amount_units": topup.give_amount_units,
        }
        if shortfall > 0:
            # Waxpeer started taking a cut, or took a bigger one than
            # configured. Do not under-deliver quietly.
            extra["give_amount_shortfall_units"] = shortfall
            log.error(
                "waxpeer.give_amount_short",
                order_item_id=item.id,
                promised_units=promised_units,
                give_amount_units=topup.give_amount_units,
            )
```

`check_status` fetches by `custom_id` (stored as the task's external key) and
maps the same way, adding `needs_reconciliation=True` to the metadata when the
status is `error`, and `supplier_refunded=True` when it is `canceled`.

`cancel` is a no-op that raises `FulfillerNotIntegratedError` — Waxpeer has no
cancel endpoint, and pretending otherwise would hide the truth from the
fulfilment inbox.

- [ ] **Step 4: Add the balance probe and the refund path**

`has_balance`, consumed by Task 5's preflight:

```python
    async def has_balance(self, units: int) -> bool:
        """Whether we can currently fund ``units``.

        Answers ``False`` rather than raising: an unreachable supplier is not a
        sellable one, and the caller's job is to stop the sale either way.
        """
        try:
            return await self._client().get_balance_units() >= units
        except (WaxpeerError, WaxpeerUnavailableError):
            log.warning("waxpeer.balance_probe_failed")
            return False
```

The `error` status means Waxpeer kept the money and will not return it
automatically. The customer must not wait on our correspondence with a
supplier, so the refund to them is unconditional; the recovery from Waxpeer is
a separate, human process. Verify how a `failed` outcome triggers the customer
refund today by reading `apps/api/src/yupay/modules/fulfillment/service.py` — if
failure already refunds, this task only has to make sure `error` maps to
`failed` (it does, via `_status_to_outcome`) and that the metadata carries
`needs_reconciliation=True` so the fulfilment inbox can surface it. If failure
does **not** refund automatically, add the refund call here and cover it with:

```python
async def test_error_status_refunds_the_customer(...) -> None:
    """The customer is made whole even though Waxpeer has not refunded us."""
```

- [ ] **Step 5: Register the supplier**

In `apps/api/src/yupay/modules/fulfillment/suppliers/__init__.py`, add the
import and the registry entry next to `"g2b": G2bFulfiller()`:

```python
from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller
...
    "waxpeer": WaxpeerFulfiller(),
```

- [ ] **Step 6: Run tests**

Run: `cd apps/api && uv run pytest tests/contract/test_waxpeer_fulfiller.py -q`
Expected: PASS, 8 passed

Coverage gate for the adapter:
Run: `cd apps/api && uv run pytest tests/contract/test_waxpeer_fulfiller.py tests/contract/test_waxpeer_client.py --cov=yupay.modules.fulfillment.suppliers.waxpeer --cov=yupay.modules.fulfillment.suppliers.waxpeer_client --cov-report=term-missing -q`
Expected: ≥95% on both modules

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/fulfillment/suppliers apps/api/tests/contract/test_waxpeer_fulfiller.py
git commit -m "feat(api/fulfillment): Waxpeer Steam top-up adapter"
```

---

### Task 7: Steam login validation through check-player

**Files:**

- Modify: `apps/api/src/yupay/modules/catalog/schemas.py` (`FieldCheck.provider`)
- Modify: `apps/api/src/yupay/modules/integrations/player_check.py`
- Test: `apps/api/tests/integration/test_player_check_endpoint.py` (extend)

**Interfaces:**

- Consumes: Task 1 (`WaxpeerClient.validate_login`).
- Produces: `FieldCheck.provider` accepting `"waxpeer"`; the existing
  `POST /api/v1/catalog/products/{id}/check-player` answering for Steam.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/integration/test_player_check_endpoint.py`:

```python
@respx.mock
async def test_steam_login_valid(integration_client, ...) -> None:
    """A supported login answers status "valid"."""


@respx.mock
async def test_steam_login_invalid(integration_client, ...) -> None:
    """An unsupported login answers status "invalid", not an error — the
    customer mistyped, nothing is broken."""


@respx.mock
async def test_steam_check_upstream_failure_is_error(integration_client, ...) -> None:
    """Waxpeer unreachable answers status "error" so the UI blames us, not the
    customer, and never blocks checkout."""
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/api && uv run pytest tests/integration/test_player_check_endpoint.py -q -k steam`
Expected: FAIL

- [ ] **Step 3: Widen the provider literal**

In `apps/api/src/yupay/modules/catalog/schemas.py`:

```python
    provider: Literal["g2b", "waxpeer"]
```

- [ ] **Step 4: Route by provider in player_check**

In `apps/api/src/yupay/modules/integrations/player_check.py`, branch on the
field's `check.provider`: `"g2b"` keeps today's path; `"waxpeer"` calls
`WaxpeerClient.validate_login` and maps to the existing three-way result —
`valid` → `PlayerCheckOut(status="valid", name=None)`, not valid →
`status="invalid"`, transport failure → `status="error"`. Steam has no display
name to show, so `name` stays `None` and the storefront shows the confirmation
pill without a nickname.

Keep the existing cache key hashing: the Steam login is personal data and must
not appear in Redis keys in the clear.

- [ ] **Step 5: Run tests**

Run: `cd apps/api && uv run pytest tests/integration/test_player_check_endpoint.py -q`
Expected: PASS, all

- [ ] **Step 6: Commit**

```bash
make gen-api
git add apps/api/src/yupay/modules/catalog/schemas.py \
        apps/api/src/yupay/modules/integrations/player_check.py \
        apps/api/tests/integration/test_player_check_endpoint.py docs/api/openapi.json packages/api-client
git commit -m "feat(api/catalog): validate Steam logins through check-player"
```

---

### Task 8: Steam in the catalogue

**Files:**

- Modify: `apps/api/src/yupay/scripts/seed_catalog.py`
- Test: `apps/api/tests/integration/test_seed_catalog.py` (extend if present, else assert via the catalog API test)

- [ ] **Step 1: Add the brand, product and SKU**

Extend the curated snapshot in `seed_catalog.py` with a `steam` brand, a
`Пополнение кошелька` product (`kind="top_up"`), and one SKU:

```python
SkuSpec(
    code="steam-wallet-usd",
    denomination="Любая сумма",
    price_usd=Decimal("1"),          # unused for variable SKUs; satisfies the CHECK
    variable_amount=True,
    min_amount_usd=Decimal("1.00"),
    max_amount_usd=Decimal("300.00"),
    rate_multiplier=Decimal("1.0800"),
    supplier="waxpeer",
    external_product_id="steam-topup",
)
```

The product's `required_fields` carry the login field with the check opt-in:

```python
{
    "key": "steam_login",
    "label": {"ru": "Логин Steam", "en": "Steam login", "uz": "Steam login"},
    "type": "text",
    "required": True,
    "pattern": r"^[A-Za-z0-9_-]{3,64}$",
    "check": {"provider": "waxpeer"},
}
```

- [ ] **Step 2: Run the seed against a scratch database and verify**

Run: `cd apps/api && uv run python -m yupay.scripts.seed_catalog`
Then: `psql -c "SELECT sku_code, variable_amount, min_amount_usd, max_amount_usd, rate_multiplier FROM skus WHERE variable_amount;"`
Expected: one row, `steam-wallet-usd`, `t`, `1.000000`, `300.000000`, `1.0800`

- [ ] **Step 3: Commit**

```bash
git add apps/api/src/yupay/scripts/seed_catalog.py
git commit -m "feat(api/catalog): seed Steam wallet top-up"
```

---

### Task 9: Storefront — amount input and the rate line

**Files:**

- Modify: `apps/miniapp/src/pages/TopUp.tsx`
- Modify: `apps/web/src/components/store/PurchasePanel.tsx`
- Create: `apps/miniapp/src/lib/variable-amount.ts`
- Test: `apps/miniapp/src/lib/variable-amount.test.ts`
- Modify: `packages/i18n/locales/{ru,en,uz}/{miniapp,web}.json`

**Interfaces:**

- Consumes: `SkuOut.variable_amount`, `min_amount_usd`, `max_amount_usd` (Task 2);
  `amount_usd` on the checkout line (Task 5).
- Produces: `parseAmount(input: string): number | null`,
  `amountError(amount, min, max): "below" | "above" | "precision" | null`.

- [ ] **Step 1: Write the failing unit tests**

`apps/miniapp/src/lib/variable-amount.test.ts` — parsing (comma and dot as
decimal separators, empty, junk), bounds, and the two-decimal rule. Node
environment, no DOM, following `player-check-state.test.ts`.

- [ ] **Step 2: Implement the helper, run tests**

Run: `cd apps/miniapp && pnpm exec vitest run src/lib/variable-amount.test.ts`
Expected: PASS

- [ ] **Step 3: Render the amount field**

When the selected product's SKU has `variable_amount`, replace the package grid
with: an amount input (numeric keyboard, `$` prefix), the computed UZS total,
and the rate line — `1 $ = {rate} сум` plus a `0%` badge, matching the spec's
customer-facing wording. The pay button stays disabled while `amountError` is
non-null and shows the reason.

The rate comes from the same catalog response that already carries
`display_price`; if it is absent, the product is not for sale (the FX gate
tripped) — render the existing "temporarily unavailable" state rather than a
price of zero.

- [ ] **Step 4: Add i18n keys to all three locales**

`topup.amountLabel`, `topup.amountPlaceholder`, `topup.amountBelow`,
`topup.amountAbove`, `topup.ratePerDollar`, `topup.zeroFee`,
`topup.priceUnavailable`.

- [ ] **Step 5: Verify in the browser**

Run the miniapp against a seeded API, open the Steam product, and check: typing
`10` shows the UZS total and the rate line; `0.5` and `301` disable the button
with the right message; `10.123` is rejected.

- [ ] **Step 6: Commit**

```bash
git add apps/miniapp/src apps/web/src packages/i18n/locales
git commit -m "feat(miniapp,web): amount input and rate line for Steam top-up"
```

---

### Task 10: Admin — variable-SKU fields

**Files:**

- Modify: `apps/admin/src/features/catalog/skus/SkuEditPage.tsx`
- Modify: `apps/api/src/yupay/modules/catalog/schemas.py` (admin SKU in/out)

- [ ] **Step 1: Expose the fields on the admin schema**

Add `variable_amount`, `min_amount_usd`, `max_amount_usd`, `rate_multiplier` to
the admin SKU create/update schemas (the public `SkuOut` already carries the
first three from Task 2; `rate_multiplier` is admin-only).

- [ ] **Step 2: Add the form controls**

In `SkuEditPage.tsx`, a "Плавающая сумма" checkbox that reveals three fields:
minimum, maximum, rate multiplier. When it is off, the three stay hidden and are
sent as `null`. Price fields hide when it is on — `price_usd` means nothing for
a variable SKU and showing it invites someone to "fix" the price.

- [ ] **Step 3: Show the effective rate**

Under the multiplier, render the resulting customer-facing rate — the operator
is setting margin, and a bare `1.08` does not tell them what the customer will
see. Reuse the admin FX page's rate query.

- [ ] **Step 4: Verify and commit**

Run: `cd apps/admin && pnpm exec tsc --noEmit && pnpm exec eslint src`
Expected: no errors

```bash
git add apps/admin/src apps/api/src/yupay/modules/catalog/schemas.py
git commit -m "feat(admin/catalog): edit variable-amount SKU fields"
```

---

### Task 11: Documentation

**Files:**

- Create: `apps/api/src/yupay/modules/pricing/README.md`
- Create: `docs/decisions/0032-variable-amount-skus.md`
- Create: `docs/runbooks/waxpeer-troubleshooting.md`
- Modify: `docs/architecture/module-map.md`

- [ ] **Step 1: Write the ADR**

`0032-variable-amount-skus.md` (MADR template): why the amount lives on the
order line rather than as `qty` or a separate module, and why the margin lives
in the rate instead of a percentage.

- [ ] **Step 2: Write the runbook**

`waxpeer-troubleshooting.md`: how to read a stuck top-up (`GET /v1/steam-topup?custom_id=`),
what each status means for the customer's money, what to do about
`needs_reconciliation` (the `error` case: we refunded the customer, Waxpeer has
not refunded us — open a ticket with the pay id), how to top up our Waxpeer
balance, and what a `give_amount` shortfall alert means (a supplier fee
appeared: set `WAXPEER_FEE_RATE` and redeploy).

- [ ] **Step 3: Module README and map**

`pricing/README.md` documents the trust gate and its four settings. Add the
`pricing` module to `docs/architecture/module-map.md`.

- [ ] **Step 4: Commit**

```bash
git add docs apps/api/src/yupay/modules/pricing/README.md
git commit -m "docs: variable-amount SKUs, pricing gate, Waxpeer runbook"
```

---

## Final verification

- [ ] `cd apps/api && uv run pytest tests/unit tests/integration tests/contract -q` — all pass
- [ ] `uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps` — clean
- [ ] `pnpm exec turbo run lint typecheck test` — clean
- [ ] `pnpm exec prettier --check .` — clean (repo-wide, not just touched files)
- [ ] `make gen-api` leaves no diff
- [ ] Manual: seed, open the Steam product, buy $1 against the real Waxpeer key
      in a scratch environment, confirm the wallet is credited and the order
      reaches `delivered`
