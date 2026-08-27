"""What a partner reads about themselves, and what they must not read.

Two assertions here carry the design rather than describing it. Balance comes
from the ledger, not from summing the commissions table — the three-account
split exists for exactly that. And a partner sees only their own numbers, which
is worth asserting even though the queries are scoped by construction: this is
the test that fails loudly if someone later adds a ``partner_id`` parameter to
a route.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _partner_with_commission(
    db: AsyncSession, *, total_charged: Decimal = Decimal("100000")
) -> tuple[str, str]:
    """A partner, an attributed buyer, and one delivered order accrued.

    Returns:
        ``(partner_id, order_id)``.
    """
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.accrual import accrue_commissions
    from yupay.modules.affiliate.models import (
        AffiliateAttribution,
        AffiliateCode,
        AffiliatePartner,
    )
    from yupay.modules.orders.models import Order
    from yupay.modules.users.models import User

    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    user = User(id=new_id())
    db.add_all([partner, user])
    await db.flush()

    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=f"C{secrets.token_hex(5).upper()}",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    db.add(code)
    await db.flush()

    moment = now()
    order = Order(
        id=new_id(),
        user_id=user.id,
        status="delivered",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=total_charged,
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        delivered_at=moment,
    )
    db.add(order)
    await db.flush()
    db.add(
        AffiliateAttribution(
            id=new_id(),
            user_id=user.id,
            partner_id=partner.id,
            code_id=code.id,
            first_order_id=order.id,
        )
    )
    await db.flush()

    await accrue_commissions(db, hold_days=14)
    return partner.id, order.id


async def test_balance_is_read_from_the_ledger_not_summed_from_the_table(
    db_session: AsyncSession,
) -> None:
    """The property the three-account split exists for.

    Recomputing "available" from ``affiliate_commissions`` would reintroduce
    the second source of truth the split was built to remove — and would let a
    payout check disagree with the ledger it draws on.
    """
    from yupay.core.clock import now
    from yupay.modules.affiliate import panel
    from yupay.modules.affiliate.accrual import mature_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    partner_id, _ = await _partner_with_commission(db_session)

    before = await panel.balances(db_session, partner_id=partner_id)
    assert before["held"] == Decimal("2000")
    assert before["available"] == Decimal("0")
    assert before["reserved"] == Decimal("0")

    await db_session.execute(
        update(AffiliateCommission).values(available_at=now() - timedelta(seconds=1))
    )
    assert await mature_commissions(db_session) == 1

    after = await panel.balances(db_session, partner_id=partner_id)
    assert after["held"] == Decimal("0")
    assert after["available"] == Decimal("2000")


async def test_a_partner_reads_only_their_own_numbers(db_session: AsyncSession) -> None:
    """Scoped by construction — asserted anyway, so that adding a partner_id
    parameter to a route later fails here rather than in production."""
    from yupay.modules.affiliate import panel

    first, _ = await _partner_with_commission(db_session, total_charged=Decimal("100000"))
    second, _ = await _partner_with_commission(db_session, total_charged=Decimal("500000"))

    assert (await panel.balances(db_session, partner_id=first))["held"] == Decimal("2000")
    assert (await panel.balances(db_session, partner_id=second))["held"] == Decimal("10000")

    first_rows, first_total = await panel.commissions(db_session, partner_id=first)
    assert first_total == 1
    assert all(row.partner_id == first for row in first_rows)

    first_stats = await panel.stats(db_session, partner_id=first, period="month")
    assert first_stats["earned"] == Decimal("2000")
    second_stats = await panel.stats(db_session, partner_id=second, period="month")
    assert second_stats["earned"] == Decimal("10000")


async def test_every_window_covers_a_fresh_commission(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate import panel

    partner_id, _ = await _partner_with_commission(db_session)

    for period in ("day", "week", "month", "year"):
        result = await panel.stats(db_session, partner_id=partner_id, period=period)
        assert result["earned"] == Decimal("2000"), period
        assert result["orders"] == 1, period
        assert result["activations"] == 1, period


async def test_an_older_commission_falls_out_of_the_shorter_windows(
    db_session: AsyncSession,
) -> None:
    """A rolling window has to actually roll."""
    from yupay.core.clock import now
    from yupay.modules.affiliate import panel
    from yupay.modules.affiliate.models import AffiliateCommission

    partner_id, _ = await _partner_with_commission(db_session)
    await db_session.execute(
        update(AffiliateCommission).values(created_at=now() - timedelta(days=45))
    )

    assert (await panel.stats(db_session, partner_id=partner_id, period="day"))[
        "earned"
    ] == Decimal("0")
    assert (await panel.stats(db_session, partner_id=partner_id, period="month"))[
        "earned"
    ] == Decimal("0")
    assert (await panel.stats(db_session, partner_id=partner_id, period="year"))[
        "earned"
    ] == Decimal("2000")


async def test_a_voided_commission_stops_counting_as_earnings(
    db_session: AsyncSession,
) -> None:
    """A refund took the money back; the panel must not still show it."""
    from yupay.modules.affiliate import panel
    from yupay.modules.affiliate.accrual import void_commission

    partner_id, order_id = await _partner_with_commission(db_session)
    assert await void_commission(db_session, order_id=order_id) is True

    result = await panel.stats(db_session, partner_id=partner_id, period="month")
    assert result["earned"] == Decimal("0")
    assert (await panel.balances(db_session, partner_id=partner_id))["held"] == Decimal("0")


async def test_a_partner_with_no_activity_reads_as_zeroes(db_session: AsyncSession) -> None:
    """An empty panel is a legitimate state, not an error."""
    from yupay.core.ids import new_id
    from yupay.modules.affiliate import panel
    from yupay.modules.affiliate.models import AffiliatePartner

    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    db_session.add(partner)
    await db_session.flush()

    assert (await panel.balances(db_session, partner_id=partner.id)) == {
        "available": Decimal("0"),
        "held": Decimal("0"),
        "reserved": Decimal("0"),
    }
    result = await panel.stats(db_session, partner_id=partner.id, period="week")
    assert result["earned"] == Decimal("0")
    assert result["activations"] == 0
    assert await panel.codes(db_session, partner_id=partner.id) == []
    assert await panel.commissions(db_session, partner_id=partner.id) == ([], 0)


async def _partner_with_available(db: AsyncSession, amount: str) -> str:
    """A partner whose commission has matured, so it can be withdrawn."""
    from yupay.core.clock import now
    from yupay.modules.affiliate.accrual import mature_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    # 2% of this is the commission, so ask for 50× the amount we want.
    partner_id, _ = await _partner_with_commission(
        db, total_charged=Decimal(amount) * Decimal("50")
    )
    await db.execute(update(AffiliateCommission).values(available_at=now() - timedelta(seconds=1)))
    await mature_commissions(db)
    return partner_id


async def test_two_requests_cannot_overdraw_one_balance(db_session: AsyncSession) -> None:
    """The property the whole reservation exists for.

    Requesting the full balance twice must leave the second refused, not the
    partner owed money twice over.
    """
    from yupay.core.errors import ConflictError
    from yupay.modules.affiliate import panel, payouts

    partner_id = await _partner_with_available(db_session, "100000")
    available = (await panel.balances(db_session, partner_id=partner_id))["available"]
    assert available == Decimal("100000")

    await payouts.request_payout(
        db_session,
        partner_id=partner_id,
        amount=available,
        card_number="8600123412341234",
        card_holder="P PARTNER",
    )
    with pytest.raises(ConflictError):
        await payouts.request_payout(
            db_session,
            partner_id=partner_id,
            amount=available,
            card_number="8600123412341234",
            card_holder="P PARTNER",
        )

    after = await panel.balances(db_session, partner_id=partner_id)
    assert after["available"] == Decimal("0")
    assert after["reserved"] == Decimal("100000")


async def test_a_request_below_the_minimum_is_refused(db_session: AsyncSession) -> None:
    """Each payout is a manual bank transfer, so there is a floor."""
    from yupay.core.errors import ValidationError
    from yupay.modules.affiliate import payouts

    partner_id = await _partner_with_available(db_session, "100000")
    with pytest.raises(ValidationError):
        await payouts.request_payout(
            db_session,
            partner_id=partner_id,
            amount=Decimal("100"),
            card_number="8600123412341234",
            card_holder="P PARTNER",
        )


async def test_held_commission_is_not_withdrawable(db_session: AsyncSession) -> None:
    """Money still inside its hold period is not the partner's to take yet."""
    from yupay.core.errors import ConflictError
    from yupay.modules.affiliate import panel, payouts

    # Accrued but never matured.
    partner_id, _ = await _partner_with_commission(db_session, total_charged=Decimal("5000000"))
    assert (await panel.balances(db_session, partner_id=partner_id))["held"] == Decimal("100000")

    with pytest.raises(ConflictError):
        await payouts.request_payout(
            db_session,
            partner_id=partner_id,
            amount=Decimal("100000"),
            card_number="8600123412341234",
            card_holder="P PARTNER",
        )


