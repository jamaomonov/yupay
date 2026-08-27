"""SQLAlchemy ORM for the ``affiliate`` module.

Six tables. Two of the constraints here carry the design rather than merely
describing it:

``UNIQUE(user_id)`` on :class:`AffiliateAttribution` is what makes a buyer
belong to exactly one partner forever — the guarantee lives in the database,
not in a service that remembers to check.

``UNIQUE(order_id)`` on :class:`AffiliateCommission` is the whole of the
accrual sweep's idempotency. Two overlapping ticks cannot pay twice, and a
retried pass is free.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class AffiliatePartner(Base):
    """A partner, and their application.

    Application and account are one row, not two: the landing form inserts
    ``status='pending'`` and an admin moves it to ``active``. Nothing is copied
    on approval, and there is no state where an application is approved but the
    account does not yet exist.

    ``password_hash`` stays empty until the partner follows the set-password
    link, so an approved-but-not-yet-activated partner is simply one that
    cannot log in.

    ``user_id`` is the optional link to a buyer account. It exists for exactly
    one rule — a partner may not redeem their own code.
    """

    __tablename__ = "affiliate_partners"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'rejected')",
            name="ck_affiliate_partners_status",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    admin_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AffiliateCode(Base):
    """A promo code owned by a partner.

    The percentages live on the code rather than the partner so one partner can
    run several codes on different channels with different terms at no extra
    cost. ``commission_percent`` is read live at accrual time, so raising a
    code's rate raises it for that code's future orders — the intuitive
    behaviour, and simpler than freezing a rate per referred buyer.

    Bounds are enforced in the database because they are the guard rail on our
    own margin: the spec measures break-even on the thinnest SKU at about a
    12.2% discount.
    """

    __tablename__ = "affiliate_codes"
    __table_args__ = (
        CheckConstraint(
            "discount_percent >= 3 AND discount_percent <= 10",
            name="ck_affiliate_codes_discount_range",
        ),
        CheckConstraint(
            "commission_percent >= 1 AND commission_percent <= 2",
            name="ck_affiliate_codes_commission_range",
        ),
        CheckConstraint("code = upper(code)", name="ck_affiliate_codes_upper"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: Stored uppercase; lookups normalise the buyer's input the same way.
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AffiliateAttribution(Base):
    """A buyer permanently bound to the partner who introduced them.

    ``UNIQUE(user_id)`` is the guarantee, not a convention. It also makes the
    write race-safe without a lock: the row is created in the transaction that
    marks the first order paid, and a loser simply hits the constraint.
    """

    __tablename__ = "affiliate_attributions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_affiliate_attributions_user"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_codes.id", ondelete="RESTRICT"), nullable=False
    )
    #: The order that created the binding. Nullable only so a future admin
    #: tool can bind a buyer by hand without inventing an order.
    first_order_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AffiliateCommission(Base):
    """Commission earned on one delivered order.

    ``UNIQUE(order_id)`` is the accrual sweep's idempotency. ``percent`` and
    ``base_amount`` are frozen here at accrual time so that later edits to the
    code cannot revalue money already earned.
    """

    __tablename__ = "affiliate_commissions"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_affiliate_commissions_order"),
        CheckConstraint(
            "status IN ('pending', 'available', 'paid', 'void')",
            name="ck_affiliate_commissions_status",
        ),
        CheckConstraint("amount >= 0", name="ck_affiliate_commissions_amount_non_negative"),
        # The maturation sweep's only query.
        Index("ix_affiliate_commissions_status_available", "status", "available_at"),
        Index("ix_affiliate_commissions_partner_created", "partner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_codes.id", ondelete="RESTRICT"), nullable=False
    )
    base_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AffiliatePayout(Base):
    """A partner's withdrawal request.

    Card details are stored because the transfer is made by hand; they are PII
    and must never reach a log line.
    """

    __tablename__ = "affiliate_payouts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'paid')",
            name="ck_affiliate_payouts_status",
        ),
        CheckConstraint("amount > 0", name="ck_affiliate_payouts_amount_positive"),
        Index("ix_affiliate_payouts_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    card_number: Mapped[str] = mapped_column(String(32), nullable=False)
    card_holder: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'requested'")
    )
    admin_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AffiliateSession(Base):
    """A partner's refresh session, mirroring ``auth``'s rotation policy."""

    __tablename__ = "affiliate_sessions"
    __table_args__ = (Index("ix_affiliate_sessions_partner", "partner_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_partners.id", ondelete="CASCADE"), nullable=False
    )
    #: SHA-256 of the refresh token. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = [
    "AffiliateAttribution",
    "AffiliateCode",
    "AffiliateCommission",
    "AffiliatePartner",
    "AffiliatePayout",
    "AffiliateSession",
]
