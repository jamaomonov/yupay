"""Reviews service: eligibility, stats transactionality, reporting, moderation."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.errors import ConflictError, ForbiddenError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.reviews import service as svc
from yupay.modules.reviews.models import BrandRatingStats, Review
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _make_user(db: AsyncSession, *, display_name: str | None = None) -> User:
    user = User(
        id=new_id(),
        email=None,
        display_name=display_name,
        locale="ru",
        display_currency="USD",
        roles=[],
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_brand(db: AsyncSession, slug: str) -> tuple[Brand, Sku]:
    cat = Category(id=new_id(), slug=f"cat-{slug}", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Cat")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug=slug, category_id=cat.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name=slug.title())]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug=f"{slug}-p", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="P")]
    db.add(product)
    await db.flush()
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"{slug}-1",
        price_usd=Decimal("1.00"),
        cost_usdt=None,
    )
    db.add(sku)
    await db.flush()
    return brand, sku


async def _make_order(
    db: AsyncSession, *, user_id: str, sku_id: str, status: str = "delivered"
) -> Order:
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        guest_email=None,
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


async def test_create_review_happy_path_bumps_stats(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, display_name="Alice")
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)

    review = await svc.create_review(
        db_session,
        user_id=user.id,
        guest_email=None,
        order_id=order.id,
        brand_slug=brand.slug,
        rating=5,
        body="great",
        locale="ru",
    )
    assert review.status == "published"
    stats = (await svc.get_stats(db_session, [brand.id]))[brand.id]
    assert stats.count == 1
    assert float(stats.avg) == 5.0
    assert stats.count_5 == 1


async def test_duplicate_same_order_brand_conflicts(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    brand, sku = await _seed_brand(db_session, "pubg")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)
    await svc.create_review(
        db_session,
        user_id=user.id,
        guest_email=None,
        order_id=order.id,
        brand_slug=brand.slug,
        rating=4,
        body=None,
        locale="ru",
    )
    with pytest.raises(ConflictError):
        await svc.create_review(
            db_session,
            user_id=user.id,
            guest_email=None,
            order_id=order.id,
            brand_slug=brand.slug,
            rating=3,
            body=None,
            locale="ru",
        )


async def test_undelivered_order_forbidden(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    brand, sku = await _seed_brand(db_session, "mlbb")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id, status="paid")
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session,
            user_id=user.id,
            guest_email=None,
            order_id=order.id,
            brand_slug=brand.slug,
            rating=4,
            body=None,
            locale="ru",
        )


async def test_brand_not_in_order_forbidden(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    brand, sku = await _seed_brand(db_session, "roblox")
    other_brand, _ = await _seed_brand(db_session, "valorant")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session,
            user_id=user.id,
            guest_email=None,
            order_id=order.id,
            brand_slug=other_brand.slug,
            rating=4,
            body=None,
            locale="ru",
        )


async def test_not_your_order_forbidden(db_session: AsyncSession) -> None:
    buyer = await _make_user(db_session)
    stranger = await _make_user(db_session)
    brand, sku = await _seed_brand(db_session, "genshin")
    order = await _make_order(db_session, user_id=buyer.id, sku_id=sku.id)
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session,
            user_id=stranger.id,
            guest_email=None,
            order_id=order.id,
            brand_slug=brand.slug,
            rating=4,
            body=None,
            locale="ru",
        )


async def _make_published_review(db: AsyncSession, brand: Brand, sku: Sku) -> Review:
    user = await _make_user(db, display_name="Buyer")
    order = await _make_order(db, user_id=user.id, sku_id=sku.id)
    return await svc.create_review(
        db,
        user_id=user.id,
        guest_email=None,
        order_id=order.id,
        brand_slug=brand.slug,
        rating=5,
        body="ok",
        locale="ru",
    )


async def test_report_threshold_auto_hides(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam2")
    review = await _make_published_review(db_session, brand, sku)
    for _ in range(3):
        reporter = await _make_user(db_session)
        await svc.report_review(
            db_session, review_id=review.id, reporter_user_id=reporter.id, reason=None
        )
    await db_session.refresh(review)
    assert review.status == "hidden"
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 0


async def test_duplicate_report_is_noop(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam3")
    review = await _make_published_review(db_session, brand, sku)
    reporter = await _make_user(db_session)
    await svc.report_review(
        db_session, review_id=review.id, reporter_user_id=reporter.id, reason=None
    )
    # same reporter again → swallowed
    await svc.report_review(
        db_session, review_id=review.id, reporter_user_id=reporter.id, reason=None
    )
    await db_session.refresh(review)
    assert review.status == "published"


async def test_admin_hide_then_unhide_adjusts_stats(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam4")
    review = await _make_published_review(db_session, brand, sku)
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 1

    await svc.admin_set_status(db_session, review_id=review.id, status="hidden")
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 0

    await svc.admin_set_status(db_session, review_id=review.id, status="published")
    assert (await svc.get_stats(db_session, [brand.id]))[brand.id].count == 1


async def test_list_published_paginates_newest_first(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam5")
    for _ in range(3):
        await _make_published_review(db_session, brand, sku)
    page1, cursor = await svc.list_published(db_session, brand_id=brand.id, limit=2, cursor=None)
    assert len(page1) == 2
    assert cursor is not None
    page2, cursor2 = await svc.list_published(db_session, brand_id=brand.id, limit=2, cursor=cursor)
    assert len(page2) == 1
    assert cursor2 is None
    # Newest-first ordering: page1[0] is at least as new as page1[1].
    assert page1[0].created_at >= page1[1].created_at
    # Each review's author is a logged-in user seeded with display_name="Buyer"
    # (see _make_published_review) — the outer join to User must resolve it.
    assert all(item.author_name == "Buyer" for item in [*page1, *page2])


async def test_recompute_fixes_drift(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam6")
    brand_id = brand.id
    await _make_published_review(db_session, brand, sku)
    # Corrupt the stats row via a raw UPDATE (bypasses the ORM identity map,
    # which recompute's Core upsert would otherwise not refresh).
    await db_session.execute(
        update(BrandRatingStats)
        .where(BrandRatingStats.brand_id == brand_id)
        .values(count=99, avg=Decimal("1.00"))
    )

    touched = await svc.recompute_all_stats(db_session)
    assert touched == 1
    # Read fresh scalars (not the entity) so the assertion sees the DB, not the
    # session's stale identity-mapped stats object.
    row = (
        await db_session.execute(
            select(BrandRatingStats.count.label("cnt"), BrandRatingStats.avg).where(
                BrandRatingStats.brand_id == brand_id
            )
        )
    ).one()
    assert row.cnt == 1
    assert float(row.avg) == 5.0


async def test_guest_create_review_success(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    review = await svc.create_review(
        db_session,
        user_id=None,
        guest_email="g@x.com",
        order_id=order.id,
        brand_slug="steam",
        rating=5,
        body="fast",
        locale="ru",
    )
    assert review.user_id is None
    assert review.guest_email == "g@x.com"
    stats = (await svc.get_stats(db_session, [brand.id]))[brand.id]
    assert stats.count == 1


async def test_guest_wrong_email_forbidden(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session,
            user_id=None,
            guest_email="other@x.com",
            order_id=order.id,
            brand_slug="steam",
            rating=5,
            body=None,
            locale="ru",
        )


async def test_guest_not_delivered_forbidden(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(
        db_session, guest_email="g@x.com", sku_id=sku.id, status="fulfilling"
    )
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session,
            user_id=None,
            guest_email="g@x.com",
            order_id=order.id,
            brand_slug="steam",
            rating=5,
            body=None,
            locale="ru",
        )


async def test_guest_duplicate_conflict(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await svc.create_review(
        db_session,
        user_id=None,
        guest_email="g@x.com",
        order_id=order.id,
        brand_slug="steam",
        rating=5,
        body=None,
        locale="ru",
    )
    with pytest.raises(ConflictError):
        await svc.create_review(
            db_session,
            user_id=None,
            guest_email="g@x.com",
            order_id=order.id,
            brand_slug="steam",
            rating=4,
            body=None,
            locale="ru",
        )


async def test_user_cannot_review_guest_order(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, display_name="Bob")
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    with pytest.raises(ForbiddenError):
        await svc.create_review(
            db_session,
            user_id=user.id,
            guest_email=None,
            order_id=order.id,
            brand_slug="steam",
            rating=5,
            body=None,
            locale="ru",
        )


async def test_guest_review_row_persists_and_is_unique_per_order_brand(
    db_session: AsyncSession,
) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    r1 = Review(
        id=new_id(),
        brand_id=brand.id,
        user_id=None,
        guest_email="g@x.com",
        order_id=order.id,
        rating=5,
        body=None,
        status="published",
        locale="ru",
    )
    db_session.add(r1)
    await db_session.flush()
    r2 = Review(
        id=new_id(),
        brand_id=brand.id,
        user_id=None,
        guest_email="g@x.com",
        order_id=order.id,
        rating=4,
        body=None,
        status="published",
        locale="ru",
    )
    db_session.add(r2)
    with pytest.raises(IntegrityError):  # IntegrityError on uq_reviews_order_brand
        await db_session.flush()


async def test_public_list_includes_guest_review_as_anonymous(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await svc.create_review(
        db_session,
        user_id=None,
        guest_email="g@x.com",
        order_id=order.id,
        brand_slug="steam",
        rating=5,
        body="great",
        locale="ru",
    )
    items, _ = await svc.list_published(db_session, brand_id=brand.id, limit=20, cursor=None)
    assert len(items) == 1
    assert items[0].author_name is None
    assert items[0].body == "great"
