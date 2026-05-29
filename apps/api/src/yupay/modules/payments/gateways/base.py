"""Payment gateway protocol.

Every provider (mock + every real acquirer) implements this interface. Composition,
retries, audit logging are the service's job — adapters stay thin.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ``pending`` is a no-op signal: a signed-but-non-terminal callback (e.g. Octo's
# ``created`` / ``waiting_for_capture``). The service records it for audit but does
# not move the FSM. ``mock`` and ``wallet`` never emit it. See ADR-0020.
WebhookOutcome = Literal["succeeded", "failed", "cancelled", "pending"]


class PaymentGatewayError(Exception):
    """Raised by an adapter on any non-recoverable provider error."""


class PaymentNotIntegratedError(NotImplementedError):
    """Raised by stub adapters that haven't been hooked up to a real provider yet."""


@dataclass(frozen=True)
class PaymentIntent:
    """What a successful ``create_intent`` returns."""

    external_id: str
    intent_url: str | None
    status: Literal["pending", "requires_action", "succeeded"]
    extra_metadata: dict[str, Any]


@dataclass(frozen=True)
class WebhookEvent:
    """Result of ``verify_webhook``."""

    external_event_id: str
    external_payment_id: str | None
    outcome: WebhookOutcome
    raw: dict[str, Any]


@dataclass(frozen=True)
class RefundResult:
    """Result of ``refund``."""

    external_refund_id: str
    amount: Decimal
    extra_metadata: dict[str, Any]


@runtime_checkable
class PaymentGateway(Protocol):
    """Contract every payment adapter implements."""

    provider: str

    @property
    def available(self) -> bool:
        """Whether this adapter can actually serve requests in the current env."""
        ...

    async def create_intent(
        self,
        *,
        db: AsyncSession,
        order: Any,
        return_url: str,
    ) -> PaymentIntent: ...

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> WebhookEvent: ...

    async def refund(
        self,
        *,
        payment: Any,
        amount: Decimal,
    ) -> RefundResult: ...
