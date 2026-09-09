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

from decimal import ROUND_HALF_UP, Decimal
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
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineClient,
    GEngineError,
    GEngineOrder,
    GEngineShopOrder,
    GEngineUnavailableError,
)
from yupay.modules.fulfillment.suppliers.gengine_gifts import fulfill_gift, gift_status

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
    # Telegram credits a @username rather than a numeric id, but it travels in
    # the same `Account` slot.
    "username": "Account",
    "telegram_username": "Account",
}

#: Order statuses that mean the sale is finished, one way or another.
_DELIVERED = "shipped"
_CUSTOMER_FAULT = {"invalid_account", "invalid_amount"}
_DEAD = {"cancelled"}

#: A refusal raised **before** any call goes out, or from a call that cannot
#: spend: a missing key, an unmapped SKU, a malformed line — and every failure
#: of ``create``, because a G-Engine order is created *unpaid*. That last one
#: is not an inference about their refund policy; it is the state machine this
#: module is built on (see the module docstring): only ``pay`` moves money, and
#: a create that never happened has nothing to pay for.
_NOTHING_LEFT_OUR_BALANCE = MoneyOutcome.RETURNED

#: ``extra_metadata`` key marking that we have decided to pay for this task —
#: **written and committed by a call that does not pay, one tick before the one
#: that does.** It is an intent log, and the ordering is the entire point.
#:
#: Why it exists at all: a pay that returns 200 leaves the order ``processing``,
#: which is ``in_progress``, which records no money outcome. A later poll seeing
#: ``invalid_account`` would then answer ``RETURNED`` with nothing to refuse it,
#: and M3b would refund a top-up we paid for. Asking "did *this* call pay?" does
#: not help: on the poll path — this adapter's normal path — that is False for
#: every status but ``verified``.
#:
#: Why the two-phase shape rather than writing it inside the paying tick: a
#: breadcrumb whose durability depends on the transaction that may fail is not
#: a breadcrumb. The tick that pays must still survive ``_record_attempt``, the
#: metadata merge, ``_try_settle_order``'s blocking ``FOR UPDATE`` on the order
#: row, a flush and a COMMIT — and the poll path has no crash net, so any abort
#: in that window rolls the key back and the next tick is unarmed. So
#: :meth:`GEngineFulfiller._advance` **refuses to pay a ``verified`` order it has
#: no committed intent for**: it records the intent, returns ``in_progress``, and
#: the saga commits it in a transaction that spent nothing. The next tick (60 s,
#: ``gengine_reconcile``) sees the key already on the row and pays. If *that*
#: tick aborts, the key is already committed and cannot be rolled back with it.
#:
#: The cost is one extra 60-second tick before any G-Engine order is paid. The
#: sweep exists because a ``verified`` order once sat for nine hours; a minute
#: against that, to never refund a top-up we bought, is the trade taken here.
PAY_REQUESTED_KEY = "gengine_pay_requested"

#: A failure on, or after, the one call that spends. ``GEngineError`` is raised
#: for **every** status ≥ 400, a 500 included, so "they refused to charge us"
#: and "they charged us and then fell over" arrive here as the same exception.
_PAY_MAY_HAVE_LANDED = MoneyOutcome.UNKNOWN


