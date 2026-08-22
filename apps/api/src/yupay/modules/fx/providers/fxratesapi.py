"""fxratesapi.com adapter — fiat provider with an API key.

Endpoint shape::

    GET https://api.fxratesapi.com/latest?api_key=<KEY>&base=USD&currencies=UZS
    →   {
          "success": true,
          "base": "USD",
          "rates": { "UZS": 11853.55 }
        }

Only fiat pairs with ``USD`` base. Missing key → ``supports`` is false so the
chain skips this adapter.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx

from yupay.core.clock import now
from yupay.modules.fx.providers._http import client_context
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote


class FxRatesApiProvider(FxProvider):
    """FXRatesAPI latest-rates client."""

    slug = "fxratesapi"
    name = "fxratesapi.com"
    _FIAT_BASES: ClassVar[frozenset[str]] = frozenset({"USD"})
    _SUPPORTED_QUOTES: ClassVar[frozenset[str]] = frozenset(
        {"USD", "RUB", "UZS", "EUR", "KZT", "UAH", "TRY", "BYN", "GBP", "TJS", "AZN"}
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
        if not self._api_key:
            return False
        return base.upper() in self._FIAT_BASES and quote.upper() in self._SUPPORTED_QUOTES

    async def get_rate(self, base: str, quote: str) -> Quote:
        if not self._api_key:
            raise FxProviderError(f"{self.name}: API key not configured")
        base_u, quote_u = base.upper(), quote.upper()
        params = {
            "api_key": self._api_key,
            "base": base_u,
            "currencies": quote_u,
        }
        try:
            async with client_context(self._client) as client:
                resp = await client.get(self._url, params=params, timeout=self._timeout)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FxProviderError(f"{self.name}: transport error") from exc

        if payload.get("success") is not True:
            raise FxProviderError(f"{self.name}: API said success={payload.get('success')!r}")

        if (payload.get("base") or "").upper() != base_u:
            raise FxProviderError(
                f"{self.name}: API returned base {payload.get('base')!r}, expected {base_u}"
            )

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
