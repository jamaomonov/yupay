"""``Fulfiller`` for NOVA (nova-gifts.com) game and Steam wallet top-ups.

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

from decimal import Decimal
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
from yupay.modules.fulfillment.suppliers.nova_grading import (
    _MAY_HAVE_SPENT,
    _NOTHING_SPENT,
    _finish,
    _looks_like_low_balance,
    _low_balance_result,
    _refusal_money,
    _result,
    _without_our_inputs,
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

#: A mapping whose ``external_product_id`` is this is a Steam wallet top-up,
#: not a game: their Steam endpoint takes a login and an amount and has no
#: category at all, so there is no real id to put here.
#:
#: A sentinel rather than a fourth ``kind`` for the reason ADR-0081 gives about
#: the validate namespace: ``ck_sku_supplier_mapping_kind`` allows only
#: ``voucher|game|gift``, and the admin's mapping wizard coerces whatever it
#: loads to ``voucher|game`` when an operator saves the page. A sentinel in a
#: column the wizard round-trips untouched survives that; a new kind does not.
STEAM_SENTINEL = "steam-topup"


#: They document no code for it, so we sniff the message. A false positive only
#: demotes a hard failure to a retryable one, which is the safer mistake.
def _fields_from(item: OrderItem) -> dict[str, str]:
    """Their ``fields`` payload, built from our form data."""
    data = item.fulfillment_data or {}
    out: dict[str, str] = {}
    for key, value in data.items():
        target = _FIELD_MAP.get(str(key).lower())
        if target and str(value).strip():
            out.setdefault(target, str(value).strip())
    return out


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
        if category_id == STEAM_SENTINEL:
            return await self._fulfill_steam(item=item, idempotency_key=idempotency_key)

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
            raise FulfillerError(
                _without_our_inputs(str(exc), fields), money_outcome=_refusal_money(exc)
            ) from exc
        except NovaUnavailableError as exc:
            # A transport failure carries no body, so there is nothing of ours
            # in it to take back out.
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _finish(obj)

    async def _fulfill_steam(self, *, item: OrderItem, idempotency_key: str) -> FulfillResult:
        """The Steam wallet branch. Mirrors the games path above exactly on
        money grading — same client, same exceptions, same guard — because a
        different endpoint is not a different money story.

        ``item.qty > 1`` is already refused by :meth:`fulfill` before the
        mapping is even loaded, so it is not repeated here.
        """
        steam_login = str((item.fulfillment_data or {}).get("steam_login") or "").strip()
        if not steam_login:
            raise FulfillerError(
                "order item is missing fulfillment_data.steam_login",
                money_outcome=_NOTHING_SPENT,
            )

        try:
            obj = await self._client().create_steam_order(
                steam_login=steam_login,
                amount_usd=Decimal(str(item.unit_price_usd)),
                idempotency_key=idempotency_key,
            )
        except NovaError as exc:
            if _looks_like_low_balance(exc):
                return _low_balance_result()
            raise FulfillerError(
                _without_our_inputs(str(exc), {"steam_login": steam_login}),
                money_outcome=_refusal_money(exc),
            ) from exc
        except NovaUnavailableError as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _finish(obj)

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

    async def health(self) -> dict[str, Any]:
        """Connectivity, key validity and wallet balance, in one call.

        ``GET /admin/integrations/nova/health`` reads this. It matters more
        here than for the other suppliers: NOVA is a reserve, so nothing routes
        to it on an ordinary day, and the first thing anyone asks before
        switching a SKU to it is whether the key still works and whether there
        is money behind it. Without this the answer needed a shell.

        Never raises: an operator opening the integrations page must not meet
        an error boundary because a supplier is down.
        """
        if not self.available:
            return {"available": False, "reason": "NOVA_API_KEY is not configured"}
        try:
            data = await self._client().get_balance()
        except Exception as exc:  # noqa: BLE001 -- a probe must not crash the page
            return {"available": False, "reason": str(exc)[:200]}
        balance = data.get("balance")
        return {
            "available": True,
            # Their balance is a decimal string ("0.0000"); the page wants the
            # two places everything else on it shows.
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
                SkuSupplierMapping.supplier_slug == "nova",
                # A NOVA row of any other kind is not a top-up route. The
                # composite primary key makes a second row impossible, so this
                # is not about ambiguity: it is about failing at our own guard,
                # with a message an operator can act on, rather than at NOVA
                # with whatever they say about an id from the wrong namespace.
                SkuSupplierMapping.kind == "game",
                SkuSupplierMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise FulfillerError(
            "no active nova game mapping for this SKU", money_outcome=_NOTHING_SPENT
        )
    return row


__all__ = ["NovaFulfiller"]
