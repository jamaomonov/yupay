"""Payme (Paycom) — the other major Uzbek acquirer, alongside Octo.

Payme's checkout is a base64-encoded GET URL built entirely client-side (no
prepare-payment API call at intent time — see
:func:`yupay.modules.payme.service.build_checkout_url`). The actual money
movement happens later, out-of-band, via Payme's Merchant JSON-RPC callback
(``CheckPerformTransaction`` / ``CreateTransaction`` / ``PerformTransaction`` /
``CancelTransaction``) mounted at ``/payments/payme/merchant`` — see
:mod:`yupay.modules.payme.service` and :mod:`yupay.modules.payme.routes`. That
callback is signed and idempotent on its own terms (keyed by ``payme_id``), so
this adapter never accepts the generic ``/webhooks/payments/{provider}`` route,
and never issues a refund directly — Payme reconciles refunds via
``CancelTransaction`` initiated from the Payme cabinet, which lands back through
the same Merchant API, not through this class.
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


class PaymeGateway(PaymentGateway):
    """``PaymentGateway`` for Payme's hosted checkout."""

    provider = "payme"

    @property
    def available(self) -> bool:
        s = get_settings()
        return bool(s.payme_merchant_id and (s.payme_key or s.payme_test_key))

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- Payme keeps no DB-side state at intent time
        order: Any,
        return_url: str,
    ) -> PaymentIntent:
        # Deferred: ``payme.service`` imports ``payments.service`` (for the
        # provider-lifecycle hooks), which imports this package back — a
        # module-level import here would be a circular import whenever
        # something reaches ``payments.gateways`` before ``payme.routes`` has
        # (e.g. importing this package directly in a test). Mirrors the same
        # deferred-import pattern already used in ``payments/service.py`` and
        # ``payments/gateways/wallet.py`` for cross-module edges like this one.
        from yupay.modules.payme import service as payme_svc

        if order.currency != "UZS":
            raise PaymentGatewayError(f"payme only supports UZS, got {order.currency!r}")
        amount: Decimal = order.total_charged
        if amount is None or amount <= 0:
            raise PaymentGatewayError("order total_charged is non-positive")
        raw = amount * Decimal(100)
        if raw != raw.to_integral_value():
            raise PaymentGatewayError(f"order total_charged {amount} is not an exact tiyin amount")
        amount_tiyin = int(raw)
        intent_url = payme_svc.build_checkout_url(
            order_id=order.id,
            amount_tiyin=amount_tiyin,
            return_url=return_url,
        )
        return PaymentIntent(
            external_id=f"payme:{order.id}",
            intent_url=intent_url,
            status="pending",
            extra_metadata={"amount_tiyin": amount_tiyin},
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- Payme never hits this route
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        raise PaymentNotIntegratedError(
            "Payme uses the /payments/payme/merchant JSON-RPC endpoint, not verify_webhook"
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        raise PaymentGatewayError(
            "refund a Payme payment from the Payme cabinet; it reconciles via CancelTransaction"
        )


__all__ = ["PaymeGateway"]
