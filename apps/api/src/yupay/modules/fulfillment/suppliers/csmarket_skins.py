"""Buy a CS2 skin through csmarket's public API and follow the trade (ADR-0098).

The csmarket twin of ``waxpeer_skins``. Rules:

* ``client_order_id`` = our fulfilment idempotency key. csmarket answers a repeat with the
  order it already has (409 ``duplicate_client_order_id``, returned by the client as
  ``created=False``), so **every** uncertainty is settled by sending the same purchase
  again — never by a timer and never by a second purchase. A lost answer (transport
  error, 5xx) parks the task ``buy_unconfirmed``; the status sweep re-sends.
* **The lot the buyer chose, or nothing** (owner, 2026-10-10; csmarket's ADR-0013). A buyer
  picks a lot by its float and stickers, so another lot of the same name is a different
  thing. ``offer_gone`` / ``price_above_max`` → ``RETURNED`` with ``sold_out`` at once; a
  line with no ``offer_id`` is never bought "any lot" — it is returned too. The checkout
  asks csmarket about the lot before payment (``skins.offer_check``), so this refusal is
  left for a lot sold in the minutes the buyer spent paying.
* ``402 insufficient_balance`` → the buyer is refunded at once and ops alerted, exactly
  like a Waxpeer low balance on a skin (owner, 2026-09-29).
* Any other 4xx refusal: csmarket bought nothing → ``RETURNED`` with its code.
* Status: ``buying`` in progress · ``trade_sent`` offer out · ``delivered`` succeeded ·
  ``refunded`` failed ``RETURNED`` with csmarket's reason. csmarket reports no rollback
  after delivery (it stays ``delivered``), so nothing here can produce ``SPENT``.
* A lot the purchase found sold (``offer_gone``, or a refund for ``sold_out``) is hidden
  from the offers list for a few minutes (``skins.listings_csmarket.forget``), as a lot the
  checkout found gone is: csmarket's check reads a copy of Skinslink up to 30 s old, so a
  lot sold seconds earlier can still pass it. A lot whose price moved is not sold, so it
  only drops the cached list, which then shows the new price.

The trade is mirrored onto ``skin_trades`` in Waxpeer's status codes (0 buying, 4 offer
out, 4 + ``release_date`` accepted, 5 released, 6 failed) so the order page, the admin
trades screen and the refund guard read it unchanged. The task carries
``waxpeer_kind = "skin"`` for the same reason: it is the saga's skin marker, whichever
supplier bought it.
"""

from __future__ import annotations

from datetime import timedelta
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
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.csmarket_client import (
    CsmarketClient,
    CsmarketError,
    CsmarketRateLimitedError,
    CsmarketUnavailableError,
    CsmOrder,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.skins.listings_csmarket import forget
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.tradelink import parse_tradelink

log = get_logger("yupay.fulfillment.csmarket_skins")

SUPPLIER = "csmarket"
SKIN_KIND = "skin"
LOW_BALANCE_ERROR = "supplier_low_balance"
#: Steam's trade protection after acceptance, when csmarket gives no ``release_at``.
_PROTECTION = timedelta(days=7)
#: csmarket refund reasons where nothing was ever sent to the buyer.
_NEVER_SENT = frozenset({"sold_out", "price_moved"})


class OrderClient(Protocol):
    """What this module needs from csmarket (``CsmarketClient`` satisfies it)."""

    async def create_order(
        self,
        *,
        item_id: str,
        offer_id: str | None,
        max_price_units: int,
        trade_link: str,
        client_order_id: str,
    ) -> tuple[CsmOrder, bool]: ...

    async def order(self, order_id: str) -> CsmOrder: ...


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


def _as_status(result: FulfillResult) -> FulfillStatus:
    return FulfillStatus(
        outcome=result.outcome,
        artifact_kind=result.artifact_kind,
        artifact=result.artifact,
        error=result.error,
        money_outcome=result.money_outcome,
        extra_metadata=result.extra_metadata,
    )


async def trade_row(db: AsyncSession, item: OrderItem, key: str) -> SkinTrade:
    """The line's trade mirror, created on first use."""
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
        supplier=SUPPLIER,
        offer_id=str(data.get("offer_id") or "") or None,
        listing_id=int(data.get("listing_id") or 0),
        market_hash_name=str(data.get("market_hash_name") or ""),
        phase=str(data.get("phase") or ""),
        paid_units=int(data.get("expected_units") or 0),
    )
    db.add(row)
    await db.flush()
    return row


