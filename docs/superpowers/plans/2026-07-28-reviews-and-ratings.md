# Reviews & Ratings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let verified buyers rate a **brand** (1–5 stars + optional text), show per-brand aggregate ratings across web + Mini App, and feed Google rich snippets.

**Architecture:** New FastAPI modular-monolith module `reviews/` owns three tables (`reviews`, `review_reports`, `brand_rating_stats`). Aggregates are denormalized into `brand_rating_stats` and updated transactionally on every status change (Approach A); catalog reads them via a batch `reviews.api.get_stats`. Web (next-intl, SSG) and Mini App (wouter, custom i18n) render summaries, lists, and a submit form. A nightly scheduler job reconciles stats.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / Pydantic v2; Next.js 15 RSC (web); Vite + React + wouter (miniapp); Vite + React Router (admin); pnpm/turbo; next-intl + custom miniapp i18n.

**Design spec:** `docs/superpowers/specs/2026-07-28-reviews-and-ratings-design.md` (approved).

## Global Constraints

- Rated entity is the **Brand** (`Brand.id` UUID; addressed by `Brand.slug` on the wire). Reviews keyed by `brand_id`.
- Author = logged-in user with a `delivered` order that contains an item of that brand. **Guests cannot review.**
- **One review per `(user_id, order_id, brand_id)`.** Enforced by a UNIQUE constraint.
- Reviews are **immutable**: no user edit, no user delete. Admin may `hide`/`unhide`/`remove`; users may `report`.
- Post-moderation: new reviews are `published` immediately. Only `published` reviews count toward stats and appear in public lists.
- Money/IDs/time idioms: IDs are `str` via `yupay.core.ids.new_id()`; time via `yupay.core.clock.now()`; `Base` from `yupay.core.db`; UUID columns `UUID(as_uuid=False)`.
- Errors: raise typed `yupay.core.errors.{ConflictError,NotFoundError,ValidationError,ForbiddenError}` — never `try/except` in routes; a global handler renders them. `ConflictError(..., code="...")` surfaces `code` in the JSON body.
- Write endpoints require an `Idempotency-Key` header (`IDEMPOTENCY_HEADER`, min 16 chars).
- Rate limiting is **global** (slowapi middleware in `bootstrap.py`) — no per-route limiter code.
- Every new user-facing string added to `packages/i18n/locales/{ru,en,uz}/*.json` in the **same task**. Web uses next-intl namespaces (`web.*`); Mini App uses its own flat-key `miniapp.json` + `useT()`/`tn()`.
- New API DTO fields consumed by web MUST be **optional** (`field?: T`) and every consumer must default them (`?? null` / `?? []`) — `next build` SSG prerenders against the live (old) API. See [[web-ssg-prerenders-against-deployed-api]].
- List endpoints must avoid N+1; the brand-grid enrichment test asserts a bounded query count.
- Escape user-generated text on render (XSS). Show author `display_name`, never email. Never log PII.
- `mypy --strict`, `ruff` (line 100), Google docstrings on public defs (Python); `strict` TS, no `any`.
- Run `make lint typecheck test` before the branch is done. Regenerate OpenAPI (`make gen-api`) whenever routes change.

---

### Task 1: Reviews module — models + migration `0034_reviews`

**Files:**
- Create: `apps/api/src/yupay/modules/reviews/__init__.py`
- Create: `apps/api/src/yupay/modules/reviews/models.py`
- Create: `apps/api/migrations/versions/0034_reviews.py`
- Modify: `apps/api/migrations/env.py` (register models import, alphabetical)
- Modify: `apps/scheduler/src/yupay_scheduler/main.py` (register models import, alphabetical)
- Test: `apps/api/tests/integration/test_reviews_migration.py`

**Interfaces:**
- Produces: ORM classes `Review`, `ReviewReport`, `BrandRatingStats` (all import `Base` from `yupay.core.db`). Statuses live in a module constant `REVIEW_STATUSES = ("published", "hidden", "removed")`.

- [ ] **Step 1: Module docstring file**

`apps/api/src/yupay/modules/reviews/__init__.py`:
```python
"""Brand reviews & ratings: verified-buyer star ratings with post-moderation."""
```

- [ ] **Step 2: Write `models.py`**

```python
"""SQLAlchemy models for brand reviews, abuse reports, and denormalized rating stats."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base

REVIEW_STATUSES = ("published", "hidden", "removed")


class Review(Base):
    """A single brand review anchored to a delivered order (proof of purchase)."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'published'"))
    locale: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'ru'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        UniqueConstraint("user_id", "order_id", "brand_id", name="uq_reviews_user_order_brand"),
        Index("ix_reviews_brand_status_created", "brand_id", "status", "created_at"),
        Index("ix_reviews_user", "user_id"),
    )


class ReviewReport(Base):
    """An abuse report against a review. Threshold of distinct reports auto-hides."""

    __tablename__ = "review_reports"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    reporter_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("review_id", "reporter_user_id", name="uq_review_reports_review_reporter"),
        Index("ix_review_reports_review", "review_id"),
    )


class BrandRatingStats(Base):
    """Denormalized per-brand aggregate over ``published`` reviews only."""

    __tablename__ = "brand_rating_stats"

    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sum_rating: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    avg: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, server_default=text("0"))
    count_1: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_2: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_3: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_4: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_5: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = ["REVIEW_STATUSES", "Review", "ReviewReport", "BrandRatingStats"]
```

- [ ] **Step 3: Write migration `0034_reviews.py`**

Mirror `0033_idempotent_responses.py` structure. `down_revision = "0033_idempotent_responses"`.

