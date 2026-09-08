"""Manual fulfiller — parks the task in ``in_progress`` for an admin.

Used for SKUs where there's no supplier API: the customer pays, the task
lands in the admin queue (``/admin/fulfillment/tasks?supplier=manual&...``),
and an operator finalises it via the ``/complete`` or ``/fail`` admin route.

Unlike ``MockFulfiller`` this isn't a dev-only stand-in — it's a real
fulfilment path. ``available`` is always ``True``: it doesn't depend on
``Settings.is_prod`` (we still want it live in prod) and it has no upstream
to be offline.
"""

from __future__ import annotations

from typing import Any

from yupay.core.clock import now
from yupay.modules.fulfillment.suppliers.base import (
    FulfillResult,
    FulfillStatus,
)


class ManualFulfiller:
    """Always returns ``in_progress`` — the human in the loop does the work.

    It has **no terminal failure of its own**, which is why every result here
    carries ``money_outcome=None``. A manual task only ever ends badly through
    the admin ``/fail`` route, and ``fulfillment.service.fail_manual_task``
    answers the money question there — an operator who bought the goods
    somewhere by hand is the only one who knows what happened to the money,
    and that route already leaves the refund to them explicitly.
    """

    supplier = "manual"

    @property
    def available(self) -> bool:
        return True

    async def fulfill(
        self,
        *,
        db: Any,  # noqa: ARG002
        order: Any,  # noqa: ARG002 -- not consulted; admin reads the order itself
        item: Any,  # noqa: ARG002
        idempotency_key: str,  # noqa: ARG002 -- task.id already uniquely keys the work
    ) -> FulfillResult:
        return FulfillResult(
            outcome="in_progress",
            external_order_id=None,
            artifact_kind=None,
            artifact=None,
            error=None,
            extra_metadata={"queued_at": now().isoformat()},
            money_outcome=None,
        )

    async def check_status(
        self,
        *,
        db: Any,  # noqa: ARG002
        task: Any,  # noqa: ARG002 -- nothing to poll; admin advances state
    ) -> FulfillStatus:
        return FulfillStatus(
            outcome="in_progress",
            artifact_kind=None,
            artifact=None,
            error=None,
            money_outcome=None,
        )

    async def cancel(
        self,
        *,
        db: Any,  # noqa: ARG002
        task: Any,  # noqa: ARG002
    ) -> None:
        # No upstream to roll back. The /cancel admin route already flipped
        # the task's status; nothing else to do.
        return None
