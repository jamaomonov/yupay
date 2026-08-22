"""FX orchestrator: cache → provider chain → cache write-back → DB history.

The service is the *only* place that knows about the full chain; providers stay
unaware of caching and DB.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fx import cache
from yupay.modules.fx.models import FxRate, FxSnapshot
from yupay.modules.fx.provider_chain import load_chain, provider_slug
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.quote_settings import (
    MANUAL_SOURCE,
    ManualOverride,
    load_override,
    override_to_quote,
    upsert_override,
)

log = get_logger("yupay.fx.service")


class FxUnavailableError(Exception):
    """Raised when no provider could service a request and no stale cache exists."""


@dataclass(frozen=True)
class ConversionResult:
    """Result of a currency conversion."""

    amount: Decimal
    rate: Decimal
    source: str


class FxService:
    """Stateful façade over the provider chain + cache + DB.

    Constructed once per app at startup (or per test); free of FastAPI / Dramatiq
    coupling so the same instance is reusable from the scheduler, the storefront, and
    the order saga.
    """

    def __init__(
        self,
        *,
        providers: Sequence[FxProvider],
        redis: Redis,
        settings: Settings | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._providers = list(providers)
        self._redis = redis
        self._settings = settings or get_settings()
        self._session_factory = session_factory

    async def _ordered_providers(self) -> list[FxProvider]:
        """Admin chain when stored; otherwise the constructor list."""
        chain = await load_chain(self._redis, session_factory=self._session_factory)
        if chain is None:
            return list(self._providers)
        by_slug = {provider_slug(p): p for p in self._providers}
        ordered: list[FxProvider] = []
        seen: set[str] = set()
        for item in chain:
            if not item.enabled:
                continue
            provider = by_slug.get(item.slug)
            if provider is None:
                continue
            ordered.append(provider)
            seen.add(item.slug)
        for provider in self._providers:
            slug = provider_slug(provider)
            if slug not in seen:
                ordered.append(provider)
        return ordered

    async def get_rate(self, base: str, quote: str, *, allow_stale: bool = True) -> Quote:
        """Return the rate the system must use for ``base → quote``.

        Admin manual override (when on) wins over Redis and every provider. The
        market path is cache → providers → stale fallback.
        """
        base_u, quote_u = base.upper(), quote.upper()
        if base_u == quote_u:
            return Quote(
                base=base_u, quote=quote_u, rate=Decimal(1), fetched_at=now(), source="identity"
            )
        manual = await self._manual_quote(base_u, quote_u)
        if manual is not None:
            return manual
        return await self.get_market_rate(base_u, quote_u, allow_stale=allow_stale)

    async def get_market_rate(self, base: str, quote: str, *, allow_stale: bool = True) -> Quote:
        """Provider/cache rate, ignoring any admin override.

        Used by the admin dashboard (to show the live FX next to ours) and by
        ``refresh_all`` so a manual toggle cannot pollute ``fx_rates`` history.
        """
        base_u, quote_u = base.upper(), quote.upper()
        if base_u == quote_u:
            return Quote(
                base=base_u, quote=quote_u, rate=Decimal(1), fetched_at=now(), source="identity"
            )

        fresh = await cache.read_fresh(self._redis, base_u, quote_u)
        if fresh is not None:
            return fresh

        for provider in await self._ordered_providers():
            if not provider.supports(base_u, quote_u):
                continue
            try:
                q = await provider.get_rate(base_u, quote_u)
            except FxProviderError as exc:
                log.warning("fx.provider.failed", provider=provider.name, error=str(exc))
                continue

            await cache.write(
                self._redis,
                q,
                fresh_ttl_seconds=self._settings.fx_cache_fresh_seconds,
                stale_ttl_seconds=self._settings.fx_cache_stale_seconds,
            )
            return q

        if allow_stale:
            stale = await cache.read_stale(self._redis, base_u, quote_u)
            if stale is not None:
                log.warning("fx.serving_stale", base=base_u, quote=quote_u)
                return stale

        raise FxUnavailableError(f"no provider could serve {base_u}->{quote_u}")

    async def _manual_quote(self, base: str, quote: str) -> Quote | None:
        """Return the admin rate when the toggle is on for a USD→quote pair."""
        if base != "USD":
            return None
        override = await load_override(self._redis, quote, session_factory=self._session_factory)
        if override is None:
            return None
        return override_to_quote(override, base=base)

    async def set_quote_setting(
        self,
        db: AsyncSession,
        *,
        quote: str,
        use_manual: bool,
        manual_rate: Decimal | None,
        updated_by: str | None,
    ) -> ManualOverride:
        """Persist the admin toggle/rate for ``quote`` and refresh the Redis copy."""
        quote_u = quote.upper()
        supported = {q.upper() for q in self._settings.fx_supported_quotes}
        if quote_u not in supported:
            raise NotFoundError(f"unsupported FX quote {quote_u}")
        if use_manual and (manual_rate is None or manual_rate <= 0):
            raise ValidationError(
                "manual_rate must be greater than 0 when use_manual is true",
                extra={"field": "manual_rate"},
            )
        if manual_rate is not None and manual_rate <= 0:
            raise ValidationError(
                "manual_rate must be greater than 0", extra={"field": "manual_rate"}
            )
        override = await upsert_override(
            db,
            self._redis,
            quote=quote_u,
            use_manual=use_manual,
            manual_rate=manual_rate,
            updated_by=updated_by,
        )
        log.info(
            "fx.manual.updated",
            quote=quote_u,
            use_manual=use_manual,
            has_rate=override.manual_rate is not None,
        )
        return override

    async def convert(self, amount: Decimal, *, base: str, quote: str) -> ConversionResult:
        """Convert ``amount`` from ``base`` to ``quote`` using the latest cached rate."""
        q = await self.get_rate(base, quote)
        return ConversionResult(amount=(amount * q.rate), rate=q.rate, source=q.source)

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        base: str,
        quote: str,
        reuse_within_seconds: int | None = None,
    ) -> FxSnapshot:
        """Persist (or reuse) an immutable :class:`FxSnapshot` for an order.

        If a recent snapshot for the same pair exists within
        ``reuse_within_seconds`` (default = ``fx_snapshot_max_age_seconds``), we return
        it as-is. Otherwise we fetch a fresh rate and insert a new row.
        """
        max_age = reuse_within_seconds or self._settings.fx_snapshot_max_age_seconds
        base_u, quote_u = base.upper(), quote.upper()
        q = await self.get_rate(base_u, quote_u)

        if max_age > 0:
            stmt = (
                select(FxSnapshot)
                .where(FxSnapshot.base == base_u, FxSnapshot.quote == quote_u)
                .order_by(FxSnapshot.created_at.desc())
                .limit(1)
            )
            recent = (await db.execute(stmt)).scalar_one_or_none()
            if recent is not None:
                age = (now() - recent.created_at).total_seconds()
                if age <= max_age and recent.rate == q.rate and recent.source == q.source:
                    return recent

        snap = FxSnapshot(
            id=new_id(),
            base=q.base,
            quote=q.quote,
            rate=q.rate,
            source=q.source,
            fetched_at=q.fetched_at,
        )
        db.add(snap)
        await db.flush()
        return snap

    async def refresh_all(
        self,
        db: AsyncSession,
        *,
        base: str = "USD",
        quotes: Sequence[str] | None = None,
    ) -> dict[str, Quote]:
        """Force-refresh the supported pair matrix.

        Intended to be called by the periodic scheduler every 5 minutes. Returns the
        fetched quotes keyed by ``quote`` symbol. Also writes a history row to
        ``fx_rates`` per successful fetch.
        """
        targets = list(quotes) if quotes is not None else self._settings.fx_supported_quotes
        results: dict[str, Quote] = {}
        for q_symbol in targets:
            if q_symbol.upper() == base.upper():
                continue
            try:
                # Bypass the fresh cache to force network call.
                await self._redis.delete(f"fx:rate:{base.upper()}:{q_symbol.upper()}")
                q = await self.get_market_rate(base, q_symbol, allow_stale=False)
            except FxUnavailableError:
                log.exception("fx.refresh.unavailable", base=base, quote=q_symbol)
                continue
            db.add(
                FxRate(
                    id=new_id(),
                    base=q.base,
                    quote=q.quote,
                    rate=q.rate,
                    source=q.source,
                    fetched_at=q.fetched_at,
                )
            )
            results[q.quote] = q
        await db.flush()
        return results


__all__ = [
    "MANUAL_SOURCE",
    "ConversionResult",
    "FxService",
    "FxUnavailableError",
]
