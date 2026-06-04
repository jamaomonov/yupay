# Admin Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/analytics` admin page (two tabs — Бизнес & Операционка — with a 7/30/90-day selector) backed by two range-parameterised aggregation endpoints in the `stats` module.

**Architecture:** Extend the existing `stats` module with two read-only endpoints that run indexed SQL aggregations and cache results in Redis (TTL 300s). The admin SPA renders the data with `recharts` charts, KPI cards, and existing `DataTable`s. Margin is approximate (current `sku.cost_usdt`). No new DB tables.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 async · Pydantic v2 · Redis · pytest+testcontainers (API). React 19 · React Router 7 · TanStack Query v5 · recharts · Tailwind v4 (admin).

**Spec:** `docs/superpowers/specs/2026-06-04-analytics-dashboard-design.md`
**Branch:** `main` (per user instruction).

---

## Reference facts (verified — use verbatim)

- `stats` module files: `apps/api/src/yupay/modules/stats/{routes,service,schemas,api}.py`. Admin router `admin_router = APIRouter(prefix="/admin/stats", dependencies=[Depends(require_admin)])` mounted already. Deps: `from yupay.api.v1.deps import db_session`, `from yupay.modules.admin.api import require_admin`, `from yupay.modules.users.models import User`.
- Service pattern (`stats/service.py`): aggregate `select(func.count())…`, `func.date_trunc("day", col)`, `func.sum(col).filter(<predicate>)`, `case((cond, 1), else_=0)`; `from yupay.core.clock import now`; money read as `Decimal(str(x or 0))`; zero-filled day series — copy the dict-by-date + fixed-width fill approach from `_orders_last_7_days`.
- Redis: `from yupay.core.redis import get_redis` → `Redis` (redis.asyncio). Reference cache pattern: `apps/api/src/yupay/modules/fx/cache.py`. Use `await r.get(key)` / `await r.set(key, value, ex=300)`; serialise with `payload.model_dump_json()` and rebuild with `Model.model_validate_json(raw)`.
- Model fields (verified):
  - `Order`: `id, user_id, guest_email, status, currency, total_usd, total_charged, created_at, paid_at, fulfilled_at, delivered_at, cancelled_at, expires_at`. Paid-like statuses: `("paid","fulfilling","fulfilled","delivered")`. Terminal-fail: `("cancelled","expired")`; plus `refunded`.
  - `OrderItem`: `order_id, sku_id, qty, unit_price_usd`.
  - `Sku`: `id, product_id, sku_code, price_usd, cost_usdt` (nullable). `Product`: `id, brand_id, slug`. `Brand`: `id, slug`.
  - `Payment`: `provider, status` (`pending|succeeded|failed`), `amount, currency, created_at, succeeded_at`. `PaymentWebhook`: `provider, signature_ok, processed_at, received_at`.
  - `FulfillmentTask`: `supplier, status` (`pending|in_progress|succeeded|failed|cancelled`), `attempts_count, created_at, succeeded_at, next_attempt_at, completed_by`.
  - `User`: `id, created_at, locale, deleted_at`. Guest orders = `Order.user_id IS NULL` (have `guest_email`).
  - `SupplierPriceHistory`: `sku_id, supplier_slug, cost_usdt, previous_cost_usdt, captured_at`. `InventoryCode`: `sku_id, state, expires_at`.
- Admin SPA: router `apps/admin/src/app/router.tsx`, shell `apps/admin/src/app/Layout.tsx`, existing 24h page `apps/admin/src/routes/Dashboard.tsx`. Components: `@/components/{DataTable,PageHeader,Spinner→States,Toast}`, `@yupay/ui` `Button`. API client: `apiGet` from `@/lib/api`; query keys in `@/lib/queryKeys.ts`. No i18n (Russian strings). `recharts` is NOT yet a dependency.
- Next ADR number: **0025**. `docs/architecture/cache-keys.md` exists.

### Scoping conventions (apply consistently)
- `range` → `since`: `7d→7`, `30d→30`, `90d→90` days; `since = now() - timedelta(days=N)`.
- **Revenue / margin** scoped by `paid_at >= since` AND `status IN paid_like` (money that landed in the window; paid-like guarantees `paid_at` non-null).
- **Funnel / customers / payments / fulfilment / supplier_cost** scoped by `created_at >= since` (`captured_at >= since` for supplier_cost).
- All money reported in **USD** (`total_usd` for orders, `amount` for payments). Currency breakdown uses `total_charged` grouped by `currency`.

---

## File structure

**API**
- Modify `apps/api/src/yupay/modules/stats/schemas.py` — analytics DTOs + `AnalyticsRange`.
- Modify `apps/api/src/yupay/modules/stats/service.py` — `build_business_analytics`, `build_ops_analytics` + helpers.
- Modify `apps/api/src/yupay/modules/stats/routes.py` — two endpoints + Redis cache.
- Create `apps/api/tests/integration/test_stats_analytics.py`.

**Admin**
- Modify `apps/admin/package.json` — add `recharts`.
- Modify `apps/admin/src/lib/queryKeys.ts` — `analyticsBusiness(range)`, `analyticsOps(range)`.
- Create `apps/admin/src/features/analytics/types.ts`.
- Create `apps/admin/src/features/analytics/charts/{LineTrend,BarBreakdown,DonutShare}.tsx`, `KpiCard.tsx`, `FunnelBars.tsx`.
- Create `apps/admin/src/features/analytics/{AnalyticsPage,BusinessTab,OpsTab}.tsx`.
- Modify `apps/admin/src/app/router.tsx`, `apps/admin/src/app/Layout.tsx`.

**Docs**
- Create `docs/decisions/0025-analytics-dashboard.md`; modify `docs/architecture/cache-keys.md`, `docs/architecture/module-map.md`; regenerate `docs/api/openapi.json`.

---

## Task 1: Analytics schemas + range enum

**Files:** Modify `apps/api/src/yupay/modules/stats/schemas.py`; Test `apps/api/tests/unit/test_stats_analytics_schemas.py` (create).

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/unit/test_stats_analytics_schemas.py`:
```python
"""Unit tests for analytics schema range parsing."""

from __future__ import annotations

import pytest
from yupay.modules.stats.schemas import AnalyticsRange, range_to_days


def test_range_values() -> None:
    assert {r.value for r in AnalyticsRange} == {"7d", "30d", "90d"}


@pytest.mark.parametrize(("r", "days"), [("7d", 7), ("30d", 30), ("90d", 90)])
def test_range_to_days(r: str, days: int) -> None:
    assert range_to_days(AnalyticsRange(r)) == days
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd apps/api && uv run pytest tests/unit/test_stats_analytics_schemas.py -v`
Expected: ImportError (`AnalyticsRange` not defined).

- [ ] **Step 3: Add schemas**

Append to `apps/api/src/yupay/modules/stats/schemas.py` (it already imports `from pydantic import BaseModel`; add `from enum import Enum`, `from datetime import date, datetime`, `from decimal import Decimal` if not present):
```python
class AnalyticsRange(str, Enum):
    """Selectable analytics window."""

    D7 = "7d"
    D30 = "30d"
    D90 = "90d"


def range_to_days(r: AnalyticsRange) -> int:
    """Map a range enum to its day count."""
    return {AnalyticsRange.D7: 7, AnalyticsRange.D30: 30, AnalyticsRange.D90: 90}[r]


# ---- business tab ----