```python
"""Brand reviews, abuse reports, and denormalized per-brand rating stats.

See docs/decisions/0039-reviews-and-ratings.md.

Revision ID: 0034_reviews
Revises: 0033_idempotent_responses
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0034_reviews"
down_revision: str | None = "0033_idempotent_responses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=False), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", UUID(as_uuid=False), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'published'")),
        sa.Column("locale", sa.String(3), nullable=False, server_default=sa.text("'ru'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        sa.UniqueConstraint("user_id", "order_id", "brand_id", name="uq_reviews_user_order_brand"),
    )
    op.create_index("ix_reviews_brand_status_created", "reviews", ["brand_id", "status", "created_at"])
    op.create_index("ix_reviews_user", "reviews", ["user_id"])

    op.create_table(
        "review_reports",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("review_id", UUID(as_uuid=False), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("review_id", "reporter_user_id", name="uq_review_reports_review_reporter"),
    )
    op.create_index("ix_review_reports_review", "review_reports", ["review_id"])

    op.create_table(
        "brand_rating_stats",
        sa.Column("brand_id", UUID(as_uuid=False), sa.ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("sum_rating", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("avg", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("count_1", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_2", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_3", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_4", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("count_5", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("brand_rating_stats")
    op.drop_index("ix_review_reports_review", table_name="review_reports")
    op.drop_table("review_reports")
    op.drop_index("ix_reviews_user", table_name="reviews")
    op.drop_index("ix_reviews_brand_status_created", table_name="reviews")
    op.drop_table("reviews")
```

- [ ] **Step 4: Register models for metadata**

In `apps/api/migrations/env.py`, add (alphabetical, after `_promo_models`... place by module name `reviews` — after `payments`/`promo`? current file has no promo import; insert in correct alphabetical slot between `_payments_models` and `_sourcing_models`):
```python
from yupay.modules.reviews import models as _reviews_models  # noqa: F401
```
In `apps/scheduler/src/yupay_scheduler/main.py`, add the same import in its alphabetical slot (after `_payments_models`, before `_sourcing_models`).

- [ ] **Step 5: Write the migration test**

`apps/api/tests/integration/test_reviews_migration.py` — assert the three tables + the unique constraint exist after `alembic upgrade head` (the integration test DB runs migrations). Mirror any existing migration/schema test; if none exists, assert via `db_session`:
```python
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_reviews_tables_exist(db_session):
    for table in ("reviews", "review_reports", "brand_rating_stats"):
        r = await db_session.execute(
            text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
        )
        assert r.scalar() is not None, f"{table} missing"
```

- [ ] **Step 6: Run + commit**

Run: `make migrate` (or the containerized alembic) then `pytest apps/api/tests/integration/test_reviews_migration.py -v`. Expected: PASS.
Commit: `feat(api/reviews): models + migration 0034 for brand reviews`.

---

### Task 2: Reviews service + schemas (business logic, no HTTP)

**Files:**
- Create: `apps/api/src/yupay/modules/reviews/schemas.py`
- Create: `apps/api/src/yupay/modules/reviews/service.py`
- Test: `apps/api/tests/integration/test_reviews_service.py`

**Interfaces:**
- Consumes: `Review`, `ReviewReport`, `BrandRatingStats` (Task 1); `yupay.core.ids.new_id`, `yupay.core.clock.now`, `yupay.core.errors.*`.
- Produces (called by routes in Task 3 and catalog in Task 4):
  - `async create_review(db, *, user_id: str, order_id: str, brand_slug: str, rating: int, body: str | None, locale: str) -> Review`
  - `async list_published(db, *, brand_id: str, limit: int, cursor: str | None) -> tuple[list[Review], str | None]` (returns page + next cursor)
  - `async get_stats(db, brand_ids: Sequence[str]) -> dict[str, BrandRatingStats]`
  - `async list_own(db, *, user_id: str) -> list[Review]`
  - `async report_review(db, *, review_id: str, reporter_user_id: str | None, reason: str | None) -> None`
  - `async admin_list(db, *, status: str | None, reported_only: bool, limit: int, offset: int) -> tuple[list[Review], int]`
  - `async admin_set_status(db, *, review_id: str, status: str) -> Review`
  - `async recompute_all_stats(db) -> int` (used by the scheduler)
  - `async resolve_brand_id(db, slug: str) -> str` (slug→id, raises `NotFoundError`)
- Schemas: `ReviewCreateIn`, `ReviewOut`, `ReviewListOut`, `ReviewStatsOut`, `OwnReviewOut`, `OwnReviewListOut`, `ReviewReportIn`, `AdminReviewOut`, `AdminReviewListOut`.

- [ ] **Step 1: Write `schemas.py`**

```python
"""Pydantic v2 request/response models for the reviews module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_REPORT_THRESHOLD_REASON_MAX = 64


class ReviewCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    brand_slug: str = Field(..., min_length=1, max_length=64)
    rating: int = Field(..., ge=1, le=5)
    body: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    """A published review as shown on the public brand page."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    rating: int
    body: str | None
    author_name: str
    created_at: datetime


class ReviewStatsOut(BaseModel):
    avg: float
    count: int
    dist: dict[int, int]  # {1: n1, ..., 5: n5}


class ReviewListOut(BaseModel):
    items: list[ReviewOut]
    next_cursor: str | None
    stats: ReviewStatsOut


class OwnReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    brand_id: str
    rating: int


class OwnReviewListOut(BaseModel):
    items: list[OwnReviewOut]


class ReviewReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=_REPORT_THRESHOLD_REASON_MAX)


class AdminReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    brand_id: str
    user_id: str
    order_id: str
    rating: int
    body: str | None
    status: str
    report_count: int
    created_at: datetime


class AdminReviewListOut(BaseModel):
    items: list[AdminReviewOut]
    total: int
```

- [ ] **Step 2: Write the failing service test**

