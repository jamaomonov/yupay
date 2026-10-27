"""Where a brand under maintenance sends its buyers (``brands.maintenance_redirect_id``).

A paused brand keeps its page — and the search traffic that lands on it — but takes
no orders. When the same goods are on sale under another brand, the page names that
brand and links to it. Standoff 2 promo codes, paused while G-Engine is down, point
at Standoff 2 Gold by player id (2026-10-27).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.modules.catalog.models import Brand, Category
from yupay.modules.catalog.schemas import BrandRedirectOut


async def resolve(db: AsyncSession, brand: Brand, *, locale: str) -> BrandRedirectOut | None:
    """The brand to point at, or ``None``.

    Only while ``brand`` is in maintenance, and only to a target a buyer can use:
    active, on the storefront, in a visible category and not itself paused — a
    link to a second dead end is worse than none.
    """
    if not brand.maintenance or brand.maintenance_redirect_id is None:
        return None
    from yupay.modules.catalog.service import _pick_translation

    stmt = (
        select(Brand)
        .join(Brand.category)
        .options(selectinload(Brand.translations))
        .where(
            Brand.id == brand.maintenance_redirect_id,
            Brand.active.is_(True),
            Brand.visible_retail.is_(True),
            Brand.maintenance.is_(False),
            Category.active.is_(True),
        )
    )
    target = (await db.execute(stmt)).scalar_one_or_none()
    if target is None:
        return None
    name, short_description, _, _ = _pick_translation(target.translations, locale)
    return BrandRedirectOut(slug=target.slug, name=name, short_description=short_description)


__all__ = ["resolve"]
