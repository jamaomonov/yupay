"""What an order is worth in USD, when a Steam markup is in play.

``Order.total_usd`` is the face value of the goods. On a variable-amount SKU
that is the credit the customer chose, not the money they handed over — the
markup lives in ``rate_multiplier``. Reading the face value as revenue
understated every Steam order by exactly the margin, which is what these pin.
"""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.catalog.models import Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import order_charged_usd

# Registers the mapper behind `Order.payments`; without it, merely constructing
# an `Order` fails to configure. Imported for the side effect only.
from yupay.modules.payments.models import Payment  # noqa: F401


def _sku(*, variable: bool, multiplier: str | None) -> Sku:
    return Sku(
        id="sku-1",
        product_id="p-1",
        sku_code="s-1",
        price_usd=Decimal("10.00"),
        variable_amount=variable,
        rate_multiplier=Decimal(multiplier) if multiplier is not None else None,
    )


def _order(items: list[OrderItem]) -> Order:
    return Order(
        id="o-1",
        status="delivered",
        currency="UZS",
        total_usd=Decimal("10.00"),
        total_charged=Decimal("134380"),
        items=items,
    )


def _item(sku: Sku, *, qty: int = 1, unit: str = "10.00", pinned: str | None = None) -> OrderItem:
    """One line. ``pinned`` is the multiplier frozen at checkout (ADR-0051);
    ``None`` models a row written before that column existed."""
    return OrderItem(
        id="i-1",
        order_id="o-1",
        sku_id=sku.id,
        qty=qty,
        unit_price_usd=Decimal(unit),
        rate_multiplier=Decimal(pinned) if pinned is not None else None,
        sku=sku,
    )


def test_a_steam_top_up_is_worth_its_markup_not_its_face_value() -> None:
    # $10 of Steam credit at a 1.13 multiplier: the buyer paid ~134 380 so'm,
    # which is $11.30 at the market rate — not the $10 `total_usd` reports.
    order = _order([_item(_sku(variable=True, multiplier="1.1300"))])
    assert order_charged_usd(order) == Decimal("11.30")
    assert order.total_usd == Decimal("10.00")


def test_a_fixed_price_line_is_worth_its_price() -> None:
    # Nothing to correct here: `unit_price_usd` already is the retail price,
    # and the margin sits between it and `cost_usdt`.
    order = _order([_item(_sku(variable=False, multiplier=None), unit="25.00")])
    assert order_charged_usd(order) == Decimal("25.00")


def test_quantity_multiplies() -> None:
    order = _order([_item(_sku(variable=True, multiplier="1.1300"), qty=3)])
    assert order_charged_usd(order) == Decimal("33.90")


def test_a_mixed_order_applies_the_markup_only_to_the_variable_line() -> None:
    variable = _item(_sku(variable=True, multiplier="1.1300"))
    fixed = _item(_sku(variable=False, multiplier=None), unit="5.00")
    assert order_charged_usd(_order([variable, fixed])) == Decimal("16.30")


def test_the_pinned_multiplier_wins_over_a_since_edited_sku() -> None:
    # The whole point of freezing it: the shop raises its Steam margin to 1.20
    # tomorrow, and an order sold at 1.13 must still be worth $11.30.
    sku = _sku(variable=True, multiplier="1.2000")
    order = _order([_item(sku, pinned="1.1300")])
    assert order_charged_usd(order) == Decimal("11.30")


def test_a_line_predating_the_snapshot_falls_back_to_the_sku() -> None:
    # NULL means "not recorded", not "no markup" — those orders keep valuing
    # exactly as they did before the column existed.
    order = _order([_item(_sku(variable=True, multiplier="1.1300"), pinned=None)])
    assert order_charged_usd(order) == Decimal("11.30")


def test_a_pinned_multiplier_applies_even_if_the_sku_is_no_longer_variable() -> None:
    # A SKU converted to fixed pricing later must not retroactively strip the
    # markup off the orders that were sold under it.
    sku = _sku(variable=False, multiplier=None)
    order = _order([_item(sku, pinned="1.1300")])
    assert order_charged_usd(order) == Decimal("11.30")


def test_the_result_is_rounded_to_cents() -> None:
    # 9.99 * 1.0825 = 10.814175 — a repeating tail would otherwise reach the
    # API as a 20-digit decimal.
    order = _order([_item(_sku(variable=True, multiplier="1.0825"), unit="9.99")])
    assert order_charged_usd(order) == Decimal("10.81")
