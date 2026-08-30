"""The auto-refund sweep for expired holds (ADR-0063).

``orders.risk.auto_refund_expired_holds`` is the deadline behind
``hold_for_review``'s alert: a paid catalog order held past
``risk_hold_auto_refund_hours`` gets refunded automatically instead of
sitting forever on an alert nobody acted on. Runs against real Postgres
because the point under test is the selection query (status, purpose, event
age all interacting) and the real refund chokepoint (``payments.service.
refund_admin`` — ledger posting, order FSM, idempotency), not a pure
function `unit/test_order_risk.py` could fake.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Importing yupay.api.v1 first avoids the payments.service <-> wallet.routes
# <-> api.v1 import cycle -- see held_order_refund.py's module docstring and
# test_click_timeout.py, which hits the exact same trap.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.orders.risk import _auto_refund_one, auto_refund_expired_holds
from yupay.modules.payments.models import Payment, PaymentAttempt

pytestmark = pytest.mark.asyncio


def _cfg(*, hours: int = 24) -> Settings:
    """Same shape as `unit/test_order_risk.py`'s own `_cfg`, with the one
    knob this sweep actually reads."""
    base = get_settings().model_dump()
    base["risk_hold_auto_refund_hours"] = hours
    return Settings(**base)


async def _held_order(
    db: AsyncSession,
    *,
    status: str = "paid",
    purpose: str = "catalog",
    total_usd: str = "5",
    held_hours_ago: float,
    tag: str,
    provider: str = "mock",
    user_id: str | None = None,
) -> tuple[Order, Payment]:
    """A minimal order + succeeded payment + `order.held_for_review` event,
    the latter dated `held_hours_ago` in the past.

    No SKUs or order items: `auto_refund_expired_holds` never reads them, and
    `refund_admin`'s fulfilment-cancel step tolerates an order with no tasks.

    ``user_id``, when given, makes this a signed-in order (`guest_email` is
    then left unset -- `ck_orders_user_xor_guest` requires exactly one) --
    needed for a `provider="wallet"` order, since `_book_refund_ledger`
    refuses to refund a wallet payment with no user to credit.
    """
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        guest_email=None if user_id else f"sweep-{tag}@example.test",
        status=status,
        currency="USD",
        total_usd=Decimal(total_usd),
        total_charged=Decimal(total_usd),
        purpose=purpose,
        expires_at=moment + timedelta(days=1),
        paid_at=moment - timedelta(hours=held_hours_ago),
    )
    db.add(order)
    await db.flush()
    payment = Payment(
        id=new_id(),
        order_id=order.id,
        provider=provider,
        status="succeeded",
        amount=Decimal(total_usd),
        currency="USD",
        succeeded_at=moment - timedelta(hours=held_hours_ago),
    )
    db.add(payment)
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.held_for_review",
            payload={"reason": "amount_at_or_above_threshold", "total_usd": total_usd},
            actor="risk",
            created_at=moment - timedelta(hours=held_hours_ago),
        )
    )
    await db.flush()
    await db.commit()
    return order, payment


async def test_a_hold_past_the_deadline_is_refunded(db_session: AsyncSession) -> None:
    order, payment = await _held_order(db_session, held_hours_ago=25, tag="expired")

    n = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))

    assert n == 1
    await db_session.refresh(payment)
    await db_session.refresh(order)
    assert payment.status == "refunded"
    assert order.status == "refunded"
    kinds = [
        e.kind
        for e in (
            await db_session.execute(select(OrderEvent).where(OrderEvent.order_id == order.id))
        ).scalars()
    ]
    assert "order.auto_refund_hold_expired" in kinds


async def test_fresh_holds_released_orders_and_wallet_topups_are_left_alone(
    db_session: AsyncSession,
) -> None:
    # A fresh hold — inside the 24h deadline.
    await _held_order(db_session, held_hours_ago=1, tag="fresh")
    # Held once, but an operator already released it — fulfilment moved the
    # order off `paid`, so it must never be re-selected even though the old
    # `order.held_for_review` event is still on the timeline.
    await _held_order(db_session, held_hours_ago=25, status="fulfilling", tag="released")
    # A wallet top-up held past the deadline — out of scope: `purpose` gates it.
    await _held_order(db_session, held_hours_ago=25, purpose="wallet_topup", tag="topup")

    assert await auto_refund_expired_holds(db_session, settings=_cfg(hours=24)) == 0


async def test_the_sweep_is_idempotent_across_ticks(db_session: AsyncSession) -> None:
    order, payment = await _held_order(db_session, held_hours_ago=48, tag="idempotent")

    first = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))
    assert first == 1

    second = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))
    assert second == 0

    # The gateway (and the ledger) were only ever touched once.
    refund_attempts = (
        await db_session.execute(
            select(func.count())
            .select_from(PaymentAttempt)
            .where(PaymentAttempt.payment_id == payment.id, PaymentAttempt.kind == "refund")
        )
    ).scalar_one()
    assert refund_attempts == 1


async def test_zero_disables(db_session: AsyncSession) -> None:
    await _held_order(db_session, held_hours_ago=999, tag="disabled")

    assert await auto_refund_expired_holds(db_session, settings=_cfg(hours=0)) == 0


async def test_a_held_order_with_no_succeeded_payment_is_skipped(
    db_session: AsyncSession,
) -> None:
    """Defensive branch: a `paid` order has a succeeded payment by
    definition, but if that invariant is ever broken, the sweep must log and
    move on rather than crash the batch.

    Checked two ways: the selection query's succeeded-payment filter keeps
    such an order out of the batch entirely (the outer assertion below), and
    `_auto_refund_one` itself never crashes if it is ever handed one anyway
    (a defence-in-depth check, exercised directly since the query-level
    filter would otherwise make this branch unreachable from here)."""
    moment = now()
    order = Order(
        id=new_id(),
        guest_email="sweep-no-payment@example.test",
        status="paid",
        currency="USD",
        total_usd=Decimal("5"),
        total_charged=Decimal("5"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment - timedelta(hours=25),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.held_for_review",
            payload={"reason": "amount_at_or_above_threshold"},
            actor="risk",
            created_at=moment - timedelta(hours=25),
        )
    )
    await db_session.commit()

    assert await auto_refund_expired_holds(db_session, settings=_cfg(hours=24)) == 0
    assert await _auto_refund_one(db_session, order.id, hours=24) is False


async def test_a_failing_refund_is_skipped_and_the_sweep_continues(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One order's refund blowing up (acquirer down, a stale payment state,
    whatever) must not take the rest of the batch with it — the per-order
    try/except in `auto_refund_expired_holds` logs it and moves on, and its
    `db.rollback()` is what keeps the shared session usable for the next
    order's queries afterwards."""
    from yupay.modules.payments import service as payments_svc

    failing_order, _ = await _held_order(db_session, held_hours_ago=25, tag="boom")
    healthy_order, _ = await _held_order(db_session, held_hours_ago=25, tag="ok")
    # Captured as a plain string rather than read off `failing_order` inside
    # `_flaky` below: `auto_refund_expired_holds`'s `db.rollback()` after the
    # first failure expires every ORM object on the shared session, and a
    # bare (non-awaited) attribute access on an expired instance inside a
    # sync closure raises `MissingGreenlet` instead of lazy-loading.
    failing_order_id = failing_order.id

    real_refund_admin = payments_svc.refund_admin

    async def _flaky(
        db: AsyncSession,
        *,
        payment_id: str,
        admin_id: str,
        amount: Decimal | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> Payment:
        if idempotency_key == f"auto-refund:{failing_order_id}":
            raise RuntimeError("acquirer down")
        return await real_refund_admin(
            db,
            payment_id=payment_id,
            admin_id=admin_id,
            amount=amount,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    monkeypatch.setattr(payments_svc, "refund_admin", _flaky)

    n = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))

    assert n == 1  # only the healthy order made it through
    await db_session.refresh(failing_order)
    await db_session.refresh(healthy_order)
    assert failing_order.status == "paid", "the failing order is untouched, not half-refunded"
    assert healthy_order.status == "refunded"


