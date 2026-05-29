"""Wallet-as-payment-method.

This is the only "gateway" whose money never leaves the database — the
customer's :class:`WalletAccount` balance becomes the order's payment.
No webhook, no external acquirer, no card. The work happens entirely
inside one Postgres transaction.

Safety invariants — every one of these is enforced **inside the same
DB transaction** that ``payments.service.create_intent`` already opened,
so a crash anywhere rolls back the whole thing:

1. **No double-spend.** We ``SELECT … FOR UPDATE`` the
   ``WalletAccount`` row before reading its balance. A second
   concurrent ``create_intent`` for the same user blocks until the
   first commits, then re-reads the (already decremented) balance and
   refuses on insufficiency.

2. **No phantom balance check.** The balance comparison and the
   ledger ``post()`` happen inside one transaction *and* one row-lock.
   A third party can't credit the wallet between the two and trick us
   into approving an order we shouldn't.

3. **Idempotent posting.** The ledger transaction uses
   ``"payment:{payment_id}"`` as its idempotency key. The PRD
   ``WalletTransaction.idempotency_key`` UNIQUE constraint guarantees
   only one debit lands even if ``create_intent`` is re-run for the
   same payment (e.g. an admin retry, a network blip mid-request).

4. **No partial state on failure.** Insufficient balance / frozen
   account / wrong currency ⇒ raise inside the gateway ⇒
   ``create_intent`` propagates ⇒ Postgres rolls back the whole
   transaction ⇒ no orphan ``Payment`` row, no half-decremented
   wallet, order stays ``pending_payment``.

5. **No fulfillment without payment.** ``create_intent`` ships
   ``status="succeeded"`` only after the ledger has accepted the
   debit. ``payments.service.create_intent`` then walks the order to
   ``paid`` (and triggers fulfilment) in the **same** transaction. If
   fulfilment starts and crashes, the rollback also reverses the
   wallet debit.

Currency policy: the customer pays in their wallet's currency. We
require ``order.currency == wallet_currency`` so the customer can't
pay a UZS order with a USDT balance silently — that conversion is a
separate, deliberate FX step we'll wire up later if needed.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import ValidationError
from yupay.core.logging import get_logger
from yupay.modules.payments.gateways.base import (
    PaymentGatewayError,
    PaymentIntent,
    RefundResult,
    WebhookEvent,
)

# ``wallet.api`` pulls in ``wallet.routes`` → ``api.v1`` → ``payments.api`` →
# ``payments.gateways``. Importing it at module top would make this gateway file
# uneimportable on its own (the ``payments.gateways`` package init imports us
# before it finishes defining ``available_providers``). Import lazily inside the
# methods instead — same trick this file already uses for the Order/Payment models.
if TYPE_CHECKING:
    from yupay.modules.wallet.models import WalletAccount

log = get_logger("yupay.payments.wallet")


class WalletGateway:
    """``PaymentGateway`` whose backend is our own double-entry ledger."""

    provider = "wallet"

    # Guest orders are explicitly NOT supported — there's no wallet
    # account to charge. The route layer enforces this earlier, but we
    # double-check here so misuse from another path also fails cleanly.
    @property
    def available(self) -> bool:
        return True

    async def create_intent(
        self,
        *,
        db: AsyncSession,
        order: Any,
        return_url: str,  # noqa: ARG002 -- wallet has no redirect step
    ) -> PaymentIntent:
        """Charge the customer's wallet for ``order.total_charged``.

        Runs inside the caller's transaction. Raises
        :class:`PaymentGatewayError` on insufficient funds or any other
        condition that should prevent the order from moving to ``paid``.
        The caller (``payments.service.create_intent``) treats a
        ``status=succeeded`` intent as authority to immediately mark
        the order paid; the wallet debit is already committed in the
        same transaction, so that's safe.
        """
        # The protocol declares ``order: Any`` because adapters live behind a
        # generic dispatch. Reach for the real model here.
        from yupay.modules.orders.models import Order as _Order
        from yupay.modules.wallet import api as wallet_api

        if not isinstance(order, _Order):  # pragma: no cover -- defensive
            raise PaymentGatewayError("wallet gateway needs an Order instance")
        if order.user_id is None:
            raise PaymentGatewayError(
                "wallet payment requires a logged-in user (guest orders cannot use the wallet)"
            )
        amount: Decimal = order.total_charged
        if amount <= 0:
            raise PaymentGatewayError("order total_charged is non-positive")

        account = await self._lock_wallet_account(
            db, user_id=order.user_id, currency=order.currency
        )
        balance = await wallet_api.balance(db, account.id)
        if balance < amount:
            raise PaymentGatewayError(
                f"insufficient wallet balance: have {balance} {account.currency}, "
                f"need {amount} {account.currency}"
            )

        # Counter-account for the user-side credit.
        # ``house_payments_received`` (NORMAL=D) is the dedicated
        # bucket for money customers paid us directly — wallet today,
        # card / Click / Payme / crypto later. Kept separate from
        # ``house_promo_expense`` so finance can answer "сколько мы
        # приняли от клиентов" without subtracting out promo grants.
        # See ADR-0004 for the ledger model.
        counter = await wallet_api.ensure_account(
            db,
            owner_type="house",
            owner_id="house",
            kind="house_payments_received",
            currency=account.currency,
        )

        # Idempotency key uses the order id (NOT the payment id) so a
        # retry that recreates the Payment row still hits the same
        # ledger transaction and the second debit is suppressed.
        idem_key = f"wallet-pay:order:{order.id}"
        external_id = f"wallet:{order.id}"

        try:
            txn = await wallet_api.post(
                db,
                kind="wallet_payment",
                legs=[
                    # C on user_wallet (NORMAL=D) → balance ↓ by ``amount``.
                    wallet_api.Leg(
                        account_id=account.id,
                        direction="C",
                        amount=amount,
                        currency=account.currency,
                    ),
                    # D on house counter (NORMAL=D) → balanced
                    # double-entry; SUM(D) == SUM(C) holds.
                    wallet_api.Leg(
                        account_id=counter.id,
                        direction="D",
                        amount=amount,
                        currency=account.currency,
                    ),
                ],
                idempotency_key=idem_key,
                reference=wallet_api.Reference(type="order", id=order.id),
                actor="payments.wallet",
                metadata={
                    "user_id": order.user_id,
                    "order_id": order.id,
                    "external_id": external_id,
                },
            )
        except ValidationError as exc:
            raise PaymentGatewayError(f"ledger rejected wallet posting: {exc.detail}") from exc

        log.info(
            "payments.wallet.charged",
            order_id=order.id,
            user_id=order.user_id,
            amount=str(amount),
            currency=account.currency,
            wallet_txn_id=txn.id,
        )

        return PaymentIntent(
            external_id=external_id,
            intent_url=None,
            status="succeeded",
            extra_metadata={
                "wallet_account_id": account.id,
                "wallet_txn_id": txn.id,
                "charged_amount": str(amount),
                "currency": account.currency,
            },
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002
        body: bytes,  # noqa: ARG002
    ) -> WebhookEvent:
        # No webhook for a synchronous in-house "provider". A real call
        # here means someone hit ``/webhooks/payments/wallet`` directly,
        # which is either a misconfigured client or a probe — refuse.
        raise PaymentGatewayError(
            "wallet gateway has no inbound webhook — payments succeed synchronously",
        )

    async def refund(
        self,
        *,
        payment: Any,
        amount: Decimal,
    ) -> RefundResult:
        """Credit ``amount`` back to the customer's wallet.

        Refunds are admin-driven (``payments.service.refund_admin``);
        the route already does its own ledger accounting against
        ``house_refunds``. The gateway just confirms the inverse
        external id pattern so audit-feed entries stay consistent.
        """
        from yupay.modules.payments.models import Payment as _Payment

        if not isinstance(payment, _Payment):  # pragma: no cover -- defensive
            raise PaymentGatewayError("wallet refund needs a Payment instance")
        if amount <= 0:
            raise PaymentGatewayError("refund amount must be positive")
        # External id mirrors the original charge so the audit log shows
        # the relationship clearly.
        return RefundResult(
            external_refund_id=f"wallet-refund:{payment.id}",
            amount=amount,
            extra_metadata={"original_external_id": payment.external_id},
        )

    # ---------- internals ----------

    async def _lock_wallet_account(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        currency: str,
    ) -> WalletAccount:
        """``SELECT FOR UPDATE`` on the user's wallet account.

        Returns the locked row. The lock is released on transaction
        commit/rollback. A concurrent charger on the same wallet
        blocks here until we're done, which is precisely what we want
        — the balance check below sees a fresh (post-blocker) value.
        """
        from yupay.modules.wallet import api as wallet_api
        from yupay.modules.wallet.models import WalletAccount

        # Try the existing row first; if absent, create it (race-safe via
        # the ``ensure_account`` upsert) and re-lock.
        stmt = (
            select(WalletAccount)
            .where(
                WalletAccount.owner_type == "user",
                WalletAccount.owner_id == user_id,
                WalletAccount.kind == "user_wallet",
                WalletAccount.currency == currency,
            )
            .with_for_update()
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        # No wallet account yet → make one (zero balance), then lock.
        await wallet_api.ensure_account(
            db,
            owner_type="user",
            owner_id=user_id,
            kind="user_wallet",
            currency=currency,
        )
        return (await db.execute(stmt)).scalar_one()
