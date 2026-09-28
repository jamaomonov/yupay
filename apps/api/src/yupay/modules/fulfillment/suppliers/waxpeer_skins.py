"""Buy a CS2 skin on Waxpeer for the customer's trade link, and follow the trade.

Plan 3a Task 5; the rules are the spike's (spec §8.1):

* ``project_id`` = our idempotency key. A replay looks the purchase up **first**; a buy
  whose response was lost is parked and resolved by lookup, never bought again. After
  :data:`UNCONFIRMED_WINDOW` with nothing found it fails ``UNKNOWN`` for a human.
* The chosen listing gone (or dearer) → up to :data:`MAX_SUBSTITUTES` same-name ``auto``
  listings at no more than the units the customer paid for; none → ``failed``/``RETURNED``.
* Status: 0/1/2 buying · 4 with no ``release_date`` offer sent · 4 **with**
  ``release_date`` accepted (Steam's 7-day protection started) → ``succeeded`` · 5 released
  → ``succeeded`` · 6 → ``failed``/``RETURNED`` (Waxpeer refunds a declined or expired
  offer in full, no penalty).
* Every step is mirrored onto the ``skin_trades`` row the order page reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerError,
    WaxpeerUnavailableError,
)
from yupay.modules.fulfillment.suppliers.waxpeer_trades import (
    WaxpeerBuy,
    WaxpeerBuyRefusedError,
    WaxpeerTrade,
)
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.tradelink import TradeLink, parse_tradelink

log = get_logger("yupay.fulfillment.waxpeer_skins")

SKIN_KIND = "skin"
MAX_SUBSTITUTES = 2
UNCONFIRMED_WINDOW = timedelta(minutes=10)
_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")


class SkinTradeClient(Protocol):
    """What this module needs from Waxpeer (``WaxpeerTradeClient`` satisfies it)."""

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """Trades by our ``project_id``."""
        ...

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        """Buy one listing."""
        ...

    async def search_listings(self, names: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """Live listings by name."""
        ...


def is_skin_task(task: FulfillmentTask) -> bool:
    """A task this module owns (set on the first fulfil)."""
    return (getattr(task, "extra_metadata", None) or {}).get("waxpeer_kind") == SKIN_KIND


def is_skin_line(data: dict[str, Any]) -> bool:
    """An order line priced by ``skins.checkout`` (trade link + listing id)."""
    return bool(data.get("tradelink")) and data.get("listing_id") is not None


def _meta(**extra: Any) -> dict[str, Any]:
    return {"waxpeer_kind": SKIN_KIND, **extra}


def _in_progress(key: str, **extra: Any) -> FulfillResult:
    return FulfillResult(
        outcome="in_progress",
        external_order_id=key,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata=_meta(**extra),
        money_outcome=None,
    )


def _failed(key: str | None, error: str, money: MoneyOutcome | None, **extra: Any) -> FulfillResult:
    return FulfillResult(
        outcome="failed",
        external_order_id=key,
        artifact_kind=None,
        artifact=None,
        error=error,
        extra_metadata=_meta(**extra),
        money_outcome=money,
    )


async def _trade_row(db: AsyncSession, item: OrderItem, key: str) -> SkinTrade:
    row = (
        await db.execute(select(SkinTrade).where(SkinTrade.order_item_id == item.id))
    ).scalar_one_or_none()
    if row is not None:
        return row
    data = item.fulfillment_data or {}
    row = SkinTrade(
        id=new_id(),
        order_item_id=item.id,
        project_id=key,
        listing_id=int(data.get("listing_id") or 0),
        market_hash_name=str(data.get("market_hash_name") or ""),
        phase=str(data.get("phase") or ""),
        paid_units=int(data.get("expected_units") or 0),
    )
    db.add(row)
    await db.flush()
    return row


def mirror(row: SkinTrade, trade: WaxpeerTrade) -> None:
    """Copy one Waxpeer trade report onto our row."""
    row.waxpeer_id = trade.id or row.waxpeer_id
    row.status = trade.status
    row.trade_id = trade.trade_id or row.trade_id
    row.send_until = trade.send_until or row.send_until
    if trade.release_date is not None and row.release_date is None:
        row.accepted_at = now()
    row.release_date = trade.release_date or row.release_date
    row.is_released = trade.is_released
    row.reason = trade.reason or row.reason
    row.penalties = trade.penalties or row.penalties
    if any(v for v in trade.seller.values()):
        row.seller = trade.seller
    row.last_checked_at = now()
    row.updated_at = now()


def _looks_like_low_balance(exc: WaxpeerError) -> bool:
    text = f"{exc} {exc.body}".lower()
    return any(hint in text for hint in _LOW_BALANCE_HINTS)


async def _candidates(
    client: SkinTradeClient, *, name: str, max_units: int, tried: set[int]
) -> list[tuple[int, int]]:
    """Same-name auto listings no dearer than ``max_units``, cheapest first."""
    try:
        found = await client.search_listings([name])
    except (WaxpeerError, WaxpeerUnavailableError):
        return []
    rows = next(iter(found.values()), []) if found else []
    out = [
        (int(r["item_id"]), int(r["price"]))
        for r in rows
        if r.get("auto")
        and int(r.get("price") or 0) <= max_units
        and int(r.get("item_id") or 0) not in tried
    ]
    return sorted(out, key=lambda c: c[1])


async def fulfill_skin(
    client: SkinTradeClient, *, db: AsyncSession, item: OrderItem, idempotency_key: str
) -> FulfillResult:
    """Buy the line's listing (or a same-name one no dearer) for the trade link."""
    key = idempotency_key
    data = item.fulfillment_data or {}
    try:
        link = parse_tradelink(str(data.get("tradelink") or ""))
    except ValidationError as exc:
        raise FulfillerError(
            "skin line has no valid trade link", money_outcome=MoneyOutcome.RETURNED
        ) from exc
    max_units = int(data.get("expected_units") or 0)
    name = str(data.get("name") or data.get("market_hash_name") or "")
    row = await _trade_row(db, item, key)

    try:
        earlier = await client.check_project_ids([key])
    except (WaxpeerError, WaxpeerUnavailableError):
        # Cannot tell whether a crashed attempt bought it: do not risk a second buy.
        return _in_progress(key, buy_unconfirmed_at=now().isoformat())
    if earlier:
        mirror(row, earlier[0])
        await db.flush()
        return _in_progress(key)

    first = (int(data.get("listing_id") or 0), max_units)
    return await _buy(client, db=db, row=row, key=key, link=link, first=first, name=name)


