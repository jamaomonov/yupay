"""Fulfilment saga (synchronous skeleton).

Drives an order from ``paid`` through ``fulfilling → fulfilled → delivered`` by
creating one :class:`FulfillmentTask` per :class:`OrderItem`, executing each task
in-process against the resolved :class:`Fulfiller`, recording each interaction
in ``fulfillment_attempts``, and persisting the artifact in ``deliveries``.

With ``fulfilment_async`` on, ``start_for_order`` leaves tasks ``pending`` and
fires ``pg_notify('fulfillment_queue', ...)`` on commit instead of executing
inline; ``apps/worker`` drains them via :func:`drain_pending_tasks`. The public
API stays the same either way (ADR-0064).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import sys
from collections.abc import Coroutine, Iterable
from typing import Any, Final

from sqlalchemy import Row, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import AppError, ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.models import (
    Delivery,
    FulfillmentAttempt,
    FulfillmentTask,
)
from yupay.modules.fulfillment.suppliers import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillResult,
    MoneyOutcome,
    get_fulfiller,
)
from yupay.modules.inventory import service as inv_svc
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.sourcing import service as sourcing_svc
from yupay.modules.sourcing.service import Decision

log = get_logger("yupay.fulfillment.service")

INVENTORY_ROUTE = "inventory"
_SUPPLIER_PREFIX = "supplier:"

# Mirrors ``g2b.LOW_BALANCE_ERROR``. Duplicated here (instead of imported)
# to keep the saga independent of any one supplier module — once a
# second adapter ships with the same kind of soft-failure, both will
# write the same sentinel string and the saga will route them
# identically.
_LOW_BALANCE_ERROR = "supplier_low_balance"
# Redis-side dedupe window. Without it a 50-order backlog after a
# balance drop would fan out 50 Telegram messages in the same minute.
# 15 min covers a typical "see the alert, top up the wallet, retry"
# loop without burying ops in repeats.
_LOW_BALANCE_ALERT_DEDUPE_SECONDS = 15 * 60

#: Where a task records what became of our money when it failed. It lives in
#: ``extra_metadata`` rather than a column because that is where every other
#: structured fact about a task already lives, and because nothing queries it
#: yet — M3b Task 3 reads it at the moment the failure happens, on the row it
#: has in hand. Read it with :func:`money_outcome_of`, never by key.
MONEY_OUTCOME_KEY = "money_outcome"

#: Our own warehouse running dry. No supplier is involved in an inventory
#: route at all, so nothing external was ever charged — the cleanest
#: :attr:`MoneyOutcome.RETURNED` in the codebase, and the one case where an
#: automatic refund is unambiguously right.
INVENTORY_FAILURE_MONEY_OUTCOME = MoneyOutcome.RETURNED

#: How much a money outcome commits us to, lowest first. ``record_money_outcome``
#: never moves a task down this ladder: knowledge about our own money only ever
#: accumulates. ``RETURNED`` is the bottom because it is the one value that
#: unlocks an automatic refund, so promoting to it is the expensive mistake;
#: ``SPENT`` is the top because "we know it is gone" is a positive finding that
#: a later "we cannot tell" must not erase — the very blur
#: :class:`MoneyOutcome`'s docstring forbids.
_CONFIDENCE: dict[MoneyOutcome, int] = {
    MoneyOutcome.RETURNED: 0,
    MoneyOutcome.UNKNOWN: 1,
    MoneyOutcome.SPENT: 2,
}

#: A task that crashed on an exception nobody wrapped, or one an admin
#: rejected by hand. Neither can say what happened upstream: the first died
#: mid-saga, and the second is a human who bought (or did not buy) the goods
#: somewhere this code cannot see.
_NOBODY_CAN_SAY = MoneyOutcome.UNKNOWN


def record_money_outcome(task: FulfillmentTask, outcome: MoneyOutcome) -> None:
    """Persist what became of our money on a task that has just failed.

    **A task never moves down :data:`_CONFIDENCE`.** The rung that matters is
    the bottom one: every ``RETURNED`` an adapter can produce is a fact about
    *one attempt* —
    "the supplier refunded this order", "this create never reached the call
    that pays". A task outlives its attempts: an admin Retry re-runs it, and
    the retry knows nothing about what the attempt before it spent. Without
    this rule the sequence is a real money loss, and needs no supplier
    misbehaviour to reach:

    1. ``pay`` is charged and *then* returns HTTP 500 → ``UNKNOWN``, correctly.
    2. An admin clicks Retry — the ordinary response to that failure.
    3. The replay trips a transient outage before it creates anything →
       ``RETURNED``, also correctly, *for that attempt*.
    4. M3b refunds the deposit for goods we have already paid for.

    So once any attempt has left money unaccounted for, no later attempt may
    declare the task's money whole. Upward stays open: a ``RETURNED`` task that
    is retried and then loses money records that, because it is new knowledge
    rather than an older attempt's absence of it. ``SPENT`` is likewise never
    downgraded to ``UNKNOWN`` — a retry whose call fails ambiguously would
    otherwise turn "waxpeer kept our money" into "we cannot tell" in the admin
    inbox. Task 3 treats those two the same, but a human does not.

    There is deliberately **no way to lower a recorded outcome**, here or
    through ``retry_task`` / ``complete_manual_task``. That is safe while only
    a terminal supplier verdict writes one, and it cuts both ways:

    - a caller that starts recording on *transient* errors would make every
      outage a permanent ``UNKNOWN`` on an otherwise fine task;
    - and ``SPENT`` is already unrecoverable **today**. Waxpeer writes it for an
      ``error`` top-up, the runbook's answer is "chase the money", and an
      operator who chases it successfully has no way to record that we are whole
      again — the task reads "money gone" forever and M3b will never refund that
      merchant automatically.

    Either direction needs an operator re-grade path. Neither has one yet.

    The value is merged onto ``extra_metadata`` rather than assigned, so the
    supplier flags the adapters wrote — ``supplier_refunded``,
    ``needs_reconciliation`` and the rest — survive alongside it. Those keys
    stay the admin inbox's and the runbooks' spelling of the same idea; this
    one is the typed source of truth M3b acts on.

    Args:
        task: The task, already marked ``failed``.
        outcome: What became of the money on the attempt that just ended.
    """
    standing = _standing_outcome(task)
    if standing is not None and _CONFIDENCE[outcome] < _CONFIDENCE[standing]:
        log.info(
            "fulfillment.money_outcome.kept",
            task_id=task.id,
            supplier=task.supplier,
            standing=standing.value,
            refused=outcome.value,
        )
        return
    task.extra_metadata = {**(task.extra_metadata or {}), MONEY_OUTCOME_KEY: outcome.value}


def _standing_outcome(task: FulfillmentTask) -> MoneyOutcome | None:
    """The value already on the task, for the ladder — **failing closed**.

    ``money_outcome_of`` reads an unrecognised string as "nothing recorded",
    which is right for a reader but wrong for the guard: it would let a later
    ``RETURNED`` overwrite a value this build merely cannot parse. The one
    re-grade available today is a hand DB edit (see
    :func:`record_money_outcome`), and the enum's values are lowercase, so an
    operator typing ``'UNKNOWN'`` would silently disarm the invariant on that
    task — on the exact rows a human is already worried about.

    A present-but-unreadable value therefore counts as
    :attr:`MoneyOutcome.UNKNOWN`: high enough to block a promotion, low enough
    that real knowledge still lands on top of it.
    """
    standing = money_outcome_of(task)
    if standing is None and (task.extra_metadata or {}).get(MONEY_OUTCOME_KEY) is not None:
        return MoneyOutcome.UNKNOWN
    return standing


def _record_or_warn(
    task: FulfillmentTask, outcome: MoneyOutcome | None, *, discovered: str
) -> None:
    """Record a terminal failure's money outcome, or say out loud that it has none.

    Never raising is the right *behaviour* — a saga must not die because an
    adapter forgot — but swallowing it silently would make the totality
    property unenforced at runtime, so a hole the AST guard cannot see (an
    adapter's intermediate type, a value threaded through a helper) would
    produce no signal at all. M3b Task 3 is about to start acting on this
    field's absence, so absence gets a log line an alert can find.

    The low-balance stall never reaches here: it returns earlier, without an
    outcome and legitimately so.

    Args:
        task: The task, already marked ``failed``.
        outcome: What the adapter said, or ``None`` if it said nothing.
        discovered: Which path found the failure, for the log line.
    """
    if outcome is None:
        log.warning(
            "fulfillment.money_outcome.missing",
            task_id=task.id,
            supplier=task.supplier,
            discovered=discovered,
        )
        return
    record_money_outcome(task, outcome)


def money_outcome_of(task: FulfillmentTask) -> MoneyOutcome | None:
    """What this task's last terminal failure recorded about our money.

    **It outlives that failure.** ``retry_task`` does not clear it and no
    success path removes it, so a task that failed and then succeeded on a
    retry still answers — deliberately, because it is the only trace that an
    earlier attempt may have spent money the successful one did not account
    for, and because :func:`record_money_outcome` needs it to refuse a replay's
    false "we still have the money". A caller asking "what happened to *this*
    order" must therefore pair it with ``task.status == "failed"``; a caller
    asking "is there money unaccounted for on this task" must not.

    ``None`` covers three rows and deliberately does not distinguish them: one
    that has never failed, one that failed before this field existed, and one
    carrying a value this build does not know. The last is why this is a lookup
    rather than a cast — a row written by another deploy must not crash a saga,
    and "we do not know" is already one of the three answers a caller handles.
    """
    raw = (task.extra_metadata or {}).get(MONEY_OUTCOME_KEY)
    return next((m for m in MoneyOutcome if m.value == raw), None)


# ---------- supplier routing ----------


def _route_label(decision: Decision) -> str:
    """Persisted ``fulfillment_tasks.supplier`` value for a routing decision."""
    if decision.primary == "inventory":
        return INVENTORY_ROUTE
    return decision.primary.removeprefix(_SUPPLIER_PREFIX) or decision.primary


def _supplier_slug(route: str) -> str:
    return route.removeprefix(_SUPPLIER_PREFIX) if route.startswith(_SUPPLIER_PREFIX) else route


# ---------- loaders ----------


async def _load_order_with_items(db: AsyncSession, order_id: str) -> Order:
    # Suppliers (notably the mock fulfiller, but real ones too once we wire
    # them) read ``item.sku.product.kind`` to decide whether to mint a
    # voucher code or a top-up receipt — async SA refuses lazy loads, so
    # eager-load the chain right here.
    from yupay.modules.catalog.models import Sku

    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.sku).selectinload(Sku.product),
            selectinload(Order.events),
        )
        .where(Order.id == order_id)
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("order not found")
    return order


async def _load_task(
    db: AsyncSession, task_id: str, *, for_update: bool = False
) -> FulfillmentTask:
    """Load one task, optionally under a row lock.

    ``for_update=True`` is for the *mutating* callers (admin retry/cancel, and
    the poll/webhook reconciler, which read-modify-writes ``extra_metadata``).
    Without it they read a snapshot taken before the consumer's claim, decide
    on that stale status, and then queue behind the consumer's row lock only
    to overwrite what it just committed — an admin cancel landing on top of a
    committed ``succeeded`` is a refund issued for goods that were delivered.
    ``populate_existing`` is not optional here: a lock whose row is then
    served from the session's identity map (with the attributes it had before
    the lock was granted) proves nothing. Read-only callers stay unlocked —
    an admin list must never wait on a supplier call.
    """
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.id == task_id)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise NotFoundError("fulfilment task not found")
    return task


async def _existing_tasks_for_order(
    db: AsyncSession, order_id: str, *, for_update: bool = False
) -> list[FulfillmentTask]:
    """Load an order's tasks, optionally under row locks. See :func:`_load_task`.

    The ``created_at, id`` ordering is what keeps the locking variant
    deadlock-free against the drain loop: both take this order's rows in
    ``created_at`` order (``drain_pending_tasks``' claim query orders the same
    way), so two sessions can queue but never wait on each other in a cycle.
    """
    stmt = (
        select(FulfillmentTask)
        .options(selectinload(FulfillmentTask.attempts))
        .where(FulfillmentTask.order_id == order_id)
        .order_by(FulfillmentTask.created_at, FulfillmentTask.id)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list((await db.execute(stmt)).scalars().all())


#: Task statuses that mean a supplier call for this order is still coming.
#: ``pending`` is what :func:`drain_pending_tasks` claims and what
#: :func:`retry_task` writes; ``in_progress`` is a call already out. The three
#: terminal statuses are absent on purpose — settling the order of a ``failed``
#: task is the whole point of a hand settlement.
OPEN_TASK_STATUSES: Final[frozenset[str]] = frozenset({"pending", "in_progress"})


async def lock_tasks_for_order(db: AsyncSession, *, order_id: str) -> list[FulfillmentTask]:
    """Take ``FOR UPDATE`` on every fulfilment task of an order, and return them.

    The public door onto :func:`_existing_tasks_for_order`'s locking variant,
    for a caller in another module that must decide something about this
    order's tasks and have the decision **stay true** for the rest of its
    transaction. Today that is exactly one caller:
    ``merchants.deposit.credit_deposit``, which refuses an attributed
    settlement while a task is still open (M3c fix round 1). An unlocked read
    there is a check-then-act — the drain can claim the task a millisecond
    later — and the thing being decided is whether a reseller gets goods they
    have already been refunded for.

    **It works because of ``SKIP LOCKED``, not in spite of it.**
    ``drain_pending_tasks`` claims with ``FOR UPDATE SKIP LOCKED``, so a row
    this holds is *skipped* rather than waited on: the drain moves past the
    order for as long as the settlement's transaction lives, and never blocks.

    **Lock order: tasks before the order row, the system-wide invariant.** Call
    this *before* touching ``orders``; the ordering inside is
    ``_existing_tasks_for_order``'s ``created_at, id``, the same the drain's
    claim query uses, so two sessions queue and never cycle.

    Args:
        db: Session. The caller owns the transaction, and the locks live until
            it ends.
        order_id: The order whose tasks to lock.

    Returns:
        Every task of the order, oldest first. Empty when the saga has not
        started — which is not the same as "nothing is coming"; see the
        caller's own note on that residue.
    """
    return await _existing_tasks_for_order(db, order_id, for_update=True)


# ---------- audit ----------


async def _record_attempt(
    db: AsyncSession,
    *,
    task: FulfillmentTask,
    kind: str,
    status: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Append an interaction to the task's audit log, folding repeats.

    The poller asks the supplier for a status once a minute for as long as the
    order stays open, and every answer used to become a row: one production
    task holds 1641, of which 1640 are the identical "still in progress". They
    say nothing the first one does not — except that we were still checking at
    T, which ``last_seen_at``/``repeat_count`` record on the row itself.

    So an attempt identical to the task's most recent one (same kind, status,
    payload and error) updates that row instead of adding another. Anything
    that differs — a new outcome, an error appearing or clearing — starts a new
    row, which is what makes the log a record of what *changed*.

    ``attempts_count`` counts rows, not observations, so it stays in step with
    the log the admin panel renders and stops reporting a well-behaved task as
    having been attempted 1641 times. (`stats.analytics.ops` averages it per
    supplier; polls had pushed that average to 47.6.)
    """
    previous = (
        await db.execute(
            select(FulfillmentAttempt)
            .where(FulfillmentAttempt.task_id == task.id)
            .order_by(FulfillmentAttempt.created_at.desc(), FulfillmentAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    moment = now()
    if (
        previous is not None
        and previous.kind == kind
        and previous.status == status
        and previous.error == error
        and previous.payload == (payload or {})
    ):
        previous.repeat_count += 1
        previous.last_seen_at = moment
        task.updated_at = moment
        return

    db.add(
        FulfillmentAttempt(
            id=new_id(),
            task_id=task.id,
            kind=kind,
            status=status,
            payload=payload or {},
            error=error,
        )
    )
    task.attempts_count += 1
    task.updated_at = moment

    # Every way fulfilment can go wrong lands here: a supplier call that threw,
    # and a call that succeeded while *reporting* failure (both record
    # ``status="error"``). Alerting from this one place is what makes "any
    # error reaches us" true, rather than a list of call sites someone has to
    # remember to extend.
    if status == "error":
        _dispatch_alert(_alert_fulfillment_error(task, kind=kind, error=error))


# ---------- realtime ----------


async def _publish_status_changed(
    db: AsyncSession, order: Order, *, publish_realtime: bool = True
) -> None:
    """Route a status change through the orders module's one seam.

    This used to be a verbatim copy of the realtime nudge — one of three. The
    nudge, and the merchant webhook beside it, now live in
    ``orders.service.on_order_status_changed``; the local name is kept so the
    call sites read as they always did. ``publish_realtime=False`` is for the
    settle path, which emits ``order.delivered`` instead and must not start
    sending a connected storefront a second event as well.

    Imported lazily for the reason ``orders.service`` imports *this* module
    lazily: the two reach into each other and a module-level import would
    close the cycle.
    """
    from yupay.modules.orders import service as orders_svc

    await orders_svc.on_order_status_changed(db, order, publish_realtime=publish_realtime)


async def _publish_delivered(order: Order) -> None:
    """Tell the order's owner (if any) the order just reached ``delivered``."""
    from yupay.modules.realtime import api as realtime

    await realtime.publish_order_event(
        order.user_id,
        {
            "type": "order.delivered",
            "orderId": order.id,
            "payload": {"kind": "order", "data": None},
        },
    )


# ---------- core saga ----------


async def start_for_order(
    db: AsyncSession, *, order_id: str, settings: Settings | None = None
) -> list[FulfillmentTask]:
    """Plan and execute fulfilment for a freshly-paid order.

    Creates one task per order item (idempotent — re-running on the same order
    is a no-op because of the ``UNIQUE(order_item_id)`` constraint), drives
    order ``paid → fulfilling``, then — with ``fulfilment_async`` off (the
    default) — processes every task in-process, same as always. With it on,
    tasks are left ``pending`` for the worker and a ``pg_notify`` rides the
    caller's transaction instead.
    """
    order = await _load_order_with_items(db, order_id)
    if order.status not in ("paid", "fulfilling"):
        raise ConflictError(
            "order is not in a fulfilment-ready state",
            extra={"status": order.status},
        )
    # A wallet deposit has no items, so this would create no tasks, still flip
    # the order to ``fulfilling``, and then strand it there — ``_try_settle_order``
    # returns early when there is nothing to settle. A held deposit is resolved
    # by crediting or refunding the customer, not by releasing it to fulfilment;
    # see docs/runbooks/paid-after-expiry.md.
    if order.purpose != "catalog":
        raise ConflictError(
            "a wallet top-up has nothing to fulfil",
            extra={"purpose": order.purpose},
        )

    existing = {t.order_item_id: t for t in await _existing_tasks_for_order(db, order_id)}
    new_tasks: list[FulfillmentTask] = []
    for item in order.items:
        if item.id in existing:
            new_tasks.append(existing[item.id])
            continue
        decision = await sourcing_svc.resolve_for_sku(db, item.sku_id)
        task = FulfillmentTask(
            id=new_id(),
            order_id=order.id,
            order_item_id=item.id,
            supplier=_route_label(decision),
            status="pending",
        )
        db.add(task)
        new_tasks.append(task)

    transitioned_to_fulfilling = False
    if order.status == "paid":
        order.status = "fulfilling"
        order.updated_at = now()
        transitioned_to_fulfilling = True
        db.add(
            OrderEvent(
                id=new_id(),
                order_id=order.id,
                kind="order.fulfilling",
                payload={"task_ids": [t.id for t in new_tasks]},
                actor="fulfillment",
            )
        )

    await db.flush()
    if transitioned_to_fulfilling:
        await _publish_status_changed(db, order)

    cfg = settings or get_settings()
    if cfg.fulfilment_async:
        # Planned, not executed: the rows ARE the queue (they just landed in
        # the caller's transaction, atomically with the payment). The NOTIFY
        # rides the same transaction — Postgres delivers it on COMMIT and
        # drops it on ROLLBACK, so a nudge can neither outrun the commit nor
        # survive a rollback. The worker's poll tick covers a nudge lost to
        # a worker restart; nothing here needs to care.
        await db.execute(text("SELECT pg_notify('fulfillment_queue', :oid)"), {"oid": order_id})
    else:
        for task in new_tasks:
            if task.status == "pending":
                await process_task(db, task_id=task.id)

    await _try_settle_order(db, order_id=order_id)
    await db.flush()
    return new_tasks


async def _inventory_fulfill(db: AsyncSession, *, task: FulfillmentTask, item: OrderItem) -> bool:
    """Try to satisfy the task from the warehouse.

    Returns True on success. On ``NoStockError`` returns False — caller decides
    whether to fall back or mark the task failed.
    """
    try:
        issued = await inv_svc.reserve_and_issue(db, sku_id=item.sku_id, order_item_id=item.id)
    except inv_svc.NoStockError as exc:
        await _record_attempt(
            db,
            task=task,
            kind="fulfill",
            status="error",
            payload={"route": INVENTORY_ROUTE, "reason": "no_stock"},
            error=str(exc),
        )
        return False

    task.external_order_id = issued.inventory_code_id
    task.status = "succeeded"
    task.succeeded_at = now()
    task.last_error = None
    item.fulfillment_state = "delivered"
    item.supplier_order_id = issued.inventory_code_id
    db.add(
        Delivery(
            id=new_id(),
            order_item_id=item.id,
            channel="in_app",
            artifact_kind="voucher_code",
            artifact={
                "code": issued.code,
                "inventory_code_id": issued.inventory_code_id,
                "source": INVENTORY_ROUTE,
            },
        )
    )
    await _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="ok",
        payload={
            "route": INVENTORY_ROUTE,
            "inventory_code_id": issued.inventory_code_id,
        },
    )
    return True


async def process_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Run a single task and persist the outcome.

    Routing: if ``task.supplier == 'inventory'`` (set by ``start_for_order`` from
    the sourcing decision), serve from the warehouse. On no-stock we re-consult
    sourcing to decide whether to fall back to a supplier (mode='auto') or fail
    the task (mode='force_inventory').
    """
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        return task

    # Eager-load ``item.sku.product`` — real-supplier fulfillers read
    # ``sku.cost_usdt`` (pre-flight balance check) and ``sku.product.kind``
    # (artifact decision). Async SA raises on lazy attribute access
    # otherwise.
    from yupay.modules.catalog.models import Sku

    item = (
        await db.execute(
            select(OrderItem)
            .options(selectinload(OrderItem.sku).selectinload(Sku.product))
            .where(OrderItem.id == task.order_item_id)
        )
    ).scalar_one()
    order = (await db.execute(select(Order).where(Order.id == task.order_id))).scalar_one()

    task.status = "in_progress"
    task.updated_at = now()

    # ---- inventory route ----
    if task.supplier == INVENTORY_ROUTE:
        if await _inventory_fulfill(db, task=task, item=item):
            return task
        # No stock — check sourcing rule to decide fallback.
        decision = await sourcing_svc.resolve_for_sku(db, item.sku_id)
        if decision.strict or decision.fallback is None:
            task.status = "failed"
            task.failed_at = now()
            task.last_error = "no stock and sourcing rule is strict"
            item.fulfillment_state = "failed"
            record_money_outcome(task, INVENTORY_FAILURE_MONEY_OUTCOME)
            return task
        # Switch the route to the supplier fallback for the rest of this attempt.
        task.supplier = _supplier_slug(decision.fallback)
        await _record_attempt(
            db,
            task=task,
            kind="fulfill",
            status="ok",
            payload={"route_switch": task.supplier, "reason": "inventory_no_stock"},
        )

    # ---- supplier route ----
    fulfiller: Fulfiller = get_fulfiller(task.supplier)

    try:
        result: FulfillResult = await fulfiller.fulfill(
            db=db, order=order, item=item, idempotency_key=task.id
        )
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        await _record_attempt(
            db,
            task=task,
            kind="fulfill",
            status="error",
            payload={"supplier": task.supplier},
            error=str(exc),
        )
        task.status = "failed"
        task.failed_at = now()
        task.last_error = str(exc)
        item.fulfillment_state = "failed"
        # An adapter that raises has ended the order as terminally as one that
        # returns ``failed``, and answers the same question at the raise site.
        record_money_outcome(task, exc.money_outcome)
        log.warning(
            "fulfillment.fulfill.failed",
            task_id=task.id,
            supplier=task.supplier,
            error=str(exc),
        )
        return task

    task.external_order_id = result.external_order_id
    if result.extra_metadata:
        task.extra_metadata = {**task.extra_metadata, **result.extra_metadata}

    await _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="ok" if result.outcome != "failed" else "error",
        payload={
            "supplier": task.supplier,
            "outcome": result.outcome,
            "external_order_id": result.external_order_id,
        },
        error=result.error,
    )

    if result.outcome == "succeeded":
        task.status = "succeeded"
        task.succeeded_at = now()
        task.last_error = None
        item.fulfillment_state = "delivered"  # see ck_order_items_state
        item.supplier_order_id = result.external_order_id
        if result.artifact_kind and result.artifact is not None:
            db.add(
                Delivery(
                    id=new_id(),
                    order_item_id=item.id,
                    channel="in_app",
                    artifact_kind=result.artifact_kind,
                    artifact=result.artifact,
                )
            )
    elif result.outcome == "in_progress":
        task.status = "in_progress"
        item.fulfillment_state = "in_progress"
    else:  # "failed"
        _apply_failure(task=task, item=item, result=result)

    return task


def _apply_failure(*, task: FulfillmentTask, item: OrderItem, result: FulfillResult) -> None:
    """Land a ``failed`` supplier result on the task and its order item.

    Low-balance is the one "failed" mode we deliberately hide from the
    customer: the task lands in the admin inbox, but the order item stays
    ``in_progress`` so the storefront keeps saying "обработка" instead of
    flipping to an error state. The admin will either top up + retry, or
    fulfil manually. It is also the one failure with **no** money outcome to
    record — nothing has finished happening to the money yet (M3b Task 4 owns
    making that stall visible).
    """
    task.status = "failed"
    task.failed_at = now()
    task.last_error = result.error

    if result.error == _LOW_BALANCE_ERROR:
        item.fulfillment_state = "in_progress"
        _dispatch_alert(_maybe_alert_low_balance(task=task, result=result))
        return

    item.fulfillment_state = "failed"
    _record_or_warn(task, result.money_outcome, discovered="fulfill")


# ---------- the merchant deposit, after a terminal failure ----------

#: Recorded on the refund's ledger transaction. A closed internal label, not a
#: supplier's or an operator's words: the row is readable through the admin
#: audit feed.
_MERCHANT_REFUND_REASON = "fulfillment_failed"


async def _settle_merchant_deposit(db: AsyncSession, *, task_id: str) -> None:
    """Give a merchant back what a failed order took, or call a human.

    The one seam M3b Task 3 adds to the saga. It fires only on
    :attr:`MoneyOutcome.RETURNED` and only on a **merchant** order; ``SPENT``
    and ``UNKNOWN`` post nothing and raise an ops alert instead, because
    refunding money we did not get back is not a safe failure mode.

    **Retail is untouched, and it pays one indexed read to stay that way.**
    :data:`INVENTORY_FAILURE_MONEY_OUTCOME` is ``RETURNED`` and fires whenever
    an inventory route runs dry with nothing to fall back to (see the
    ``decision.strict or decision.fallback is None`` arm in
    :func:`process_task`; a dry warehouse *with* a supplier fallback re-routes
    instead of failing) — a common terminal failure here — so the
    ``merchant_id`` gate is doing real work rather than documenting an
    impossibility. It runs **before** the savepoint and before ``merchants`` is
    imported at all, so a retail task costs one query and no
    ``SAVEPOINT``/``RELEASE`` pair.

    **Why the caller runs this and not ``process_task``.** Under
    ``drain_pending_tasks`` a task runs inside a SAVEPOINT whose crash arm
    answers an unexpected exception by recording ``UNKNOWN`` — the one value
    :func:`record_money_outcome` will never let anything move back down, with
    no operator re-grade path anywhere. A refund that raised inside that
    savepoint would therefore roll back the ``RETURNED`` it was acting on and
    replace it with a permanent "we cannot tell": a refundable failure turned
    unrefundable by the attempt to refund it. So this runs **after** the
    savepoint is released, at each of the **four** sites that can terminally
    fail a merchant task — the drain, an admin retry, the poll/webhook
    reconciler, and an operator rejecting a manual task. Merchant orders are
    enqueue-only by construction (``merchants.orders._enqueue_only``), so no
    merchant task is ever run by the synchronous ``start_for_order`` path,
    and those four are the rest.

    The fourth was nearly missed and is reachable: a B2B-visible **``top_up``**
    SKU with no active ``SkuSupplierMapping`` — and no ``SkuSourcingRule`` at
    all — falls through ``sourcing._resolve_auto`` to ``"supplier:manual"``,
    so ``fail_manual_task`` ends real merchant orders. (An explicit
    ``force_supplier`` rule reaches it too; the mapping is the operative
    absence, and only for ``top_up``.) It records ``UNKNOWN``,
    which refunds nothing — calling the seam there changes no money today. It
    is called anyway, because "safe only because one constant happens to be
    ``UNKNOWN``" is a trap, and the alert earns its place regardless: the
    operator who rejects the task is not necessarily the one who settles the
    deposit.

    ``_apply_cancel`` is deliberately **not** one of these; see its docstring.

    **Everything the refund raises is caught here, and the reason is worth
    reading before anyone narrows it.** The rule this looks like it breaks is
    "no bare ``except Exception`` on the money path", which exists because
    ``main``'s 64decbd hid a circular import behind one for six weeks. That
    rule forbids *swallowing*, and nothing is swallowed here: every exception
    is logged at ``error`` with the order id and raises an ops alert, and the
    log line says whether it was a modelled refusal or a bug, so a
    ``NameError`` is one Loki query away rather than invisible.

    What propagating would buy is nothing, and what it costs is the queue. A
    deterministic crash escapes ``drain_pending_tasks``, rolls back the whole
    batch, returns the task to ``pending``, and is re-run and re-crashed on
    the next tick — for ever, taking up to ``limit`` other orders' completed
    work with it each time. That is the **livelock** that function's own
    docstring names as the entire reason its savepoint exists, and it would
    be a total fulfilment outage for the storefront as well as for resellers.

    Catching is safe in the only way that matters: this runs **outside** that
    savepoint, so it cannot reach the crash arm and therefore cannot write
    ``UNKNOWN``. The task keeps the ``RETURNED`` it earned and stays
    refundable by hand.

    Args:
        db: Session. The caller owns the transaction. The task's failure must
            already be durable in it — see above.
        task_id: The task that has just terminated.
    """
    # **Outside the try and outside the savepoint below, and the only statement
    # that is.** It flushes the *caller's* pending writes — the task's failure,
    # its item, the crash arm's attempt row — not this function's. Containing
    # it in the savepoint would mean a rollback here discarded the very
    # failure record the refund exists to act on, which is ruling 4's poison
    # arriving from the other side; and swallowing it would let the batch
    # continue on a session that cannot write. It also cannot introduce a
    # failure that was not already there: without this call the same writes
    # are flushed a few lines later by the caller anyway. What it buys is that
    # nothing pending is left for autoflush to drag *into* the savepoint,
    # where a rollback would take it back out again.
    await _flush_caller_writes(db)

    # **The merchant gate, ahead of the savepoint.** One indexed read, and a
    # retail task pays that and nothing else: no task reload, no order read,
    # no item read, and no SAVEPOINT/RELEASE pair.
    # ``INVENTORY_FAILURE_MONEY_OUTCOME`` is ``RETURNED`` and fires whenever an
    # inventory route runs dry with no fallback to switch to, which is a common
    # terminal failure here, so "retail is untouched" has to mean round trips
    # and not only behaviour.
    #
    # It is **inside the try and outside the savepoint**, and those are two
    # different things — a distinction this function got wrong once. Inside the
    # try, because a fault here must be reported like any other; outside the
    # savepoint, because opening one for a read that retail never gets past is
    # the cost Minor 4 removed.
    #
    # What that trades, stated rather than implied: a transaction-poisoning
    # fault here is **reported but not repaired**. There is no savepoint to
    # roll back to, so the enclosing transaction stays aborted and the rest of
    # the batch fails behind it — which the worker recovers by rolling back and
    # re-ticking, and which is not reachable deterministically anyway
    # (``one_or_none()`` over a primary-key join cannot raise ``MultipleResults``,
    # and ``_flush_caller_writes`` has just run, so autoflush has nothing left
    # to fail on). A dying session is the only way in, and a dying session is
    # not something a savepoint fixes.
    #
    # A plain dict carries the order id out to the failure path: an operator
    # settles by it, and it cannot be read back off an ORM object there,
    # because a savepoint rollback expires those. A ``str`` in a ``dict``
    # survives it. It is filled in only once the read has succeeded, which is
    # why the handler reads it with ``.get``.
    seen: dict[str, str] = {}
    try:
        row = await _merchant_of_task(db, task_id)
        if row is None:
            return
        seen["order_id"] = row.id
        # One savepoint over the whole body, not just the posting. Two things
        # need it. A refusal must roll back a half-written posting without
        # touching the failure record above — that was always true — and a
        # ``SQLAlchemyError`` from any of the reads below poisons the
        # enclosing transaction, which this function is *not* the owner of:
        # it runs outside ``drain_pending_tasks``' per-task savepoint, so
        # there would be nothing between a swallowed error and the rest of the
        # batch running on a dead session. ``ROLLBACK TO SAVEPOINT`` clears
        # the aborted state; catching without one would not.
        async with db.begin_nested():
            await _settle_merchant_deposit_inner(db, task_id=task_id, seen=seen)
    except Exception as exc:  # noqa: BLE001 -- see the docstring: propagating livelocks the whole fulfilment queue, and nothing is swallowed -- every exception is logged at ``error`` and alerted, tagged by whether it was modelled.
        # **This handler is the last thing between a bug and a queue outage,
        # so it gets a guard of its own.** An ``except`` arm is outside its own
        # ``try`` by construction: fix round 2 put a lazy
        # ``from ...refund import RefundError`` here, and on the one failure
        # the widened catch was widened *for* — ``merchants.refund``
        # unimportable, the 64decbd shape every document cites — the body's
        # import raised, control arrived here, and this import raised too, so
        # ``ImportError`` escaped the drain with no line and no alert. The
        # classification below no longer imports anything (see
        # :func:`_is_modelled`), and the rest is wrapped so that a raise from
        # ``_crash_detail`` or ``_dispatch_alert`` degrades to one bare line
        # instead of to a stalled queue.
        try:
            # ``_crash_detail``, not ``str(exc)`` and not ``log.exception``: a
            # SQLAlchemy error stringifies as the driver message, then the
            # full statement, then its **bound parameters** — customer email,
            # delivery address (AGENTS.md §9). Its first-line-plus-cap rule is
            # what keeps those out of the log, and a traceback would put them
            # straight back.
            #
            # ``modelled`` is the whole difference between an ordinary refusal
            # — an order support already settled, a database hiccup — and a
            # bug in this code. Both leave the deposit for a human; only one
            # is ours to go and fix, and a log line that could not tell them
            # apart is what "swallowed" would actually mean.
            detail = _crash_detail(exc)
            log.error(  # noqa: TRY400 -- see above: no traceback on this path
                "merchant_refund.failed",
                order_id=seen.get("order_id", "?"),
                task_id=task_id,
                supplier=seen.get("supplier", "?"),
                modelled=_is_modelled(exc),
                error=detail,
            )
            _dispatch_alert(
                _alert_merchant_refund_failed(
                    task_id=task_id, order_id=seen.get("order_id"), error=detail
                )
            )
        except Exception:  # noqa: BLE001 -- nothing may escape the reporter; see above
            log.error(  # noqa: TRY400 -- the fallback cannot afford to format anything
                "merchant_refund.reporting_failed", task_id=task_id
            )


def _is_modelled(exc: BaseException) -> bool:
    """Is this an exception the refund path models, or a bug in it?

    **It resolves ``RefundError`` without importing anything**, and that is the
    point rather than an optimisation. This runs inside
    :func:`_settle_merchant_deposit`'s ``except`` arm, which is outside its own
    ``try``; an import there fails on exactly the case the arm exists to
    report — ``merchants.refund`` unimportable, or a cycle that leaves
    ``RefundError`` unbound part-way through ``refund.py`` — and an
    ``ImportError`` raised while reporting an ``ImportError`` escapes the drain
    and stalls the queue.

    ``sys.modules.get`` and ``getattr`` cannot raise. A module that never
    loaded, or loaded only part-way, yields no class and the answer is
    ``False`` — which is the right answer, because an import that did not work
    *is* a bug in this code and not a refusal the module modelled.

    Args:
        exc: What the seam raised.

    Returns:
        ``True`` for a modelled refusal or an error the database itself
        reported; ``False`` for anything else, which is the signal worth
        paging on.
    """
    module = sys.modules.get("yupay.modules.merchants.refund")
    refund_error = getattr(module, "RefundError", None)
    if isinstance(refund_error, type) and issubclass(refund_error, BaseException):
        return isinstance(exc, refund_error | AppError | SQLAlchemyError)
    return isinstance(exc, AppError | SQLAlchemyError)


async def _merchant_of_task(db: AsyncSession, task_id: str) -> Row[tuple[str | None, str]] | None:
    """The task's order, if it belongs to a merchant. One indexed read.

    The gate that keeps retail out of the refund seam, in a function of its own
    so the seam's own placement is nameable and testable — this read has now
    been on both sides of the ``try`` and the difference was invisible in a
    diff.

    Args:
        db: Session. The caller owns the transaction.
        task_id: The task that has just terminated.

    Returns:
        The ``(merchant_id, order_id)`` row for a merchant order, or ``None``
        for a retail one and for a task whose order has gone.
    """
    row = (
        await db.execute(
            select(Order.merchant_id, Order.id)
            .join(FulfillmentTask, FulfillmentTask.order_id == Order.id)
            .where(FulfillmentTask.id == task_id)
        )
    ).one_or_none()
    return row if row is not None and row.merchant_id is not None else None


async def _flush_caller_writes(db: AsyncSession) -> None:
    """Persist whatever the caller has pending, before the seam's savepoint.

    A named function for one statement, because the boundary it draws is the
    one thing :func:`_settle_merchant_deposit` deliberately does **not** make
    exception-safe, and a boundary that cannot be named cannot be tested. See
    the call site for why it is outside, and
    ``test_a_failure_to_persist_the_callers_writes_is_not_turned_into_unknown``
    for the property that depends on it.

    Args:
        db: Session. The caller owns the transaction.
    """
    await db.flush()


async def _settle_merchant_deposit_inner(
    db: AsyncSession, *, task_id: str, seen: dict[str, str]
) -> None:
    """The seam's body. Runs inside a savepoint; may raise.

    Split out so :func:`_settle_merchant_deposit` can wrap **all** of it —
    the lazy import and the three reads included — in one savepoint and one
    catch. Fix round 1 wrapped only the posting, which left a deterministic
    fault in any of these reads propagating out of ``drain_pending_tasks``
    with no log line and no alert: the livelock, arriving from a line nobody
    had looked at.

    Args:
        db: Session. The caller owns the transaction.
        task_id: The task that has just terminated. Already known to belong to
            a merchant order — the caller gates on that before the savepoint.
        seen: Filled in with the plain-``str`` facts the caller's failure path
            needs. The caller seeds ``order_id`` (it has one by the time it
            opens the savepoint, and an alert without it is useless); this
            adds the supplier.
    """
    task = await _load_task(db, task_id)
    # ``money_outcome_of`` outlives the failure that wrote it (``retry_task``
    # does not clear it), so the pair its docstring requires is checked here:
    # a task that failed and then succeeded on a retry still answers, and
    # refunding on that would give away the goods and the money.
    if task.status != "failed":
        return
    outcome = money_outcome_of(task)
    if outcome is None:
        return
    # The merchant gate already ran, ahead of the savepoint — this is the row
    # itself, which ``refund_order`` needs.
    order = (await db.execute(select(Order).where(Order.id == task.order_id))).scalar_one()
    order_id = order.id
    supplier = task.supplier
    seen["supplier"] = supplier or "?"

    # The **item**, not just the task, and the rule is inherited rather than
    # invented: a supplier that refuses for lack of *our* balance fails the
    # task but deliberately leaves the item ``in_progress``, so the storefront
    # keeps saying "обработка" while an operator tops up and retries.
    # ``order_status._failure_reason`` reads the item for that same reason.
    #
    # It matters here because ``money_outcome`` outlives the attempt that
    # wrote it and the stall records none: a task that failed ``RETURNED``,
    # whose refund then failed, and which an admin retried into a stall,
    # arrives here still carrying the earlier attempt's verdict. Refunding
    # then would return the money for an order we are about to deliver, and
    # would publish ``refunded_usd`` against a ``failure_reason`` of ``null``.
    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    if item.fulfillment_state != "failed":
        return

    if outcome is not MoneyOutcome.RETURNED:
        _dispatch_alert(
            _alert_merchant_needs_a_human(
                task_id=task_id, order_id=order_id, supplier=supplier, outcome=outcome
            )
        )
        return

    # Imported here, not at module scope: ``merchants`` imports this module
    # (``order_status.py``, for the delivery artifact and its allow-list), so
    # a module-scope import back would close the cycle and break every caller
    # that is not already inside the app. Same discipline, and same reason,
    # as ``orders.service``'s reach for ``affiliate.discount``. It sits inside
    # the caller's try, so an ImportError here is reported rather than fatal.
    from yupay.modules.merchants import refund as merchant_refund

    txn = await merchant_refund.refund_order(db, order=order, reason=_MERCHANT_REFUND_REASON)
    log.info(
        "merchant_refund.posted",
        order_id=order_id,
        task_id=task_id,
        supplier=supplier,
        transaction_id=txn.id,
    )
    # Inside the same savepoint as the posting, deliberately: the money going
    # back and the order ending are one fact, and a fault while closing it must
    # take the posting with it rather than leave a refunded order still reading
    # "in progress". The caller's ``except`` then alerts and the failure stays
    # refundable by hand, which is the safe direction.
    await end_a_refunded_merchant_order(
        db,
        order=order,
        by="fulfillment",
        reason=_MERCHANT_REFUND_REASON,
        actor="fulfillment",
        task_id=task_id,
    )


async def end_a_refunded_merchant_order(
    db: AsyncSession, *, order: Order, by: str, reason: str, actor: str, task_id: str | None = None
) -> None:
    """Close a merchant order whose whole charge has come back (M3c Tasks 6 and 4).

    **Two callers, and the second is why this is public.** Task 6 wrote it for
    the drain's automatic refund; M3c Task 4 gives it to
    ``merchants.deposit.credit_deposit``, so a settlement a person books ends
    the order identically. What ends an order is that the money is back, not
    who decided it — and until Task 4 a hand settlement left ``fulfilling``,
    ``delivered_at IS NULL`` and the five-minute stuck-order alert firing about
    money that was already returned.

    **Why the second caller is the posting and not the button.** The admin SPA
    grew a settle button on the order page in the same task, and putting the
    closure there would have left the runbook's ``curl`` procedure and M4's
    cabinet with the old inconsistency — the very one this closes, only harder
    to find, because it would then depend on which surface an operator used.
    At the posting, *every* caller closes identically, including ones nobody
    has written yet.

    **The reviewer's counter-proposal, and why it loses.** It was to compose at
    the admin service layer — ``credit_deposit`` then this closer, in one
    transaction — keeping the money primitive money-only, on the grounds that
    ``credit_deposit`` has three uses under one signature (a prepayment, a
    settlement, a stage of one). Two things defeat it. First, the primitive is
    *already* not money-only: ``_refuse_over_settlement`` refuses a credit that
    would take **the order** past what it charged, so an order-level invariant
    is in its contract, and this is the same invariant's other half — the
    refusal above the total and the closure at the total. Second, a rule
    enforced at one call site is a rule with a hole; the three uses are not
    three code paths but three answers from one predicate
    (``refund.settled_in_full``): a prepayment names no order and never reaches
    it, a partial is declined by it, a full settlement closes.

    The objection it rests on is real and is not dismissed: **a money endpoint
    now writes order state.** That is acceptable here because the write is a
    *consequence* of the money reaching a known total rather than an action of
    its own, it is idempotent (``FAILABLE_STATUSES`` excludes an order already
    closed), it fires only on a full settlement, and the alternative is an
    inconsistency that depends on which door the operator walked through.

    **Why the status moves here and nowhere else.** Retail's rule is that a
    terminal fulfilment failure leaves ``order.status`` alone, because an
    operator may still top a supplier up, retry, or deliver by hand — the order
    is not over. That reason is **false for a refunded order**: both *admin*
    delivery routes, :func:`retry_task` and :func:`complete_manual_task`,
    already refuse it with ``409 deposit_already_returned``, because delivering
    it would hand the reseller the goods *and* their money. The state said "in
    progress" about an order support could not move, and an owner found that at
    05:30 on the alert it kept firing.

    **The drain is the exit those two do not cover, and saying otherwise was a
    real defect** (M3c fix round 1). ``drain_pending_tasks`` claims on
    ``status == 'pending'`` alone, so an order closed while a task was still
    open would have been bought from the supplier afterwards. From *this*
    caller it cannot happen — the seam runs on a task that has just terminally
    failed — but the hand settlement could reach it, and
    ``merchants.deposit._refuse_a_still_fulfilling_order`` is what closes it
    there. Do not restore the old sentence: "every way of delivering one is
    already refused" was never true of the queue.

    **``failed``, not a new value, and the contract decides it.** The module
    README tells integrators to treat an unknown ``status`` as *still in
    flight*, so a ``refunded`` invented today would be polled for ever by
    everyone already integrated and their end customers never settled — worse
    than doing nothing. ``failed`` is published, documented as reachable "from
    any of the first three", and terminal. What the money did is carried by
    ``failure_reason: fulfillment_failed_refunded`` and ``refunded_usd``, which
    already exist — and ``order_status._failure_reason`` had to have its
    precedence corrected in the same commit, or the status this sets would have
    collapsed that reason to ``order_failed``.

    **Only on a full settlement**, asked of the ledger through
    ``refund.settled_in_full`` — the same pure predicate ``_failure_reason``
    and the cancellation alert use, never a second comparison. Note what the
    guard is worth *through the saga*: ``refund_order`` posts exactly what the
    charge took and refuses any order money has already come back on, so by the
    time the seam gets here the answer is always yes. **Do not read that as
    "untested".** Calling this function directly reaches it, which is what
    ``test_a_partial_settlement_is_not_closed_by_the_closer_itself`` does, and
    the harness row ``close_ignores_a_partial_settlement`` deletes this line and
    expects that test red. The same holds for ``FAILABLE_STATUSES`` above it
    (``test_a_delivered_order_is_never_closed_by_a_refund``,
    ``close_ignores_a_delivered_order``). An earlier draft of both this comment
    and the harness declared them unfalsifiable; the harness's docstring records
    why that was wrong, and this comment used to repeat the mistake.

    The rule the settlement guard protects is that **money is still owed**, so
    the order is not over — not that closing would take away a retry. It would
    not: :func:`_refuse_a_settled_merchant_order` already refuses ``retry_task``
    and ``complete_manual_task`` on *any* returned amount, so a partially
    settled order has lost its retry already. It is written here rather than
    left to the caller because the settlement a person books by hand is the
    second caller — since Task 4 an actual one, not an anticipated one — and it
    is the one that can be partial.

    ``FAILABLE_STATUSES`` is the same shape: a merchant order at this seam is
    always ``fulfilling``, so it never rejects one *here*, and what it keeps out
    is a ``delivered`` order — the codes are already handed over and reversing
    that is a refund, which moves real money and belongs to ``payments``.

    Three consequences follow, and each was measured rather than assumed:

    * the admin list stops rendering «В работе» and shows «Проблемный» in the
      danger tone, which is what an operator needed;
    * ``orders.service.list_stuck_paid_orders`` stops matching it — its
      ``STUCK_STATUSES`` is ``paid``/``fulfilling``/``fulfilled`` — so the
      five-minute watchdog goes quiet **without** learning anything about
      merchants;
    * the move goes through ``on_order_status_changed``, the one seam, so
      ``order.status_changed`` fires and a webhook subscriber learns about the
      refund by **push**. The README said the opposite for this case and says
      this now.

    The ``OrderEvent`` is ``order.failed`` — a kind already in
    ``order_status.TIMELINE_EVENTS`` and already published for this channel, so
    a reseller's timeline gains a line and not a word it does not know. A
    terminal status with nothing on the timeline explaining it would be the odd
    thing.

    **The order row is not locked, and one half of what that costs is new.**
    Neither this function nor ``mark_order_failed_admin`` takes the order row,
    and both test ``status in FAILABLE_STATUSES`` on their own READ COMMITTED
    snapshot — so a drain refunding while an operator presses «Отметить
    проблемным» can have both pass and both write. Two duplicates follow, and
    they are not the same kind of thing:

    * a duplicate ``order.status_changed`` webhook. **Inherited**, not
      introduced: delivery is at-least-once by contract and every event carries
      a signed ``delivery_id`` for the receiver to dedupe on.
    * a duplicate ``order.failed`` **timeline row**, and this one *is* new.
      Before M3c Task 6 that kind had exactly one writer, so two lines could
      not occur; the timeline is contract (``order_status.TIMELINE_EVENTS``),
      and a reseller reading two endings for one order has no way to tell them
      apart, because no payload is published.

    Money is safe either way — ``wallet.service.post`` resolves the unique-key
    violation into a replay — and the fix, if the duplicate is ever observed,
    is a locked re-read here. It is not taken now because it would make this
    the second site in the codebase that locks the order row for a *failure*
    (:func:`_try_settle_order` is the first, and locks for the *delivered*
    transition, with its own docstring saying why). Recorded rather than fixed,
    deliberately, so that the next person meeting a doubled timeline finds this
    paragraph instead of rediscovering it.

    Args:
        db: Session. The caller owns the transaction — inside the seam's
            savepoint for the drain, inside the admin request's transaction for
            the settlement.
        order: The settled order, already carrying its ``merchant_id``.
        by: Which writer this is, recorded on the timeline payload:
            ``fulfillment`` for the drain, ``settlement`` for a credit booked
            by a person. Neither is published — see above — but the admin audit
            feed reads them, and ``admin`` is taken by
            ``mark_order_failed_admin``.
        reason: The internal label recorded beside ``by``. A closed word, not
            an operator's or a supplier's own text: this row is readable
            through the admin audit feed.
        actor: The ``OrderEvent.actor``: ``fulfillment`` for the drain, the
            credit's own ``admin:<id>`` for a settlement. It is what answers
            "who closed this order" a month later.
        task_id: The task that failed, for the log line only. ``None`` on the
            hand path, where no task decided anything.
    """
    # Both lazy, for the reason the seam's own import is: ``merchants`` and
    # ``orders.service`` each import this module at module scope, so a
    # module-level import either way closes the cycle. They sit inside the
    # seam's ``try``, so an ``ImportError`` here is reported rather than fatal.
    from yupay.modules.merchants import refund as merchant_refund
    from yupay.modules.orders import service as orders_svc

    merchant_id = order.merchant_id
    if merchant_id is None:  # pragma: no cover -- refund_order raises first
        return
    # ``orders.service``'s own list, shared rather than respelled: "which
    # statuses may a paid-but-undeliverable order be closed from" is one
    # question, and ``delivered`` must stay out of it on both sides.
    if order.status not in orders_svc.FAILABLE_STATUSES:
        return
    if not await merchant_refund.is_settled_in_full(db, merchant_id=merchant_id, order_id=order.id):
        return

    moment = now()
    order.status = "failed"
    order.updated_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.failed",
            # ``by`` is what tells the three writers of this kind apart:
            # ``fulfillment`` (the drain's automatic refund), ``settlement``
            # (a credit a person booked, M3c Task 4) and ``admin``
            # (``mark_order_failed_admin``, which also carries the operator's
            # own words). No payload is published — the merchant timeline
            # carries a kind and a timestamp and nothing else — so this is for
            # the admin audit feed.
            payload={"by": by, "reason": reason},
            actor=actor,
        )
    )
    await db.flush()
    # The full seam, realtime nudge included. It is a no-op for a merchant
    # order by construction (``publish_order_event`` returns for a NULL
    # ``user_id``, which the actor CHECK guarantees here), so passing
    # ``publish_realtime=False`` would document a suppression that does not
    # exist.
    await _publish_status_changed(db, order)
    log.info("merchant_refund.order_closed", order_id=order.id, task_id=task_id, by=by)


async def _refuse_a_settled_merchant_order(db: AsyncSession, *, task: FulfillmentTask) -> None:
    """Refuse to re-drive a merchant order whose money has already gone back.

    The loophole this closes needs no misbehaviour to reach.
    ``deposit.charge_deposit`` is idempotent on ``merchant-order:{order_id}``,
    so a **second** charge for one order replays the first transaction and
    debits nothing. Refund the deposit, click Retry — the ordinary response to
    a failed task, one button in the admin SPA, and the failure it is for
    looks identical to this one — and a success hands the reseller the goods
    *and* their money, with no code path noticing.

    Refusing is the answer rather than re-charging under a fresh key. A
    reseller who has been told the money is back has very likely already
    settled with their own end customer; silently debiting them again for an
    order they closed is a surprise money movement, and it can fail on a
    balance that no longer covers it, mid-retry. The recovery is the one their
    contract already describes: place a new order.

    It reads the same sum ``refunded_usd`` publishes, so it catches a **hand**
    settlement too — support crediting the order at 10:00 and an operator
    retrying at 10:05 is the same free-goods loophole through a different
    door, and it predates the automatic refund.

    Args:
        db: Session. The caller owns the transaction.
        task: The task about to be re-driven or force-completed.

    Raises:
        ConflictError: ``deposit_already_returned``.
    """
    merchant_id = (
        await db.execute(select(Order.merchant_id).where(Order.id == task.order_id))
    ).scalar_one()
    if merchant_id is None:
        return
    from yupay.modules.merchants import refund as merchant_refund

    returned = await merchant_refund.returned_for_order(
        db, merchant_id=merchant_id, order_id=task.order_id
    )
    if returned <= 0:
        return
    raise ConflictError(
        "this order's deposit has already been returned; delivering it now "
        "would hand over goods nobody paid for",
        code=merchant_refund.CODE_DEPOSIT_ALREADY_RETURNED,
        order_id=task.order_id,
        returned_usd=str(returned),
    )


#: Cap for a crashed task's stored error. Long enough to keep a stack-less
#: message useful in the admin UI, short enough that a driver that dumps a
#: whole statement can't fill the column (or a log line) with it.
_CRASH_DETAIL_MAX = 500


def _crash_detail(exc: BaseException) -> str:
    """One-line, bounded description of an unexpected task crash.

    Leads with the type because a bare ``str(exc)`` from an unexpected
    exception is often empty or meaningless on its own.

    First line only, then a length cap — both are PII bounds, not cosmetics
    (AGENTS.md §9). This string lands in ``fulfillment_tasks.last_error``,
    which the admin UI shows and the crash log line echoes, and the most
    likely unexpected exception on this path is a SQLAlchemy
    ``IntegrityError``, which stringifies as the driver message, then a
    ``DETAIL: Key (email)=(...)`` line, then the full statement and its
    **bound parameters** — customer email, delivery address. Every one of
    those sits on its own line after the first, so taking the first line
    drops them; the cap bounds whatever a future driver puts on line one.
    """
    lines = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"[:_CRASH_DETAIL_MAX]


async def drain_pending_tasks(db: AsyncSession, *, limit: int = 20) -> int:
    """Claim and run pending fulfilment tasks. The worker's whole job.

    ``FOR UPDATE SKIP LOCKED`` is the entire concurrency story: duplicate
    notifications, a second worker replica, a poll tick racing a NOTIFY —
    whoever locks a row first runs it, everyone else skips. A crashed
    consumer's locks die with its connection and the next tick reclaims.

    Claims ``status='pending'`` only. ``failed`` stays a human decision
    (admin retry), exactly as in the synchronous mode — the async migration
    changes where work runs, never what counts as runnable.

    Each claimed task runs inside its own ``SAVEPOINT``. ``process_task``
    already turns every *expected* supplier failure (``FulfillerError`` /
    ``FulfillerNotIntegratedError``) into a handled ``failed`` task and
    returns normally — the savepoint is for the unexpected kind: a raw
    ``httpx`` error a supplier client forgot to wrap, a bug. Without it,
    that exception would escape this loop and propagate out of
    ``drain_pending_tasks`` entirely — this function never commits, so the
    caller (the worker) would roll back the *whole* connection, discarding
    every already-succeeded task earlier in the same batch. Worse, the
    poisoned task would still be ``pending`` afterwards, so the next tick
    reclaims and crashes on it again — a livelock. The savepoint contains
    the damage to the one task; on rollback we mark that task ``failed`` in
    the (still-good) outer transaction so it leaves the queue for good.
    """
    rows = (
        await db.execute(
            select(FulfillmentTask.id, FulfillmentTask.order_id)
            .where(FulfillmentTask.status == "pending")
            .order_by(FulfillmentTask.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    ran = 0
    settled: set[str] = set()
    for task_id, order_id in rows:
        # Whether the seam below is worth two round trips. Most drained tasks
        # succeed, and a success has no money question — reading it here,
        # from the task ``process_task`` already returned, is what keeps the
        # worker's hot path free of a task reload and an order read per item.
        # ``process_webhook_update`` draws the same line inside its own
        # ``failed`` branch.
        failed = False
        try:
            async with db.begin_nested():
                failed = (await process_task(db, task_id=task_id)).status == "failed"
        except Exception as exc:  # noqa: BLE001 -- a poisoned task must not stall the queue; FulfillerError/FulfillerNotIntegratedError are already handled INSIDE process_task, so only a genuine unexpected crash reaches here.
            # The SAVEPOINT above already rolled back this task's partial
            # writes and expired the ORM objects it touched — same
            # begin_nested()-then-expire behaviour ``complete_manual_task``
            # already relies on. Reload fresh; the claim query's FOR UPDATE
            # lock (held by the outer transaction, unaffected by a
            # SAVEPOINT rollback) means no other consumer could have
            # touched this row meanwhile.
            detail = _crash_detail(exc)
            task = await _load_task(db, task_id)
            item = (
                await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
            ).scalar_one()
            task.status = "failed"
            task.failed_at = now()
            task.last_error = detail
            item.fulfillment_state = "failed"
            # We crashed part-way through the saga. Whether the supplier call
            # went out, and what it cost, is exactly what we do not know.
            record_money_outcome(task, _NOBODY_CAN_SAY)
            await _record_attempt(
                db,
                task=task,
                kind="fulfill",
                status="error",
                payload={"supplier": task.supplier},
                error=detail,
            )
            log.warning(
                "fulfillment.drain.task_crashed",
                task_id=task_id,
                error=detail[:200],
            )
            failed = True
        if failed:
            # Outside the SAVEPOINT above, deliberately: its crash arm answers
            # an unexpected exception with a permanent ``UNKNOWN``, so a refund
            # that raised inside it would convert a refundable failure into an
            # unrefundable one. See ``_settle_merchant_deposit``.
            await _settle_merchant_deposit(db, task_id=task_id)
        settled.add(order_id)
        ran += 1
    for order_id in settled:
        await _try_settle_order(db, order_id=order_id)
    await db.flush()
    return ran


async def retry_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Admin-triggered retry of a failed task.

    Locked: the status check below is only meaningful if nothing can claim
    and run the row between the read and the retry — otherwise an admin
    Retry on a task the consumer picked up a moment ago runs the supplier
    call a second time.
    """
    task = await _load_task(db, task_id, for_update=True)
    if task.status not in ("failed", "pending"):
        raise ConflictError(
            "task is not retryable in its current state",
            extra={"status": task.status},
        )
    # Before anything is written: a retry of an order whose deposit already
    # went back would deliver goods nobody paid for, because a second charge
    # replays its key and debits nothing.
    await _refuse_a_settled_merchant_order(db, task=task)
    task.status = "pending"
    task.last_error = None
    # ``money_outcome`` is deliberately **not** cleared. It is the only memory
    # the next attempt has of what an earlier one may have spent, and
    # ``record_money_outcome`` needs it to refuse a false "we still have the
    # money" from a replay. See that function.
    task.failed_at = None
    task.updated_at = now()
    await db.flush()
    task = await process_task(db, task_id=task_id)
    await _settle_merchant_deposit(db, task_id=task_id)
    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


#: Routes an admin may move a task *onto*. The warehouse is not a supplier —
#: ``process_task`` would try to issue a code and fall back again — and the
#: manual queue has its own intake (``mode="manual"``) with its own inbox tab;
#: an operator who wants a human to do it sets the rule, not the task.
_NOT_REASSIGNABLE: frozenset[str] = frozenset({INVENTORY_ROUTE, "manual"})


async def reassign_task(
    db: AsyncSession, *, task_id: str, supplier: str, admin_id: str
) -> FulfillmentTask:
    """Move a failed task to another supplier and run it there.

    The case this exists for: the supplier the task was routed to answered
    with an error, or our balance there ran dry, and the operator wants the
    *same* order out through the other channel now — not after editing the
    sourcing rule (which only governs orders that have not been placed yet)
    and not by hand.

    Same preconditions and the same money guard as :func:`retry_task`, and the
    switch is written into the attempt log in the shape the inventory
    fallback already uses (``route_switch``), so a task that changed hands
    reads the same way whoever moved it.

    Refuses what would only fail later: an unknown slug, the warehouse or the
    manual queue, the supplier it is already on, and a supplier whose adapter
    needs a mapping row this SKU does not have.
    """
    slug = supplier.strip().lower()
    task = await _load_task(db, task_id, for_update=True)
    if task.status not in ("failed", "pending"):
        raise ConflictError(
            "task is not reassignable in its current state",
            extra={"status": task.status},
        )
    if slug in _NOT_REASSIGNABLE:
        raise ValidationError(
            f"'{slug}' is not a supplier a task can be moved onto",
            extra={"supplier": slug},
        )
    get_fulfiller(slug)  # NotFoundError on an unknown slug
    if slug == task.supplier:
        raise ConflictError("task is already routed to this supplier", extra={"supplier": slug})

    # Lazy, like the adapters: ``integrations`` reaches back into this package
    # for the registry, and a top-level import here would close that loop.
    from yupay.modules.integrations.models import MAPPING_REQUIRED_SUPPLIERS, SkuSupplierMapping

    if slug in MAPPING_REQUIRED_SUPPLIERS:
        sku_id = (
            await db.execute(select(OrderItem.sku_id).where(OrderItem.id == task.order_item_id))
        ).scalar_one()
        mapped = (
            await db.execute(
                select(SkuSupplierMapping.supplier_slug).where(
                    SkuSupplierMapping.sku_id == sku_id,
                    SkuSupplierMapping.supplier_slug == slug,
                    SkuSupplierMapping.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if mapped is None:
            raise ConflictError(
                f"no active {slug} mapping for this SKU — create it under "
                "Integrations → Mappings first",
                extra={"supplier": slug, "sku_id": sku_id},
            )

    await _refuse_a_settled_merchant_order(db, task=task)

    previous = task.supplier
    task.supplier = slug
    task.status = "pending"
    task.last_error = None
    # ``money_outcome`` stays, for the reason ``retry_task`` gives.
    task.failed_at = None
    task.updated_at = now()
    await _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="ok",
        payload={
            "route_switch": slug,
            "from": previous,
            "reason": "admin_reassign",
            "admin_id": admin_id,
        },
    )
    await db.flush()
    task = await process_task(db, task_id=task_id)
    await _settle_merchant_deposit(db, task_id=task_id)
    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


async def bulk_retry_tasks(
    db: AsyncSession, *, task_ids: list[str]
) -> tuple[list[FulfillmentTask], list[tuple[str, str]]]:
    """Best-effort retry for a batch.

    Each task is replayed via :func:`retry_task`; ones that can't be (unknown id,
    wrong status) are returned in the second tuple with a short reason instead of
    aborting the whole batch. Duplicates in ``task_ids`` are deduped.

    Ids are then **sorted**, so every bulk retry takes its per-task row locks
    in the same global order. Two admins bulk-retrying overlapping selections
    would otherwise be a textbook AB/BA deadlock, and the window is not
    small: ``retry_task`` holds each lock across a live supplier HTTP call.
    The returned ``retried`` order changes with the sort; it is a result set,
    not an ordered contract.

    Sorting does **not** cover bulk-retry vs. a drainer or the reconcile
    sweep, and that variant is accepted rather than fixed: this loop can hold
    an order-row lock (from one iteration's ``_try_settle_order``) while the
    next iteration waits on a task row one of them holds, and that holder waits
    on the same order row. The exposure is tiny — drainers only ever claim
    ``pending`` tasks and the sweep only ``in_progress`` ones, while a human
    bulk-retries ``failed`` ones, and ``process_webhook_update`` deliberately
    takes its task lock *after* the supplier call rather than across it — and
    closing it properly means
    ordering locks across a loop of independent orders, which is a redesign
    of the bulk endpoint rather than a patch. If it ever fires, it is a
    deadlock error on the admin request, safe to retry.
    """
    seen: set[str] = set()
    deduped: list[str] = []
    for tid in task_ids:
        if tid in seen:
            continue
        seen.add(tid)
        deduped.append(tid)
    deduped.sort()

    retried: list[FulfillmentTask] = []
    skipped: list[tuple[str, str]] = []
    for tid in deduped:
        try:
            task = await retry_task(db, task_id=tid)
        except NotFoundError as exc:
            skipped.append((tid, exc.detail))
        except ConflictError as exc:
            status_hint = exc.extra.get("status") if exc.extra else None
            reason = f"not retryable (status={status_hint})" if status_hint else exc.detail
            skipped.append((tid, reason))
        else:
            retried.append(task)
    return retried, skipped


async def _apply_cancel(db: AsyncSession, *, task: FulfillmentTask, reason: str) -> None:
    """Run the supplier cancel hook (best-effort), then flip the task to
    ``cancelled`` and its order item to ``failed``.

    ``ck_order_items_state`` has no ``cancelled`` value, so a cancelled task's
    item lands in ``failed``. Shared by the single-task admin cancel and the
    order/refund cascade — the supplier call is best-effort, a rejection is
    recorded but doesn't block the local state flip (there's nothing to settle
    once the order is gone).

    **On a merchant order this is an unstated money state, and it says so.**
    Cancelling records **no** ``money_outcome`` — so M3b's automatic refund
    never runs — while the deposit stays debited and nothing can move the
    order afterwards: ``retry_task`` and ``complete_manual_task`` both refuse
    a ``cancelled`` task. It is also the shape *most* likely to have left our
    money with us, since a cancel usually precedes any supplier verdict and
    this function calls the supplier's own ``cancel`` hook.

    Refunding it automatically is deliberately **not** done here: cancelling
    is a human action taken for a reason this code cannot see, and inferring
    a refund from it would be the guess :class:`MoneyOutcome` exists to
    forbid. What is not acceptable is the state being *silent*, so a merchant
    task's cancellation logs and alerts, and the runbook says what to do.

    **Only when the order is not already square**, though — measured against
    what it charged, so a partial settlement still alerts.
    ``cancel_open_tasks_for_order`` cancels ``failed`` tasks too, so the
    documented support step after a failed merchant order — close it by hand,
    once the automatic refund has already posted — runs straight through here.
    An alert saying "the deposit is still debited" about an order that reads
    ``refunded_usd: "1.07"`` is wrong on the feature's most common path, and
    an alert that is wrong on the common path is one ops stops reading.
    """
    try:
        # The lookup is **inside** the try, and that is the whole fix. It used
        # to sit above it, so an unknown slug raised before the best-effort
        # promise this docstring makes could apply — and the promise was made
        # by a comment while the line above it broke it.
        #
        # ``INVENTORY_ROUTE`` is not a supplier at all: it is our own
        # warehouse, and ``REGISTRY`` holds external integrations only. Asking
        # for a fulfiller answered ``unknown fulfilment supplier: inventory``,
        # which 404'd the whole ``mark_order_failed_admin`` cascade — so an
        # order our own stock had served could never be closed by hand. Found
        # on production 2026-09-10 by an operator trying to close one.
        #
        # A slug that is unknown for any *other* reason — a retired
        # integration, a typo in a seeded row — gets the same treatment for the
        # same reason: there is nothing to settle once the order is gone, and
        # refusing to close it helps nobody.
        if task.supplier != INVENTORY_ROUTE:
            await get_fulfiller(task.supplier).cancel(db=db, task=task)
        await _record_attempt(
            db,
            task=task,
            kind="cancel",
            status="ok",
            payload={
                "supplier": task.supplier,
                "reason": reason,
                **(
                    {"note": "inventory route — no external supplier to cancel"}
                    if task.supplier == INVENTORY_ROUTE
                    else {}
                ),
            },
        )
    except (FulfillerError, FulfillerNotIntegratedError, NotFoundError) as exc:
        await _record_attempt(
            db,
            task=task,
            kind="cancel",
            status="error",
            payload={"supplier": task.supplier, "reason": reason},
            error=str(exc),
        )
    moment = now()
    task.status = "cancelled"
    task.cancelled_at = moment
    task.updated_at = moment
    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    item.fulfillment_state = "failed"  # see ck_order_items_state — no 'cancelled'

    # See the docstring: a cancelled merchant task leaves a debited deposit
    # against an order nothing can move again. Two bounded reads on an admin
    # action — the first runs for every cancelled task, retail included, and
    # only the second and the alert are merchant-gated.
    merchant_id = (
        await db.execute(select(Order.merchant_id).where(Order.id == task.order_id))
    ).scalar_one()
    if merchant_id is not None:
        # **Only when the money is still out.** ``cancel_open_tasks_for_order``
        # cancels ``failed`` tasks too, so the documented support step for a
        # failed merchant order — close it by hand after the refund has already
        # posted — reaches this line on the feature's *happy* path. Alerting
        # there would say "the deposit is still debited" about an order whose
        # ``refunded_usd`` reads the full charge, and an alert that is wrong on
        # the common path is an alert ops learns to close unread. Which would
        # cost exactly the finding this one exists to make findable.
        from yupay.modules.merchants import refund as merchant_refund

        # Against the **charge**, not against zero. ``returned <= 0`` was a sum
        # read as a flag — the shape this milestone has now met twice — and a
        # one-cent attributed credit would have silenced both the alert and the
        # log line while the other $1.06 sat parked on a task nothing can move
        # again, which is the exact state this alert exists to make findable.
        # One predicate, shared with ``order_status._failure_reason``.
        if not await merchant_refund.is_settled_in_full(
            db, merchant_id=merchant_id, order_id=task.order_id
        ):
            log.warning(
                "merchant_task_cancelled",
                order_id=task.order_id,
                task_id=task.id,
                reason=reason,
            )
            _dispatch_alert(
                _alert_merchant_order_cancelled(
                    task_id=task.id, order_id=task.order_id, reason=reason
                )
            )


async def cancel_task(db: AsyncSession, *, task_id: str) -> FulfillmentTask:
    """Admin-triggered cancellation of a single task. Calls the supplier's
    cancel hook best-effort. Rejects a task that already terminated
    (``succeeded`` / ``cancelled``) — including one that terminated while
    this call was waiting for the row lock."""
    task = await _load_task(db, task_id, for_update=True)
    if task.status in ("succeeded", "cancelled"):
        raise ConflictError(
            "task cannot be cancelled in its current state",
            extra={"status": task.status},
        )
    await _apply_cancel(db, task=task, reason="admin_cancel")
    await db.flush()
    return task


async def cancel_open_tasks_for_order(
    db: AsyncSession, *, order_id: str, reason: str
) -> list[FulfillmentTask]:
    """Cancel every still-open fulfilment task for a terminating order.

    Called when the order is cancelled or its payment refunded (see
    ``orders.service.cancel_order_admin`` and ``payments.service.refund_admin``)
    so the fulfilment saga doesn't keep trying to deliver — or leave a stuck
    ``failed`` task — for an order the customer no longer owns.

    Tasks that already ``succeeded`` are left untouched: the customer already
    received the goods, and a money refund does not retract a delivered code.
    Already-``cancelled`` tasks are skipped, so this is idempotent.

    The load is locked because "already succeeded" has to mean *now*, not
    "when this transaction's snapshot was taken". A refund racing a consumer
    that is mid-flight on the same task waits here for the consumer's commit
    and then sees ``succeeded`` and skips — instead of overwriting it with
    ``cancelled`` and leaving the books saying the money was refunded and
    nothing was delivered.
    """
    cancelled: list[FulfillmentTask] = []
    for task in await _existing_tasks_for_order(db, order_id, for_update=True):
        if task.status in ("succeeded", "cancelled"):
            continue
        await _apply_cancel(db, task=task, reason=reason)
        cancelled.append(task)
    if cancelled:
        await db.flush()
    return cancelled


# ---------- alert dispatch ----------

#: Strong references to in-flight alert tasks. Without them the event loop is
#: free to garbage-collect a pending task mid-send, and the alert vanishes.
_ALERT_TASKS: set[asyncio.Task[None]] = set()


def _dispatch_alert(coro: Coroutine[Any, Any, None]) -> None:
    """Start an alert without making the caller wait for Telegram.

    Alerts fire from inside the saga, mid-transaction. Awaiting them there put
    an outbound HTTP round trip inside a database transaction — latency on the
    fulfilment path and a transaction held open across a third party we do not
    control (AGENTS.md §10). The alert still leaves immediately; only the
    waiting is gone.

    Outside a running loop (a sync script, some test harnesses) there is
    nothing to schedule on, so the coroutine is closed rather than left as an
    un-awaited warning.
    """
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _ALERT_TASKS.add(task)
    task.add_done_callback(_ALERT_TASKS.discard)


# ---------- error alerting ----------

#: How long the same error on the same task stays quiet after the first alert.
#: Consecutive identical failures already collapse into one attempt row
#: (see ``_record_attempt``) and never reach here twice, so this covers the
#: flapping case — error, recovery, same error again — and duplicate delivery
#: from a second worker. An hour is long enough that a task failing every
#: minute costs one message, short enough that an unresolved incident says so
#: again within a shift.
_ERROR_ALERT_DEDUPE_SECONDS = 60 * 60


async def _alert_fulfillment_error(
    task: FulfillmentTask,
    *,
    kind: str,
    error: str | None,
) -> None:
    """Tell ops, immediately, that a fulfilment step failed.

    Never raises and never blocks the saga: an alerting outage must not be
    able to fail an order that is otherwise recoverable, so every failure here
    is swallowed and logged.

    The message deliberately carries no ``fulfillment_data`` — that is where
    the customer's Steam login and player ids live (§9). Supplier error text
    is included because it is the one thing that says *what to do*, truncated
    so a stack trace cannot turn into a wall of chat.
    """
    from yupay.modules.notifications import api as notifications

    detail = (error or "").strip() or "без текста ошибки"
    signature = hashlib.sha1(detail.encode("utf-8")).hexdigest()[:12]  # noqa: S324 -- dedupe key, not a secret
    key = f"alert:fulfill_error:{task.id}:{kind}:{signature}"
    try:
        if await _set_redis_dedupe(key, ttl_seconds=_ERROR_ALERT_DEDUPE_SECONDS):
            return
        text = (
            "<b>🛑 Ошибка фулфилмента</b>\n"
            f"Шаг: <code>{html.escape(kind)}</code> · "
            f"Поставщик: <code>{html.escape(task.supplier or '?')}</code>\n"
            f"Заказ: <code>{task.order_id}</code>\n"
            f"Задача: <code>{task.id}</code>\n"
            f"<pre>{html.escape(detail[:300])}</pre>"
        )
        await notifications.send_admin_alert(text, kind="fulfillment_error")
    except Exception as exc:  # noqa: BLE001 -- alerting must never break a sale
        log.warning(
            "fulfillment.error_alert_failed",
            task_id=task.id,
            kind=kind,
            error=str(exc)[:200],
        )


# ---------- merchant money alerting ----------

#: How long one supplier's "a human must decide" alerts stay quiet after the
#: first. Same window and same reason as the low-balance one: a supplier
#: outage parks fifty merchant orders in a minute and every one of them wants
#: the same person to look at the same inbox. Keyed by supplier **and**
#: outcome, so "waxpeer kept our money" does not silence "we cannot tell about
#: g2b" — two different investigations.
_MERCHANT_MONEY_ALERT_DEDUPE_SECONDS = 15 * 60


async def _alert_merchant_needs_a_human(
    *, task_id: str, order_id: str, supplier: str | None, outcome: MoneyOutcome
) -> None:
    """Tell ops a merchant order failed with money we cannot return automatically.

    ``SPENT`` and ``UNKNOWN`` say different things to the person who reads
    this — one is "go and get our money back", the other is "find out what
    happened" — so the outcome is in the message and in the dedupe key even
    though the automatic refund treats them identically.

    Takes plain strings, not the ORM objects: this runs later, on the event
    loop, after the caller's session has moved on or been rolled back to a
    savepoint that expired them.

    Never raises: an alerting outage must not fail an order (AGENTS.md §9 —
    order ids, amounts and supplier slugs are fine to log; nothing here is
    PII).
    """
    from yupay.modules.notifications import api as notifications

    key = f"alert:merchant_money:{supplier or '?'}:{outcome.value}"
    try:
        if await _set_redis_dedupe(key, ttl_seconds=_MERCHANT_MONEY_ALERT_DEDUPE_SECONDS):
            return
        verdict = (
            "поставщик оставил деньги себе"
            if outcome is MoneyOutcome.SPENT
            else "что с деньгами — выяснить нельзя"
        )
        text = (
            "<b>💸 Заказ реселлера: депозит не вернётся сам</b>\n"
            f"Поставщик: <code>{html.escape(supplier or '?')}</code> · "
            f"<code>{html.escape(outcome.value)}</code> — {verdict}\n"
            f"Заказ: <code>{order_id}</code>\n"
            f"Задача: <code>{task_id}</code>\n"
            "<i>Автовозврат не сработал по правилу, а не по ошибке. "
            "Решение за человеком — см. Fulfilment Inbox и раннбук "
            "merchant-b2b.</i>"
        )
        await notifications.send_admin_alert(text, kind="merchant_money_outcome")
    except Exception as exc:  # noqa: BLE001 -- alerting must never break a sale
        log.warning(
            "fulfillment.merchant_money_alert_failed",
            task_id=task_id,
            error=str(exc)[:200],
        )


async def _alert_merchant_order_cancelled(*, task_id: str, order_id: str, reason: str) -> None:
    """Tell ops a cancelled merchant task has left a deposit against nothing.

    Cancelling is a human action and records no money outcome, so nothing
    refunds and nothing else would ever mention it — while the order becomes
    unmovable (``retry_task`` and ``complete_manual_task`` both refuse a
    ``cancelled`` task). Deduped per **order** for an hour, like the failed
    refund and for the same reason: each one is one reseller's money, and
    collapsing two would lose the order id an operator needs to settle it.

    Never raises, for the same reason as :func:`_alert_fulfillment_error`.
    """
    from yupay.modules.notifications import api as notifications

    try:
        if await _set_redis_dedupe(
            f"alert:merchant_cancelled:{order_id}",
            ttl_seconds=_ERROR_ALERT_DEDUPE_SECONDS,
        ):
            return
        text = (
            "<b>🚫 Отменена задача по заказу реселлера</b>\n"
            f"Заказ: <code>{order_id}</code>\n"
            f"Задача: <code>{task_id}</code>\n"
            f"Причина: <code>{html.escape(reason)}</code>\n"
            "<i>Депозит остаётся списанным, автовозврат сюда не приходит, и "
            "заказ больше нельзя ни повторить, ни закрыть вручную. Реши по "
            "деньгам сам — раннбук merchant-b2b.</i>"
        )
        await notifications.send_admin_alert(text, kind="merchant_order_cancelled")
    except Exception as exc:  # noqa: BLE001 -- alerting must never break a sale
        log.warning(
            "fulfillment.merchant_cancel_alert_failed",
            order_id=order_id,
            error=str(exc)[:200],
        )


async def _alert_merchant_refund_failed(*, task_id: str, order_id: str | None, error: str) -> None:
    """Tell ops an automatic deposit refund did not post.

    Deduped **per order** and for an hour, not per supplier: each one of these
    is one reseller's money sitting where it should not, and collapsing two of
    them into one message would lose the second order id — the only thing an
    operator needs to settle it by hand.

    ``order_id`` may be ``None`` when the fault landed before the seam knew
    which order it was on, and the key then falls back to the **task**. It
    must not fall back to a constant: a literal ``"?"`` in the key would make
    every such failure across every reseller one message an hour, which is the
    opposite of what "one reseller's money is one alert" promises. A task id
    is always available and is one-to-one with an order in practice.

    Never raises, for the same reason as :func:`_alert_fulfillment_error`.
    """
    from yupay.modules.notifications import api as notifications

    try:
        if await _set_redis_dedupe(
            f"alert:merchant_refund_failed:{order_id or f'task:{task_id}'}",
            ttl_seconds=_ERROR_ALERT_DEDUPE_SECONDS,
        ):
            return
        text = (
            "<b>🛑 Автовозврат депозита не прошёл</b>\n"
            f"Заказ: <code>{order_id or 'неизвестен — см. задачу'}</code>\n"
            f"Задача: <code>{task_id}</code>\n"
            f"<pre>{html.escape(error[:300])}</pre>"
            "<i>Заказ остаётся возвращаемым: верни депозит вручную "
            "(раннбук merchant-b2b, «Settling a failed order»).</i>"
        )
        await notifications.send_admin_alert(text, kind="merchant_refund_failed")
    except Exception as exc:  # noqa: BLE001 -- alerting must never break a sale
        log.warning(
            "fulfillment.merchant_refund_alert_failed",
            order_id=order_id,
            error=str(exc)[:200],
        )


# ---------- low-balance alerting ----------


async def _maybe_alert_low_balance(
    *,
    task: FulfillmentTask,
    result: FulfillResult,
) -> None:
    """Send an ops Telegram alert when a supplier rejects an order for
    lack of funds — but only once per supplier per dedupe window.

    Dedupe lives in Redis so the lock survives across uvicorn workers
    and a process restart. A Redis outage degrades to "alert every time"
    rather than "alert never"; we'd rather over-notify than miss the
    incident.
    """
    from yupay.modules.notifications import api as notifications

    extra = result.extra_metadata or {}
    supplier = str(extra.get("supplier") or task.supplier or "unknown")
    key = f"alert:low_balance:{supplier}"

    if await _set_redis_dedupe(key, ttl_seconds=_LOW_BALANCE_ALERT_DEDUPE_SECONDS):
        # Another worker already alerted for this supplier within the
        # window — silently drop this one.
        return

    current = extra.get("current_balance") or "?"
    required = extra.get("required") or "?"
    # supplier/ext_id/variant can echo back supplier- or admin-entered free text
    # (mapping fields) — escape before splicing into a parse_mode:HTML message.
    ext_id = html.escape(str(extra.get("external_product_id") or "?"))
    variant = str(extra.get("external_variant_id") or "")
    variant_line = f"\nНоминал: <code>{html.escape(variant)}</code>" if variant else ""
    text = (
        "<b>⚠️ Низкий баланс поставщика</b>\n"
        f"Поставщик: <code>{html.escape(supplier)}</code>\n"
        f"Продукт: <code>{ext_id}</code>{variant_line}\n"
        f"Баланс: <b>${current}</b> · Нужно: <b>${required}</b>\n"
        f"<i>Задача: {task.id[:8]}… · клиент видит «в обработке».</i>\n"
        f"Пополни счёт и нажми «Повторить» в Fulfilment Inbox."
    )
    await notifications.send_admin_alert(text, kind="supplier_low_balance")


async def _set_redis_dedupe(key: str, *, ttl_seconds: int) -> bool:
    """Return ``True`` if the key was already set (i.e. a previous alert
    is still within the dedupe window).

    Uses SET NX so the check + set is atomic. Swallows Redis errors —
    a dead Redis must not block the saga, and degrading to "alert every
    time" is the right failure mode for an alert dedupe.
    """
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            existed = not await client.set(key, "1", ex=ttl_seconds, nx=True)
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001 -- Redis outage degrades to "alert each time"
        log.warning("alerts.dedupe.redis_unavailable", error=str(exc), key=key)
        return False
    return existed


# ---------- async-supplier reconciliation (webhook & polling) ----------


async def process_webhook_update(
    db: AsyncSession,
    *,
    task_id: str,
) -> FulfillmentTask:
    """Reconcile a task with the supplier after an out-of-band signal.

    Called from the supplier-specific webhook route and from the polling
    actor. We **never** trust the webhook body — instead we ask the
    fulfiller's ``check_status`` for the authoritative view and apply the
    same state transitions the synchronous saga would have done.
    """
    # Unlocked for the supplier round trip. The lock this function needs is
    # taken below, *after* ``check_status`` answers — holding it across a live
    # HTTP call (up to ``gengine_request_timeout_seconds``, and two requests on
    # a paying tick) would park an admin retry or cancel behind the reconcile
    # sweep for tens of seconds, and widen the AB/BA window ``bulk_retry_tasks``
    # documents by the same factor.
    task = await _load_task(db, task_id)
    if task.status in ("succeeded", "cancelled"):
        # Nothing to do — terminal-but-good.
        return task
    if task.status == "failed":
        # Idempotent: a webhook that arrives after manual /fail is a no-op.
        return task

    fulfiller = get_fulfiller(task.supplier)
    try:
        status = await fulfiller.check_status(db=db, task=task)
    except (FulfillerError, FulfillerNotIntegratedError) as exc:
        await _record_attempt(
            db,
            task=task,
            kind="status_check",
            status="error",
            payload={"supplier": task.supplier},
            error=str(exc),
        )
        log.warning(
            "fulfillment.check_status.failed",
            task_id=task.id,
            supplier=task.supplier,
            error=str(exc),
        )
        return task

    # Now take the lock, for the two read-modify-writes below: the
    # ``extra_metadata`` merge, and the standing-value read inside
    # ``record_money_outcome``. Re-loading under the lock also re-reads the
    # status, so a task that terminated while we were talking to the supplier
    # is caught here rather than overwritten — the same reason ``cancel_task``
    # re-checks after waiting for its lock.
    task = await _load_task(db, task_id, for_update=True)
    if task.status in ("succeeded", "cancelled", "failed"):
        log.info(
            "fulfillment.check_status.raced",
            task_id=task.id,
            supplier=task.supplier,
            status=task.status,
        )
        return task

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()

    await _record_attempt(
        db,
        task=task,
        kind="status_check",
        status="ok" if status.outcome != "failed" else "error",
        payload={"supplier": task.supplier, "outcome": status.outcome},
        error=status.error,
    )

    # Persist any structured flags the supplier reported (needs_reconciliation,
    # supplier_refunded, give_amount_shortfall_units) so the admin inbox can
    # filter on them, not just grep last_error. Same merge the fulfill() path
    # does with FulfillResult.extra_metadata.
    if status.extra_metadata:
        task.extra_metadata = {**(task.extra_metadata or {}), **status.extra_metadata}

    if status.outcome == "succeeded":
        task.status = "succeeded"
        task.succeeded_at = now()
        task.last_error = None
        item.fulfillment_state = "delivered"
        if status.artifact_kind and status.artifact is not None:
            # Deliveries are unique on order_item_id — guard against a
            # double-fire by checking first instead of letting the
            # IntegrityError bubble up and abort the session.
            existing = (
                await db.execute(select(Delivery).where(Delivery.order_item_id == item.id))
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    Delivery(
                        id=new_id(),
                        order_item_id=item.id,
                        channel="in_app",
                        artifact_kind=status.artifact_kind,
                        artifact=status.artifact,
                    )
                )
    elif status.outcome == "failed":
        task.status = "failed"
        task.failed_at = now()
        task.last_error = status.error or "supplier reported failure"
        item.fulfillment_state = "failed"
        _record_or_warn(task, status.money_outcome, discovered="check_status")
        # The third and last site that can terminally fail a merchant task.
        # Inside the branch rather than below it so an ordinary
        # still-in-progress tick — which is most of them, every 60 s per open
        # task — does not pay for a task reload it has no use for.
        await _settle_merchant_deposit(db, task_id=task_id)
    # ``in_progress`` — leave the task untouched; the next poll / webhook
    # will fire again.

    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


# ---------- manual fulfilment (admin-driven) ----------


_VALID_ARTIFACT_KINDS = frozenset({"voucher_code", "topup_receipt", "license_key"})
_VALID_DELIVERY_CHANNELS = frozenset({"in_app", "email", "telegram"})


async def complete_manual_task(
    db: AsyncSession,
    *,
    task_id: str,
    artifact_kind: str,
    artifact: dict[str, Any],
    channel: str | None,
    admin_note: str | None,
    admin_id: str,
    proof_url: str | None = None,
    force: bool = False,
) -> FulfillmentTask:
    """Admin marks a task as completed by hand.

    Default behaviour is unchanged: only ``supplier="manual"`` tasks in
    ``in_progress`` can be finalised here, so real supplier tasks can't
    drift away from their upstream's idea of state.

    ``force=True`` is the supplier-side escape hatch: an admin uses it
    when a real supplier rejected the order (typically
    ``supplier_low_balance`` after the operator topped up off-platform
    and delivered the code manually). In that mode we accept any
    supplier and any ``failed | in_progress`` status, and tag the
    audit row + ``extra_metadata.force_complete=True`` so the action is
    distinguishable in the audit feed.
    """
    task = await _load_task(db, task_id)
    if not force:
        if task.supplier != "manual":
            raise ConflictError(
                "task is not a manual task",
                extra={"supplier": task.supplier},
            )
        if task.status != "in_progress":
            raise ConflictError(
                "manual task cannot be completed in its current state",
                extra={"status": task.status},
            )
    elif task.status not in ("in_progress", "failed"):
        raise ConflictError(
            "task cannot be force-completed in its current state",
            extra={"status": task.status},
        )
    # The same free-goods loophole as ``retry_task``'s, through the other
    # button: ``force=True`` accepts any supplier's ``failed`` task and hands
    # the artifact over without touching the ledger. Checked for both modes —
    # a ``manual`` task in ``in_progress`` cannot have been refunded, since a
    # refund only ever follows a failure, so the guard costs one bounded read
    # and removes the need to reason about that each time the guards move.
    await _refuse_a_settled_merchant_order(db, task=task)
    if artifact_kind not in _VALID_ARTIFACT_KINDS:
        from yupay.core.errors import ValidationError

        raise ValidationError(
            f"unsupported artifact_kind: {artifact_kind!r}",
            extra={"allowed": sorted(_VALID_ARTIFACT_KINDS)},
        )
    resolved_channel = channel or "in_app"
    if resolved_channel not in _VALID_DELIVERY_CHANNELS:
        from yupay.core.errors import ValidationError

        raise ValidationError(
            f"unsupported delivery channel: {resolved_channel!r}",
            extra={"allowed": sorted(_VALID_DELIVERY_CHANNELS)},
        )
    if not artifact:
        from yupay.core.errors import ValidationError

        raise ValidationError("artifact must contain at least one key")

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()
    # Captured before the savepoint: its rollback expires ORM instances, and
    # touching ``item.id`` in the except-branch would trigger a lazy refresh.
    order_item_id = item.id

    try:
        # UNIQUE(order_item_id) on ``deliveries`` is the DB-level idempotency
        # guarantee — even if two admins race the in-process status guard,
        # only one row lands. The SAVEPOINT opens BEFORE the Delivery is
        # added: ``begin_nested()`` autoflushes pending state first, so a
        # later savepoint would let the failing INSERT poison the outer
        # transaction instead of rolling back just this block.
        async with db.begin_nested():
            db.add(
                Delivery(
                    id=new_id(),
                    order_item_id=item.id,
                    channel=resolved_channel,
                    artifact_kind=artifact_kind,
                    artifact=artifact,
                )
            )
            moment = now()
            task.status = "succeeded"
            task.succeeded_at = moment
            task.last_error = None
            task.completed_by = admin_id
            task.admin_note = admin_note
            task.updated_at = moment
            new_meta: dict[str, Any] = {}
            if proof_url is not None and proof_url.strip():
                new_meta["proof_url"] = proof_url.strip()
            if force:
                # Audit marker — the admin overrode a real-supplier task
                # instead of completing a regular manual one. Surfaced in the
                # activity feed so it's clear this delivery never passed
                # through the supplier's fulfilment pipeline.
                new_meta["force_complete"] = True
            # A force-complete can land on a task that already failed and
            # recorded what became of our money. That answer is kept: the
            # admin delivered the goods some other way, which says nothing
            # about the supplier spend the failed attempt may have made, and
            # it is the only trace of it. (Not clearing also keeps an ordinary
            # completion a no-op on ``extra_metadata``.)
            if new_meta:
                task.extra_metadata = {**(task.extra_metadata or {}), **new_meta}
            item.fulfillment_state = "delivered"
            await _record_attempt(
                db,
                task=task,
                kind="fulfill",
                status="ok",
                payload={
                    "manual": True,
                    "admin_id": admin_id,
                    **({"force_complete": True} if force else {}),
                },
            )
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "item already has a delivery",
            extra={"order_item_id": order_item_id},
        ) from exc
    await _try_settle_order(db, order_id=task.order_id)
    await db.flush()
    return task


async def fail_manual_task(
    db: AsyncSession,
    *,
    task_id: str,
    reason: str,
    admin_note: str | None,
    admin_id: str,
) -> FulfillmentTask:
    """Admin rejects a manual task (e.g. account suspended, no stock, …).

    Marks the task as ``failed`` with ``reason`` as ``last_error``. The
    order stays in ``fulfilling``; refunds are issued separately through
    ``/admin/payments/{id}/refund`` so the admin keeps explicit control
    over the money side.
    """
    task = await _load_task(db, task_id)
    if task.supplier != "manual":
        raise ConflictError(
            "task is not a manual task",
            extra={"supplier": task.supplier},
        )
    if task.status != "in_progress":
        raise ConflictError(
            "manual task cannot be failed in its current state",
            extra={"status": task.status},
        )
    reason_clean = reason.strip()
    if not reason_clean:
        from yupay.core.errors import ValidationError

        raise ValidationError("reason is required to reject a manual task")

    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))
    ).scalar_one()

    moment = now()
    task.status = "failed"
    task.failed_at = moment
    task.last_error = reason_clean
    task.completed_by = admin_id
    task.admin_note = admin_note
    task.updated_at = moment
    item.fulfillment_state = "failed"
    # A manual SKU has no supplier API, so nothing here can read what an
    # operator did with the money — and this route deliberately leaves the
    # refund to them (see the docstring). "A human decides" is what UNKNOWN
    # means, so recording it changes nothing and hides nothing.
    record_money_outcome(task, _NOBODY_CAN_SAY)
    await _record_attempt(
        db,
        task=task,
        kind="fulfill",
        status="error",
        payload={"manual": True, "admin_id": admin_id},
        error=reason_clean,
    )
    await db.flush()
    # The fourth terminal site. ``UNKNOWN`` refunds nothing, so this moves no
    # money today — it is called so the safety does not rest on which constant
    # this function happens to record, and so a merchant order rejected by
    # hand says out loud that its deposit is still debited.
    await _settle_merchant_deposit(db, task_id=task_id)
    return task


