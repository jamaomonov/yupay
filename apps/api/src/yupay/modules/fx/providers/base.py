"""FX provider contract.

A provider knows how to fetch *one* USD-base rate at a time. Composition (fallback,
retries, caching) is the service layer's job — keep providers as thin and dumb as
possible so unit tests can run without any of the surrounding machinery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


class FxProviderError(Exception):
    """Raised by a provider when it cannot return a rate.

    Treated as ``"try the next provider in the chain"`` by the orchestrator.
    """


@dataclass(frozen=True)
class Quote:
    """A single fetched rate."""

    base: str
    quote: str
    rate: Decimal
    fetched_at: datetime
    source: str


@runtime_checkable
class FxProvider(Protocol):
    """Contract every FX adapter implements."""

    name: str

    def supports(self, base: str, quote: str) -> bool:
        """Whether this provider can be asked for ``base/quote``."""

    async def get_rate(self, base: str, quote: str) -> Quote:
        """Fetch the latest ``base → quote`` rate.

        Raises:
            FxProviderError: On any failure — network, parsing, validation, rate
                limit, or missing pair. The orchestrator will fall through to the next
                provider.
        """
