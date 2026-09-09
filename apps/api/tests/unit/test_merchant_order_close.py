"""The two guards on closing a refunded merchant order (M3c Task 6).

``fulfillment.service.end_a_refunded_merchant_order`` was reached from exactly
one place when this file was written — the refund seam, immediately after a
posting — and from there both of its guards are always satisfied: a merchant
order at the seam is ``fulfilling``, and ``refund_order`` posts the whole
charge and refuses any order money has already come back on, so a successful
posting *is* a complete settlement. **M3c Task 4 added the second caller the
last paragraph below anticipated** (``deposit.credit_deposit``, a settlement a
person books), which can reach both guards for real — and that makes testing
them more worth doing, not less: they are now on a path an operator drives.

Through the saga alone the guards were untestable and, left there, untested
full stop — which is how defensive code stops being defence and becomes
decoration. Calling the function directly is what gives each one a case, and it
was worth doing rather than declaring, because the rules are about money and
about a delivered order: the hand settlement can be partial, and it can be
booked against an order that a later manual delivery has since completed.

The partial half needs a ledger and lives with the rest of the money path in
``tests/integration/test_merchant_auto_refund.py``; this half needs no database
at all, and proves it.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.orders import service as orders_svc
from yupay.modules.orders.models import Order


class _NoDatabase:
    """A session that fails loudly on first use.

    The assertion is "the guard returned **before** asking the ledger
    anything", which a mock that answers politely would not make. Any attribute
    touched here is a query this test says must not happen.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the guard should have returned before touching db.{name}")


def _merchant_order(status: str) -> Order:
    return Order(id=new_id(), status=status, merchant_id=new_id())


async def test_a_delivered_order_is_never_closed_by_a_refund() -> None:
    """``delivered`` is out of ``FAILABLE_STATUSES``, and that is the point.

    Reversing a delivery is a refund that moves real money and belongs to
    ``payments``; writing ``failed`` over it would tell a reseller their order
    ended without goods while the codes were already in their hands. The one
    list both closers read (``orders.service.FAILABLE_STATUSES``) is what keeps
    the automatic path and the admin path agreeing about that.
    """
    order = _merchant_order("delivered")

    await ff_svc.end_a_refunded_merchant_order(
        cast(AsyncSession, _NoDatabase()),
        order=order,
        by="fulfillment",
        reason="fulfillment_failed",
        actor="fulfillment",
        task_id=new_id(),
    )

    assert order.status == "delivered"


async def test_the_three_statuses_a_refund_may_close_from_are_the_admins_own() -> None:
    """One list, not two spellings — and ``delivered`` is not in it.

    The constant is asserted rather than the behaviour because it is shared:
    ``mark_order_failed_admin`` rejects with ``409`` from anything outside it,
    and the refund silently declines. A value added to it changes both, which
    is the reason it is one list.
    """
    assert set(orders_svc.FAILABLE_STATUSES) == {"paid", "fulfilling", "fulfilled"}
    assert "delivered" not in orders_svc.FAILABLE_STATUSES
