"""How a CS2 skin line reads in an order: the skin bought, with its picture.

The line's SKU is the one generic ``cs2-skin``; what the customer bought lives
in the line's ``fulfillment_data``, snapshotted at checkout by
``checkout.price_skin_line`` (``name``, ``slug``, ``waxpeer_name``). The name is
read from that snapshot, so a later catalogue rename never rewrites an order;
the picture is looked up by slug, since rows keep one image per item.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import get_settings
from yupay.modules.skins.images import steam_image
from yupay.modules.skins.models import SkinItem


def skin_line_name(data: Mapping[str, object]) -> str | None:
    """The skin a line bought, or ``None`` when the line is not a skin.

    Args:
        data: The order line's ``fulfillment_data``.

    Returns:
        The snapshotted name (market hash name plus any Doppler phase).
    """
    if "waxpeer_name" not in data:  # only price_skin_line writes it
        return None
    for key in ("name", "market_hash_name", "waxpeer_name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def skin_images(db: AsyncSession, slugs: Iterable[str]) -> dict[str, str | None]:
    """Each slug's picture on a host customers can reach — one query.

    Args:
        db: Active session.
        slugs: Skin slugs from order lines.

    Returns:
        ``slug -> image URL`` for the slugs that exist.
    """
    wanted = sorted(set(slugs))
    if not wanted:
        return {}
    rows = await db.execute(
        select(SkinItem.slug, SkinItem.image_url).where(SkinItem.slug.in_(wanted))
    )
    host = get_settings().cs2_skins_image_host
    return {slug: steam_image(url, host=host) for slug, url in rows.all()}


__all__ = ["skin_images", "skin_line_name"]