async def test_a_released_order_is_skipped_not_refunded(db_session: AsyncSession) -> None:
    """CRITICAL regression: the batch snapshots order ids and then processes
    up to `limit` of them sequentially with real gateway calls in between --
    long enough for an operator to release the order (or the fulfilment saga
    to deliver it) in that gap. `_auto_refund_one` re-verifies `status ==
    "paid"` under `SELECT ... FOR UPDATE` immediately before refunding, so a
    status that already moved off `paid` by the time this runs must be a
    clean skip, never a refund on top of goods the customer already has.

    Exercises `_auto_refund_one` directly (as the review that flagged this
    suggested) rather than trying to interpose mid-`auto_refund_expired_holds`
    loop: flipping `order.status` to `fulfilling` here stands in for "the
    release happened after the batch was snapshotted, before this order's
    turn" without needing to hook the loop itself.
    """
    order, payment = await _held_order(db_session, held_hours_ago=25, tag="released-race")
    order.status = "fulfilling"
    await db_session.commit()

    refunded = await _auto_refund_one(db_session, order.id, hours=24)

    assert refunded is False
    await db_session.refresh(payment)
    await db_session.refresh(order)
    assert payment.status == "succeeded", "money must stay put -- the order was already released"
    assert order.status == "fulfilling"
    kinds = [
        e.kind
        for e in (
            await db_session.execute(select(OrderEvent).where(OrderEvent.order_id == order.id))
        ).scalars()
    ]
    assert "order.auto_refund_hold_expired" not in kinds


