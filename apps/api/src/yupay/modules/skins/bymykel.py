"""The daily catalogue import from ByMykel/CSGO-API (spec §4.1, §4.3).

Eleven JSON files, one entry per item-and-wear, become :class:`CatalogRow`s
and are upserted into ``skin_items`` by ``(market_hash_name, phase)``. Only
metadata columns are written here — the Waxpeer side of a row belongs to
``skins.prices`` and is never touched by an import, so a re-import can run
at any time without disturbing prices.

Each file is read whole and parsed in memory, one file at a time (the
largest is 37 MB of JSON, ~200 MB resident while parsed), and rows are
flushed in batches of 1 000. Streaming JSON would need a new dependency;
see the final-review ruling on the plan ledger.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.naming import ParsedName, parse_market_name, search_text, slug_for
from yupay.modules.skins.slugs import existing_slugs, resolve
from yupay.modules.skins.taxonomy import FILE_CATEGORIES, category_for_file, category_for_skin

log = get_logger("yupay.skins.bymykel")

SKINS_FILE = "skins_not_grouped"
#: Every file the import reads, skins first.
FILES: tuple[str, ...] = (SKINS_FILE, *FILE_CATEGORIES)
_BATCH = 1000


@dataclass(frozen=True)
class CatalogRow:
    """What the import knows about one item — the metadata half of ``skin_items``."""

    market_hash_name: str
    phase: str
    slug: str
    category: str
    weapon: str | None
    skin: str | None
    exterior: str | None
    stattrak: bool
    souvenir: bool
    rarity: str | None
    rarity_color: str | None
    image_url: str | None
    min_float: Decimal | None
    max_float: Decimal | None
    paint_index: int | None
    search_text: str
    #: An agent's side (``ct`` / ``t``); ``None`` for everything that is not an agent.
    team: str | None = None


@dataclass(frozen=True)
class ImportSummary:
    files: int
    rows: int
    changed: int


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _rarity(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    rarity = entry.get("rarity")
    if not isinstance(rarity, dict):
        return None, None
    name = rarity.get("name")
    color = rarity.get("color")
    return (name if isinstance(name, str) else None, color if isinstance(color, str) else None)


#: ByMykel's ``team.id`` → ours.
_TEAMS = {"terrorists": "t", "counter-terrorists": "ct"}


def _team(entry: dict[str, Any]) -> str | None:
    team = entry.get("team")
    return _TEAMS.get(team.get("id", "")) if isinstance(team, dict) else None


def _row(
    entry: dict[str, Any], category: Callable[[ParsedName], str], *, weapons: bool = True
) -> CatalogRow | None:
    name = entry.get("market_hash_name")
    if not isinstance(name, str) or not name.strip():
        return None
    parsed = parse_market_name(name)
    phase = entry.get("phase") if isinstance(entry.get("phase"), str) else parsed.phase
    rarity, color = _rarity(entry)
    image = entry.get("image")
    return CatalogRow(
        market_hash_name=parsed.market_hash_name,
        phase=phase or "",
        slug=slug_for(parsed.market_hash_name, phase or ""),
        category=category(parsed),
        # Only weapons have a weapon: an agent is named «X | Faction», a music
        # kit «Music Kit | Artist» — the same separator, a different meaning.
        weapon=parsed.weapon if weapons else None,
        skin=parsed.skin if weapons else None,
        exterior=parsed.exterior,
        stattrak=bool(entry.get("stattrak", parsed.stattrak)),
        souvenir=bool(entry.get("souvenir", parsed.souvenir)),
        rarity=rarity,
        rarity_color=color,
        image_url=image if isinstance(image, str) and image else None,
        min_float=_decimal(entry.get("min_float")),
        max_float=_decimal(entry.get("max_float")),
        paint_index=_int(entry.get("paint_index")),
        search_text=search_text(parsed.market_hash_name, phase or ""),
        team=_team(entry),
    )


def rows_from_skins(entries: list[dict[str, Any]]) -> list[CatalogRow]:
    """Rows for ``skins_not_grouped.json``; the category comes from each entry."""
    rows: list[CatalogRow] = []
    for entry in entries:

        def category(parsed: ParsedName, e: dict[str, Any] = entry) -> str:
            return category_for_skin(e, parsed)

        row = _row(entry, category)
        if row is not None:
            rows.append(row)
    return rows


def rows_from_file(file_key: str, entries: list[dict[str, Any]]) -> list[CatalogRow]:
    """Rows for any non-skin file; the category is the file's."""
    category = category_for_file(file_key)
    rows: list[CatalogRow] = []
    for entry in entries:
        row = _row(entry, lambda _parsed: category, weapons=False)
        if row is not None:
            rows.append(row)
    return rows


