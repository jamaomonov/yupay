"""Sell price from a listing's cost under the admin-editable rules.

The owner thinks of a price as *cost + expenses + our margin*, and wants
the margin to depend on how liquid the item is, not only on how expensive.
So the rules document (:class:`PricingRules`) has:

- ``expenses_percent`` — acquirer fees and taxes, one number on cost;
- progressive margin brackets per channel — the first dollar at one rate,
  the next nine at another, like tax bands, so the sell price is continuous
  and never falls when the cost rises;
- ``liquidity`` bands by the item's auto-listing count — a supply-side
  proxy for how often the item is bought and price-compared; the input can
  later be our own views/orders without changing the shape;
- per-category and per-weapon adjustments in percentage points;
- per-item overrides (``item_pp``, or a pinned price that never undercuts
  cost + min margin);
- a minimum margin in dollars for the cents-priced tail, a price floor for
  the acquirers' minimum charge, UZS rounding, and an optional cap at the
  Steam Market price.

:func:`quote` applies them in a fixed order and returns every component,
so the admin preview can explain a price and the checkout re-price computes
exactly what the storefront showed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal["retail", "b2b"]
Applied = Literal["formula", "fixed", "min_margin", "steam_cap", "floor"]

_CENT = Decimal("0.01")
_UNITS_PER_USD = Decimal(1000)


class Bracket(BaseModel):
    """``percent`` applies to the slice of cost from ``from_usd`` up to the next bracket."""

    model_config = ConfigDict(frozen=True)

    from_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    percent: Decimal = Field(ge=-100, le=500, max_digits=7, decimal_places=2)


class LiquidityBand(BaseModel):
    """``pp`` applies when the item has at least ``min_count`` auto listings."""

    model_config = ConfigDict(frozen=True)

    min_count: int = Field(ge=0)
    pp: Decimal = Field(ge=-100, le=100, max_digits=6, decimal_places=2)


class PricingRules(BaseModel):
    """The whole pricing document, as stored in ``skin_pricing_rules.rules``."""

    model_config = ConfigDict(frozen=True)

    #: Acquirer fees and taxes, as a percent of cost, added to every price.
    expenses_percent: Decimal = Field(default=Decimal("3"), ge=0, le=100, decimal_places=2)
    retail: list[Bracket] = Field(min_length=1)
    b2b: list[Bracket] = Field(min_length=1)
    #: Sorted by ``min_count`` descending; the last band must start at 0.
    liquidity: list[LiquidityBand] = Field(default_factory=list)
    #: category slug -> percentage points added on top of the bracket margin.
    category_pp: dict[str, Decimal] = Field(default_factory=dict)
    #: weapon name (``AK-47``) -> percentage points.
    weapon_pp: dict[str, Decimal] = Field(default_factory=dict)
    min_margin_usd: Decimal = Field(default=Decimal("0.10"), ge=0, decimal_places=2)
    price_floor_usd: Decimal = Field(default=Decimal("0.20"), ge=0, decimal_places=2)
    uzs_round_to: int = Field(default=100, ge=1, le=10000)
    cap_at_steam: bool = False

    @model_validator(mode="after")
    def _shape(self) -> PricingRules:
        for name in ("retail", "b2b"):
            brackets: list[Bracket] = getattr(self, name)
            if brackets[0].from_usd != 0:
                raise ValueError(f"{name}: the first bracket must start at 0")
            for prev, cur in pairwise(brackets):
                if cur.from_usd <= prev.from_usd:
                    raise ValueError(f"{name}: brackets must ascend strictly")
        if self.liquidity:
            counts = [band.min_count for band in self.liquidity]
            if counts != sorted(counts, reverse=True) or counts[-1] != 0:
                raise ValueError("liquidity: bands must descend by min_count and end at 0")
        return self


DEFAULT_RULES = PricingRules(
    expenses_percent=Decimal("3"),
    retail=[
        Bracket(from_usd=Decimal("0"), percent=Decimal("10")),
        Bracket(from_usd=Decimal("1"), percent=Decimal("5")),
        Bracket(from_usd=Decimal("10"), percent=Decimal("7")),
        # 2026-09-29, owner: parity with skinsavdo, more margin on dear skins
        # (was 2 % and 1 %; measured on 19 103 shared items).
        Bracket(from_usd=Decimal("100"), percent=Decimal("3")),
        Bracket(from_usd=Decimal("1000"), percent=Decimal("2")),
    ],
    b2b=[
        Bracket(from_usd=Decimal("0"), percent=Decimal("6")),
        Bracket(from_usd=Decimal("1"), percent=Decimal("3")),
        Bracket(from_usd=Decimal("10"), percent=Decimal("4")),
        Bracket(from_usd=Decimal("100"), percent=Decimal("1.2")),
        Bracket(from_usd=Decimal("1000"), percent=Decimal("0.6")),
    ],
    liquidity=[
        LiquidityBand(min_count=50, pp=Decimal("-1")),
        LiquidityBand(min_count=20, pp=Decimal("-0.5")),
        LiquidityBand(min_count=4, pp=Decimal("0")),
        LiquidityBand(min_count=0, pp=Decimal("3")),
    ],
    category_pp={"stickers": Decimal("5")},
    # A $0.10 minimum margin made skins under $0.9 ~9 % dearer than skinsavdo (2026-09-29).
    min_margin_usd=Decimal("0.03"),
    # The acquirers' minimum payment is 1000 soʻm: $0.10 is ~1200 at ~11 800 soʻm/$.
    # Revisit if the rate ever falls near 10 000.
    price_floor_usd=Decimal("0.10"),
)


@dataclass(frozen=True)
class Quote:
    """A sell price and every component that made it."""

    price_usd: Decimal
    cost_usd: Decimal
    expenses_usd: Decimal
    bracket_margin_usd: Decimal
    category_pp: Decimal
    weapon_pp: Decimal
    liquidity_pp: Decimal
    item_pp: Decimal
    effective_percent: Decimal
    applied: Applied


def bracket_margin(cost: Decimal, brackets: list[Bracket]) -> Decimal:
    """Progressive margin: each bracket's percent on the slice of cost inside it."""
    margin = Decimal(0)
    for index, bracket in enumerate(brackets):
        upper = brackets[index + 1].from_usd if index + 1 < len(brackets) else None
        low = bracket.from_usd
        high = cost if upper is None else min(cost, upper)
        if high <= low:
            break
        margin += (high - low) * bracket.percent / Decimal(100)
    return margin


