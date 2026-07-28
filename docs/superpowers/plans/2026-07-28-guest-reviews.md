# Guest Reviews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let guest buyers (email + order UUID, no account) post a brand review after their order is delivered, reusing the existing order-access capability.

**Architecture:** Extend the `reviews` module to accept a guest actor. A guest authenticates exactly like the order-view path: `Authorization: Guest <jwt>` + `X-Guest-Email`, verified via `email_hash`. `Review.user_id` becomes nullable with a new `guest_email` column; uniqueness moves to `(order_id, brand_id)`. The web shows an inline review form on the order-status page for guests (they get no global WS delivered modal). Spec: `docs/superpowers/specs/2026-07-28-guest-reviews-design.md`.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 async · Alembic · Pydantic v2 · pytest + testcontainers (Postgres) · Next.js 15 (web) · TanStack Query · Vitest.

## Global Constraints

- Money in minor units as `Decimal`/string — not touched here, but never introduce floats.
- Every write endpoint requires an `Idempotency-Key` header (`>= MIN_IDEMPOTENCY_KEY_LENGTH` chars).
- Never log or return PII: `guest_email` is stored but never appears in a response body or a log line.
- `mypy --strict`, `ruff` (line-length 100, py312) for Python; `tsc` strict, eslint, prettier for TS.
- Reviews coverage gate: keep the `reviews` module green; add tests for every new branch.
- i18n: any new user-facing string lands in `ru.json`, `en.json`, `uz.json` in the same change (this plan expects to reuse existing `web.brandReviews.*` — add none unless a step says so).
- Web is bind-mounted into the dev `web` container running `next dev`; do NOT run `pnpm --filter web build` on the host while that container is up (it corrupts `.next` → 500). Verify types with `pnpm --filter web typecheck`; run the production build only after `docker compose stop web` (or in CI).
- Branch: `feat/guest-reviews`. Conventional Commits, scope `reviews` / `web/orders` / `api`.

---

### Task 1: DB model + migration — nullable user_id, guest_email, uniqueness swap

**Files:**

- Modify: `apps/api/src/yupay/modules/reviews/models.py`
- Create: `apps/api/migrations/versions/0035_guest_reviews.py`
- Test: `apps/api/tests/integration/test_reviews_service.py` (add a guest helper + insert test)

**Interfaces:**

- Produces: `Review.user_id: str | None`, `Review.guest_email: str | None`; unique `(order_id, brand_id)`; CHECK `ck_reviews_user_xor_guest`. A test helper `_make_guest_order(db, *, guest_email, sku_id, status="delivered") -> Order` added to `test_reviews_service.py` and imported by later tasks.

- [ ] **Step 1: Write the failing test** — add to `apps/api/tests/integration/test_reviews_service.py`:

```python
from yupay.modules.reviews.models import Review  # already imported


async def _make_guest_order(
    db: AsyncSession, *, guest_email: str, sku_id: str, status: str = "delivered"
) -> Order:
    moment = now()
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=guest_email,
        status=status,
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        created_at=moment,
        expires_at=moment + timedelta(hours=1),
        delivered_at=moment if status == "delivered" else None,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(), order_id=order.id, sku_id=sku_id, qty=1, unit_price_usd=Decimal("1.00")
        )
    )
    await db.flush()
    return order


async def test_guest_review_row_persists_and_is_unique_per_order_brand(
    db_session: AsyncSession,
) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    r1 = Review(
        id=new_id(), brand_id=brand.id, user_id=None, guest_email="g@x.com",
        order_id=order.id, rating=5, body=None, status="published", locale="ru",
    )
    db_session.add(r1)
    await db_session.flush()
    r2 = Review(
        id=new_id(), brand_id=brand.id, user_id=None, guest_email="g@x.com",
        order_id=order.id, rating=4, body=None, status="published", locale="ru",
    )
    db_session.add(r2)
    with pytest.raises(Exception):  # IntegrityError on uq_reviews_order_brand
        await db_session.flush()
```

- [ ] **Step 2: Run it, expect failure** — `make test-py ARGS="tests/integration/test_reviews_service.py::test_guest_review_row_persists_and_is_unique_per_order_brand"` (or `docker compose run --rm api pytest ...`). Expected: FAIL — `Review` has no `guest_email` / `user_id` is `NOT NULL`.

- [ ] **Step 3: Update the model** in `apps/api/src/yupay/modules/reviews/models.py`:

Change the `user_id` column and add `guest_email`; import `CITEXT`:

```python
from sqlalchemy.dialects.postgresql import CITEXT, UUID  # add CITEXT
```

```python
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    guest_email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
```

Replace `__table_args__`:

