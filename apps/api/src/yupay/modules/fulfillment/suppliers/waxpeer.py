"""Waxpeer Steam wallet top-up adapter.

One supplier, one job: move money into a customer's Steam wallet. Unlike
G2B (voucher purchases *and* game top-ups, branched by SKU mapping), every
Waxpeer SKU is the same shape — a customer-chosen dollar amount, gross
converted to supplier units, posted with the order's idempotency key as
``custom_id``. All HTTP lives in
:class:`yupay.modules.fulfillment.suppliers.waxpeer_client.WaxpeerClient`;
this module is pure orchestration and status-mapping.

Idempotent replay: ``custom_id`` is the fulfilment task's id (passed in as
``idempotency_key``). Waxpeer returns the *original* top-up for a repeated
``custom_id`` instead of charging twice, so calling :meth:`fulfill` again
after a timeout or an admin retry is safe — it never creates a second
top-up, and the reconciliation logic below reads whatever state the
original top-up is in today (which may by then be terminal).

Status vocabulary (see :class:`WaxpeerStatus`): ``created``/``sending`` are
in flight, ``completed`` is the only success, ``canceled``/``error`` are
both failures but differ in whether Waxpeer already returned our money.
``unknown`` — the client's catch-all for a status this module has never
seen — is deliberately treated as in-flight, not resolved either way: reading
it as success would mark undelivered goods delivered, reading it as failure
would trigger reconciliation for money that may still complete normally.

PII: ``steam_login`` is customer-supplied and lands in the outbound request
body (it has to) and in the customer-facing receipt artifact (the customer
already knows it), but it is never written to a log line.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import (
    ArtifactKind,
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillOutcome,
    FulfillResult,
    FulfillStatus,
)
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerClient,
    WaxpeerError,
    WaxpeerStatus,
    WaxpeerTopup,
    WaxpeerUnavailableError,
)
from yupay.modules.pricing.variable import UNITS_PER_USD, to_units

log = get_logger("yupay.fulfillment.waxpeer")

_CENT = Decimal("0.01")

# Soft-failure sentinel: a paid order the supplier can't fund right now. MUST
# equal ``fulfillment.service._LOW_BALANCE_ERROR`` — the saga keys on this exact
# string to keep the customer on "processing", park the task in the admin inbox,
# and alert ops instead of surfacing a hard error. A guard test locks the match.
LOW_BALANCE_ERROR = "supplier_low_balance"
# Substrings that mark a Waxpeer refusal as "top up your balance", not a real
# failure. Waxpeer has no dedicated code, so we sniff the message — a false
# positive only demotes a hard failure to a retryable one, the safer mistake.
_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")

_TERMINAL_OK: WaxpeerStatus = "completed"
# "unknown" is in-flight, not terminal: see module docstring. It is the
# client's mapping for any status Waxpeer might add later.
_IN_FLIGHT: tuple[WaxpeerStatus, ...] = ("created", "sending", "unknown")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem


def _status_to_outcome(status: WaxpeerStatus) -> FulfillOutcome:
    """Map a Waxpeer top-up status to the ``Fulfiller`` outcome vocabulary."""
    if status == _TERMINAL_OK:
        return "succeeded"
    if status in _IN_FLIGHT:
        return "in_progress"
    return "failed"


def _looks_like_low_balance(exc: WaxpeerError) -> bool:
    """Whether a Waxpeer refusal is a "top up your balance" one."""
    text = f"{exc} {exc.body}".lower()
    return any(hint in text for hint in _LOW_BALANCE_HINTS)


def _low_balance_result(*, balance_units: int | None, required_units: int) -> FulfillResult:
    """A soft low-balance failure the saga parks in the inbox + alerts on.

    Dollars in ``extra_metadata`` (the alert renders ``$balance / $required``);
    ``current_balance`` is left off when we couldn't read it. ``external_product_id``
    labels the alert since Waxpeer is a single product.
    """
    extra: dict[str, Any] = {
        "supplier": "waxpeer",
        "required": f"{Decimal(required_units) / UNITS_PER_USD:.2f}",
        "external_product_id": "steam-topup",
    }
    if balance_units is not None:
        extra["current_balance"] = f"{Decimal(balance_units) / UNITS_PER_USD:.2f}"
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE_ERROR,
        extra_metadata=extra,
    )


@dataclass(frozen=True)
class _Reconciled:
    """Shared result of interpreting one ``WaxpeerTopup`` — used by both
    :meth:`WaxpeerFulfiller.fulfill` and :meth:`WaxpeerFulfiller.check_status`.
    Both carry ``extra_metadata`` onto the task (fulfill via ``FulfillResult``,
    check_status via ``FulfillStatus``), so the reconciliation flags land on
    ``task.extra_metadata`` as queryable fields — and, redundantly, in
    ``error``/``last_error`` for a human reading the inbox."""

    outcome: FulfillOutcome
    artifact_kind: ArtifactKind | None
    artifact: dict[str, Any] | None
    error: str | None
    extra_metadata: dict[str, Any]


class WaxpeerFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for Waxpeer Steam top-ups."""

    supplier = "waxpeer"

    def __init__(self, client: WaxpeerClient | None = None) -> None:
        # ``client`` injectable for tests; in prod we build a transient one
        # from settings each call so a hot-reloaded key is picked up.
        self._client_override = client

    def _client(self) -> WaxpeerClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return WaxpeerClient(
            api_key=s.waxpeer_api_key,
            base_url=s.waxpeer_base_url,
            timeout_seconds=s.waxpeer_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().waxpeer_api_key)

    # ---------- protocol ----------

    async def fulfill(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- not consulted; the item carries everything
        order: Order,  # noqa: ARG002 -- not consulted; same
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError("WAXPEER_API_KEY is not configured")

        steam_login = str((item.fulfillment_data or {}).get("steam_login") or "").strip()
        if not steam_login:
            raise FulfillerError("order item is missing fulfillment_data.steam_login")

        s = get_settings()
        amount_units = to_units(item.unit_price_usd, fee_rate=s.waxpeer_fee_rate)

        try:
            topup = await self._client().create_topup(
                steam_login=steam_login,
                amount_units=amount_units,
                custom_id=idempotency_key,
            )
        except WaxpeerError as exc:
            # Low balance is a SOFT failure, never a raise: the order is already
            # paid. Waxpeer is the authority — it refuses the create with
            # "not enough balance" — so we react to that rather than pre-probing
            # every fulfil. The saga keeps the customer on "processing" and
            # alerts ops (service.process_task); an admin tops up and retries.
            if _looks_like_low_balance(exc):
                balance_units = await self._balance_units_or_none()
                return _low_balance_result(balance_units=balance_units, required_units=amount_units)
            raise FulfillerError(f"waxpeer top-up failed: HTTP {exc.status}") from exc
        except WaxpeerUnavailableError as exc:
            raise FulfillerError(f"waxpeer unreachable: {exc}") from exc

        reconciled = _reconcile(item=item, topup=topup)
        return FulfillResult(
            outcome=reconciled.outcome,
            external_order_id=idempotency_key,
            artifact_kind=reconciled.artifact_kind,
            artifact=reconciled.artifact,
            error=reconciled.error,
            extra_metadata=reconciled.extra_metadata,
        )

    async def check_status(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> FulfillStatus:
        if not self.available:
            raise FulfillerError("WAXPEER_API_KEY is not configured")
        if not task.external_order_id:
            raise FulfillerError("task has no waxpeer custom_id to check")

        # ``task.external_order_id`` is *our* custom_id (see fulfill()), not
        # a Waxpeer-issued id — lazy import mirrors g2b.py's check_status.
        from sqlalchemy import select

        from yupay.modules.orders.models import OrderItem

        item = (
            await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
        ).scalar_one()

        try:
            topup = await self._client().get_topup(custom_id=task.external_order_id)
        except WaxpeerError as exc:
            raise FulfillerError(f"waxpeer status check failed: HTTP {exc.status}") from exc
        except WaxpeerUnavailableError as exc:
            raise FulfillerError(f"waxpeer unreachable: {exc}") from exc

        reconciled = _reconcile(item=item, topup=topup)
        return FulfillStatus(
            outcome=reconciled.outcome,
            artifact_kind=reconciled.artifact_kind,
            artifact=reconciled.artifact,
            error=reconciled.error,
            # Carry the reconciliation flags (needs_reconciliation / supplier_refunded
            # / give_amount_shortfall_units) so the sweep persists them as queryable
            # fields — without this they'd exist only in the error string.
            extra_metadata=reconciled.extra_metadata,
        )

    async def cancel(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        # Waxpeer has no cancel endpoint for steam-topup. Claiming to cancel
        # would hide the truth from the fulfilment inbox — the task stays
        # whatever it was, and an admin has to reconcile by hand.
        raise FulfillerNotIntegratedError("waxpeer has no cancel endpoint for steam top-ups")

    # ---------- balance probe ----------

    async def _balance_units_or_none(self) -> int | None:
        """Our Waxpeer wallet balance in supplier units, or ``None`` if it
        can't be read. ``None`` (not 0) so a probe failure doesn't masquerade
        as a real low balance — ``fulfill`` then falls through to the create
        call and lets Waxpeer be the authority."""
        try:
            return await self._client().get_balance_units()
        except (WaxpeerError, WaxpeerUnavailableError):
            log.warning("waxpeer.balance_probe_failed")
            return None

    async def has_balance(self, units: int) -> bool:
        """Whether we can currently fund ``units``. ``False`` on an unreadable
        balance (not a raise), so a caller treating the supplier as unsellable
        fails safe."""
        balance = await self._balance_units_or_none()
        return balance is not None and balance >= units


# ---------- reconciliation ----------


def _reconcile(*, item: OrderItem, topup: WaxpeerTopup) -> _Reconciled:
    """Interpret one ``WaxpeerTopup`` against what we promised the customer.

    The promise is ``item.unit_price_usd`` dollars, i.e.
    ``unit_price_usd * UNITS_PER_USD`` supplier units — not the grossed-up
    ``amount_units`` we sent (that already includes the configured fee).
    ``give_amount_units`` is what Waxpeer says actually lands in the Steam
    wallet; if it falls short of the promise, a fee appeared that the
    configured ``waxpeer_fee_rate`` didn't account for, and that must
    surface immediately rather than under-deliver silently.
    """
    outcome = _status_to_outcome(topup.status)

    # `unit_price_usd` is only constrained to `> 0` at the DB layer
    # (Numeric(20,6)) — nothing enforces the "at most two decimals" rule that
    # `pricing.variable.validate_amount` checks at checkout time. This module
    # exists to catch shortfalls, so it must not blindly trust that upstream
    # invariant: quantize to cents before converting to units, so a stray
    # sub-cent fraction gets rounded rather than silently truncated away
    # (which would understate the promise and hide a real shortfall).
    promised_units = int(
        item.unit_price_usd.quantize(_CENT, rounding=ROUND_HALF_UP) * UNITS_PER_USD
    )
    shortfall = promised_units - topup.give_amount_units
    extra: dict[str, Any] = {
        "waxpeer_status": topup.status,
        "amount_units": topup.amount_units,
        "give_amount_units": topup.give_amount_units,
    }
    if shortfall > 0:
        extra["give_amount_shortfall_units"] = shortfall
        log.error(
            "waxpeer.give_amount_short",
            order_item_id=item.id,
            promised_units=promised_units,
            give_amount_units=topup.give_amount_units,
        )

    artifact_kind: ArtifactKind | None = None
    artifact: dict[str, Any] | None = None
    error: str | None = None

    if outcome == "succeeded" and shortfall > 0:
        # Under-delivery on an otherwise-successful top-up: Waxpeer credited
        # less than we promised the customer, who paid for the full amount.
        # Do NOT mark the order delivered — that closes it as fine and silently
        # pockets the shortfall against the customer. Route it to the
        # reconciliation inbox (failed, no receipt) so an admin tops up the
        # difference or refunds it. "failed" here does not auto-refund; it just
        # parks the task for manual handling (see fulfillment.service).
        outcome = "failed"
        extra["needs_reconciliation"] = True
        error = (
            f"waxpeer credited {topup.give_amount_units} units but we promised "
            f"{promised_units} (short {shortfall}); does not auto-refund — "
            "needs manual reconciliation"
        )
    elif outcome == "succeeded":
        artifact_kind = "topup_receipt"
        artifact = _receipt_artifact(item=item, topup=topup)
    elif outcome == "in_progress":
        if topup.status == "unknown":
            log.warning("waxpeer.topup_unknown_status", order_item_id=item.id, topup_id=topup.id)
    elif topup.status == "canceled":
        extra["supplier_refunded"] = True
        error = "waxpeer canceled the top-up; waxpeer refunded the amount to our balance"
    else:  # "error"
        extra["needs_reconciliation"] = True
        error = (
            "waxpeer reported an error on this top-up; it does not "
            "auto-refund this case — needs manual reconciliation"
        )

    return _Reconciled(
        outcome=outcome,
        artifact_kind=artifact_kind,
        artifact=artifact,
        error=error,
        extra_metadata=extra,
    )


def _receipt_artifact(*, item: OrderItem, topup: WaxpeerTopup) -> dict[str, Any]:
    """Customer-facing top-up receipt. No codes — the credit goes straight
    to the player's Steam wallet on Waxpeer's side."""
    return {
        "sku_id": item.sku_id,
        "qty": item.qty,
        "source": "waxpeer",
        "external_order_id": str(topup.id),
        "steam_login": topup.steam_login,
        "amount_units": topup.amount_units,
        "give_amount_units": topup.give_amount_units,
    }


__all__ = ["WaxpeerFulfiller"]
