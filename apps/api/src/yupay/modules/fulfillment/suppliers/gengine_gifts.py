"""Fulfilment branch of the G-Engine adapter for Steam gifts.

A Steam gift is a single call — ``POST /gifts/orders`` both creates and buys
in one step, unlike the two-step recharge and shop order machines the rest of
``gengine.py`` drives. That collapses the state machine, but it sharpens the
one risk unique to a single-call purchase: a lost response. A recharge order
is created *unpaid* (a lost create just leaves an unpaid reservation, nothing
spent) and a shop order is recovered by a client-chosen ``uuid``; a gift order
has neither cushion — money has already moved by the time a response is lost,
and there is no id of ours to look it up by.

**Never create a second gift order for the same task** is therefore the whole
design here. Every path that might retry a purchase for the same order line
looks for an existing order first (:func:`_find_gift_order`), and an
ambiguous create (:class:`GEngineUnavailableError` — did it land or not?) is
parked ``in_progress`` rather than declared failed (which would invite a
human to retry it and buy twice) or retried blind. An id-less task that
stays unresolved past :data:`GIFT_ADOPT_WINDOW_MINUTES` is parked ``failed``
for manual review instead — by then a landed create is findable, so its
absence means the create never happened, and a human confirms that before
any second spend is made.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import FulfillerError, FulfillResult, FulfillStatus
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineClient,
    GEngineError,
    GEngineGiftOrder,
    GEngineUnavailableError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import OrderItem

log = get_logger("yupay.fulfillment.gengine_gifts")

#: Terminal-success statuses. OUR success fires at ``shipped`` (spec § 4.4);
#: ``delivered`` arriving first for a fast recipient is also success. A
#: post-``shipped`` decline surfaces as ``refunded`` on a task that already
#: succeeded — the existing stuck/refund manual path, not this state machine.
GIFT_STATUS_DONE = frozenset({"shipped", "delivered"})
#: Terminal-failure statuses.
GIFT_STATUS_DEAD = frozenset({"canceled", "refunded"})

#: An id-less gift task older than this is parked for manual review instead of
#: being re-bought: by then a landed create is findable, so absence means the
#: create never happened — and a human confirms that before any second spend.
GIFT_ADOPT_WINDOW_MINUTES = 30

#: RU free text — the existing precedent is g2b's ``_game_artifact``
#: ``message`` field. The storefront renders its own localized card
#: (Task 9); this string is only the email/miniapp fallback.
_DELIVERY_MESSAGE = (
    "Steam прислал вам подарок — примите его в клиенте или по ссылке из "
    "письма Steam. Отправитель — бот-аккаунт магазина, это нормально."
)

_PARK_ERROR = "gift order not found at supplier after create timeout — manual review"


async def fulfill_gift(
    client: GEngineClient, *, item: OrderItem, order_created_at: datetime
) -> FulfillResult:
    """Buy one Steam gift, or adopt an order already placed for this line.

    Checkout (Task 4) guarantees ``item.fulfillment_data`` carries a
    canonical ``invite_url``, ``package_id``, and upper-cased ``region`` — a
    missing field here means the row is corrupted, not that the supplier is
    having a bad day.

    The wire ``region`` G-Engine's ``POST /gifts/orders`` actually wants is
    the 2-letter country code carried on the package's own price entry
    (``PackagePriceResponse.region``), not our customer-facing zone label —
    a zone label there gets G-Engine's «Price not found». Checkout resolves
    that code at price time and stores it as ``region_code``; this prefers
    it, falling back to the legacy ``region`` zone value only for order
    rows written before this resolution existed.

    Args:
        client: G-Engine API client.
        item: the order line being fulfilled. Its ``fulfillment_data`` must
            carry ``invite_url``, ``package_id``, and ``region``; a
            ``region_code`` (the supplier's country code, checkout-derived)
            is preferred when present.
        order_created_at: the parent order's ``created_at``, the lower bound
            for the adopt-before-create probe.

    Returns:
        ``in_progress`` carrying the order id once one exists (created,
        adopted, or — on an ambiguous create — none at all, so a retry of
        this same call can adopt it instead of buying a second gift).

    Raises:
        FulfillerError: the line is missing a required field (data
            corruption, not weather), or G-Engine cleanly refused the
            create (:class:`GEngineError`).
    """
    data = item.fulfillment_data or {}
    invite_url = str(data.get("invite_url") or "").strip()
    region = str(data.get("region") or "").strip()
    package_id_raw = data.get("package_id")
    if not invite_url or not region or package_id_raw is None:
        raise FulfillerError("gift order line is missing invite_url, package_id, or region")
    # G-Engine's wire `region` is the supplier's 2-letter country code from
    # the package's own price entry, not our zone label (`region` above) —
    # a zone label gets «Price not found». Checkout (Task 4-hotfix) resolves
    # and stores that code as `region_code`; fall back to the legacy `region`
    # zone value only for order rows written before this resolution existed.
    wire_region = str(data.get("region_code") or data.get("region") or "")
    try:
        package_id = int(package_id_raw)
    except (TypeError, ValueError) as exc:
        raise FulfillerError(
            f"gift order line package_id must be numeric, got {package_id_raw!r}"
        ) from exc

    try:
        existing = await _find_gift_order(
            client, invite_url=invite_url, package_id=package_id, since=order_created_at
        )
    except GEngineUnavailableError:
        # Best-effort: the probe failing must not block a genuinely new line
        # from ever being bought. The create call carries its own
        # ambiguous-failure guard, so treating an outage here as "not found"
        # is safe — worst case is a second probe on the next retry, never a
        # second spend.
        existing = None
    if existing is not None:
        log.info("gengine_gifts.adopted_before_create", order_id=existing.id)
        return _gift_created_result(existing, package_id=package_id, invite_url=invite_url)

    try:
        order = await client.create_gift_order(
            invite_url=invite_url, package_id=package_id, region=wire_region
        )
    except GEngineError as exc:
        raise FulfillerError(str(exc)) from exc
    except GEngineUnavailableError as exc:
        # Ambiguous: the create may have landed upstream even though we
        # never saw the response. Parking id-less (rather than raising, which
        # would surface as a plain failure) means the next `fulfill_gift`
        # call on this same task adopts the order it finds instead of
        # buying a second gift.
        log.warning("gengine_gifts.create_unavailable", error=str(exc))
        return FulfillResult(
            outcome="in_progress",
            external_order_id=None,
            artifact_kind=None,
            artifact=None,
            error=None,
            extra_metadata=_gift_search_metadata(package_id=package_id, invite_url=invite_url),
        )

    return _gift_created_result(order, package_id=package_id, invite_url=invite_url)


async def gift_status(client: GEngineClient, *, task: FulfillmentTask) -> FulfillStatus:
    """Poll a gift order's supplier status, adopting an id-less task first.

    Runs before ``GEngineFulfiller.check_status``'s ``external_order_id``
    early-return — an id-less gift task still has work to do: find the order
    an ambiguous create may have placed, or park for manual review once it
    has been unresolved too long to still be waiting on one.

    Args:
        client: G-Engine API client.
        task: the fulfilment task. ``task.external_order_id`` is read first;
            failing that, ``task.extra_metadata["gift_order_id"]`` (an order
            already adopted on a previous poll); failing that, the finder is
            re-run from ``gift_search`` / ``gift_package_id`` /
            ``gift_invite_url``.

    Returns:
        The mapped supplier status, or ``in_progress`` while unresolved, or
        ``failed`` once the task has aged past
        :data:`GIFT_ADOPT_WINDOW_MINUTES` with no order found.
    """
    order_id = task.external_order_id or task.extra_metadata.get("gift_order_id")
    if order_id:
        return await _poll_gift_order(client, task=task, order_id=int(order_id))

    invite_url = str(task.extra_metadata.get("gift_invite_url") or "")
    package_id_raw = task.extra_metadata.get("gift_package_id")
    if invite_url and package_id_raw is not None:
        try:
            found = await _find_gift_order(
                client,
                invite_url=invite_url,
                package_id=int(package_id_raw),
                since=task.created_at,
            )
        except GEngineUnavailableError:
            # An outage during the adopt probe is not "not found" — reporting
            # it as such would park the task failed purely because the
            # supplier was unreachable. The 60s reconcile sweep retries.
            return FulfillStatus(
                outcome="in_progress", artifact_kind=None, artifact=None, error=None
            )
        if found is not None:
            status = await _poll_gift_order(client, task=task, order_id=found.id)
            return FulfillStatus(
                outcome=status.outcome,
                artifact_kind=status.artifact_kind,
                artifact=status.artifact,
                error=status.error,
                # `gift_order_id` lets the next poll skip straight to the
                # direct id-based lookup instead of re-running the finder.
                extra_metadata={**status.extra_metadata, "gift_order_id": str(found.id)},
            )

    if now() - task.created_at > timedelta(minutes=GIFT_ADOPT_WINDOW_MINUTES):
        return FulfillStatus(outcome="failed", artifact_kind=None, artifact=None, error=_PARK_ERROR)
    return FulfillStatus(outcome="in_progress", artifact_kind=None, artifact=None, error=None)


# ---------- helpers ----------


async def _poll_gift_order(
    client: GEngineClient, *, task: FulfillmentTask, order_id: int
) -> FulfillStatus:
    """Fetch one gift order by id and map it, treating unavailability as a
    reason to keep waiting rather than an error to raise.

    The reconcile sweep retries every 60 s (see ``gengine_reconcile``), so an
    unreachable supplier here is not this call's problem to solve — unlike
    the top-up/voucher poll paths, which raise `FulfillerError` and let the
    caller record it as an attempt failure.
    """
    try:
        order = await client.get_gift_order(order_id)
    except GEngineUnavailableError:
        return FulfillStatus(outcome="in_progress", artifact_kind=None, artifact=None, error=None)
    except GEngineError as exc:
        raise FulfillerError(str(exc)) from exc
    return _map_gift_order(order, task=task)


def _map_gift_order(order: GEngineGiftOrder, *, task: FulfillmentTask) -> FulfillStatus:
    """Interpret one supplier order as a delivery outcome.

    The refunded/dead check runs *before* the done check: if the very first
    poll we ever see already shows a done status (``shipped``/``delivered``)
    with ``is_refunded=True``, the money has already come back and this must
    report ``failed``, not ``succeeded``. A refund that lands only *after*
    we already recorded success is the existing stuck/refund manual path —
    unaffected by this ordering, since `check_status` no longer runs once a
    task is `succeeded`.
    """
    if order.is_refunded or order.status in GIFT_STATUS_DEAD:
        return FulfillStatus(
            outcome="failed",
            artifact_kind=None,
            artifact=None,
            error=order.error or f"supplier status {order.status}",
        )
    if order.status in GIFT_STATUS_DONE:
        # `app_name` isn't ours to set from this module (`GEngineGiftOrder`
        # has no such field) — it rides on task metadata if a caller ever
        # puts it there; today none does, so this always falls through to
        # `order.package_name`, the closest thing the supplier reports.
        app_name = task.extra_metadata.get("app_name") or order.package_name
        return FulfillStatus(
            outcome="succeeded",
            artifact_kind="topup_receipt",
            artifact={
                "supplier": "gengine",
                "kind": "gift",
                "external_order_id": str(order.id),
                "status": order.status,
                "app_name": app_name,
                "package_name": order.package_name,
                "message": _DELIVERY_MESSAGE,
            },
            error=None,
        )
    return FulfillStatus(
        outcome="in_progress",
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={"gengine_status": order.status},
    )


def _gift_search_metadata(*, package_id: int, invite_url: str) -> dict[str, Any]:
    """The metadata that lets a later call find or adopt this exact line.

    Return type is `dict[str, Any]` (not a narrower shape) to mirror
    `FulfillResult.extra_metadata` itself — free-form JSONB merged onto the
    task, with no fixed schema.
    """
    return {
        "supplier": "gengine",
        "gengine_kind": "gift",
        "gift_package_id": package_id,
        "gift_search": _search_term(invite_url),
        "gift_invite_url": invite_url,
    }


def _gift_created_result(
    order: GEngineGiftOrder, *, package_id: int, invite_url: str
) -> FulfillResult:
    """A created-or-adopted order, in the shape `fulfill_gift` returns."""
    return FulfillResult(
        outcome="in_progress",
        external_order_id=str(order.id),
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={
            **_gift_search_metadata(package_id=package_id, invite_url=invite_url),
            "gengine_status": order.status,
        },
    )


def _search_term(invite_url: str) -> str:
    """The last path segment of a Steam invite URL — the steamid64 or
    vanity name — because the full URL exceeds the supplier's 36-char
    search cap (``GIFT_SEARCH_MAX``)."""
    return invite_url.rstrip("/").rsplit("/", 1)[-1]


async def _find_gift_order(
    client: GEngineClient, *, invite_url: str, package_id: int, since: datetime
) -> GEngineGiftOrder | None:
    """Best-effort probe for an order already placed for this exact line.

    Used both to adopt-instead-of-recreate at fulfil time and to adopt an
    id-less task at poll time. A clean refusal (:class:`GEngineError`) is
    treated as not-found — the supplier answered, and its answer was "no" —
    but :class:`GEngineUnavailableError` (an outage) is left to propagate:
    the two mean different things to a caller. `fulfill_gift`'s probe is
    best-effort and treats either as not-found (the create call has its own
    ambiguous-failure guard), but `gift_status` must not conflate an outage
    with "genuinely not found" — that would park a task failed purely
    because G-Engine was unreachable, not because the create never
    happened.

    Raises:
        GEngineUnavailableError: the supplier could not be reached at all.
    """
    try:
        orders = await client.list_gift_orders(
            search=_search_term(invite_url), date_from=since.isoformat()
        )
    except GEngineError:
        return None
    for order in orders:
        if order.invite_url == invite_url and order.package_id == package_id:
            return order
    return None


__all__ = [
    "GIFT_ADOPT_WINDOW_MINUTES",
    "GIFT_STATUS_DEAD",
    "GIFT_STATUS_DONE",
    "fulfill_gift",
    "gift_status",
]
