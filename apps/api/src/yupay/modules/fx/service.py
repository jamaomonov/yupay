"""FX orchestrator: cache → provider chain → cache write-back → DB history.

The service is the *only* place that knows about the full chain; providers stay
unaware of caching and DB.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fx import cache
from yupay.modules.fx.failover_alert import notify_failover, provider_label
from yupay.modules.fx.models import FxRate, FxSnapshot
from yupay.modules.fx.provider_chain import load_chain, provider_slug
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote
from yupay.modules.fx.quote_settings import (
    MANUAL_SOURCE,
    ManualOverride,
    load_override,
    override_to_quote,
    publish_override,
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
        db: AsyncSession | None = None,
    ) -> None:
        self._providers = list(providers)
        self._redis = redis
        self._settings = settings or get_settings()
        self._session_factory = session_factory
        #: A session lent by the caller, when the caller has one. Settings
        #: lookups borrow it instead of taking a second connection from the
        #: same pool while the caller still holds the first — see
        #: ``fx.session_source``. ``None`` for the scheduler, which holds no
        #: session and must open its own.
        self._db = db

    async def _ordered_providers(self) -> list[FxProvider]:
        """Admin chain when stored; otherwise the constructor list."""
        chain = await load_chain(self._redis, session_factory=self._session_factory, db=self._db)
        if chain is None:
            return list(self._providers)
        by_slug = {provider_slug(p): p for p in self._providers}
        ordered: list[FxProvider] = []
        # Every slug the chain has an opinion about, enabled or not. The
        # trailing loop exists to pick up an adapter the stored chain predates,
        # and it used to sweep the disabled ones back in with them — so
        # unticking a source in the admin UI moved it to the end of the chain
        # instead of removing it, and its rate still shipped whenever the
        # enabled ones failed. Recording the slug here regardless of `enabled`
        # is what makes "off" mean off.
        decided: set[str] = set()
        for item in chain:
            decided.add(item.slug)
            if not item.enabled:
                continue
            provider = by_slug.get(item.slug)
            if provider is None:
                continue
            ordered.append(provider)
        for provider in self._providers:
            if provider_slug(provider) not in decided:
                ordered.append(provider)
        return ordered

    async def get_rate(
        self,
        base: str,
        quote: str,
        *,
        allow_stale: bool = True,
        override_cache: dict[str, ManualOverride | None] | None = None,
    ) -> Quote:
        """Return the rate the system must use for ``base → quote``.

        Admin manual override (when on) wins over Redis and every provider. The
        market path is cache → providers → stale fallback.

        Args:
            override_cache: Memoizes the manual-override lookup per quote,
                keyed by the upper-cased quote code, across several calls that
                share this dict — mirrors the catalog ``rate_cache`` pattern
                (see ``catalog.service._resolve_variable_price``). Pass the
                same dict across every conversion in one request (e.g. once
                per product/brand/listing page) so a product with N SKUs reads
                the override once, not N times. ``None`` (the default) keeps
                the old per-call behaviour for one-off callers.
        """
        base_u, quote_u = base.upper(), quote.upper()
        if base_u == quote_u:
            return Quote(
                base=base_u, quote=quote_u, rate=Decimal(1), fetched_at=now(), source="identity"
            )
        manual = await self._manual_quote(base_u, quote_u, override_cache=override_cache)
        if manual is not None:
            return manual
        return await self.get_market_rate(base_u, quote_u, allow_stale=allow_stale)

    async def get_market_rate(
        self, base: str, quote: str, *, allow_stale: bool = True, force: bool = False
    ) -> Quote:
        """Provider/cache rate, ignoring any admin override.

        Used by the admin dashboard (to show the live FX next to ours) and by
        ``refresh_all`` so a manual toggle cannot pollute ``fx_rates`` history.

        Args:
            allow_stale: Fall back to the stale copy when every provider fails.
            force: Skip the fresh-cache read and go to the providers. This is
                how ``refresh_all`` gets a genuinely new quote *without*
                deleting the cached one first — the old value stays readable
                for the length of the round trip instead of leaving a hole
                every concurrent request falls into.
        """
        base_u, quote_u = base.upper(), quote.upper()
        if base_u == quote_u:
            return Quote(
                base=base_u, quote=quote_u, rate=Decimal(1), fetched_at=now(), source="identity"
            )

        if not force:
            # A read that *failed* is not a read that found nothing. Returning
            # None here would send this request — and every concurrent one —
            # out to an FX provider over HTTP from inside a request handler,
            # turning a Redis blip into a stampede against a rate-limited third
            # party (AGENTS.md §10). "We cannot see our rates" is the honest
            # answer, and callers already know what to do with it: the catalog
            # renders the page without a converted price rather than 500ing,
            # which is what was happening instead — 132 events in five days.
            try:
                fresh = await cache.read_fresh(self._redis, base_u, quote_u)
            except RedisError as exc:
                raise FxUnavailableError(f"rate cache unreadable for {base_u}->{quote_u}") from exc
            if fresh is not None:
                return fresh

        failed: list[str] = []
        for provider in await self._ordered_providers():
            if not provider.supports(base_u, quote_u):
                continue
            try:
                q = await provider.get_rate(base_u, quote_u)
            except FxProviderError as exc:
                log.warning("fx.provider.failed", provider=provider.name, error=str(exc))
                failed.append(provider_label(provider))
                continue

            await cache.write(
                self._redis,
                q,
                fresh_ttl_seconds=self._settings.fx_cache_fresh_seconds,
                stale_ttl_seconds=self._settings.fx_cache_stale_seconds,
            )
            await notify_failover(
                self._redis,
                base=base_u,
                quote=quote_u,
                failed=failed,
                winner=provider_label(provider),
            )
            return q

        if allow_stale:
            # Same rule; the fall-through here is the FxUnavailableError below,
            # so this only stops a Redis error arriving as a 500 instead.
            try:
                stale = await cache.read_stale(self._redis, base_u, quote_u)
            except RedisError as exc:
                raise FxUnavailableError(f"rate cache unreadable for {base_u}->{quote_u}") from exc
            if stale is not None:
                log.warning("fx.serving_stale", base=base_u, quote=quote_u)
                if failed:
                    await notify_failover(
                        self._redis,
                        base=base_u,
                        quote=quote_u,
                        failed=failed,
                        winner=stale.source,
                        stale=True,
                    )
                return stale

        if failed:
            await notify_failover(
                self._redis,
                base=base_u,
                quote=quote_u,
                failed=failed,
                winner=None,
            )
        raise FxUnavailableError(f"no provider could serve {base_u}->{quote_u}")

    async def _manual_quote(
        self,
        base: str,
        quote: str,
        *,
        override_cache: dict[str, ManualOverride | None] | None = None,
    ) -> Quote | None:
        """Return the admin rate when the toggle is on for a USD→quote pair.

        See :meth:`get_rate` for ``override_cache``. A quote present in the
        dict — even mapped to ``None`` — is a cached negative, not a miss, and
        is never re-queried within the same cache's lifetime.
        """
        if base != "USD":
            return None
        if override_cache is not None and quote in override_cache:
            override = override_cache[quote]
        else:
            override = await load_override(
                self._redis, quote, session_factory=self._session_factory, db=self._db
            )
            if override_cache is not None:
                override_cache[quote] = override
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
        """Persist the admin toggle/rate for ``quote``.

        Postgres only. The caller publishes to Redis with
        :func:`publish_quote_setting` once it has committed — see
        ``quote_settings.upsert_override``.
        """
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

    async def publish_quote_setting(self, override: ManualOverride) -> None:
        """Make a **committed** override visible to the hot path."""
        await publish_override(self._redis, override)

    async def convert(
        self,
        amount: Decimal,
        *,
        base: str,
        quote: str,
        override_cache: dict[str, ManualOverride | None] | None = None,
    ) -> ConversionResult:
        """Convert ``amount`` from ``base`` to ``quote`` using the latest cached rate.

        ``override_cache``: see :meth:`get_rate` — pass one shared dict across
        every conversion in a batch (e.g. every SKU on one catalog page) to
        read the admin override once instead of once per conversion.
        """
        q = await self.get_rate(base, quote, override_cache=override_cache)
        return ConversionResult(amount=(amount * q.rate), rate=q.rate, source=q.source)

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        base: str,
        quote: str,
        reuse_within_seconds: int | None = None,
        override_cache: dict[str, ManualOverride | None] | None = None,
    ) -> FxSnapshot:
        """Persist (or reuse) an immutable :class:`FxSnapshot` for an order.

        If a recent snapshot for the same pair exists within
        ``reuse_within_seconds`` (default = ``fx_snapshot_max_age_seconds``), we return
        it as-is. Otherwise we fetch a fresh rate and insert a new row.

        ``override_cache``: see :meth:`get_rate` — pass one shared dict across
        every snapshot taken within one request (e.g. ``pricing.fx_guard
        .guarded_usd_rate`` called once per variable-amount SKU on a catalog
        page) so the admin override is read once, not once per call.
        """
        max_age = reuse_within_seconds or self._settings.fx_snapshot_max_age_seconds
        base_u, quote_u = base.upper(), quote.upper()
        q = await self.get_rate(base_u, quote_u, override_cache=override_cache)

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
                # Fetch first, then overwrite — never delete-then-fetch. Deleting
                # left the cache empty for the length of a provider round trip
                # (up to 1.5s, or ~7.5s if the chain has to be walked), and this
                # runs every five minutes: 288 self-inflicted stampede windows a
                # day, on a value that sits on the checkout path. `force` skips
                # the fresh read without disturbing what is stored.
                q = await self.get_market_rate(base, q_symbol, allow_stale=False, force=True)
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
