"""Uzum Bank Merchant API — the third Uzbek acquirer, alongside Octo and Payme.

Uzum's checkout is a plain query-string GET URL built entirely client-side
(no prepare-payment API call at intent time — see
:func:`yupay.modules.uzum.service.build_checkout_url`). The actual money
movement happens later, out-of-band, via Uzum's own inverted webhooks
(``/check`` / ``/create`` / ``/confirm`` / ``/reverse`` / ``/status``) mounted
at ``/payments/uzum/*`` — see :mod:`yupay.modules.uzum.service` and
:mod:`yupay.modules.uzum.routes`. That callback chain is HTTP Basic-auth
protected and idempotent on its own terms (keyed by ``trans_id``), so this
adapter never accepts the generic ``/webhooks/payments/{provider}`` route,
and never issues a refund directly — Uzum reconciles reversals via
``/reverse`` initiated from the Uzum side, which lands back through the same
Merchant API, not through this class.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.modules.payments.gateways.base import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentIntent,
    PaymentNotIntegratedError,
    RefundResult,
    WebhookEvent,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class UzumGateway(PaymentGateway):
    """``PaymentGateway`` for Uzum Bank's hosted open-service checkout."""

    provider = "uzum"

    @property
    def available(self) -> bool:
        s = get_settings()
        return bool(
            s.uzum_service_id
            and ((s.uzum_login and s.uzum_password) or (s.uzum_test_login and s.uzum_test_password))
        )

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- Uzum keeps no DB-side state at intent time
        order: Any,
        return_url: str,
    ) -> PaymentIntent:
        # Deferred: ``uzum.service`` imports ``payments.service`` (for the
        # provider-lifecycle hooks), which imports this package back — a
        # module-level import here would be a circular import whenever
        # something reaches ``payments.gateways`` before ``uzum.routes`` has
        # (e.g. importing this package directly in a test). Mirrors the same
        # deferred-import pattern already used in ``payments/service.py`` and
        # ``payments/gateways/payme.py`` for cross-module edges like this one.
        from yupay.modules.uzum import service as uzum_svc

        if order.currency != "UZS":
            raise PaymentGatewayError(f"uzum only supports UZS, got {order.currency!r}")
        amount: Decimal = order.total_charged
        if amount is None or amount <= 0:
            raise PaymentGatewayError("order total_charged is non-positive")
        raw = amount * Decimal(100)
        if raw != raw.to_integral_value():
            raise PaymentGatewayError(f"order total_charged {amount} is not an exact tiyin amount")
        amount_tiyin = int(raw)
        intent_url = uzum_svc.build_checkout_url(
            order_id=order.id,
            amount_tiyin=amount_tiyin,
            return_url=return_url,
        )
        return PaymentIntent(
            external_id=f"uzum:{order.id}",
            intent_url=intent_url,
            status="pending",
            extra_metadata={"amount_tiyin": amount_tiyin},
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- Uzum never hits this route
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        raise PaymentNotIntegratedError(
            "Uzum uses the /payments/uzum/{check,create,confirm,reverse,status} "
            "endpoints, not verify_webhook"
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        raise PaymentGatewayError(
            "refund a Uzum payment from the Uzum side; it reconciles via /reverse"
        )


__all__ = ["UzumGateway"]
