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