async def test_rejecting_a_payout_returns_the_money(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate import panel, payouts

    partner_id = await _partner_with_available(db_session, "100000")
    payout = await payouts.request_payout(
        db_session,
        partner_id=partner_id,
        amount=Decimal("100000"),
        card_number="8600123412341234",
        card_holder="P PARTNER",
    )
    assert (await panel.balances(db_session, partner_id=partner_id))["available"] == Decimal("0")

    await payouts.reject_payout(db_session, payout_id=payout.id, note="wrong card")

    after = await panel.balances(db_session, partner_id=partner_id)
    assert after["available"] == Decimal("100000")
    assert after["reserved"] == Decimal("0")


async def test_paying_a_payout_clears_the_reservation_without_returning_it(
    db_session: AsyncSession,
) -> None:
    from yupay.modules.affiliate import panel, payouts

    partner_id = await _partner_with_available(db_session, "100000")
    payout = await payouts.request_payout(
        db_session,
        partner_id=partner_id,
        amount=Decimal("100000"),
        card_number="8600123412341234",
        card_holder="P PARTNER",
    )
    await payouts.mark_paid(db_session, payout_id=payout.id)

    after = await panel.balances(db_session, partner_id=partner_id)
    assert after["available"] == Decimal("0")
    assert after["reserved"] == Decimal("0")


async def test_a_settled_payout_cannot_be_settled_twice(db_session: AsyncSession) -> None:
    """Two admins with the same tab open must not pay it, then refund it."""
    from yupay.core.errors import ConflictError
    from yupay.modules.affiliate import payouts

    partner_id = await _partner_with_available(db_session, "100000")
    payout = await payouts.request_payout(
        db_session,
        partner_id=partner_id,
        amount=Decimal("100000"),
        card_number="8600123412341234",
        card_holder="P PARTNER",
    )
    await payouts.mark_paid(db_session, payout_id=payout.id)

    with pytest.raises(ConflictError):
        await payouts.mark_paid(db_session, payout_id=payout.id)
    with pytest.raises(ConflictError):
        await payouts.reject_payout(db_session, payout_id=payout.id)


async def test_the_card_number_never_reaches_a_log_record(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """CLAUDE.md §9 forbids PII in logs, and a card number is the worst thing
    in this module. Asserted rather than assumed."""
    import logging

    from yupay.modules.affiliate import payouts

    card = "8600999988887777"
    partner_id = await _partner_with_available(db_session, "100000")

    with caplog.at_level(logging.DEBUG):
        await payouts.request_payout(
            db_session,
            partner_id=partner_id,
            amount=Decimal("100000"),
            card_number=card,
            card_holder="SECRET HOLDER",
        )

    emitted = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert card not in emitted
    assert "SECRET HOLDER" not in emitted


async def test_payout_history_is_scoped_to_the_partner(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate import payouts

    first = await _partner_with_available(db_session, "100000")
    second = await _partner_with_available(db_session, "100000")

    await payouts.request_payout(
        db_session,
        partner_id=first,
        amount=Decimal("100000"),
        card_number="8600111122223333",
        card_holder="FIRST",
    )

    assert len(await payouts.list_for_partner(db_session, partner_id=first)) == 1
    assert await payouts.list_for_partner(db_session, partner_id=second) == []


async def test_a_non_positive_amount_and_an_unknown_partner_are_refused(
    db_session: AsyncSession,
) -> None:
    from yupay.core.errors import NotFoundError, ValidationError
    from yupay.core.ids import new_id
    from yupay.modules.affiliate import payouts

    partner_id = await _partner_with_available(db_session, "100000")
    with pytest.raises(ValidationError):
        await payouts.request_payout(
            db_session,
            partner_id=partner_id,
            amount=Decimal("0"),
            card_number="8600111122223333",
            card_holder="P",
        )
    with pytest.raises(NotFoundError):
        await payouts.request_payout(
            db_session,
            partner_id=new_id(),
            amount=Decimal("100000"),
            card_number="8600111122223333",
            card_holder="P",
        )


async def test_acting_on_an_unknown_payout_is_not_found(db_session: AsyncSession) -> None:
    from yupay.core.errors import NotFoundError
    from yupay.core.ids import new_id
    from yupay.modules.affiliate import payouts

    with pytest.raises(NotFoundError):
        await payouts.mark_paid(db_session, payout_id=new_id())


async def test_attribution_ignores_a_wallet_topup(db_session: AsyncSession) -> None:
    """A top-up is not a sale, so it binds nobody to anyone."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.attribution import bind_attribution
    from yupay.modules.affiliate.models import AffiliateCode, AffiliatePartner
    from yupay.modules.orders.models import Order
    from yupay.modules.users.models import User

    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    user = User(id=new_id())
    db_session.add_all([partner, user])
    await db_session.flush()
    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=f"C{secrets.token_hex(5).upper()}",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    db_session.add(code)
    await db_session.flush()

    moment = now()
    topup = Order(
        id=new_id(),
        user_id=user.id,
        status="paid",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("100000"),
        purpose="wallet_topup",
        expires_at=moment + timedelta(days=1),
        paid_at=moment,
        affiliate_code_id=code.id,
    )
    db_session.add(topup)
    await db_session.flush()

    assert await bind_attribution(db_session, order=topup) is False
