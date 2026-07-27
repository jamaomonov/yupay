"""Idempotency-key middleware contract.

Every mutating endpoint accepts an ``Idempotency-Key`` header. Endpoints whose domain
row has a natural place to record the key persist it directly on their own table and
replay from there — see ``Payment.idempotency_key``, ``Order.idempotency_key``,
``WalletTransaction.idempotency_key``, ``PromoRedemption.idempotency_key``.

Admin write endpoints that *mutate* an existing row rather than create one (retry /
cancel / complete a fulfillment task, upsert or delete a sourcing rule or supplier
mapping, ...) have no such column to piggy-back on. Those use the small generic store
below: ``(scope, idempotency_key)`` -> a snapshot of the response first returned for
that pair. A repeat request with the same key replays the stored snapshot instead of
re-running the handler. See :func:`load_replay` / :func:`save_replay`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id

IDEMPOTENCY_HEADER = "Idempotency-Key"
"""Canonical header name."""

MIN_IDEMPOTENCY_KEY_LENGTH = 16
"""Keys shorter than this are rejected — they're too likely to collide."""

IDEMPOTENCY_KEY_TTL_SECONDS = 24 * 60 * 60
"""How long we remember a response for replay (24 h). Not yet enforced by a reaper —
admin write volume is low and rows are tiny; add a cleanup job if that changes."""


def normalize_idempotency_key(idempotency_key: str | None) -> str | None:
    """Validate an *optional* ``Idempotency-Key`` header value.

    Returns ``None`` when the header is absent so the caller executes the handler
    normally with no replay bookkeeping — the admin write endpoints in scope here
    accept the header (satisfying AGENTS.md §9) but don't require it, mirroring
    ``integrations.routes.import_g2b_game`` where the key is accepted for client
    convenience rather than mandated. A key that *is* present but shorter than
    :data:`MIN_IDEMPOTENCY_KEY_LENGTH` is rejected outright rather than silently
    treated as a valid replay token.
    """
    if idempotency_key is None:
        return None
    if len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header, if present, must be >={MIN_IDEMPOTENCY_KEY_LENGTH} chars",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


class IdempotentResponse(Base):
    """One stored replay: the first response returned for ``(scope, idempotency_key)``.

    ``scope`` namespaces the key per action (e.g. ``"fulfillment.retry_task"``) so the
    same client-generated key can't accidentally replay across unrelated endpoints.
    """

    __tablename__ = "idempotent_responses"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotent_responses_scope_key"),
    )


@dataclass(frozen=True)
class CachedResponse:
    """A previously stored response for a given ``(scope, idempotency_key)``."""

    status_code: int
    body: dict[str, Any] | None


async def load_replay(
    db: AsyncSession, *, scope: str, idempotency_key: str
) -> CachedResponse | None:
    """Return the stored response for ``(scope, idempotency_key)``, or ``None`` on a miss."""
    row = (
        await db.execute(
            select(IdempotentResponse).where(
                IdempotentResponse.scope == scope,
                IdempotentResponse.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return CachedResponse(status_code=row.status_code, body=row.response_body)


async def save_replay(
    db: AsyncSession,
    *,
    scope: str,
    idempotency_key: str,
    body: dict[str, Any] | None,
    status_code: int = 200,
) -> None:
    """Persist the response for ``(scope, idempotency_key)`` so a retry replays it.

    A concurrent request racing for the same key loses the unique constraint and is
    swallowed — the other request's row already holds the canonical response, and the
    caller's own response (computed from the same successful mutation) is equivalent.
    """
    row = IdempotentResponse(
        id=new_id(),
        scope=scope,
        idempotency_key=idempotency_key,
        status_code=status_code,
        response_body=body,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        pass


__all__ = [
    "IDEMPOTENCY_HEADER",
    "IDEMPOTENCY_KEY_TTL_SECONDS",
    "MIN_IDEMPOTENCY_KEY_LENGTH",
    "CachedResponse",
    "IdempotentResponse",
    "load_replay",
    "normalize_idempotency_key",
    "save_replay",
]
