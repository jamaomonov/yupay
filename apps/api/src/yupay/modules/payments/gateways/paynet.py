"""Paynet — UZ terminal and mobile-app network, driven by a deep link.

Two halves that arrive from opposite directions:

* **Out:** this adapter builds a link that opens the Paynet app with our order
  id and amount already filled in, so the payer confirms and nothing is typed.
  No API call at intent time — the URL is assembled client-side, exactly like
  Payme's checkout link.
* **In:** the money movement lands later on ``/payments/paynet/uws``, Paynet's
  UWS JSON-RPC callback (``GetInformation`` → ``PerformTransaction``, and
  ``CancelTransaction`` for a reversal). That endpoint is authenticated and
  idempotent on its own terms, keyed on Paynet's ``transactionId``.

So this class never accepts the generic ``/webhooks/payments/{provider}``
route, and never refunds directly: a Paynet reversal is initiated on their side
and reconciles through ``CancelTransaction``.

**The link format is configuration, not code.** Paynet supplies the exact
template — host, parameter names, and whether the amount is in soʻm or tiyin —
after integration, and published third-party notes disagree with each other on
all three. ``paynet_pay_url_template`` is therefore a format string with named
placeholders: correcting it is an env change and a restart, not a release.
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


def build_pay_url(*, order_id: str, amount_tiyin: int) -> str:
    """Render the deep link that opens Paynet with this order pre-filled.

    Args:
        order_id: Our order id — the ``account`` Paynet sends back in ``fields``.
        amount_tiyin: Charge in minor units.

    Returns:
        The universal link, ready to hand to the browser.

    Raises:
        PaymentGatewayError: the configured template names a placeholder we do
            not supply — caught here rather than as a ``KeyError`` five frames
            down, because the template is operator-edited.
    """
    settings = get_settings()
    try:
        return settings.paynet_pay_url_template.format(
            service_id=settings.paynet_service_id,
            account=order_id,
            amount=amount_tiyin,
            # Both units are offered because their own documentation and the
            # third-party write-ups disagree about which the link carries.
            # Whichever it turns out to be, the template picks it.
            amount_major=Decimal(amount_tiyin) / Decimal(100),
        )
    except (KeyError, IndexError) as exc:
        raise PaymentGatewayError(
            f"paynet_pay_url_template has an unknown placeholder: {exc}"
        ) from exc


class PaynetGateway(PaymentGateway):
    """``PaymentGateway`` for Paynet's app deep link."""

    provider = "paynet"

    @property
    def available(self) -> bool:
        s = get_settings()
        # The UWS credentials gate the method, not the link: a link nobody can
        # settle against takes money into a void. Both halves or neither.
        return bool(s.paynet_username and s.paynet_password and s.paynet_pay_url_template)

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- nothing is written at intent time
        order: Any,
        return_url: str,  # noqa: ARG002 -- the app has nowhere to send the payer back to
    ) -> PaymentIntent:
        if order.currency != "UZS":
            raise PaymentGatewayError(f"paynet only supports UZS, got {order.currency!r}")
        amount: Decimal = order.total_charged
        if amount is None or amount <= 0:
            raise PaymentGatewayError("order total_charged is non-positive")
        raw = amount * Decimal(100)
        if raw != raw.to_integral_value():
            raise PaymentGatewayError(f"order total_charged {amount} is not an exact tiyin amount")
        amount_tiyin = int(raw)
        return PaymentIntent(
            external_id=f"paynet:{order.id}",
            intent_url=build_pay_url(order_id=order.id, amount_tiyin=amount_tiyin),
            status="pending",
            extra_metadata={"amount_tiyin": amount_tiyin},
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- Paynet never hits this route
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        raise PaymentNotIntegratedError(
            "Paynet uses the /payments/paynet/uws JSON-RPC endpoint, not verify_webhook"
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        raise PaymentGatewayError(
            "refund a Paynet payment on Paynet's side; it reconciles via CancelTransaction"
        )


__all__ = ["PaynetGateway", "build_pay_url"]
