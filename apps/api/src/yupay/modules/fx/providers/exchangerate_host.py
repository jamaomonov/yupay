"""exchangerate.host adapter — primary fiat provider.

The free endpoint takes ``base`` and ``symbols`` and returns ``rates: {SYM: float, ...}``.
We don't trust that float — we re-parse via :class:`decimal.Decimal`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx

from yupay.core.clock import now
from yupay.modules.fx.providers._http import client_context
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote


class ExchangerateHostProvider(FxProvider):
    """Implementation of :class:`FxProvider` against ``api.exchangerate.host``."""

    slug = "exchangerate-host"
    name = "exchangerate.host"
    _FIAT_BASES: ClassVar[frozenset[str]] = frozenset({"USD"})
    _SUPPORTED_QUOTES: ClassVar[frozenset[str]] = frozenset(
        {"RUB", "UZS", "EUR", "KZT", "UAH", "TRY", "USD"}
    )

    def __init__(
        self, url: str, *, timeout_seconds: float, client: httpx.AsyncClient | None = None
    ) -> None:
        """Configure the adapter. Pass ``client`` to share an HTTP pool in tests."""
        self._url = url
        self._timeout = timeout_seconds
        self._client = client

    def supports(self, base: str, quote: str) -> bool:
        """We're a fiat-only adapter; reject crypto pairs."""
        return base.upper() in self._FIAT_BASES and quote.upper() in self._SUPPORTED_QUOTES

    async def get_rate(self, base: str, quote: str) -> Quote:
        """Fetch ``base → quote`` from exchangerate.host."""
        base_u, quote_u = base.upper(), quote.upper()
        params = {"base": base_u, "symbols": quote_u}
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
