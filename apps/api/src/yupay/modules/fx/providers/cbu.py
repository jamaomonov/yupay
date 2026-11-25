"""Central Bank of Uzbekistan (cbu.uz) — keyless official rates, the last fiat fallback.

Endpoint shape (one currency per call, soʻm per ``Nominal`` units)::

    GET https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/
    →   [{"Ccy": "USD", "Rate": "12050.43", "Nominal": "1", "Date": "25.11.2026", ...}]

The rate is the official one, set once a day, not a market quote — which is why
it sits at the end of the chain (owner, 2026-11-25): it answers when every
commercial provider is down or out of quota. csmarket uses the same endpoint as
its primary USD/UZS source.

``USD→UZS`` is the USD row itself. ``USD→RUB`` (and the other CIS quotes) is a
cross through the soʻm: ``UZS per USD / UZS per RUB``, two calls.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx

from yupay.core.clock import now
from yupay.modules.fx.providers._http import client_context
from yupay.modules.fx.providers.base import FxProvider, FxProviderError, Quote

#: A soʻm per dollar outside this band is a broken answer, not a rate.
_USD_PLAUSIBLE = (Decimal(1000), Decimal(100000))


class CbuProvider(FxProvider):
    """Official CBU rates, USD base only."""

    slug = "cbu"
    name = "cbu.uz"
    _SUPPORTED_QUOTES: ClassVar[frozenset[str]] = frozenset(
        {"UZS", "RUB", "EUR", "KZT", "UAH", "TRY", "BYN", "GBP", "TJS", "AZN"}
    )

    def __init__(
        self,
        url_template: str,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """``url_template`` has one ``{ccy}`` placeholder, e.g. ``.../json/{ccy}/``."""
        self._url_template = url_template
        self._timeout = timeout_seconds
        self._client = client

    def supports(self, base: str, quote: str) -> bool:
        """USD against the soʻm or a currency the CBU publishes."""
        return base.upper() == "USD" and quote.upper() in self._SUPPORTED_QUOTES

    async def _uzs_per_unit(self, client: httpx.AsyncClient, ccy: str) -> Decimal:
        url = self._url_template.replace("{ccy}", ccy)
        try:
            resp = await client.get(url, timeout=self._timeout)
            resp.raise_for_status()
            body: Any = resp.json()  # JSON of unknown shape, checked below
        except httpx.HTTPStatusError as exc:
            raise FxProviderError(f"{self.name}: HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise FxProviderError(f"{self.name}: transport error {type(exc).__name__}") from exc
        if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict):
            raise FxProviderError(f"{self.name}: unexpected shape for {ccy}")
        row = body[0]
        if row.get("Ccy") != ccy:
            raise FxProviderError(f"{self.name}: asked {ccy}, got {row.get('Ccy')!r}")
        try:
            rate = Decimal(str(row["Rate"])) / Decimal(str(row.get("Nominal") or "1"))
        except (KeyError, InvalidOperation, ZeroDivisionError) as exc:
            raise FxProviderError(f"{self.name}: bad rate for {ccy}") from exc
        if not rate.is_finite() or rate <= 0:
            raise FxProviderError(f"{self.name}: non-positive rate for {ccy}")
        return rate

    async def get_rate(self, base: str, quote: str) -> Quote:
        """Quote units per one USD."""
        base_u, quote_u = base.upper(), quote.upper()
        if not self.supports(base_u, quote_u):
            raise FxProviderError(f"{self.name}: {base_u}->{quote_u} not supported")
        async with client_context(self._client) as client:
            usd = await self._uzs_per_unit(client, "USD")
            if not _USD_PLAUSIBLE[0] <= usd <= _USD_PLAUSIBLE[1]:
                raise FxProviderError(f"{self.name}: implausible USD rate {usd}")
            rate = usd if quote_u == "UZS" else usd / await self._uzs_per_unit(client, quote_u)
        return Quote(
            base=base_u,
            quote=quote_u,
            rate=rate.quantize(Decimal("0.000001")),
            fetched_at=now(),
            source=self.name,
        )
