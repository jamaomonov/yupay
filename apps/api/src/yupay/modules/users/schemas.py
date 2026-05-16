"""Pydantic DTOs for the ``users`` module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    """User profile returned to authenticated clients."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    locale: str
    display_name: str | None
    photo_url: str | None
    roles: list[str] = []
    created_at: datetime
