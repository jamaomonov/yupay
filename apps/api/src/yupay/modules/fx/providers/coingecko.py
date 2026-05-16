"""CoinGecko adapter — stablecoin and crypto rates.

We use it exclusively for USDT (and any other crypto pair we add later). CoinGecko's
``simple/price`` endpoint returns ``{ "tether": {"usd": 1.0003} }``-style payloads.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from yupay.core.clock import now
from yupay.modules.fx.providers._http import client_context
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote

# Maps an upper-cased ticker on YuPay's side to the id CoinGecko knows it by.
_COIN_IDS: dict[str, str] = {
    "USDT": "tether",
    "USDC": "usd-coin",
    "TON": "the-open-network",
    "BTC": "bitcoin",
    "ETH": "ethereum",
}


class CoingeckoProvider(FxProvider):
    """USD-base crypto rates via ``simple/price``."""

    name = "coingecko"  # instance default; the FxProvider protocol declares it

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout_seconds
        self._client = client

    def supports(self, base: str, quote: str) -> bool:
        """Only fiat→crypto USD-base pairs; the inverse is the service's job to derive."""
        return base.upper() == "USD" and quote.upper() in _COIN_IDS

    async def get_rate(self, base: str, quote: str) -> Quote:
        base_u, quote_u = base.upper(), quote.upper()
        coin_id = _COIN_IDS.get(quote_u)
        if coin_id is None:
            raise FxProviderError(f"{self.name}: unsupported coin {quote_u}")

        params = {"ids": coin_id, "vs_currencies": "usd"}
        try:
            async with client_context(self._client) as client:
                resp = await client.get(self._url, params=params, timeout=self._timeout)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FxProviderError(f"{self.name}: transport error: {exc}") from exc

        usd_per_coin = (payload.get(coin_id) or {}).get("usd")
        if usd_per_coin is None:
            raise FxProviderError(f"{self.name}: missing price for {coin_id}")
        try:
            usd_per_coin_dec = Decimal(str(usd_per_coin))
        except (InvalidOperation, ValueError) as exc:
            raise FxProviderError(f"{self.name}: non-decimal price {usd_per_coin!r}") from exc
        if usd_per_coin_dec <= 0:
            raise FxProviderError(f"{self.name}: non-positive price")

        # CoinGecko returns USD-per-coin; we want coin-per-USD.
        rate = (Decimal(1) / usd_per_coin_dec).quantize(Decimal("1.0000000000"))
        return Quote(
            base=base_u,
            quote=quote_u,
            rate=rate,
            fetched_at=now(),
            source=self.name,
        )
