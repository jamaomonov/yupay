"""Business logic for brand reviews, moderation, and denormalized rating stats.

Reviews are anchored to a delivered order (proof of purchase) and are immutable
once posted. Only ``published`` reviews count toward :class:`BrandRatingStats`,
which is bumped transactionally on every status change so the storefront can read
aggregates cheaply. See docs/decisions/0039-reviews-and-ratings.md.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.reviews.models import (
    REVIEW_STATUSES,
    BrandRatingStats,
    Review,
    ReviewReport,
)
from yupay.modules.reviews.schemas import ReviewOut
from yupay.modules.users.models import User

log = get_logger("yupay.reviews.service")

_REPORT_AUTO_HIDE_THRESHOLD = 3
_DEFAULT_LIST_LIMIT = 20
_MAX_LIST_LIMIT = 50
_STAR_COLUMNS = {1: "count_1", 2: "count_2", 3: "count_3", 4: "count_4", 5: "count_5"}


async def resolve_brand_id(db: AsyncSession, slug: str) -> str:
    """Return a brand's id from its slug, or raise ``NotFoundError``."""
    brand_id = (await db.execute(select(Brand.id).where(Brand.slug == slug))).scalar_one_or_none()
    if brand_id is None:
        raise NotFoundError("brand not found")
    return brand_id


async def _order_contains_brand(db: AsyncSession, order_id: str, brand_id: str) -> bool:
    """True if any item of the order belongs to the given brand (sku→product→brand)."""
    hit = (
        await db.execute(
            select(Product.brand_id)
            .select_from(OrderItem)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Product, Product.id == Sku.product_id)
            .where(OrderItem.order_id == order_id, Product.brand_id == brand_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return hit is not None


async def _ensure_stats_row(db: AsyncSession, brand_id: str) -> None:
    """Create a zeroed stats row for the brand if none exists (race-safe)."""
    await db.execute(
        pg_insert(BrandRatingStats)
        .values(brand_id=brand_id)
        .on_conflict_do_nothing(index_elements=["brand_id"])
    )


async def _bump_stats(db: AsyncSession, brand_id: str, rating: int, sign: int) -> None:
    """Apply one review's contribution (``sign`` = +1 add, -1 remove) under a row lock."""
    await _ensure_stats_row(db, brand_id)
    row = (
        await db.execute(
            select(BrandRatingStats).where(BrandRatingStats.brand_id == brand_id).with_for_update()
        )
    ).scalar_one()
    row.count = max(0, row.count + sign)
    row.sum_rating = max(0, row.sum_rating + sign * rating)
    col = _STAR_COLUMNS[rating]
    setattr(row, col, max(0, getattr(row, col) + sign))
    row.avg = (
        (Decimal(row.sum_rating) / Decimal(row.count)).quantize(Decimal("0.01"))
        if row.count
        else Decimal("0.00")
    )
    row.updated_at = now()


async def create_review(
    db: AsyncSession,
    *,
    user_id: str,
    order_id: str,
    brand_slug: str,
    rating: int,
    body: str | None,
    locale: str,
) -> Review:
    """Create a published review for a delivered order that contains the brand.

    Raises ``NotFoundError`` (unknown brand/order), ``ForbiddenError`` (not the
    buyer, order not delivered, or brand not in the order), or ``ConflictError``
    (already reviewed this order+brand).
    """
    brand_id = await resolve_brand_id(db, brand_slug)

    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    if order.user_id != user_id:
        raise ForbiddenError("not your order")
    if order.status != "delivered":
        raise ForbiddenError("order not delivered")
    if not await _order_contains_brand(db, order_id, brand_id):
        raise ForbiddenError("brand not in order")

    review = Review(
        id=new_id(),
        brand_id=brand_id,
        user_id=user_id,
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


def _encode_cursor(created_at: datetime, review_id: str) -> str:
    raw = f"{created_at.isoformat()}|{review_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        iso, review_id = raw.split("|", 1)
        return datetime.fromisoformat(iso), review_id
    except (ValueError, TypeError) as exc:
        raise ValidationError("invalid cursor") from exc


async def list_published(
    db: AsyncSession, *, brand_id: str, limit: int, cursor: str | None
) -> tuple[list[ReviewOut], str | None]:
    """Return a keyset page of published reviews (newest first) + the next cursor."""
    limit = max(1, min(limit, _MAX_LIST_LIMIT))
    stmt = (
        select(Review, User.display_name)
        .join(User, User.id == Review.user_id)
        .where(Review.brand_id == brand_id, Review.status == "published")
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        c_created, c_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Review.created_at < c_created)
            | ((Review.created_at == c_created) & (Review.id < c_id))
        )
    rows = (await db.execute(stmt)).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    items = [
        ReviewOut(
            id=r.Review.id,
            rating=r.Review.rating,
            body=r.Review.body,
            author_name=r.display_name,
            created_at=r.Review.created_at,
        )
        for r in page
    ]
    next_cursor = (
        _encode_cursor(page[-1].Review.created_at, page[-1].Review.id)
        if has_more and page
        else None
    )
    return items, next_cursor


async def get_stats(db: AsyncSession, brand_ids: Sequence[str]) -> dict[str, BrandRatingStats]:
    """Batch-load rating stats keyed by brand id (missing brands simply absent)."""
    if not brand_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(BrandRatingStats).where(BrandRatingStats.brand_id.in_(list(brand_ids)))
            )
        )
        .scalars()
        .all()
    )
    return {row.brand_id: row for row in rows}


