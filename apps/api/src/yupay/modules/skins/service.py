"""Catalogue reads: filtered keyset pages, facets, suggest, detail — Postgres only.

No function here talks to Waxpeer. ``q`` switches the page to trigram
search ordered by similarity with an offset cursor; every other sort is a
keyset ``(sort value, id)`` cursor, which stays O(page) at any depth.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import Select, case, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.skins.models import SkinItem, SkinSearchAlias
from yupay.modules.skins.naming import search_text
from yupay.modules.skins.prices import CATALOG_VERSION_KEY

Sort = Literal["price", "-price", "discount", "popular"]
_SIMILARITY_FLOOR = 0.25


@dataclass(frozen=True)
class CatalogQuery:
    category: str | None = None
    weapon: str | None = None
    exterior: str | None = None
    stattrak: bool | None = None
    souvenir: bool | None = None
    rarity: str | None = None
    #: An agent's side, ``ct`` / ``t``.
    team: str | None = None
    #: Bounds on our **sell** price (what the card shows), not on supplier cost.
    min_usd: Decimal | None = None
    max_usd: Decimal | None = None
    q: str | None = None
    sort: Sort = "price"
    cursor: str | None = None
    limit: int = 48


@dataclass(frozen=True)
class Facets:
    categories: list[tuple[str, int]]
    teams: list[tuple[str, int]]
    weapons: list[tuple[str, int]]
    exteriors: list[tuple[str, int]]
    #: (name, count, colour) — the colour is the game's for that grade.
    rarities: list[tuple[str, int, str | None]]


CursorValue = int | Decimal | None


def encode_cursor(value: CursorValue, item_id: str) -> str:
    # A Decimal travels as a string so no float ever touches a price.
    wire = str(value) if isinstance(value, Decimal) else value
    raw = json.dumps([wire, item_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[CursorValue, str]:
    """Inverse of :func:`encode_cursor`; anything else is a 422, not a 500."""
    try:
        padded = token + "=" * (-len(token) % 4)
        value, item_id = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ValidationError("invalid cursor") from exc
    if not isinstance(item_id, str) or isinstance(value, bool):
        raise ValidationError("invalid cursor")
    if value is None or isinstance(value, int):
        return value, item_id
    if isinstance(value, str):
        try:
            return Decimal(value), item_id
        except ArithmeticError as exc:
            raise ValidationError("invalid cursor") from exc
    raise ValidationError("invalid cursor")


def _base(categories: list[str]) -> Select[tuple[SkinItem]]:
    return select(SkinItem).where(SkinItem.active.is_(True), SkinItem.category.in_(categories))


def _filtered(query: CatalogQuery, categories: list[str]) -> Select[tuple[SkinItem]]:
    stmt = _base(categories)
    if query.category:
        stmt = stmt.where(SkinItem.category == query.category)
    if query.weapon:
        stmt = stmt.where(SkinItem.weapon == query.weapon)
    if query.exterior:
        stmt = stmt.where(SkinItem.exterior == query.exterior)
    if query.stattrak is not None:
        stmt = stmt.where(SkinItem.stattrak.is_(query.stattrak))
    if query.souvenir is not None:
        stmt = stmt.where(SkinItem.souvenir.is_(query.souvenir))
    if query.rarity:
        stmt = stmt.where(SkinItem.rarity == query.rarity)
    if query.team:
        stmt = stmt.where(SkinItem.team == query.team)
    if query.min_usd is not None:
        stmt = stmt.where(SkinItem.sell_price_usd >= query.min_usd)
    if query.max_usd is not None:
        stmt = stmt.where(SkinItem.sell_price_usd <= query.max_usd)
    return stmt


#: Stored by ``repricing.reprice_rows``; a row without a Steam price sorts last.
_NO_DISCOUNT = -1000


def _sort_column(sort: Sort) -> Any:
    if sort == "discount":
        return func.coalesce(SkinItem.discount_percent, _NO_DISCOUNT)
    if sort == "popular":
        return SkinItem.count_auto
    return SkinItem.sell_price_usd


def _sort_value(item: SkinItem, sort: Sort) -> CursorValue:
    """The row's own stored sort value — exactly what the SQL ordered by."""
    if sort == "discount":
        return item.discount_percent if item.discount_percent is not None else _NO_DISCOUNT
    if sort == "popular":
        return item.count_auto
    return item.sell_price_usd