def _recharge_money_outcome(order: GEngineOrder, *, pay_may_have_landed: bool) -> MoneyOutcome:
    """What a terminal recharge failure means for our money.

    Two answers rest on things we actually know, and the third admits it does
    not:

    - ``is_refunded`` is a **real field** on their order — the strongest
      evidence any adapter in this package has, and the same field that has
      driven the ``supplier_refunded`` metadata key since this adapter landed.
    - a ``_CUSTOMER_FAULT`` status on a task **no pay request has ever gone out
      for**. Their flow puts verification strictly before payment, but that
      ordering is their documentation, and a mapping that trusted it would rest
      on exactly the evidence this package refuses to act on for G2B — **a
      vendor's document**, still refused there. M3c's single G2B exception is
      not a counter-example: it rests on an observed error string plus the
      owner's ruling that it is not billed, never on a document. So the
      claim is not inferred, it is **checked**, and checked across the whole
      task rather than one call: ``pay_may_have_landed`` is this invocation's
      own pay request OR :data:`PAY_REQUESTED_KEY` left on the task by an
      earlier one. Checking only the current call would have added nothing on
      the poll path — every status but ``verified`` skips the pay branch, and
      the poll path is this adapter's normal path — so a pay that returned 200
      and left the order ``processing`` would have been forgotten by the next
      poll.
    - anything else (a cancellation with no refund, a refusal mid-payment) is
      :attr:`MoneyOutcome.UNKNOWN`. The flag says no refund landed; nothing
      says the money ever left. This is exactly the case the adapter's own
      comment has always described as "needs the money chased" — and chasing
      is a human, not an automatic credit.

    Args:
        order: The order as G-Engine last reported it.
        pay_may_have_landed: Whether a pay request has gone out for this task,
            by this call or an earlier one. A refusal *from* that call is
            undecided, not free — see :data:`_PAY_MAY_HAVE_LANDED`.
    """
    if order.is_refunded:
        # A field, and it outranks everything else here: money that came back
        # came back whatever was spent to send it.
        return MoneyOutcome.RETURNED
    if order.status in _CUSTOMER_FAULT and not pay_may_have_landed:
        return _NOTHING_LEFT_OUR_BALANCE
    return MoneyOutcome.UNKNOWN


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

    def client_for_reads(self) -> GEngineClient:
        """A client for read-only catalogue calls made outside fulfilment.

        The stock refresh lives in ``integrations`` but the credentials and
        retry policy belong here, so it borrows a client instead of building a
        second one from settings and drifting apart from this adapter.
        """
        return self._client()

    @property
    def available(self) -> bool:
        return bool(get_settings().gengine_api_key)

    # ---------- protocol ----------

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        if not self.available:
            raise FulfillerError(
                "GENGINE_API_KEY is not configured", money_outcome=_NOTHING_LEFT_OUR_BALANCE
            )

        mapping = await _mapping_for(db, sku_id=item.sku_id)
        if mapping.kind == "voucher":
            return await self._fulfill_shop(mapping=mapping, item=item)
        if mapping.kind == "gift":
            return await fulfill_gift(self._client(), item=item, order_created_at=order.created_at)

        service_id = _int_or_fail(mapping.external_product_id, field="external_product_id")
        denomination_id = (
            _int_or_fail(mapping.external_variant_id, field="external_variant_id")
            if mapping.external_variant_id
            else None
        )
        params = _params_from(item)
        if not params:
            raise FulfillerError(
                "no G-Engine parameters could be built from fulfillment_data",
                money_outcome=_NOTHING_LEFT_OUR_BALANCE,
            )

        if denomination_id is None:
            # An `unfixed` service (Telegram Stars, and anything else priced by
            # amount) has no denominations to choose from — it wants a
            # `Quantity` instead, and rejects the order without one.
            #
            # Where that number comes from depends on how the SKU is sold. A
            # package SKU carries it on the mapping. A variable-amount SKU is
            # the customer's own figure, and it has to be re-derived from the
            # money actually charged rather than trusted from the form —
            # checkout snapped it to a whole unit, so this reverses exactly
            # that and cannot drift from what was paid.
            params["Quantity"] = str(await _quantity_for(db, item=item, mapping=mapping))

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
                # Creating costs nothing but a reservation — only ``pay``
                # spends — so however this create ended, our balance is whole.
                raise FulfillerError(str(exc), money_outcome=_NOTHING_LEFT_OUR_BALANCE) from exc
            created = recovered
        except GEngineUnavailableError as exc:
            raise FulfillerError(str(exc), money_outcome=_NOTHING_LEFT_OUR_BALANCE) from exc

        return await self._advance(created, first_call=True)

    async def check_status(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- the task carries the supplier id
        task: FulfillmentTask,
    ) -> FulfillStatus:
        if str(task.extra_metadata.get("gengine_kind") or "") == "gift":
            # Before the id-less early-return below: an id-less gift task
            # still has work to do (adopt an ambiguous create, or park it).
            return await gift_status(self._client(), task=task)
        if not task.external_order_id:
            return FulfillStatus(
                outcome="in_progress",
                artifact_kind=None,
                artifact=None,
                error=None,
                money_outcome=None,
            )
        if str(task.extra_metadata.get("gengine_kind") or "") == "voucher":
            return await self._shop_status(task)

        try:
            order = await self._client().get_recharge_order(int(task.external_order_id))
        except (GEngineError, GEngineUnavailableError) as exc:
            # A read we could not complete says nothing either way. (This one
            # does not end the task — ``process_webhook_update`` records the
            # attempt and lets the sweep retry — but it answers regardless, so
            # no exit in this module is left without a fact behind it.)
            raise FulfillerError(str(exc), money_outcome=MoneyOutcome.UNKNOWN) from exc

        result = await self._advance(
            order,
            first_call=False,
            paid_before=bool(task.extra_metadata.get(PAY_REQUESTED_KEY)),
        )
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
        # nothing about what became of that money. ``_apply_cancel``
        # records the refusal and cancels locally, so the value is unread
        # today — see :class:`FulfillerNotIntegratedError` for why a stub
        # answers RETURNED here and an integrated adapter does not.
        raise FulfillerNotIntegratedError(
            "g-engine exposes no cancel endpoint", money_outcome=MoneyOutcome.UNKNOWN
        )

    # ---------- shop: gift codes and keys ----------

    async def _fulfill_shop(self, *, mapping: Any, item: OrderItem) -> FulfillResult:
        """Buy activation codes.

        Two calls, and the order matters. Reserving costs nothing but stock,
        so a create whose response is lost leaves an unpaid reservation rather
        than a code we paid for and cannot find. Only the pay step spends, and
        by then we hold the order id — which is what lets the poller finish a
        sale this call could not.

        Unlike ``/recharge``, the shop API accepts no client-supplied id, so
        that ordering *is* the idempotency story rather than a nicety.
        """
        denomination_id = _int_or_fail(
            mapping.external_variant_id or mapping.external_product_id,
            field="external_variant_id",
        )
        client = self._client()
        try:
            reserved = await client.create_shop_order(
                denomination_id=denomination_id, quantity=item.qty
            )
        except (GEngineError, GEngineUnavailableError) as exc:
            # Reserving costs stock, not money — this method's docstring is
            # built on that ordering. Nothing was paid for.
            raise FulfillerError(str(exc), money_outcome=_NOTHING_LEFT_OUR_BALANCE) from exc

        try:
            paid = await client.pay_shop_order(reserved.id)
        except GEngineError as exc:
            return _shop_failed(reserved, f"payment refused: {exc}", money=_PAY_MAY_HAVE_LANDED)
        except GEngineUnavailableError as exc:
            # Undecided upstream. The reservation exists and we know its id, so
            # the poller can settle it — failing here would abandon a sale that
            # may already have gone through.
            log.warning("gengine.shop_pay_unavailable", order_id=reserved.id, error=str(exc))
            return _shop_in_progress(reserved)

        return _shop_result(paid, mapping=mapping, item=item)

    async def _shop_status(self, task: FulfillmentTask) -> FulfillStatus:
        client = self._client()
        try:
            order = await client.get_shop_order(int(task.external_order_id or 0))
            if order.status == "pending":
                # Reserved but never paid — the window this design exists to
                # make cheap. Settle it now.
                order = await client.pay_shop_order(order.id)
        except (GEngineError, GEngineUnavailableError) as exc:
            # This branch may have been mid-``pay_shop_order`` when it broke.
            raise FulfillerError(str(exc), money_outcome=_PAY_MAY_HAVE_LANDED) from exc

        result = _shop_result(order, mapping=None, item=None)
        return FulfillStatus(
            outcome=result.outcome,
            artifact_kind=result.artifact_kind,
            artifact=result.artifact,
            error=result.error,
            extra_metadata=result.extra_metadata,
            money_outcome=result.money_outcome,
        )

    # ---------- state machine ----------

    async def _advance(
        self, order: GEngineOrder, *, first_call: bool, paid_before: bool = False
    ) -> FulfillResult:
        """Move the order one step, and report where it landed.

        ``verified`` is the only state that opens payment, so this pays as soon
        as it sees one — whether that is on the first call or a later poll.

        Args:
            order: The order as G-Engine last reported it.
            first_call: Whether this is the create rather than a poll; only
                changes a log line.
            paid_before: Whether an earlier call already **committed** the
                intent to pay for this task, read from
                :data:`PAY_REQUESTED_KEY`. A ``verified`` order is only paid
                when this is true; see that constant for why the write and the
                spend are deliberately in different transactions. Every exit
                below re-emits the key once it is set, so it also survives the
                ``in_progress`` results that record no money outcome at all.
        """
        pay_may_have_landed = paid_before
        if order.status == "verified":
            pay_may_have_landed = True
            if not paid_before:
                # Phase one: bank the intent and spend nothing. The caller
                # commits this; the next tick finds the key and pays. Paying
                # here instead would put the record of the spend in the same
                # transaction as the spend, which is the failure this whole
                # mechanism exists to survive.
                log.info("gengine.pay_intent_recorded", order_id=order.id)
                return _in_progress(order, pay_may_have_landed=True)
            try:
                order = await self._client().pay_recharge_order(order.id)
            except GEngineError as exc:
                # Paying is where our money leaves. A refusal here is worth
                # surfacing verbatim rather than as a generic failure.
                return _failed(order, f"payment refused: {exc}", pay_may_have_landed=True)
            except GEngineUnavailableError as exc:
                # Undecided upstream: stay in progress so the poller retries
                # instead of failing a sale that may yet complete.
                log.warning("gengine.pay_unavailable", order_id=order.id, error=str(exc))
                return _in_progress(order, pay_may_have_landed=True)

        return self._settle(order, first_call=first_call, pay_may_have_landed=pay_may_have_landed)

    def _settle(
        self, order: GEngineOrder, *, first_call: bool, pay_may_have_landed: bool
    ) -> FulfillResult:
        """Read a post-payment order status as an outcome. No calls, no spend."""
        if order.status == _DELIVERED:
            return FulfillResult(
                outcome="succeeded",
                external_order_id=str(order.id),
                artifact_kind="topup_receipt",
                artifact=_receipt(order),
                error=None,
                extra_metadata={
                    "supplier": self.supplier,
                    "gengine_status": order.status,
                    **({PAY_REQUESTED_KEY: True} if pay_may_have_landed else {}),
                },
                money_outcome=None,
            )
        if order.status in _CUSTOMER_FAULT:
            return _failed(order, order.status, pay_may_have_landed=pay_may_have_landed)
        if order.status in _DEAD:
            return _failed(order, "cancelled by supplier", pay_may_have_landed=pay_may_have_landed)

        if first_call:
            log.info("gengine.order_created", order_id=order.id, status=order.status)
        return _in_progress(order, pay_may_have_landed=pay_may_have_landed)

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


