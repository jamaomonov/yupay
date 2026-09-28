"""``quote`` under the default rules and under hand-made ones.

Every number is arithmetic on the defaults (owner, chat 2026-09-28):
expenses 3 % on cost; progressive margin brackets $0-1 10 %, $1-10 5 %,
$10-100 7 %, $100-1000 2 %, above 1 %; liquidity by auto-listing count
(>=50: -1 pp, 20-49: -0.5, 4-19: 0, <=3: +3); stickers +5 pp; min margin
$0.10; floor $0.20; UZS rounded up to 100."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from yupay.modules.skins.pricing import (
    DEFAULT_RULES,
    Bracket,
    LiquidityBand,
    PricingRules,
    bracket_margin,
    quote,
    to_uzs,
)


def test_brackets_are_progressive() -> None:
    # 27.867: 1×10% + 9×5% + 17.867×7% = 0.10 + 0.45 + 1.25069 = 1.80069
    assert bracket_margin(Decimal("27.867"), DEFAULT_RULES.retail) == Decimal("1.80069")


def test_expenses_and_liquidity_ride_on_top_of_the_brackets() -> None:
    # + expenses 3 % - liquidity 0.5 pp (49 listings) = 2.5 pp × 27.867 = 0.696675
    q = quote(27867, rules=DEFAULT_RULES, category="rifles", count_auto=49)
    assert (q.price_usd, q.applied) == (Decimal("30.37"), "formula")
    assert q.expenses_usd == Decimal("0.83601")
    assert (q.liquidity_pp, q.effective_percent) == (Decimal("-0.5"), Decimal("9.0"))


def test_liquidity_bands_move_the_same_cost_both_ways() -> None:
    hot = quote(3000, rules=DEFAULT_RULES, category="rifles", count_auto=60)
    rare = quote(3000, rules=DEFAULT_RULES, category="rifles", count_auto=2)
    # bracket 0.10 + 2×5% = 0.20; hot: +3 -1 = 2 pp -> 0.06; rare: +3 +3 = 6 pp -> 0.18
    assert (hot.price_usd, rare.price_usd) == (Decimal("3.26"), Decimal("3.38"))
    assert quote(3000, rules=DEFAULT_RULES, category="rifles").liquidity_pp == Decimal(0)


def test_category_weapon_and_item_pp() -> None:
    # 1450: 0.10 + 0.45 + 6.30 + 18.00 + 4.50 = 29.35; expenses 3 % = 43.50; 5 listings -> 0 pp
    knife = quote(1450000, rules=DEFAULT_RULES, category="knives", count_auto=5)
    assert (knife.price_usd, knife.effective_percent) == (Decimal("1522.85"), Decimal("5.0"))
    boosted = quote(
        1450000, rules=DEFAULT_RULES, category="knives", count_auto=5, item_pp=Decimal("10")
    )
    assert boosted.price_usd == Decimal("1667.85")
    ak_rules = DEFAULT_RULES.model_copy(update={"weapon_pp": {"AK-47": Decimal("-2")}})
    ak = quote(27867, rules=ak_rules, category="rifles", weapon="AK-47", count_auto=49)
    assert (ak.weapon_pp, ak.price_usd) == (Decimal("-2"), Decimal("29.81"))


def test_half_cent_listing_hits_the_floor() -> None:
    q = quote(5, rules=DEFAULT_RULES, category="stickers")
    assert (q.price_usd, q.applied) == (Decimal("0.20"), "floor")


def test_min_margin_beats_a_thin_percent() -> None:
    thin = DEFAULT_RULES.model_copy(
        update={
            "retail": [Bracket(from_usd=Decimal(0), percent=Decimal(2))],
            "expenses_percent": Decimal(0),
        }
    )
    q = quote(1000, rules=thin, category="rifles")
    assert (q.price_usd, q.applied) == (Decimal("1.10"), "min_margin")


def test_fixed_price_only_while_it_covers_cost_plus_min_margin() -> None:
    pinned = quote(
        27867,
        rules=DEFAULT_RULES,
        category="rifles",
        count_auto=49,
        fixed_price_usd=Decimal("30.00"),
    )
    assert (pinned.price_usd, pinned.applied) == (Decimal("30.00"), "fixed")
    too_low = quote(
        27867,
        rules=DEFAULT_RULES,
        category="rifles",
        count_auto=49,
        fixed_price_usd=Decimal("27.90"),
    )
    assert (too_low.price_usd, too_low.applied) == (Decimal("30.37"), "formula")


def test_steam_cap_when_enabled_never_undercuts_cost() -> None:
    capped = DEFAULT_RULES.model_copy(update={"cap_at_steam": True})
    q = quote(27867, rules=capped, category="rifles", count_auto=49, steam_price_units=30000)
    assert (q.price_usd, q.applied) == (Decimal("30.00"), "steam_cap")
    q = quote(27867, rules=capped, category="rifles", count_auto=49, steam_price_units=27900)
    assert q.price_usd == Decimal("27.97")  # cost + min margin, not Steam's 27.90
    off = quote(
        27867, rules=DEFAULT_RULES, category="rifles", count_auto=49, steam_price_units=30000
    )
    assert off.price_usd == Decimal("30.37")


def test_b2b_channel_uses_its_own_brackets() -> None:
    retail = quote(27867, rules=DEFAULT_RULES, category="rifles").price_usd
    b2b = quote(27867, rules=DEFAULT_RULES, category="rifles", channel="b2b").price_usd
    assert b2b < retail


def test_price_never_drops_when_cost_rises() -> None:
    last = Decimal(0)
    for units in range(1, 2_000_000, 997):
        price = quote(units, rules=DEFAULT_RULES, category="rifles", count_auto=10).price_usd
        assert price >= last, units
        last = price


def test_to_uzs_rounds_up_to_hundreds() -> None:
    assert to_uzs(Decimal("30.37"), Decimal("12700"), round_to=100) == Decimal("385700")
    assert to_uzs(Decimal("30.37"), Decimal("12700"), round_to=1) == Decimal("385699")


def test_rules_validation() -> None:
    with pytest.raises(ValidationError):
        PricingRules(
            retail=[Bracket(from_usd=Decimal(1), percent=Decimal(10))], b2b=DEFAULT_RULES.b2b
        )
    with pytest.raises(ValidationError):
        PricingRules(
            retail=[
                Bracket(from_usd=Decimal(0), percent=Decimal(10)),
                Bracket(from_usd=Decimal(0), percent=Decimal(5)),
            ],
            b2b=DEFAULT_RULES.b2b,
        )
    with pytest.raises(ValidationError):  # liquidity bands must end at min_count 0
        PricingRules(
            retail=DEFAULT_RULES.retail,
            b2b=DEFAULT_RULES.b2b,
            liquidity=[LiquidityBand(min_count=5, pp=Decimal(1))],
        )