async def expand_aliases(db: AsyncSession, q: str) -> str:
    """Replace whole-word aliases («ак» -> ``ak-47``) before the trigram match."""
    words = q.lower().split()
    if not words:
        return ""
    rows = (
        await db.execute(select(SkinSearchAlias).where(SkinSearchAlias.alias.in_(words)))
    ).scalars()
    table = {row.alias: row.text for row in rows}
    expanded = " ".join(table.get(word, word) for word in words)
    # Folded the same way ``skin_items.search_text`` was, so ``ak-47`` from an
    # alias meets ``ak 47`` in the row.
    return search_text(expanded, "")


async def list_items(
    db: AsyncSession, query: CatalogQuery, *, categories: list[str]
) -> tuple[list[SkinItem], str | None]:
    """One page and the cursor for the next, or ``None`` on the last page."""
    limit = max(1, min(query.limit, 100))
    stmt = _filtered(query, categories)

    if query.q:
        needle = await expand_aliases(db, query.q)
        if not needle:
            return [], None
        similarity = func.similarity(SkinItem.search_text, needle)
        stmt = stmt.where(
            or_(similarity > _SIMILARITY_FLOOR, SkinItem.search_text.ilike(f"%{needle}%"))
        ).order_by(similarity.desc(), SkinItem.sell_price_usd.asc(), SkinItem.id)
        raw = decode_cursor(query.cursor)[0] if query.cursor else 0
        offset = max(0, raw) if isinstance(raw, int) else 0
        rows = list((await db.execute(stmt.offset(offset).limit(limit + 1))).scalars())
        more = len(rows) > limit
        return rows[:limit], encode_cursor(offset + limit, "") if more else None

    column = _sort_column(query.sort)
    descending = query.sort in ("-price", "discount", "popular")
    if query.cursor:
        value, last_id = decode_cursor(query.cursor)
        # Typed as the column so Postgres compares uuid with uuid, not with varchar.
        after = tuple_(literal(value), literal(last_id, type_=SkinItem.id.type))
        if descending:
            stmt = stmt.where(tuple_(column, SkinItem.id) < after)
        else:
            stmt = stmt.where(tuple_(column, SkinItem.id) > after)
    order = (column.desc(), SkinItem.id.desc()) if descending else (column.asc(), SkinItem.id.asc())
    rows = list((await db.execute(stmt.order_by(*order).limit(limit + 1))).scalars())
    more = len(rows) > limit
    page = rows[:limit]
    if not more or not page:
        return page, None
    last = page[-1]
    last_value = _sort_value(last, query.sort)
    return page, encode_cursor(last_value, last.id)


#: Grade → tier, rarest highest, so the filter reads like the game's colour ladder.
#: Weapons, stickers/cases and agents have parallel ladders; each tier lines up.
RARITY_TIER = {
    "Contraband": 6,
    "Covert": 5,
    "Extraordinary": 5,
    "Master": 5,
    "Classified": 4,
    "Exotic": 4,
    "Superior": 4,
    "Restricted": 3,
    "Remarkable": 3,
    "Exceptional": 3,
    "Mil-Spec Grade": 2,
    "High Grade": 2,
    "Distinguished": 2,
    "Industrial Grade": 1,
    "Highlight Base Grade": 1,
    "Consumer Grade": 0,
    "Base Grade": 0,
}

#: The weapons people look for first; the rest of a category follows by count.
WEAPON_PRIORITY = ("AK-47", "M4A4", "M4A1-S", "AWP", "Desert Eagle", "USP-S", "Glock-18")


