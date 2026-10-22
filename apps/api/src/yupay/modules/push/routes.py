"""``/push/devices``: the app tells us where to push, and stops it on sign-out."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.auth.deps import current_user
from yupay.modules.push import service
from yupay.modules.push.models import PushDevice
from yupay.modules.users.models import User

router = APIRouter(prefix="/push", tags=["push"])

#: ``ExponentPushToken[…]`` (current) or ``ExpoPushToken[…]`` (older SDKs).
_TOKEN_PATTERN = r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]{10,180}\]$"  # noqa: S105 - a format, not a secret


class RegisterDeviceIn(BaseModel):
    """The app's Expo push token, read on the device after the buyer allowed notifications."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(pattern=_TOKEN_PATTERN, max_length=200)
    platform: Literal["ios", "android"]
    app_version: str | None = Field(default=None, max_length=32)


class DeviceOut(BaseModel):
    """A device as the app sees it. The token is not echoed back."""

    model_config = ConfigDict(frozen=True)

    id: str
    platform: str
    app_version: str | None
    created_at: datetime
    last_seen_at: datetime
    active: bool

    @classmethod
    def of(cls, device: PushDevice) -> DeviceOut:
        """Build from the row."""
        return cls(
            id=device.id,
            platform=device.platform,
            app_version=device.app_version,
            created_at=device.created_at,
            last_seen_at=device.last_seen_at,
            active=device.disabled_at is None,
        )


class DeviceListOut(BaseModel):
    """The account's devices that receive pushes."""

    items: list[DeviceOut]


def _key(raw: str | None) -> str:
    key = normalize_idempotency_key(raw)
    if key is None:
        raise ValidationError(
            f"{IDEMPOTENCY_HEADER} header is required", extra={"header": IDEMPOTENCY_HEADER}
        )
    return key


@router.put(
    "/devices",
    response_model=DeviceOut,
    summary="Register this install's push token for the signed-in account",
)
async def register_device(
    body: RegisterDeviceIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> DeviceOut:
    """Upsert by token: the app calls it at every launch with a session, and after sign-in."""
    key = _key(idempotency_key)
    scope = f"push.device:{user.id}"
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    if cached is not None and cached.body is not None:
        return DeviceOut.model_validate(cached.body)
    device = await service.register_device(
        db,
        user_id=user.id,
        token=body.token,
        platform=body.platform,
        app_version=body.app_version,
    )
    out = DeviceOut.of(device)
    await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("/devices", response_model=DeviceListOut, summary="My devices that receive pushes")
async def list_devices(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> DeviceListOut:
    return DeviceListOut(
        items=[DeviceOut.of(d) for d in await service.active_devices(db, user_id=user.id)]
    )


@router.delete(
    "/devices/{device_id}",
    response_model=DeviceOut,
    summary="Stop pushing to one of my devices (call before signing out)",
)
async def disable_device(
    device_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> DeviceOut:
    key = _key(idempotency_key)
    scope = f"push.device.disable:{user.id}"
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    if cached is not None and cached.body is not None:
        return DeviceOut.model_validate(cached.body)
    device = await service.disable_device(db, user_id=user.id, device_id=device_id)
    out = DeviceOut.of(device)
    await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


__all__ = ["DeviceListOut", "DeviceOut", "RegisterDeviceIn", "router"]