async def _quantity_for(db: AsyncSession, *, item: OrderItem, mapping: Any) -> int:
    """How many units to buy for one order line of an amount-priced service.

    Two sources of truth coexist here (dual-read), and the variable-amount
    one is checked *first*:

    - A ``variable_amount`` + ``units_per_usd`` line (Steam, and the
      pre-seed Stars free-amount SKU) re-derives its count from the money
      actually charged — checkout snapped it to a whole unit, so this
      reverses exactly that and cannot drift from what was paid. This
      reverse-engineer path is for any such SKU, not Stars-specific; do
      not delete it after the Stars seed.
    - Everything else is ``item.qty * mapping.quantity``. ``item.qty`` is
      *not* pinned to 1 for a package SKU — checkout allows up to
      ``DEFAULT_QTY_MAX`` packs of an ordinary SKU in one line — so this is
      genuinely "packs bought × units per pack" for those. After the Stars
      seed, the Stars mapping is ``quantity=1`` so the product collapses
      to ``item.qty`` (the customer's star count). Other products keep
      their pack ``mapping.quantity``.
    """
    from sqlalchemy import select

    from yupay.modules.catalog.models import Sku

    sku = (await db.execute(select(Sku).where(Sku.id == item.sku_id))).scalar_one_or_none()
    if sku is not None and sku.variable_amount and sku.units_per_usd:
        units = (item.unit_price_usd * sku.units_per_usd).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        if units > 0:
            return int(units)
        raise FulfillerError(
            f"variable amount {item.unit_price_usd} resolves to no units — refusing to order",
            money_outcome=_NOTHING_LEFT_OUR_BALANCE,
        )
    qty = int(item.qty) * int(mapping.quantity)
    # Both factors carry a DB `CHECK (... > 0)` (ck_order_items_qty_positive,
    # ck_sku_supplier_mapping_quantity_positive), so this is belt-and-suspenders
    # for a caller that hands in a non-persisted or duck-typed `item`/`mapping`
    # rather than a reachable state for a real order.
    if qty <= 0:
        raise FulfillerError(
            "quantity resolves to zero — refusing to order", money_outcome=_NOTHING_LEFT_OUR_BALANCE
        )
    return qty


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
        raise FulfillerError(
            "no active g-engine mapping for this SKU", money_outcome=_NOTHING_LEFT_OUR_BALANCE
        )
    return row


