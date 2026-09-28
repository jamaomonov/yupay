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
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import Select, func, literal, or_, select, tuple_
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
    min_units: int | None = None
    max_units: int | None = None
    q: str | None = None
    sort: Sort = "price"
    cursor: str | None = None
    limit: int = 48


@dataclass(frozen=True)
class Facets:
    categories: list[tuple[str, int]]
    weapons: list[tuple[str, int]]
    exteriors: list[tuple[str, int]]


def encode_cursor(value: int | None, item_id: str) -> str:
    raw = json.dumps([value, item_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[int | None, str]:
    """Inverse of :func:`encode_cursor`; anything else is a 422, not a 500."""
    try:
        padded = token + "=" * (-len(token) % 4)
        value, item_id = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ValidationError("invalid cursor") from exc
    if (value is not None and not isinstance(value, int)) or not isinstance(item_id, str):
        raise ValidationError("invalid cursor")
    return value, item_id


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
    if query.min_units is not None:
        stmt = stmt.where(SkinItem.min_auto_units >= query.min_units)
    if query.max_units is not None:
        stmt = stmt.where(SkinItem.min_auto_units <= query.max_units)
    return stmt


_DISCOUNT = (
    (SkinItem.steam_price_units - SkinItem.min_auto_units) * 100 / SkinItem.steam_price_units
)


def _sort_column(sort: Sort) -> Any:
    if sort == "discount":
        return func.coalesce(_DISCOUNT, 0)
    if sort == "popular":
        return SkinItem.count_auto
    return SkinItem.min_auto_units


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
        ).order_by(similarity.desc(), SkinItem.min_auto_units.asc(), SkinItem.id)
        offset = decode_cursor(query.cursor)[0] or 0 if query.cursor else 0
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
    last_value = (
        last.count_auto
        if query.sort == "popular"
        else (int(_discount_of(last)) if query.sort == "discount" else last.min_auto_units)
    )
    return page, encode_cursor(last_value, last.id)


def _discount_of(item: SkinItem) -> int:
    if not item.steam_price_units or item.min_auto_units is None:
        return 0
    return (item.steam_price_units - item.min_auto_units) * 100 // item.steam_price_units


async def facets(db: AsyncSession, *, categories: list[str]) -> Facets:
    """Counts of active rows per category, weapon and exterior."""

    async def count_by(column: Any) -> list[tuple[str, int]]:
        rows = await db.execute(
            select(column, func.count())
            .where(
                SkinItem.active.is_(True), SkinItem.category.in_(categories), column.is_not(None)
            )
            .group_by(column)
            .order_by(func.count().desc(), column)
        )
        return [(str(value), int(count)) for value, count in rows.all()]

    return Facets(
        categories=await count_by(SkinItem.category),
        weapons=await count_by(SkinItem.weapon),
        exteriors=await count_by(SkinItem.exterior),
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
    "get_item",
    "list_items",
    "suggest",
]