```python
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        CheckConstraint(
            "(user_id IS NULL) <> (guest_email IS NULL)", name="ck_reviews_user_xor_guest"
        ),
        UniqueConstraint("order_id", "brand_id", name="uq_reviews_order_brand"),
        Index("ix_reviews_brand_status_created", "brand_id", "status", "created_at"),
        Index("ix_reviews_user", "user_id"),
    )
```

- [ ] **Step 4: Write the migration** `apps/api/migrations/versions/0035_guest_reviews.py`:

```python
"""Guest reviews: nullable user_id, guest_email, one-review-per-(order,brand).

See docs/decisions/0039-reviews-and-ratings.md (guest-reviews amendment).

Revision ID: 0035_guest_reviews
Revises: 0034_reviews
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT

revision: str = "0035_guest_reviews"
down_revision: str | None = "0034_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("reviews", "user_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    op.add_column("reviews", sa.Column("guest_email", CITEXT(), nullable=True))
    op.create_check_constraint(
        "ck_reviews_user_xor_guest", "reviews", "(user_id IS NULL) <> (guest_email IS NULL)"
    )
    op.drop_constraint("uq_reviews_user_order_brand", "reviews", type_="unique")
    op.create_unique_constraint("uq_reviews_order_brand", "reviews", ["order_id", "brand_id"])


def downgrade() -> None:
    op.drop_constraint("uq_reviews_order_brand", "reviews", type_="unique")
    op.create_unique_constraint(
        "uq_reviews_user_order_brand", "reviews", ["user_id", "order_id", "brand_id"]
    )
    op.drop_constraint("ck_reviews_user_xor_guest", "reviews", type_="check")
    op.drop_column("reviews", "guest_email")
    op.alter_column(
        "reviews", "user_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False
    )
```

