"""Click Shop API — the first Uzbek acquirer routed through two surfaces.

Click's checkout is a plain query-string GET URL built entirely client-side
(no prepare-payment API call at intent time — see
:func:`yupay.modules.click.service.build_checkout_url`). The actual money
movement happens later, out-of-band, via Click's own inverted webhooks
(``/prepare`` / ``/complete``) mounted at ``/payments/click/*`` — see
:mod:`yupay.modules.click.service` and :mod:`yupay.modules.click.routes`.
That callback chain is MD5-``sign_string``-verified and idempotent on its
own terms (keyed by ``click_trans_id`` / ``merchant_prepare_id``), so this
adapter never accepts the generic ``/webhooks/payments/{provider}`` route,
and never issues a refund directly — Click v1 has no merchant-initiated
refund; reconciliation happens from the Click side.

Unlike every other acquirer in this package, Click needs **two** gateway
instances rather than one: the web storefront and the Telegram mini app each
have their own Click ``service_id`` + ``SECRET_KEY`` sharing one
``click_merchant_id`` (see ``core.config.Settings``). ``ClickGateway`` is
parametrised by ``provider`` (``"click"`` for web, ``"click_miniapp"`` for
the bot) so one class backs both registry entries instead of two
near-duplicate files.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

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

#: The two surfaces Click's Shop API is registered under, each with its own
#: ``service_id`` + ``SECRET_KEY`` (see :mod:`yupay.modules.click.service`).
ClickProvider = Literal["click", "click_miniapp"]


class ClickGateway(PaymentGateway):
    """``PaymentGateway`` for Click's hosted Shop API checkout, one surface at a time.

    Instantiate once per surface — ``ClickGateway(provider="click")`` for the
    web storefront, ``ClickGateway(provider="click_miniapp")`` for the
    Telegram mini app — and register both in
    :data:`yupay.modules.payments.gateways.REGISTRY`.
    """

    def __init__(self, *, provider: ClickProvider) -> None:
        """Bind this instance to one Click surface.

        Args:
            provider: ``"click"`` (web) or ``"click_miniapp"`` (Telegram mini
                app).
        """
        self.provider = provider

    @property
    def available(self) -> bool:
        s = get_settings()
        if self.provider == "click":
            return bool(s.click_merchant_id and s.click_service_id_web and s.click_secret_key_web)
        return bool(s.click_merchant_id and s.click_service_id_bot and s.click_secret_key_bot)

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- Click keeps no DB-side state at intent time
        order: Any,
        return_url: str,
    ) -> PaymentIntent:
        # Deferred: ``click.service`` imports ``payments.service`` (for the
        # provider-lifecycle hooks), which imports this package back — a
        # module-level import here would be a circular import whenever
        # something reaches ``payments.gateways`` before ``click.routes`` has
        # (e.g. importing this package directly in a test). Mirrors the same
        # deferred-import pattern already used in ``payments/service.py`` and
        # ``payments/gateways/uzum.py`` for cross-module edges like this one.
        from yupay.modules.click import service as click_svc

        if order.currency != "UZS":
            raise PaymentGatewayError(f"click only supports UZS, got {order.currency!r}")
        amount: Decimal = order.total_charged
        if amount is None or amount <= 0:
            raise PaymentGatewayError("order total_charged is non-positive")
        # Click's ``amount`` wire field is soums (major units), unlike the
        # tiyin the other Uzbek acquirers here use — see
        # ``click.service.build_checkout_url``'s docstring.
        intent_url = click_svc.build_checkout_url(
            provider=self.provider,
            order_id=order.id,
            amount=amount,
            return_url=return_url,
        )
        return PaymentIntent(
            external_id=f"click:{order.id}",
            intent_url=intent_url,
            status="pending",
            extra_metadata={"amount_soums": str(amount)},
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- Click never hits this route
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        raise PaymentNotIntegratedError(
            "Click uses the /payments/click/{prepare,complete} endpoints, not verify_webhook"
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        raise PaymentGatewayError(
            "Click v1 has no merchant-initiated refund; reconcile from the Click side"
        )


__all__ = ["ClickGateway"]
