"""Idempotency-replay helpers shared by the merchant admin routers.

``admin_routes`` and ``catalog_b2b_routes`` are two routers over the same
generic ``(scope, key)`` replay store (:mod:`yupay.core.idempotency`). They
were one file until the file passed AGENTS.md §6's split-before-500 line; the
helpers live here rather than in either router so neither has to import the
other's privates.

Nothing here is merchant-specific — it is the thin ``load_replay`` /
``save_replay`` pairing the other admin write endpoints already use, kept in
one place so the two routers cannot drift on what a replay means.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.idempotency import IDEMPOTENCY_HEADER, load_replay, save_replay

IdempotencyKeyHeader = Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)]


async def replayed[ModelT: BaseModel](
    db: AsyncSession, *, scope: str, key: str | None, model: type[ModelT]
) -> ModelT | None:
    """Return the stored response for ``(scope, key)``, or ``None`` to proceed.

    Args:
        db: Session the replay row is read in.
        scope: Per-resource replay namespace, so one key cannot replay a
            different merchant's (or SKU's) write.
        key: The normalised ``Idempotency-Key``; ``None`` means the caller
            supplied none, which is never a replay.
        model: Response model the stored body is validated back into.

    Returns:
        The original response, or ``None`` when this is a first call.
    """
    if key is None:
        return None
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    if cached is None:
        return None
    return model.model_validate(cached.body)


async def remember(
    db: AsyncSession, *, scope: str, key: str | None, body: dict[str, Any], status_code: int = 200
) -> None:
    """Store a response for replay when a key was supplied.

    Args:
        db: Session the replay row is written in — the caller's transaction,
            so a rollback drops the snapshot with the write it describes.
        scope: Per-resource replay namespace.
        key: The normalised ``Idempotency-Key``; ``None`` stores nothing.
        body: JSON-mode dump of the response to replay.
        status_code: Status the original call answered with.
    """
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=body, status_code=status_code)


__all__ = ["IdempotencyKeyHeader", "remember", "replayed"]