- [ ] **Step 5: Apply + run the test** — `make migrate` then re-run Step 2's command. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/reviews/models.py apps/api/migrations/versions/0035_guest_reviews.py apps/api/tests/integration/test_reviews_service.py
git commit -m "feat(reviews): guest-capable schema (nullable user_id, guest_email, order+brand unique)"
```

---

### Task 2: Shared request-actor resolver in `auth`

**Files:**

- Modify: `apps/api/src/yupay/modules/auth/deps.py`
- Test: `apps/api/tests/integration/test_reviews_routes.py` (exercised via Task 5; add a direct unit test here)

**Interfaces:**

- Produces: `RequestActor(user_id: str | None, guest_email: str | None, user: User | None)` and
  `async def resolve_request_actor(request: Request, db: AsyncSession) -> RequestActor`.
  Later tasks consume `resolve_request_actor` in the reviews routes.

- [ ] **Step 1: Write the failing test** — `apps/api/tests/integration/test_auth_request_actor.py` (new):

```python
"""resolve_request_actor: Bearer → user, Guest+email → guest, mismatches raise."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.modules.auth.deps import resolve_request_actor
from yupay.modules.auth.jwt import mint_access

from tests.integration.test_reviews_service import _make_user

pytestmark = pytest.mark.asyncio


def _req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


async def test_bearer_resolves_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, display_name="Alice")
    await db_session.commit()
    actor = await resolve_request_actor(
        _req({"Authorization": f"Bearer {mint_access(sub=user.id, sid='s1')}"}), db_session
    )
    assert actor.user_id == user.id and actor.guest_email is None and actor.user is not None


async def test_guest_requires_email_header(db_session: AsyncSession) -> None:
    from yupay.modules.auth.service import guest_checkout

    res = await guest_checkout(db_session, "g@x.com")
    with pytest.raises(ValidationError):
        await resolve_request_actor(
            _req({"Authorization": f"Guest {res.access_token}"}), db_session
        )


async def test_guest_email_mismatch_rejected(db_session: AsyncSession) -> None:
    from yupay.modules.auth.service import guest_checkout

    res = await guest_checkout(db_session, "g@x.com")
    with pytest.raises(UnauthorizedError):
        await resolve_request_actor(
            _req({"Authorization": f"Guest {res.access_token}", "X-Guest-Email": "other@x.com"}),
            db_session,
        )
```

- [ ] **Step 2: Run it, expect failure** — `make test-py ARGS="tests/integration/test_auth_request_actor.py"`. Expected: FAIL — `resolve_request_actor` does not exist.

- [ ] **Step 3: Implement** in `apps/api/src/yupay/modules/auth/deps.py` (append; add imports as needed):

```python
from dataclasses import dataclass

from starlette.requests import Request

from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.modules.auth.jwt import verify as verify_jwt
from yupay.modules.auth.security import email_hash
from yupay.modules.users.models import User


@dataclass(frozen=True)
class RequestActor:
    """Who is making a request: a logged-in user or an order-scoped guest."""

    user_id: str | None
    guest_email: str | None
    user: User | None


async def resolve_request_actor(request: Request, db: AsyncSession) -> RequestActor:
    """Bearer → user; ``Guest <jwt>`` + ``X-Guest-Email`` → guest (email_hash-checked).

    Mirrors the order-view auth so guest reviews inherit the same capability model.
    """
    auth = request.headers.get("Authorization")
    if not auth:
        raise UnauthorizedError("authorization required")
    scheme, _, token = auth.partition(" ")
    if scheme == "Bearer":
        from yupay.modules.auth.service import current_user as resolve_user

        user = await resolve_user(db, token)
        return RequestActor(user_id=user.id, guest_email=None, user=user)
    if scheme == "Guest":
        email = request.headers.get("X-Guest-Email")
        if not email:
            raise ValidationError("X-Guest-Email header required for guest actor")
        normalised = email.strip().lower()
        claims = verify_jwt(token, expected_kind="guest")
        expected = email_hash(normalised, get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        return RequestActor(user_id=None, guest_email=normalised, user=None)
    raise UnauthorizedError("invalid authorization scheme")
```

(If `AsyncSession` / `db_session` imports aren't already present in `deps.py`, add `from sqlalchemy.ext.asyncio import AsyncSession`.)

- [ ] **Step 4: Run it, expect pass** — same command as Step 2. Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/auth/deps.py apps/api/tests/integration/test_auth_request_actor.py
git commit -m "feat(auth): resolve_request_actor — shared Bearer/Guest actor resolution"
```

---

### Task 3: Actor-aware `create_review`

**Files:**

- Modify: `apps/api/src/yupay/modules/reviews/service.py`
- Test: `apps/api/tests/integration/test_reviews_service.py`

**Interfaces:**

- Consumes: `_make_guest_order` (Task 1), `_make_order`/`_make_user`/`_seed_brand`.
- Produces: `create_review(db, *, user_id: str | None, guest_email: str | None, order_id, brand_slug, rating, body, locale) -> Review`.

- [ ] **Step 1: Write the failing tests** — add to `test_reviews_service.py`:

```python
async def test_guest_create_review_success(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    review = await svc.create_review(
        db_session, user_id=None, guest_email="g@x.com", order_id=order.id,
        brand_slug="steam", rating=5, body="fast", locale="ru",
    )
    assert review.user_id is None and review.guest_email == "g@x.com"
    stats = (await svc.get_stats(db_session, [brand.id]))[brand.id]
    assert stats.count == 1


async def test_guest_wrong_email_forbidden(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session, user_id=None, guest_email="other@x.com", order_id=order.id,
            brand_slug="steam", rating=5, body=None, locale="ru",
        )


async def test_guest_not_delivered_forbidden(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(
        db_session, guest_email="g@x.com", sku_id=sku.id, status="fulfilling"
    )
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session, user_id=None, guest_email="g@x.com", order_id=order.id,
            brand_slug="steam", rating=5, body=None, locale="ru",
        )


async def test_guest_duplicate_conflict(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await svc.create_review(
        db_session, user_id=None, guest_email="g@x.com", order_id=order.id,
        brand_slug="steam", rating=5, body=None, locale="ru",
    )
    with pytest.raises(ConflictError):
        await svc.create_review(
            db_session, user_id=None, guest_email="g@x.com", order_id=order.id,
            brand_slug="steam", rating=4, body=None, locale="ru",
        )


async def test_user_cannot_review_guest_order(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, display_name="Bob")
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session, user_id=user.id, guest_email=None, order_id=order.id,
            brand_slug="steam", rating=5, body=None, locale="ru",
        )
```

Also update any EXISTING call in this test file that calls `svc.create_review(db, user_id=..., order_id=...)` to pass `guest_email=None` (keyword now required).

- [ ] **Step 2: Run, expect failure** — `make test-py ARGS="tests/integration/test_reviews_service.py -k guest or user_cannot"`. Expected: FAIL (`create_review` got unexpected keyword `guest_email`).

- [ ] **Step 3: Implement** — replace the `create_review` signature + ownership block in `service.py`:

```python
async def create_review(
    db: AsyncSession,
    *,
    user_id: str | None,
    guest_email: str | None,
    order_id: str,
    brand_slug: str,
    rating: int,
    body: str | None,
    locale: str,
) -> Review:
    """Create a published review for a delivered order that contains the brand.

    Exactly one of ``user_id`` / ``guest_email`` identifies the buyer. Raises
    ``NotFoundError`` (unknown brand/order), ``ForbiddenError`` (not the buyer,
    order not delivered, or brand not in the order), or ``ConflictError``
    (already reviewed this order).
    """
    if (user_id is None) == (guest_email is None):
        raise ValidationError("exactly one of user_id / guest_email is required")
    brand_id = await resolve_brand_id(db, brand_slug)

    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    if user_id is not None:
        if order.user_id != user_id:
            raise ForbiddenError("not your order")
    else:
        if order.guest_email is None or order.guest_email.lower() != guest_email:
            raise ForbiddenError("not your order")
    if order.status != "delivered":
        raise ForbiddenError("order not delivered")
    if not await _order_contains_brand(db, order_id, brand_id):
        raise ForbiddenError("brand not in order")

    review = Review(
        id=new_id(),
        brand_id=brand_id,
        user_id=user_id,
        guest_email=guest_email,
        order_id=order_id,
        rating=rating,
        body=body,
        status="published",
        locale=locale[:3],
    )
    try:
        async with db.begin_nested():
            db.add(review)
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError("already reviewed", code="already_reviewed") from exc

    await _bump_stats(db, brand_id, rating, +1)
    log.info("review.created", brand_id=brand_id, rating=rating)
    return review
```

- [ ] **Step 4: Run, expect pass** — same command as Step 2 plus the full file: `make test-py ARGS="tests/integration/test_reviews_service.py"`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/reviews/service.py apps/api/tests/integration/test_reviews_service.py
git commit -m "feat(reviews): actor-aware create_review (user or guest buyer)"
```

---

### Task 4: Public list LEFT-join + admin schema nullable

**Files:**

- Modify: `apps/api/src/yupay/modules/reviews/service.py` (`list_published`)
- Modify: `apps/api/src/yupay/modules/reviews/schemas.py` (`AdminReviewOut.user_id`)
- Test: `apps/api/tests/integration/test_reviews_service.py`

**Interfaces:**

- Consumes: `create_review` (Task 3). Produces: guest reviews appear in `list_published` with `author_name=None`.

- [ ] **Step 1: Write the failing test** — add to `test_reviews_service.py`:

```python
async def test_public_list_includes_guest_review_as_anonymous(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await svc.create_review(
        db_session, user_id=None, guest_email="g@x.com", order_id=order.id,
        brand_slug="steam", rating=5, body="great", locale="ru",
    )
    items, _ = await svc.list_published(db_session, brand_id=brand.id, limit=20, cursor=None)
    assert len(items) == 1
    assert items[0].author_name is None
    assert items[0].body == "great"
```

- [ ] **Step 2: Run, expect failure** — `make test-py ARGS="tests/integration/test_reviews_service.py::test_public_list_includes_guest_review_as_anonymous"`. Expected: FAIL — INNER join drops the null-`user_id` row (0 items).

- [ ] **Step 3: Implement** — in `list_published`, change the join to an outer join:

```python
    stmt = (
        select(Review, User.display_name)
        .outerjoin(User, User.id == Review.user_id)
        .where(Review.brand_id == brand_id, Review.status == "published")
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit + 1)
    )
```

And in `schemas.py` make the admin projection tolerate guests:

```python
class AdminReviewOut(BaseModel):
    id: str
    brand_id: str
    user_id: str | None
    order_id: str
    ...
```

- [ ] **Step 4: Run, expect pass** — same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/reviews/service.py apps/api/src/yupay/modules/reviews/schemas.py apps/api/tests/integration/test_reviews_service.py
git commit -m "feat(reviews): show guest reviews (LEFT join) + nullable admin user_id"
```

---

### Task 5: POST `/reviews` via resolver + `GET /reviews/eligibility`

**Files:**

- Modify: `apps/api/src/yupay/modules/reviews/routes.py`
- Modify: `apps/api/src/yupay/modules/reviews/service.py` (add `review_eligibility`)
- Modify: `apps/api/src/yupay/modules/reviews/schemas.py` (add `ReviewEligibilityOut`)
- Test: `apps/api/tests/integration/test_reviews_routes.py`
- Regenerate: `docs/api/openapi.json`

**Interfaces:**

- Consumes: `resolve_request_actor` (Task 2), `create_review` (Task 3).
- Produces: `POST /reviews` accepting Bearer or Guest; `GET /reviews/eligibility?order_id=` →
  `ReviewEligibilityOut(brand_slug: str | None, delivered: bool, already_reviewed: bool)`.

- [ ] **Step 1: Write the failing tests** — add to `test_reviews_routes.py`:

```python
async def _guest_token(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/v1/auth/guest", json={"email": email})
    assert r.status_code == 200
    return r.json()["access_token"]


async def test_guest_can_post_and_list_shows_anonymous(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await db_session.commit()
    token = await _guest_token(integration_client, "g@x.com")
    r = await integration_client.post(
        "/api/v1/reviews",
        headers={
            "Authorization": f"Guest {token}",
            "X-Guest-Email": "g@x.com",
            "Idempotency-Key": _KEY,
        },
        json={"order_id": order.id, "brand_slug": "steam", "rating": 5, "body": "fast"},
    )
    assert r.status_code == 201
    assert r.json()["author_name"] is None
    lst = await integration_client.get("/api/v1/reviews/brands/steam")
    assert lst.json()["stats"]["count"] == 1


async def test_guest_wrong_email_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await db_session.commit()
    token = await _guest_token(integration_client, "g@x.com")
    r = await integration_client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Guest {token}", "X-Guest-Email": "evil@x.com",
                 "Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": "steam", "rating": 5},
    )
    assert r.status_code == 401


async def test_eligibility_guest_delivered_then_reviewed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await db_session.commit()
    token = await _guest_token(integration_client, "g@x.com")
    h = {"Authorization": f"Guest {token}", "X-Guest-Email": "g@x.com"}
    e1 = await integration_client.get(f"/api/v1/reviews/eligibility?order_id={order.id}", headers=h)
    assert e1.json() == {"brand_slug": "steam", "delivered": True, "already_reviewed": False}
    await integration_client.post(
        "/api/v1/reviews", headers={**h, "Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": "steam", "rating": 5},
    )
    e2 = await integration_client.get(f"/api/v1/reviews/eligibility?order_id={order.id}", headers=h)
    assert e2.json()["already_reviewed"] is True
```

- [ ] **Step 2: Run, expect failure** — `make test-py ARGS="tests/integration/test_reviews_routes.py -k guest or eligibility"`. Expected: FAIL (route still requires Bearer `current_user`; no eligibility route).

- [ ] **Step 3a: Add the eligibility schema** to `schemas.py` (and `__all__`):

```python
class ReviewEligibilityOut(BaseModel):
    brand_slug: str | None
    delivered: bool
    already_reviewed: bool
```

- [ ] **Step 3b: Add `review_eligibility` to `service.py`**:

```python
async def _first_brand_of_order(db: AsyncSession, order_id: str) -> tuple[str, str] | None:
    """(brand_id, brand_slug) of the order's first item, or None."""
    row = (
        await db.execute(
            select(Brand.id, Brand.slug)
            .select_from(OrderItem)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(OrderItem.order_id == order_id)
            .limit(1)
        )
    ).first()
    return (row.id, row.slug) if row else None


