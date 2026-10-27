"""A game sold two ways on two pages: the brand's variants (migration 0108).

Standoff 2 Gold by player id (``standoff-2-id``, the main variant) and as promo codes
(``standoff-2``, the page with the search history). The catalogue lists the main one;
each page carries every variant for a switcher of links. Unlike a region (ADR-0099) a
variant is never redirected: its page, URL and search copy are its own.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.catalog.models import Brand, Category
from yupay.modules.catalog.schemas import BrandVariantOut


async def brand_variants(db: AsyncSession, brand: Brand) -> list[BrandVariantOut]:
    """Every variant of ``brand``'s game a buyer can open, main one first.

    A variant is listed while its brand is active, on the storefront and in a
    visible category — a page in maintenance still is, it says so itself. Fewer
    than two left means no switcher: the list is empty.
    """
    root = brand.variant_parent_id or brand.id
    rows = (
        await db.execute(
            select(Brand.slug, Brand.variant_code, Brand.variant_parent_id)
            .join(Brand.category)
            .where(
                (Brand.id == root) | (Brand.variant_parent_id == root),
                Brand.active.is_(True),
                Brand.visible_retail.is_(True),
                Category.active.is_(True),
            )
            .order_by(Brand.variant_parent_id.is_not(None), Brand.sort_order, Brand.slug)
        )
    ).all()
    out = [
        BrandVariantOut(code=code, slug=slug) for slug, code, _parent in rows if code is not None
    ]
    return out if len(out) > 1 else []


__all__ = ["brand_variants"]
