"""HTTP routes for the ``fx`` module."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from yupay.core.logging import get_logger
from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.schemas import RateOut, RatesOut
from yupay.modules.fx.service import FxUnavailableError

router = APIRouter(prefix="/fx", tags=["fx"])
log = get_logger("yupay.fx.routes")


@router.get(
    "/rates",
    response_model=RatesOut,
    summary="Return USD-base rates for the supported quote currencies",
)
async def get_rates() -> RatesOut:
    """Public endpoint used by the storefront to render local prices.

    Reads through cache: 99% of calls under steady state never hit a provider.
    """
    service = build_default_service()
    base = "USD"
    results: list[RateOut] = []
    for quote in service._settings.fx_supported_quotes:
        try:
            q = await service.get_rate(base, quote)
        except FxUnavailableError as exc:
            log.exception("fx.routes.unavailable", quote=quote, error=str(exc))
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