async def test_a_partially_refunded_hold_is_never_reselected(db_session: AsyncSession) -> None:
    """IMPORTANT regression: an admin partial refund leaves the order
    `paid` (partial refunds don't walk the FSM, see
    `payments.service._apply_refund_reversal`) with its payment
    `partially_refunded`. Without the succeeded-payment filter in the
    selection query, this order would be re-selected and fail
    `refund_admin`'s "already refunded" guard every 15 minutes forever. The
    selection query excludes it outright -- the sweep must select nothing
    and never even attempt (and therefore never `log.exception`) a refund on
    it. Finishing it is the operator's job, per the runbook."""
    order, payment = await _held_order(db_session, held_hours_ago=25, tag="partial")
    payment.status = "partially_refunded"
    await db_session.commit()

    assert await auto_refund_expired_holds(db_session, settings=_cfg(hours=24)) == 0

    await db_session.refresh(order)
    await db_session.refresh(payment)
    assert order.status == "paid", "a partial refund never walks the order FSM"
    assert payment.status == "partially_refunded"


# ---------- C1: cabinet-refund-only acquirers are escalated, not refunded ----------


async def test_a_held_order_on_a_cabinet_only_provider_is_escalated_not_refunded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CRITICAL regression: Payme, Click, and Uzum have no merchant-initiated
    refund API -- their gateways' `refund()` unconditionally raises. Before
    the capability check, `_auto_refund_one` would call `refund_admin` for
    every one of these anyway, hitting the same wall on every 15-minute tick
    forever with no operator ever told. This order must instead be escalated
    exactly once across two sweep runs: one `order.auto_refund_escalated`
    event, no `refund_admin` attempt (asserted two ways below: no
    `PaymentAttempt` row, and `refund_admin` itself raises if called at all
    -- an extra guard against the capability check silently regressing), and
    the second tick must not re-escalate."""
    from yupay.modules.payments import service as payments_svc

    order, payment = await _held_order(
        db_session, held_hours_ago=25, tag="payme-escalate", provider="payme"
    )

    async def _must_not_be_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("refund_admin must never be called for a cabinet-only provider")

    monkeypatch.setattr(payments_svc, "refund_admin", _must_not_be_called)

    first = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))
    second = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))

    # Neither tick refunded anything -- no money moved for this order.
    assert first == 0
    assert second == 0
    await db_session.refresh(order)
    await db_session.refresh(payment)
    assert order.status == "paid", "escalation moves no money and no FSM state"
    assert payment.status == "succeeded"

    refund_attempts = (
        await db_session.execute(
            select(func.count())
            .select_from(PaymentAttempt)
            .where(PaymentAttempt.payment_id == payment.id)
        )
    ).scalar_one()
    assert refund_attempts == 0, "refund_admin was never reached, so it never recorded an attempt"

    kinds = [
        e.kind
        for e in (
            await db_session.execute(select(OrderEvent).where(OrderEvent.order_id == order.id))
        ).scalars()
    ]
    assert kinds.count("order.auto_refund_escalated") == 1, "escalated exactly once, not per tick"
    assert "order.auto_refund_hold_expired" not in kinds


async def test_octo_wallet_and_mock_providers_still_auto_refund(
    db_session: AsyncSession,
) -> None:
    """The mirror case: `_AUTO_REFUNDABLE_PROVIDERS` must not accidentally
    shrink to exclude a provider that genuinely supports a refund -- octo and
    wallet are the two real ones in production; mock is the dev/test
    gateway every other test in this file already relies on implicitly."""
    from yupay.modules.users.models import User

    wallet_user_id = new_id()
    db_session.add(User(id=wallet_user_id, roles=[]))
    await db_session.flush()

    for provider, tag, user_id in (
        ("octo", "octo-refund", None),
        ("wallet", "wallet-refund", wallet_user_id),
        ("mock", "mock-refund", None),
    ):
        order, payment = await _held_order(
            db_session, held_hours_ago=25, tag=tag, provider=provider, user_id=user_id
        )

        n = await auto_refund_expired_holds(db_session, settings=_cfg(hours=24))

        assert n == 1, f"{provider} must still auto-refund as today"
        await db_session.refresh(order)
        await db_session.refresh(payment)
        assert payment.status == "refunded"
        assert order.status == "refunded"
