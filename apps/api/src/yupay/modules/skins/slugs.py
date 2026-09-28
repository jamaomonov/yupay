"""Slugs that stay unique when two names fold to the same ASCII text.

``naming.slug_for`` drops non-ASCII and lower-cases, so real names collide:
``Sunset Storm 壱``/``弐``, ``Sticker | NiKo``/``Sticker | niko  ``. A slug is
assigned once, when the row is first written, and never changes after that
(it is a URL); a newcomer whose plain slug is taken by a different item gets
a short hash of its own name appended.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.skins.models import SkinItem

Key = tuple[str, str]


def suffixed(slug: str, key: Key) -> str:
    """``slug`` plus six hex chars of the item's own identity — stable across runs."""
    digest = hashlib.sha1(f"{key[0]}|{key[1]}".encode()).hexdigest()[:6]  # noqa: S324
    return f"{slug}-{digest}"


def resolve(wanted: Iterable[tuple[Key, str]], existing: dict[Key, str]) -> dict[Key, str]:
    """The slug each key gets: its existing one, its plain one, or a suffixed one."""
    taken = {slug: key for key, slug in existing.items()}
    out: dict[Key, str] = {}
    for key, slug in wanted:
        if key in existing:
            out[key] = existing[key]
            continue
        chosen = slug if taken.get(slug, key) == key else suffixed(slug, key)
        taken[chosen] = key
        out[key] = chosen
    return out


async def existing_slugs(db: AsyncSession) -> dict[Key, str]:
    """Every ``(market_hash_name, phase) -> slug`` already stored (~35k rows)."""
    rows = await db.execute(select(SkinItem.market_hash_name, SkinItem.phase, SkinItem.slug))
    return {(name, phase): slug for name, phase, slug in rows.all()}


__all__ = ["existing_slugs", "resolve", "suffixed"]
