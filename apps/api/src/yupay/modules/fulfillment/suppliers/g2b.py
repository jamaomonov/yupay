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

import json
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.core.logging import hash_short
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
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

#: What a terminal G2B failure means for our money — and why it is the weakest
#: of the three adapters' answers in this package.
#:
#: **No endpoint this adapter calls carries a refund field.** Their
#: documentation says a FAILED order auto-refunds the balance (see
#: :meth:`G2bFulfiller.cancel`, which has relied on that sentence since the
#: integration landed), and the client's own comment reads a 410 on the
#: delivery poll as "refunded / cancelled". All of that is a promise; no
#: response we parse ever tells us the money came back.
#:
#: Compare the other two. ``gengine`` reads ``is_refunded`` — a real field, on
#: every order. ``waxpeer`` splits ``canceled`` from ``error`` on refund
#: behaviour it has watched and written down. Answering ``RETURNED`` here
#: would flatten three very different confidences into one word, and M3b acts
#: on that word: it would credit a reseller's deposit on the strength of
#: someone else's paperwork. ``UNKNOWN`` is what the third value is for — no
#: automatic refund, and a human who can go and look.
#:
#: **One narrow exception exists, and it is a different constant.** M3c graded
#: a single *create* rejection — an invalid player id — as ``RETURNED``, on
#: the owner's ruling (2026-09-09) that G2B does not debit us for it: see
#: :data:`_REJECTED_UNBILLED` and :func:`_is_an_unbilled_player_rejection`,
#: which matches their exact envelope and their exact message, and nothing
#: looser. Every failure *this* constant covers still answers ``UNKNOWN``,
#: and so does every create rejection that predicate does not recognise.
#:
#: **Promoting this is cheaper than it sounds, and does not need G2B's help:
#: they already publish the evidence and we simply do not fetch it.**
#: ``docs/g2b-intergation.md`` §7 documents ``GET /v1/games/orders``, whose
#: per-order fields include ``is_refunded`` — the same field ``gengine`` reads
#: — and §8 documents ``GET /v1/transactions``, typed balance movements
#: (``add_balance`` = "пополнение или возврат", ``charge_balance`` with
#: ``balance_before`` / ``balance_after``), which is the reconciled balance
#: history this note used to name as a distant goal. Neither is wired up. A
#: client method plus a poll would move this adapter's ``UNKNOWN`` bucket —
#: whose size nobody has counted — to a field we read; until one exists, this stays
#: ``UNKNOWN``, because what is documented and what we observe are not the
#: same thing — which is the whole point of this constant.
_FAILURE_MONEY_OUTCOME = MoneyOutcome.UNKNOWN

#: A refusal that happens **before** any call goes out to G2B — a missing key,
#: an unmapped SKU, a malformed order line. Nothing was ordered, so nothing was
#: charged, and our balance is provably whole.
_NEVER_SENT = MoneyOutcome.RETURNED

#: A refusal from a call that may already have placed (and been billed for) an
#: order. ``G2bError`` covers every non-retryable status the client gives up
#: on, so "they refused" and "they charged us and then errored" are not
#: distinguishable from here — **except** for the one shape below.
_MAY_HAVE_SPENT = MoneyOutcome.UNKNOWN

#: A create G2B refused **without billing us**, recognised from their own
#: rejection (see :func:`_is_an_unbilled_player_rejection`). One shape
#: qualifies: an invalid player id.
#:
#: This is a **fourth kind of evidence**, and it is worth naming because the
#: other three are graded in ADR-0071's decision 3. It is not a field we read
#: (``gengine``'s ``is_refunded``), not behaviour we have watched and written
#: down (``waxpeer``), and not our own control flow (:data:`_NEVER_SENT`,
#: where no call went out at all). It is **their error string, plus the
#: owner's knowledge that this particular refusal is not billed** — a ruling
#: made on 2026-09-09 after the shape was observed on production. Weaker than
#: a field, because the string is not a statement about money and could be
#: reused for something that *is* billed; stronger than the documentation
#: sentence :data:`_FAILURE_MONEY_OUTCOME` rests on, because we have seen this
#: exact response and been told what it costs. What would promote it to a
#: field is the same read :data:`_FAILURE_MONEY_OUTCOME`'s note names.
_REJECTED_UNBILLED = MoneyOutcome.RETURNED

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.orders.models import Order, OrderItem