def mirror(row: SkinTrade, order: CsmOrder) -> None:
    """Copy one csmarket order report onto our row, in Waxpeer's status codes."""
    at = now()
    row.supplier_order_id = order.order_id or row.supplier_order_id
    row.bought_units = order.price_units or row.bought_units
    trade = order.trade
    if trade is not None:
        row.trade_id = trade.steam_offer_id or row.trade_id
        if trade.seller_name:
            row.seller = {"name": trade.seller_name}
    if order.status == "buying":
        row.status = 0
    elif order.status == "trade_sent":
        row.status = 4
    elif order.status == "delivered":
        if row.release_date is None:
            row.accepted_at = (trade.accepted_at if trade else None) or at
            release = trade.release_at if trade else None
            row.release_date = release or (row.accepted_at + _PROTECTION)
        released = row.release_date is not None and row.release_date <= at
        row.status = 5 if released else 4
        row.is_released = released
    elif order.status == "refunded":
        reason = order.refund_reason or "supplier_refused"
        sent = row.status is not None and row.status >= 4
        if reason in _NEVER_SENT and not sent:
            row.status = None  # nothing was bought: the page says «распродано»
            row.reason = "sold_out"
        else:
            row.status = 6
            row.reason = "not accepted" if reason == "supplier_refused" and sent else reason
    row.last_checked_at = at
    row.updated_at = at


def _map(order: CsmOrder, row: SkinTrade) -> FulfillStatus:
    if order.status == "delivered":
        return FulfillStatus(
            outcome="succeeded",
            artifact_kind="topup_receipt",
            artifact={
                "kind": "skin",
                "name": row.market_hash_name,
                "trade_id": row.trade_id,
                "release_date": row.release_date.isoformat() if row.release_date else None,
            },
            error=None,
            money_outcome=None,
            extra_metadata=_meta(buy_unconfirmed_at=None),
        )
    if order.status == "refunded":
        return FulfillStatus(
            outcome="failed",
            artifact_kind=None,
            artifact=None,
            error=order.refund_reason or "supplier_refused",
            money_outcome=MoneyOutcome.RETURNED,
            extra_metadata=_meta(buy_unconfirmed_at=None),
        )
    return FulfillStatus(
        outcome="in_progress",
        artifact_kind=None,
        artifact=None,
        error=None,
        money_outcome=None,
        extra_metadata=_meta(buy_unconfirmed_at=None),
    )


#: csmarket codes and refund reasons that mean the lot itself was sold.
_LOT_SOLD = frozenset({"offer_gone", "item_not_found", "sold_out"})
#: ...and those that mean only its price moved.
_PRICE_MOVED = frozenset({"price_above_max", "price_moved"})


async def _refresh_lot(item: OrderItem, code: str | None) -> None:
    """Hide a sold lot, or drop the cached list for a repriced one (it never raises)."""
    data = item.fulfillment_data or {}
    slug, offer_id = data.get("slug"), data.get("offer_id")
    if not isinstance(slug, str) or not slug:
        return
    if code in _LOT_SOLD and offer_id:
        await forget(get_redis(), slug, str(offer_id))
    elif code in _PRICE_MOVED:
        await forget(get_redis(), slug)


def _refund_code(order: CsmOrder) -> str | None:
    return order.refund_reason if order.status == "refunded" else None


async def _settle(
    db: AsyncSession, item: OrderItem, row: SkinTrade, order: CsmOrder, key: str
) -> FulfillResult:
    mirror(row, order)
    await db.flush()
    await _refresh_lot(item, _refund_code(order))
    status = _map(order, row)
    return FulfillResult(
        outcome=status.outcome,
        external_order_id=key,
        artifact_kind=status.artifact_kind,
        artifact=status.artifact,
        error=status.error,
        extra_metadata=status.extra_metadata,
        money_outcome=status.money_outcome,
    )