def dedupe(rows: Iterable[CatalogRow]) -> list[CatalogRow]:
    """First row per ``(market_hash_name, phase)`` wins. Slugs are made unique on write
    (``skins.slugs``), not here: two names can fold to one slug."""
    seen: set[tuple[str, str]] = set()
    kept: list[CatalogRow] = []
    for row in rows:
        key = (row.market_hash_name, row.phase)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


async def fetch_file(http: httpx.AsyncClient, base_url: str, file_key: str) -> list[dict[str, Any]]:
    """``GET {base_url}/{file_key}.json``; a non-list body is an empty file."""
    response = await http.get(f"{base_url.rstrip('/')}/{file_key}.json", timeout=120.0)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, list) else []


#: ``slug`` is not here: it is assigned on insert and never rewritten (a URL).
_METADATA_COLUMNS: tuple[str, ...] = (
    "category",
    "weapon",
    "skin",
    "exterior",
    "stattrak",
    "souvenir",
    "rarity",
    "rarity_color",
    "image_url",
    "min_float",
    "max_float",
    "paint_index",
    "search_text",
    "team",
)


async def upsert_items(db: AsyncSession, rows: Iterable[CatalogRow]) -> int:
    """Insert new rows, update metadata on existing ones; price columns untouched.

    Returns the number of rows the statement wrote — Postgres counts an
    ``ON CONFLICT DO UPDATE`` whose ``WHERE`` excluded the row as not
    written, so an unchanged catalogue reports ``0``.
    """
    written = 0
    batch: list[dict[str, Any]] = []

    async def flush() -> None:
        nonlocal written
        if not batch:
            return
        stmt = pg_insert(SkinItem).values(batch)
        # IS DISTINCT FROM, not !=: a value appearing where NULL was is a change.
        changed = [
            getattr(stmt.excluded, col).is_distinct_from(getattr(SkinItem, col))
            for col in _METADATA_COLUMNS
        ]
        stmt = stmt.on_conflict_do_update(
            constraint="uq_skin_items_name_phase",
            set_={
                **{col: getattr(stmt.excluded, col) for col in _METADATA_COLUMNS},
                "source": "bymykel",
                "updated_at": now(),
            },
            where=or_(*changed, SkinItem.source != "bymykel"),
        )
        result = await db.execute(stmt)
        # ``rowcount`` lives on CursorResult; async ``execute`` is typed as Result.
        written += int(getattr(result, "rowcount", 0) or 0)
        batch.clear()

    rows = list(rows)
    slugs = resolve(
        (((row.market_hash_name, row.phase), row.slug) for row in rows), await existing_slugs(db)
    )
    for row in rows:
        values = asdict(row)
        values["slug"] = slugs[(row.market_hash_name, row.phase)]
        batch.append({"id": new_id(), "source": "bymykel", **values})
        if len(batch) >= _BATCH:
            await flush()
    await flush()
    return written


async def import_catalog(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    base_url: str,
    http: httpx.AsyncClient | None = None,
) -> ImportSummary:
    """One import tick: every file, parsed and upserted in its own transaction."""
    own_client = http is None
    client = http or httpx.AsyncClient()
    files = rows = changed = 0
    try:
        for file_key in FILES:
            entries = await fetch_file(client, base_url, file_key)
            parsed = (
                rows_from_skins(entries)
                if file_key == SKINS_FILE
                else rows_from_file(file_key, entries)
            )
            unique = dedupe(parsed)
            async with session_factory() as db:
                written = await upsert_items(db, unique)
                await db.commit()
            files += 1
            rows += len(unique)
            changed += written
            log.info("skins.import.file", file=file_key, rows=len(unique), changed=written)
    finally:
        if own_client:
            await client.aclose()
    return ImportSummary(files=files, rows=rows, changed=changed)


__all__ = [
    "FILES",
    "CatalogRow",
    "ImportSummary",
    "dedupe",
    "fetch_file",
    "import_catalog",
    "rows_from_file",
    "rows_from_skins",
    "upsert_items",
]
