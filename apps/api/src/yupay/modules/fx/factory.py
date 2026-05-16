"""Construct an :class:`FxService` from application settings.

Lives next to the service so callers don't have to remember which provider knobs to
wire. Use :func:`build_default_service` from FastAPI deps, the scheduler, and tests.
"""

from __future__ import annotations

from redis.asyncio import Redis

from yupay.core.config import Settings, get_settings
from yupay.core.redis import get_redis
from yupay.modules.fx.providers import (
    CoingeckoProvider,
    ExchangerateHostProvider,
    OpenExchangeRatesProvider,
)
from yupay.modules.fx.service import FxService


def build_default_service(
    *,
    settings: Settings | None = None,
    redis: Redis | None = None,
) -> FxService:
    """Build an :class:`FxService` wired to the configured provider chain."""
    s = settings or get_settings()
    providers = [
        ExchangerateHostProvider(s.fx_primary_url, timeout_seconds=s.fx_provider_timeout_seconds),
        OpenExchangeRatesProvider(
            s.fx_fallback_url,
            s.fx_fallback_api_key,
            timeout_seconds=s.fx_provider_timeout_seconds,
        ),
        CoingeckoProvider(s.fx_crypto_url, timeout_seconds=s.fx_provider_timeout_seconds),
    ]
    return FxService(providers=providers, redis=redis or get_redis(), settings=s)
