"""The customer delivery DTO must expose ONLY whitelisted artifact keys.

Internal/supplier fields (source, external ids, sku/inventory ids, raw units)
stored on the row for audit must never reach the customer-facing API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from yupay.modules.fulfillment.routes import _to_customer_delivery_out


@dataclass
class _Row:
    id: str
    order_item_id: str
    channel: str
    artifact_kind: str
    artifact: dict[str, Any]
    delivered_at: datetime


def _row(artifact: dict[str, Any]) -> _Row:
    return _Row(
        id="d1",
        order_item_id="oi1",
        channel="in_app",
        artifact_kind="voucher_code",
        artifact=artifact,
        delivered_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_supplier_internal_keys_are_stripped() -> None:
    out = _to_customer_delivery_out(
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
    assert out.artifact == {"code": "GIFT-123"}


def test_customer_supplied_and_deliverable_keys_survive() -> None:
    out = _to_customer_delivery_out(
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
    assert out.artifact == {
        "steam_login": "player42",
        "fulfillment_data": {"steam_login": "player42"},
        "key": "AAAA-BBBB",
        "message": "Enjoy!",
    }
