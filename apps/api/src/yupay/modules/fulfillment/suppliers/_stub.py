"""Stub fulfillers — reserve a slug, refuse to do real work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerNotIntegratedError,
    FulfillResult,
    FulfillStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem


@dataclass(frozen=True)
class StubFulfiller(Fulfiller):
    """Stub supplier — every method raises :class:`FulfillerNotIntegratedError`."""

    supplier: str
    todo_message: str

    @property
    def available(self) -> bool:
        return False

    async def fulfill(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        order: Order,  # noqa: ARG002
        item: OrderItem,  # noqa: ARG002
        idempotency_key: str,  # noqa: ARG002
    ) -> FulfillResult:
        raise FulfillerNotIntegratedError(self.todo_message)

    async def check_status(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> FulfillStatus:
        raise FulfillerNotIntegratedError(self.todo_message)

    async def cancel(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        raise FulfillerNotIntegratedError(self.todo_message)
