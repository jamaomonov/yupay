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
    OpenExchangeRatesProvider,
)
from yupay.modules.fx.service import FxService


def build_default_service(
    *,
    settings: Settings | None = None,
    redis: Redis | None = None,
) -> FxService:
    """Build an :class:`FxService` wired to the configured provider chain.

    Order matters — the first provider that ``supports`` a pair wins, and
    failures fall through to the next. Crypto pairs route through Coingecko
    regardless of the fiat order above it.
    """
    s = settings or get_settings()
    providers: list[FxProvider] = []
    # Prefer the keyed exchangerate-api.com if we have a key — it's the most
    # stable in our region and includes UZS / KZT / TJS out of the box.
    if s.fx_exchangerate_api_key:
        providers.append(
            ExchangerateApiProvider(
                s.fx_exchangerate_api_url,
                s.fx_exchangerate_api_key,
                timeout_seconds=s.fx_provider_timeout_seconds,
            )
        )
    providers.append(
        ExchangerateHostProvider(s.fx_primary_url, timeout_seconds=s.fx_provider_timeout_seconds)
    )
    providers.append(
        OpenExchangeRatesProvider(
            s.fx_fallback_url,
            s.fx_fallback_api_key,
            timeout_seconds=s.fx_provider_timeout_seconds,
        )
    )
    providers.append(
        CoingeckoProvider(s.fx_crypto_url, timeout_seconds=s.fx_provider_timeout_seconds)
    )
    return FxService(
        providers=providers,
        redis=redis or get_redis(),
        settings=s,
        session_factory=get_session_factory(),
    )
