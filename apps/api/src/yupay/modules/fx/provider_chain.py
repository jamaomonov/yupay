"""Admin-ordered FX provider chain.

The live adapters still live in :mod:`yupay.modules.fx.factory`. This module
persists **which order** to try them in. First enabled+configured slug is the
primary; the rest are fallbacks. CoinGecko stays in the list but only answers
crypto pairs via ``supports``.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.errors import ValidationError
from yupay.modules.fx.models import FxProviderSetting
from yupay.modules.fx.providers.base import FxProvider

Kind = Literal["fiat", "crypto"]


@dataclass(frozen=True)
class ProviderSpec:
    """Stable catalog entry. ``slug`` is what we store; ``name`` is Quote.source."""

    slug: str
    title: str
    kind: Kind


CATALOG: tuple[ProviderSpec, ...] = (
    ProviderSpec("fxratesapi", "FXRatesAPI", "fiat"),
    ProviderSpec("exchangerate-api", "ExchangeRate-API", "fiat"),
    ProviderSpec("exchangerate-host", "exchangerate.host", "fiat"),
    ProviderSpec("openexchangerates", "Open Exchange Rates", "fiat"),
    ProviderSpec("coingecko", "CoinGecko", "crypto"),
)

CATALOG_BY_SLUG: dict[str, ProviderSpec] = {s.slug: s for s in CATALOG}
DEFAULT_SLUGS: tuple[str, ...] = tuple(s.slug for s in CATALOG)

_CHAIN_KEY = "fx:provider_chain"


@dataclass(frozen=True)
class ChainItem:
    """One row of the admin-ordered chain."""

    slug: str
    enabled: bool
    sort_order: int


def provider_slug(provider: FxProvider) -> str:
    """Prefer an explicit ``slug``; stubs fall back to ``name``."""
    slug = getattr(provider, "slug", None)
    if isinstance(slug, str) and slug:
        return slug
    return provider.name


def provider_configured(provider: FxProvider, *, base: str = "USD", quote: str = "UZS") -> bool:
    """Whether this adapter would even be asked for a typical pair.

    Keyed fiat providers return False without a key. CoinGecko is configured
    but ``supports`` UZS is False — callers that care about a pair should
    still use ``supports``.
    """
    return provider.supports(base, quote) or provider.supports(base, "USDT")


async def load_chain(
    redis: Redis,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> list[ChainItem] | None:
    """Redis, then Postgres. ``None`` means 'use constructor order'.

    A Redis failure falls through to Postgres, which holds the same ordering —
    see ``quote_settings.load_override`` for why that is safe here and not for
    the rate cache.
    """
    cached = None
    with contextlib.suppress(RedisError):
        cached = await redis.get(_CHAIN_KEY)
    if cached:
        raw: list[object] = json.loads(cached)
        items: list[ChainItem] = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug", ""))
            if slug not in CATALOG_BY_SLUG:
                continue
            items.append(
                ChainItem(
                    slug=slug,
                    enabled=bool(row.get("enabled", True)),
                    sort_order=int(row.get("sort_order", i)),
                )
            )
        if items:
            return _with_missing_defaults(items)
    if session_factory is None:
        return None
    async with session_factory() as db:
        items = await list_chain(db)
    if not items:
        return None
    await write_chain_cache(redis, items)
    return items


async def list_chain(db: AsyncSession) -> list[ChainItem]:
    """All catalog slugs, DB order first, then any not-yet-seeded defaults."""
    rows = (
        (await db.execute(select(FxProviderSetting).order_by(FxProviderSetting.sort_order)))
        .scalars()
        .all()
    )
    stored = [
        ChainItem(slug=row.slug, enabled=row.enabled, sort_order=row.sort_order) for row in rows
    ]
    return _with_missing_defaults(stored) if stored else _default_items()


def _default_items() -> list[ChainItem]:
    return [
        ChainItem(slug=slug, enabled=True, sort_order=i) for i, slug in enumerate(DEFAULT_SLUGS)
    ]


def _with_missing_defaults(stored: list[ChainItem]) -> list[ChainItem]:
    seen = {item.slug for item in stored}
    out = list(stored)
    next_order = (max((i.sort_order for i in stored), default=-1)) + 1
    for slug in DEFAULT_SLUGS:
        if slug not in seen:
            out.append(ChainItem(slug=slug, enabled=True, sort_order=next_order))
            next_order += 1
    out.sort(key=lambda i: i.sort_order)
    return out


async def write_chain_cache(redis: Redis, items: list[ChainItem]) -> None:
    payload = json.dumps(
        [{"slug": i.slug, "enabled": i.enabled, "sort_order": i.sort_order} for i in items]
    )
    await redis.set(_CHAIN_KEY, payload)


def assert_chain_covers_quotes(
    items: Sequence[ChainItem],
    *,
    providers: Sequence[FxProvider],
    quotes: Sequence[str],
) -> None:
    """Refuse a chain that leaves a currency with nobody to price it.

    Disabling a provider used to be advisory — the ordering code swept
    disabled slugs back in as a last-resort fallback, so unticking one could
    never take a quote off the air. Now that "off" means off, it can: only
    CoinGecko answers USD→USDT, and only the fiat adapters answer USD→UZS, so
    one unticked box can leave a quote uncovered. Nothing fails at that moment
    — the fresh cache still answers — and then the stale entry expires and
    checkout starts returning 503 for that currency.

    A provider that is not configured (no API key) cannot cover anything, and
    ``supports`` already says so, which is the same question
    ``get_market_rate`` asks.

    Raises:
        ValidationError: some supported quote has no enabled provider.
    """
    enabled = {item.slug for item in items if item.enabled}
    by_slug = {provider_slug(p): p for p in providers}
    orphaned = [
        quote
        for quote in quotes
        if not any(slug in enabled and by_slug[slug].supports("USD", quote) for slug in by_slug)
    ]
    if orphaned:
        raise ValidationError(
            "every currency needs at least one enabled provider",
            extra={"field": "items", "uncovered": orphaned},
        )


async def save_chain(db: AsyncSession, *, items: list[ChainItem]) -> list[ChainItem]:
    """Replace the chain. ``items`` must be a permutation of the catalog."""
    slugs = [i.slug for i in items]
    if sorted(slugs) != sorted(DEFAULT_SLUGS):
        raise ValidationError(
            "chain must list every provider exactly once",
            extra={"field": "items"},
        )
    if len(set(slugs)) != len(slugs):
        raise ValidationError("duplicate provider slug", extra={"field": "items"})

    normalized = [
        ChainItem(slug=item.slug, enabled=item.enabled, sort_order=index)
        for index, item in enumerate(items)
    ]
    existing = {
        row.slug: row for row in (await db.execute(select(FxProviderSetting))).scalars().all()
    }
    for item in normalized:
        row = existing.get(item.slug)
        if row is None:
            db.add(
                FxProviderSetting(slug=item.slug, sort_order=item.sort_order, enabled=item.enabled)
            )
        else:
            row.sort_order = item.sort_order
            row.enabled = item.enabled
    await db.flush()
    return normalized
