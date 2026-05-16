"""openexchangerates.org adapter — fiat fallback.

Free tier requires an ``app_id`` (API key). When the key is missing the adapter
declares itself unsupported and the chain skips it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx

from yupay.core.clock import now
from yupay.modules.fx.providers._http import client_context
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote


class OpenExchangeRatesProvider(FxProvider):
    """openexchangerates.org adapter; USD-base only on the free plan."""

    name = "openexchangerates"  # instance default; the FxProvider protocol declares it
    _SUPPORTED_QUOTES: ClassVar[frozenset[str]] = frozenset(
        {"RUB", "UZS", "EUR", "KZT", "UAH", "TRY"}
    )

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client

    def supports(self, base: str, quote: str) -> bool:
        """Skip silently when no API key is configured."""
        if not self._api_key:
            return False
        return base.upper() == "USD" and quote.upper() in self._SUPPORTED_QUOTES

    async def get_rate(self, base: str, quote: str) -> Quote:
        base_u, quote_u = base.upper(), quote.upper()
        params = {"app_id": self._api_key, "symbols": quote_u, "base": base_u}
        try:
            async with client_context(self._client) as client:
                resp = await client.get(self._url, params=params, timeout=self._timeout)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FxProviderError(f"{self.name}: transport error: {exc}") from exc

        rate_raw = (payload.get("rates") or {}).get(quote_u)
        if rate_raw is None:
            raise FxProviderError(f"{self.name}: missing rate for {base_u}->{quote_u}")
        try:
            rate = Decimal(str(rate_raw))
        except (InvalidOperation, ValueError) as exc:
            raise FxProviderError(f"{self.name}: non-decimal rate {rate_raw!r}") from exc
        if rate <= 0:
            raise FxProviderError(f"{self.name}: non-positive rate {rate}")

        return Quote(
            base=base_u,
            quote=quote_u,
            rate=rate,
            fetched_at=now(),
            source=self.name,
        )
