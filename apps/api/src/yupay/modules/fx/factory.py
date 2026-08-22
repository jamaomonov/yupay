"""Construct an :class:`FxService` from application settings.

Lives next to the service so callers don't have to remember which provider knobs to
wire. Use :func:`build_default_service` from FastAPI deps, the scheduler, and tests.
"""

from __future__ import annotations

from redis.asyncio import Redis

from yupay.core.config import Settings, get_settings
from yupay.core.db import get_session_factory
from yupay.core.redis import get_redis
from yupay.modules.fx.providers import (
    CoingeckoProvider,
    ExchangerateApiProvider,
    ExchangerateHostProvider,
    FxProvider,
    FxRatesApiProvider,
    OpenExchangeRatesProvider,
)
from yupay.modules.fx.service import FxService


def build_default_service(
    *,
    settings: Settings | None = None,
    redis: Redis | None = None,
) -> FxService:
    """Build an :class:`FxService` with every known adapter.

    Runtime order comes from ``fx_provider_settings`` (admin UI). Constructor
    order is the default: FXRatesAPI → ExchangeRate-API → exchangerate.host →
    Open Exchange Rates → CoinGecko. Keyed adapters with an empty key stay in
    the list but ``supports`` is false, so the chain skips them.
    """
    s = settings or get_settings()
    timeout = s.fx_provider_timeout_seconds
    providers: list[FxProvider] = [
        FxRatesApiProvider(s.fx_rates_api_url, s.fx_rates_api_key, timeout_seconds=timeout),
        ExchangerateApiProvider(
            s.fx_exchangerate_api_url,
            s.fx_exchangerate_api_key,
            timeout_seconds=timeout,
        ),
        ExchangerateHostProvider(s.fx_primary_url, timeout_seconds=timeout),
        OpenExchangeRatesProvider(
            s.fx_fallback_url,
            s.fx_fallback_api_key,
            timeout_seconds=timeout,
        ),
        CoingeckoProvider(s.fx_crypto_url, timeout_seconds=timeout),
    ]
    return FxService(
        providers=providers,
        redis=redis or get_redis(),
        settings=s,
        session_factory=get_session_factory(),
    )
