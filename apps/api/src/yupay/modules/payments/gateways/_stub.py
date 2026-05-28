"""Helper to declare a stub gateway in one line per provider.

Stub gateways exist so the registry slug, the webhook URL, and the contract are
nailed down before the real adapter lands. They raise ``PaymentNotIntegratedError``
on every concrete call.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from yupay.modules.payments.gateways.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentNotIntegratedError,
    RefundResult,
    WebhookEvent,
)


@dataclass(frozen=True)
class StubGateway(PaymentGateway):
    """Stub provider that reserves a slug and refuses to do anything else."""

    provider: str
    todo_message: str

    @property
    def available(self) -> bool:
        return False

    async def create_intent(
        self,
        *,
        db: Any,  # noqa: ARG002
        order: Any,  # noqa: ARG002
        return_url: str,  # noqa: ARG002
    ) -> PaymentIntent:
        raise PaymentNotIntegratedError(self.todo_message)

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        raise PaymentNotIntegratedError(self.todo_message)

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        raise PaymentNotIntegratedError(self.todo_message)