# ---------- order-level settlement ----------


async def _try_settle_order(db: AsyncSession, *, order_id: str) -> None:
    """If every task succeeded, advance the order to ``fulfilled`` then ``delivered``.

    Lock first, then read. The order row is locked before the tasks are even
    looked at, and both the settle-eligibility check and the all-succeeded
    gate are evaluated behind that lock. That ordering is what makes
    settlement exactly-once *and* never-lost with concurrent drainers:

    * **Never duplicated.** Two drainers finishing the last two sibling tasks
      of one order both want to settle it. The loser of the lock re-reads a
      status that is no longer settle-eligible and bails, instead of writing
      a second ``order.delivered`` event, realtime push, and Telegram ping.
    * **Never lost.** This is why the cheap check cannot come first. Split a
      two-task order across two drainers: each holds one task ``succeeded``
      but uncommitted, and each reads the *other's* task as still ``pending``
      (MVCC — neither sees the other's uncommitted write). Both would bail,
      both commit, and the order sits in ``fulfilling`` forever with every
      task succeeded — a state no admin path can repair, because retry and
      cancel both refuse a ``succeeded`` task. Behind the lock the loser
      blocks until the winner commits, re-reads the tasks with a fresh
      READ COMMITTED snapshot, sees them all ``succeeded``, and settles.

    Lock order (system-wide invariant): **fulfilment task rows are locked
    before the order row, everywhere.** The drain loop conforms for free —
    it claims tasks with ``SKIP LOCKED``, which never waits, and only then
    reaches this function. The refund / order-failed / order-cancelled
    cascades conform because they call ``cancel_open_tasks_for_order``
    *before* touching the order row (see the comments there). Hold that line
    and a refund can never deadlock against a drainer.
    """
    # ``populate_existing`` for the same reason as in ``_load_task``: the
    # worker's session is long-lived (``expire_on_commit=False``, batch after
    # batch), so an Order it loaded during an earlier batch would otherwise be
    # served from the identity map at its pre-lock status.
    order = (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if order.status not in ("fulfilling", "paid"):
        return

    # Read behind the lock: this snapshot is taken after the winner's commit,
    # so a sibling task it succeeded is visible here.
    tasks = await _existing_tasks_for_order(db, order_id)
    if not tasks:
        return
    if any(t.status != "succeeded" for t in tasks):
        return

    moment = now()
    order.status = "delivered"
    order.fulfilled_at = order.fulfilled_at or moment
    order.delivered_at = moment
    order.updated_at = moment
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.delivered",
            payload={"tasks": [t.id for t in tasks]},
            actor="fulfillment",
        )
    )

    # Immediate realtime push (in-transaction, not after-commit): the client
    # treats it as a nudge and re-fetches the order, so a rare rollback after
    # this point self-corrects on that refetch.
    await _publish_delivered(order)

    # And the status-change seam, for its **webhook** half only. ``delivered``
    # is the event a reseller actually waits for and this is the one site that
    # reaches it, so skipping the seam here would ship a webhook that never
    # announces the delivery. ``publish_realtime=False`` because the nudge
    # above already went out as ``order.delivered``: routing this site through
    # the nudge as well would start sending every connected retail storefront a
    # second event it has never received.
    await _publish_status_changed(db, order, publish_realtime=False)

    # Telegram push — fire-and-forget *after commit* so a slow / down
    # Telegram never blocks the saga AND the notification's own session can
    # see the persisted delivery rows. Notifications swallow their own
    # errors.
    from yupay.modules.notifications import api as notifications

    order_id = order.id
    notifications.schedule_after_commit(
        db,
        lambda: notifications.notify_order_delivered(order_id),
    )


