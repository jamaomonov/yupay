"""A customer's Steam trade link: parse it, and check it before they pay.

The link is where Waxpeer sends the offer, so a broken one is a refund waiting to
happen. The check is advisory (AGENTS.md §10 carve-out): it asks Waxpeer whether the
link works (private inventory, trade ban) and Steam whether a trade to it would be
held (no mobile authenticator for 7 days — the offer would sit in escrow where either
side can cancel). An outage answers ``unavailable`` and never blocks checkout.

The ``token`` in a trade link lets anyone send that account offers; it is treated as a
credential: never logged, never part of a Redis key (the cache key is a hash).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.core.logging import get_logger
from yupay.modules.skins.models import SkinTradeLink

log = get_logger("yupay.skins.tradelink")

#: steamid64 = steamid32 ("partner") + this.
STEAM64_BASE = 76561197960265728
_LINK = re.compile(
    r"^https://steamcommunity\.com/tradeoffer/new/\?partner=(\d{1,12})&token=([\w-]{6,16})$"
)
_CACHE_TTL = 600
_CACHE_PREFIX = "skins:tradelink:"
#: Opened by an upstream failure; while set, the check answers "unavailable" at once.
_BREAKER_KEY = "skins:tradelink:breaker"
_BREAKER_TTL = 60

TradeLinkReason = Literal["invalid", "private", "trade_ban", "hold", "unavailable"]


class TradeLink(BaseModel):
    """A parsed trade link."""

    model_config = ConfigDict(frozen=True)

    url: str
    partner: int
    token: str

    @property
    def steam_id(self) -> int:
        """The account's steamid64."""
        return self.partner + STEAM64_BASE


class TradeLinkVerdict(BaseModel):
    """``ok`` false blocks checkout; ``unavailable`` is ok with a reason."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    reason: TradeLinkReason | None = None


def parse_tradelink(raw: str) -> TradeLink:
    """Parse Steam's «Trade URL» (Inventory → Trade offers → Who can send me offers).

    Raises:
        ValidationError: anything that is not exactly that link.
    """
    url = raw.strip()
    match = _LINK.match(url)
    if match is None:
        raise ValidationError("not a Steam trade link", extra={"reason": "invalid"})
    return TradeLink(url=url, partner=int(match.group(1)), token=match.group(2))


class TradelinkChecker(Protocol):
    """Waxpeer's ``check-tradelink``: ``None`` when fine, else Steam's reason text."""

    async def check_tradelink(self, url: str) -> str | None:
        """Return Waxpeer's ``info`` for ``url``."""
        ...


class HoldChecker(Protocol):
    """Steam's ``GetTradeHoldDurations``: days a trade to this account would be held."""

    async def trade_hold_days(self, steam_id: int, token: str) -> int | None:
        """Return the hold in days, ``None`` if Steam gave no number."""
        ...


def _reason_for(info: str) -> TradeLinkReason:
    text = info.lower()
    if "private" in text:
        return "private"
    if "ban" in text:
        return "trade_ban"
    return "invalid"


async def _verdict(
    link: TradeLink, *, waxpeer: TradelinkChecker, steam: HoldChecker
) -> TradeLinkVerdict:
    info = await waxpeer.check_tradelink(link.url)
    if info:
        return TradeLinkVerdict(ok=False, reason=_reason_for(info))
    days = await steam.trade_hold_days(link.steam_id, link.token)
    if days:
        return TradeLinkVerdict(ok=False, reason="hold")
    return TradeLinkVerdict(ok=True)


async def check_tradelink(
    url: str, *, waxpeer: TradelinkChecker, steam: HoldChecker, redis: Redis
) -> TradeLinkVerdict:
    """The advisory pre-purchase check, cached for 10 minutes per link.

    An upstream failure opens a 60-second breaker: until it closes every check answers
    ``unavailable`` without calling Waxpeer or Steam (ADR-0031's conditions).

    Raises:
        ValidationError: ``url`` is not a trade link.
    """
    link = parse_tradelink(url)
    key = _CACHE_PREFIX + hashlib.sha1(link.url.encode()).hexdigest()  # noqa: S324 - a cache key
    with contextlib.suppress(RedisError, ValueError):
        cached = await redis.get(key)
        if cached is not None:
            return TradeLinkVerdict.model_validate(json.loads(cached))
    unavailable = TradeLinkVerdict(ok=True, reason="unavailable")
    with contextlib.suppress(RedisError):
        if await redis.exists(_BREAKER_KEY):
            return unavailable
    try:
        verdict = await _verdict(link, waxpeer=waxpeer, steam=steam)
    except Exception as exc:  # noqa: BLE001 - advisory: any upstream failure is "unavailable"
        log.warning("skins.tradelink.unavailable", error=type(exc).__name__)
        with contextlib.suppress(RedisError):
            await redis.set(_BREAKER_KEY, "1", ex=_BREAKER_TTL)
        return unavailable
    with contextlib.suppress(RedisError):
        await redis.set(key, verdict.model_dump_json(), ex=_CACHE_TTL)
    return verdict


async def save_trade_link(db: AsyncSession, *, user_id: str, url: str, steam_id: int) -> None:
    """Upsert the user's saved link (checkout reuses this). Flushes, never commits."""
    row = await db.get(SkinTradeLink, user_id)
    if row is None:
        db.add(SkinTradeLink(user_id=user_id, url=url, steam_id=steam_id))
    else:
        row.url, row.steam_id, row.updated_at = url, steam_id, now()
    await db.flush()


__all__ = [
    "STEAM64_BASE",
    "HoldChecker",
    "TradeLink",
    "TradeLinkReason",
    "TradeLinkVerdict",
    "TradelinkChecker",
    "check_tradelink",
    "parse_tradelink",
    "save_trade_link",
]