class G2bFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for G2Bulk."""

    supplier = "g2b"

    def __init__(self, client: G2bClient | None = None) -> None:
        # ``client`` injectable for tests. In prod a fresh wrapper is built
        # from settings on each call so a hot-reloaded key is picked up — the
        # wrapper is cheap; the connection pool underneath it is shared
        # process-wide (see ``g2b_client._pool``), so this costs no handshake.
        self._client_override = client

    def client_for_reads(self) -> G2bClient:
        """A client for read-only catalogue calls made outside fulfilment.

        The stock refresh lives in ``integrations`` but the credentials and
        retry policy belong here, so it borrows a client instead of building a
        second one from settings and drifting apart from this adapter.
        """
        return self._client()

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
            raise FulfillerError("G2B_API_KEY is not configured", money_outcome=_NEVER_SENT)
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
            # Both guards answer UNKNOWN rather than "nothing was sent": a task
            # only reaches ``check_status`` after an order went out, so a key
            # that went missing since, or an id we failed to persist, says
            # nothing about the money that order cost.
            raise FulfillerError("G2B_API_KEY is not configured", money_outcome=_MAY_HAVE_SPENT)
        if not task.external_order_id:
            raise FulfillerError("task has no G2B order id to check", money_outcome=_MAY_HAVE_SPENT)

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
                    money_outcome=_FAILURE_MONEY_OUTCOME,
                )
            if result.status == "completed" and result.delivery_items:
                return FulfillStatus(
                    outcome="succeeded",
                    artifact_kind="voucher_code",
                    artifact=_voucher_artifact(
                        mapping=mapping,
                        item=item,
                        codes=result.delivery_items,
                        g2b_order_id=task.external_order_id,
                    ),
                    error=None,
                    money_outcome=None,
                )
            # "completed" with zero codes stays in_progress (see fulfill's guard):
            # never deliver an empty voucher; let the poller keep trying.
            return FulfillStatus(
                outcome="in_progress",
                artifact_kind=None,
                artifact=None,
                error=None,
                money_outcome=None,
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
                money_outcome=None,
            )
        if status.status == "failed":
            return FulfillStatus(
                outcome="failed",
                artifact_kind=None,
                artifact=None,
                error=status.message or "g2b reported failure",
                money_outcome=_FAILURE_MONEY_OUTCOME,
            )
        return FulfillStatus(
            outcome="in_progress",
            artifact_kind=None,
            artifact=None,
            error=None,
            money_outcome=None,
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
        #
        # That "their docs say" is the whole of our evidence about G2B money
        # everywhere but one place: the single *create* rejection the owner
        # graded by hand in M3c (``_REJECTED_UNBILLED``). Nothing on this path
        # is covered by it, which is why ``_FAILURE_MONEY_OUTCOME`` is UNKNOWN
        # — read its note before treating a failed G2B order as refunded, and
        # for the two endpoints that would turn the promise into an
        # observation.
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
            raise FulfillerError(
                f"g2b purchase failed: HTTP {exc.status}: {_err_body(exc)}",
                money_outcome=_MAY_HAVE_SPENT,
            ) from exc

        if result.status == "completed" and result.delivery_items:
            return FulfillResult(
                outcome="succeeded",
                external_order_id=result.g2b_order_id,
                artifact_kind="voucher_code",
                artifact=_voucher_artifact(
                    mapping=mapping,
                    item=item,
                    codes=result.delivery_items,
                    g2b_order_id=result.g2b_order_id,
                ),
                error=None,
                extra_metadata={
                    "supplier": "g2b",
                    "kind": "voucher",
                    "delivery_count": len(result.delivery_items),
                },
                money_outcome=None,
            )
        if result.status == "completed":
            # "completed" but zero codes: never deliver an empty voucher — that
            # marks the order fulfilled with ``code=""`` and no refund ever fires.
            # Keep it in_progress so the poller retries and ops can see it.
            return FulfillResult(
                outcome="in_progress",
                external_order_id=result.g2b_order_id,
                artifact_kind=None,
                artifact=None,
                error=None,
                extra_metadata={
                    "supplier": "g2b",
                    "kind": "voucher",
                    "completed_without_codes": True,
                },
                money_outcome=None,
            )
        if result.status == "pending":
            return FulfillResult(
                outcome="in_progress",
                external_order_id=result.g2b_order_id,
                artifact_kind=None,
                artifact=None,
                error=None,
                extra_metadata={"supplier": "g2b", "kind": "voucher"},
                money_outcome=None,
            )
        return FulfillResult(
            outcome="failed",
            external_order_id=result.g2b_order_id,
            artifact_kind=None,
            artifact=None,
            error="g2b returned failed status",
            extra_metadata={"supplier": "g2b", "kind": "voucher"},
            money_outcome=_FAILURE_MONEY_OUTCOME,
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
            raise FulfillerError(
                "order item is missing fulfillment_data.player_id required by g2b",
                money_outcome=_NEVER_SENT,
            )
        # The product's server/zone field is keyed ``server`` in its form schema
        # (e.g. Genshin: os_euro), which is what the order stores. Older data /
        # tests may use ``server_id`` — accept both. Reading the wrong key drops
        # the server and G2B rejects the game order with HTTP 400.
        server_id = _stringify_or_none(
            fulfillment_data.get("server") or fulfillment_data.get("server_id")
        )
        charname = _stringify_or_none(fulfillment_data.get("charname"))
        catalogue_name = mapping.external_variant_id
        if not catalogue_name:
            raise FulfillerError(
                "g2b mapping is missing external_variant_id for kind=game",
                money_outcome=_NEVER_SENT,
            )

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
            # One rejection is known to cost us nothing and refunds a
            # reseller automatically; **everything else falls back to
            # ``_MAY_HAVE_SPENT``**, which parks the order for a human. That
            # fallback is the behaviour, not a gap — see
            # ``_is_an_unbilled_player_rejection`` for why it is narrow.
            raise FulfillerError(
                f"g2b game order failed: HTTP {exc.status}: {_err_body(exc)}",
                money_outcome=(
                    _REJECTED_UNBILLED if _is_an_unbilled_player_rejection(exc) else _MAY_HAVE_SPENT
                ),
            ) from exc

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
                    "player_id_hash": hash_short(player_id),
                },
                money_outcome=None,
            )
        if created.status == "failed":
            return FulfillResult(
                outcome="failed",
                external_order_id=created.g2b_order_id,
                artifact_kind=None,
                artifact=None,
                error="g2b returned failed status on create",
                extra_metadata={"supplier": "g2b", "kind": "game"},
                money_outcome=_FAILURE_MONEY_OUTCOME,
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
                "player_id_hash": hash_short(player_id),
            },
            money_outcome=None,
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
                "no active g2b mapping for SKU — set one via /admin/integrations/mappings",
                money_outcome=_NEVER_SENT,
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


def _stringify_or_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _err_body(exc: G2bError) -> str:
    """G2B's response body, single-lined and truncated — surfaced into the
    ``FulfillerError`` so the admin inbox / ``last_error`` shows *why* G2B
    rejected the call (a bare "HTTP 400" is undiagnosable). No PII: G2B error
    bodies describe the request shape, not the buyer."""
    body = " ".join(str(exc.body or "").split())
    return body[:200] if body else "(no body)"


_LOW_BALANCE_HINTS = ("insufficient", "balance", "funds", "not enough")


def _looks_like_low_balance(exc: G2bError) -> bool:
    """Heuristic: does this 4xx look like a "topped-up wallet needed" error?

    G2B doesn't document a dedicated error code for this case, so we
    inspect the response body. The hints are deliberately loose — a
    false positive demotes a hard failure to a low-balance retryable
    state, which is the safer mistake (admin sees both kinds in the
    same queue either way).

    Since M3c that mistake has a second, still-safe consequence, stated here
    so the looseness stays a decision: this branch is checked **first**, so a
    body that would also match :func:`_is_an_unbilled_player_rejection` stalls
    instead of auto-refunding a reseller. Withholding a refund is the
    direction this package errs in everywhere — an order that stalls is still
    in flight and still settleable by hand.
    """
    body = (exc.body or "").lower()
    if exc.status not in {400, 402, 403, 422}:
        return False
    return any(hint in body for hint in _LOW_BALANCE_HINTS)


#: G2B's envelope for the one rejection we know costs us nothing, as observed
#: on production 2026-09-09::
#:
#:     HTTP 400 {"message":"Invalid player ID. Please check and try again.","success":false}
#:
#: The message is compared **whole**, normalised, not matched as a prefix.
#: An earlier version anchored a pattern at the start, which accepted any
#: message *beginning* with the phrase — including
#: ``"Invalid player ID; the order was created and charged"``, which is a
#: refusal we have been **billed** for, wearing the words of one we have not.
#: That is the single shape in which a future G2B string could turn this into
#: a refund of money we spent, so the tolerance is for **formatting** (case,
#: collapsed whitespace) and never for wording.
#:
#: The cost is stated rather than hidden: if G2B rewords this message at all,
#: the match stops, the order parks, and an operator settles it by hand —
#: which is exactly the behaviour that existed before M3c. Losing the
#: automatic refund is the cheap failure; refunding a billed refusal is not.
_INVALID_PLAYER_STATUS = 400
_INVALID_PLAYER_MESSAGE = "invalid player id. please check and try again."


def _is_an_unbilled_player_rejection(exc: G2bError) -> bool:
    """Is this the one create refusal G2B makes without debiting our balance?

    **Read this next to** :func:`_looks_like_low_balance`, which is
    deliberately loose, and understand that the two are opposite on purpose —
    an unexplained difference between neighbours invites someone to "fix" one
    of them. Its false positive demotes a hard failure to a retryable stall
    and an admin sees both kinds in the same queue anyway. **This one's false
    positive pays a merchant back for goods we may have bought**, on our own
    money, silently, with no operator path to undo it (ADR-0071 decision 5).
    So it is as narrow as the evidence: the status, their envelope, and the
    **whole** message — the owner's ruling covers *this* rejection, and we
    know nothing about a variant of it.

    A rejection this does not recognise is not a gap — the caller keeps
    answering :data:`_MAY_HAVE_SPENT`, which parks the order and fetches a
    human. Falling back to the safe answer **is** the design; widening this
    predicate to cover a refusal nobody has graded is how that design is lost.

    Args:
        exc: The non-retryable error the client raised for a create call.

    Returns:
        ``True`` only for a 400 carrying G2B's own ``{"success": false,
        "message": ...}`` body whose message, normalised, is exactly
        :data:`_INVALID_PLAYER_MESSAGE`.
    """
    if exc.status != _INVALID_PLAYER_STATUS:
        return False
    try:
        body = json.loads(exc.body)
    except (json.JSONDecodeError, TypeError):
        # Not their JSON at all — an HTML error page, a proxy, a truncated
        # body. Whatever rejected us, it was not G2B saying this.
        return False
    if not isinstance(body, dict) or body.get("success") is not False:
        return False
    message = body.get("message")
    if not isinstance(message, str):
        return False
    return " ".join(message.split()).lower() == _INVALID_PLAYER_MESSAGE


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
        # Deliberately unclassified: this is not a terminal failure. The order
        # stays in flight, an admin tops the supplier up, and nothing has
        # happened to the money yet. M3b Task 4 owns making that visible.
        money_outcome=None,
    )


__all__ = ["G2bFulfiller"]
