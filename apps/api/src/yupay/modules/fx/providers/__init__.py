"""FX provider implementations.

Each provider implements the :class:`yupay.modules.fx.providers.base.FxProvider` protocol.
The chain that orchestrates them lives in :mod:`yupay.modules.fx.service`.
"""

from yupay.modules.fx.providers.base import (
    FxProvider,
    FxProviderError,
    Quote,
)
from yupay.modules.fx.providers.coingecko import CoingeckoProvider
from yupay.modules.fx.providers.exchangerate_api import ExchangerateApiProvider
from yupay.modules.fx.providers.exchangerate_host import ExchangerateHostProvider
from yupay.modules.fx.providers.openexchangerates import OpenExchangeRatesProvider

__all__ = [
    "CoingeckoProvider",
    "ExchangerateApiProvider",
    "ExchangerateHostProvider",
    "FxProvider",
    "FxProviderError",
    "OpenExchangeRatesProvider",
    "Quote",
]
