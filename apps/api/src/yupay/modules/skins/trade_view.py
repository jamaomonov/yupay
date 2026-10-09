"""The buyer's view of a CS2 skin trade, for the order page (plan 3a, Task 8).

Waxpeer's numbers become five states a customer understands:

* ``buying`` — Waxpeer is creating the offer (status 0–2, or not bought yet);
* ``offer_sent`` — the offer is in Steam, accept it before ``send_until`` (4, no
  ``release_date``);
* ``accepted`` — received; Steam's trade protection runs to ``release_date`` (4 with it);
* ``released`` — protection over (5);
* ``failed`` — ``not_accepted`` (declined or expired), ``sold_out`` (nothing left to buy),
  ``try_later`` (Waxpeer was short of our money — a retry in a few minutes may work);
  ``support``: a purchase we could not confirm, settled by a human; ``other``.

Whether the money came back is not read off the reason: ``refunded_to`` says where a refund
actually went (``wallet`` / ``card``), from the order's payment, so the page never promises a
refund that failed or has not happened.

The seller is shown on purpose (spec §2.3): the customer should recognise the offer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from yupay.modules.skins.models import SkinTrade

SkinTradeState = Literal["buying", "offer_sent", "accepted", "released", "failed"]
SkinTradeReason = Literal["not_accepted", "sold_out", "try_later", "tradelink", "support", "other"]
SkinRefundedTo = Literal["wallet", "card"]


class SkinSellerOut(BaseModel):
    """Who the offer comes from."""

    name: str | None = None
    avatar_url: str | None = None
    level: int | None = None
    joined_at: datetime | None = None


class SkinTradeOut(BaseModel):
    """One order line's trade, as the buyer sees it."""

    state: SkinTradeState
    offer_url: str | None = None
    send_until: datetime | None = None
    release_date: datetime | None = None
    seller: SkinSellerOut | None = None
    reason_code: SkinTradeReason | None = None
    refunded_to: SkinRefundedTo | None = None


def _state(row: SkinTrade, fulfillment_state: str) -> SkinTradeState:
    if row.status == 6 or fulfillment_state == "failed":
        return "failed"
    if row.status == 5 or row.is_released:
        return "released"
    if row.status == 4:
        return "accepted" if row.release_date is not None else "offer_sent"
    return "buying"


_TRADELINK_REASONS = frozenset({"invalid_trade_link", "invalid_tradelink", "trade_hold"})


def _reason(row: SkinTrade) -> SkinTradeReason:
    # ``support`` is a purchase we could not confirm — a human settles it.
    if row.reason in ("buy_unconfirmed", "ambiguous_trade"):
        return "support"
    if row.reason == "supplier_low_balance":
        return "try_later"
    # The market refused the buyer's trade link (LIS-SKINS ``invalid_trade_url``, a trade
    # hold): every retry with the same link fails the same way, so the page says so.
    if row.reason in _TRADELINK_REASONS:
        return "tradelink"
    if row.status is None:
        return "sold_out"
    if row.reason and "accept" in row.reason.lower():
        return "not_accepted"
    return "other"


def _seller(raw: dict[str, Any]) -> SkinSellerOut | None:
    if not raw or not any(raw.values()):
        return None
    return SkinSellerOut.model_validate(raw)


def skin_trade_out(
    row: SkinTrade, *, fulfillment_state: str, refunded_to: SkinRefundedTo | None = None
) -> SkinTradeOut:
    """Map our mirror of a Waxpeer trade to the buyer's view.

    Args:
        row: The trade mirror.
        fulfillment_state: The order line's state.
        refunded_to: Where the order's refund went, if one was made.
    """
    state = _state(row, fulfillment_state)
    return SkinTradeOut(
        state=state,
        offer_url=(
            f"https://steamcommunity.com/tradeoffer/{row.trade_id}/" if row.trade_id else None
        ),
        send_until=row.send_until,
        release_date=row.release_date,
        seller=_seller(row.seller or {}),
        reason_code=_reason(row) if state == "failed" else None,
        refunded_to=refunded_to if state == "failed" else None,
    )


__all__ = [
    "SkinRefundedTo",
    "SkinSellerOut",
    "SkinTradeOut",
    "SkinTradeReason",
    "SkinTradeState",
    "skin_trade_out",
]