async def review_eligibility(
    db: AsyncSession, *, order_id: str, user_id: str | None, guest_email: str | None
) -> tuple[str | None, bool, bool]:
    """(brand_slug, delivered, already_reviewed) for an order the actor owns."""
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    if user_id is not None:
        if order.user_id != user_id:
            raise ForbiddenError("not your order")
    elif order.guest_email is None or order.guest_email.lower() != guest_email:
        raise ForbiddenError("not your order")
    brand = await _first_brand_of_order(db, order_id)
    if brand is None:
        return None, order.status == "delivered", False
    brand_id, brand_slug = brand
    reviewed = (
        await db.execute(
            select(Review.id).where(Review.order_id == order_id, Review.brand_id == brand_id)
        )
    ).first() is not None
    return brand_slug, order.status == "delivered", reviewed
```

Add `Brand` to the existing `from yupay.modules.catalog.models import ...` line if not present (it already imports `Brand, Product, Sku`).

- [ ] **Step 3c: Rewrite the POST route + add the eligibility route** in `routes.py`. Replace the `current_user`-based `create_review_route` with:

```python
from fastapi import Request
from yupay.modules.auth.deps import resolve_request_actor
from yupay.modules.reviews.schemas import ReviewEligibilityOut  # add to imports


@router.post(
    "", response_model=ReviewOut, status_code=status.HTTP_201_CREATED,
    summary="Submit a review for a delivered order (user or guest)",
)
async def create_review_route(
    body: ReviewCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> ReviewOut:
    _require_idempotency_key(idempotency_key)
    actor = await resolve_request_actor(request, db)
    locale = actor.user.locale if actor.user else (request.headers.get("Accept-Language") or "ru")
    review = await svc.create_review(
        db, user_id=actor.user_id, guest_email=actor.guest_email, order_id=body.order_id,
        brand_slug=body.brand_slug, rating=body.rating, body=body.body, locale=locale,
    )
    return ReviewOut(
        id=review.id, rating=review.rating, body=review.body,
        author_name=actor.user.display_name if actor.user else None,
        created_at=review.created_at,
    )


@router.get(
    "/eligibility", response_model=ReviewEligibilityOut,
    summary="Whether the actor's order can be reviewed / already was",
)
async def review_eligibility_route(
    order_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ReviewEligibilityOut:
    actor = await resolve_request_actor(request, db)
    brand_slug, delivered, already = await svc.review_eligibility(
        db, order_id=order_id, user_id=actor.user_id, guest_email=actor.guest_email
    )
    return ReviewEligibilityOut(
        brand_slug=brand_slug, delivered=delivered, already_reviewed=already
    )
```

Keep the existing `GET /reviews/mine` and `report` routes (still `current_user`).
Note: register `/eligibility` BEFORE `/{...}` dynamic routes is not a concern here — there are none that collide; but keep it above `report` for readability.

- [ ] **Step 4: Run, expect pass** — `make test-py ARGS="tests/integration/test_reviews_routes.py"`. Expected: PASS (all, including existing Bearer tests still green).

- [ ] **Step 5: Regenerate the API schema** — `make gen-api`. Confirm `docs/api/openapi.json` now has the guest auth note on `POST /reviews` and the new `GET /reviews/eligibility`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/reviews/routes.py apps/api/src/yupay/modules/reviews/service.py apps/api/src/yupay/modules/reviews/schemas.py apps/api/tests/integration/test_reviews_routes.py docs/api/openapi.json packages/api-client
git commit -m "feat(reviews): guest-capable POST + eligibility endpoint"
```

---

### Task 6: Web client helpers — guest token mint, guest submit, eligibility

**Files:**

- Modify: `apps/web/src/lib/reviews.ts`
- Create: `apps/web/src/lib/guest.ts`
- Modify: `apps/web/src/components/store/PurchasePanel.tsx` (use the shared mint helper)
- Test: `apps/web/src/lib/reviews.test.ts` (new)

**Interfaces:**

- Produces: `mintGuestToken(email: string): Promise<string>`;
  `submitReview(body, opts?: { guestEmail?: string })`;
  `getReviewEligibility(orderId: string, opts?: { guestEmail?: string }): Promise<ReviewEligibility>`
  where `ReviewEligibility = { brand_slug: string | null; delivered: boolean; already_reviewed: boolean }`.

- [ ] **Step 1: Write the failing test** — `apps/web/src/lib/reviews.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { getReviewEligibility } from "./reviews";

afterEach(() => vi.restoreAllMocks());

describe("getReviewEligibility (guest)", () => {
  it("sends Guest auth + X-Guest-Email and no Bearer", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ brand_slug: "steam", delivered: true, already_reviewed: false }),
          { status: 200 },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    // mintGuestToken hits /auth/guest first:
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "gt" }), { status: 200 }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ brand_slug: "steam", delivered: true, already_reviewed: false }),
        { status: 200 },
      ),
    );
    const res = await getReviewEligibility("ord-1", { guestEmail: "G@x.com " });
    expect(res.brand_slug).toBe("steam");
    const headers = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Guest gt");
    expect(headers.get("X-Guest-Email")).toBe("g@x.com");
  });
});
```

- [ ] **Step 2: Run, expect failure** — `pnpm --filter web test src/lib/reviews.test.ts`. Expected: FAIL — `getReviewEligibility` not exported.

- [ ] **Step 3a: Create `apps/web/src/lib/guest.ts`**:

```ts
const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Mint a short-lived guest token for an email (freely mintable; carries the
 *  email hash). Used by guest checkout and guest review submit. */
export async function mintGuestToken(email: string): Promise<string> {
  const r = await fetch(`${API}/api/v1/auth/guest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase() }),
  });
  if (!r.ok) throw new Error("guest-token");
  const { access_token } = (await r.json()) as { access_token: string };
  return access_token;
}
```

- [ ] **Step 3b: Extend `apps/web/src/lib/reviews.ts`** — add types + guest-aware helpers:

```ts
import { mintGuestToken } from "./guest";

