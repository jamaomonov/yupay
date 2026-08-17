"""``Fulfiller`` for G-Engine (api.g-engine.net) game top-ups.

G-Engine is a *second source* for titles we already sell — its catalogue
overlaps ours almost exactly (Mobile Legends RU, PUBG, Delta Force, Arena
Breakout, Steam in USD/RUB/KZT/UAH) at prices that beat G2B on some SKUs and
lose on others. It earns its place as a fallback for when the primary route is
out of stock or short on balance, which is what ``sourcing`` already routes.

**Why this adapter is a state machine and the others are not.** A G-Engine
order is created *unpaid*. G-Engine then validates the player account itself
and moves the order ``pending → processing → verified``; only a ``verified``
order may be paid, and only payment ships it. So one sale is two calls with a
supplier-side verification in between:

    create ──► pending/processing ──► verified ──► pay ──► paid ──► shipped
                     │                    │
                     └──► invalid_account └──► cancelled

``fulfill`` therefore usually returns ``in_progress`` rather than a delivered
artifact, and the poller (``process_webhook_update`` → :meth:`check_status`)
drives the rest. That is not a limitation to work around — the verification is
the supplier catching a wrong player id *before* our money moves.

**Idempotency.** The create call takes a ``uuid`` we choose, and G-Engine can
look an order up by it. A retry after a lost response therefore recovers the
original order instead of buying twice, which for a top-up is unrecoverable
money.
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
)
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineClient,
    GEngineError,
    GEngineOrder,
    GEngineUnavailableError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.gengine")

#: Our form-field keys → G-Engine's parameter names. Our checkout already
#: collects these (``player_id`` / ``server``); this is only the rename.
_PARAM_MAP: dict[str, str] = {
    "player_id": "Account",
    "account": "Account",
    "server": "Region",
    "region": "Region",
    "steam_login": "Account",
}

#: Order statuses that mean the sale is finished, one way or another.
_DELIVERED = "shipped"
_CUSTOMER_FAULT = {"invalid_account", "invalid_amount"}
_DEAD = {"cancelled"}


class GEngineFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for G-Engine."""

    supplier = "gengine"

    def __init__(self, client: GEngineClient | None = None) -> None:
        # Injectable for tests; in prod a transient client is built per call so
        # a hot-reloaded key takes effect without a restart (same as g2b).
        self._client_override = client

    def _client(self) -> GEngineClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return GEngineClient(
            api_key=s.gengine_api_key,
            base_url=s.gengine_base_url,
            timeout_seconds=s.gengine_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().gengine_api_key)

    # ---------- protocol ----------

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,  # noqa: ARG002 -- the item carries everything needed
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError("GENGINE_API_KEY is not configured")

        mapping = await _mapping_for(db, sku_id=item.sku_id)
        service_id = _int_or_fail(mapping.external_product_id, field="external_product_id")
        denomination_id = (
            _int_or_fail(mapping.external_variant_id, field="external_variant_id")
            if mapping.external_variant_id
            else None
        )
        params = _params_from(item)
        if not params:
            raise FulfillerError("no G-Engine parameters could be built from fulfillment_data")

        try:
            created = await self._client().create_recharge_order(
                service_id=service_id,
                params=params,
                denomination_id=denomination_id,
                uuid=idempotency_key,
            )
        except GEngineError as exc:
            # A create that was already made under this uuid is not a failure:
            # recover it rather than buying the same top-up twice.
            recovered = await self._recover(idempotency_key)
            if recovered is None:
                raise FulfillerError(str(exc)) from exc
            created = recovered
        except GEngineUnavailableError as exc:
            raise FulfillerError(str(exc)) from exc

        return await self._advance(created, first_call=True)

    async def check_status(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- the task carries the supplier id
        task: FulfillmentTask,
    ) -> FulfillStatus:
        if not task.external_order_id:
            return FulfillStatus(
                outcome="in_progress", artifact_kind=None, artifact=None, error=None
            )
        try:
            order = await self._client().get_recharge_order(int(task.external_order_id))
        except (GEngineError, GEngineUnavailableError) as exc:
            raise FulfillerError(str(exc)) from exc

        result = await self._advance(order, first_call=False)
        return FulfillStatus(
            outcome=result.outcome,
            artifact_kind=result.artifact_kind,
            artifact=result.artifact,
            error=result.error,
            extra_metadata=result.extra_metadata,
        )

    async def cancel(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        raise FulfillerNotIntegratedError("g-engine exposes no cancel endpoint")

    # ---------- state machine ----------

    async def _advance(self, order: GEngineOrder, *, first_call: bool) -> FulfillResult:
        """Move the order one step, and report where it landed.

        ``verified`` is the only state that opens payment, so this pays as soon
        as it sees one — whether that is on the first call or a later poll.
        """
        if order.status == "verified":
            try:
                order = await self._client().pay_recharge_order(order.id)
            except GEngineError as exc:
                # Paying is where our money leaves. A refusal here is worth
                # surfacing verbatim rather than as a generic failure.
                return _failed(order, f"payment refused: {exc}")
            except GEngineUnavailableError as exc:
                # Undecided upstream: stay in progress so the poller retries
                # instead of failing a sale that may yet complete.
                log.warning("gengine.pay_unavailable", order_id=order.id, error=str(exc))
                return _in_progress(order)

        if order.status == _DELIVERED:
            return FulfillResult(
                outcome="succeeded",
                external_order_id=str(order.id),
                artifact_kind="topup_receipt",
                artifact=_receipt(order),
                error=None,
                extra_metadata={"supplier": self.supplier, "gengine_status": order.status},
            )
        if order.status in _CUSTOMER_FAULT:
            return _failed(order, order.status)
        if order.status in _DEAD:
            return _failed(order, "cancelled by supplier")

        if first_call:
            log.info("gengine.order_created", order_id=order.id, status=order.status)
        return _in_progress(order)

    async def _recover(self, uuid: str) -> GEngineOrder | None:
        """The order behind a uuid we already used, if there is one."""
        try:
            return await self._client().get_recharge_order_by_uuid(uuid)
        except (GEngineError, GEngineUnavailableError):
            return None

    # ---------- probe ----------

    async def health(self) -> dict[str, Any]:
        """Connectivity + wallet balance for ``/admin/integrations/gengine/health``.

        Never raises: an operator opening the integrations page must not meet
        an error boundary because a supplier is down.
        """
        if not self.available:
            return {"available": False, "reason": "GENGINE_API_KEY is not configured"}
        try:
            data = await self._client().get_balance()
        except (GEngineError, GEngineUnavailableError) as exc:
            return {"available": False, "reason": str(exc)[:200]}
        except Exception as exc:  # noqa: BLE001 -- a probe must not crash the page
            return {"available": False, "reason": str(exc)[:200]}
        balance = data.get("balance")
        return {
            "available": True,
            "balance": f"{float(balance):.2f}" if balance is not None else None,
            "currency": data.get("currency"),
        }


# ---------- helpers ----------


async def _mapping_for(db: AsyncSession, *, sku_id: str) -> Any:
    from sqlalchemy import select

    from yupay.modules.integrations.models import SkuSupplierMapping

    row = (
        await db.execute(
            select(SkuSupplierMapping).where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.supplier_slug == "gengine",
                SkuSupplierMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise FulfillerError("no active g-engine mapping for this SKU")
    return row


def _int_or_fail(raw: str | None, *, field: str) -> int:
    """G-Engine addresses services and denominations by integer id, and the
    mapping stores them as text. A non-numeric value is a misconfiguration
    worth naming, not a stack trace from ``int()``."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise FulfillerError(f"g-engine mapping {field} must be numeric, got {raw!r}") from exc


def _params_from(item: OrderItem) -> dict[str, str]:
    """Translate the checkout form into G-Engine's parameter names.

    Only keys we recognise are forwarded — an unmapped field is more likely a
    form we have not taught this adapter about than something the supplier
    wants, and passing it through would be rejected as an unknown param.
    """
    data = item.fulfillment_data or {}
    out: dict[str, str] = {}
    for key, value in data.items():
        target = _PARAM_MAP.get(str(key).lower())
        if target and str(value).strip():
            out.setdefault(target, str(value).strip())
    return out


def _receipt(order: GEngineOrder) -> dict[str, Any]:
    """What the customer sees. Deliberately thin: a top-up has no code to
    hand over, only proof that it happened."""
    return {
        "supplier": "gengine",
        "external_order_id": str(order.id),
        "status": order.status,
    }


def _in_progress(order: GEngineOrder) -> FulfillResult:
    return FulfillResult(
        outcome="in_progress",
        external_order_id=str(order.id),
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={"supplier": "gengine", "gengine_status": order.status},
    )


def _failed(order: GEngineOrder, error: str) -> FulfillResult:
    return FulfillResult(
        outcome="failed",
        external_order_id=str(order.id),
        artifact_kind=None,
        artifact=None,
        error=error,
        extra_metadata={
            "supplier": "gengine",
            "gengine_status": order.status,
            # A refunded order needs no money chased; one that failed *without*
            # a refund does, and only the flag tells them apart.
            "supplier_refunded": order.is_refunded,
        },
    )


__all__ = ["GEngineFulfiller"]