async def _buy(
    client: SkinTradeClient,
    *,
    db: AsyncSession,
    row: SkinTrade,
    key: str,
    link: TradeLink,
    first: tuple[int, int],
    name: str,
) -> FulfillResult:
    """The chosen listing, then up to :data:`MAX_SUBSTITUTES` no dearer than it."""
    max_units = first[1]
    queue: list[tuple[int, int]] = [first]
    tried: set[int] = set()
    while queue and len(tried) <= MAX_SUBSTITUTES:
        listing_id, units = queue.pop(0)
        tried.add(listing_id)
        try:
            bought = await client.buy_one_p2p(
                item_id=listing_id,
                price_units=units,
                partner=link.partner,
                token=link.token,
                project_id=key,
            )
        except WaxpeerBuyRefusedError as exc:
            if _looks_like_low_balance(exc):
                return _failed(None, "supplier_low_balance", None, required_units=max_units)
            log.info("skins.buy.refused", order_item_id=row.order_item_id, listing_id=listing_id)
            if not queue:
                queue = await _candidates(client, name=name, max_units=max_units, tried=tried)
            continue
        except WaxpeerError as exc:
            if _looks_like_low_balance(exc):
                return _failed(None, "supplier_low_balance", None, required_units=max_units)
            return _in_progress(key, buy_unconfirmed_at=now().isoformat())
        except WaxpeerUnavailableError:
            return _in_progress(key, buy_unconfirmed_at=now().isoformat())
        row.listing_id = listing_id
        row.waxpeer_id = bought.id
        row.bought_units = bought.price_units or units
        row.status = 0
        row.updated_at = now()
        await db.flush()
        return _in_progress(key)

    return _failed(key, "sold_out", MoneyOutcome.RETURNED)


def _status(outcome: str, **kw: Any) -> FulfillStatus:
    return FulfillStatus(
        outcome=outcome,  # type: ignore[arg-type] # one of the three literals below
        artifact_kind=kw.get("artifact_kind"),
        artifact=kw.get("artifact"),
        error=kw.get("error"),
        money_outcome=kw.get("money_outcome"),
        extra_metadata=_meta(),
    )


def _unconfirmed_expired(task: FulfillmentTask) -> bool:
    raw = (task.extra_metadata or {}).get("buy_unconfirmed_at")
    if not raw:
        return False
    try:
        since = datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return now() - since > UNCONFIRMED_WINDOW


async def skin_status(
    client: SkinTradeClient, *, db: AsyncSession, task: FulfillmentTask
) -> FulfillStatus:
    """One look at the trade: mirror it, and map it to the task's outcome."""
    row = (
        await db.execute(select(SkinTrade).where(SkinTrade.order_item_id == task.order_item_id))
    ).scalar_one_or_none()
    key = task.external_order_id or (row.project_id if row else "")
    trades = await client.check_project_ids([key]) if key else []
    if not trades:
        if _unconfirmed_expired(task):
            return _status("failed", error="buy_unconfirmed", money_outcome=MoneyOutcome.UNKNOWN)
        return _status("in_progress")
    trade = trades[0]
    if row is not None:
        row.task_id = task.id
        mirror(row, trade)
        await db.flush()
    if trade.status == 5 or (trade.status == 4 and trade.release_date is not None):
        return _status(
            "succeeded",
            artifact_kind="topup_receipt",
            artifact={
                "kind": "skin",
                "name": row.market_hash_name if row else None,
                "trade_id": trade.trade_id,
                "release_date": trade.release_date.isoformat() if trade.release_date else None,
            },
        )
    if trade.status == 6:
        return _status("failed", error="not_accepted", money_outcome=MoneyOutcome.RETURNED)
    return _status("in_progress")


__all__ = [
    "MAX_SUBSTITUTES",
    "SKIN_KIND",
    "SkinTradeClient",
    "fulfill_skin",
    "is_skin_line",
    "is_skin_task",
    "mirror",
    "skin_status",
]
