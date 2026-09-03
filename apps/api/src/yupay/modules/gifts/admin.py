"""Admin HTTP routes for the ``gifts`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.deps import require_admin
from yupay.modules.gifts.schemas import GiftsAdminSettingsOut, GiftsSettingsIn
from yupay.modules.gifts.settings import (
    default_zone,
    load_margin_percent,
    offered_zones,
    publish_margin,
    save_margin_percent,
)
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/gifts",
    tags=["admin:gifts"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get(
    "/settings",
    response_model=GiftsAdminSettingsOut,
    summary="Current Steam Gifts margin and region configuration",
)
async def admin_get_settings(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> GiftsAdminSettingsOut:
    settings = get_settings()
    margin = await load_margin_percent(db)
    return GiftsAdminSettingsOut(
        margin_percent=margin,
        enabled=settings.steam_gifts_enabled,
        region_default=default_zone(settings),
        regions=offered_zones(settings),
    )


@admin_router.patch(
    "/settings",
    response_model=GiftsAdminSettingsOut,
    summary="Set the Steam Gifts margin percent",
)
async def admin_set_settings(
    body: GiftsSettingsIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> GiftsAdminSettingsOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "gifts.set_margin_percent"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None and cached.body is not None:
            return GiftsAdminSettingsOut.model_validate(cached.body)

    await save_margin_percent(db, value=body.margin_percent, admin_id=admin.id)
    # Everything that can still refuse the request happens before the commit,
    # and the margin reaches Redis only after it — same ordering as
    # ``fx.routes.admin_set_rate``. Publishing first would have left Redis
    # serving a margin Postgres could still roll back.
    await db.commit()
    await publish_margin(body.margin_percent)

    settings = get_settings()
    out = GiftsAdminSettingsOut(
        margin_percent=body.margin_percent,
        enabled=settings.steam_gifts_enabled,
        region_default=default_zone(settings),
        regions=offered_zones(settings),
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["admin_router"]
