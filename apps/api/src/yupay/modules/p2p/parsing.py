"""Read a @HUMOcardbot notification into numbers (spec §3).

Pure: no I/O, no clock. A line we do not recognise makes the whole message
``unparsed`` rather than half-read — a guessed amount is worse than none,
because a guessed amount can match a reservation.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

TASHKENT = ZoneInfo("Asia/Tashkent")

_AMOUNT = r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*UZS"
_SIGNED = re.compile(rf"^\s*(➕|➖)\s*{_AMOUNT}\s*$", re.M)
_BALANCE = re.compile(rf"^\s*💰\s*{_AMOUNT}\s*$", re.M)
_SOURCE = re.compile(r"^\s*📍\s*(.+?)\s*$", re.M)
_CARD = re.compile(r"\*(\d{4})\b")
_TIME = re.compile(r"(\d{2}):(\d{2})\s+(\d{2})\.(\d{2})\.(\d{4})")


class ParsedNotification(BaseModel):
    """One notification, read. Every field is ``None`` when ``kind`` is ``unparsed``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["credit", "debit", "unparsed"]
    amount: Decimal | None = None
    source: str | None = None
    card_last4: str | None = None
    bank_time: datetime | None = None
    balance_after: Decimal | None = None


_UNPARSED = ParsedNotification(kind="unparsed")


def _money(raw: str) -> Decimal:
    return Decimal(raw.replace(".", "").replace(",", "."))


def parse_humo(text: str) -> ParsedNotification:
    """Parse one notification.

    Args:
        text: The message text exactly as Telegram delivered it.

    Returns:
        A credit or debit with every field set, or ``unparsed``.
    """
    signed = _SIGNED.search(text or "")
    balance = _BALANCE.search(text or "")
    card = _CARD.search(text or "")
    when = _TIME.search(text or "")
    source = _SOURCE.search(text or "")
    if not (signed and balance and card and when):
        return _UNPARSED
    hh, mm, dd, mo, yyyy = (int(g) for g in when.groups())
    try:
        bank_time = datetime(yyyy, mo, dd, hh, mm, tzinfo=TASHKENT)
    except ValueError:
        return _UNPARSED
    return ParsedNotification(
        kind="credit" if signed.group(1) == "➕" else "debit",
        amount=_money(signed.group(2)),
        source=source.group(1) if source else None,
        card_last4=card.group(1),
        bank_time=bank_time,
        balance_after=_money(balance.group(1)),
    )


__all__ = ["TASHKENT", "ParsedNotification", "parse_humo"]
