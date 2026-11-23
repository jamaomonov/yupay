"""UzQR — pay by scanning a dynamic QR in any Uzbek banking app (ADR-0106).

We are the "POS" of UzQR's POS API: ``create_intent`` asks UzQR for an
invoice on the order's exact total and keeps the QR text on the payment; the
storefront draws it with a clock (``payments.p2p_details.payment_out``).
UzQR never calls us back. The scheduler polls every pending invoice
(``modules/uzqr/poll.py``) and books a paid one through
``payments.service.settle_provider_payment`` — the same chokepoint Payme's
callback uses — and cancels the invoice once the order's window is gone.

* **No webhook.** ``verify_webhook`` is never reached and says so.
* **No refund.** UzQR has refunds switched off; a refund is a transfer back
  from the bank, recorded in the admin (runbook ``uzqr.md``).
* **No fiscal receipt yet.** The spec wants a link to the GNK receipt after
  each payment; we have no virtual till, and UzQR accepts a paid invoice
  without one. Recorded as debt in ADR-0106.
"""

from __future__ import annotations

import secrets
import string
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.modules.payments.gateways.base import (
    PaymentGatewayError,
    PaymentIntent,
    PaymentNotIntegratedError,
    RefundResult,
    WebhookEvent,
)
from yupay.modules.uzqr import client

#: Below this much of the order's window left, a QR is not worth showing:
#: the payer would be opening the banking app as the order expired.
MIN_WINDOW = timedelta(seconds=90)

_ALPHABET = string.ascii_uppercase + string.digits


def new_external_id() -> str:
    """Our id for one UzQR operation: 20 alphanumerics, the spec's maximum.

    Random rather than derived from the order: an order can be paid by a second
    attempt after a cancelled first, and a reused ``external_id`` would replay
    the first invoice (spec §2.3.2).
    """
    return "YP" + "".join(secrets.choice(_ALPHABET) for _ in range(18))


class UzqrGateway:
    """Dynamic QR through UzQR's POS API, settled by the scheduler's poll."""

    provider = "uzqr"

    @property
    def available(self) -> bool:
        """Configured when both the INN and the API key are set."""
        s = get_settings()
        return bool(s.uzqr_inn and s.uzqr_api_key)

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- nothing of ours is written here
        order: Any,
        return_url: str,  # noqa: ARG002 -- the payer never leaves the page
    ) -> PaymentIntent:
        """Ask UzQR for an invoice on the order's total and keep its QR text.

        Raises:
            PaymentGatewayError: the order is not in UZS, its total is not an
                exact tiyin amount, its window is nearly over, or UzQR refused
                or did not answer. The message is what the storefront shows.
        """
        if order.currency != "UZS":
            raise PaymentGatewayError(f"uzqr only supports UZS, got {order.currency!r}")
        amount = Decimal(order.total_charged)
        if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise PaymentGatewayError("order total must be a positive tiyin amount")
        if order.expires_at - now() < MIN_WINDOW:
            raise PaymentGatewayError("слишком мало времени на оплату — оформите заказ заново")
        external_id = new_external_id()
        try:
            invoice = await client.create_invoice(external_id=external_id, amount=amount)
        except client.UzqrError as exc:
            raise PaymentGatewayError("оплата по QR сейчас недоступна") from exc
        except client.UzqrUnavailableError as exc:
            raise PaymentGatewayError("оплата по QR не отвечает — попробуйте позже") from exc
        return PaymentIntent(
            external_id=f"uzqr:{invoice.invoice_id}",
            intent_url=None,
            status="pending",
            extra_metadata={
                "invoice_id": invoice.invoice_id,
                "uzqr_external_id": external_id,
                "qr_text": invoice.qr_text,
            },
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        """Never reached: UzQR has no callback, the scheduler polls."""
        raise PaymentNotIntegratedError("uzqr has no webhook; payments are polled")

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        """UzQR refunds are switched off on their side: a refund is manual."""
        raise PaymentGatewayError(
            "UzQR refunds are manual — transfer the amount back from the bank "
            "and record it in the admin (docs/runbooks/uzqr.md)"
        )


__all__ = ["MIN_WINDOW", "UzqrGateway", "new_external_id"]
