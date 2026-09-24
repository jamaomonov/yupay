"""``Fulfiller`` for FazerCards (api.fzr.cards) game, gift-card and Steam lines.

FazerCards is a **reserve**, like NOVA and for the same reason: nothing routes
there on its own, an operator switches a SKU with ``force_supplier``. What
makes it worth having at all is price — measured against our own catalogue on
2026-09-24, on 38 of the 39 SKUs we buy from NOVA it quotes exactly
``nova_price / 1.02``, and on our real 30-day volume it is about $27/month
cheaper than the best price we already have across g2b, gengine and nova.

Three facts from their API shape this adapter. The first two it shares with
NOVA, which is why almost all of the machinery is shared:

* **The create spends.** Balance is charged immediately, then ``processing``
  until completed or refunded. So a create that failed on or after the call
  leaves both answers open and is :attr:`MoneyOutcome.UNKNOWN`, never
  "returned" — and a create whose *response* was lost is parked for adoption
  rather than failed, because retrying it would buy the thing twice.
* **Their order object is untyped** in their own OpenAPI (``order: {}``). The
  status allow-list in ``panel_grading`` is therefore a guess made from their
  prose, and anything outside it stays ``in_progress``.
* **It is a subscription, and the plan gates the catalogue.** An expired plan
  answers 403 ``subscription_inactive`` on every product route — including
  the ones this adapter calls — so that refusal is given its own sentence
  instead of arriving as an anonymous 403. Our account runs a Gold trial that
  expires 2026-09-29; after that someone has to pay for a plan or every order
  routed here fails.

**Telegram is deliberately not wired up.** Their Stars and Premium endpoints
exist and would fit, but on 2026-09-24 they quoted 0.0152625 per Star against
NOVA's 0.015225 and were dearer on all three Premium terms. Routing Telegram
here would cost us money, so the branch is absent rather than present and
unused.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from yupay.core.clock import now
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
from yupay.modules.fulfillment.suppliers.fzr_client import (
    SUBSCRIPTION_INACTIVE,
    FzrClient,
    FzrError,
    FzrUnavailableError,
)
from yupay.modules.fulfillment.suppliers.panel_adopt import (
    ADOPT_WINDOW_MINUTES,
    AdoptKey,
    find_order,
    key_is_usable,
)
from yupay.modules.fulfillment.suppliers.panel_fields import (
    build_fields,
    field_specs,
    legacy_fields,
)
from yupay.modules.fulfillment.suppliers.panel_grading import (
    _MAY_HAVE_SPENT,
    _NOTHING_SPENT,
    PanelGrader,
    looks_like_low_balance,
    refusal_money,
    shortfall_side,
    without_our_inputs,
)
from yupay.modules.integrations.models import FZR_STEAM_SENTINEL

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.fzr")

SUPPLIER = "fzr"

#: ``SkuSupplierMapping.kind`` for a SKU that hands over a code rather than
#: crediting an account. The catalogue's own word, shared with G2B's voucher
#: mappings — the dispatch below reads it rather than sniffing the category,
#: because a category id says what is being bought and not how it arrives.
_VOUCHER_KIND = "voucher"

STEAM_SENTINEL = FZR_STEAM_SENTINEL

#: Reads their order objects and refusals. See ``panel_grading``.
_GRADE = PanelGrader(SUPPLIER)


def _parked_for_adoption(exc: Exception) -> FulfillResult:
    """A create whose response was lost: in flight, not failed.

    They charge on create, so a transport failure there leaves the money gone
    and the order's existence unknown. Declaring a failure invites a human to
    retry it and buy a second time; declaring success would be a lie. Parking
    says the true thing — we do not know yet — and ``check_status`` goes
    looking (``panel_adopt``).

    Deliberately id-less and deliberately ungraded: ``money_outcome`` stays
    ``None`` because an ``in_progress`` result is not a failure and the saga
    refuses a money verdict on one.
    """
    return FulfillResult(
        outcome="in_progress",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={"supplier": SUPPLIER, "fzr_create_unresolved": str(exc)[:200]},
        money_outcome=None,
    )


def _refusal(exc: FzrError, *, fields: dict[str, str] | None = None) -> FulfillerError:
    """Their refusal as a terminal failure, with the money question answered.

    A lapsed subscription gets its own sentence. It is the one refusal here an
    operator can fix in a minute, and as a bare 403 it reads like a permissions
    bug in our own code — which is exactly the wrong place to start looking.
    """
    text = str(exc)
    if fields:
        text = without_our_inputs(text, fields)
    if exc.code == SUBSCRIPTION_INACTIVE:
        text = f"fzr subscription is not active — renew the plan in their panel (they said: {text})"
    return FulfillerError(text, money_outcome=refusal_money(exc))


class FzrFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for FazerCards."""

    supplier = SUPPLIER

    def __init__(self, client: FzrClient | None = None) -> None:
        # Injectable for tests; in prod a transient client is built per call so
        # a hot-reloaded key takes effect without a restart (same as g2b).
        self._client_override = client

    def client_for_reads(self) -> FzrClient:
        """A client for read-only catalogue calls made outside fulfilment.

        The stock and cost sweeps live in ``integrations`` but the credentials
        and retry policy belong here, so they borrow a client instead of
        building a second one from settings and drifting apart from this
        adapter.
        """
        return self._client()

    def _client(self) -> FzrClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return FzrClient(
            api_key=s.fzr_api_key,
            base_url=s.fzr_base_url,
            timeout_seconds=s.fzr_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().fzr_api_key)

    # ---------- alert decoration ----------

    @staticmethod
    def _required_or_none(item: OrderItem) -> str | None:
        """What this line costs us, for the alert's "Нужно:" figure.

        ``Sku.cost_usdt`` is per unit, so it is multiplied out. ``None`` when
        the SKU was not loaded or carries no cost, which the alert renders as
        the ``$?`` it has always rendered.

        Like :meth:`_balance_or_none`, this only ever decorates a refusal that
        has already happened, so it must not be able to raise.
        """
        sku = getattr(item, "sku", None)
        cost = getattr(sku, "cost_usdt", None) if sku is not None else None
        if cost is None:
            return None
        try:
            return f"{Decimal(str(cost)) * Decimal(int(getattr(item, 'qty', 1) or 1)):.2f}"
        except (InvalidOperation, TypeError, ValueError):
            return None

    async def _balance_or_none(self) -> str | None:
        """Our wallet, for the alert. Never fails the refusal it decorates.

        One extra read on a path that has already failed, so the operator is
        told whether the missing money is theirs to add. If this call is the
        thing that is broken, the refusal still lands — a missing number is a
        worse alert, not a worse outcome.
        """
        try:
            body = await self._client().get_balance()
        except Exception as exc:  # noqa: BLE001 -- decoration must not raise
            log.info("fzr.balance_unavailable_for_alert", error=str(exc)[:200])
            return None
        value = body.get("balance")
        return None if value in (None, "") else str(value)

    async def _low_balance(self, exc: FzrError, item: OrderItem, message: str) -> FulfillResult:
        """The soft failure the saga parks in the inbox and alerts ops on."""
        return _GRADE.low_balance_result(
            message=message,
            side=shortfall_side(exc),
            our_balance=await self._balance_or_none(),
            required=self._required_or_none(item),
        )

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
            raise FulfillerError("FZR_API_KEY is not configured", money_outcome=_NOTHING_SPENT)

        mapping = await _mapping_for(db, sku_id=item.sku_id)
        category_id = str(mapping.external_product_id or "").strip()

        # Gift cards first, ahead of the quantity guard below: their endpoint
        # takes a real ``quantity`` (1-100), so the guard that is right for a
        # top-up would refuse every multi-card purchase.
        if mapping.kind == _VOUCHER_KIND:
            return await self._fulfill_giftcard(
                item=item, mapping=mapping, idempotency_key=idempotency_key
            )

        # One call buys one thing — for a game offer and a Steam wallet alike.
        # There is no Stars carve-out here because Telegram is not routed to
        # this vendor; see the module docstring.
        if item.qty > 1:
            raise FulfillerError(
                "fzr has no quantity on a top-up order — one call buys one offer",
                money_outcome=_NOTHING_SPENT,
            )

        if category_id == STEAM_SENTINEL:
            return await self._fulfill_steam(item=item, idempotency_key=idempotency_key)

        offer_id = str(mapping.external_variant_id or "").strip()
        if not category_id or not offer_id:
            raise FulfillerError("no active fzr mapping for this SKU", money_outcome=_NOTHING_SPENT)

        fields = await self._fields_for(category_id, item)
        if not fields:
            raise FulfillerError(
                "no fzr fields could be built from fulfillment_data",
                money_outcome=_NOTHING_SPENT,
            )

        try:
            obj = await self._client().create_topup_order(
                category_id=category_id,
                offer_id=offer_id,
                fields=fields,
                idempotency_key=idempotency_key,
            )
        except FzrError as exc:
            if looks_like_low_balance(exc):
                return await self._low_balance(exc, item, without_our_inputs(str(exc), fields))
            raise _refusal(exc, fields=fields) from exc
        except FzrUnavailableError as exc:
            # The create is the call that spends, so a lost response is the one
            # moment we must not declare anything. Park id-less and let the
            # poller find the order.
            return _parked_for_adoption(exc)

        return _GRADE.finish(obj)

    async def _fields_for(self, category_id: str, item: OrderItem) -> dict[str, str]:
        """Their ``fields`` payload, shaped the way *this category* asks.

        They declare their inputs per category on ``GET /topups/offers``, in
        the same four shapes NOVA does — ``player_id`` alone, plus a free-form
        ``server_id``, plus a ``server`` **select**, or a differently named
        identifier like ``imo_id``. Reading the declaration rather than
        assuming a rename is what stopped NOVA refusing Honkai Star Rail
        orders with ``Field "server" is required.``

        One extra request per order buys that. It runs on the worker, not a
        request, and it is a catalogue read against a 120/min limit.

        Falls back to the fixed rename when they will not tell us: an outage on
        the spec call must not block a sale that would have gone through.
        """
        legacy = legacy_fields(item.fulfillment_data or {})
        try:
            body = await self._client().get_offers(category_id)
        except Exception as exc:  # noqa: BLE001 -- a probe must never block a sale
            # Deliberately wider than their two error types: this is an
            # optional question asked before the real call, and *any* way it
            # can fail must fall through to the rename rather than refuse an
            # order we could have placed.
            log.info("fzr.field_spec_unavailable", category_id=category_id, error=str(exc)[:120])
            return legacy
        specs = field_specs(body)
        if not specs:
            # Told nothing is not the same as "needs nothing" — the two look
            # identical from here and mean opposite things.
            return legacy
        built = build_fields(specs, item.fulfillment_data or {})
        return built or legacy

    async def _fulfill_giftcard(
        self, *, item: OrderItem, mapping: Any, idempotency_key: str
    ) -> FulfillResult:
        """Buy gift-card codes — their gift-card endpoint, not the top-ups one.

        A card has no player to credit, so nothing is read out of
        ``fulfillment_data``: the whole order is a category, a denomination and
        a count. That is why this cannot ride on the default path, whose body
        requires ``fields``.

        Delivery is asynchronous even when it is fast: the create answers with
        the money already gone and the codes appear on the order a moment
        later, so this returns whatever ``finish`` grades the create as and
        ``check_status`` hands the code over.
        """
        category_id = str(mapping.external_product_id or "").strip()
        card_id = str(mapping.external_variant_id or "").strip()
        if not category_id or not card_id:
            raise FulfillerError("no active fzr mapping for this SKU", money_outcome=_NOTHING_SPENT)
        # ``mapping.quantity`` is how many supplier units make one of ours; a
        # card is one for one today, and multiplying keeps that an assumption
        # of the DATA rather than of this function.
        quantity = item.qty * max(1, int(mapping.quantity or 1))

        try:
            obj = await self._client().create_giftcard_order(
                category_id=category_id,
                card_id=card_id,
                quantity=quantity,
                idempotency_key=idempotency_key,
            )
        except FzrError as exc:
            if looks_like_low_balance(exc):
                return await self._low_balance(exc, item, str(exc))
            raise _refusal(exc) from exc
        except FzrUnavailableError as exc:
            return _parked_for_adoption(exc)

        return _GRADE.finish(obj)

    async def _fulfill_steam(self, *, item: OrderItem, idempotency_key: str) -> FulfillResult:
        """The Steam wallet branch. Mirrors the games path exactly on money
        grading — same client, same exceptions, same guard — because a
        different endpoint is not a different money story.

        Their rebate is tiered (bronze ≈2.5%, silver ≈3%, gold 3.55%), so what
        this costs us depends on the plan and is **not** the amount we send.
        The client folds their reported debit into the order under
        ``chargedUsd``, which is what ends up in the task metadata.

        ``item.qty > 1`` is already refused by :meth:`fulfill`.
        """
        steam_login = str((item.fulfillment_data or {}).get("steam_login") or "").strip()
        if not steam_login:
            raise FulfillerError(
                "order item is missing fulfillment_data.steam_login required by fzr",
                money_outcome=_NOTHING_SPENT,
            )
        try:
            obj = await self._client().create_steam_order(
                steam_login=steam_login,
                # Face value — what the customer receives. What it costs us is
                # that minus their plan rebate, which they report back and the
                # client folds in as ``chargedUsd``.
                amount_usd=Decimal(str(item.unit_price_usd)),
                idempotency_key=idempotency_key,
            )
        except FzrError as exc:
            if looks_like_low_balance(exc):
                return await self._low_balance(exc, item, str(exc))
            # The login is ours to redact for the same reason a player id is:
            # their refusal travels into ``task.last_error``.
            raise _refusal(exc, fields={"steamLogin": steam_login}) from exc
        except FzrUnavailableError as exc:
            return _parked_for_adoption(exc)

        return _GRADE.finish(obj)

    async def _adopt_or_wait(self, db: AsyncSession, task: FulfillmentTask) -> FulfillStatus:
        """Look for the order this id-less task paid for, and adopt it if found.

        The create charged us and its response was lost. Their order list is
        the only way to learn whether the order exists, and it may not exist
        *yet* — NOVA produced one eight seconds after our timeout — so this
        runs on every poll rather than once.

        Three answers, and they are genuinely different: found (record the id
        and report the order's real state), not yet (stay ``in_progress`` until
        ``ADOPT_WINDOW_MINUTES`` have passed), and past the window (fail, with
        ``UNKNOWN`` money — evidence of absence is not proof, and a wrong
        ``RETURNED`` would refund a customer who has their goods).

        An outage while probing is not "not found" — it propagates, because
        failing a task because they were unreachable would invite exactly the
        second purchase this path exists to prevent.
        """
        key = await _adopt_key_for(db, task)
        found = None
        if key is not None:
            found = await find_order(self._client(), key=key, since=task.created_at, slug=SUPPLIER)

        if found is not None:
            result = _GRADE.result(found)
            extra = dict(result.extra_metadata or {})
            extra["fzr_order_id"] = str(found.get("id") or "")
            extra["fzr_adopted"] = True
            return FulfillStatus(
                outcome=result.outcome,
                artifact_kind=result.artifact_kind,
                artifact=result.artifact,
                error=result.error,
                extra_metadata=extra,
                money_outcome=result.money_outcome,
            )

        waited = now() - task.created_at
        if waited < timedelta(minutes=ADOPT_WINDOW_MINUTES):
            return FulfillStatus(
                outcome="in_progress",
                artifact_kind=None,
                artifact=None,
                error=None,
                money_outcome=None,
            )
        raise FulfillerError(
            "fzr create was lost and no matching order appeared in "
            f"{ADOPT_WINDOW_MINUTES} minutes — check their panel before retrying "
            "(docs/runbooks/fzr.md)",
            money_outcome=_MAY_HAVE_SPENT,
        )

    async def check_status(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> FulfillStatus:
        if not self.available:
            # UNKNOWN, not "never ordered": by the time anything polls, the
            # order has been placed. A key that went missing since says
            # nothing about the money it was spent with.
            raise FulfillerError("FZR_API_KEY is not configured", money_outcome=_MAY_HAVE_SPENT)
        # An id adopted on an earlier poll counts as ours — the reconciler
        # merges ``extra_metadata`` onto the task but does not move it into
        # the ``external_order_id`` column, so read both.
        order_id = task.external_order_id or str(task.extra_metadata.get("fzr_order_id") or "")
        if not order_id:
            # The create never got far enough to give us an id. Go looking
            # before deciding anything: they charge on create, so the order
            # may well exist.
            return await self._adopt_or_wait(db, task)

        try:
            obj = await self._client().get_order(order_id)
        except (FzrError, FzrUnavailableError) as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        result = _GRADE.result(obj)
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
        # Refusing a *cancellation*, not ending a purchase: the order it would
        # have cancelled was already bought, and this call learns nothing about
        # what became of that money.
        raise FulfillerNotIntegratedError(
            "fzr exposes no cancel endpoint", money_outcome=MoneyOutcome.UNKNOWN
        )

    async def health(self) -> dict[str, Any]:
        """Connectivity, key validity, wallet balance and plan, in one pair of
        calls.

        It matters more here than for the other suppliers for two reasons:
        FazerCards is a reserve, so nothing routes to it on an ordinary day,
        and its catalogue access expires with the subscription. The first
        things anyone asks before switching a SKU to it are whether the key
        still works, whether there is money behind it, and whether the plan is
        still paid for.

        Never raises: an operator opening the integrations page must not meet
        an error boundary because a supplier is down.
        """
        if not self.available:
            return {"available": False, "reason": "FZR_API_KEY is not configured"}
        try:
            data = await self._client().get_balance()
        except Exception as exc:  # noqa: BLE001 -- a probe must not crash the page
            return {"available": False, "reason": str(exc)[:200]}
        balance = data.get("balance")
        out: dict[str, Any] = {
            "available": True,
            # Their balance is a decimal string ("0.0000"); the page wants the
            # two places everything else on it shows.
            "balance": f"{float(balance):.2f}" if balance is not None else None,
            "currency": data.get("currency"),
        }
        out.update(await self._plan_or_empty())
        return out

    async def _plan_or_empty(self) -> dict[str, Any]:
        """Plan name and expiry, or nothing. Never fails the health card.

        A second call, because the balance endpoint does not carry it and the
        plan is half the answer to "can we route to this supplier tomorrow".
        """
        try:
            body = await self._client().get_subscription()
        except Exception as exc:  # noqa: BLE001 -- a probe must not crash the page
            log.info("fzr.subscription_unavailable", error=str(exc)[:200])
            return {}
        return {
            "plan": body.get("plan"),
            "plan_expires_at": body.get("planExpiresAt"),
            "subscription_active": bool(body.get("subscriptionActive")),
        }


# ---------- helpers ----------


async def _adopt_key_for(db: AsyncSession, task: FulfillmentTask) -> AdoptKey | None:
    """What identifies the order this task paid for, in their list.

    ``None`` when the task cannot be described precisely enough to match on —
    see ``panel_adopt.key_is_usable`` for why a partial key is worse than no
    key at all.
    """
    from sqlalchemy import select

    from yupay.modules.orders.models import OrderItem as OrderItemModel

    item = (
        await db.execute(select(OrderItemModel).where(OrderItemModel.id == task.order_item_id))
    ).scalar_one_or_none()
    if item is None:
        return None
    mapping = await _mapping_or_none(db, sku_id=item.sku_id)
    if mapping is None:
        return None

    category_id = str(mapping.external_product_id or "").strip()
    data = item.fulfillment_data or {}
    if category_id == STEAM_SENTINEL:
        key = AdoptKey(kind="steam_topup", steam_login=str(data.get("steam_login") or "").strip())
    elif mapping.kind == _VOUCHER_KIND:
        key = AdoptKey(
            kind="gift_card",
            category_id=category_id,
            card_id=str(mapping.external_variant_id or "").strip(),
            quantity=item.qty * max(1, int(mapping.quantity or 1)),
        )
    else:
        key = AdoptKey(
            kind="topup",
            category_id=category_id,
            offer_id=str(mapping.external_variant_id or "").strip(),
            player_id=str(data.get("player_id") or data.get("account") or "").strip(),
        )
    return key if key_is_usable(key) else None


async def _mapping_or_none(db: AsyncSession, *, sku_id: str) -> Any:
    """Their active mapping for this SKU, or ``None``."""
    from sqlalchemy import select

    from yupay.modules.integrations.models import SkuSupplierMapping

    return (
        await db.execute(
            select(SkuSupplierMapping).where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.supplier_slug == SUPPLIER,
                # They sell two things this adapter buys: a top-up (``game``)
                # and a gift card (``voucher``). ``gift`` is not a route here,
                # so the filter stays a filter — failing at our own guard with
                # a message an operator can act on beats failing at their API
                # with whatever they say about an id from the wrong namespace.
                SkuSupplierMapping.kind.in_(("game", _VOUCHER_KIND)),
                SkuSupplierMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _mapping_for(db: AsyncSession, *, sku_id: str) -> Any:
    """Their active mapping for this SKU. Refuses rather than returns ``None``."""
    row = await _mapping_or_none(db, sku_id=sku_id)
    if row is None:
        raise FulfillerError(
            "no active fzr mapping for this SKU (need kind=game or kind=voucher)",
            money_outcome=_NOTHING_SPENT,
        )
    return row


__all__ = ["FzrFulfiller"]
