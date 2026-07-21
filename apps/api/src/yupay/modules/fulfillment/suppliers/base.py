"""Fulfiller protocol.

Every supplier (mock, Steam, Riot, PUBG/Tencent, Spotify, Apple, in-house voucher
warehouse) implements this contract. The saga in ``fulfillment.service`` is
otherwise supplier-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem


FulfillOutcome = Literal["succeeded", "in_progress", "failed"]
ArtifactKind = Literal["voucher_code", "topup_receipt", "license_key"]


class FulfillerError(Exception):
    """Non-recoverable supplier error."""


class FulfillerNotIntegratedError(NotImplementedError):
    """Raised by stub suppliers that haven't been hooked up yet."""


@dataclass(frozen=True)
class FulfillResult:
    """Return type of :meth:`Fulfiller.fulfill`."""

    outcome: FulfillOutcome
    external_order_id: str | None
    artifact_kind: ArtifactKind | None
    artifact: dict[str, Any] | None
    error: str | None
    extra_metadata: dict[str, Any]


@dataclass(frozen=True)
class FulfillStatus:
    """Return type of :meth:`Fulfiller.check_status`."""

    outcome: FulfillOutcome
    artifact_kind: ArtifactKind | None
    artifact: dict[str, Any] | None
    error: str | None
    # Structured flags the reconciler merges onto ``task.extra_metadata`` — e.g.
    # ``needs_reconciliation`` / ``supplier_refunded`` / ``give_amount_shortfall_units``.
    # Mirrors ``FulfillResult.extra_metadata`` so a status discovered by the
    # webhook/poll path (the only path Waxpeer has) surfaces the same queryable
    # flags as one discovered synchronously, instead of only in ``last_error``.
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Fulfiller(Protocol):
    """Contract every supplier adapter must satisfy."""

    supplier: str

    @property
    def available(self) -> bool: ...

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult: ...

    async def check_status(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> FulfillStatus: ...

    async def cancel(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> None: ...
