"""Buy a CS2 skin on Waxpeer for the customer's trade link, and follow the trade.

Plan 3a Task 5, hardened by the final review; the rules are the spike's (spec §8.1):

* ``project_id`` = our idempotency key. Every buy is preceded by a lookup — Waxpeer
  answers ``trades: []`` for a key it has never seen (probed on prod 2026-09-28). A lookup
  that fails parks the task **buy_pending**: nothing was sent, and the next status check
  (the 5 s sweep) retries the lookup and then buys. Only a buy request whose answer was
  lost (transport error, 5xx) parks it **buy_unconfirmed**; that is resolved by lookup,
  never by buying again, and fails ``UNKNOWN`` after :data:`UNCONFIRMED_WINDOW`.
* The chosen listing refused (sold, price up, a 4xx) → up to :data:`MAX_SUBSTITUTES`
  same-name ``auto`` listings no dearer than the units paid, found through the item page's
  own cached, budgeted read under Waxpeer's spelling of the name; none → ``RETURNED``.
* A lookup can return more than one trade for our key (refused attempts); the one that is
  ours is the one whose ``id`` Waxpeer gave us on the buy. Several live ones and no id
  → ``UNKNOWN`` for a human.
* Status: 0/1/2 buying · 4 without ``release_date`` offer sent · 4 **with** it accepted →
  ``succeeded`` · 5 released → ``succeeded`` · 6 before acceptance → ``RETURNED`` (Waxpeer
  refunds a declined or expired offer in full) · 6 after acceptance or with penalties →
  ``SPENT`` (a rollback, not a refund).
* Every step is mirrored onto ``skin_trades``; ``reason`` carries ``sold_out`` /
  ``buy_unconfirmed`` so the order page can tell the customer the truth.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import FulfillResult, FulfillStatus, MoneyOutcome
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
from yupay.modules.skins.models import SkinItem, SkinTrade
from yupay.modules.skins.tradelink import TradeLink, parse_tradelink

log = get_logger("yupay.fulfillment.waxpeer_skins")

SKIN_KIND = "skin"
MAX_SUBSTITUTES = 2
UNCONFIRMED_WINDOW = timedelta(minutes=10)
LOW_BALANCE_ERROR = "supplier_low_balance"
_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")
#: A refusal about the buyer's Steam account, not the listing: every other lot would be
#: refused the same way, so no substitute is tried and the money goes back at once. Seen on
#: csmarket's Waxpeer 2026-10-20 as "Please set your steam inventory public".
_BUYER_INVENTORY_HINTS = ("inventory public", "inventory is private", "private inventory")


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


def _result(
    outcome: str,
    key: str | None,
    *,
    error: str | None = None,
    money: MoneyOutcome | None = None,
    **extra: Any,
) -> FulfillResult:
    return FulfillResult(
        outcome=outcome,  # type: ignore[arg-type] # one of the three literals, set here only
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


class AmbiguousTradeError(Exception):
    """Several live trades under our key and no Waxpeer id to tell ours."""


def pick_trade(trades: Sequence[WaxpeerTrade], waxpeer_id: int | None) -> WaxpeerTrade | None:
    """Our trade among those under our key: by Waxpeer's id, else the only live one.

    Raises:
        AmbiguousTradeError: several live trades and no id to choose by.
    """
    if waxpeer_id:
        return next((t for t in trades if t.id == waxpeer_id), None)
    if len(trades) <= 1:
        return trades[0] if trades else None
    live = [t for t in trades if t.status != 6]
    if len(live) == 1:
        return live[0]
    if not live:
        return trades[-1]
    raise AmbiguousTradeError(str(len(live)))


def _looks_like_low_balance(exc: WaxpeerError) -> bool:
    text = f"{exc} {exc.body}".lower()
    return any(hint in text for hint in _LOW_BALANCE_HINTS)


def _looks_like_hidden_inventory(exc: WaxpeerError) -> bool:
    text = f"{exc} {exc.body}".lower()
    return any(hint in text for hint in _BUYER_INVENTORY_HINTS)


async def _candidates(
    client: SkinTradeClient, db: AsyncSession, *, slug: str, max_units: int, tried: set[int]
) -> list[tuple[int, int]]:
    """Same-name auto listings no dearer than paid, via the item page's cached read."""
    # Lazy: skins.listings imports the Waxpeer client, whose package imports this module.
    from yupay.modules.skins.listings import listings_for

    item = (await db.execute(select(SkinItem).where(SkinItem.slug == slug))).scalar_one_or_none()
    if item is None:
        return []
    rows, _ = await listings_for(
        item,
        client=client,  # type: ignore[arg-type] # SearchClient: search_listings only
        redis=get_redis(),
        budget_per_minute=get_settings().cs2_skins_listings_bucket_per_minute,
    )
    picked = [
        (r.listing_id, r.price_units)
        for r in rows
        if r.price_units <= max_units and r.listing_id not in tried
    ]
    return sorted(picked, key=lambda c: c[1])


