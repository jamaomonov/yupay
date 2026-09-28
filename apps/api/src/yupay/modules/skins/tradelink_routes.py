"""``/skins/tradelink`` — the advisory trade-link check and the customer's saved link.

Mounted **before** the catalogue router: ``GET /skins/{slug}`` would otherwise swallow
``GET /skins/tradelink``. Both 404 while ``cs2_skins_enabled`` is off.

``POST /check`` is the one advisory external call here (AGENTS.md §10, ADR-0093):
Waxpeer ``check-tradelink`` + Steam ``GetTradeHoldDurations``, 4 s timeouts, a 10-minute
Redis cache, its own ``guard_ip`` bucket, off the order path. ``POST`` for a read keeps
the link — whose token is a credential — out of the edge access log; it writes nothing,
so it takes no ``Idempotency-Key`` (AGENTS.md §9).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.core.redis import get_redis
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.auth.steam import trade_hold_days
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerClient
from yupay.modules.skins.models import SkinTradeLink
from yupay.modules.skins.tradelink import (
    HoldChecker,
    TradelinkChecker,
    TradeLinkReason,
    check_tradelink,
    parse_tradelink,
)
from yupay.modules.users.models import User

_TIMEOUT = 4.0


def _ensure_enabled() -> None:
    if not get_settings().cs2_skins_enabled:
        raise NotFoundError("cs2 skins catalog is not enabled")


router = APIRouter(
    prefix="/skins/tradelink", tags=["skins"], dependencies=[Depends(_ensure_enabled)]
)


class TradeLinkIn(BaseModel):
    """A pasted trade link."""

    url: str = Field(max_length=300)


class TradeLinkCheckOut(BaseModel):
    """``ok`` false blocks checkout; ``reason`` names what to fix."""

    ok: bool
    reason: TradeLinkReason | None


class SavedTradeLinkOut(BaseModel):
    """The customer's saved link, or ``null``."""

    url: str | None


class _SteamHold:
    """Steam's hold check bound to our key; no key means "no number"."""

    async def trade_hold_days(self, steam_id: int, token: str) -> int | None:
        key = get_settings().steam_api_key
        if not key:
            return None
        return await trade_hold_days(steam_id, token, api_key=key)


def _checkers() -> tuple[TradelinkChecker, HoldChecker]:
    settings = get_settings()
    waxpeer = WaxpeerClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=_TIMEOUT,
    )
    return waxpeer, _SteamHold()


@router.post("/check", response_model=TradeLinkCheckOut, summary="Check a trade link")
async def check_link(request: Request, body: TradeLinkIn) -> TradeLinkCheckOut:
    """Advisory: will an offer to this link arrive? Never blocks on an outage."""
    await guard_ip(request, bucket="skins-tradelink")
    try:
        parse_tradelink(body.url)
    except ValidationError:
        return TradeLinkCheckOut(ok=False, reason="invalid")
    waxpeer, steam = _checkers()
    verdict = await check_tradelink(body.url, waxpeer=waxpeer, steam=steam, redis=get_redis())
    return TradeLinkCheckOut(ok=verdict.ok, reason=verdict.reason)


@router.get("", response_model=SavedTradeLinkOut, summary="My saved trade link")
async def get_saved(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> SavedTradeLinkOut:
    row = await db.get(SkinTradeLink, user.id)
    return SavedTradeLinkOut(url=row.url if row else None)


@router.put("", response_model=SavedTradeLinkOut, summary="Save my trade link")
async def put_saved(
    body: TradeLinkIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SavedTradeLinkOut:
    key = normalize_idempotency_key(idempotency_key)
    if key is None:
        raise ValidationError(
            f"{IDEMPOTENCY_HEADER} header is required", extra={"header": IDEMPOTENCY_HEADER}
        )
    scope = f"skins.tradelink:{user.id}"
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    if cached is not None and cached.body is not None:
        return SavedTradeLinkOut.model_validate(cached.body)
    link = parse_tradelink(body.url)
    await save_trade_link(db, user_id=user.id, url=link.url, steam_id=link.steam_id)
    out = SavedTradeLinkOut(url=link.url)
    await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump())
    await db.commit()
    return out


async def save_trade_link(db: AsyncSession, *, user_id: str, url: str, steam_id: int) -> None:
    """Upsert the user's saved link (checkout reuses this). Flushes, never commits."""
    row = await db.get(SkinTradeLink, user_id)
    if row is None:
        db.add(SkinTradeLink(user_id=user_id, url=url, steam_id=steam_id))
    else:
        row.url, row.steam_id, row.updated_at = url, steam_id, now()
    await db.flush()


__all__ = ["router", "save_trade_link"]
