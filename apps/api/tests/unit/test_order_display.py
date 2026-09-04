"""``build_item_display`` line labels.

A unit SKU (Telegram Stars) is sold as an integer quantity of a named unit,
so the customer-facing line must read "500 Stars" — the quantity they
actually bought — not the SKU's static ``denomination`` field (which for a
unit SKU is either unset or a generic template, not the purchased amount).
Steam's ``variable_amount`` line is unrelated (``is_unit_sku`` is false
whenever ``variable_amount`` is true) and must keep showing its stored
``denomination`` label unchanged.

A Steam *gift* line (``steam-gift``, one SKU standing in for ~4200 games)
has the same "generic denomination" problem as the variable-amount line
above, but a fix: the real game name is snapshotted server-side onto
``item.fulfillment_data["app_name"]`` by
``yupay.modules.gifts.checkout.price_gift_line`` at checkout. Those tests
below cover that branch, including the two things it must never do: leak
``invite_url``/``supplier_price_usd`` (also in that dict) into the label,
and touch a line that merely *looks* gift-shaped but isn't (wrong SKU).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from yupay.modules.catalog.models import Sku
from yupay.modules.gifts.checkout import STEAM_GIFT_SKU_CODE
from yupay.modules.orders.models import OrderItem
from yupay.modules.orders.service import build_item_display

# Registers the mapper behind `Order.payments`; without it, merely
# constructing an `Order`/`OrderItem` fails to configure. Imported for the
# side effect only.
from yupay.modules.payments.models import Payment  # noqa: F401


def _unit_sku(*, amount_unit: str | None = "Stars") -> Sku:
    return Sku(
        id="sku-1",
        product_id="p-1",
        sku_code="tg-stars-unit",
        denomination=None,
        price_usd=Decimal("0.013"),
        variable_amount=False,
        amount_unit=amount_unit,
        min_qty=50,
        max_qty=2500,
    )


def _steam_variable_sku() -> Sku:
    return Sku(
        id="sku-2",
        product_id="p-2",
        sku_code="steam-wallet-variable",
        denomination="Любая сумма",
        price_usd=Decimal("1.00"),
        variable_amount=True,
        min_amount_usd=Decimal("5.00"),
        max_amount_usd=Decimal("500.00"),
        rate_multiplier=Decimal("1.1300"),
    )


def _pack_sku() -> Sku:
    return Sku(
        id="sku-3",
        product_id="p-3",
        sku_code="pubg-uc-60-tr",
        denomination="60 UC",
        price_usd=Decimal("0.85"),
        variable_amount=False,
    )


def _gift_sku() -> Sku:
    return Sku(
        id="sku-4",
        product_id="p-4",
        sku_code=STEAM_GIFT_SKU_CODE,
        denomination="Любая сумма",
        price_usd=Decimal("1.00"),
        variable_amount=True,
    )


def _item(sku: Sku, *, qty: int, fulfillment_data: dict[str, Any] | None = None) -> OrderItem:
    item = OrderItem(
        id="i-1",
        order_id="o-1",
        sku_id=sku.id,
        qty=qty,
        unit_price_usd=sku.price_usd,
        sku=sku,
    )
    if fulfillment_data is not None:
        item.fulfillment_data = fulfillment_data
    return item


def test_unit_sku_denomination_is_qty_and_unit() -> None:
    item = _item(_unit_sku(), qty=500)
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "500 Stars"
    assert display.variable_amount is False


def test_pre_seed_qty_one_on_unit_sku_keeps_stored_denomination() -> None:
    """After the seed the live SKU is a unit SKU, but a historical free-amount
    line stored ``qty=1``. Must not rewrite the label to ``"1 Stars"``."""
    sku = _unit_sku()
    sku.denomination = "Любое количество"
    item = _item(sku, qty=1)
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Любое количество"


def test_unit_sku_without_amount_unit_falls_back_to_stored_denomination() -> None:
    # Defensive: ``is_unit_sku`` requires amount_unit truthy, so a SKU
    # missing it (shouldn't happen once the DB constraint holds) still
    # shows whatever ``denomination`` was on file instead of crashing.
    sku = _unit_sku(amount_unit=None)
    sku.min_qty = None
    sku.max_qty = None
    sku.denomination = "N/A"
    item = _item(sku, qty=500)
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "N/A"


def test_steam_variable_amount_denomination_is_unchanged() -> None:
    item = _item(_steam_variable_sku(), qty=1)
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Любая сумма"
    assert display.variable_amount is True


def test_pack_sku_denomination_is_unchanged() -> None:
    item = _item(_pack_sku(), qty=3)
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "60 UC"
    assert display.variable_amount is False


def test_gift_line_with_app_name_renders_the_game_name() -> None:
    item = _item(_gift_sku(), qty=1, fulfillment_data={"app_name": "Dead Cells"})
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Dead Cells"


def test_gift_line_with_differing_package_name_appends_it() -> None:
    item = _item(
        _gift_sku(),
        qty=1,
        fulfillment_data={
            "app_name": "Grand Theft Auto V",
            "package_name": "Grand Theft Auto V: Premium Edition",
        },
    )
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Grand Theft Auto V · Grand Theft Auto V: Premium Edition"


def test_gift_line_with_matching_package_name_renders_just_the_game_name() -> None:
    """G-Engine usually names the base package identically to the app —
    appending it unconditionally would print the name twice."""
    item = _item(
        _gift_sku(),
        qty=1,
        fulfillment_data={
            "app_name": "Grand Theft Auto V Enhanced",
            "package_name": "Grand Theft Auto V Enhanced",
        },
    )
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Grand Theft Auto V Enhanced"


def test_gift_line_without_package_name_renders_just_the_game_name() -> None:
    item = _item(_gift_sku(), qty=1, fulfillment_data={"app_name": "Hades"})
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Hades"


def test_gift_line_without_app_name_falls_back_to_the_placeholder() -> None:
    """A gift order placed before this snapshot existed must not crash or
    render empty — it keeps today's SKU-level placeholder."""
    item = _item(
        _gift_sku(),
        qty=1,
        fulfillment_data={"invite_url": "https://steamcommunity.com/id/somebody"},
    )
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Любая сумма"


def test_gift_line_with_no_fulfillment_data_falls_back_to_the_placeholder() -> None:
    """The un-set (``None``) shape, not just an empty dict — what an
    in-memory ``OrderItem`` looks like before its first flush."""
    item = _item(_gift_sku(), qty=1)
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Любая сумма"


def test_gift_line_never_leaks_invite_url_or_supplier_price_into_the_label() -> None:
    """``fulfillment_data`` also carries the recipient's Steam profile and our
    wholesale cost — neither may ever reach a customer-facing label."""
    item = _item(
        _gift_sku(),
        qty=1,
        fulfillment_data={
            "app_name": "Hades",
            "invite_url": "https://steamcommunity.com/profiles/76561198000000000",
            "supplier_price_usd": "3.14",
        },
    )
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "Hades"


def test_non_gift_sku_with_gift_shaped_data_is_unchanged() -> None:
    """The gate is the SKU code AND ``app_name`` — a non-gift line that
    happens to carry an ``app_name`` key must not have its denomination
    hijacked."""
    item = _item(_pack_sku(), qty=3, fulfillment_data={"app_name": "Not A Game"})
    display = build_item_display(item)
    assert display is not None
    assert display.denomination == "60 UC"