async def buy(  # noqa: PLR0911 -- one return per outcome reads as the table above
    client: OrderClient, *, db: AsyncSession, item: OrderItem, row: SkinTrade, key: str
) -> FulfillResult:
    """Send the purchase (again, if a first answer was lost) and mirror what csmarket says."""
    data = item.fulfillment_data or {}
    try:
        link = parse_tradelink(str(data.get("tradelink") or ""))
    except ValidationError:
        return _result("failed", None, error="invalid_tradelink", money=MoneyOutcome.RETURNED)
    item_id = str(data.get("source_item_id") or "")
    cap = int(data.get("expected_units") or 0)
    if not item_id or cap <= 0:
        # A line checkout did not price for csmarket: nothing can be bought for it.
        return _result("failed", None, error="not_a_csmarket_line", money=MoneyOutcome.RETURNED)

    offer_id = str(data.get("offer_id") or "")
    if not offer_id:
        # Without the chosen lot csmarket would buy "the cheapest under the cap" — a lot
        # the buyer never saw. Never: the line ends and the money goes back.
        return _result("failed", None, error="not_a_csmarket_line", money=MoneyOutcome.RETURNED)
    try:
        order, created = await client.create_order(
            item_id=item_id,
            offer_id=offer_id,
            max_price_units=cap,
            trade_link=link.url,
            client_order_id=key,
        )
    except CsmarketRateLimitedError:
        return _result("in_progress", key, buy_pending=True)
    except CsmarketUnavailableError:
        # It may have landed: the sweep sends the same purchase again (409 → the order).
        return _result("in_progress", key, buy_unconfirmed_at=now().isoformat(), buy_pending=True)
    except CsmarketError as exc:
        return await _refused(db, item, row, exc, cap)
    if not created:
        log.info("skins.buy.adopted", order_item_id=row.order_item_id)
    return await _settle(db, item, row, order, key)


async def _refused(
    db: AsyncSession, item: OrderItem, row: SkinTrade, exc: CsmarketError, cap: int
) -> FulfillResult:
    """csmarket refused the purchase: nothing was bought, the line ends ``RETURNED``."""
    if exc.code == "insufficient_balance":
        # Nothing was bought: the buyer gets the money back now and ops tops up the wallet.
        row.reason = LOW_BALANCE_ERROR
        await db.flush()
        return _result(
            "failed", None, error=LOW_BALANCE_ERROR, money=MoneyOutcome.RETURNED, required_units=cap
        )
    reason = {
        "offer_gone": "sold_out",
        "price_above_max": "sold_out",
        "item_not_found": "sold_out",
        "trade_link_invalid": "invalid_tradelink",
    }.get(exc.code, exc.code or f"http_{exc.status}")
    log.warning(
        "skins.buy.refused", order_item_id=row.order_item_id, code=exc.code, status=exc.status
    )
    row.reason = reason
    row.updated_at = now()
    await db.flush()
    await _refresh_lot(item, exc.code)
    return _result(
        "failed", row.project_id, error=reason, money=MoneyOutcome.RETURNED, buy_pending=False
    )


async def skin_status(
    client: OrderClient, *, db: AsyncSession, task: FulfillmentTask
) -> FulfillStatus:
    """One look at the purchase: re-send it while unconfirmed, else read and mirror it."""
    item = await db.get(OrderItem, task.order_item_id)
    if item is None:  # pragma: no cover - FK
        return _as_status(_result("failed", None, error="missing_item", money=MoneyOutcome.UNKNOWN))
    key = task.external_order_id or ""
    row = await trade_row(db, item, key)
    row.task_id = task.id
    if not row.supplier_order_id:
        return _as_status(await buy(client, db=db, item=item, row=row, key=row.project_id))
    try:
        order = await client.order(row.supplier_order_id)
    except (CsmarketUnavailableError, CsmarketRateLimitedError):
        return _as_status(_result("in_progress", key))
    mirror(row, order)
    await db.flush()
    await _refresh_lot(item, _refund_code(order))
    return _map(order, row)


class CsmarketFulfiller:
    """``csmarket`` in the registry: CS2 skins only (ADR-0098)."""

    supplier = SUPPLIER

    def __init__(self, client: CsmarketClient | None = None) -> None:
        self._client_override = client

    def _client(self) -> CsmarketClient:
        if self._client_override is not None:
            return self._client_override
        settings = get_settings()
        return CsmarketClient(
            api_key=settings.csmarket_api_key,
            base_url=settings.csmarket_base_url,
            timeout_seconds=settings.csmarket_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(self._client_override is not None or get_settings().csmarket_api_key)

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,  # noqa: ARG002 -- the line carries everything
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError(
                "CSMARKET_API_KEY is not configured", money_outcome=MoneyOutcome.RETURNED
            )
        row = await trade_row(db, item, idempotency_key)
        return await buy(self._client(), db=db, item=item, row=row, key=idempotency_key)

    async def check_status(self, *, db: AsyncSession, task: FulfillmentTask) -> FulfillStatus:
        if not self.available:
            return _as_status(_result("in_progress", task.external_order_id))
        return await skin_status(self._client(), db=db, task=task)

    async def cancel(self, *, db: AsyncSession, task: FulfillmentTask) -> None:  # noqa: ARG002
        """A csmarket purchase cannot be cancelled from here; the trade runs its course."""
        return


__all__ = [
    "SUPPLIER",
    "CsmarketFulfiller",
    "OrderClient",
    "buy",
    "mirror",
    "skin_status",
    "trade_row",
]
