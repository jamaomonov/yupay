"""HTTP routes for the ``fx`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from yupay.core.logging import get_logger
from yupay.modules.admin.api import require_admin
from yupay.modules.fx import cache
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.schemas import RateOut, RatesOut
from yupay.modules.fx.service import FxUnavailableError
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


@router.get(
    "/rates",
    response_model=RatesOut,
    summary="Return USD-base rates for the supported quote currencies",
)
async def get_rates() -> RatesOut:
    """Public endpoint used by the storefront to render local prices.

    Reads through cache: 99% of calls under steady state never hit a provider.
    """
    return await _collect_rates(force=False)


@admin_router.get(
    "/rates",
    response_model=RatesOut,
    summary="Same as public, but admin-only and useful for the admin dashboard",
)
async def admin_get_rates(
    _admin: Annotated[User, Depends(require_admin)],
) -> RatesOut:
    return await _collect_rates(force=False)


@admin_router.post(
    "/refresh",
    response_model=RatesOut,
    summary="Force-refetch all supported pairs (bypasses fresh cache)",
)
async def admin_refresh_rates(
    _admin: Annotated[User, Depends(require_admin)],
) -> RatesOut:
    return await _collect_rates(force=True)
