"""Stub fulfillers — reserve a slug, refuse to do real work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerNotIntegratedError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem


#: A stub has no upstream, no credentials and no purchase — nothing it does
#: can move money, so every one of its failures leaves our balance whole,
#: ``cancel`` included. ``process_task`` turns these raises into a ``failed``
#: task, and a stub's failure that read ``SPENT`` or ``UNKNOWN`` would park a
#: human on an order nobody was ever billed for. The two integrated adapters
#: answer ``UNKNOWN`` from *their* ``cancel`` because their facts differ, not
#: because the rule does — see :class:`FulfillerNotIntegratedError`.
_NOTHING_WAS_EVER_SPENT = MoneyOutcome.RETURNED


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
        raise FulfillerNotIntegratedError(self.todo_message, money_outcome=_NOTHING_WAS_EVER_SPENT)

    async def check_status(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> FulfillStatus:
        raise FulfillerNotIntegratedError(self.todo_message, money_outcome=_NOTHING_WAS_EVER_SPENT)

    async def cancel(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        raise FulfillerNotIntegratedError(self.todo_message, money_outcome=_NOTHING_WAS_EVER_SPENT)