class RevenuePoint(BaseModel):
    date: date
    revenue_usd: Decimal
    orders: int


class FunnelOut(BaseModel):
    created: int
    paid: int
    fulfilling: int
    delivered: int
    cancelled: int
    expired: int
    refunded: int
    payment_conversion_pct: float


class BrandRevenueOut(BaseModel):
    slug: str
    revenue_usd: Decimal
    units: int
    margin_usd: Decimal | None


class SkuRevenueOut(BaseModel):
    sku_code: str
    revenue_usd: Decimal
    units: int
    margin_usd: Decimal | None


class LocaleCountOut(BaseModel):
    locale: str
    users: int


class NewUsersPoint(BaseModel):
    date: date
    users: int


class BusinessSummaryOut(BaseModel):
    gmv_usd: Decimal
    orders: int
    paid_orders: int
    delivered_orders: int
    aov_usd: Decimal
    fx_pnl_usd: Decimal
    gross_margin_usd: Decimal
    margin_pct: float
    margin_approx: bool
    margin_unknown_units: int


class CustomersOut(BaseModel):
    new_users_series: list[NewUsersPoint]
    guest_orders: int
    registered_orders: int
    repeat_rate_pct: float
    top_locales: list[LocaleCountOut]


class BusinessAnalyticsOut(BaseModel):
    generated_at: datetime
    range: AnalyticsRange
    summary: BusinessSummaryOut
    revenue_series: list[RevenuePoint]
    funnel: FunnelOut
    top_brands: list[BrandRevenueOut]
    top_skus: list[SkuRevenueOut]
    customers: CustomersOut


# ---- ops tab ----

class ProviderStatOut(BaseModel):
    provider: str
    count: int
    volume_usd: Decimal
    success_rate_pct: float


class SupplierStatOut(BaseModel):
    supplier: str
    total: int
    success_rate_pct: float
    avg_seconds: float | None
    manual_count: int
    avg_attempts: float


class LowStockOut(BaseModel):
    sku_code: str
    available: int


class CostChangeOut(BaseModel):
    sku_code: str
    supplier_slug: str
    cost_usdt: Decimal
    previous_cost_usdt: Decimal | None
    captured_at: datetime


class OpsAnalyticsOut(BaseModel):
    generated_at: datetime
    range: AnalyticsRange
    payments: list[ProviderStatOut]
    stuck_pending: int
    webhook_unhealthy: int
    fulfillment: list[SupplierStatOut]
    stuck_tasks: int
    low_stock: list[LowStockOut]
    expiring_soon: int
    supplier_cost: list[CostChangeOut]
```
Add the new public names to the module's `__all__` if one exists.

- [ ] **Step 4: Run, expect PASS**

Run: `cd apps/api && uv run pytest tests/unit/test_stats_analytics_schemas.py -v` → 4 passed.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/yupay/modules/stats/schemas.py apps/api/tests/unit/test_stats_analytics_schemas.py
git commit -m "feat(stats): analytics DTOs + range enum"
```

---

## Task 2: Business analytics service

**Files:** Modify `apps/api/src/yupay/modules/stats/service.py`; Test `apps/api/tests/integration/test_stats_analytics.py` (create).

- [ ] **Step 1: Write the failing integration test**

Create `apps/api/tests/integration/test_stats_analytics.py`:
```python
"""Integration tests for analytics aggregation services."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand, BrandTranslation, Category, CategoryTranslation, Product, ProductTranslation, Sku,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.stats import service as svc
from yupay.modules.stats.schemas import AnalyticsRange

pytestmark = pytest.mark.asyncio


async def _seed_catalog(db: AsyncSession) -> tuple[str, str]:
    cat = Category(id=new_id(), slug="games", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug="pubg", category_id=cat.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name="PUBG")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug="pubg-uc", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="PUBG UC")]
    db.add(product)
    await db.flush()
    sku_with = Sku(id=new_id(), product_id=product.id, sku_code="pubg-60",
                   price_usd=Decimal("1.00"), cost_usdt=Decimal("0.60"))
    sku_no = Sku(id=new_id(), product_id=product.id, sku_code="pubg-300",
                 price_usd=Decimal("5.00"), cost_usdt=None)
    db.add_all([sku_with, sku_no])
    await db.flush()
    return sku_with.id, sku_no.id


async def _paid_order(db: AsyncSession, *, sku_id: str, qty: int, unit: str, paid_ago_days: int) -> None:
    moment = now() - timedelta(days=paid_ago_days)
    order = Order(
        id=new_id(), user_id=None, guest_email="g@example.com", status="delivered",
        currency="USD", total_usd=Decimal(unit) * qty, total_charged=Decimal(unit) * qty,
        created_at=moment, paid_at=moment, delivered_at=moment,
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(id=new_id(), order_id=order.id, sku_id=sku_id, qty=qty,
                     unit_price_usd=Decimal(unit)))
    await db.flush()


async def test_business_summary_and_margin_approx(db_session: AsyncSession) -> None:
    sku_with, sku_no = await _seed_catalog(db_session)
    # 2 units of the cost-known SKU @1.00 (cost 0.60) + 1 unit of cost-unknown @5.00
    await _paid_order(db_session, sku_id=sku_with, qty=2, unit="1.00", paid_ago_days=1)
    await _paid_order(db_session, sku_id=sku_no, qty=1, unit="5.00", paid_ago_days=2)

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    assert out.summary.orders == 2
    assert out.summary.gmv_usd == Decimal("7.00")  # 2.00 + 5.00
    # margin only over cost-known revenue: revenue 2.00, cost 1.20 → margin 0.80
    assert out.summary.gross_margin_usd == Decimal("0.80")
    assert out.summary.margin_approx is True
    assert out.summary.margin_unknown_units == 1
    # AOV = gmv / paid orders
    assert out.summary.aov_usd == Decimal("3.50")
    brands = {b.slug: b for b in out.top_brands}
    assert brands["pubg"].units == 3


async def test_range_filtering(db_session: AsyncSession) -> None:
    sku_with, _ = await _seed_catalog(db_session)
    await _paid_order(db_session, sku_id=sku_with, qty=1, unit="1.00", paid_ago_days=2)
    await _paid_order(db_session, sku_id=sku_with, qty=1, unit="1.00", paid_ago_days=40)
    out7 = await svc.build_business_analytics(db_session, r=AnalyticsRange.D7)
    out90 = await svc.build_business_analytics(db_session, r=AnalyticsRange.D90)
    assert out7.summary.orders == 1
    assert out90.summary.orders == 2
```

- [ ] **Step 2: Run, expect FAIL** (`build_business_analytics` missing)

Run: `cd apps/api && uv run pytest tests/integration/test_stats_analytics.py -v`

- [ ] **Step 3: Implement business service**