# ---------- read helpers ----------


#: Artifact keys that ARE safe to show the buyer — the retail customer and,
#: since M2 Task 5, a reseller reading ``GET /merchant/v1/orders/{id}``. An
#: allow-list (not a blocklist) on purpose: a delivery ``artifact`` also
#: carries internal audit/chargeback fields — ``source`` (the upstream
#: supplier), ``external_order_id``, ``inventory_code_id``, ``sku_id``,
#: ``catalogue_name``, raw ``amount_units`` — that MUST NOT leave the API. The
#: DB row keeps everything; admins see it via ``/admin/fulfillment``. A new
#: supplier adding a field defaults to hidden until listed here.
#:
#: It lives beside the rows rather than in ``routes.py`` because it now has
#: two consumers and a second copy would drift in exactly the dangerous
#: direction: a field added to one list and not the other defaults to
#: *visible* on the surface that forgot it.
BUYER_SAFE_ARTIFACT_KEYS: frozenset[str] = frozenset(
    {
        "code",  # single voucher/gift code
        "codes",  # multi-code delivery
        "key",  # license/activation key
        "pin",  # scratch PIN
        "serial",  # serial number
        "steam_login",  # the account the customer themselves entered
        "login",  # generic account login the customer entered
        "message",  # human-readable delivery note
        "note",  # human-readable delivery note (alt key)
        "fulfillment_data",  # the customer's own checkout input, echoed back
        "kind",  # sub-kind of a supplier artifact, e.g. gengine gift vs top-up
        "app_name",  # the Steam app a gift was bought for
        "package_name",  # the Steam gift edition/package name
        "status",  # supplier-reported delivery status, e.g. "shipped"
    }
)


