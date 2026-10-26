"""Which region a Free Fire account lives in, and whether this page sells it.

G2B's ``checkPlayerId`` for Free Fire looks the id up across every Garena
region at once: asked under ``freefire_bd`` about a CIS account it still
answers ``valid`` with the nickname — and names the account's real region
beside it (``"region": "RU"``). We used to read the nickname and drop the
region, so an id passed on every regional page and a CIS buyer could pay for
a Bangladesh pack that never reaches their account (seen 2026-10-26).

Now a hit whose region is *known* and *not* this page's is answered as
``invalid`` with ``reason="wrong_region"`` and the regions the account can be
topped up in. Everything uncertain stays as it was: no ``region`` in the body
(the CIS code itself sends none), a region string not in the table below, or
a page whose own region we cannot place (the ``global`` brand) — none of those
blocks anybody. The table only grows from confirmed answers; a wrong entry
would turn a good id into a refusal.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.catalog.models import Brand
from yupay.modules.integrations.schemas import PlayerCheckOut

#: G2B's ``region`` on a Free Fire hit → our ``brands.region_code`` values that
#: account can be credited in. ``RU`` confirmed on production 2026-10-26 (a CIS
#: account); the others are Garena's own server codes for the regions we sell.
FREE_FIRE_ACCOUNT_REGIONS: Final[dict[str, frozenset[str]]] = {
    "RU": frozenset({"cis"}),
    "BD": frozenset({"bd"}),
    "BR": frozenset({"br"}),
    "ID": frozenset({"id"}),
    "VN": frozenset({"vn"}),
    "TH": frozenset({"th"}),
    "TW": frozenset({"tw"}),
    "SG": frozenset({"sg", "mysg"}),
    "MY": frozenset({"mysg"}),
    "PH": frozenset({"ph"}),
    "EU": frozenset({"eu"}),
    "ME": frozenset({"mena"}),
}

#: Every page region the table can speak for. A page outside it (``global``,
#: ``latam``) is never blocked: we do not know which accounts it takes.
_KNOWN_PAGES: Final[frozenset[str]] = frozenset().union(*FREE_FIRE_ACCOUNT_REGIONS.values())


def checks_region(game_code: str) -> bool:
    """``True`` for a G2B game whose hits carry a region worth comparing."""
    return game_code.startswith("freefire_")


async def page_region(session: AsyncSession, brand_id: str) -> str | None:
    """The brand's own region code (``cis``, ``bd``…), or ``None``."""
    stmt = select(Brand.region_code).where(Brand.id == brand_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def apply(out: PlayerCheckOut, resp: dict[str, Any], page: str | None) -> PlayerCheckOut:
    """Turn a ``valid`` hit from another region into a ``wrong_region`` refusal.

    Args:
        out: The verdict read from the body (``_map_response``).
        resp: The body itself, for its ``region``.
        page: This brand's region code.

    Returns:
        ``out`` unchanged unless both regions are known and differ.
    """
    if out.status != "valid" or page not in _KNOWN_PAGES:
        return out
    account = FREE_FIRE_ACCOUNT_REGIONS.get(str(resp.get("region") or "").strip().upper())
    if account is None or page in account:
        return out
    return PlayerCheckOut(
        status="invalid",
        name=out.name,
        reason="wrong_region",
        account_regions=sorted(account),
    )


async def sibling_slugs(session: AsyncSession, brand_id: str, regions: list[str]) -> list[str]:
    """The game's brands selling ``regions`` — where a reseller should order.

    The main brand of a game is its own region's page (``free-fire`` is
    ``cis``), the rest point at it through ``region_parent_id``.
    """
    brand = await session.get(Brand, brand_id)
    if brand is None or not regions:
        return []
    root = brand.region_parent_id or brand.id
    stmt = (
        select(Brand.slug)
        .where(
            (Brand.id == root) | (Brand.region_parent_id == root),
            Brand.region_code.in_(regions),
            Brand.active.is_(True),
        )
        .order_by(Brand.slug)
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "FREE_FIRE_ACCOUNT_REGIONS",
    "apply",
    "checks_region",
    "page_region",
    "sibling_slugs",
]
