"""Our purchase price is not part of anything a buyer can read.

``OrderItem.cost_usdt`` sits on the row behind every order response, and those
responses are public to the customer who placed the order — a guest needs only
the order id and their email. A field added to ``OrderItemOut`` "for the admin
view" would ship the supplier price to every buyer and to anyone they forward
the link to, and nothing would look broken.

``OrderItemOut`` lists its fields explicitly, so this cannot happen by
accident today. It can happen by edit, which is what these tests are for.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.modules.orders.schemas import (
    OrderAdminOut,
    OrderItemAdminOut,
    OrderItemOut,
    OrderOut,
)

pytestmark = pytest.mark.asyncio

#: Substrings that would mean a purchase price reached a response model.
_COST_ISH = ("cost", "purchase_price", "wholesale", "supplier_price", "margin")


def _field_names(model: type) -> set[str]:
    return set(getattr(model, "model_fields", {}))


async def test_the_customer_order_line_carries_no_cost() -> None:
    leaked = [f for f in _field_names(OrderItemOut) if any(w in f.lower() for w in _COST_ISH)]
    assert leaked == [], (
        f"{leaked} would ship our purchase price to the buyer: this schema renders "
        "the order response a customer reads."
    )


async def test_the_admin_order_line_carries_no_cost_either() -> None:
    """It inherits from the customer schema, so anything added here ships too."""
    leaked = [f for f in _field_names(OrderItemAdminOut) if any(w in f.lower() for w in _COST_ISH)]
    assert leaked == [], f"{leaked} on the admin line is inherited by the customer's"


async def test_the_order_response_forbids_extras() -> None:
    """The other way cost could arrive: a permissive config plus an ORM object.

    ``from_attributes`` reads declared fields only, but ``extra="allow"`` would
    let an ORM row's whole column set through.
    """
    for model in (OrderItemOut, OrderItemAdminOut, OrderOut, OrderAdminOut):
        assert model.model_config.get("extra") != "allow", (
            f"{model.__name__} allows extras; an ORM object would carry cost_usdt through"
        )


async def test_a_serialized_line_has_no_cost_in_it() -> None:
    """Belt and braces: dump one and read the payload, not the declaration."""
    line = OrderItemOut(
        id="i1",
        sku_id="s1",
        qty=1,
        unit_price_usd=Decimal("10.00"),
        fulfillment_state="pending",
        fulfillment_data={},
    )
    dumped = line.model_dump_json()
    assert "cost" not in dumped.lower(), dumped


async def test_a_supplier_price_hidden_inside_fulfillment_data_is_still_redacted() -> None:
    """The declared-field checks above can't see into a free-form JSONB
    column: ``fulfillment_data`` is typed ``dict[str, Any]``, so a cost key
    living *inside* it (the Steam gift checkout hook's ``supplier_price_usd``,
    see ``gifts.checkout.price_gift_line``) doesn't show up as a field name.
    ``OrderItemOut`` redacts it at serialization time instead — this proves
    the redaction actually fires, and that everything else in the snapshot
    still comes through untouched."""
    line = OrderItemOut(
        id="i1",
        sku_id="s1",
        qty=1,
        unit_price_usd=Decimal("1.10"),
        fulfillment_state="pending",
        fulfillment_data={
            "app_id": 588650,
            "app_name": "Dead Cells",
            "supplier_price_usd": "1.00",
        },
    )
    dumped = line.model_dump()
    assert "supplier_price_usd" not in dumped["fulfillment_data"]
    assert dumped["fulfillment_data"]["app_name"] == "Dead Cells"


async def test_the_admin_line_still_sees_the_supplier_price() -> None:
    """The redaction is customer-facing only — an operator needs the real
    cost to see the actual margin on a line."""
    line = OrderItemAdminOut(
        id="i1",
        sku_id="s1",
        qty=1,
        unit_price_usd=Decimal("1.10"),
        fulfillment_state="pending",
        fulfillment_data={"supplier_price_usd": "1.00"},
    )
    dumped = line.model_dump()
    assert dumped["fulfillment_data"]["supplier_price_usd"] == "1.00"
