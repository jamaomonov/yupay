"""Shared FastAPI dependencies used by ``/api/v1`` routes.

Concrete deps (current_user, idempotency_key, etc.) land here as the corresponding modules
are implemented.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.db import get_session


async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a transactional async session per request."""
    async for session in get_session():
        yield session


SessionDep = Depends(db_session)
