"""Shared dependencies of the P2P admin routers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.deps import require_admin
from yupay.modules.users.models import User

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def parse_uuid(value: str) -> str | None:
    """Canonical uuid text, or ``None`` so a malformed id is a 404/422 and not a DB error."""
    try:
        return str(UUID(value))
    except ValueError:
        return None


__all__ = ["Admin", "Db", "PageLimit", "parse_uuid"]
