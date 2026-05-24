"""exchangerate-api.com v6 adapter — preferred fiat provider when a key is set.

Endpoint shape::

    GET https://v6.exchangerate-api.com/v6/<API_KEY>/latest/USD
    →   {
          "result": "success",
          "base_code": "USD",
          "conversion_rates": { "USD": 1, "RUB": 88.5, "UZS": 12347.5, ... }
        }

Only fiat pairs with ``USD`` base are answered here. ``base != USD`` is rejected
so the chain falls through to a provider that handles it (or to the snapshot's
``base==quote`` short-circuit).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx

from yupay.core.clock import now
from yupay.modules.fx.providers._http import client_context
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote


class ExchangerateApiProvider(FxProvider):
    """v6 client. Requires a per-deployment API key (free tier: 1500 req/mo)."""

    name = "exchangerate-api.com"
    _FIAT_BASES: ClassVar[frozenset[str]] = frozenset({"USD"})
    _SUPPORTED_QUOTES: ClassVar[frozenset[str]] = frozenset(
        {"USD", "RUB", "UZS", "EUR", "KZT", "UAH", "TRY", "BYN", "GBP", "TJS", "AZN"}
    )

    def __init__(
        self,
        url_template: str,
        api_key: str,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """``url_template`` should include a single ``{key}`` placeholder, e.g.
        ``https://v6.exchangerate-api.com/v6/{key}/latest/USD``."""
        self._url_template = url_template
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
        if base_u != "USD":
            # v6 latest endpoint is /<key>/latest/<BASE>, but we only seed the
            # template with the USD base. If you need other bases later, add
            # them at the factory level.
            raise FxProviderError(f"{self.name}: base {base_u} not supported here")

        url = self._url_template.replace("{key}", self._api_key)
        try:
            async with client_context(self._client) as client:
                resp = await client.get(url, timeout=self._timeout)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FxProviderError(f"{self.name}: transport error: {exc}") from exc

        result_flag = payload.get("result")
        if result_flag != "success":
            error_type = payload.get("error-type", "unknown")
            raise FxProviderError(f"{self.name}: API said {error_type}")

        if (payload.get("base_code") or "").upper() != base_u:
            raise FxProviderError(
                f"{self.name}: API returned base {payload.get('base_code')!r}, expected {base_u}"
            )

        rate_raw = (payload.get("conversion_rates") or {}).get(quote_u)
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