export interface ReviewEligibility {
  brand_slug: string | null;
  delivered: boolean;
  already_reviewed: boolean;
}

async function guestHeaders(email: string): Promise<Record<string, string>> {
  const token = await mintGuestToken(email);
  return { Authorization: `Guest ${token}`, "X-Guest-Email": email.trim().toLowerCase() };
}

export async function submitReview(
  body: { order_id: string; brand_slug: string; rating: number; body?: string },
  opts: { guestEmail?: string } = {},
): Promise<Review> {
  const extra = opts.guestEmail ? await guestHeaders(opts.guestEmail) : {};
  return apiFetch<Review>("/reviews", {
    method: "POST",
    body,
    anonymous: Boolean(opts.guestEmail),
    headers: { "Idempotency-Key": crypto.randomUUID(), ...extra },
  });
}

export async function getReviewEligibility(
  orderId: string,
  opts: { guestEmail?: string } = {},
): Promise<ReviewEligibility> {
  const extra = opts.guestEmail ? await guestHeaders(opts.guestEmail) : {};
  return apiFetch<ReviewEligibility>(
    `/reviews/eligibility?order_id=${encodeURIComponent(orderId)}`,
    { anonymous: Boolean(opts.guestEmail), headers: extra },
  );
}
```

(The old `submitReview` signature gains an optional 2nd arg — existing callers pass one arg and still compile.)

- [ ] **Step 3c: DRY the checkout mint** — in `PurchasePanel.tsx`, replace the inline guest-token fetch (the `POST /auth/guest` block ~lines 460-467) with:

```ts
import { mintGuestToken } from "@/lib/guest";
// ...
const access_token = await mintGuestToken(email);
auth = { Authorization: `Guest ${access_token}` };
emailSuffix = `?email=${encodeURIComponent(email)}`;
```

- [ ] **Step 4: Run, expect pass** — `pnpm --filter web test src/lib/reviews.test.ts` then `pnpm --filter web typecheck`. Expected: PASS + clean types.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/guest.ts apps/web/src/lib/reviews.ts apps/web/src/components/store/PurchasePanel.tsx apps/web/src/lib/reviews.test.ts
git commit -m "feat(web/reviews): guest-token helper, guest submit + eligibility client"
```

