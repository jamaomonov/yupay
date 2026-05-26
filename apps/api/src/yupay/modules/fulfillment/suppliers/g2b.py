"""G2Bulk (G2B) fulfiller — first real supplier integration.

One adapter, two branches: voucher purchases vs game top-ups. The branch
is chosen by ``SkuSupplierMapping.kind`` (voucher | game), so an admin
only needs to set the sourcing rule to ``force_supplier=g2b`` and create
the mapping — they don't pick the slug per flow.

The adapter is pure orchestration: it loads the mapping, builds the right
G2B request, persists the upstream identifier into the task, and
translates G2B's response back into a ``FulfillResult``. All HTTP lives in
:class:`yupay.modules.fulfillment.suppliers.g2b_client.G2bClient`.

PII / secrets policy:
- The API key only lives in ``X-API-Key`` headers — never in payloads or
  logs.
- ``delivery_items`` (the actual voucher codes) go into ``Delivery.artifact``
  (customer-facing storage) but NEVER into ``FulfillmentAttempt.payload``,
  which is admin-visible audit data; the audit row gets only
  ``{"delivery_count": N}`` as a count.
- ``player_id`` is never logged in plaintext — it appears only in the
  outbound request body where it has to.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerError,
    FulfillResult,
    FulfillStatus,
)
from yupay.modules.fulfillment.suppliers.g2b_client import (
    G2bClient,
    G2bError,
    G2bTerminalFailure,
)
from yupay.modules.integrations.service import get_mapping

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.orders.models import Order, OrderItem


class G2bFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for G2Bulk."""

    supplier = "g2b"

    def __init__(self, client: G2bClient | None = None) -> None:
        # ``client`` injectable for tests; in prod we build a transient one
        # from settings each call so a hot-reloaded key is picked up.
        self._client_override = client

    def _client(self) -> G2bClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return G2bClient(
            api_key=s.g2b_api_key,
            base_url=s.g2b_base_url,
            timeout_seconds=s.g2b_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().g2b_api_key)

    # ---------- protocol ----------

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,  # noqa: ARG002 -- not consulted; mapping carries everything
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError("G2B_API_KEY is not configured")
        mapping = await self._load_mapping(db, item.sku_id)

        if mapping.kind == "voucher":
            return await self._fulfill_voucher(
                mapping=mapping, item=item, idempotency_key=idempotency_key
            )
        return await self._fulfill_game(mapping=mapping, item=item, idempotency_key=idempotency_key)

    async def check_status(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> FulfillStatus:
        if not self.available:
            raise FulfillerError("G2B_API_KEY is not configured")
        if not task.external_order_id:
            raise FulfillerError("task has no G2B order id to check")

        # Re-derive the branch from the task's order item mapping, not from
        # the webhook body — webhook bodies are not trusted.
        from sqlalchemy import select

        from yupay.modules.orders.models import OrderItem

        item = (
            await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
        ).scalar_one()
        mapping = await self._load_mapping(db, item.sku_id)
        client = self._client()

        if mapping.kind == "voucher":
            try:
                result = await client.poll_voucher_delivery(task.external_order_id)
            except G2bTerminalFailure as exc:
                return FulfillStatus(
                    outcome="failed",
                    artifact_kind=None,
                    artifact=None,
                    error=str(exc),
                )
            if result.status == "completed":
                return FulfillStatus(
                    outcome="succeeded",
                    artifact_kind="voucher_code",
                    artifact=_voucher_artifact(
                        mapping=mapping,
                        item=item,
                        codes=result.delivery_items or [],
                        g2b_order_id=task.external_order_id,
                    ),
                    error=None,
                )
            return FulfillStatus(
                outcome="in_progress",
                artifact_kind=None,
                artifact=None,
                error=None,
            )

        # game
        status = await client.get_game_order_status(
            g2b_order_id=task.external_order_id, game_code=mapping.external_product_id
        )
        if status.status == "completed":
            return FulfillStatus(
                outcome="succeeded",
                artifact_kind="topup_receipt",
                artifact=_game_artifact(
                    mapping=mapping,
                    item=item,
                    g2b_order_id=task.external_order_id,
                    message=status.message,
                ),
                error=None,
            )
        if status.status == "failed":
            return FulfillStatus(
                outcome="failed",
                artifact_kind=None,
                artifact=None,
                error=status.message or "g2b reported failure",
            )
        return FulfillStatus(
            outcome="in_progress",
            artifact_kind=None,
            artifact=None,
            error=None,
        )

    async def cancel(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002
        task: FulfillmentTask,  # noqa: ARG002
    ) -> None:
        # G2B has no public cancel endpoint. Their docs say FAILED orders
        # auto-refund the balance, and there's nothing to do for completed
        # ones. The admin /cancel route already flipped the task locally;
        # we accept that as the only action available.
        return None

    # ---------- voucher branch ----------

    async def _fulfill_voucher(
        self,
        *,
        mapping: SkuSupplierMapping,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        qty = max(1, item.qty * mapping.quantity)
        client = self._client()
        try:
            result = await client.purchase_voucher(
                product_id=mapping.external_product_id,
                quantity=qty,
                idempotency_key=idempotency_key,
            )
        except G2bError as exc:
            raise FulfillerError(f"g2b purchase failed: HTTP {exc.status}") from exc

        if result.status == "completed":
            return FulfillResult(
                outcome="succeeded",
                external_order_id=result.g2b_order_id,
                artifact_kind="voucher_code",
                artifact=_voucher_artifact(
                    mapping=mapping,
                    item=item,
                    codes=result.delivery_items or [],
                    g2b_order_id=result.g2b_order_id,
                ),
                error=None,
                extra_metadata={
                    "supplier": "g2b",
                    "kind": "voucher",
                    "delivery_count": len(result.delivery_items or []),
                },
            )
        if result.status == "pending":
            return FulfillResult(
                outcome="in_progress",
                external_order_id=result.g2b_order_id,
                artifact_kind=None,
                artifact=None,
                error=None,
                extra_metadata={"supplier": "g2b", "kind": "voucher"},
            )
        return FulfillResult(
            outcome="failed",
            external_order_id=result.g2b_order_id,
            artifact_kind=None,
            artifact=None,
            error="g2b returned failed status",
            extra_metadata={"supplier": "g2b", "kind": "voucher"},
        )

    # ---------- game branch ----------

    async def _fulfill_game(
        self,
        *,
        mapping: SkuSupplierMapping,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        fulfillment_data = dict(item.fulfillment_data or {})
        player_id = str(fulfillment_data.get("player_id") or "").strip()
        if not player_id:
            raise FulfillerError("order item is missing fulfillment_data.player_id required by g2b")
        server_id = _stringify_or_none(fulfillment_data.get("server_id"))
        charname = _stringify_or_none(fulfillment_data.get("charname"))
        catalogue_name = mapping.external_variant_id
        if not catalogue_name:
            raise FulfillerError("g2b mapping is missing external_variant_id for kind=game")

        s = get_settings()
        callback_url = s.g2b_callback_url or None

        client = self._client()
        try:
            created = await client.create_game_order(
                game_code=mapping.external_product_id,
                catalogue_name=catalogue_name,
                player_id=player_id,
                server_id=server_id,
                charname=charname,
                callback_url=callback_url,
                remark=f"yupay:{item.id[:8]}",
                idempotency_key=idempotency_key,
            )
        except G2bError as exc:
            raise FulfillerError(f"g2b game order failed: HTTP {exc.status}") from exc

        if created.status == "completed":
            return FulfillResult(
                outcome="succeeded",
                external_order_id=created.g2b_order_id,
                artifact_kind="topup_receipt",
                artifact=_game_artifact(
                    mapping=mapping,
                    item=item,
                    g2b_order_id=created.g2b_order_id,
                    message=None,
                ),
                error=None,
                extra_metadata={
                    "supplier": "g2b",
                    "kind": "game",
                    "player_id_hash": _hash_short(player_id),
                },
            )
        if created.status == "failed":
            return FulfillResult(
                outcome="failed",
                external_order_id=created.g2b_order_id,
                artifact_kind=None,
                artifact=None,
                error="g2b returned failed status on create",
                extra_metadata={"supplier": "g2b", "kind": "game"},
            )
        # pending / processing — the webhook will finish it later. The
        # standalone polling actor in apps/worker/.../g2b_polling.py is
        # available as a safety net, but auto-scheduling it from the API
        # process requires a shared Dramatiq broker handle which is wired
        # up in a follow-up sprint; for now an admin can hit the
        # ``/admin/fulfillment/tasks/{id}/retry`` route to reconcile a
        # stuck task by hand.
        return FulfillResult(
            outcome="in_progress",
            external_order_id=created.g2b_order_id,
            artifact_kind=None,
            artifact=None,
            error=None,
            extra_metadata={
                "supplier": "g2b",
                "kind": "game",
                "player_id_hash": _hash_short(player_id),
            },
        )

    # ---------- helpers ----------

    async def _load_mapping(self, db: AsyncSession, sku_id: str) -> SkuSupplierMapping:
        row = await get_mapping(db, sku_id=sku_id, supplier_slug="g2b")
        if row is None or not row.is_active:
            raise FulfillerError(
                "no active g2b mapping for SKU — set one via /admin/integrations/mappings"
            )
        return row

    # ---------- diagnostic ----------

    async def health(self) -> dict[str, Any]:
        """Lightweight probe used by ``/admin/integrations/g2b/health``.

        Returns ``{"available": True, "balance": ..., "username": ...}`` on
        success; ``{"available": False, "reason": ...}`` otherwise. Never
        raises — the admin UI shouldn't fall over on G2B outages.
        """
        if not self.available:
            return {"available": False, "reason": "G2B_API_KEY is not configured"}
        try:
            payload = await self._client().get_me()
        except G2bError as exc:
            return {"available": False, "reason": f"g2b HTTP {exc.status}"}
        except Exception as exc:  # noqa: BLE001 -- health probe must not crash
            return {"available": False, "reason": str(exc)[:200]}
        return {
            "available": True,
            "balance": payload.get("balance"),
            "username": payload.get("username"),
        }


def _voucher_artifact(
    *,
    mapping: SkuSupplierMapping,
    item: OrderItem,
    codes: list[str],
    g2b_order_id: str,
) -> dict[str, Any]:
    """Customer-facing voucher artifact. Contains the actual codes."""
    # ``code`` is the first one for the common 1-unit case; ``codes`` lists
    # everything so the miniapp can show all of them for multi-quantity buys.
    primary = codes[0] if codes else ""
    return {
        "code": primary,
        "codes": list(codes),
        "sku_id": item.sku_id,
        "qty": item.qty,
        "source": "g2b",
        "external_order_id": g2b_order_id,
        "external_product_id": mapping.external_product_id,
    }


def _game_artifact(
    *,
    mapping: SkuSupplierMapping,
    item: OrderItem,
    g2b_order_id: str,
    message: str | None,
) -> dict[str, Any]:
    """Customer-facing game top-up receipt. No codes — the credit goes
    straight to the player's in-game account on G2B's side."""
    return {
        "sku_id": item.sku_id,
        "qty": item.qty,
        "source": "g2b",
        "external_order_id": g2b_order_id,
        "external_product_id": mapping.external_product_id,
        "catalogue_name": mapping.external_variant_id,
        "message": message,
    }


def _hash_short(value: str) -> str:
    """Stable, opaque hash for logging player ids. 12 hex chars is enough
    to identify a unique player in a single audit feed without exposing
    the upstream id."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _stringify_or_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


__all__ = ["G2bFulfiller"]