async def _buy(
    client: SkinTradeClient,
    *,
    db: AsyncSession,
    item: OrderItem,
    row: SkinTrade,
    key: str,
    link: TradeLink,
) -> FulfillResult:
    """The chosen listing, then up to :data:`MAX_SUBSTITUTES` no dearer than it."""
    data = item.fulfillment_data or {}
    max_units = int(data.get("expected_units") or 0)
    queue: list[tuple[int, int]] = [(int(data.get("listing_id") or 0), max_units)]
    tried: set[int] = set()
    searched = False
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
        except WaxpeerUnavailableError:
            return _result(
                "in_progress", key, buy_unconfirmed_at=now().isoformat(), buy_pending=False
            )
        except WaxpeerError as exc:
            if _looks_like_low_balance(exc):
                # Nothing was bought: the buyer gets the money back now rather
                # than waiting on our top-up (owner, 2026-09-29); ops is alerted.
                row.reason = LOW_BALANCE_ERROR
                await db.flush()
                return _result(
                    "failed",
                    None,
                    error=LOW_BALANCE_ERROR,
                    money=MoneyOutcome.RETURNED,
                    required_units=max_units,
                )
            if exc.status < 500 and _looks_like_hidden_inventory(exc):
                # The buyer's inventory is hidden: no lot can be sent until they open it.
                # ``invalid_tradelink`` reads to them as «check the trade link» — the fix
                # is on their side — rather than «sold out».
                row.reason = "invalid_tradelink"
                await db.flush()
                return _result(
                    "failed",
                    key,
                    error="invalid_tradelink",
                    money=MoneyOutcome.RETURNED,
                    buy_pending=False,
                )
            if exc.status >= 500:
                # A server error may have bought it: resolve by lookup, never rebuy.
                return _result(
                    "in_progress", key, buy_unconfirmed_at=now().isoformat(), buy_pending=False
                )
            # A refusal (200) or a 4xx: nothing was bought — try a substitute.
            log.info(
                "skins.buy.refused",
                order_item_id=row.order_item_id,
                refused=isinstance(exc, WaxpeerBuyRefusedError),
            )
            if not queue and not searched:
                searched = True
                queue = await _candidates(
                    client, db, slug=str(data.get("slug") or ""), max_units=max_units, tried=tried
                )
            continue
        row.listing_id = listing_id
        row.waxpeer_id = bought.id
        row.bought_units = bought.price_units or units
        row.status = 0
        row.updated_at = now()
        await db.flush()
        return _result("in_progress", key, buy_pending=False)

    row.reason = "sold_out"
    await db.flush()
    return _result("failed", key, error="sold_out", money=MoneyOutcome.RETURNED, buy_pending=False)


async def fulfill_skin(
    client: SkinTradeClient, *, db: AsyncSession, item: OrderItem, idempotency_key: str
) -> FulfillResult:
    """Buy the line's listing (or a same-name one no dearer) for the trade link."""
    key = idempotency_key
    data = item.fulfillment_data or {}
    try:
        link = parse_tradelink(str(data.get("tradelink") or ""))
    except ValidationError:
        return _result("failed", None, error="invalid_tradelink", money=MoneyOutcome.RETURNED)
    row = await _trade_row(db, item, key)
    try:
        earlier = await client.check_project_ids([key])
    except (WaxpeerError, WaxpeerUnavailableError):
        # Nothing was sent: the sweep looks again and buys (see the module docstring).
        return _result("in_progress", key, buy_pending=True)
    try:
        found = pick_trade(earlier, row.waxpeer_id)
    except AmbiguousTradeError:
        return _result("in_progress", key)  # the status check fails it UNKNOWN
    if found is not None:
        mirror(row, found)
        await db.flush()
        return _result("in_progress", key)
    return await _buy(client, db=db, item=item, row=row, key=key, link=link)


