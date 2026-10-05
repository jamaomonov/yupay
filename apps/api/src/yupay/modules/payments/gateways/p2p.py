"""P2P card transfer as a storefront payment method (ADR-0097).

The customer transfers an exact soʻm amount to the owner's Humo card; the
Telegram Business bot reads the @HUMOcardbot notification and the P2P intake
(``modules/p2p/intake.py``) settles the payment. There is no acquirer and no
redirect: ``create_intent`` holds the amount on a card for the rest of the
order's payment window and hands back the reservation; the storefront reads
the card number, holder and amount off the payment
(``payments.p2p_details``) and shows them with a clock.

Three things the other gateways do that this one does not:

* **No webhook of its own.** Settlement arrives through the P2P intake, which
  matches the transfer to the reservation by amount and card and calls
  ``payments.service.settle_provider_payment``. ``verify_webhook`` is
  therefore never reached and says so.
* **No refund API.** A transfer back is a human with a banking app;
  ``refund`` refuses, like Paynet's, and the runbook says what to do.
* **The amount can be bumped.** When the exact total is held by another
  payer on every eligible card, the reservation takes the next free amount
  (up to the card's cap). The customer is told the bumped figure; the extra
  soʻm are the price of amount-matching, the same trade the reseller
  top-up makes.

The admin provider state (active / maintenance / disabled) is the storefront
switch, read by ``payments.service.create_intent`` like every provider's.
The P2P settings ``mode`` (off / allowlist / all) stays the reseller
cabinet's gate and is not consulted here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import ConflictError, UpstreamUnavailableError
from yupay.modules.payments.gateways.base import (
    PaymentGatewayError,
    PaymentIntent,
    PaymentNotIntegratedError,
    RefundResult,
    WebhookEvent,
)

#: Below this much of the order's window left, a hold is not worth starting:
#: the customer would be typing the card number as the order expired.
MIN_WINDOW = timedelta(seconds=90)


class P2PGateway:
    """Exact-amount card transfer, settled by the Telegram P2P intake."""

    provider = "p2p"

    @property
    def available(self) -> bool:
        """Configured when the Telegram webhook secret is set.

        Whether a card exists and the Business connection is pinned is a
        database question, answered in :meth:`create_intent` — ``available``
        is read without a session (the admin provider list, ``get_gateway``).
        """
        return bool(get_settings().p2p_webhook_secret)

    async def create_intent(
        self,
        *,
        db: AsyncSession,
        order: Any,
        return_url: str,  # noqa: ARG002 -- no redirect step
    ) -> PaymentIntent:
        """Hold the order's total on a card until the order's payment window ends.

        Raises:
            PaymentGatewayError: the order is not in whole soʻm, its window is
                nearly over, the bot is not connected, no card fits the
                amount, or every nearby amount is held. The message is what
                the storefront shows.
        """
        # Lazy: ``p2p`` is a sibling module and imports from ``payments``
        # elsewhere; keeping the import inside the method avoids an import
        # cycle at module load.
        from yupay.modules.p2p import reservations
        from yupay.modules.p2p.models import P2PCard
        from yupay.modules.p2p.settings import load_settings

        if order.currency != "UZS":
            raise PaymentGatewayError(f"p2p only supports UZS, got {order.currency!r}")
        amount = Decimal(order.total_charged)
        if amount <= 0 or amount != amount.to_integral_value():
            raise PaymentGatewayError("order total must be a positive whole number of soʻm")
        if order.expires_at - now() < MIN_WINDOW:
            raise PaymentGatewayError("слишком мало времени на перевод — оформите заказ заново")
        settings = await load_settings(db)
        if not settings.business_connection_id:
            raise PaymentGatewayError("перевод на карту сейчас недоступен")
        try:
            reservation = await reservations.reserve_for_order(
                db, order_id=order.id, amount_uzs=int(amount), expires_at=order.expires_at
            )
        except ConflictError as exc:
            raise PaymentGatewayError("перевод на карту сейчас недоступен для этой суммы") from exc
        except UpstreamUnavailableError as exc:
            raise PaymentGatewayError("перевод на карту сейчас занят — попробуйте позже") from exc
        card = await db.get(P2PCard, reservation.card_id)
        return PaymentIntent(
            external_id=f"p2p:{reservation.number}",
            intent_url=None,
            status="pending",
            extra_metadata={
                "reservation_number": reservation.number,
                "amount_uzs": reservation.amount_uzs,
                "card_last4": card.pan_last4 if card is not None else None,
                "expires_at": reservation.expires_at.isoformat(),
            },
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        """Never reached: settlement comes through the Telegram P2P intake."""
        raise PaymentNotIntegratedError(
            "p2p has no payment webhook; transfers arrive through /webhooks/telegram/p2p"
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        """No API to send money back through: a refund is a manual transfer."""
        raise PaymentGatewayError(
            "P2P refunds are manual — transfer the amount back from the banking app "
            "and record it in the admin (docs/runbooks/p2p-deposit.md)"
        )


__all__ = ["MIN_WINDOW", "P2PGateway"]
