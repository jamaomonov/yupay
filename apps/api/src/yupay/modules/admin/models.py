"""SQLAlchemy models owned by the ``admin`` module.

Currently only the operator's saved-segments table — bookmark-like rows so an
admin can store a working filter (e.g. "stuck Click payments older than 1 h")
and recall it from the sidebar instead of rebuilding it each shift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class AdminSavedSegment(Base):
    """A per-admin saved filter view.

    ``path`` carries the admin-SPA path (e.g. ``/payments/triage``) and
    ``params`` carries the query-string params verbatim so the client can
    reconstruct the URL without having to know which page owns which keys.
    """

    __tablename__ = "admin_saved_segments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_admin_saved_segments_owner_name"),
    )


__all__ = ["AdminSavedSegment"]
