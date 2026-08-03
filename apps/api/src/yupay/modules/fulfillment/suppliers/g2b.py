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
from decimal import Decimal, InvalidOperation
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

# Sentinel last_error value the saga keys on to decide that this isn't a
# real fulfilment failure but a "topped-up-supplier-needed" condition.
# Keeping it machine-readable (snake_case, no human prose) lets the
# admin UI badge it without trying to parse free-form error strings.
LOW_BALANCE_ERROR = "supplier_low_balance"

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

        low_balance = await self._check_balance_or_none(
            client=client,
            required_per_unit=item.sku.cost_usdt if item.sku else None,
            qty=qty,
            mapping=mapping,
            kind="voucher",
        )
        if low_balance is not None:
            return low_balance

        try:
            result = await client.purchase_voucher(
                product_id=mapping.external_product_id,
                quantity=qty,
                idempotency_key=idempotency_key,
            )
        except G2bError as exc:
            if _looks_like_low_balance(exc):
                return _low_balance_result(
                    mapping=mapping,
                    kind="voucher",
                    current_balance=None,
                    required=None,
                    source=f"g2b HTTP {exc.status}",
                )
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

        low_balance = await self._check_balance_or_none(
            client=client,
            required_per_unit=item.sku.cost_usdt if item.sku else None,
            qty=max(1, item.qty * mapping.quantity),
            mapping=mapping,
            kind="game",
        )
        if low_balance is not None:
            return low_balance

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
            if _looks_like_low_balance(exc):
                return _low_balance_result(
                    mapping=mapping,
                    kind="game",
                    current_balance=None,
                    required=None,
                    source=f"g2b HTTP {exc.status}",
                )
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
        # pending / processing — the webhook finishes it later (fast path). If
        # the webhook is lost (it fires once, 1 retry, 10s timeout), the
        # ``g2b_reconcile`` scheduler sweep reconciles every in_progress g2b
        # task every 60s via the same ``process_webhook_update`` path, so a
        # stuck task self-heals without any manual action.
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

    async def _check_balance_or_none(
        self,
        *,
        client: G2bClient,
        required_per_unit: Decimal | None,
        qty: int,
        mapping: SkuSupplierMapping,
        kind: str,
    ) -> FulfillResult | None:
        """Pre-flight call to ``GET /v1/getMe``.

        Returns a low-balance ``FulfillResult`` when we already know we
        don't have enough USDT on the supplier side. ``None`` means
        either the balance is fine, or we couldn't price the order
        confidently (no ``cost_usdt`` on the SKU and getMe blew up) —
        in which case we let the actual purchase attempt run and react
        to its 4xx if any.

        Why pre-flight instead of post-mortem: G2B's docs explicitly
        say "перед любой покупкой запрашивать getMe и проверять, что
        balance >= unit_price * quantity". An idempotency-keyed POST
        that 4xx's still counts against the dedupe window, so failing
        early is the cheapest path to a clean retry later.
        """
        if required_per_unit is None or required_per_unit <= 0:
            return None
        try:
            me = await client.get_me()
        except Exception:  # noqa: BLE001 -- pre-flight is best-effort
            return None
        try:
            current = Decimal(str(me.get("balance"))) if me.get("balance") is not None else None
        except (InvalidOperation, ValueError):
            return None
        if current is None:
            return None
        required_total = Decimal(str(required_per_unit)) * Decimal(qty)
        if current >= required_total:
            return None
        return _low_balance_result(
            mapping=mapping,
            kind=kind,
            current_balance=current,
            required=required_total,
            source="g2b.getMe",
        )

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


_LOW_BALANCE_HINTS = ("insufficient", "balance", "funds", "not enough")


def _looks_like_low_balance(exc: G2bError) -> bool:
    """Heuristic: does this 4xx look like a "topped-up wallet needed" error?

    G2B doesn't document a dedicated error code for this case, so we
    inspect the response body. The hints are deliberately loose — a
    false positive demotes a hard failure to a low-balance retryable
    state, which is the safer mistake (admin sees both kinds in the
    same queue either way).
    """
    body = (exc.body or "").lower()
    if exc.status not in {400, 402, 403, 422}:
        return False
    return any(hint in body for hint in _LOW_BALANCE_HINTS)


def _low_balance_result(
    *,
    mapping: SkuSupplierMapping,
    kind: str,
    current_balance: Decimal | None,
    required: Decimal | None,
    source: str,
) -> FulfillResult:
    """Build the ``failed/low_balance`` FulfillResult.

    The saga keys on ``error=LOW_BALANCE_ERROR`` to split this from a
    real failure: ``task.status`` flips to ``failed`` (so admin sees it
    in the inbox), but ``item.fulfillment_state`` stays
    ``in_progress`` (so the customer keeps seeing "в обработке"
    instead of an error).
    """
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE_ERROR,
        extra_metadata={
            "supplier": "g2b",
            "kind": kind,
            "low_balance": True,
            "current_balance": str(current_balance) if current_balance is not None else None,
            "required": str(required) if required is not None else None,
            "external_product_id": mapping.external_product_id,
            "external_variant_id": mapping.external_variant_id,
            "source": source,
        },
    )


__all__ = ["G2bFulfiller"]