async def list_own(db: AsyncSession, *, user_id: str) -> list[Review]:
    """Every review authored by the user (any status) — used to suppress the CTA."""
    return list((await db.execute(select(Review).where(Review.user_id == user_id))).scalars().all())


async def _set_status(db: AsyncSession, review: Review, new_status: str) -> None:
    """Transition a review's status, adjusting stats on published-boundary crossings."""
    if new_status not in REVIEW_STATUSES:
        raise ValidationError(f"invalid status: {new_status}")
    old_status = review.status
    if old_status == new_status:
        return
    if old_status == "published" and new_status != "published":
        await _bump_stats(db, review.brand_id, review.rating, -1)
    elif old_status != "published" and new_status == "published":
        await _bump_stats(db, review.brand_id, review.rating, +1)
    review.status = new_status
    review.updated_at = now()
    # Persist the status change now so it survives regardless of when (or
    # whether) the caller commits — a bare in-memory mutation would be lost to
    # a subsequent ``session.refresh`` on the same object.
    await db.flush()


async def report_review(
    db: AsyncSession, *, review_id: str, reporter_user_id: str | None, reason: str | None
) -> None:
    """Record an abuse report; auto-hide once distinct reports cross the threshold.

    A repeat report from the same reporter is a no-op (swallowed on the unique
    constraint).
    """
    review = (
        await db.execute(select(Review).where(Review.id == review_id).with_for_update())
    ).scalar_one_or_none()
    if review is None:
        raise NotFoundError("review not found")

    report = ReviewReport(
        id=new_id(), review_id=review_id, reporter_user_id=reporter_user_id, reason=reason
    )
    try:
        async with db.begin_nested():
            db.add(report)
            await db.flush()
    except IntegrityError:
        return  # same reporter already flagged this review — idempotent no-op

    total = (
        await db.execute(
            select(func.count())
            .select_from(ReviewReport)
            .where(ReviewReport.review_id == review_id)
        )
    ).scalar_one()
    if total >= _REPORT_AUTO_HIDE_THRESHOLD and review.status == "published":
        await _set_status(db, review, "hidden")
        log.info("review.auto_hidden", review_id=review_id, reports=total)


