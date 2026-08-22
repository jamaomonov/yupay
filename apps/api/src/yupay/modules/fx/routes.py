"""HTTP routes for the ``fx`` module."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.core.logging import get_logger
from yupay.modules.admin.api import require_admin
from yupay.modules.fx import cache
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.probe import probe_chain
from yupay.modules.fx.provider_chain import ChainItem, list_chain, save_chain, write_chain_cache
from yupay.modules.fx.providers.base import Quote
from yupay.modules.fx.quote_settings import list_overrides, override_to_quote
from yupay.modules.fx.schemas import (
    AdminRateOut,
    AdminRatesOut,
    ProviderChainIn,
    ProviderChainOut,
    RateOut,
    RateSettingIn,
    RatesOut,
)
from yupay.modules.fx.service import FxService, FxUnavailableError
from yupay.modules.fx.tripwire import commit_refresh_and_trip
from yupay.modules.users.models import User

router = APIRouter(prefix="/fx", tags=["fx"])
admin_router = APIRouter(
    prefix="/admin/fx",
    tags=["admin:fx"],
    dependencies=[Depends(require_admin)],
)
log = get_logger("yupay.fx.routes")


async def _collect_rates(force: bool = False) -> RatesOut:
    """Shared body for both the public read and the admin force-refresh.

    ``force=True`` drops the fresh cache entry before each lookup so providers
    are guaranteed to be hit. The stale cache is left as a safety net so a
    provider outage during the refresh doesn't blank the dashboard.
    """
    service = build_default_service()
    base = "USD"
    results: list[RateOut] = []
    for quote in service._settings.fx_supported_quotes:
        if force:
            await cache.invalidate(service._redis, base, quote)
        try:
            q = await service.get_rate(base, quote)
        except FxUnavailableError as exc:
            log.exception(
                "fx.routes.unavailable",
                quote=quote,
                force=force,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"fx unavailable for {quote}",
            ) from exc
        results.append(
            RateOut(
                base=q.base,
                quote=q.quote,
                rate=q.rate,
                fetched_at=q.fetched_at,
                source=q.source,
            )
        )
    return RatesOut(base=base, rates=results)


async def _market_or_none(service: FxService, quote: str) -> Quote | None:
    try:
        return await service.get_market_rate("USD", quote)
    except FxUnavailableError:
        return None


def _admin_row(
    *,
    quote: str,
    effective: Quote,
    market: Quote | None,
    use_manual: bool,
    manual_rate: Decimal | None,
) -> AdminRateOut:
    return AdminRateOut(
        base=effective.base,
        quote=quote,
        rate=effective.rate,
        fetched_at=effective.fetched_at,
        source=effective.source,
        use_manual=use_manual,
        manual_rate=manual_rate,
        fx_rate=market.rate if market is not None else None,
        fx_source=market.source if market is not None else None,
        fx_fetched_at=market.fetched_at if market is not None else None,
    )


async def _collect_admin_rates(db: AsyncSession, *, force: bool = False) -> AdminRatesOut:
    """Effective rate + live FX + toggle, one row per supported quote."""
    service = build_default_service()
    stored = {row.quote: row for row in await list_overrides(db)}
    results: list[AdminRateOut] = []
    for quote in service._settings.fx_supported_quotes:
        if force:
            await cache.invalidate(service._redis, "USD", quote)
        setting = stored.get(quote.upper())
        market = await _market_or_none(service, quote)
        manual_q = override_to_quote(setting) if setting is not None else None
        effective = manual_q or market
        if effective is None:
            log.warning("fx.routes.admin_quote_unavailable", quote=quote)
            continue
        results.append(
            _admin_row(
                quote=quote,
                effective=effective,
                market=market,
                use_manual=bool(setting.use_manual) if setting is not None else False,
                manual_rate=setting.manual_rate if setting is not None else None,
            )
        )
    return AdminRatesOut(base="USD", rates=results)


@router.get(
    "/rates",
    response_model=RatesOut,
    summary="Return USD-base rates for the supported quote currencies",
)
async def get_rates() -> RatesOut:
    """Public endpoint used by the storefront to render local prices.

    Reads through cache: 99% of calls under steady state never hit a provider.
    When an admin toggle is on, the typed rate is what this returns.
    """
    return await _collect_rates(force=False)


@admin_router.get(
    "/rates",
    response_model=AdminRatesOut,
    summary="Effective rate, live FX, and the per-quote manual toggle",
)
async def admin_get_rates(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminRatesOut:
    return await _collect_admin_rates(db, force=False)


@admin_router.post(
    "/refresh",
    response_model=AdminRatesOut,
    summary="Force-refetch provider rates (does not overwrite a manual toggle)",
)
async def admin_refresh_rates(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminRatesOut:
    """Refresh, persist the tripwire, then shape the dashboard.

    The kill-switch commits on its own so a later 503 while listing quotes
    cannot undo ``maintenance`` or the ``fx_rates`` history. The ops alert
    is hooked on ``after_commit`` inside :func:`refresh_and_trip`.
    """
    await commit_refresh_and_trip(db)
    return await _collect_admin_rates(db, force=False)


@admin_router.patch(
    "/rates/{quote}",
    response_model=AdminRateOut,
    summary="Set the per-quote toggle and optional typed rate",
)
async def admin_set_rate(
    quote: str,
    body: RateSettingIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminRateOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fx.set_quote_setting"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None and cached.body is not None:
            return AdminRateOut.model_validate(cached.body)

    service = build_default_service()
    override = await service.set_quote_setting(
        db,
        quote=quote,
        use_manual=body.use_manual,
        manual_rate=body.manual_rate,
        updated_by=admin.id,
    )
    # Commit before the rate goes live. Publishing from inside the transaction
    # meant a later failure here — the 503 below, the replay write, the commit
    # itself — rolled Postgres back while Redis kept serving the new rate, with
    # nothing to expire it and an admin page reading the old row from Postgres.
    # Same order as `admin_set_providers`.
    await db.commit()
    await service.publish_quote_setting(override)

    market = await _market_or_none(service, quote)
    manual_q = override_to_quote(override)
    effective = manual_q or market
    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"fx unavailable for {quote}",
        )
    out = _admin_row(
        quote=override.quote,
        effective=effective,
        market=market,
        use_manual=override.use_manual,
        manual_rate=override.manual_rate,
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.get(
    "/providers",
    response_model=ProviderChainOut,
    summary="Live rate from each FX adapter, plus the fallback order",
)
async def admin_get_providers(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> ProviderChainOut:
    service = build_default_service()
    chain = await list_chain(db)
    return await probe_chain(service._providers, chain, service._settings.fx_supported_quotes)


@admin_router.put(
    "/providers",
    response_model=ProviderChainOut,
    summary="Set which FX adapter is primary and the fallback order",
)
async def admin_set_providers(
    body: ProviderChainIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> ProviderChainOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fx.set_provider_chain"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None and cached.body is not None:
            return ProviderChainOut.model_validate(cached.body)

    service = build_default_service()
    items = [
        ChainItem(slug=row.slug, enabled=row.enabled, sort_order=i)
        for i, row in enumerate(body.items)
    ]
    saved = await save_chain(db, items=items)
    await db.commit()
    await write_chain_cache(service._redis, saved)
    await cache.invalidate_fresh_many(service._redis, service._settings.fx_supported_quotes)
    out = await probe_chain(service._providers, saved, service._settings.fx_supported_quotes)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out