def buyer_safe_artifact(delivery: Delivery) -> dict[str, Any]:
    """The part of a delivery artifact that may leave the API.

    Args:
        delivery: The row, whose ``artifact`` holds everything we recorded.

    Returns:
        Only the keys in :data:`BUYER_SAFE_ARTIFACT_KEYS`. A voucher code is a
        bearer instrument, so this is *not* redaction for its own sake — the
        code is meant to go out; what must not go with it is our supplier's
        name and order id.
    """
    return {k: v for k, v in (delivery.artifact or {}).items() if k in BUYER_SAFE_ARTIFACT_KEYS}


async def list_deliveries_for_order(db: AsyncSession, *, order_id: str) -> list[Delivery]:
    stmt = (
        select(Delivery)
        .join(OrderItem, OrderItem.id == Delivery.order_item_id)
        .where(OrderItem.order_id == order_id)
        .order_by(Delivery.delivered_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_deliveries_for_order_admin(
    db: AsyncSession, *, order_id: str, admin_id: str
) -> list[Delivery]:
    """Delivered artifacts for an order, for support — and an audit trail.

    Support cannot answer "the code doesn't work" without seeing the code that
    was actually issued, but a voucher code is a bearer instrument: whoever
    reads it can redeem it. So every read is recorded on the order timeline
    with the acting admin, making "who looked at this customer's codes" a
    question the audit feed can answer.

    Unlike the customer-facing route this returns the artifact **unfiltered** —
    the internal fields (upstream order id, source, inventory row) are exactly
    what an operator needs when reconciling with a supplier.
    """
    deliveries = await list_deliveries_for_order(db, order_id=order_id)
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="admin.deliveries_viewed",
            payload={"count": len(deliveries)},
            actor=f"admin:{admin_id}",
        )
    )
    await db.flush()
    return deliveries