`apps/api/tests/integration/test_reviews_service.py` — build fixtures for a user, a brand (with a product+sku), and a `delivered` order containing that sku (reuse existing catalog/order test factories — grep `apps/api/tests` for `make_order`/`create_brand` helpers; if none, insert rows directly). Tests:
```python
import pytest
from yupay.core.errors import ConflictError, ForbiddenError
from yupay.modules.reviews import service as svc

pytestmark = pytest.mark.asyncio


async def test_create_review_happy_path_bumps_stats(db_session, delivered_order, brand, user):
    r = await svc.create_review(
        db_session, user_id=user.id, order_id=delivered_order.id,
        brand_slug=brand.slug, rating=5, body="great", locale="ru",
    )
    assert r.status == "published"
    stats = (await svc.get_stats(db_session, [brand.id]))[brand.id]
    assert stats.count == 1 and float(stats.avg) == 5.0 and stats.count_5 == 1


async def test_duplicate_same_order_brand_conflicts(db_session, delivered_order, brand, user):
    kw = dict(user_id=user.id, order_id=delivered_order.id, brand_slug=brand.slug, rating=4, body=None, locale="ru")
    await svc.create_review(db_session, **kw)
    with pytest.raises(ConflictError):
        await svc.create_review(db_session, **kw)


async def test_undelivered_order_forbidden(db_session, pending_order, brand, user):
    with pytest.raises(ForbiddenError):
        await svc.create_review(db_session, user_id=user.id, order_id=pending_order.id,
                                brand_slug=brand.slug, rating=4, body=None, locale="ru")


async def test_brand_not_in_order_forbidden(db_session, delivered_order, other_brand, user):
    with pytest.raises(ForbiddenError):
        await svc.create_review(db_session, user_id=user.id, order_id=delivered_order.id,
                                brand_slug=other_brand.slug, rating=4, body=None, locale="ru")


async def test_report_threshold_auto_hides(db_session, published_review, brand):
    # Three DISTINCT reporters cross the default threshold (3) → auto-hide.
    for reporter_id in ("11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222",
                        "33333333-3333-3333-3333-333333333333"):
        await svc.report_review(db_session, review_id=published_review.id,
                                reporter_user_id=reporter_id, reason=None)
    await db_session.refresh(published_review)
    assert published_review.status == "hidden"
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 0


async def test_duplicate_report_is_noop(db_session, published_review):
    kw = dict(review_id=published_review.id, reporter_user_id="44444444-4444-4444-4444-444444444444", reason=None)
    await svc.report_review(db_session, **kw)
    await svc.report_review(db_session, **kw)  # same reporter twice → swallowed, still published
    await db_session.refresh(published_review)
    assert published_review.status == "published"


async def test_admin_hide_then_unhide_adjusts_stats(db_session, published_review, brand):
    await svc.admin_set_status(db_session, review_id=published_review.id, status="hidden")
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 0
    await svc.admin_set_status(db_session, review_id=published_review.id, status="published")
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 1
```
(Refine the report-threshold assertion to re-fetch the review row; the sketch above marks intent.)

- [ ] **Step 3: Run to verify it fails**

Run: `pytest apps/api/tests/integration/test_reviews_service.py -v`. Expected: FAIL (import error / functions undefined).

- [ ] **Step 4: Implement `service.py`**

Key logic:
- `resolve_brand_id(db, slug)`: `SELECT id FROM brands WHERE slug=:slug`; `NotFoundError("brand not found")` if none.
- `create_review`:
  1. `brand_id = await resolve_brand_id(db, brand_slug)`.
  2. Load the order `WHERE id=:order_id`. If missing → `NotFoundError`. If `order.user_id != user_id` → `ForbiddenError("not your order")`. If `order.status != "delivered"` → `ForbiddenError("order not delivered")`.
  3. Verify the order contains an item of `brand_id`: join `order_items → skus → products` and check any `products.brand_id == brand_id`; else `ForbiddenError("brand not in order")`.
  4. Insert the review inside a `begin_nested()` + catch `IntegrityError` → `ConflictError("already reviewed", code="already_reviewed")` (covers the unique constraint).
  5. `await _bump_stats(db, brand_id, rating, +1)`.
  6. `return review`.
- `_bump_stats(db, brand_id, rating, sign)`: `SELECT ... FOR UPDATE` the stats row (create it if missing via `INSERT ... ON CONFLICT DO NOTHING` then re-select); apply `count += sign`, `sum_rating += sign*rating`, `count_<rating> += sign`, `avg = sum_rating/count if count else 0`, `updated_at = now()`.
- `list_published(db, brand_id, limit, cursor)`: keyset by `(created_at, id)` descending, `status='published'`; decode/encode an opaque cursor (base64 of `f"{created_at.isoformat()}|{id}"`); build `ReviewOut.author_name` from the user's `display_name` (join users; fall back to a generic `"Покупатель"` label when null — never expose email). Return `(reviews, next_cursor)`.
- `get_stats(db, brand_ids)`: `SELECT * FROM brand_rating_stats WHERE brand_id = ANY(:ids)`; return `{row.brand_id: row}`. Missing brands simply absent → callers treat as no reviews.
- `list_own(db, user_id)`: all of the user's reviews (any status) → for CTA suppression.
- `report_review`: insert a `ReviewReport` inside `begin_nested()`, swallow duplicate `(review_id, reporter)` via `IntegrityError` (idempotent — a repeat report is a no-op). Then count distinct reports; if `>= _REPORT_AUTO_HIDE_THRESHOLD` (module const, default `3`) and the review is `published`, call the same status-transition path to set `hidden` + `_bump_stats(..., -1)`.
- `admin_list(db, status, reported_only, limit, offset)`: query reviews (optionally filtered by status; if `reported_only`, join to reports having count>0), annotate `report_count` via a correlated subquery, order by `created_at DESC`, return `(rows, total)`.
- `admin_set_status(db, review_id, status)`: load review `FOR UPDATE`; validate `status in REVIEW_STATUSES`; if transitioning **into** `published` from non-published, `_bump_stats(+1)`; if transitioning **out of** `published`, `_bump_stats(-1)`; no double-count if status unchanged. Persist `status` + `updated_at`.
- `recompute_all_stats(db)`: recompute every brand's row from `published` reviews with a single `GROUP BY brand_id` aggregate and upsert; zero out brands with no published reviews. Returns number of brands touched.
- Use `log = get_logger("yupay.reviews.service")`; log events like `log.info("review.created", brand_id=..., rating=rating)` — **never** log `body` (PII/UGC).
- Add `__all__`.