---

### Task 7: Inline guest review form on the order-status page

**Files:**

- Create: `apps/web/src/components/order/GuestReviewPanel.tsx`
- Modify: `apps/web/src/components/order/OrderStatus.tsx`
- Test: `apps/web/src/components/order/GuestReviewPanel.test.tsx` (new)

**Interfaces:**

- Consumes: `getReviewEligibility`, `submitReview` (Task 6).
- Produces: a guest-only inline review form rendered on the order page when the order is
  delivered and not yet reviewed. Logged-in users keep the existing Link-to-brand CTA unchanged.

- [ ] **Step 1: Write the failing test** — `GuestReviewPanel.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";

import { GuestReviewPanel } from "./GuestReviewPanel";
import * as reviews from "@/lib/reviews";

const messages = {
  web: {
    brandReviews: {
      formTitle: "Ваш отзыв",
      ratingLabel: "Оценка",
      commentLabel: "Комментарий",
      submit: "Отправить",
      submitting: "…",
      thanks: "Спасибо!",
      alreadyReviewed: "Уже оценено",
      error: "Ошибка",
    },
  },
};

afterEach(() => vi.restoreAllMocks());

function wrap(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale="ru" messages={messages}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

it("renders the form when eligible and not yet reviewed", async () => {
  vi.spyOn(reviews, "getReviewEligibility").mockResolvedValue({
    brand_slug: "steam",
    delivered: true,
    already_reviewed: false,
  });
  wrap(<GuestReviewPanel orderId="o1" email="g@x.com" />);
  await waitFor(() => expect(screen.getByText("Ваш отзыв")).toBeInTheDocument());
});

it("renders nothing when already reviewed", async () => {
  vi.spyOn(reviews, "getReviewEligibility").mockResolvedValue({
    brand_slug: "steam",
    delivered: true,
    already_reviewed: true,
  });
  const { container } = wrap(<GuestReviewPanel orderId="o1" email="g@x.com" />);
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});
```

