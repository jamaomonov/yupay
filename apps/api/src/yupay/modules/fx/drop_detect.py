"""Pure drop-only comparison used by the FX kill-switch (ADR-0056).

Not the pricing trust gate: that one is bidirectional and 15%. This one
fires only when a watched quote *falls* more than ``fx_drop_tripwire_pct``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RateDrop:
    """One quote that fell past the tripwire."""

    quote: str
    previous: Decimal
    current: Decimal
    drop_pct: Decimal


def detect_drops(
    previous: Mapping[str, Decimal],
    current: Mapping[str, Decimal],
    *,
    threshold_pct: Decimal,
    watched: Sequence[str],
) -> list[RateDrop]:
    """Return watched quotes whose rate fell strictly more than ``threshold_pct``.

    A missing previous (first refresh) or a missing current (provider outage)
    is not a drop. A rise is ignored. ``threshold_pct`` is exclusive: exactly
    6% does not trip a 6% wire.
    """
    if threshold_pct <= 0:
        return []
    drops: list[RateDrop] = []
    for raw in watched:
        quote = raw.upper()
        prev = previous.get(quote)
        cur = current.get(quote)
        if prev is None or cur is None or prev <= 0:
            continue
        drop_pct = (prev - cur) / prev * Decimal("100")
        if drop_pct > threshold_pct:
            drops.append(RateDrop(quote=quote, previous=prev, current=cur, drop_pct=drop_pct))
    return drops
