"""The two guards on the Telegram Stars unit-SKU seed.

The seed (``scripts/seed/2026-08-21_telegram_stars_unit_sku.py``) is the only
data change of the rollout and it runs once, against prod, by hand. Both things
it can get wrong are silent and expensive:

* a pack-sized ``cost_usdt`` (or the placeholder ``price_usd=1`` the variable
  line carried) turns into a per-**star** price — 50 Stars for $50;
* a pack-era ``mapping.quantity`` multiplies against ``order_items.qty`` — a
  customer buying 500 Stars orders 500 × 500 of them from G-Engine.

So the guards are pure functions, and these are their tests. The script itself
needs a database; these do not.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

SEED_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "seed"
    / "2026-08-21_telegram_stars_unit_sku.py"
)


def _load_seed() -> ModuleType:
    """Import the seed by path — its filename starts with a date, not an identifier."""
    spec = importlib.util.spec_from_file_location("stars_unit_sku_seed", SEED_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _load_seed()


# ---------- cost guard ----------


def test_a_per_star_cost_passes() -> None:
    """$0.0155 is what one star costs at G-Engine's rate."""
    assert seed.cost_guard(Decimal("0.015455")) is None


def test_a_missing_cost_is_refused() -> None:
    """The variable-amount line never carried one, so this is the case prod hits."""
    reason = seed.cost_guard(None)

    assert reason is not None
    assert "NULL" in reason


@pytest.mark.parametrize("cost", ["0.51", "0.7725", "8.89", "42.51"])
def test_a_pack_sized_cost_is_refused_rather_than_divided(cost: str) -> None:
    """$0.7725 is 50 stars' worth. Dividing it by 50 here would be the script
    inventing a sale price nobody approved."""
    reason = seed.cost_guard(Decimal(cost))

    assert reason is not None
    assert cost in reason


def test_a_cost_too_small_to_be_a_star_is_refused() -> None:
    reason = seed.cost_guard(Decimal("0.0009"))

    assert reason is not None
    assert "below" in reason


def test_the_cost_guard_boundaries_are_inclusive() -> None:
    """0.5 and 0.001 pass; the messages above only fire outside them."""
    assert seed.cost_guard(seed.COST_CEILING) is None
    assert seed.cost_guard(seed.COST_FLOOR) is None


# ---------- price guard ----------


def test_a_per_star_price_above_cost_passes() -> None:
    assert seed.price_guard(Decimal("0.018546"), Decimal("0.015455")) is None


def test_the_variable_line_placeholder_price_is_refused() -> None:
    """``price_usd=1`` is a placeholder on a variable SKU and a dollar per star
    on a unit one. The message has to say what it would cost the customer."""
    reason = seed.price_guard(Decimal("1"), Decimal("0.015455"))

    assert reason is not None
    assert "50.00" in reason


def test_a_price_below_cost_is_refused() -> None:
    reason = seed.price_guard(Decimal("0.01"), Decimal("0.015455"))

    assert reason is not None
    assert "loss" in reason


def test_price_from_margin_keeps_six_decimals() -> None:
    """Cents would round $0.018546 to $0.02 — a fifth more margin than asked for,
    and one rate move from selling under cost."""
    assert seed.price_from_margin(Decimal("0.015455"), Decimal("20")) == Decimal("0.018546")


def test_a_margin_priced_star_survives_its_own_guard() -> None:
    cost = Decimal("0.015455")
    price = seed.price_from_margin(cost, Decimal("20"))

    assert seed.price_guard(price, cost) is None


# ---------- mapping guards ----------


@pytest.mark.parametrize("current", [50, 500])
def test_a_pack_era_quantity_is_taken_to_one_and_printed_first(current: int) -> None:
    """Task 4 sends ``Quantity = qty × mapping.quantity``: 500 × 500 = 250 000
    stars for a 500-star order. A leftover 50 is the same class of bug."""
    quantity, line = seed.quantity_plan(current)

    assert quantity == 1
    assert f"{current} -> 1" in line


def test_an_already_converted_mapping_says_so() -> None:
    quantity, line = seed.quantity_plan(1)

    assert quantity == 1
    assert "unchanged" in line


def test_the_stars_service_mapping_passes() -> None:
    assert seed.mapping_service_guard("72") is None
    assert seed.mapping_service_guard(" 72 ") is None


@pytest.mark.parametrize("external_id", [None, "", "79", "7"])
def test_a_mapping_pointing_somewhere_else_is_refused(external_id: str | None) -> None:
    """79 is Telegram Premium. Rewriting that row to quantity 1 would be this
    script editing a product it was never pointed at."""
    reason = seed.mapping_service_guard(external_id)

    assert reason is not None
    assert "72" in reason


# ---------- the constants the runbook quotes ----------


def test_the_unit_sku_bounds_are_the_ones_the_spec_names() -> None:
    assert (seed.MIN_QTY, seed.MAX_QTY) == (50, 2500)
    assert seed.AMOUNT_UNIT == "Stars"
    assert seed.MAPPING_QUANTITY == 1


def test_revert_restores_the_bounds_the_variable_line_had() -> None:
    """50..5 000 stars, priced off the rate — what the 2026-08-18 seed created."""
    rate = Decimal("64.705882")

    assert seed.usd_for_stars(seed.REVERT_MIN_STARS, rate) == Decimal("0.772727")
    assert seed.usd_for_stars(seed.REVERT_MAX_STARS, rate) == Decimal("77.272728")
