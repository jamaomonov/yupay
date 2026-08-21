from types import SimpleNamespace

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.catalog.unit_sku import DEFAULT_QTY_MAX, assert_qty_allowed, is_unit_sku


def test_stars_with_qty_bounds_is_a_unit_sku() -> None:
    sku = SimpleNamespace(variable_amount=False, amount_unit="Stars", min_qty=50, max_qty=2500)
    assert is_unit_sku(sku) is True


def test_steam_variable_is_not_a_unit_sku() -> None:
    sku = SimpleNamespace(variable_amount=True, amount_unit=None, min_qty=None, max_qty=None)
    assert is_unit_sku(sku) is False


def test_a_pack_without_bounds_is_not_a_unit_sku() -> None:
    sku = SimpleNamespace(variable_amount=False, amount_unit="Stars", min_qty=None, max_qty=None)
    assert is_unit_sku(sku) is False


def _unit_sku(min_qty: int = 50, max_qty: int = 2500) -> SimpleNamespace:
    return SimpleNamespace(
        variable_amount=False, amount_unit="Stars", min_qty=min_qty, max_qty=max_qty
    )


def _ordinary_sku() -> SimpleNamespace:
    return SimpleNamespace(variable_amount=False, amount_unit=None, min_qty=None, max_qty=None)


def test_unit_sku_qty_within_bounds_is_allowed() -> None:
    assert_qty_allowed(_unit_sku(), 500)  # must not raise


def test_unit_sku_qty_at_the_bounds_is_allowed() -> None:
    assert_qty_allowed(_unit_sku(min_qty=50, max_qty=2500), 50)
    assert_qty_allowed(_unit_sku(min_qty=50, max_qty=2500), 2500)


def test_unit_sku_qty_below_min_is_rejected() -> None:
    with pytest.raises(ValidationError):
        assert_qty_allowed(_unit_sku(min_qty=50, max_qty=2500), 49)


def test_unit_sku_qty_above_max_is_rejected() -> None:
    with pytest.raises(ValidationError):
        assert_qty_allowed(_unit_sku(min_qty=50, max_qty=2500), 2501)


def test_unit_sku_qty_may_exceed_default_qty_max() -> None:
    """The whole point of a unit SKU: its own bounds override
    DEFAULT_QTY_MAX, so a qty far past 100 is fine as long as it's within
    min_qty/max_qty."""
    assert_qty_allowed(_unit_sku(min_qty=50, max_qty=2500), DEFAULT_QTY_MAX + 400)


def test_ordinary_sku_qty_at_the_default_max_is_allowed() -> None:
    assert_qty_allowed(_ordinary_sku(), DEFAULT_QTY_MAX)


def test_ordinary_sku_qty_over_the_default_max_is_rejected() -> None:
    """Security regression: raising the wire max for unit SKUs must not
    raise it for anything else."""
    with pytest.raises(ValidationError):
        assert_qty_allowed(_ordinary_sku(), DEFAULT_QTY_MAX + 1)
