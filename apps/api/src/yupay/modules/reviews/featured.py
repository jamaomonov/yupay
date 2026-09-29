"""The home page's review wall: the newest written reviews across every brand.

Kept out of ``service`` (already past the file-length limit). Reads only: the
newest published reviews that carry text, each with its brand's localised name
and logo, and the rating over every published review — star-only ones included,
so the headline number is the whole record, not the flattering slice of it.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from yupay.modules.catalog.models import Brand, BrandTranslation
from yupay.modules.reviews.models import BrandRatingStats, Review
from yupay.modules.reviews.schemas import FeaturedReviewOut, ReviewStatsOut
from yupay.modules.reviews.service import _strip_html, public_photo
from yupay.modules.users.models import User

_FALLBACK_LOCALE = "ru"


async def list_featured(db: AsyncSession, *, locale: str, limit: int) -> list[FeaturedReviewOut]:
    """The newest published reviews with a non-blank body, newest first.

    Args:
        db: Session.
        locale: The brand name's language; a brand without one falls back to ``ru``.
        limit: How many to return.

    Returns:
        One row per review, with the author as the brand page shows them.
    """
    local = aliased(BrandTranslation)
    fallback = aliased(BrandTranslation)
    stmt = (
        select(
            Review,
            User.display_name,
            User.photo_url,
            Brand.slug,
            Brand.logo_url,
            func.coalesce(local.name, fallback.name, Brand.slug).label("brand_name"),
        )
        .join(Brand, Brand.id == Review.brand_id)
        .outerjoin(User, User.id == Review.user_id)
        .outerjoin(local, (local.brand_id == Brand.id) & (local.locale == locale))
        .outerjoin(
            fallback, (fallback.brand_id == Brand.id) & (fallback.locale == _FALLBACK_LOCALE)
        )
        .where(Review.status == "published", func.length(func.trim(Review.body)) > 0)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        FeaturedReviewOut(
            id=r.Review.id,
            rating=r.Review.rating,
            body=r.Review.body,
            author_name=_strip_html(r.display_name),
            author_photo_url=public_photo(r.photo_url),
            created_at=r.Review.created_at,
            brand_slug=r.slug,
            brand_name=r.brand_name,
            brand_logo_url=public_photo(r.logo_url),
        )
        for r in rows
    ]


async def overall_stats(db: AsyncSession) -> ReviewStatsOut:
    """Every brand's rating stats summed into one, from the maintained stats rows."""
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(BrandRatingStats.count), 0),
                func.coalesce(func.sum(BrandRatingStats.sum_rating), 0),
                *(
                    func.coalesce(func.sum(getattr(BrandRatingStats, f"count_{i}")), 0)
                    for i in range(1, 6)
                ),
            )
        )
    ).one()
    count, total = int(row[0]), int(row[1])
    return ReviewStatsOut(
        avg=round(total / count, 2) if count else 0.0,
        count=count,
        dist={i: int(row[1 + i]) for i in range(1, 6)},
    )
