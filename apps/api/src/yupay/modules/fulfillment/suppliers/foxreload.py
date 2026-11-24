"""FoxReload Steam wallet top-up adapter (ADR-0107).

One job for now: put whole dollars into a Steam wallet by login, through their
product "Steam Wallet 1 USD (Global)" bought ``amount`` times. The product id
comes from the SKU's ``sku_supplier_mapping`` row (``external_product_id``), so
an operator can point it elsewhere without a deploy.

**Whole dollars only.** The product is sold per dollar, ``1..175`` per item, so
a line with cents or above the cap cannot be bought here. ``fulfillment.service``
sends such lines to ``foxreload_overflow_supplier`` before a task is created
(:func:`takes_line` is the test both sides use); a line that reaches this
adapter anyway — an admin reassign, say — is refused before any call, with our
money intact.

**Two calls buy one top-up.** ``create`` makes an unpaid order, ``pay`` debits
our balance. A create that fails or times out has spent nothing, and a repeat
under the same key finds the order instead of making a second one (they refuse
a reused key with ``ORDER_ALREADY_EXISTS``). A pay that times out is left to
the poll: :meth:`FoxreloadFulfiller.check_status` reads the order and pays an
order that is still unpaid, so it is never paid twice and never abandoned.

**Money.** They refund a failed wholesale item to our balance on their own,
straight away (``refunded``). That, a cancelled (never paid) order and every
refusal before ``pay`` are :attr:`MoneyOutcome.RETURNED`; a ``pay`` whose answer
was lost is :attr:`MoneyOutcome.UNKNOWN` only if it can no longer be read.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillOutcome,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.foxreload_client import (
    BALANCE_NOT_ENOUGH,
    ORDER_ALREADY_EXISTS,
    ORDER_PAYMENT_ALREADY_CREATED,
    FoxOrder,
    FoxreloadClient,
    FoxreloadError,
    FoxreloadUnavailableError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.foxreload")

SUPPLIER = "foxreload"

#: Must equal ``fulfillment.service._LOW_BALANCE_ERROR``: the saga keeps the
#: customer waiting and alerts ops on exactly this string.
LOW_BALANCE_ERROR = "supplier_low_balance"

#: Nothing was paid: a refusal before ``pay``, or an order they refunded.
_RETURNED = MoneyOutcome.RETURNED
#: ``pay`` may have gone through and the order can no longer be read.
_UNKNOWN = MoneyOutcome.UNKNOWN

_IN_FLIGHT = frozenset({"active", "paid", "processing", "action_required"})
#: Nothing was debited for an order in these: no charge to record.
_UNPAID = frozenset({"active", "cancelled"})


def steam_quantity(item: OrderItem) -> int | None:
    """Whole dollars this line buys, or ``None`` when FoxReload cannot sell it.

    ``None`` for cents, for a non-positive amount and for anything outside the
    product's per-item bounds (``foxreload_steam_min_usd``..``max``).
    """
    s = get_settings()
    total = Decimal(item.unit_price_usd) * int(item.qty or 1)
    if total != total.to_integral_value():
        return None
    dollars = int(total)
    if dollars < s.foxreload_steam_min_usd or dollars > s.foxreload_steam_max_usd:
        return None
    return dollars


def takes_line(item: OrderItem) -> bool:
    """Whether FoxReload can buy this line at all. Read by the router."""
    return steam_quantity(item) is not None


def _steam_login(item: OrderItem) -> str:
    return str((item.fulfillment_data or {}).get("steam_login") or "").strip()


class FoxreloadFulfiller(Fulfiller):
    """``Fulfiller`` for FoxReload Steam wallet top-ups."""

    supplier = SUPPLIER

    def __init__(self, client: FoxreloadClient | None = None) -> None:
        # Injectable for tests; built per call in prod so a hot-reloaded key works.
        self._client_override = client

    def _client(self) -> FoxreloadClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return FoxreloadClient(
            api_key=s.foxreload_api_key,
            base_url=s.foxreload_base_url,
            timeout_seconds=s.foxreload_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().foxreload_api_key)

    # ---------- protocol ----------

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,  # noqa: ARG002 -- the item carries everything
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError("FOXRELOAD_API_KEY is not configured", money_outcome=_RETURNED)
        dollars = steam_quantity(item)
        if dollars is None:
            raise FulfillerError(
                f"foxreload sells Steam in whole dollars "
                f"{get_settings().foxreload_steam_min_usd}-"
                f"{get_settings().foxreload_steam_max_usd}; this line is "
                f"{item.unit_price_usd} x {item.qty} — send it to another supplier",
                money_outcome=_RETURNED,
            )
        login = _steam_login(item)
        if not login:
            raise FulfillerError(
                "order item is missing fulfillment_data.steam_login", money_outcome=_RETURNED
            )
        product_id = await _product_id(db, sku_id=item.sku_id)

        fox = await self._create_or_find(
            product_id=product_id, dollars=dollars, login=login, key=idempotency_key
        )
        if fox.status == "active":
            low = await self._pay(fox.id, required=dollars)
            if low is not None:
                return low
            fox = await self._reread(fox)

        graded = _grade(fox, item=item, login=login, dollars=dollars)
        return FulfillResult(
            outcome=graded.outcome,
            external_order_id=fox.id,
            artifact_kind="topup_receipt" if graded.artifact else None,
            artifact=graded.artifact,
            error=graded.error,
            extra_metadata=graded.extra,
            money_outcome=graded.money,
        )

    async def check_status(self, *, db: AsyncSession, task: FulfillmentTask) -> FulfillStatus:
        if not self.available:
            raise FulfillerError("FOXRELOAD_API_KEY is not configured", money_outcome=_UNKNOWN)
        if not task.external_order_id:
            raise FulfillerError("task has no foxreload order id to check", money_outcome=_UNKNOWN)

        from sqlalchemy import select

        from yupay.modules.orders.models import OrderItem

        item = (
            await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
        ).scalar_one()
        try:
            fox = await self._client().get_order(task.external_order_id)
        except (FoxreloadError, FoxreloadUnavailableError) as exc:
            raise FulfillerError(
                f"foxreload status check failed: {exc}", money_outcome=_UNKNOWN
            ) from exc

        dollars = steam_quantity(item) or 0
        if fox.status == "active":
            # The pay answer was lost (or never sent). Paying again is safe: a
            # second pay on a paid order is refused, never charged twice.
            low = await self._pay(fox.id, required=dollars)
            if low is not None:
                # Still unpaid, for want of balance: keep waiting. Their order
                # expires unpaid on its own (``cancelled``), which grades RETURNED.
                log.warning("foxreload.poll_low_balance", external_order_id=fox.id)
                return FulfillStatus(
                    outcome="in_progress",
                    artifact_kind=None,
                    artifact=None,
                    error=None,
                    money_outcome=None,
                    extra_metadata=low.extra_metadata,
                )
            fox = await self._reread(fox)

        graded = _grade(fox, item=item, login=_steam_login(item), dollars=dollars)
        return FulfillStatus(
            outcome=graded.outcome,
            artifact_kind="topup_receipt" if graded.artifact else None,
            artifact=graded.artifact,
            error=graded.error,
            money_outcome=graded.money,
            extra_metadata=graded.extra,
        )

    async def cancel(self, *, db: AsyncSession, task: FulfillmentTask) -> None:  # noqa: ARG002
        # Their cancel exists but is undocumented for a paid order, and a Steam
        # top-up in flight cannot be recalled. Refuse rather than pretend.
        raise FulfillerNotIntegratedError(
            "foxreload Steam top-ups are not cancelled from here", money_outcome=_UNKNOWN
        )

    # ---------- steps ----------

    async def _create_or_find(
        self, *, product_id: str, dollars: int, login: str, key: str
    ) -> FoxOrder:
        client = self._client()
        try:
            return await client.create_order(
                product_id=product_id, quantity=dollars, login=login, idempotency_key=key
            )
        except FoxreloadError as exc:
            if exc.code != ORDER_ALREADY_EXISTS:
                # Refused before anything was paid: a bad login, a product off sale.
                raise FulfillerError(
                    f"foxreload refused the order: {exc}", money_outcome=_RETURNED
                ) from exc
        except FoxreloadUnavailableError as exc:
            # A create pays nothing; a retry under the same key finds the order.
            raise FulfillerError(
                f"foxreload unreachable on create: {exc}", money_outcome=_RETURNED
            ) from exc
        try:
            found = await client.find_order_id(key)
            if found is None:
                raise FulfillerError(
                    "foxreload says the order exists but does not list it",
                    money_outcome=_UNKNOWN,
                )
            return await client.get_order(found)
        except (FoxreloadError, FoxreloadUnavailableError) as exc:
            raise FulfillerError(
                f"foxreload order lookup failed: {exc}", money_outcome=_UNKNOWN
            ) from exc

    async def _pay(self, order_id: str, *, required: int) -> FulfillResult | None:
        """Pay from our balance. A low-balance result, or ``None`` when paid
        (or when the answer was lost — the re-read and the poll decide)."""
        try:
            await self._client().pay_order(order_id)
        except FoxreloadError as exc:
            if exc.code == BALANCE_NOT_ENOUGH:
                return await self._low_balance(order_id, required=required)
            if exc.code != ORDER_PAYMENT_ALREADY_CREATED:
                raise FulfillerError(
                    f"foxreload refused to take payment: {exc}", money_outcome=_RETURNED
                ) from exc
        except FoxreloadUnavailableError:
            log.warning("foxreload.pay_unanswered", external_order_id=order_id)
        return None

    async def _reread(self, fox: FoxOrder) -> FoxOrder:
        """The order after ``pay``; the old view if it cannot be read now, so
        the line stays in flight and the poll reads it later."""
        try:
            return await self._client().get_order(fox.id)
        except (FoxreloadError, FoxreloadUnavailableError):
            log.warning("foxreload.reread_failed", external_order_id=fox.id)
            return FoxOrder(
                id=fox.id,
                status="processing",
                price=fox.price,
                refunded_amount=None,
                items=fox.items,
            )

    async def _low_balance(self, order_id: str, *, required: int) -> FulfillResult:
        extra: dict[str, Any] = {
            "supplier": SUPPLIER,
            "required": f"{Decimal(required):.2f}",
            "external_product_id": "steam-usd",
            "foxreload_order_id": order_id,
        }
        try:
            balance = await self._client().usd_balance()
        except (FoxreloadError, FoxreloadUnavailableError):
            balance = None
        if balance is not None:
            extra["current_balance"] = f"{balance:.2f}"
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=LOW_BALANCE_ERROR,
            extra_metadata=extra,
            money_outcome=None,
        )

    # ---------- probes ----------

    async def health(self) -> dict[str, Any]:
        """Connectivity + USD balance for the integrations page. Never raises."""
        if not self.available:
            return {"available": False, "reason": "FOXRELOAD_API_KEY is not configured"}
        try:
            balance = await self._client().usd_balance()
        except Exception as exc:  # noqa: BLE001 -- a probe must not crash the page
            return {"available": False, "reason": str(exc)[:200]}
        return {
            "available": True,
            "balance": f"{balance or Decimal(0):.2f}",
            "currency": "USD",
        }


# ---------- grading ----------


class _Graded:
    __slots__ = ("artifact", "error", "extra", "money", "outcome")

    def __init__(
        self,
        *,
        outcome: FulfillOutcome,
        money: MoneyOutcome | None,
        error: str | None = None,
        artifact: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.outcome = outcome
        self.money = money
        self.error = error
        self.artifact = artifact
        self.extra = extra or {}


def _grade(fox: FoxOrder, *, item: OrderItem, login: str, dollars: int) -> _Graded:
    """What one FoxReload order means for our line. Every path returns."""
    extra: dict[str, Any] = {"foxreload_status": fox.status}
    if fox.status not in _UNPAID and fox.price is not None and fox.price > 0:
        # What they debited, in USD: the margin reads this instead of assuming a
        # wallet dollar costs a dollar (``service._record_supplier_charge``).
        extra["supplier_charged_usd"] = str(fox.price)
    if fox.status == "completed":
        return _Graded(
            outcome="succeeded",
            money=None,
            extra=extra,
            artifact={
                "sku_id": item.sku_id,
                "qty": item.qty,
                "source": SUPPLIER,
                "external_order_id": fox.id,
                "steam_login": login,
                "amount_usd": dollars,
            },
        )
    if fox.status in ("refunded", "cancelled") or (
        fox.status == "failed" and (fox.refunded_amount or 0) > 0
    ):
        extra["supplier_refunded"] = True
        return _Graded(
            outcome="failed",
            money=_RETURNED,
            extra=extra,
            error=f"foxreload {fox.status}: {fox.item_error or 'no reason given'}",
        )
    if fox.status == "failed" or fox.status in _IN_FLIGHT:
        # ``failed`` without a refund yet: they refund a wholesale order right
        # after it fails, and the next poll reads ``refunded``.
        if fox.status == "action_required":
            log.warning("foxreload.action_required", external_order_id=fox.id)
        return _Graded(outcome="in_progress", money=None, extra=extra)
    # A status their API added after 2026-11-24. Waiting is the safe reading:
    # success would close an undelivered order, failure would refund on a guess.
    log.warning("foxreload.unknown_status", external_order_id=fox.id, status=fox.status)
    return _Graded(outcome="in_progress", money=None, extra=extra)


async def _product_id(db: AsyncSession, *, sku_id: str) -> str:
    """Their product id from the SKU's active mapping. Refuses without one."""
    from sqlalchemy import select

    from yupay.modules.integrations.models import SkuSupplierMapping

    row = (
        await db.execute(
            select(SkuSupplierMapping).where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.supplier_slug == SUPPLIER,
                SkuSupplierMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    product = str(getattr(row, "external_product_id", "") or "").strip()
    if not product:
        raise FulfillerError(
            "no active foxreload mapping with a product id for this SKU",
            money_outcome=_RETURNED,
        )
    return product


__all__ = ["SUPPLIER", "FoxreloadFulfiller", "steam_quantity", "takes_line"]
