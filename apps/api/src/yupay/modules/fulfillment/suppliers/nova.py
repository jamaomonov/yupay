"""``Fulfiller`` for NOVA (nova-gifts.com) game top-ups.

NOVA is a **reserve**: its catalogue covers essentially every game brand we
sell, and it earns its place as somewhere to send an order when G2B is out of
stock, short on balance, or down. Nothing routes there on its own — sourcing
keeps the incumbent mapping and an operator switches a SKU with
``force_supplier`` (see ``docs/runbooks/nova.md``).

Two facts from their API shape this adapter:

* **The create spends.** "Balance is charged immediately; then ``processing``
  until completed/refund." So this grades money like Waxpeer, not like
  G-Engine: a create that failed on or after the call leaves both answers open
  and is :attr:`MoneyOutcome.UNKNOWN`, never "returned".
* **Their order object is untyped** in their own OpenAPI (``order: {}``). The
  status table below is therefore an allow-list, and anything outside it is
  ``in_progress`` — reading an unknown word as success would mark undelivered
  goods delivered, and reading it as failure would start reconciliation on
  money that may still complete normally. The first live order is a documented
  runbook step precisely because it is what turns this guess into a fact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.nova")

#: Our form-field keys -> their `fields` keys. Our checkout already collects
#: these; this is only the rename. Unrecognised keys are dropped, as in the
#: G-Engine adapter: an unmapped field is more likely a form we have not taught
#: this adapter about than something NOVA wants.
_FIELD_MAP: dict[str, str] = {
    "player_id": "player_id",
    "account": "player_id",
    "server": "server_id",
    "server_id": "server_id",
    "zone": "server_id",
    "zone_id": "server_id",
}

#: Must equal ``fulfillment.service._LOW_BALANCE_ERROR`` — the saga keys on
#: this exact string to keep the customer on "processing", park the task in the
#: admin inbox and alert ops instead of failing the order. A guard test locks
#: the match (see ``test_supplier_money_outcome.py``).
LOW_BALANCE_ERROR = "supplier_low_balance"

#: They document no code for it, so we sniff the message. A false positive only
#: demotes a hard failure to a retryable one, which is the safer mistake.
_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")

_IN_FLIGHT = frozenset(
    {
        "pending",
        "preparing",
        "prepared",
        "debited",
        "processing",
        "in_progress",
        "created",
        "queued",
        "new",
    }
)
_SUCCESS = frozenset({"completed", "success", "delivered", "done"})
_REFUNDED = frozenset({"refunded", "refund"})
_FAILED = frozenset({"failed", "error", "cancelled", "canceled"})

#: A refusal raised before any call, or one their API answered with — nothing
#: was charged.
_NOTHING_SPENT = MoneyOutcome.RETURNED
#: A failure on or after the call that spends.
_MAY_HAVE_SPENT = MoneyOutcome.UNKNOWN


def _status_of(obj: dict[str, Any]) -> str:
    """Their order status, lowercased. ``""`` when the object carries none.

    Reads ``status`` then ``state``. The warning is how we learn their real
    shape from the first live order — their spec types this object as ``{}``.
    """
    raw = obj.get("status") or obj.get("state") or ""
    text = str(raw).strip().lower()
    if not text:
        log.warning("nova.order_without_status", keys=sorted(str(k) for k in obj)[:10])
    return text


def _order_id_of(obj: dict[str, Any]) -> str | None:
    """Their order id, as a string. ``None`` when we cannot find one."""
    for key in ("id", "order_id", "public_id", "uuid"):
        value = obj.get(key)
        if value not in (None, ""):
            return str(value)
    log.warning("nova.order_without_id", keys=sorted(str(k) for k in obj)[:10])
    return None


def _fields_from(item: OrderItem) -> dict[str, str]:
    """Their ``fields`` payload, built from our form data."""
    data = item.fulfillment_data or {}
    out: dict[str, str] = {}
    for key, value in data.items():
        target = _FIELD_MAP.get(str(key).lower())
        if target and str(value).strip():
            out.setdefault(target, str(value).strip())
    return out


def _looks_like_low_balance(exc: NovaError) -> bool:
    """Whether a refusal is a "top up your balance" one."""
    text = f"{exc} {exc.body} {exc.code}".lower()
    return any(hint in text for hint in _LOW_BALANCE_HINTS)


def _refusal_money(exc: NovaError) -> MoneyOutcome:
    """What a refusal says about our money.

    400/403/404 are refusals of the request itself — an unknown category or
    offer, a malformed field, an inactive subscription — and they happen before
    anything is charged. A 409 is their idempotency refusal, and their two
    descriptions of it disagree (the endpoint says a reused key returns the
    original order, the parameter says it is rejected), so it cannot tell us
    whether the first attempt charged us. 5xx is the same kind of open
    question with a different cause.
    """
    return _NOTHING_SPENT if exc.status in (400, 403, 404) else _MAY_HAVE_SPENT


def _receipt(order_id: str | None, status: str) -> dict[str, Any]:
    """What the customer sees. Deliberately thin: a top-up has no code to hand
    over, only proof that it happened."""
    return {"supplier": "nova", "external_order_id": order_id, "status": status}


def _meta(status: str) -> dict[str, Any]:
    return {"supplier": "nova", "nova_status": status}


def _low_balance_result() -> FulfillResult:
    """A soft low-balance failure the saga parks in the inbox and alerts on."""
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE_ERROR,
        extra_metadata={"supplier": "nova"},
        # Deliberately unclassified: the order is not finished failing.
        money_outcome=None,
    )


def _result(obj: dict[str, Any]) -> FulfillResult:
    """Interpret one order object into a fulfilment result."""
    status = _status_of(obj)
    order_id = _order_id_of(obj)
    if status in _SUCCESS:
        return FulfillResult(
            outcome="succeeded",
            external_order_id=order_id,
            artifact_kind="topup_receipt",
            artifact=_receipt(order_id, status),
            error=None,
            extra_metadata=_meta(status),
            money_outcome=None,
        )
    if status in _REFUNDED:
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=f"nova refunded the order ({status})",
            extra_metadata={**_meta(status), "supplier_refunded": True},
            money_outcome=MoneyOutcome.RETURNED,
        )
    if status in _FAILED:
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=f"nova order {status}",
            extra_metadata={**_meta(status), "needs_reconciliation": True},
            money_outcome=_MAY_HAVE_SPENT,
        )
    # Everything else, including a status we have never seen: still moving.
    return FulfillResult(
        outcome="in_progress",
        external_order_id=order_id,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata=_meta(status),
        money_outcome=None,
    )


class NovaFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for NOVA."""

    supplier = "nova"

    def __init__(self, client: NovaClient | None = None) -> None:
        # Injectable for tests; in prod a transient client is built per call so
        # a hot-reloaded key takes effect without a restart (same as g2b).
        self._client_override = client

    def _client(self) -> NovaClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return NovaClient(
            api_key=s.nova_api_key,
            base_url=s.nova_base_url,
            timeout_seconds=s.nova_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().nova_api_key)

    # ---------- protocol ----------

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,  # noqa: ARG002 -- not consulted; the item carries everything
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError("NOVA_API_KEY is not configured", money_outcome=_NOTHING_SPENT)

        if item.qty > 1:
            raise FulfillerError(
                "nova has no quantity on a top-up order — one call buys one offer",
                money_outcome=_NOTHING_SPENT,
            )

        mapping = await _mapping_for(db, sku_id=item.sku_id)
        category_id = str(mapping.external_product_id or "").strip()
        offer_id = str(mapping.external_variant_id or "").strip()
        if not category_id or not offer_id:
            raise FulfillerError(
                "no active nova mapping for this SKU", money_outcome=_NOTHING_SPENT
            )

        fields = _fields_from(item)
        if not fields:
            raise FulfillerError(
                "no nova fields could be built from fulfillment_data",
                money_outcome=_NOTHING_SPENT,
            )

        try:
            obj = await self._client().create_topup_order(
                category_id=category_id,
                offer_id=offer_id,
                fields=fields,
                idempotency_key=idempotency_key,
            )
        except NovaError as exc:
            if _looks_like_low_balance(exc):
                return _low_balance_result()
            raise FulfillerError(str(exc), money_outcome=_refusal_money(exc)) from exc
        except NovaUnavailableError as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _result(obj)

    async def check_status(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- the task carries the supplier id
        task: FulfillmentTask,
    ) -> FulfillStatus:
        if not self.available:
            # UNKNOWN, not "never ordered": by the time anything polls, the
            # order has been placed. A key that went missing since says
            # nothing about the money it was spent with.
            raise FulfillerError("NOVA_API_KEY is not configured", money_outcome=_MAY_HAVE_SPENT)
        if not task.external_order_id:
            # The create never got far enough to give us an id — the
            # reconciler keeps looking rather than treating this as decided.
            return FulfillStatus(
                outcome="in_progress",
                artifact_kind=None,
                artifact=None,
                error=None,
                money_outcome=None,
            )

        try:
            obj = await self._client().get_order(task.external_order_id)
        except (NovaError, NovaUnavailableError) as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        result = _result(obj)
        return FulfillStatus(
            outcome=result.outcome,
            artifact_kind=result.artifact_kind,
            artifact=result.artifact,
            error=result.error,
            extra_metadata=result.extra_metadata,
            money_outcome=result.money_outcome,
        )

    async def cancel(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        # Refusing a *cancellation*, not ending a purchase: the order it
        # would have cancelled was already bought, and this call learns
        # nothing about what became of that money. See
        # :class:`FulfillerNotIntegratedError` for why a stub answers
        # RETURNED here and an integrated adapter does not.
        raise FulfillerNotIntegratedError(
            "nova exposes no cancel endpoint", money_outcome=MoneyOutcome.UNKNOWN
        )


# ---------- helpers ----------


async def _mapping_for(db: AsyncSession, *, sku_id: str) -> Any:
    from sqlalchemy import select

    from yupay.modules.integrations.models import SkuSupplierMapping

    row = (
        await db.execute(
            select(SkuSupplierMapping).where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.supplier_slug == "nova",
                SkuSupplierMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise FulfillerError("no active nova mapping for this SKU", money_outcome=_NOTHING_SPENT)
    return row


__all__ = ["NovaFulfiller"]