- [ ] **Step 5: Run to verify it passes**

Run: `pytest apps/api/tests/integration/test_reviews_service.py -v`. Expected: PASS. Then `ruff check` + `mypy --strict` on the module.

- [ ] **Step 6: Commit**

Commit: `feat(api/reviews): service + schemas (create, list, stats, moderation)`.

---

### Task 3: Reviews routes + `api.py` + mount

**Files:**
- Create: `apps/api/src/yupay/modules/reviews/routes.py`
- Create: `apps/api/src/yupay/modules/reviews/api.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (import + mount, alphabetical)
- Test: `apps/api/tests/integration/test_reviews_routes.py`
- Docs: regenerate `docs/api/openapi.json` + `packages/api-client` via `make gen-api`

**Interfaces:**
- Consumes: service functions (Task 2); `db_session` from `yupay.api.v1.deps`; `current_user` from `yupay.modules.auth.deps`; `require_admin` from `yupay.modules.admin.api`; `IDEMPOTENCY_HEADER`, `MIN_IDEMPOTENCY_KEY_LENGTH` from `yupay.core.idempotency`.
- Produces: `router` (prefix `/reviews`), `admin_router` (prefix `/admin/reviews`, `Depends(require_admin)`), plus `api.py` re-exporting `get_stats` for catalog.

- [ ] **Step 1: Write the failing route test**

`apps/api/tests/integration/test_reviews_routes.py` (fixtures `integration_client: AsyncClient`, an auth header helper — grep existing route tests for `auth_header`/login helper):
```python
import pytest
pytestmark = pytest.mark.asyncio


async def test_post_review_requires_idempotency_key(integration_client, user_token, delivered_order, brand):
    r = await integration_client.post("/api/v1/reviews", headers={"Authorization": f"Bearer {user_token}"},
        json={"order_id": delivered_order.id, "brand_slug": brand.slug, "rating": 5, "body": "ok"})
    assert r.status_code == 422  # missing Idempotency-Key


async def test_post_then_public_list_shows_it(integration_client, user_token, delivered_order, brand):
    r = await integration_client.post("/api/v1/reviews",
        headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "k-abcdef0123456789"},
        json={"order_id": delivered_order.id, "brand_slug": brand.slug, "rating": 4, "body": "good"})
    assert r.status_code == 201
    lst = await integration_client.get(f"/api/v1/reviews/brands/{brand.slug}")
    body = lst.json()
    assert body["stats"]["count"] == 1 and len(body["items"]) == 1
    assert body["items"][0]["author_name"]  # never the email


async def test_guest_cannot_post(integration_client, delivered_order, brand):
    r = await integration_client.post("/api/v1/reviews",
        headers={"Idempotency-Key": "k-abcdef0123456789"},
        json={"order_id": delivered_order.id, "brand_slug": brand.slug, "rating": 4})
    assert r.status_code == 401


