"""Dev/staging-only payment gateway.

Successful intent creation; webhook acceptance with no signature check beyond a shape
guard. The admin SPA hits ``POST /admin/payments/{id}/simulate-webhook`` to flip an
order through ``paid``. Disabled in production by checking ``Settings.environment``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.payments.gateways.base import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentIntent,
    RefundResult,
    WebhookEvent,
    WebhookOutcome,
)


class MockGateway(PaymentGateway):
    """No-op gateway used by tests and dev demos."""

    provider = "mock"

    @property
    def available(self) -> bool:
        return not get_settings().is_prod

    async def create_intent(
        self,
        *,
        order: Any,  # noqa: ANN401
        return_url: str,  # noqa: ARG002 -- mock ignores return_url
    ) -> PaymentIntent:
        external_id = f"mock_{new_id()}"
        return PaymentIntent(
            external_id=external_id,
            intent_url=f"https://mock.local/pay/{external_id}",
            status="pending",
            extra_metadata={"mock": True, "order_id": order.id},
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- mock ignores headers
        body: bytes,
    ) -> WebhookEvent:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentGatewayError(f"mock: invalid body: {exc}") from exc
        external_event_id = payload.get("event_id")
        external_payment_id = payload.get("payment_id")
        outcome: WebhookOutcome = payload.get("outcome", "succeeded")
        if not external_event_id or not external_payment_id:
            raise PaymentGatewayError("mock: event_id + payment_id are required")
        if outcome not in ("succeeded", "failed", "cancelled"):
            raise PaymentGatewayError(f"mock: unknown outcome {outcome!r}")
        return WebhookEvent(
            external_event_id=external_event_id,
            external_payment_id=external_payment_id,
            outcome=outcome,
            raw=payload,
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ANN401
        amount: Decimal,
    ) -> RefundResult:
        return RefundResult(
            external_refund_id=f"mock_refund_{new_id()}",
            amount=amount,
            extra_metadata={"mock": True, "payment_id": payment.id},
        )
