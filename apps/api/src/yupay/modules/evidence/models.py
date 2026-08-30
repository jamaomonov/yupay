"""SQLAlchemy ORM for the ``evidence`` module. See ADR-0044."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from yupay.core.db import Base


class InetAsText(TypeDecorator[str]):
    """``INET`` in Postgres, plain ``str`` in Python.

    asyncpg hands back ``ipaddress`` objects for INET columns while psycopg
    returns text. Pinning the Python side to ``str`` keeps the schema, the
    evidence pack and every consumer from having to know which driver is
    underneath — without it a Pydantic ``str`` field on the admin route fails
    validation at runtime while type-checking clean.
    """

    impl = INET
    cache_ok = True

    def process_result_value(self, value: object, dialect: Dialect) -> str | None:  # noqa: ARG002
        return None if value is None else str(value)


class OrderEvidence(Base):
    """Request context captured when an order was placed, kept to answer a
    chargeback.

    One row per order, written once and never updated: an evidence record that
    can be edited after the fact is not evidence. The order's own timeline lives
    in ``order_events`` — this table holds only what that timeline cannot carry,
    namely who the request came from.

    This is the single place in the schema that stores an unhashed IP address,
    against the blanket "never store PII" rule in AGENTS.md §9. The exception is
    deliberate and narrow; ADR-0044 records why, and ``purge_after`` is what
    keeps it narrow.
    """

    __tablename__ = "order_evidence"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # INET rather than TEXT: Postgres validates the value on write, so a
    # malformed header can never masquerade as an address in a dispute pack.
    ip: Mapped[str | None] = mapped_column(InetAsText, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    accept_language: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Passive browser hints, verbatim as reported by the client. Untrusted by
    # construction — their worth is corroboration (a Tashkent IP alongside an
    # Asia/Tashkent clock reads differently than one alongside a mismatch), so
    # they are stored as sent rather than normalised into a false certainty.
    client_hints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    #: sha256 of ``user_agent | timezone | locale | screen`` — the device as a
    #: pseudonym, for the risk gate's shared-identity rule. Derived, so it
    #: lives and dies with this row's ``purge_after``.
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    #: Stamped per row at capture time, not derived from config at purge time.
    #: Shortening the retention policy later must not silently extend the life
    #: of data already collected under the promise made in the privacy notice.
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["OrderEvidence"]