def _int_or_fail(raw: str | None, *, field: str) -> int:
    """G-Engine addresses services and denominations by integer id, and the
    mapping stores them as text. A non-numeric value is a misconfiguration
    worth naming, not a stack trace from ``int()``."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise FulfillerError(
            f"g-engine mapping {field} must be numeric, got {raw!r}",
            money_outcome=_NOTHING_LEFT_OUR_BALANCE,
        ) from exc


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


def _shop_meta(order: GEngineShopOrder) -> dict[str, Any]:
    # `gengine_kind` is what tells `check_status` to poll the shop endpoints
    # rather than the recharge ones — the task itself carries no mapping.
    return {
        "supplier": "gengine",
        "gengine_kind": "voucher",
        "gengine_status": order.status,
    }


def _shop_result(order: GEngineShopOrder, *, mapping: Any, item: OrderItem | None) -> FulfillResult:
    """Interpret a shop order.

    A ``shipped``/``paid`` order with **no codes yet** stays in progress: never
    hand a customer an empty voucher, the same rule the G2B adapter follows.
    """
    if order.status == "canceled":
        return _shop_failed(
            order,
            "cancelled by supplier",
            money=MoneyOutcome.RETURNED if order.is_refunded else MoneyOutcome.UNKNOWN,
        )
    if not order.codes:
        return _shop_in_progress(order)
    return FulfillResult(
        outcome="succeeded",
        external_order_id=str(order.id),
        artifact_kind="voucher_code",
        artifact={
            # `code` is the single-unit case; `codes` carries everything so a
            # multi-quantity buy shows all of them.
            "code": order.codes[0],
            "codes": list(order.codes),
            "sku_id": getattr(item, "sku_id", None),
            "qty": getattr(item, "qty", len(order.codes)),
            "source": "gengine",
            "external_order_id": str(order.id),
            "external_product_id": getattr(mapping, "external_product_id", None),
        },
        error=None,
        extra_metadata=_shop_meta(order),
        money_outcome=None,
    )


def _shop_in_progress(order: GEngineShopOrder) -> FulfillResult:
    """A shop order still moving — including one whose ``pay_shop_order`` call
    ended undecided (see :meth:`GEngineFulfiller._fulfill_shop`).

    **That state is unrecorded, and this path has no intent log**, unlike the
    recharge machine above. It is safe today for one reason and one only: the
    shop branch's single :attr:`MoneyOutcome.RETURNED` is gated on
    ``order.is_refunded``, a field, so no absence-of-spend inference is being
    made that a forgotten pay could falsify. Anyone adding a shop ``RETURNED``
    that rests on "we never got as far as paying" must give this path a
    :data:`PAY_REQUESTED_KEY` of its own first.
    """
    return FulfillResult(
        outcome="in_progress",
        external_order_id=str(order.id),
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata=_shop_meta(order),
        money_outcome=None,
    )


def _shop_failed(order: GEngineShopOrder, error: str, *, money: MoneyOutcome) -> FulfillResult:
    """A dead shop order.

    ``money`` is a parameter rather than a re-derivation because the two
    callers know different things: a supplier-side cancellation can read
    ``is_refunded``, while a refusal on ``pay_shop_order`` happened on the one
    call that spends and cannot.
    """
    return FulfillResult(
        outcome="failed",
        external_order_id=str(order.id),
        artifact_kind=None,
        artifact=None,
        error=error,
        extra_metadata={**_shop_meta(order), "supplier_refunded": order.is_refunded},
        money_outcome=money,
    )


def _in_progress(order: GEngineOrder, *, pay_may_have_landed: bool = False) -> FulfillResult:
    """An order still moving. ``pay_may_have_landed`` is what makes the
    breadcrumb durable: this is the exit a successful pay usually takes, and
    it records no money outcome, so without the key the fact is lost."""
    return FulfillResult(
        outcome="in_progress",
        external_order_id=str(order.id),
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={
            "supplier": "gengine",
            "gengine_status": order.status,
            **({PAY_REQUESTED_KEY: True} if pay_may_have_landed else {}),
        },
        money_outcome=None,
    )


def _failed(order: GEngineOrder, error: str, *, pay_may_have_landed: bool) -> FulfillResult:
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
            # a refund does, and only the flag tells them apart. Kept because
            # the admin inbox and the runbooks read it; ``money_outcome`` below
            # is the typed source of truth M3b acts on.
            "supplier_refunded": order.is_refunded,
            **({PAY_REQUESTED_KEY: True} if pay_may_have_landed else {}),
        },
        money_outcome=_recharge_money_outcome(order, pay_may_have_landed=pay_may_have_landed),
    )


__all__ = ["GEngineFulfiller"]
