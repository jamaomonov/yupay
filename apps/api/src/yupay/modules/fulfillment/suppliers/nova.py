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
from yupay.modules.fulfillment.suppliers.amount import quantity_for
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
    _shortfall_side,
    _without_our_inputs,
)
from yupay.modules.integrations.models import (
    NOVA_FRAGMENT_PREMIUM,
    NOVA_FRAGMENT_STARS,
    NOVA_STEAM_SENTINEL,
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

#: Re-exported so this module reads as one story; the fact itself lives in
#: ``integrations.models`` because the admin's mapping validator needs the same
#: one. See it there for why a sentinel rather than a fourth ``kind``.
#: ``SkuSupplierMapping.kind`` for a SKU that hands over a code rather than
#: crediting an account. The catalogue's own word, shared with G2B's voucher
#: mappings — the dispatch below reads it rather than sniffing the category,
#: because a category id says what is being bought and not how it arrives.
_VOUCHER_KIND = "voucher"

STEAM_SENTINEL = NOVA_STEAM_SENTINEL
FRAGMENT_STARS = NOVA_FRAGMENT_STARS
FRAGMENT_PREMIUM = NOVA_FRAGMENT_PREMIUM


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

    def client_for_reads(self) -> NovaClient:
        """A client for read-only catalogue calls made outside fulfilment.

        The stock refresh lives in ``integrations`` but the credentials and
        retry policy belong here, so it borrows a client instead of building a
        second one from settings and drifting apart from this adapter.
        """
        return self._client()

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
            log.info("nova.balance_unavailable_for_alert", error=str(exc)[:200])
            return None
        value = body.get("balance")
        return None if value in (None, "") else str(value)

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

        mapping = await _mapping_for(db, sku_id=item.sku_id)
        category_id = str(mapping.external_product_id or "").strip()

        # Gift cards first, ahead of the quantity guard below: their endpoint
        # takes a real ``quantity`` (1-100), so the guard that is right for a
        # top-up would refuse every multi-card purchase. Same reason the Stars
        # carve-out exists, one line down.
        if mapping.kind == _VOUCHER_KIND:
            return await self._fulfill_giftcard(
                item=item, mapping=mapping, idempotency_key=idempotency_key
            )

        # One call buys one thing — for a game offer, a Steam wallet and a
        # Premium gift alike. **Stars are the exception**, and it is not a
        # nicety: on the free-amount line ``item.qty`` *is* the star count
        # (5000 Stars is one order of qty 5000, mapping quantity 1), so the
        # guard that protects the other three would refuse every such order.
        # That is why this sits after the mapping is known and not before.
        if item.qty > 1 and category_id != FRAGMENT_STARS:
            raise FulfillerError(
                "nova has no quantity on a top-up order — one call buys one offer",
                money_outcome=_NOTHING_SPENT,
            )

        if category_id == STEAM_SENTINEL:
            return await self._fulfill_steam(item=item, idempotency_key=idempotency_key)
        if category_id in (FRAGMENT_STARS, FRAGMENT_PREMIUM):
            return await self._fulfill_fragment(
                db=db, item=item, mapping=mapping, idempotency_key=idempotency_key
            )

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
                return _low_balance_result(
                    message=_without_our_inputs(str(exc), fields),
                    side=_shortfall_side(exc),
                    our_balance=await self._balance_or_none(),
                )
            raise FulfillerError(
                _without_our_inputs(str(exc), fields), money_outcome=_refusal_money(exc)
            ) from exc
        except NovaUnavailableError as exc:
            # A transport failure carries no body, so there is nothing of ours
            # in it to take back out.
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _finish(obj)

    async def _fulfill_giftcard(
        self, *, item: OrderItem, mapping: Any, idempotency_key: str
    ) -> FulfillResult:
        """Buy gift-card codes — their gift-card endpoint, not the top-ups one.

        A card has no player to credit, so nothing is read out of
        ``fulfillment_data``: the whole order is a category, a denomination and
        a count. That is why this cannot ride on the default path, whose body
        requires ``fields`` and which would refuse every voucher SKU with "no
        nova fields could be built".

        Delivery is asynchronous even when it is fast. Their create answers
        ``created`` with ``cards: []`` and the money already gone; the codes
        appear on ``GET /api/v2/orders/{id}`` about a second later. So this
        returns whatever ``_finish`` grades the create as — ``in_progress``
        with an id — and ``check_status`` finishes it through the same
        ``_result`` that now knows how to hand a code over.
        """
        category_id = str(mapping.external_product_id or "").strip()
        card_id = str(mapping.external_variant_id or "").strip()
        if not category_id or not card_id:
            raise FulfillerError(
                "no active nova mapping for this SKU", money_outcome=_NOTHING_SPENT
            )
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
        except NovaError as exc:
            if _looks_like_low_balance(exc):
                return _low_balance_result(
                    message=str(exc),
                    side=_shortfall_side(exc),
                    our_balance=await self._balance_or_none(),
                )
            raise FulfillerError(str(exc), money_outcome=_refusal_money(exc)) from exc
        except NovaUnavailableError as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _finish(obj)

    async def _fulfill_steam(self, *, item: OrderItem, idempotency_key: str) -> FulfillResult:
        """The Steam wallet branch. Mirrors the games path above exactly on
        money grading — same client, same exceptions, same guard — because a
        different endpoint is not a different money story.

        ``item.qty > 1`` is already refused by :meth:`fulfill` — just after
        the mapping is loaded rather than before, because Stars need the
        mapping to claim their exemption — so it is not repeated here.
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
                return _low_balance_result(
                    message=_without_our_inputs(str(exc), {"steam_login": steam_login}),
                    side=_shortfall_side(exc),
                    our_balance=await self._balance_or_none(),
                )
            raise FulfillerError(
                _without_our_inputs(str(exc), {"steam_login": steam_login}),
                money_outcome=_refusal_money(exc),
            ) from exc
        except NovaUnavailableError as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _finish(obj)

    async def _fulfill_fragment(
        self,
        *,
        db: AsyncSession,
        item: OrderItem,
        mapping: Any,
        idempotency_key: str,
    ) -> FulfillResult:
        """Telegram Stars and Premium, through NOVA's Fragment API.

        A third endpoint pair with a third shape, and the money grading is
        deliberately identical to the other two — a different URL is not a
        different money story.

        The star count is **not** computed here. ``quantity_for`` is the same
        function G-Engine's Telegram service calls, and it has to be: a package
        SKU carries its pack size on the mapping and is bought ``qty=1``, while
        the free-amount line carries ``1`` and arrives with the customer's own
        count as ``item.qty``. Two adapters reading that row differently is how
        somebody gets 1 Star instead of 5000.

        Premium takes its months from the mapping variant, which is the only
        thing separating its three products.
        """
        username = str(
            (item.fulfillment_data or {}).get("username")
            or (item.fulfillment_data or {}).get("telegram_username")
            or ""
        ).strip()
        if not username:
            raise FulfillerError(
                "order item is missing fulfillment_data.username",
                money_outcome=_NOTHING_SPENT,
            )

        is_premium = str(mapping.external_product_id or "").strip() == FRAGMENT_PREMIUM
        months = 0
        stars = 0
        if is_premium:
            try:
                months = int(str(mapping.external_variant_id or "").strip())
            except ValueError:
                months = 0
            if months <= 0:
                raise FulfillerError(
                    "nova premium mapping carries no month count in its variant",
                    money_outcome=_NOTHING_SPENT,
                )
        else:
            stars = int(await quantity_for(db, item=item, mapping=mapping))

        try:
            if is_premium:
                obj = await self._client().create_fragment_premium_order(
                    username=username, months=months, idempotency_key=idempotency_key
                )
            else:
                obj = await self._client().create_fragment_stars_order(
                    username=username, stars_amount=stars, idempotency_key=idempotency_key
                )
        except NovaError as exc:
            if _looks_like_low_balance(exc):
                return _low_balance_result(
                    message=_without_our_inputs(str(exc), {"username": username}),
                    side=_shortfall_side(exc),
                    our_balance=await self._balance_or_none(),
                )
            raise FulfillerError(
                _without_our_inputs(str(exc), {"username": username}),
                money_outcome=_refusal_money(exc),
            ) from exc
        except NovaUnavailableError as exc:
            raise FulfillerError(str(exc), money_outcome=_MAY_HAVE_SPENT) from exc

        return _finish(obj)

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

        # Which of NOVA's two APIs owns this order. `/api/v2/orders/{id}` does
        # not know a Fragment one, and asking it anyway does not 404 — the
        # Fragment answer comes back without the `ok` envelope `_request`
        # requires, so a delivered order reported itself as `nova HTTP 200`
        # and the task sat in processing while the customer already had their
        # Stars. Read from the mapping rather than a marker on the task, so
        # tasks created before this fix are answered too.
        try:
            fragment = await _is_fragment_task(db, task)
            obj = (
                await self._client().get_fragment_order(task.external_order_id)
                if fragment
                else await self._client().get_order(task.external_order_id)
            )
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


async def _is_fragment_task(db: AsyncSession, task: FulfillmentTask) -> bool:
    """Whether this task's order lives in NOVA's Fragment namespace.

    Answered from the SKU's mapping, which is the same row the fulfiller
    dispatched on, so the two cannot disagree. A task whose mapping has since
    been deleted falls back to the v2 endpoint — the older behaviour, and the
    one that is right for every order that predates Fragment.
    """
    from sqlalchemy import select

    from yupay.modules.orders.models import OrderItem

    sku_id = (
        await db.execute(select(OrderItem.sku_id).where(OrderItem.id == task.order_item_id))
    ).scalar_one_or_none()
    if not sku_id:
        return False
    try:
        mapping = await _mapping_for(db, sku_id=str(sku_id))
    except FulfillerError:
        return False
    return str(mapping.external_product_id or "").strip() in (FRAGMENT_STARS, FRAGMENT_PREMIUM)


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