def liquidity_pp(count_auto: int | None, bands: list[LiquidityBand]) -> Decimal:
    """The first band whose ``min_count`` the count reaches; 0 when the count is unknown."""
    if count_auto is None:
        return Decimal(0)
    for band in bands:
        if count_auto >= band.min_count:
            return band.pp
    return Decimal(0)


def quote(
    cost_units: int,
    *,
    rules: PricingRules,
    category: str,
    channel: Channel = "retail",
    weapon: str | None = None,
    count_auto: int | None = None,
    item_pp: Decimal | None = None,
    fixed_price_usd: Decimal | None = None,
    steam_price_units: int | None = None,
    extra_pp: Decimal = Decimal(0),
) -> Quote:
    """Price one listing. ``extra_pp`` is the per-merchant adjustment (ADR-0089) for B2B.

    Order: expenses + brackets + every pp adjustment → a pinned price if it
    covers cost + min margin → min margin → Steam cap (only downwards, never
    below cost + min margin) → ceil to the cent → floor. ``applied`` names
    the last rule that changed the number.
    """
    cost = Decimal(cost_units) / _UNITS_PER_USD
    brackets = rules.retail if channel == "retail" else rules.b2b
    margin = bracket_margin(cost, brackets)
    expenses = cost * rules.expenses_percent / Decimal(100)
    cat_pp = rules.category_pp.get(category, Decimal(0))
    wpn_pp = rules.weapon_pp.get(weapon, Decimal(0)) if weapon else Decimal(0)
    liq_pp = liquidity_pp(count_auto, rules.liquidity)
    pp = Decimal(item_pp or 0)
    price = (
        cost + expenses + margin + cost * (cat_pp + wpn_pp + liq_pp + pp + extra_pp) / Decimal(100)
    )
    applied: Applied = "formula"
    minimum = cost + rules.min_margin_usd
    if fixed_price_usd is not None and fixed_price_usd >= minimum:
        price, applied = fixed_price_usd, "fixed"
    if price < minimum:
        price, applied = minimum, "min_margin"
    if rules.cap_at_steam and steam_price_units:
        steam = Decimal(steam_price_units) / _UNITS_PER_USD
        if price > steam:
            price, applied = max(steam, minimum), "steam_cap"
    price = price.quantize(_CENT, rounding=ROUND_CEILING)
    if price < rules.price_floor_usd:
        price, applied = rules.price_floor_usd.quantize(_CENT), "floor"
    effective = (
        ((price - cost) / cost * Decimal(100)).quantize(Decimal("0.1")) if cost else Decimal(0)
    )
    return Quote(
        price_usd=price,
        cost_usd=cost,
        expenses_usd=expenses,
        bracket_margin_usd=margin,
        category_pp=cat_pp,
        weapon_pp=wpn_pp,
        liquidity_pp=liq_pp,
        item_pp=pp,
        effective_percent=effective,
        applied=applied,
    )


def to_uzs(price_usd: Decimal, rate: Decimal, *, round_to: int) -> Decimal:
    """USD → UZS, rounded **up** to a multiple of ``round_to`` (100 by default)."""
    raw = price_usd * rate
    step = Decimal(round_to)
    return (raw / step).quantize(Decimal(1), rounding=ROUND_CEILING) * step


__all__ = [
    "DEFAULT_RULES",
    "Applied",
    "Bracket",
    "Channel",
    "LiquidityBand",
    "PricingRules",
    "Quote",
    "bracket_margin",
    "liquidity_pp",
    "quote",
    "to_uzs",
]
