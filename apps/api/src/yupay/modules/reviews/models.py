"""SQLAlchemy models for brand reviews, abuse reports, and denormalized rating stats."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base

REVIEW_STATUSES = ("published", "hidden", "removed")


class Review(Base):
    """A single brand review anchored to a delivered order (proof of purchase)."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    guest_email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'published'")
    )
    locale: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'ru'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        CheckConstraint(
            "(user_id IS NULL) <> (guest_email IS NULL)", name="ck_reviews_user_xor_guest"
        ),
        UniqueConstraint("order_id", "brand_id", name="uq_reviews_order_brand"),
        Index("ix_reviews_brand_status_created", "brand_id", "status", "created_at"),
        Index("ix_reviews_user", "user_id"),
    )


class ReviewReport(Base):
    """An abuse report against a review. A threshold of distinct reports auto-hides it."""

    __tablename__ = "review_reports"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    reporter_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("review_id", "reporter_user_id", name="uq_review_reports_review_reporter"),
        Index("ix_review_reports_review", "review_id"),
    )


class BrandRatingStats(Base):
    """Denormalized per-brand aggregate over ``published`` reviews only."""

    __tablename__ = "brand_rating_stats"

    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sum_rating: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    avg: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default=text("0"))
    count_1: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_2: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_3: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_4: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    count_5: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = ["REVIEW_STATUSES", "BrandRatingStats", "Review", "ReviewReport"]