- [ ] **Step 2: Run, expect failure** — `pnpm --filter web test src/components/order/GuestReviewPanel.test.tsx`. Expected: FAIL — module not found.

- [ ] **Step 3a: Create `GuestReviewPanel.tsx`**:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { buttonStyles } from "@/lib/button";
import { ApiError } from "@/lib/client";
import { getReviewEligibility, submitReview } from "@/lib/reviews";

/**
 * Inline review form for a GUEST on their order-status page. A guest gets no
 * global delivered modal (the realtime channel is user-only), so the review
 * ask lives here, using the email the page already holds — no PII in any URL.
 * Eligibility (delivered + not already reviewed) is checked server-side.
 */
export function GuestReviewPanel({ orderId, email }: { orderId: string; email: string }) {
  const t = useTranslations("web.brandReviews");
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [body, setBody] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");

  const eligibility = useQuery({
    queryKey: ["review-eligibility", orderId],
    queryFn: () => getReviewEligibility(orderId, { guestEmail: email }),
  });

  const e = eligibility.data;
  if (!e || !e.delivered || !e.brand_slug || e.already_reviewed) return null;
  if (state === "done")
    return <p className="text-primary mt-4 text-sm font-semibold">{t("thanks")}</p>;
  if (state === "already")
    return <p className="text-tx-mute mt-4 text-sm">{t("alreadyReviewed")}</p>;

  const brandSlug = e.brand_slug;
  async function onSubmit(ev: React.SyntheticEvent) {
    ev.preventDefault();
    if (rating < 1) return;
    setState("sending");
    try {
      await submitReview(
        {
          order_id: orderId,
          brand_slug: brandSlug,
          rating,
          ...(body.trim() ? { body: body.trim() } : {}),
        },
        { guestEmail: email },
      );
      setState("done");
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  const active = hover || rating;
  return (
    <form onSubmit={onSubmit} className="border-border bg-card mt-6 rounded-2xl border p-5">
      <p className="text-sm font-semibold">{t("formTitle")}</p>
      <div className="mt-3">
        <div className="text-tx-mute mb-1.5 text-xs">{t("ratingLabel")}</div>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              aria-label={String(n)}
              onClick={() => setRating(n)}
              onMouseEnter={() => setHover(n)}
              onMouseLeave={() => setHover(0)}
              className="p-0.5"
            >
              <Star size={26} className={n <= active ? "fill-gold text-gold" : "text-white/25"} />
            </button>
          ))}
        </div>
      </div>
      <label className="mt-4 block">
        <span className="text-tx-mute mb-1.5 block text-xs">{t("commentLabel")}</span>
        <textarea
          value={body}
          onChange={(ev) => setBody(ev.target.value.slice(0, 2000))}
          rows={3}
          className="border-border bg-background focus-visible:border-primary w-full resize-none rounded-xl border px-3 py-2 text-sm outline-none"
        />
      </label>
      {state === "error" && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
      <button
        type="submit"
        disabled={rating < 1 || state === "sending"}
        className={buttonStyles({ size: "sm", className: "mt-4 disabled:opacity-50" })}
      >
        {state === "sending" ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}
```

- [ ] **Step 3b: Wire it into `OrderStatus.tsx`** — render the guest panel when the viewer is a guest (has `email`, no logged-in `user`) on a delivered order. After the existing `canRate` Link block, add:

```tsx
{
  status === "delivered" && !user && email && brandSlug && (
    <GuestReviewPanel orderId={order.data.id} email={email} />
  );
}
```

Add the import: `import { GuestReviewPanel } from "./GuestReviewPanel";`. Leave the existing logged-in `canRate` Link untouched.

- [ ] **Step 4: Run, expect pass** — `pnpm --filter web test src/components/order/GuestReviewPanel.test.tsx` then `pnpm --filter web typecheck`. Expected: PASS + clean types.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/order/GuestReviewPanel.tsx apps/web/src/components/order/OrderStatus.tsx apps/web/src/components/order/GuestReviewPanel.test.tsx
git commit -m "feat(web/orders): inline guest review form on the order page"
```

---

### Task 8: Docs + full verification

**Files:**

- Modify: `docs/decisions/0039-reviews-and-ratings.md` (amendment)
- Modify: `apps/api/src/yupay/modules/reviews/README.md`
- Modify/Create: `docs/architecture/sequence-diagrams/reviews-guest.mmd`

- [ ] **Step 1: Amend ADR-0039** — append a dated "Guest reviews" section: the actor model (Bearer or `Guest`+`X-Guest-Email`), `user_id` nullable + `guest_email` + CHECK, uniqueness now `(order_id, brand_id)`, guest reviews shown as the anonymous label, capability = order UUID + email (same as order view), reporting stays user-only.

- [ ] **Step 2: Update the reviews `README.md`** — note the guest path on `POST /reviews`, the new `GET /reviews/eligibility`, and that `guest_email` is never returned/logged.

- [ ] **Step 3: Add the sequence diagram** `docs/architecture/sequence-diagrams/reviews-guest.mmd` (Mermaid): guest → web (mint guest token) → `GET /reviews/eligibility` → inline form → `POST /reviews` (`Guest` + `X-Guest-Email`) → `resolve_request_actor` → `create_review` → stats bump.

- [ ] **Step 4: Full backend gate** — `make lint typecheck test-py` (ruff + mypy strict + pytest, incl. reviews + auth). Expected: green. Fix any drift.

- [ ] **Step 5: Full web gate** — `pnpm --filter web typecheck && pnpm --filter web test && pnpm exec prettier --check apps/web packages`. For the production build, first `docker compose stop web`, then `pnpm --filter web build`, then `docker compose up -d web` (avoids the `.next` bind-mount trap). Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add docs/decisions/0039-reviews-and-ratings.md apps/api/src/yupay/modules/reviews/README.md docs/architecture/sequence-diagrams/reviews-guest.mmd
git commit -m "docs(reviews): guest-reviews ADR amendment, README, sequence diagram"
```

---

## Self-Review

**Spec coverage:** model change (T1) · actor resolver (T2) · actor-aware create (T3) · public LEFT-join + admin nullable (T4) · guest POST + eligibility (T5) · frontend client + CTA gating (T6, T7) · security via reused capability + one-per-order unique + idempotency + no PII in responses/logs (T1/T3/T5) · tests across service+routes (T1–T5) · docs/ADR/README/openapi/diagram (T5, T8). Web-only, no Mini App work — matches spec scope.

**Placeholder scan:** no TBD/TODO; every code and test step carries full code; commands have expected outcomes.

**Type consistency:** `RequestActor(user_id, guest_email, user)` defined in T2 and consumed verbatim in T5. `create_review(..., user_id, guest_email, ...)` defined T3, called T5. `ReviewEligibility`/`ReviewEligibilityOut` fields (`brand_slug|null`, `delivered`, `already_reviewed`) identical across service (T5), schema (T5), TS client (T6), component (T7). `mintGuestToken`/`submitReview(opts.guestEmail)`/`getReviewEligibility` names match between T6 and T7.
