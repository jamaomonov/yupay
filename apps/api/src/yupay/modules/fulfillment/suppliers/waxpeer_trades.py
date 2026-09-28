"""Waxpeer's skin purchase side: buy one listing, read trades back by ``project_id``.

Shapes recorded from real purchases on 2026-09-28 (spec §8.1): ``buy-one-p2p`` answers at
once with Waxpeer's trade id; ``check-many-project-id`` reports ``status`` 0 → 2 → 4, with
``release_date`` appearing at 4 only once the buyer accepts, and 6 + ``reason`` when the
offer fails. ``send_until`` is an epoch string, ``release_date`` ISO 8601.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerClient, WaxpeerError


class WaxpeerBuyRefusedError(WaxpeerError):
    """``buy-one-p2p`` said no (sold, price moved, balance…); ``new_price`` when it moved."""

    def __init__(self, message: str, *, new_price: int | None, body: str = "") -> None:
        """Keep Waxpeer's message and the price it would now accept."""
        super().__init__(message, status=200, body=body)
        self.new_price = new_price


@dataclass(frozen=True)
class WaxpeerBuy:
    """A purchase Waxpeer accepted."""

    id: int
    price_units: int


@dataclass(frozen=True)
class WaxpeerTrade:
    """One trade as ``check-many-project-id`` reports it."""

    id: int
    project_id: str
    status: int
    trade_id: str | None
    done: bool
    reason: str | None
    release_date: datetime | None
    is_released: bool
    send_until: datetime | None
    price_units: int
    penalties: dict[str, Any] | None
    seller: dict[str, Any] = field(default_factory=dict)


def _epoch(raw: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _seller(t: dict[str, Any]) -> dict[str, Any]:
    joined = _epoch(t.get("seller_steam_joined"))
    name = str(t.get("seller_name") or "").strip()
    return {
        "name": name or None,
        "avatar_url": t.get("seller_avatar") or None,
        "level": t.get("seller_steam_level"),
        "joined_at": joined.isoformat() if joined else None,
    }


def parse_trade(t: dict[str, Any]) -> WaxpeerTrade:
    """One ``trades[]`` entry → :class:`WaxpeerTrade`."""
    penalties = t.get("penalties")
    return WaxpeerTrade(
        id=_int(t.get("id")),
        project_id=str(t.get("project_id") or ""),
        status=_int(t.get("status"), -1),
        trade_id=str(t["trade_id"]) if t.get("trade_id") else None,
        done=bool(t.get("done")),
        reason=str(t["reason"]) if t.get("reason") else None,
        release_date=_iso(t.get("release_date")),
        is_released=bool(t.get("is_released")),
        send_until=_epoch(t.get("send_until")),
        price_units=_int(t.get("price")),
        penalties=penalties if isinstance(penalties, dict) and penalties else None,
        seller=_seller(t),
    )


class WaxpeerTradeClient(WaxpeerClient):
    """The purchase endpoints on top of :class:`WaxpeerClient`'s transport."""

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        """``GET /v1/buy-one-p2p`` — refused (never over ``price_units``) raises.

        Raises:
            WaxpeerBuyRefusedError: Waxpeer said no; ``new_price`` if the price moved.
            WaxpeerUnavailableError: transport failure — the buy may have happened;
                resolve by :meth:`check_project_ids`, never by buying again.
        """
        try:
            body, _ = await self._request(
                "GET",
                "/buy-one-p2p",
                params={
                    "item_id": item_id,
                    "price": price_units,
                    "partner": partner,
                    "token": token,
                    "project_id": project_id,
                },
            )
        except WaxpeerError as exc:
            if exc.status != 200:
                raise
            try:
                parsed = json.loads(exc.body) if exc.body else {}
                raw = parsed.get("new_price") if isinstance(parsed, dict) else None
                new_price = int(raw) if raw is not None else None
            except (ValueError, TypeError):
                new_price = None
            raise WaxpeerBuyRefusedError(str(exc), new_price=new_price, body=exc.body) from exc
        return WaxpeerBuy(id=_int(body.get("id")), price_units=_int(body.get("price")))

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """``GET /v1/check-many-project-id`` for up to 100 of our ``project_id`` values."""
        if not project_ids:
            return []
        body, _ = await self._request(
            "GET", "/check-many-project-id", params={"id": list(project_ids[:100])}
        )
        trades = body.get("trades")
        return (
            [parse_trade(t) for t in trades if isinstance(t, dict)]
            if isinstance(trades, list)
            else []
        )


__all__ = [
    "WaxpeerBuy",
    "WaxpeerBuyRefusedError",
    "WaxpeerTrade",
    "WaxpeerTradeClient",
    "parse_trade",
]