async def list_tasks_admin(
    db: AsyncSession,
    *,
    order_id: str | None = None,
    supplier: str | None = None,
    status_filter: str | None = None,
    order: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FulfillmentTask], int]:
    """Paged admin listing. Returns ``(rows, total_matching_filter)``.

    ``order`` picks the created-at direction: ``"newest"`` (default) for the
    browse view, where recent activity belongs on page one; ``"oldest"`` for
    the operator work queues (stuck / failed / manual retry), where the
    longest-waiting task is the most urgent. The distinction matters under a
    backlog larger than ``limit``: those queues fetch a capped window and sort
    client-side, so a ``"newest"`` order would silently drop the oldest — and
    most overdue — tasks off the end. ``created_at`` alone is not unique for
    tasks created in the same bulk operation, so ``id`` is the deterministic
    tiebreak in both directions (stable pagination, no row seen twice or
    skipped across pages)."""
    ascending = order == "oldest"
    created_order = (
        FulfillmentTask.created_at.asc() if ascending else FulfillmentTask.created_at.desc()
    )
    id_order = FulfillmentTask.id.asc() if ascending else FulfillmentTask.id.desc()
    # Attempts are deliberately NOT eager-loaded: the list renders a count,
    # never the log, and loading them shipped every attempt of every row.
    # One production task polls its supplier's status once a minute while the
    # order stays open — 1641 rows, 218 kB — so a single page of 50 carried a
    # quarter of a megabyte nothing on screen used. The detail panel pages
    # through `list_attempts_admin(task_id=...)` instead.
    base = select(FulfillmentTask)
    count_stmt = select(func.count()).select_from(FulfillmentTask)
    if order_id is not None:
        base = base.where(FulfillmentTask.order_id == order_id)
        count_stmt = count_stmt.where(FulfillmentTask.order_id == order_id)
    if supplier is not None:
        base = base.where(FulfillmentTask.supplier == supplier)
        count_stmt = count_stmt.where(FulfillmentTask.supplier == supplier)
    if status_filter is not None:
        base = base.where(FulfillmentTask.status == status_filter)
        count_stmt = count_stmt.where(FulfillmentTask.status == status_filter)
    rows = list(
        (await db.execute(base.order_by(created_order, id_order).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return rows, total


async def get_task_admin(db: AsyncSession, task_id: str) -> FulfillmentTask:
    return await _load_task(db, task_id)


async def list_attempts_admin(
    db: AsyncSession,
    *,
    task_id: str | None = None,
    supplier: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[FulfillmentAttempt, str]], int]:
    """Paged admin listing of supplier interaction attempts.

    Returns rows joined with the parent task's supplier slug so the admin
    UI can render "G2B attempts" without a second query per row.

    ``task_id`` narrows the feed to one task's log. That is what lets the
    inbox's detail panel page through attempts instead of receiving every
    one of them at once: a single slow supplier order polls its status once
    a minute for as long as it stays open, and one such task in production
    has 1641 rows behind it.
    """
    base = (
        select(FulfillmentAttempt, FulfillmentTask.supplier)
        .join(FulfillmentTask, FulfillmentTask.id == FulfillmentAttempt.task_id)
        .order_by(FulfillmentAttempt.created_at.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(FulfillmentAttempt)
        .join(FulfillmentTask, FulfillmentTask.id == FulfillmentAttempt.task_id)
    )
    if task_id is not None:
        base = base.where(FulfillmentAttempt.task_id == task_id)
        count_stmt = count_stmt.where(FulfillmentAttempt.task_id == task_id)
    if supplier is not None:
        base = base.where(FulfillmentTask.supplier == supplier)
        count_stmt = count_stmt.where(FulfillmentTask.supplier == supplier)
    if status_filter is not None:
        base = base.where(FulfillmentAttempt.status == status_filter)
        count_stmt = count_stmt.where(FulfillmentAttempt.status == status_filter)
    rows = list((await db.execute(base.limit(limit).offset(offset))).all())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    return [(r[0], r[1]) for r in rows], total


__all__ = [
    "bulk_retry_tasks",
    "cancel_open_tasks_for_order",
    "cancel_task",
    "complete_manual_task",
    "drain_pending_tasks",
    "fail_manual_task",
    "get_task_admin",
    "list_attempts_admin",
    "list_deliveries_for_order",
    "list_tasks_admin",
    "process_task",
    "process_webhook_update",
    "retry_task",
    "start_for_order",
]


# Silence unused-import linter — Iterable is referenced from the docstring/type comments
_ = Iterable, IntegrityError
