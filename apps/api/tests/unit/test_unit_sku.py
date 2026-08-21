from types import SimpleNamespace

from yupay.modules.catalog.unit_sku import is_unit_sku


def test_stars_with_qty_bounds_is_a_unit_sku() -> None:
    sku = SimpleNamespace(variable_amount=False, amount_unit="Stars", min_qty=50, max_qty=2500)
    assert is_unit_sku(sku) is True


def test_steam_variable_is_not_a_unit_sku() -> None:
    sku = SimpleNamespace(variable_amount=True, amount_unit=None, min_qty=None, max_qty=None)
    assert is_unit_sku(sku) is False


def test_a_pack_without_bounds_is_not_a_unit_sku() -> None:
    sku = SimpleNamespace(variable_amount=False, amount_unit="Stars", min_qty=None, max_qty=None)
    assert is_unit_sku(sku) is False
