"""Fulfiller protocol.

Every supplier (mock, Steam, Riot, PUBG/Tencent, Spotify, Apple, in-house voucher
warehouse) implements this contract. The saga in ``fulfillment.service`` is
otherwise supplier-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
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


@runtime_checkable
class Fulfiller(Protocol):
    """Contract every supplier adapter must satisfy."""

    supplier: str

    @property
    def available(self) -> bool: ...

    async def fulfill(
        self,
        *,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult: ...

    async def check_status(
        self,
        *,
        task: FulfillmentTask,
    ) -> FulfillStatus: ...

    async def cancel(
        self,
        *,
        task: FulfillmentTask,
    ) -> None: ...