async def facets(db: AsyncSession, *, categories: list[str], category: str | None = None) -> Facets:
    """Counts of active rows per category, weapon, exterior and rarity.

    Categories are always counted across the catalogue (they are the tile row).
    With ``category`` the other facets are counted inside it, so the weapon row
    lists the whole category and the wear/rarity counts match the grid.
    """
    live = [SkinItem.active.is_(True), SkinItem.category.in_(categories)]
    scoped = [*live, SkinItem.category == category] if category else live

    async def count_by(column: Any, where: list[Any]) -> list[tuple[str, int]]:
        rows = await db.execute(
            select(column, func.count())
            .where(*where, column.is_not(None))
            .group_by(column)
            .order_by(func.count().desc(), column)
        )
        return [(str(value), int(count)) for value, count in rows.all()]

    weapons = await count_by(SkinItem.weapon, scoped)
    rank = {w: i for i, w in enumerate(WEAPON_PRIORITY)}
    weapons.sort(key=lambda wc: (rank.get(wc[0], len(rank)), -wc[1], wc[0]))
    rarity_rows = await db.execute(
        select(SkinItem.rarity, func.count(), func.max(SkinItem.rarity_color))
        .where(*scoped, SkinItem.rarity.is_not(None))
        .group_by(SkinItem.rarity)
        .order_by(func.count().desc(), SkinItem.rarity)
    )
    return Facets(
        categories=await count_by(SkinItem.category, live),
        weapons=weapons,
        exteriors=await count_by(SkinItem.exterior, scoped),
        # Only inside a category: agents are the one category with sides.
        teams=await count_by(SkinItem.team, scoped) if category else [],
        rarities=sorted(
            ((str(r), int(c), color) for r, c, color in rarity_rows.all()),
            key=lambda rc: (-RARITY_TIER.get(rc[0], -1), rc[0]),
        ),
    )


async def suggest(
    db: AsyncSession, q: str, *, categories: list[str], limit: int = 10
) -> list[SkinItem]:
    needle = await expand_aliases(db, q)
    if not needle:
        return []
    similarity = func.similarity(SkinItem.search_text, needle)
    stmt = (
        _base(categories)
        .where(or_(similarity > _SIMILARITY_FLOOR, SkinItem.search_text.ilike(f"%{needle}%")))
        .order_by(similarity.desc(), SkinItem.count_auto.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def get_item(db: AsyncSession, slug: str, *, categories: list[str]) -> SkinItem:
    """An item by slug, active or not — a sold-out page is a page, not a 404."""
    row = (
        await db.execute(
            select(SkinItem).where(SkinItem.slug == slug, SkinItem.category.in_(categories))
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("skin not found")
    return row


_WEAR_ORDER = case(
    (SkinItem.exterior == "FN", 0),
    (SkinItem.exterior == "MW", 1),
    (SkinItem.exterior == "FT", 2),
    (SkinItem.exterior == "WW", 3),
    (SkinItem.exterior == "BS", 4),
    else_=5,
)


async def family(db: AsyncSession, item: SkinItem, *, categories: list[str]) -> list[SkinItem]:
    """Every wear (and StatTrak/Souvenir twin) of the same skin, sold out included.

    Only a weapon skin has wears. A case, sticker or agent has no weapon and no
    skin, so matching on those would call the whole category its family.
    """
    if item.weapon is None:
        return [item]
    stmt = (
        select(SkinItem)
        .where(
            SkinItem.category.in_(categories),
            SkinItem.category == item.category,
            SkinItem.weapon.is_not_distinct_from(item.weapon),
            SkinItem.skin.is_not_distinct_from(item.skin),
            SkinItem.phase == item.phase,
        )
        # One row per variant on the item page: plain, then Souvenir, then StatTrak.
        .order_by(SkinItem.stattrak, SkinItem.souvenir, _WEAR_ORDER, SkinItem.id)
    )
    return list((await db.execute(stmt)).scalars())


async def catalog_version(redis: Redis) -> int:
    with contextlib.suppress(RedisError, ValueError, TypeError):
        raw = await redis.get(CATALOG_VERSION_KEY)
        if raw is not None:
            return int(raw)
    return 0


__all__ = [
    "CatalogQuery",
    "Facets",
    "catalog_version",
    "decode_cursor",
    "encode_cursor",
    "expand_aliases",
    "facets",
    "family",
    "get_item",
    "list_items",
    "suggest",
]
