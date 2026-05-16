"""SQLAlchemy ORM models for the ``auth`` module.

The ORM ``User`` and ``TelegramLink`` live in :mod:`yupay.modules.users.models` — this
module owns only the session record.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class AuthSession(Base):
    """One row per issued refresh token (kind='user') or per guest checkout
    (kind='guest').

    Stateless access tokens (JWTs) are not tracked here — only their refresh counterparts
    and audit metadata. See :doc:`/docs/decisions/0007-jwt-format-and-rotation` for the
    full token lifecycle.
    """

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    refresh_token_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    guest_email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    ip_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    ua_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('user', 'guest')", name="ck_auth_sessions_kind"),
        CheckConstraint(
            "(kind = 'user' AND user_id IS NOT NULL AND refresh_token_hash IS NOT NULL) "
            "OR (kind = 'guest' AND user_id IS NULL AND guest_email IS NOT NULL)",
            name="ck_auth_sessions_shape",
        ),
    )


__all__ = ["AuthSession"]