async def admin_list(
    db: AsyncSession, *, status: str | None, reported_only: bool, limit: int, offset: int
) -> tuple[list[tuple[Review, int]], int]:
    """List reviews for moderation with each review's report count + total row count."""
    report_count = (
        select(func.count())
        .select_from(ReviewReport)
        .where(ReviewReport.review_id == Review.id)
        .correlate(Review)
        .scalar_subquery()
    )
    stmt = select(Review, report_count.label("report_count"))
    count_stmt = select(func.count()).select_from(Review)
    if status is not None:
        stmt = stmt.where(Review.status == status)
        count_stmt = count_stmt.where(Review.status == status)
    if reported_only:
        stmt = stmt.where(report_count > 0)
        count_stmt = count_stmt.where(report_count > 0)
    stmt = stmt.order_by(Review.created_at.desc()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).all()
    total = (await db.execute(count_stmt)).scalar_one()
    return [(r.Review, r.report_count) for r in rows], total


async def count_reports(db: AsyncSession, review_id: str) -> int:
    """Number of abuse reports filed against a review."""
    return (
        await db.execute(
            select(func.count())
            .select_from(ReviewReport)
            .where(ReviewReport.review_id == review_id)
        )
    ).scalar_one()


async def admin_set_status(db: AsyncSession, *, review_id: str, status: str) -> Review:
    """Admin moderation: hide/unhide/remove a review, adjusting stats accordingly."""
    review = (
        await db.execute(select(Review).where(Review.id == review_id).with_for_update())
    ).scalar_one_or_none()
    if review is None:
        raise NotFoundError("review not found")
    await _set_status(db, review, status)
    log.info("review.status_changed", review_id=review_id, status=status)
    return review


async def recompute_all_stats(db: AsyncSession) -> int:
    """Rebuild every brand's stats from published reviews (drift safety net).

    Returns the number of brands with at least one published review.
    """
    agg = (
        select(
            Review.brand_id,
            # ``n`` not ``count``: a Row attribute named ``count`` collides with
            # the namedtuple ``.count`` method and resolves to it under typing.
            func.count().label("n"),
            func.coalesce(func.sum(Review.rating), 0).label("sum_rating"),
            *[
                func.count().filter(Review.rating == star).label(col)
                for star, col in _STAR_COLUMNS.items()
            ],
        )
        .where(Review.status == "published")
        .group_by(Review.brand_id)
    )
    rows = (await db.execute(agg)).all()

    # Zero out brands whose stats row no longer has any published reviews.
    live_ids = [r.brand_id for r in rows]
    zero_stmt = select(BrandRatingStats)
    if live_ids:
        zero_stmt = zero_stmt.where(BrandRatingStats.brand_id.notin_(live_ids))
    for stale in (await db.execute(zero_stmt)).scalars().all():
        stale.count = 0
        stale.sum_rating = 0
        stale.avg = Decimal("0.00")
        stale.count_1 = stale.count_2 = stale.count_3 = stale.count_4 = stale.count_5 = 0
        stale.updated_at = now()

    for r in rows:
        n = int(r.n)
        total = int(r.sum_rating)
        values = {
            "brand_id": r.brand_id,
            "count": n,
            "sum_rating": total,
            "avg": (Decimal(total) / Decimal(n)).quantize(Decimal("0.01")),
            "count_1": int(r.count_1),
            "count_2": int(r.count_2),
            "count_3": int(r.count_3),
            "count_4": int(r.count_4),
            "count_5": int(r.count_5),
            "updated_at": now(),
        }
        await db.execute(
            pg_insert(BrandRatingStats)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["brand_id"],
                set_={k: v for k, v in values.items() if k != "brand_id"},
            )
        )
    return len(rows)


__all__ = [
    "admin_list",
    "admin_set_status",
    "count_reports",
    "create_review",
    "get_stats",
    "list_own",
    "list_published",
    "recompute_all_stats",
    "report_review",
    "resolve_brand_id",
]