def _status(
    outcome: str,
    *,
    error: str | None = None,
    money: MoneyOutcome | None = None,
    artifact: dict[str, Any] | None = None,
    **extra: Any,
) -> FulfillStatus:
    return FulfillStatus(
        outcome=outcome,  # type: ignore[arg-type] # one of the three literals below
        artifact_kind="topup_receipt" if artifact else None,
        artifact=artifact,
        error=error,
        money_outcome=money,
        extra_metadata=_meta(**extra),
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


async def _pending_buy(
    client: SkinTradeClient, *, db: AsyncSession, task: FulfillmentTask, row: SkinTrade | None
) -> FulfillStatus:
    """The buy a failed first lookup postponed — the lookup has now answered "none"."""
    item = await db.get(OrderItem, task.order_item_id)
    if item is None:  # pragma: no cover - FK
        return _status("failed", error="missing_item", money=MoneyOutcome.UNKNOWN)
    try:
        link = parse_tradelink(str((item.fulfillment_data or {}).get("tradelink") or ""))
    except ValidationError:
        return _status("failed", error="invalid_tradelink", money=MoneyOutcome.RETURNED)
    row = row or await _trade_row(db, item, task.external_order_id or "")
    result = await _buy(client, db=db, item=item, row=row, key=row.project_id, link=link)
    return FulfillStatus(
        outcome=result.outcome,
        artifact_kind=None,
        artifact=None,
        error=result.error,
        money_outcome=result.money_outcome,
        extra_metadata=result.extra_metadata,
    )


def _map(trade: WaxpeerTrade, row: SkinTrade | None, **extra: Any) -> FulfillStatus:
    if trade.status == 5 or (trade.status == 4 and trade.release_date is not None):
        return _status(
            "succeeded",
            artifact={
                "kind": "skin",
                "name": row.market_hash_name if row else None,
                "trade_id": trade.trade_id,
                "release_date": trade.release_date.isoformat() if trade.release_date else None,
            },
            **extra,
        )
    if trade.status == 6:
        accepted = trade.release_date is not None or (row is not None and row.release_date)
        if accepted or trade.penalties:
            return _status("failed", error="rolled_back", money=MoneyOutcome.SPENT, **extra)
        return _status("failed", error="not_accepted", money=MoneyOutcome.RETURNED, **extra)
    return _status("in_progress", **extra)


async def skin_status(
    client: SkinTradeClient, *, db: AsyncSession, task: FulfillmentTask
) -> FulfillStatus:
    """One look at the trade: finish a pending buy, mirror the trade, map it."""
    row = (
        await db.execute(select(SkinTrade).where(SkinTrade.order_item_id == task.order_item_id))
    ).scalar_one_or_none()
    key = task.external_order_id or (row.project_id if row else "")
    trades = await client.check_project_ids([key]) if key else []
    try:
        trade = pick_trade(trades, row.waxpeer_id if row else None)
    except AmbiguousTradeError:
        log.warning("skins.trade.ambiguous", project_id=key, trades=len(trades))
        if row is not None:
            row.reason = "ambiguous_trade"
            await db.flush()
        return _status("failed", error="ambiguous_trade", money=MoneyOutcome.UNKNOWN)
    pending = bool((task.extra_metadata or {}).get("buy_pending"))
    if trade is None:
        if pending:
            return await _pending_buy(client, db=db, task=task, row=row)
        if _unconfirmed_expired(task):
            if row is not None:
                row.reason = "buy_unconfirmed"
                await db.flush()
            return _status("failed", error="buy_unconfirmed", money=MoneyOutcome.UNKNOWN)
        return _status("in_progress")
    if row is not None:
        row.task_id = task.id
        mirror(row, trade)
        await db.flush()
    return _map(trade, row, **({"buy_pending": False} if pending else {}))


__all__ = [
    "MAX_SUBSTITUTES",
    "SKIN_KIND",
    "AmbiguousTradeError",
    "SkinTradeClient",
    "fulfill_skin",
    "is_skin_line",
    "is_skin_task",
    "mirror",
    "pick_trade",
    "skin_status",
]
