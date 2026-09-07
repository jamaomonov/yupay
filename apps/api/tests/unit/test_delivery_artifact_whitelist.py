"""A delivery artifact must expose ONLY whitelisted keys to a buyer.

Internal/supplier fields (source, external ids, sku/inventory ids, raw units)
stored on the row for audit must never reach an API a buyer can read.

Since M2 Task 5 that is two surfaces, not one: the storefront's
``GET /orders/{id}/deliveries`` and the machine API's
``GET /merchant/v1/orders/{merchant_order_id}``, which hands a reseller the
voucher code on purpose. Both call ``fulfillment.service.buyer_safe_artifact``,
so this pins the one filter rather than one of its callers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from yupay.modules.fulfillment.models import Delivery
from yupay.modules.fulfillment.service import buyer_safe_artifact


def _row(artifact: dict[str, Any]) -> Delivery:
    """A real ``Delivery`` row, unattached to any session."""
    return Delivery(
        id="d1",
        order_item_id="oi1",
        channel="in_app",
        artifact_kind="voucher_code",
        artifact=artifact,
        delivered_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_supplier_internal_keys_are_stripped() -> None:
    kept = buyer_safe_artifact(
        _row(
            {
                "code": "GIFT-123",
                "source": "waxpeer",
                "external_id": "mock_x",
                "external_order_id": "wp-999",
                "external_product_id": "p-1",
                "inventory_code_id": "inv-7",
                "sku_id": "sku-abc",
                "catalogue_name": "internal-cat",
                "qty": 1,
                "amount_units": "20000",
                "give_amount_units": "500",
            }
        )
    )
    assert kept == {"code": "GIFT-123"}


def test_customer_supplied_and_deliverable_keys_survive() -> None:
    kept = buyer_safe_artifact(
        _row(
            {
                "steam_login": "player42",
                "fulfillment_data": {"steam_login": "player42"},
                "key": "AAAA-BBBB",
                "message": "Enjoy!",
                "source": "waxpeer",
            }
        )
    )
    assert kept == {
        "steam_login": "player42",
        "fulfillment_data": {"steam_login": "player42"},
        "key": "AAAA-BBBB",
        "message": "Enjoy!",
    }


def test_an_empty_artifact_survives_without_a_crash() -> None:
    """``Delivery.artifact`` is NOT NULL, but an empty dict is legal."""
    assert buyer_safe_artifact(_row({})) == {}