async def test_admin_hide_removes_from_public_list(integration_client, admin_token, published_review, brand):
    h = await integration_client.post(f"/api/v1/admin/reviews/{published_review.id}/hide",
        headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": "k-hide-0123456789"})
    assert h.status_code == 200
    lst = await integration_client.get(f"/api/v1/reviews/brands/{brand.slug}")
    assert lst.json()["stats"]["count"] == 0
```

- [ ] **Step 2: Run to verify it fails** — `pytest apps/api/tests/integration/test_reviews_routes.py -v` → FAIL (404s / import errors).

- [ ] **Step 3: Implement `routes.py`**

Public `router = APIRouter(prefix="/reviews", tags=["reviews"])`:
- `GET /reviews/brands/{slug}?cursor=&limit=` → resolve brand id, `list_published`, `get_stats`, return `ReviewListOut` (public, anonymous OK). `limit` clamped to `[1, 50]`, default 20. Build the response `stats: ReviewStatsOut` from the ORM `BrandRatingStats` row: `ReviewStatsOut(avg=float(s.avg), count=s.count, dist={1: s.count_1, ..., 5: s.count_5})`, or a zeroed `ReviewStatsOut(avg=0, count=0, dist={1:0,...,5:0})` when the brand has no stats row yet.
- `POST /reviews` → `current_user`, require Idempotency-Key (reuse the promo `_require_idempotency_key` helper pattern), call `create_review`, return `201` `ReviewOut`. Idempotency: because a review row is unique on `(user, order, brand)`, a retried POST with the same tuple naturally 409s — for a true replay, catch the create's `ConflictError(code="already_reviewed")` only when the incoming Idempotency-Key matches a stored one; **MVP: rely on the unique constraint (repeat = 409)** and document that the client treats 409 as "already submitted". (No generic idempotency store needed.)
- `GET /reviews/mine` → `current_user`, `list_own`, return `OwnReviewListOut`.
- `POST /reviews/{id}/report` → `current_user`, `report_review`, return `204`.

Admin `admin_router = APIRouter(prefix="/admin/reviews", tags=["admin:reviews"], dependencies=[Depends(require_admin)])`:
- `GET /admin/reviews?status=&reported=&limit=&offset=` → `admin_list` → `AdminReviewListOut`.
- `POST /admin/reviews/{id}/hide` / `.../unhide` / `.../remove` → `admin_set_status` to `hidden`/`published`/`removed` → `AdminReviewOut`. Require Idempotency-Key on these writes (use the generic `load_replay`/`save_replay` from `yupay.core.idempotency` with `scope="reviews.admin.<action>"`, mirroring how fulfillment admin mutate-endpoints do it).

Set explicit `status_code=201`/`204` on the decorators. No `try/except` — let typed errors propagate.

- [ ] **Step 4: Write `api.py`**

```python
"""Public surface of the ``reviews`` module — the only thing other modules import."""

from yupay.modules.reviews.models import BrandRatingStats, Review, ReviewReport
from yupay.modules.reviews.routes import admin_router, router
from yupay.modules.reviews.schemas import ReviewStatsOut
from yupay.modules.reviews.service import get_stats, recompute_all_stats

__all__ = [
    "BrandRatingStats", "Review", "ReviewReport", "ReviewStatsOut",
    "admin_router", "get_stats", "recompute_all_stats", "router",
]
```

- [ ] **Step 5: Mount in `api/v1/__init__.py`**

Add imports in the alphabetical slot (after `promo`, before `sourcing`):
```python
from yupay.modules.reviews.api import admin_router as reviews_admin_router
from yupay.modules.reviews.api import router as reviews_router
```
And in the include block:
```python
router.include_router(reviews_router)
router.include_router(reviews_admin_router)
```

- [ ] **Step 6: Run + regen + commit**

Run: `pytest apps/api/tests/integration/test_reviews_routes.py -v` → PASS. Then `make gen-api` (regenerates `docs/api/openapi.json` + `packages/api-client`).
Commit: `feat(api/reviews): public + admin routes, mount, api.py` (include regenerated client).

---

### Task 4: Catalog enrichment — attach `rating` to brand DTOs (no N+1)

**Files:**
- Modify: `apps/api/src/yupay/modules/catalog/schemas.py` (add optional `rating` to `BrandOut` + `BrandDetailOut`)
- Modify: `apps/api/src/yupay/modules/catalog/service.py` (`_brand_summary` ~line 121, `list_brands` ~line 283, `get_brand_by_slug` ~line 306)
- Test: `apps/api/tests/integration/test_catalog_ratings.py`
- Docs: `make gen-api` again

**Interfaces:**
- Consumes: `reviews.api.get_stats` (Task 3).
- Produces: catalog DTOs now carry `rating: BrandRatingOut | None`.

- [ ] **Step 1: Add the DTO**

In `catalog/schemas.py`:
```python
class BrandRatingOut(BaseModel):
    avg: float
    count: int
```
Add `rating: BrandRatingOut | None = None` to both `BrandOut` and `BrandDetailOut`.

- [ ] **Step 2: Write the failing enrichment + query-count test**

`apps/api/tests/integration/test_catalog_ratings.py`:
```python
import pytest
from sqlalchemy import event

pytestmark = pytest.mark.asyncio


async def test_brand_grid_includes_rating(integration_client, brand_with_reviews):
    r = await integration_client.get("/api/v1/catalog/brands")
    item = next(b for b in r.json()["items"] if b["slug"] == brand_with_reviews.slug)
    assert item["rating"]["count"] >= 1 and item["rating"]["avg"] > 0


async def test_brand_grid_rating_is_not_n_plus_1(integration_client, db_engine, many_brands_with_reviews):
    # Count SELECTs against reviews stats; must be a single batch query regardless of brand count.
    counter = {"stats": 0}
    @event.listens_for(db_engine.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):
        if "brand_rating_stats" in statement:
            counter["stats"] += 1
    await integration_client.get("/api/v1/catalog/brands")
    assert counter["stats"] <= 1
```
(Adapt the engine-event hook to the project's existing query-counting helper if one exists — grep `before_cursor_execute` in `apps/api/tests`.)

- [ ] **Step 3: Run to verify it fails** — FAIL (rating null / N+1).

- [ ] **Step 4: Implement enrichment**

- Change `_brand_summary(brand, locale)` → `_brand_summary(brand, locale, rating: BrandRatingOut | None = None)` and set `rating=rating` in the returned `BrandOut`.
- In `list_brands`, after loading `rows`:
```python
from yupay.modules.reviews import api as reviews_api
...
stats = await reviews_api.get_stats(db, [b.id for b in rows])
return [
    _brand_summary(b, locale, _to_rating(stats.get(b.id)))
    for b in rows
]
```
with a small local helper `_to_rating(s) -> BrandRatingOut | None` returning `None` when `s is None or s.count == 0`, else `BrandRatingOut(avg=float(s.avg), count=s.count)`.
- In `get_brand_by_slug`, before constructing `BrandDetailOut`, add `stats = await reviews_api.get_stats(db, [brand.id])` and pass `rating=_to_rating(stats.get(brand.id))`.

- [ ] **Step 5: Run + regen + commit** — tests PASS; `make gen-api`; commit `feat(api/catalog): expose per-brand rating on brand DTOs`.

---

### Task 5: Scheduler — nightly `recompute_brand_rating_stats`

**Files:**
- Create: `apps/scheduler/src/yupay_scheduler/jobs/recompute_review_stats.py`
- Modify: `apps/scheduler/src/yupay_scheduler/main.py` (import + `register`)
- Test: `apps/scheduler` test dir (mirror an existing job test) or `apps/api/tests/integration/test_reviews_reconcile.py` exercising `recompute_all_stats`

**Interfaces:**
- Consumes: `reviews.service.recompute_all_stats` via `reviews.api` (`from yupay.modules.reviews.service import recompute_all_stats` — reach into service directly like `waxpeer_reconcile` does, to avoid importing `routes`).

- [ ] **Step 1: Write the job** — mirror `waxpeer_reconcile.py` structure but `trigger="cron"`:
```python
"""Nightly reconcile of denormalized brand rating stats (drift safety net)."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.reviews.service import recompute_all_stats

log = get_logger("yupay.scheduler.recompute_review_stats")
_JOB_ID = "reviews.recompute_stats"


async def run_recompute_review_stats() -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        touched = await recompute_all_stats(session)
    log.info("recompute_review_stats.tick", brands=touched)


def register(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        run_recompute_review_stats, trigger="cron", hour=3, minute=15,
        id=_JOB_ID, replace_existing=True, max_instances=1, coalesce=True,
    )
    log.info("recompute_review_stats.registered")


__all__ = ["register", "run_recompute_review_stats"]
```

- [ ] **Step 2: Register** in `main.py`: add `recompute_review_stats` to the `from yupay_scheduler.jobs import (...)` block and `recompute_review_stats.register(scheduler)` in `build_scheduler`.

- [ ] **Step 3: Test** `recompute_all_stats` corrects a deliberately-wrong stats row (write a review, corrupt the stats row to `count=99`, run recompute, assert it resets to the true value). Run → PASS.

- [ ] **Step 4: Commit** — `feat(scheduler): nightly recompute of brand rating stats`.

---

### Task 6: Web — rating display (catalog types, brand card, brand-page summary, JSON-LD)

**Files:**
- Modify: `apps/web/src/lib/catalog.ts` (optional `rating` on `BrandSummary` + `BrandDetail`)
- Create: `apps/web/src/lib/reviews.ts` (fetchers + types for the reviews API)
- Create: `apps/web/src/components/store/RatingSummary.tsx` (stars + avg + count + histogram)
- Create: `apps/web/src/components/store/Stars.tsx` (extract the star row; reuse the `lucide-react` `Star fill-gold` idiom from `components/sections/Reviews.tsx`)
- Modify: `apps/web/src/components/store/BrandCard.tsx` (rating chip)
- Modify: `apps/web/src/app/[locale]/store/[brandSlug]/page.tsx` (summary block under hero + `aggregateRating` in `productLd`)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (new `brandReviews` namespace)
- Test: `apps/web/src/components/store/RatingSummary.test.tsx`, `Stars.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/reviews/brands/{slug}` (Task 3), `rating` on brand DTOs (Task 4).

- [ ] **Step 1: Types** — in `catalog.ts` add to both interfaces (optional!):
```ts
export interface BrandRating { avg: number; count: number; }
// on BrandSummary AND BrandDetail:
rating?: BrandRating | null;
```
Create `lib/reviews.ts`:
```ts
import { apiGet, apiFetch } from "./client"; // match actual exports

export interface Review { id: string; rating: number; body: string | null; author_name: string; created_at: string; }
export interface ReviewStats { avg: number; count: number; dist: Record<string, number>; }
export interface ReviewPage { items: Review[]; next_cursor: string | null; stats: ReviewStats; }

export function getBrandReviews(slug: string, locale: string, cursor?: string): Promise<ReviewPage> {
  const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiGet<ReviewPage>(`/reviews/brands/${encodeURIComponent(slug)}${q}`, { locale, revalidate: 60 });
}
export function submitReview(body: { order_id: string; brand_slug: string; rating: number; body?: string }) {
  return apiFetch("/reviews", { method: "POST", body, headers: { "Idempotency-Key": crypto.randomUUID() } });
}
export function getMyReviews() {
  return apiFetch<{ items: { id: string; order_id: string; brand_id: string; rating: number }[] }>("/reviews/mine");
}
```
(Reconcile the exact `apiGet`/`apiFetch` signatures with `apps/web/src/lib/client.ts` + `api.ts`.)

- [ ] **Step 2: `Stars.tsx` + failing test** — a presentational component `<Stars value={4.3} size={16} />` rendering 5 `Star` icons with fractional fill. Test asserts 5 icons and the filled count for integer + rounding for fractional.

- [ ] **Step 3: `RatingSummary.tsx` + failing test** — props `{ avg, count, dist }`; renders big avg, `<Stars>`, count label via `t("web.brandReviews.count", { count })` (ICU plural), and 5 histogram bars. Test asserts avg text + count label + 5 bars. When `count === 0`, render a "no reviews yet" state.

- [ ] **Step 4: Implement, then wire into pages**
- `BrandCard.tsx`: if `brand.rating && brand.rating.count > 0`, render a small chip `★ {avg.toFixed(1)} ({count})` (mirror the maintenance badge placement). Always guard `brand.rating ?? null`.
- Brand page `page.tsx`: fetch reviews server-side alongside `getBrandDetail` (`getBrandReviews(brandSlug, locale)` in the same `try/catch`, default to `{ items: [], next_cursor: null, stats: { avg: 0, count: 0, dist: {} } }` on failure — SSG safety). Render `<RatingSummary … />` right after the hero chips row (~line 207-224). Add to `productLd` (sibling of `offers`, conditional):
```ts
...(stats.count > 0 ? { aggregateRating: { "@type": "AggregateRating", ratingValue: stats.avg, reviewCount: stats.count } } : {}),
```

- [ ] **Step 5: i18n** — add a `brandReviews` block to `web.json` in **all three** locales, incl. an ICU plural:
```json
"brandReviews": {
  "title": "Отзывы",
  "count": "{count, plural, one {# отзыв} few {# отзыва} many {# отзывов} other {# отзыва}}",
  "empty": "Пока нет отзывов",
  "writeCta": "Оценить покупку",
  "submit": "Отправить",
  "ratingLabel": "Ваша оценка",
  "commentLabel": "Комментарий (необязательно)",
  "thanks": "Спасибо за отзыв!",
  "alreadyReviewed": "Вы уже оценили эту покупку",
  "report": "Пожаловаться"
}
```
(en/uz translated equivalently; keep ICU plural categories valid per locale — en uses `one/other`, uz uses `other`.)

- [ ] **Step 6: Run + commit** — `pnpm --filter web test` + `pnpm --filter web typecheck`. Commit `feat(web/store): brand rating summary, card badge, JSON-LD aggregateRating`.

---

### Task 7: Web — submit form + account "Rate your purchase" CTA

**Files:**
- Create: `apps/web/src/components/store/ReviewForm.tsx` (client) + `ReviewList.tsx` (paginated list, escapes body)
- Modify: brand page `page.tsx` to render `<ReviewList>` after FAQ and `<ReviewForm>` for eligible users (client island)
- Modify: `apps/web/src/app/[locale]/account/orders/page.tsx` (per-delivered-order CTA) OR `apps/web/src/components/order/OrderStatus.tsx`
- Test: `ReviewForm.test.tsx`

**Interfaces:**
- Consumes: `submitReview`, `getMyReviews` (Task 6), `useAuth` (`apps/web/src/lib/auth.tsx`).

- [ ] **Step 1: `ReviewList.tsx`** — renders `Review[]` with `<Stars>`, `author_name`, date via `Intl.DateTimeFormat`, and body rendered as **plain text** (React escapes by default — do NOT use `dangerouslySetInnerHTML`). "Load more" uses `next_cursor` (client component with `useState` + `getBrandReviews`). Include a small "Пожаловаться" action → `POST /reviews/{id}/report` (auth only).

- [ ] **Step 2: `ReviewForm.tsx` + failing test** — `"use client"`; props `{ orderId, brandSlug, onDone }`; star picker (1-5) + optional textarea (max 2000, counter); submit calls `submitReview`; on success shows `t("web.brandReviews.thanks")` and calls `onDone`; on 409 shows `alreadyReviewed`. Test: renders stars, submits, calls the fetch with the right body, shows thanks.

- [ ] **Step 3: Brand-page wiring** — a client wrapper decides eligibility: fetch `getMyReviews()` (only if `useAuth().user`), and show the form when the user has a `delivered` order for this brand not yet in their reviews. Since the brand page is a server component, add a small `"use client"` island `<BrandReviewsSection brandSlug detail>` that owns the list + conditional form. Keep `"use client"` as deep as possible.

- [ ] **Step 4: Account CTA** — in `account/orders/page.tsx`, for each order with `status === "delivered"`, for each distinct `item.display.brand_slug` not present in `getMyReviews()` results, render a passive link/button "Оценить покупку" that deep-links to `/${locale}/store/${brand_slug}#reviews` (the review section anchor) carrying `?order=${o.id}` so the form preselects the order. Gate on `useAuth().user` (guests never see it). After a review exists for that `(order, brand)`, the CTA disappears (derived from `getMyReviews`).

- [ ] **Step 5: Run + commit** — web tests + typecheck. Commit `feat(web/store): review submit form + account rate-purchase CTA`.

---

### Task 8: Mini App — reviews sheet + submit + History/OrderSuccess CTA

**Files:**
- Create: `apps/miniapp/src/lib/reviews.ts` (fetchers using `apiGet`/`apiPost` from `src/lib/api.ts`)
- Create: `apps/miniapp/src/components/ReviewsSheet.tsx` (bottom sheet: summary + list + form)
- Modify: `apps/miniapp/src/pages/TopUp.tsx` (rating chip at the flagged slot ~line 660 → opens the sheet)
- Modify: `apps/miniapp/src/pages/History.tsx` (or `src/lib/orders.ts` row) + `apps/miniapp/src/pages/OrderSuccess.tsx` (`DeliveredExtras`) — "Оценить" CTA
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` (flat keys incl. a plural object)
- Test: a component test if the miniapp has a test setup (mirror `History.test` if present)

**Interfaces:**
- Consumes: reviews API (Task 3), brand rating (Task 4 — available via `useBrandSummary`), `useMe()` (`src/lib/auth.ts`), `newIdempotencyKey` (`src/lib/api.ts`), `useT`/`tn` (`src/lib/i18n`).

- [ ] **Step 1: `lib/reviews.ts`** — `getBrandReviews(slug, cursor?)`, `submitReview(body)` with `apiPost("/reviews", body, { idempotencyKey: newIdempotencyKey("review") })`, `getMyReviews()`, `reportReview(id, reason)`. Types mirror web.

- [ ] **Step 2: `ReviewsSheet.tsx`** — a bottom sheet (reuse the app's existing sheet/modal primitive — grep for an existing `Sheet`/`Drawer`) showing `RatingSummary`-equivalent (stars + count + histogram), a scrollable list (escaped text), and — when `useMe()` is set and the user has an eligible delivered order for this brand — the star+textarea form. Submit via `submitReview`; on 409 show "already reviewed" (`tn`/`t`).

- [ ] **Step 3: TopUp chip** — at the flagged code comment (~line 660 in `TopUp.tsx`), replace/augment the delivery-time chip row with a rating chip: `★ {avg} ({count})` from `useBrandSummary(gameId).rating` (guard optional), tapping opens `<ReviewsSheet brandSlug=…/>`. If `rating` is null/absent, show only the existing delivery-time chip (no fake stars).

- [ ] **Step 4: History / OrderSuccess CTA** — in `History.tsx` next to the existing `history.repeat` button (same `status === "success"` gate, same `e.preventDefault(); e.stopPropagation()`), add a "Оценить" button opening the sheet for `tx.gameSlug`. In `OrderSuccess.tsx` `DeliveredExtras`, add the same CTA using `order.items[0].display.brand_slug`. Suppress once `getMyReviews()` contains that `(order, brand)`.

- [ ] **Step 5: i18n** — add flat keys to `miniapp.json` (all three locales), incl. a plural object:
```json
"reviews.title": "Отзывы",
"reviews.count": { "one": "{count} отзыв", "few": "{count} отзыва", "many": "{count} отзывов", "other": "{count} отзыва" },
"reviews.rateCta": "Оценить",
"reviews.submit": "Отправить",
"reviews.commentPlaceholder": "Комментарий (необязательно)",
"reviews.thanks": "Спасибо за отзыв!",
"reviews.already": "Вы уже оценили эту покупку",
"reviews.empty": "Пока нет отзывов"
```
(en/uz parity — the miniapp i18n has compile-time parity assertions, so all three must match key-for-key.)

- [ ] **Step 6: Run + commit** — `pnpm --filter miniapp typecheck` (+ tests if present). Commit `feat(miniapp): brand reviews sheet, rating chip, rate CTA`.

---

### Task 9: Admin — moderation queue

**Files:**
- Create: `apps/admin/src/features/reviews/types.ts`
- Create: `apps/admin/src/features/reviews/ReviewsPage.tsx`
- Modify: `apps/admin/src/app/router.tsx` (route `/reviews`)
- Modify: `apps/admin/src/app/Layout.tsx` (nav entry — mirror an existing sidebar item)
- Modify: `apps/admin/src/lib/queryKeys.ts` (`qk.reviews(...)`)
- Test: `apps/admin/src/features/reviews/ReviewsPage.test.tsx` (mirror `ManualQueuePage`/broadcasts tests)

**Interfaces:**
- Consumes: `GET /api/v1/admin/reviews`, `POST /api/v1/admin/reviews/{id}/{hide,unhide,remove}` (Task 3); `apiGet`/`apiPost` from `@/lib/api`; `DataTable`, `PageHeader`.

- [ ] **Step 1: Types** — `AdminReview`, `AdminReviewList` mirroring `AdminReviewOut`/`AdminReviewListOut`.

- [ ] **Step 2: Page** — `useQuery(qk.reviews(filter), () => apiGet<AdminReviewList>("/api/v1/admin/reviews?..."))` with a status/reported filter toggle; `DataTable` columns: brand_id (short), rating (stars), body (truncated + escaped — it's plain text in React, safe), status pill, report_count, created_at. Row actions: Hide / Unhide / Remove buttons calling `apiPost(".../hide", {}, { headers: { "Idempotency-Key": crypto.randomUUID() } })` then invalidating the query. Follow `ManualQueuePage.tsx` structure verbatim for the table + `PageHeader`.

- [ ] **Step 3: Route + nav** — add `{ path: "/reviews", element: <ReviewsPage /> }` in `router.tsx` (import at top), and a sidebar entry in `Layout.tsx` next to an existing moderation-ish item (Fulfillment/Audit). Mirror the exact nav-item markup already there.

- [ ] **Step 4: Run + commit** — `pnpm --filter admin test` + `typecheck`. Commit `feat(admin/reviews): moderation queue (hide/unhide/remove)`.

---

### Task 10: Docs — module map, README, diagrams, ADR, security

**Files:**
- Create: `apps/api/src/yupay/modules/reviews/README.md`
- Modify: `docs/architecture/module-map.md` (add the reviews module + its edge to catalog)
- Create: `docs/architecture/sequence-diagrams/leave-review.mmd`, `.../review-moderation.mmd`
- Create: `docs/decisions/0039-reviews-and-ratings.md` (MADR template — new module, denormalized aggregate Approach A, post-moderation, SEO structured data)
- Modify: `docs/security/threat-model.md` (UGC/XSS surface, verified-purchase gate) + `docs/security/pii-handling.md` (author identity = display_name, never email)
- Modify: `docs/api/README.md` (note the reviews endpoints, idempotency behavior, 409 = already reviewed)
- Verify: `docs/api/openapi.json` current (already regenerated in Tasks 3-4)

- [ ] **Step 1** Write `README.md` inside the module (purpose, tables, public `api.py` surface, moderation model).
- [ ] **Step 2** Add the module to `module-map.md` with a one-line responsibility + the `catalog → reviews.api.get_stats` dependency edge.
- [ ] **Step 3** Author the two Mermaid sequence diagrams (leave-review: buyer → POST /reviews → eligibility check → insert + bump stats; moderation: report → threshold → auto-hide, and admin hide/unhide).
- [ ] **Step 4** Write ADR 0039 from `docs/decisions/0000-template.md`, referencing this plan + the spec.
- [ ] **Step 5** Update threat-model + pii-handling.
- [ ] **Step 6** Commit `docs(reviews): module map, ADR-0039, sequence diagrams, security notes`.

---

## Final verification (before opening the PR)

- [ ] `make lint typecheck test` green (Python + all TS workspaces).
- [ ] `make gen-api` produces no diff (OpenAPI + client committed).
- [ ] Single alembic head = `0034_reviews`.
- [ ] Coverage: reviews module ≥ 80%.
- [ ] All three locales updated for every new key (web `web.json` + miniapp `miniapp.json`).
- [ ] No PII in logs; UGC escaped on every render surface; guests cannot review.
- [ ] PR description: summary, screenshots (brand page rating, admin queue), testing notes, rollback (drop migration 0034 / feature is additive).
