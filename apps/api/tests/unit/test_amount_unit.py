"""A variable amount typed in something other than dollars.

The Steam wallet is bought in dollars, so the number the customer types is the
number that gets billed. Telegram Stars is bought in stars at $0.01545 each, and
the two must not drift: the supplier is sent an integer star count, so a
customer who asked for 500 has to be charged for exactly 500.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.orders.service import _snap_to_unit

STARS_PER_USD = Decimal("64.705882")


def _sku(*, variable: bool = True, per_usd: Decimal | None = STARS_PER_USD) -> Sku:
    return Sku(
        id="sku-stars",
        product_id="p1",
        sku_code="tg-stars-any",
        price_usd=Decimal("1"),
        variable_amount=variable,
        units_per_usd=per_usd,
        amount_unit="stars" if per_usd is not None else None,
    )


@pytest.mark.parametrize("stars", [50, 75, 137, 500, 1000, 2500, 50_000])
def test_a_star_count_survives_the_round_trip_through_dollars(stars: int) -> None:
    """The storefront divides, we multiply back. If that did not land on the
    same integer, the customer would be credited a different amount than the
    one they paid for."""
    as_usd = (Decimal(stars) / STARS_PER_USD).quantize(Decimal("0.000001"))

    snapped = _snap_to_unit(as_usd, _sku())

    assert (snapped * STARS_PER_USD).quantize(Decimal("1")) == stars


def test_float_noise_from_the_browser_is_snapped_back() -> None:
    # What a JS `500 / 64.705882` can arrive as after rounding for the wire.
    noisy = Decimal("7.727270")

    snapped = _snap_to_unit(noisy, _sku())

    assert (snapped * STARS_PER_USD).quantize(Decimal("1")) == 500
    assert snapped != noisy


def test_a_dollar_priced_sku_is_left_exactly_as_it_was() -> None:
    """Every SKU that exists today. Rounding a Steam top-up to a whole
    "unit" would quietly change what the customer asked to pay."""
    steam = _sku(per_usd=None)

    assert _snap_to_unit(Decimal("10.55"), steam) == Decimal("10.55")


def test_a_fixed_price_sku_is_never_snapped() -> None:
    assert _snap_to_unit(Decimal("3.33"), _sku(variable=False)) == Decimal("3.33")


def test_an_amount_below_half_a_unit_is_left_for_the_bounds_check() -> None:
    """Snapping it to zero would price a sale at nothing; the minimum is what
    should reject it, with a message that says so."""
    tiny = Decimal("0.000001")

    assert _snap_to_unit(tiny, _sku()) == tiny


# ---------- pricing a free amount from the packages ----------


def _pack(units: int, price: str, *, active: bool = True) -> Sku:
    return Sku(
        id=f"pack-{units}",
        product_id="p1",
        sku_code=f"tg-stars-{units}",
        price_usd=Decimal(price),
        units=units,
        active=active,
    )


#: The intent behind all of this: 20% on the small packs, less on the large.
#: 50 → $0.93 is 20% over cost; 2500 → $42.51 is about 10%.
TIERS = [
    _pack(50, "0.93"),
    _pack(100, "1.85"),
    _pack(500, "8.89"),
    _pack(2500, "42.51"),
]


def test_an_exact_package_amount_costs_exactly_the_package() -> None:
    """The whole point. A customer typing 500 must not be charged a different
    price from the one on the 500 tile right above the field."""
    from yupay.modules.orders.service import tier_price_usd

    assert tier_price_usd(500, TIERS) == Decimal("8.89")


@pytest.mark.parametrize("units", [50, 100, 500, 2_500])
def test_every_package_amount_matches_its_tile(units: int) -> None:
    from yupay.modules.orders.service import tier_price_usd

    expected = next(p for p in TIERS if p.units == units)
    assert tier_price_usd(units, TIERS) == expected.price_usd


@pytest.mark.parametrize(("typed", "band"), [(50, 50), (74, 50), (99, 50), (250, 100)])
def test_an_amount_is_priced_by_the_package_it_falls_in(typed: int, band: int) -> None:
    from yupay.modules.orders.service import tier_price_usd

    pack = next(p for p in TIERS if p.units == band)
    assert tier_price_usd(typed, TIERS) == Decimal(typed) * (pack.price_usd / Decimal(band))


def test_a_bigger_pack_s_discount_reaches_the_free_amount() -> None:
    """Without this the free amount would keep one rate and overcharge exactly
    where the volume discount is deepest."""
    from yupay.modules.orders.service import tier_price_usd

    small = tier_price_usd(50, TIERS)
    large = tier_price_usd(2_500, TIERS)

    assert small is not None
    assert large is not None
    assert large / Decimal(2_500) < small / Decimal(50)


def test_no_amount_costs_more_than_the_next_package() -> None:
    """499 stars at the 100-pack's rate came to $9.23 while the 500-pack cost
    $8.89 — buying less cost more. The cap is what stops that."""
    from yupay.modules.orders.service import tier_price_usd

    assert tier_price_usd(499, TIERS) == Decimal("8.89")


def test_more_units_never_cost_less_in_total() -> None:
    from yupay.modules.orders.service import tier_price_usd

    totals = []
    for n in (50, 74, 100, 250, 481, 499, 500, 501, 1000, 2_500, 5_000):
        total = tier_price_usd(n, TIERS)
        assert total is not None
        totals.append(total)
    assert totals == sorted(totals), totals


def test_an_amount_below_every_package_has_no_price_rather_than_a_guess() -> None:
    from yupay.modules.orders.service import tier_price_usd

    assert tier_price_usd(10, TIERS) is None


def test_a_disabled_package_stops_pricing_anything() -> None:
    """An admin who pulls a pack off the shelf did not mean to keep selling it
    by the unit."""
    from yupay.modules.orders.service import tier_price_usd

    tiers = [_pack(50, "0.93"), _pack(500, "8.89", active=False)]

    assert tier_price_usd(600, tiers) == Decimal(600) * (Decimal("0.93") / Decimal(50))


# ---------- the face value the order line actually stores ----------


def _stars_sku(multiplier: str) -> Sku:
    sku = Sku(
        id="sku-any",
        product_id="p1",
        sku_code="tg-stars-any",
        price_usd=Decimal("1"),
        variable_amount=True,
        amount_unit="Stars",
        units_per_usd=STARS_PER_USD,
        rate_multiplier=Decimal(multiplier),
        min_amount_usd=Decimal("0.772727"),
        max_amount_usd=Decimal("772.727277"),
    )
    # A real Product: the relationship is what `_tier_priced_amount` reads, and
    # SQLAlchemy will not accept a stand-in object there.
    Product(id="p1", slug="stars", brand_id="b1", kind="top_up", skus=[*TIERS, sku])
    return sku


@pytest.mark.parametrize("multiplier", ["1", "1.2", "1.5"])
def test_the_customer_is_charged_the_package_price_whatever_the_multiplier_is(
    multiplier: str,
) -> None:
    """`unit_price_usd` is a face value that gets multiplied downstream. If the
    tier price were stored raw, a multiplier of 1.2 would charge the margin
    twice — so the division here is what keeps a mis-set multiplier from
    quietly overcharging."""
    from yupay.modules.orders.service import _tier_priced_amount

    sku = _stars_sku(multiplier)
    # 500 stars, named the only unambiguous way: as its dollar equivalent.
    face = _tier_priced_amount(Decimal(500) / STARS_PER_USD, sku)

    assert face is not None
    charged = face * Decimal(multiplier)
    assert abs(charged - Decimal("8.89")) < Decimal("0.000002")


def test_a_product_with_no_packages_bills_what_the_customer_named() -> None:
    """The Steam wallet, and any unit SKU before its packages exist. Nothing
    to derive a price from, so nothing is re-derived."""
    from yupay.modules.orders.service import _tier_priced_amount

    sku = Sku(
        id="lonely",
        product_id="p3",
        sku_code="tg-stars-any",
        price_usd=Decimal("1"),
        variable_amount=True,
        amount_unit="Stars",
        units_per_usd=STARS_PER_USD,
        rate_multiplier=Decimal("1.2"),
    )
    Product(id="p3", slug="lonely", brand_id="b1", kind="top_up", skus=[sku])

    assert _tier_priced_amount(Decimal("7.727273"), sku) is None


def test_a_dollar_priced_variable_sku_is_never_re_priced() -> None:
    from yupay.modules.orders.service import _tier_priced_amount

    steam = Sku(
        id="steam",
        product_id="p2",
        sku_code="steam-wallet",
        price_usd=Decimal("1"),
        variable_amount=True,
        rate_multiplier=Decimal("1.128"),
    )
    Product(id="p2", slug="steam-wallet", brand_id="b1", kind="top_up", skus=[steam])

    assert _tier_priced_amount(Decimal("10"), steam) is None
