"""Dev/staging-only fulfiller.

Returns a fake artifact synchronously so the order can be walked through the full
lifecycle in tests and demos without any supplier dependency. Disabled in prod
via :attr:`MockFulfiller.available`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillResult,
    FulfillStatus,
)

if TYPE_CHECKING:
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem


class MockFulfiller(Fulfiller):
    """No-op fulfiller used by tests and the dev admin SPA."""

    supplier = "mock"

    @property
    def available(self) -> bool:
        return not get_settings().is_prod

    async def fulfill(
        self,
        *,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        # Branch on product kind so the demo flow looks plausible end-to-end:
        # top-up products mint a receipt that echoes the player_id the user
        # entered at checkout; vouchers mint a copyable fake code.
        product = item.sku.product if item.sku is not None else None
        kind = product.kind if product is not None else "voucher"
        external_id = f"mock_{new_id()}"

        if kind == "top_up":
            artifact_kind = "topup_receipt"
            artifact: dict[str, object] = {
                "external_id": external_id,
                "fulfillment_data": item.fulfillment_data,
                "sku_id": item.sku_id,
                "qty": item.qty,
            }
        else:
            artifact_kind = "voucher_code"
            artifact = {
                "code": f"MOCK-{item.id[-12:].upper()}",
                "sku_id": item.sku_id,
                "qty": item.qty,
            }

        return FulfillResult(
            outcome="succeeded",
            external_order_id=external_id,
            artifact_kind=artifact_kind,  # type: ignore[arg-type]
            artifact=artifact,
            error=None,
            extra_metadata={
                "mock": True,
                "order_id": order.id,
                "idempotency_key": idempotency_key,
                "product_kind": kind,
            },
        )

    async def check_status(
        self,
        *,
        task: FulfillmentTask,  # noqa: ARG002 -- mock is always already done
    ) -> FulfillStatus:
        return FulfillStatus(
            outcome="succeeded",
            artifact_kind="voucher_code",
            artifact={"code": "MOCK"},
            error=None,
        )

    async def cancel(
        self,
        *,
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        return None