In `apps/api/src/yupay/modules/stats/service.py` add these imports at the top (extend existing import lines, don't duplicate): `from datetime import date as date_cls`, `from yupay.modules.catalog.models import Brand, Product, Sku`, `from yupay.modules.orders.models import OrderItem`, `from yupay.modules.users.models import User`, and from schemas import the new analytics models + `AnalyticsRange, range_to_days`. Then append:

```python
_PAID_LIKE = ("paid", "fulfilling", "fulfilled", "delivered")


async def build_business_analytics(db: AsyncSession, *, r: AnalyticsRange) -> BusinessAnalyticsOut:
    """Business tab: revenue, margin (approx), funnel, product mix, customers."""
    moment = now()
    since = moment - timedelta(days=range_to_days(r))

    summary = await _business_summary(db, since)
    revenue_series = await _revenue_series(db, since)
    funnel = await _funnel(db, since)
    top_brands = await _top_brands(db, since)
    top_skus = await _top_skus(db, since)
    customers = await _customers(db, since)

    return BusinessAnalyticsOut(
        generated_at=moment, range=r, summary=summary, revenue_series=revenue_series,
        funnel=funnel, top_brands=top_brands, top_skus=top_skus, customers=customers,
    )


async def _business_summary(db: AsyncSession, since: datetime) -> BusinessSummaryOut:
    # Orders + GMV + FX P&L over paid-like orders paid in window.
    base = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_usd), 0),
        func.coalesce(func.sum(Order.total_charged - Order.total_usd), 0),
        func.count(Order.id).filter(Order.status == "delivered"),
    ).where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
    paid_orders, gmv, fx_pnl, delivered = (await db.execute(base)).one()
    paid_orders = int(paid_orders or 0)
    gmv = Decimal(str(gmv or 0))

    # Total orders created (for "orders" headline) in same window by created_at.
    total_created = int(
        (await db.execute(
            select(func.count(Order.id)).where(Order.created_at >= since)
        )).scalar_one() or 0
    )

    # Margin (approx): join items→sku, only rows with cost_usdt known.
    m = select(
        func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd).filter(Sku.cost_usdt.isnot(None)), 0),
        func.coalesce(func.sum(OrderItem.qty * Sku.cost_usdt).filter(Sku.cost_usdt.isnot(None)), 0),
        func.coalesce(func.sum(OrderItem.qty).filter(Sku.cost_usdt.is_(None)), 0),
    ).select_from(OrderItem).join(Order, Order.id == OrderItem.order_id).join(
        Sku, Sku.id == OrderItem.sku_id
    ).where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
    known_rev, known_cost, unknown_units = (await db.execute(m)).one()
    known_rev = Decimal(str(known_rev or 0))
    known_cost = Decimal(str(known_cost or 0))
    margin = known_rev - known_cost
    margin_pct = float(margin / known_rev * 100) if known_rev > 0 else 0.0
    aov = (gmv / paid_orders) if paid_orders else Decimal("0")

    return BusinessSummaryOut(
        gmv_usd=gmv, orders=total_created, paid_orders=paid_orders, delivered_orders=int(delivered or 0),
        aov_usd=aov.quantize(Decimal("0.01")) if paid_orders else Decimal("0"),
        fx_pnl_usd=Decimal(str(fx_pnl or 0)), gross_margin_usd=margin, margin_pct=round(margin_pct, 2),
        margin_approx=True, margin_unknown_units=int(unknown_units or 0),
    )


async def _revenue_series(db: AsyncSession, since: datetime) -> list[RevenuePoint]:
    day = func.date_trunc("day", Order.paid_at)
    stmt = (
        select(day.label("d"), func.coalesce(func.sum(Order.total_usd), 0).label("rev"),
               func.count(Order.id).label("c"))
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(day).order_by(day)
    )
    rows = (await db.execute(stmt)).all()
    return [
        RevenuePoint(date=d.date() if hasattr(d, "date") else d,
                     revenue_usd=Decimal(str(rev or 0)), orders=int(c or 0))
        for d, rev, c in rows if d is not None
    ]


async def _funnel(db: AsyncSession, since: datetime) -> FunnelOut:
    stmt = select(Order.status, func.count()).where(Order.created_at >= since).group_by(Order.status)
    counts = {s: int(c) for s, c in (await db.execute(stmt)).all()}
    created = sum(counts.values())
    paid = sum(counts.get(s, 0) for s in _PAID_LIKE)
    conv = (paid / created * 100) if created else 0.0
    return FunnelOut(
        created=created, paid=counts.get("paid", 0), fulfilling=counts.get("fulfilling", 0),
        delivered=counts.get("delivered", 0), cancelled=counts.get("cancelled", 0),
        expired=counts.get("expired", 0), refunded=counts.get("refunded", 0),
        payment_conversion_pct=round(conv, 2),
    )


async def _top_brands(db: AsyncSession, since: datetime) -> list[BrandRevenueOut]:
    stmt = (
        select(
            Brand.slug,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            func.coalesce(func.sum(OrderItem.qty * Sku.cost_usdt).filter(Sku.cost_usdt.isnot(None)), 0),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(Brand.slug)
        .order_by(func.sum(OrderItem.qty * OrderItem.unit_price_usd).desc())
        .limit(10)
    )
    out: list[BrandRevenueOut] = []
    for slug, rev, units, cost in (await db.execute(stmt)).all():
        rev_d = Decimal(str(rev or 0))
        out.append(BrandRevenueOut(slug=slug, revenue_usd=rev_d, units=int(units or 0),
                                   margin_usd=(rev_d - Decimal(str(cost or 0)))))
    return out


async def _top_skus(db: AsyncSession, since: datetime) -> list[SkuRevenueOut]:
    stmt = (
        select(
            Sku.sku_code,
            func.coalesce(func.sum(OrderItem.qty * OrderItem.unit_price_usd), 0),
            func.coalesce(func.sum(OrderItem.qty), 0),
            func.coalesce(func.sum(OrderItem.qty * Sku.cost_usdt).filter(Sku.cost_usdt.isnot(None)), 0),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .where(Order.paid_at >= since, Order.status.in_(_PAID_LIKE))
        .group_by(Sku.sku_code)
        .order_by(func.sum(OrderItem.qty * OrderItem.unit_price_usd).desc())
        .limit(10)
    )
    out: list[SkuRevenueOut] = []
    for code, rev, units, cost in (await db.execute(stmt)).all():
        rev_d = Decimal(str(rev or 0))
        out.append(SkuRevenueOut(sku_code=code, revenue_usd=rev_d, units=int(units or 0),
                                 margin_usd=(rev_d - Decimal(str(cost or 0)))))
    return out


async def _customers(db: AsyncSession, since: datetime) -> CustomersOut:
    day = func.date_trunc("day", User.created_at)
    new_rows = (await db.execute(
        select(day.label("d"), func.count()).where(User.created_at >= since).group_by(day).order_by(day)
    )).all()
    new_series = [NewUsersPoint(date=d.date() if hasattr(d, "date") else d, users=int(c))
                  for d, c in new_rows if d is not None]

    guest = int((await db.execute(
        select(func.count(Order.id)).where(Order.created_at >= since, Order.user_id.is_(None))
    )).scalar_one() or 0)
    registered = int((await db.execute(
        select(func.count(Order.id)).where(Order.created_at >= since, Order.user_id.isnot(None))
    )).scalar_one() or 0)

    # repeat rate: of distinct users with >=1 order in window, share with >=2.
    per_user = (await db.execute(
        select(Order.user_id, func.count(Order.id))
        .where(Order.created_at >= since, Order.user_id.isnot(None))
        .group_by(Order.user_id)
    )).all()
    total_users = len(per_user)
    repeat = sum(1 for _u, c in per_user if int(c) >= 2)
    repeat_pct = round(repeat / total_users * 100, 2) if total_users else 0.0

    locale_rows = (await db.execute(
        select(User.locale, func.count()).where(User.created_at >= since)
        .group_by(User.locale).order_by(func.count().desc()).limit(5)
    )).all()
    locales = [LocaleCountOut(locale=loc or "—", users=int(c)) for loc, c in locale_rows]

    return CustomersOut(new_users_series=new_series, guest_orders=guest, registered_orders=registered,
                        repeat_rate_pct=repeat_pct, top_locales=locales)
```
Add `build_business_analytics` to `__all__` if present.

- [ ] **Step 4: Run, expect PASS** (2 passed)

Run: `cd apps/api && uv run pytest tests/integration/test_stats_analytics.py -v`

- [ ] **Step 5: Lint/type**

Run: `cd apps/api && uv run ruff check src/yupay/modules/stats && cd /Users/macbook_uz/Projects/yupay && uv run mypy apps/api/src/yupay/modules/stats/service.py`
Fix issues (no rule-disabling on hand-written code).

- [ ] **Step 6: Commit**
```bash
git add apps/api/src/yupay/modules/stats/service.py apps/api/tests/integration/test_stats_analytics.py
git commit -m "feat(stats): business analytics aggregations (revenue, margin approx, funnel, mix, customers)"
```

---

## Task 3: Ops analytics service

**Files:** Modify `apps/api/src/yupay/modules/stats/service.py`; append tests to `apps/api/tests/integration/test_stats_analytics.py`.

- [ ] **Step 1: Append failing tests**

Add to `apps/api/tests/integration/test_stats_analytics.py` (imports: `from yupay.modules.payments.models import Payment`, `from yupay.modules.fulfillment.models import FulfillmentTask`):
```python
async def test_ops_payments_and_fulfillment(db_session: AsyncSession) -> None:
    moment = now()
    db_session.add_all([
        Payment(id=new_id(), order_id=new_id(), provider="octo", status="succeeded",
                amount=Decimal("10.00"), currency="USD", created_at=moment, succeeded_at=moment),
        Payment(id=new_id(), order_id=new_id(), provider="octo", status="failed",
                amount=Decimal("10.00"), currency="USD", created_at=moment),
        Payment(id=new_id(), order_id=new_id(), provider="wallet", status="succeeded",
                amount=Decimal("3.00"), currency="USD", created_at=moment, succeeded_at=moment),
    ])
    db_session.add_all([
        FulfillmentTask(id=new_id(), order_id=new_id(), order_item_id=new_id(), supplier="g2b",
                        status="succeeded", attempts_count=1, created_at=moment - timedelta(seconds=30),
                        succeeded_at=moment),
        FulfillmentTask(id=new_id(), order_id=new_id(), order_item_id=new_id(), supplier="g2b",
                        status="failed", attempts_count=3, created_at=moment),
    ])
    await db_session.flush()

    out = await svc.build_ops_analytics(db_session, r=AnalyticsRange.D30)
    octo = next(p for p in out.payments if p.provider == "octo")
    assert octo.count == 2
    assert octo.success_rate_pct == 50.0
    g2b = next(f for f in out.fulfillment if f.supplier == "g2b")
    assert g2b.total == 2
    assert g2b.success_rate_pct == 50.0
    assert g2b.avg_attempts == 2.0
```

- [ ] **Step 2: Run, expect FAIL** (`build_ops_analytics` missing)

Run: `cd apps/api && uv run pytest tests/integration/test_stats_analytics.py -k ops -v`

- [ ] **Step 3: Implement ops service**

In `apps/api/src/yupay/modules/stats/service.py` add imports `from yupay.modules.payments.models import Payment, PaymentWebhook`, `from yupay.modules.integrations.models import SupplierPriceHistory`. (`FulfillmentTask`, `InventoryCode` already imported.) Append:
```python
async def build_ops_analytics(db: AsyncSession, *, r: AnalyticsRange) -> OpsAnalyticsOut:
    """Ops tab: payments, fulfilment, inventory, supplier cost movements."""
    moment = now()
    since = moment - timedelta(days=range_to_days(r))

    payments = await _payment_stats(db, since)
    stuck_pending = await _count_stuck_payments(db, moment - _STUCK_PAYMENT_AFTER)
    webhook_unhealthy = await _webhook_unhealthy(db, since)
    fulfillment = await _fulfillment_stats(db, since)
    stuck_tasks = await _stuck_tasks(db, moment)
    low_stock = await _low_stock(db)
    expiring_soon = await _expiring_soon(db, moment)
    supplier_cost = await _supplier_cost_changes(db, since)

    return OpsAnalyticsOut(
        generated_at=moment, range=r, payments=payments, stuck_pending=stuck_pending,
        webhook_unhealthy=webhook_unhealthy, fulfillment=fulfillment, stuck_tasks=stuck_tasks,
        low_stock=low_stock, expiring_soon=expiring_soon, supplier_cost=supplier_cost,
    )


async def _payment_stats(db: AsyncSession, since: datetime) -> list[ProviderStatOut]:
    stmt = (
        select(
            Payment.provider,
            func.count(),
            func.coalesce(func.sum(Payment.amount).filter(Payment.status == "succeeded"), 0),
            func.count().filter(Payment.status == "succeeded"),
        )
        .where(Payment.created_at >= since)
        .group_by(Payment.provider)
        .order_by(func.count().desc())
    )
    out: list[ProviderStatOut] = []
    for provider, total, vol, ok in (await db.execute(stmt)).all():
        total = int(total or 0)
        rate = round(int(ok or 0) / total * 100, 2) if total else 0.0
        out.append(ProviderStatOut(provider=provider, count=total,
                                   volume_usd=Decimal(str(vol or 0)), success_rate_pct=rate))
    return out


async def _webhook_unhealthy(db: AsyncSession, since: datetime) -> int:
    from sqlalchemy import or_

    stmt = select(func.count()).select_from(PaymentWebhook).where(
        PaymentWebhook.received_at >= since,
        or_(PaymentWebhook.signature_ok.is_(False), PaymentWebhook.processed_at.is_(None)),
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _fulfillment_stats(db: AsyncSession, since: datetime) -> list[SupplierStatOut]:
    secs = func.extract("epoch", FulfillmentTask.succeeded_at - FulfillmentTask.created_at)
    stmt = (
        select(
            FulfillmentTask.supplier,
            func.count(),
            func.count().filter(FulfillmentTask.status == "succeeded"),
            func.avg(secs).filter(FulfillmentTask.status == "succeeded"),
            func.count().filter(FulfillmentTask.completed_by.isnot(None)),
            func.coalesce(func.avg(FulfillmentTask.attempts_count), 0),
        )
        .where(FulfillmentTask.created_at >= since)
        .group_by(FulfillmentTask.supplier)
        .order_by(func.count().desc())
    )
    out: list[SupplierStatOut] = []
    for supplier, total, ok, avg_sec, manual, avg_att in (await db.execute(stmt)).all():
        total = int(total or 0)
        rate = round(int(ok or 0) / total * 100, 2) if total else 0.0
        out.append(SupplierStatOut(
            supplier=supplier, total=total, success_rate_pct=rate,
            avg_seconds=round(float(avg_sec), 1) if avg_sec is not None else None,
            manual_count=int(manual or 0), avg_attempts=round(float(avg_att or 0), 2),
        ))
    return out


async def _stuck_tasks(db: AsyncSession, moment: datetime) -> int:
    stmt = select(func.count()).select_from(FulfillmentTask).where(
        FulfillmentTask.status.in_(("pending", "in_progress")),
        FulfillmentTask.next_attempt_at.isnot(None),
        FulfillmentTask.next_attempt_at < moment,
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _low_stock(db: AsyncSession) -> list[LowStockOut]:
    avail = func.sum(case((InventoryCode.state == "available", 1), else_=0)).label("a")
    stmt = (
        select(Sku.sku_code, avail)
        .select_from(InventoryCode)
        .join(Sku, Sku.id == InventoryCode.sku_id)
        .group_by(Sku.sku_code)
        .having(avail < _LOW_STOCK_THRESHOLD)
        .order_by(avail)
        .limit(20)
    )
    return [LowStockOut(sku_code=code, available=int(a or 0)) for code, a in (await db.execute(stmt)).all()]


async def _expiring_soon(db: AsyncSession, moment: datetime) -> int:
    stmt = select(func.count()).select_from(InventoryCode).where(
        InventoryCode.state == "available",
        InventoryCode.expires_at.isnot(None),
        InventoryCode.expires_at < moment + timedelta(days=7),
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _supplier_cost_changes(db: AsyncSession, since: datetime) -> list[CostChangeOut]:
    stmt = (
        select(Sku.sku_code, SupplierPriceHistory.supplier_slug, SupplierPriceHistory.cost_usdt,
               SupplierPriceHistory.previous_cost_usdt, SupplierPriceHistory.captured_at)
        .select_from(SupplierPriceHistory)
        .join(Sku, Sku.id == SupplierPriceHistory.sku_id)
        .where(SupplierPriceHistory.captured_at >= since)
        .order_by(SupplierPriceHistory.captured_at.desc())
        .limit(20)
    )
    return [
        CostChangeOut(sku_code=code, supplier_slug=slug, cost_usdt=Decimal(str(cost)),
                      previous_cost_usdt=Decimal(str(prev)) if prev is not None else None, captured_at=cap)
        for code, slug, cost, prev, cap in (await db.execute(stmt)).all()
    ]
```
Add `build_ops_analytics` to `__all__` if present.

- [ ] **Step 4: Run, expect PASS** (3 passed total)

Run: `cd apps/api && uv run pytest tests/integration/test_stats_analytics.py -v`

- [ ] **Step 5: Lint/type** (same commands as Task 2 Step 5).

- [ ] **Step 6: Commit**
```bash
git add apps/api/src/yupay/modules/stats/service.py apps/api/tests/integration/test_stats_analytics.py
git commit -m "feat(stats): ops analytics aggregations (payments, fulfilment, inventory, cost changes)"
```

---

## Task 4: Endpoints + Redis cache

**Files:** Modify `apps/api/src/yupay/modules/stats/routes.py`; append endpoint tests to `apps/api/tests/integration/test_stats_analytics.py`.

- [ ] **Step 1: Append failing endpoint tests**

Add to the test file (auth helpers `_login_admin` — copy from `apps/api/tests/integration/test_integrations_mapping.py` if a shared fixture isn't available; the import endpoints test in `test_g2b_import.py` shows the exact copy). Use the `integration_client` fixture (it swaps the DB engine — confirm by reading `tests/integration/conftest.py`):
```python
from httpx import AsyncClient


async def test_business_endpoint(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _login_admin(integration_client, db_session)  # helper copied per above
    r = await integration_client.get(
        "/api/v1/admin/stats/analytics/business?range=30d",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["range"] == "30d"
    assert "summary" in r.json()


async def test_ops_endpoint_requires_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/stats/analytics/ops")
    assert r.status_code in (401, 403)


async def test_invalid_range_rejected(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _login_admin(integration_client, db_session)
    r = await integration_client.get(
        "/api/v1/admin/stats/analytics/business?range=bogus",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run, expect FAIL** (404)

Run: `cd apps/api && uv run pytest tests/integration/test_stats_analytics.py -k endpoint -v`

- [ ] **Step 3: Add routes + cache**

In `apps/api/src/yupay/modules/stats/routes.py`: add to imports `from yupay.modules.stats.schemas import AnalyticsRange, BusinessAnalyticsOut, OpsAnalyticsOut` and `from yupay.core.redis import get_redis`. Add a small cache helper + two routes:
```python
_ANALYTICS_TTL = 300


async def _cached(key: str, model: type, builder):  # builder: async () -> BaseModel
    """Return a cached analytics payload or compute, cache (TTL 300s), and return.

    Best-effort: Redis errors fall back to a live computation so the dashboard
    never 500s on a cache hiccup.
    """
    r = get_redis()
    try:
        raw = await r.get(key)
        if raw is not None:
            return model.model_validate_json(raw)
    except Exception:  # noqa: BLE001 -- cache is best-effort
        pass
    payload = await builder()
    try:
        await r.set(key, payload.model_dump_json(), ex=_ANALYTICS_TTL)
    except Exception:  # noqa: BLE001
        pass
    return payload


@admin_router.get(
    "/analytics/business",
    response_model=BusinessAnalyticsOut,
    summary="Business analytics (revenue, margin, funnel, mix, customers)",
)
async def analytics_business(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    range: AnalyticsRange = AnalyticsRange.D30,
) -> BusinessAnalyticsOut:
    return await _cached(
        f"stats:analytics:business:{range.value}",
        BusinessAnalyticsOut,
        lambda: svc.build_business_analytics(db, r=range),
    )


@admin_router.get(
    "/analytics/ops",
    response_model=OpsAnalyticsOut,
    summary="Operational analytics (payments, fulfilment, inventory)",
)
async def analytics_ops(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    range: AnalyticsRange = AnalyticsRange.D30,
) -> OpsAnalyticsOut:
    return await _cached(
        f"stats:analytics:ops:{range.value}",
        OpsAnalyticsOut,
        lambda: svc.build_ops_analytics(db, r=range),
    )
```
Note: FastAPI maps an unknown `range` value to 422 automatically because `AnalyticsRange` is an enum. The cache key embeds only the validated `range.value`.

- [ ] **Step 4: Run, expect PASS** (full file green)

Run: `cd apps/api && uv run pytest tests/integration/test_stats_analytics.py -v`

- [ ] **Step 5: Lint/type**

Run: `cd apps/api && uv run ruff check src/yupay/modules/stats && cd /Users/macbook_uz/Projects/yupay && uv run mypy apps/api/src/yupay/modules/stats/routes.py`

- [ ] **Step 6: Commit**
```bash
git add apps/api/src/yupay/modules/stats/routes.py apps/api/tests/integration/test_stats_analytics.py
git commit -m "feat(stats): /admin/stats/analytics business+ops endpoints with Redis cache"
```

---

## Task 5: Regenerate OpenAPI + TS client

- [ ] **Step 1:** Run `make gen-api`. Expected: `docs/api/openapi.json` gains both `/admin/stats/analytics/...` paths; `grep -c "analytics/business" docs/api/openapi.json` ≥ 1.
- [ ] **Step 2:** Commit:
```bash
git add docs/api/openapi.json packages/api-client
git commit -m "build(api): regenerate OpenAPI for analytics endpoints"
```
(If `packages/api-client/src/generated` is gitignored, only `openapi.json` is staged — that's expected.)

---

## Task 6: Admin — recharts + query keys + types

**Files:** Modify `apps/admin/package.json`, `apps/admin/src/lib/queryKeys.ts`; Create `apps/admin/src/features/analytics/types.ts`.

- [ ] **Step 1: Add recharts**

Run: `pnpm --filter @yupay/admin add recharts` (pins a 2.x version into `apps/admin/package.json` + updates the lockfile).

- [ ] **Step 2: Query keys**

In `apps/admin/src/lib/queryKeys.ts`, inside the `qk` object (match the existing factory style), add:
```typescript
  analyticsBusiness: (range: string) => ["admin", "stats", "analytics", "business", range] as const,
  analyticsOps: (range: string) => ["admin", "stats", "analytics", "ops", range] as const,
```

- [ ] **Step 3: Types**

Create `apps/admin/src/features/analytics/types.ts` mirroring the backend DTOs (money/decimals arrive as JSON strings):
```typescript
export type AnalyticsRange = "7d" | "30d" | "90d";

export interface RevenuePoint { date: string; revenue_usd: string; orders: number; }
export interface FunnelOut {
  created: number; paid: number; fulfilling: number; delivered: number;
  cancelled: number; expired: number; refunded: number; payment_conversion_pct: number;
}
export interface BrandRevenue { slug: string; revenue_usd: string; units: number; margin_usd: string | null; }
export interface SkuRevenue { sku_code: string; revenue_usd: string; units: number; margin_usd: string | null; }
export interface LocaleCount { locale: string; users: number; }
export interface NewUsersPoint { date: string; users: number; }
export interface BusinessSummary {
  gmv_usd: string; orders: number; paid_orders: number; delivered_orders: number;
  aov_usd: string; fx_pnl_usd: string; gross_margin_usd: string; margin_pct: number;
  margin_approx: boolean; margin_unknown_units: number;
}
export interface Customers {
  new_users_series: NewUsersPoint[]; guest_orders: number; registered_orders: number;
  repeat_rate_pct: number; top_locales: LocaleCount[];
}
export interface BusinessAnalytics {
  generated_at: string; range: AnalyticsRange; summary: BusinessSummary;
  revenue_series: RevenuePoint[]; funnel: FunnelOut; top_brands: BrandRevenue[];
  top_skus: SkuRevenue[]; customers: Customers;
}
export interface ProviderStat { provider: string; count: number; volume_usd: string; success_rate_pct: number; }
export interface SupplierStat {
  supplier: string; total: number; success_rate_pct: number; avg_seconds: number | null;
  manual_count: number; avg_attempts: number;
}
export interface LowStock { sku_code: string; available: number; }
export interface CostChange {
  sku_code: string; supplier_slug: string; cost_usdt: string;
  previous_cost_usdt: string | null; captured_at: string;
}
export interface OpsAnalytics {
  generated_at: string; range: AnalyticsRange; payments: ProviderStat[]; stuck_pending: number;
  webhook_unhealthy: number; fulfillment: SupplierStat[]; stuck_tasks: number;
  low_stock: LowStock[]; expiring_soon: number; supplier_cost: CostChange[];
}
```

- [ ] **Step 4: Typecheck + commit**

Run: `pnpm --filter @yupay/admin exec tsc --noEmit` → 0 errors.
```bash
git add apps/admin/package.json pnpm-lock.yaml apps/admin/src/lib/queryKeys.ts apps/admin/src/features/analytics/types.ts
git commit -m "feat(admin): recharts dep + analytics query keys/types"
```

---

## Task 7: Admin — chart + KPI components

**Files:** Create `apps/admin/src/features/analytics/charts/{LineTrend,BarBreakdown,DonutShare}.tsx`, `KpiCard.tsx`, `FunnelBars.tsx`.

- [ ] **Step 1: KpiCard**

Create `apps/admin/src/features/analytics/KpiCard.tsx`:
```tsx
interface KpiCardProps {
  label: string;
  value: string;
  hint?: string;
}

export function KpiCard({ label, value, hint }: KpiCardProps) {
  return (
    <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
      <div className="text-[11px] uppercase tracking-wide text-[var(--text-tertiary)]">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-1 text-xs text-[var(--text-secondary)]">{hint}</div>}
    </div>
  );
}
```

- [ ] **Step 2: LineTrend (recharts wrapper)**

Create `apps/admin/src/features/analytics/charts/LineTrend.tsx`:
```tsx
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface LineTrendProps {
  data: { x: string; y: number }[];
  height?: number;
}

export function LineTrend({ data, height = 240 }: LineTrendProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
        <XAxis dataKey="x" tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} />
        <YAxis tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} width={48} />
        <Tooltip
          contentStyle={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Line type="monotone" dataKey="y" stroke="var(--accent)" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 3: BarBreakdown**

Create `apps/admin/src/features/analytics/charts/BarBreakdown.tsx`:
```tsx
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface BarBreakdownProps {
  data: { name: string; value: number }[];
  height?: number;
}

export function BarBreakdown({ data, height = 240 }: BarBreakdownProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} />
        <YAxis tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} width={48} />
        <Tooltip
          contentStyle={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Bar dataKey="value" fill="var(--accent)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 4: DonutShare**

Create `apps/admin/src/features/analytics/charts/DonutShare.tsx`:
```tsx
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const PALETTE = ["var(--accent)", "#6aa3ff", "#f4a261", "#9b8cff", "#4cc9a0", "#e07a8b"];

interface DonutShareProps {
  data: { name: string; value: number }[];
  height?: number;
}

export function DonutShare({ data, height = 240 }: DonutShareProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={56} outerRadius={88} paddingAngle={2}>
          {data.map((d, i) => (
            <Cell key={d.name} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 5: FunnelBars**

Create `apps/admin/src/features/analytics/FunnelBars.tsx`:
```tsx
import type { FunnelOut } from "./types";

export function FunnelBars({ funnel }: { funnel: FunnelOut }) {
  const stages: { label: string; n: number }[] = [
    { label: "Создано", n: funnel.created },
    { label: "Оплачено", n: funnel.paid },
    { label: "Выдаётся", n: funnel.fulfilling },
    { label: "Доставлено", n: funnel.delivered },
  ];
  const max = Math.max(1, funnel.created);
  return (
    <div className="space-y-2">
      {stages.map((s) => (
        <div key={s.label} className="flex items-center gap-3">
          <div className="w-24 text-xs text-[var(--text-secondary)]">{s.label}</div>
          <div className="h-6 flex-1 overflow-hidden rounded bg-[var(--bg-muted)]">
            <div className="h-full bg-[var(--accent)]" style={{ width: `${(s.n / max) * 100}%` }} />
          </div>
          <div className="w-12 text-right text-xs font-medium">{s.n}</div>
        </div>
      ))}
      <div className="text-xs text-[var(--text-tertiary)]">
        Конверсия в оплату: {funnel.payment_conversion_pct}%
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Typecheck + lint + commit**

Run: `pnpm --filter @yupay/admin exec tsc --noEmit && pnpm --filter @yupay/admin run lint` (0 errors; the new files 0 warnings). Then `pnpm exec prettier --write apps/admin/src/features/analytics/`.
```bash
git add apps/admin/src/features/analytics/KpiCard.tsx apps/admin/src/features/analytics/FunnelBars.tsx apps/admin/src/features/analytics/charts
git commit -m "feat(admin): analytics chart + KPI + funnel components"
```

---

## Task 8: Admin — AnalyticsPage + tabs + routing

**Files:** Create `apps/admin/src/features/analytics/{AnalyticsPage,BusinessTab,OpsTab}.tsx`; Modify `apps/admin/src/app/router.tsx`, `apps/admin/src/app/Layout.tsx`.

- [ ] **Step 1: BusinessTab**

Create `apps/admin/src/features/analytics/BusinessTab.tsx`. It receives the fetched payload and renders KPIs + charts + tables. Use `DataTable` for top brands/SKUs. (Format money from the string decimals with `Number(x).toLocaleString()`.)
```tsx
import { DataTable } from "@/components/DataTable";

import { DonutShare } from "./charts/DonutShare";
import { LineTrend } from "./charts/LineTrend";
import { FunnelBars } from "./FunnelBars";
import { KpiCard } from "./KpiCard";
import type { BusinessAnalytics } from "./types";

function usd(s: string): string {
  return `$${Number(s).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}`;
}

export function BusinessTab({ data }: { data: BusinessAnalytics }) {
  const s = data.summary;
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiCard label="GMV" value={usd(s.gmv_usd)} />
        <KpiCard label="Заказов" value={String(s.orders)} hint={`оплачено ${s.paid_orders}`} />
        <KpiCard label="Средний чек" value={usd(s.aov_usd)} />
        <KpiCard
          label="Маржа ≈"
          value={usd(s.gross_margin_usd)}
          hint={`${s.margin_pct}% · оценочно${s.margin_unknown_units ? ` · ${s.margin_unknown_units} ед. без cost` : ""}`}
        />
        <KpiCard label="FX P&L" value={usd(s.fx_pnl_usd)} />
      </div>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Выручка по дням</h3>
        <LineTrend data={data.revenue_series.map((p) => ({ x: p.date.slice(5), y: Number(p.revenue_usd) }))} />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Воронка</h3>
        <FunnelBars funnel={data.funnel} />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Топ бренды</h3>
          <DataTable
            rows={data.top_brands}
            rowKey={(b) => b.slug}
            ariaLabel="Топ бренды"
            columns={[
              { key: "slug", header: "Бренд", render: (b) => b.slug },
              { key: "rev", header: "Выручка", render: (b) => usd(b.revenue_usd) },
              { key: "units", header: "Штук", render: (b) => String(b.units) },
              { key: "margin", header: "Маржа ≈", render: (b) => (b.margin_usd ? usd(b.margin_usd) : "—") },
            ]}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Доли брендов</h3>
          <DonutShare data={data.top_brands.map((b) => ({ name: b.slug, value: Number(b.revenue_usd) }))} />
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Новые пользователи</h3>
          <LineTrend data={data.customers.new_users_series.map((p) => ({ x: p.date.slice(5), y: p.users }))} />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Гость vs зарегистрированный</h3>
          <DonutShare
            data={[
              { name: "Гость", value: data.customers.guest_orders },
              { name: "Зарегистр.", value: data.customers.registered_orders },
            ]}
          />
          <div className="mt-2 text-xs text-[var(--text-secondary)]">
            Повторные покупки: {data.customers.repeat_rate_pct}%
          </div>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: OpsTab**

Create `apps/admin/src/features/analytics/OpsTab.tsx`:
```tsx
import { DataTable } from "@/components/DataTable";

import { BarBreakdown } from "./charts/BarBreakdown";
import { KpiCard } from "./KpiCard";
import type { OpsAnalytics } from "./types";

function usd(s: string): string {
  return `$${Number(s).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}`;
}

export function OpsTab({ data }: { data: OpsAnalytics }) {
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Застрявшие платежи" value={String(data.stuck_pending)} />
        <KpiCard label="Проблемные вебхуки" value={String(data.webhook_unhealthy)} />
        <KpiCard label="Застрявшие задачи" value={String(data.stuck_tasks)} />
        <KpiCard label="Истекают коды (7д)" value={String(data.expiring_soon)} />
      </div>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Платежи по провайдерам</h3>
          <BarBreakdown data={data.payments.map((p) => ({ name: p.provider, value: p.count }))} />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Провайдеры — успех</h3>
          <DataTable
            rows={data.payments}
            rowKey={(p) => p.provider}
            ariaLabel="Платежи по провайдерам"
            columns={[
              { key: "p", header: "Провайдер", render: (p) => p.provider },
              { key: "n", header: "Транзакций", render: (p) => String(p.count) },
              { key: "v", header: "Объём", render: (p) => usd(p.volume_usd) },
              { key: "ok", header: "Success", render: (p) => `${p.success_rate_pct}%` },
            ]}
          />
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Фулфилмент по поставщикам</h3>
        <DataTable
          rows={data.fulfillment}
          rowKey={(f) => f.supplier}
          ariaLabel="Фулфилмент по поставщикам"
          columns={[
            { key: "s", header: "Поставщик", render: (f) => f.supplier },
            { key: "t", header: "Всего", render: (f) => String(f.total) },
            { key: "ok", header: "Success", render: (f) => `${f.success_rate_pct}%` },
            { key: "avg", header: "Ср. время", render: (f) => (f.avg_seconds != null ? `${f.avg_seconds}s` : "—") },
            { key: "m", header: "Вручную", render: (f) => String(f.manual_count) },
            { key: "att", header: "Ср. попыток", render: (f) => String(f.avg_attempts) },
          ]}
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Заканчивается на складе</h3>
          <DataTable
            rows={data.low_stock}
            rowKey={(l) => l.sku_code}
            ariaLabel="Низкие остатки"
            empty="Низких остатков нет"
            columns={[
              { key: "sku", header: "SKU", render: (l) => l.sku_code },
              { key: "a", header: "Доступно", render: (l) => String(l.available) },
            ]}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Изменения себестоимости</h3>
          <DataTable
            rows={data.supplier_cost}
            rowKey={(c) => `${c.sku_code}-${c.captured_at}`}
            ariaLabel="Изменения себестоимости"
            empty="Изменений нет"
            columns={[
              { key: "sku", header: "SKU", render: (c) => c.sku_code },
              { key: "sup", header: "Поставщик", render: (c) => c.supplier_slug },
              { key: "was", header: "Было", render: (c) => (c.previous_cost_usdt ? usd(c.previous_cost_usdt) : "—") },
              { key: "now", header: "Стало", render: (c) => usd(c.cost_usdt) },
            ]}
          />
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: AnalyticsPage**

Create `apps/admin/src/features/analytics/AnalyticsPage.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import { BusinessTab } from "./BusinessTab";
import { OpsTab } from "./OpsTab";
import type { AnalyticsRange, BusinessAnalytics, OpsAnalytics } from "./types";

const RANGES: AnalyticsRange[] = ["7d", "30d", "90d"];
const RANGE_LABEL: Record<AnalyticsRange, string> = { "7d": "7 дней", "30d": "30 дней", "90d": "90 дней" };

export function AnalyticsPage() {
  const [tab, setTab] = useState<"business" | "ops">("business");
  const [range, setRange] = useState<AnalyticsRange>("30d");

  const business = useQuery<BusinessAnalytics>({
    queryKey: qk.analyticsBusiness(range),
    queryFn: () => apiGet<BusinessAnalytics>(`/api/v1/admin/stats/analytics/business?range=${range}`),
    enabled: tab === "business",
  });
  const ops = useQuery<OpsAnalytics>({
    queryKey: qk.analyticsOps(range),
    queryFn: () => apiGet<OpsAnalytics>(`/api/v1/admin/stats/analytics/ops?range=${range}`),
    enabled: tab === "ops",
  });

  const active = tab === "business" ? business : ops;

  return (
    <div>
      <PageHeader title="Аналитика" description="Тренды по бизнесу и операционке." />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-[var(--border-default)] p-1">
          {(["business", "ops"] as const).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-[var(--bg-accent-soft)] text-[var(--accent)]" : "text-[var(--text-secondary)]"}`}
            >
              {t === "business" ? "Бизнес" : "Операционка"}
            </button>
          ))}
        </div>
        <div className="flex gap-1 rounded-lg border border-[var(--border-default)] p-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => {
                setRange(r);
              }}
              className={`rounded-md px-3 py-1.5 text-sm ${range === r ? "bg-[var(--bg-accent-soft)] text-[var(--accent)]" : "text-[var(--text-secondary)]"}`}
            >
              {RANGE_LABEL[r]}
            </button>
          ))}
        </div>
      </div>

      {active.isLoading ? (
        <Spinner label="Считаем…" />
      ) : active.isError ? (
        <div role="alert" className="rounded-lg border border-[var(--danger)] p-4 text-sm">
          Не удалось загрузить аналитику.
        </div>
      ) : tab === "business" && business.data ? (
        <BusinessTab data={business.data} />
      ) : tab === "ops" && ops.data ? (
        <OpsTab data={ops.data} />
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Route + sidebar**

In `apps/admin/src/app/router.tsx`, import `AnalyticsPage` and add `{ path: "/analytics", element: <AnalyticsPage /> }` under the authed `Layout` children (next to the dashboard `"/"` route). In `apps/admin/src/app/Layout.tsx`, add a sidebar nav link to `/analytics` labelled "Аналитика" — match the existing nav-item markup exactly (read the file, copy the pattern used by the Dashboard/other links; use a lucide icon like `BarChart3`).

- [ ] **Step 5: Typecheck + lint + prettier**

Run: `pnpm --filter @yupay/admin exec tsc --noEmit && pnpm --filter @yupay/admin run lint` (0 errors; new files 0 warnings) then `pnpm exec prettier --write apps/admin/src/features/analytics apps/admin/src/app/router.tsx apps/admin/src/app/Layout.tsx`. Brace any void-returning arrow handlers; fix import order.

- [ ] **Step 6: Commit**
```bash
git add apps/admin/src/features/analytics/AnalyticsPage.tsx apps/admin/src/features/analytics/BusinessTab.tsx apps/admin/src/features/analytics/OpsTab.tsx apps/admin/src/app/router.tsx apps/admin/src/app/Layout.tsx
git commit -m "feat(admin): analytics page with business + ops tabs and range selector"
```

---

## Task 9: Manual verification

- [ ] **Step 1:** Ensure the stack runs (`docker compose -p yupay-dev up -d` or `make dev`). Recreate api if backend changed: `docker compose -p yupay-dev up -d --no-deps api`.
- [ ] **Step 2:** Open the admin (`http://localhost:3002`), go to **Аналитика**. Verify: both tabs render; the 7/30/90 selector refetches; revenue line, funnel, donuts, provider bar, and tables populate; KPI numbers are sane. Cross-check GMV against `SELECT SUM(total_usd) FROM orders WHERE paid_at >= now() - interval '30 days' AND status IN ('paid','fulfilling','fulfilled','delivered')` via adminer (`http://localhost:8080`).
- [ ] **Step 3:** No commit (verification only). Capture results for the wrap-up note.

---

## Task 10: Documentation

**Files:** Create `docs/decisions/0025-analytics-dashboard.md`; Modify `docs/architecture/cache-keys.md`, `docs/architecture/module-map.md`.

- [ ] **Step 1: ADR**

Create `docs/decisions/0025-analytics-dashboard.md` using `docs/decisions/0000-template.md` (match an existing ADR's MADR format). Decision: a `/analytics` admin page backed by two cached `stats` endpoints; `recharts` adopted for charts; **margin is approximate** (current `sku.cost_usdt`, NULL-cost rows excluded) — precise margin needs denormalised order-item cost (deferred). Alternatives considered: hand-rolled SVG charts (rejected — more code for axes/tooltips/legends); extending the 24h Dashboard (rejected — different cadence/audience). Consequences: new `recharts` dep; `stats` now reads orders/payments/fulfilment/catalog/users/integrations for aggregation.

- [ ] **Step 2: cache-keys**

In `docs/architecture/cache-keys.md`, add an entry (match the file's table/section format): key pattern `stats:analytics:{business|ops}:{7d|30d|90d}`, TTL 300s, invalidation: time-only (no explicit busting; data is approximate trend data), written by the analytics endpoints.

- [ ] **Step 3: module-map**

In `docs/architecture/module-map.md`, note under `stats`: reads `orders, order_items, payments, payment_webhooks, fulfillment_tasks, inventory_codes, catalog (sku/product/brand), users, integrations (supplier_price_history)` for read-only analytics aggregation. Match existing formatting.

- [ ] **Step 4: Commit**
```bash
git add docs/decisions/0025-analytics-dashboard.md docs/architecture/cache-keys.md docs/architecture/module-map.md
git commit -m "docs(stats): ADR + cache-keys + module-map for analytics dashboard"
```

---

## Task 11: Full gate

- [ ] **Step 1:** Backend: `cd apps/api && uv run pytest tests/unit/test_stats_analytics_schemas.py tests/integration/test_stats_analytics.py -v` → all green. Confirm `stats` coverage ≥80% (`uv run pytest --cov=yupay.modules.stats tests/integration/test_stats_analytics.py`).
- [ ] **Step 2:** Admin: `pnpm --filter @yupay/admin exec tsc --noEmit && pnpm --filter @yupay/admin run lint` → 0 errors; `pnpm exec prettier --check apps/admin/src/features/analytics` → clean.
- [ ] **Step 3:** Confirm `main` is clean and push: `git push origin main`. (Per user instruction, work lands directly on `main`; ensure each commit above already passed its checks so CI stays green.)

---

## Self-review notes (resolved)

- **Spec coverage:** range enum + endpoints (T1, T4), business aggregations incl. approx margin with NULL exclusion (T2), ops aggregations (T3), Redis cache + documented keys (T4, T10), recharts + page/tabs/range/charts (T6–T8), tests incl. range filtering + success rates + margin + query path (T2–T4), OpenAPI (T5), ADR + cache-keys + module-map (T10), manual reconcile (T9). All mapped.
- **Type consistency:** `AnalyticsRange`/`range_to_days` (T1) used in T2–T4; `BusinessAnalyticsOut`/`OpsAnalyticsOut` (T1) returned by services (T2/T3) and routes (T4) and mirrored in TS (`BusinessAnalytics`/`OpsAnalytics`, T6) consumed by tabs (T8). `qk.analyticsBusiness/Ops` (T6) used in T8. Chart wrappers (`LineTrend`/`BarBreakdown`/`DonutShare`, T7) consumed in T8.
- **Verify-before-use flagged inline:** `integration_client` + `_login_admin` real fixture (T4 — confirm against `test_g2b_import.py`/conftest), `core.redis.get_redis` cache pattern (mirror `fx/cache.py`), sidebar nav-item markup in `Layout.tsx` (T8 — copy existing), `DataTable` `empty` prop type (string), `Order.paid_at` non-null for paid-like rows.
- **Margin caveat:** explicitly approximate; NULL-cost units excluded from numerator/denominator and surfaced as `margin_unknown_units`.
