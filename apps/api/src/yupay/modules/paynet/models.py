"""SQLAlchemy ORM for the ``paynet`` module.

One row per Paynet transaction. Unlike Payme there is no "created" state to
model: UWS has no CreateTransaction — ``PerformTransaction`` both opens and
settles in a single call, so a row exists only once money has moved. That
leaves two stored states, ``1`` (successful) and ``2`` (cancelled); the third
value in Paynet's enum, ``3``, means "no such transaction" and is therefore the
absence of a row rather than a value in it.

``provider_trn_id`` is the identifier we hand back, and Paynet types it as a
64-bit **integer**. Our order ids are UUIDs, so the number has to come from
somewhere: a dedicated sequence, allocated once when the transaction is
performed and then immutable, because it is what Paynet quotes in reconciliation
and on a receipt.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base

#: Source of ``provider_trn_id``. Starts at 1000 so the first live id is not a
#: single digit — a one-character identifier in a support chat is unreadable
#: and indistinguishable from a typo.
PROVIDER_TRN_ID_SEQ = Sequence("paynet_provider_trn_id_seq", start=1000)

STATE_SUCCESS = 1
STATE_CANCELLED = 2
#: Not a stored state — the answer ``CheckTransaction`` gives for a
#: ``transactionId`` we have never seen. The spec requires a successful
#: envelope carrying this, not an error.
STATE_NOT_FOUND = 3


class PaynetTransaction(Base):
    """One Paynet payment, keyed on Paynet's own ``transactionId``."""

    __tablename__ = "paynet_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    #: Paynet's transaction id — their idempotency key, and ours. A replayed
    #: ``PerformTransaction`` carries the same value and must not charge twice.
    paynet_transaction_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: What we return as ``providerTrnId``. Allocated once, never reused.
    provider_trn_id: Mapped[int] = mapped_column(
        BigInteger,
        PROVIDER_TRN_ID_SEQ,
        nullable=False,
        server_default=PROVIDER_TRN_ID_SEQ.next_value(),
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Minor units, as Paynet sends them. 1 soʻm = 100 tiyin.
    amount_tiyin: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The ``serviceId`` the payment came in under, stored so a second service
    #: added later is distinguishable in the statement without a schema change.
    service_id: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[int] = mapped_column(Integer, nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("paynet_transaction_id", name="uq_paynet_transactions_external"),
        UniqueConstraint("provider_trn_id", name="uq_paynet_transactions_provider_trn"),
        CheckConstraint("state IN (1, 2)", name="state_known"),
        Index("ix_paynet_transactions_order", "order_id"),
        # GetStatement pages a time window of successful rows, newest last.
        Index("ix_paynet_transactions_state_performed", "state", "performed_at"),
    )


__all__ = [
    "PROVIDER_TRN_ID_SEQ",
    "STATE_CANCELLED",
    "STATE_NOT_FOUND",
    "STATE_SUCCESS",
    "PaynetTransaction",
]
