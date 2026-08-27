"""Affiliate commission: ledger accounts, accrual, maturation, voiding.

The sweep is idempotent by construction — ``UNIQUE(order_id)`` on
``affiliate_commissions`` — so these tests lean on running it twice rather than
on mocking a scheduler.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# Reach into ``service`` rather than the ``api`` facade: the facade imports the
# wallet router, which pulls in the whole v1 route stack and circles back here.
# The affiliate module's own ledger.py does the same, for the same reason plus
# one more: the scheduler imports it, and a scheduler process has no business
# loading FastAPI routes.
from yupay.modules.wallet import service as wallet_service


def _unique_code(prefix: str) -> str:
    """A collision-free test code.

    Not derived from ``new_id()``: it is a UUIDv7, so its leading characters
    are a timestamp and three codes minted inside one test share them.
    """
    return f"{prefix}{secrets.token_hex(5).upper()}"


pytestmark = pytest.mark.asyncio

AFFILIATE_KINDS = [
    "partner_pending",
    "partner_balance",
    "partner_payout_hold",
    "house_affiliate_expense",
    "house_affiliate_paid",
]


@pytest.mark.parametrize("kind", AFFILIATE_KINDS)
async def test_affiliate_account_kinds_are_postable(db_session: AsyncSession, kind: str) -> None:
    """Every affiliate account kind can be created through the wallet facade."""
    owner_type = "house" if kind.startswith("house_") else "partner"
    account = await wallet_service.ensure_account(
        db_session,
        owner_type=owner_type,
        owner_id="house" if owner_type == "house" else "00000000-0000-0000-0000-000000000001",
        kind=kind,
        currency="UZS",
    )
    assert account.kind == kind
    assert await wallet_service.balance(db_session, account.id) == Decimal("0")


async def test_attribution_is_unique_per_user(db_session: AsyncSession) -> None:
    """A buyer belongs to exactly one partner, enforced by the database."""
    from sqlalchemy.exc import IntegrityError
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import (
        AffiliateAttribution,
        AffiliateCode,
        AffiliatePartner,
    )
    from yupay.modules.users.models import User

    user = User(id=new_id())
    partner_a = AffiliatePartner(id=new_id(), email=f"a-{new_id()}@example.test", status="active")
    partner_b = AffiliatePartner(id=new_id(), email=f"b-{new_id()}@example.test", status="active")
    db_session.add_all([user, partner_a, partner_b])
    await db_session.flush()

    code_a = AffiliateCode(
        id=new_id(),
        partner_id=partner_a.id,
        code=_unique_code("A"),
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    code_b = AffiliateCode(
        id=new_id(),
        partner_id=partner_b.id,
        code=_unique_code("B"),
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    db_session.add_all([code_a, code_b])
    await db_session.flush()

    db_session.add(
        AffiliateAttribution(
            id=new_id(), user_id=user.id, partner_id=partner_a.id, code_id=code_a.id
        )
    )
    await db_session.flush()

    db_session.add(
        AffiliateAttribution(
            id=new_id(), user_id=user.id, partner_id=partner_b.id, code_id=code_b.id
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def _seed_delivered_order(
    db: AsyncSession,
    *,
    total_charged: Decimal,
    commission_percent: Decimal = Decimal("2"),
    currency: str = "UZS",
    delivered: bool = True,
    purpose: str = "catalog",
    with_attribution: bool = True,
) -> tuple[str, str, str]:
    """Create partner + code + user + (optionally) attribution + one order.

    Returns:
        ``(order_id, partner_id, user_id)``.
    """
    from yupay.core.clock import now
    from yupay.core.ids import new_id
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
        code=_unique_code("C"),
        discount_percent=Decimal("5"),
        commission_percent=commission_percent,
    )
    db.add(code)
    await db.flush()

    moment = now()
    order = Order(
        id=new_id(),
        user_id=user.id,
        status="delivered" if delivered else "paid",
        currency=currency,
        total_usd=Decimal("1"),
        total_charged=total_charged,
        purpose=purpose,
        expires_at=moment + timedelta(days=1),
        delivered_at=moment if delivered else None,
    )
    db.add(order)
    await db.flush()

    if with_attribution:
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

    return order.id, partner.id, user.id


async def _partner_balance(db: AsyncSession, partner_id: str, kind: str) -> Decimal:
    account = await wallet_service.ensure_account(
        db, owner_type="partner", owner_id=partner_id, kind=kind, currency="UZS"
    )
    return await wallet_service.balance(db, account.id)


async def test_accrual_posts_commission_to_pending(db_session: AsyncSession) -> None:
    """A delivered, attributed order accrues 2% into the partner's pending account."""
    from sqlalchemy import select
    from yupay.modules.affiliate.accrual import accrue_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    order_id, partner_id, _ = await _seed_delivered_order(
        db_session, total_charged=Decimal("100000")
    )

    assert await accrue_commissions(db_session, hold_days=14) == 1

    row = (
        await db_session.execute(
            select(AffiliateCommission).where(AffiliateCommission.order_id == order_id)
        )
    ).scalar_one()
    assert row.amount == Decimal("2000")
    assert row.status == "pending"
    assert row.currency == "UZS"

    assert await _partner_balance(db_session, partner_id, "partner_pending") == Decimal("2000")


async def test_accrual_is_idempotent(db_session: AsyncSession) -> None:
    """Running the sweep twice pays once. This is the property the whole
    accrue-by-sweep design rests on."""
    from yupay.modules.affiliate.accrual import accrue_commissions

    _, partner_id, _ = await _seed_delivered_order(db_session, total_charged=Decimal("100000"))

    assert await accrue_commissions(db_session, hold_days=14) == 1
    assert await accrue_commissions(db_session, hold_days=14) == 0

    assert await _partner_balance(db_session, partner_id, "partner_pending") == Decimal("2000")


async def test_accrual_skips_undelivered_unattributed_and_topups(
    db_session: AsyncSession,
) -> None:
    """Three orders that must not earn commission."""
    from yupay.modules.affiliate.accrual import accrue_commissions

    await _seed_delivered_order(db_session, total_charged=Decimal("100000"), delivered=False)
    await _seed_delivered_order(db_session, total_charged=Decimal("100000"), with_attribution=False)
    await _seed_delivered_order(db_session, total_charged=Decimal("100000"), purpose="wallet_topup")

    assert await accrue_commissions(db_session, hold_days=14) == 0


async def test_maturation_moves_pending_to_balance(db_session: AsyncSession) -> None:
    """Past its hold date, commission becomes withdrawable — and 'withdrawable'
    is the balance of ``partner_balance``, not a sum over the table."""
    from sqlalchemy import select, update
    from yupay.core.clock import now
    from yupay.modules.affiliate.accrual import accrue_commissions, mature_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    _, partner_id, _ = await _seed_delivered_order(db_session, total_charged=Decimal("100000"))
    assert await accrue_commissions(db_session, hold_days=14) == 1

    # Nothing is due yet.
    assert await mature_commissions(db_session) == 0

    await db_session.execute(
        update(AffiliateCommission).values(available_at=now() - timedelta(seconds=1))
    )
    assert await mature_commissions(db_session) == 1
    assert await mature_commissions(db_session) == 0

    row = (await db_session.execute(select(AffiliateCommission))).scalar_one()
    assert row.status == "available"

    assert await _partner_balance(db_session, partner_id, "partner_pending") == Decimal("0")
    assert await _partner_balance(db_session, partner_id, "partner_balance") == Decimal("2000")


async def test_void_reverses_a_pending_commission(db_session: AsyncSession) -> None:
    """A refund before maturity takes the money back out of pending."""
    from sqlalchemy import select
    from yupay.modules.affiliate import api as affiliate_api
    from yupay.modules.affiliate.models import AffiliateCommission

    order_id, partner_id, _ = await _seed_delivered_order(
        db_session, total_charged=Decimal("100000")
    )
    assert await affiliate_api.accrue_commissions(db_session, hold_days=14) == 1

    assert await affiliate_api.void_commission(db_session, order_id=order_id) is True

    row = (await db_session.execute(select(AffiliateCommission))).scalar_one()
    assert row.status == "void"
    assert await _partner_balance(db_session, partner_id, "partner_pending") == Decimal("0")

    # Voiding again is a no-op, not a second reversal.
    assert await affiliate_api.void_commission(db_session, order_id=order_id) is False
    assert await _partner_balance(db_session, partner_id, "partner_pending") == Decimal("0")


async def test_void_refuses_an_already_matured_commission(db_session: AsyncSession) -> None:
    """After maturity the money may already be inside a payout request, so an
    automatic clawback is refused and left to an admin."""
    from sqlalchemy import select, update
    from yupay.core.clock import now
    from yupay.modules.affiliate import api as affiliate_api
    from yupay.modules.affiliate.models import AffiliateCommission

    order_id, _, _ = await _seed_delivered_order(db_session, total_charged=Decimal("100000"))
    assert await affiliate_api.accrue_commissions(db_session, hold_days=14) == 1
    await db_session.execute(
        update(AffiliateCommission).values(available_at=now() - timedelta(seconds=1))
    )
    assert await affiliate_api.mature_commissions(db_session) == 1

    assert await affiliate_api.void_commission(db_session, order_id=order_id) is False
    row = (await db_session.execute(select(AffiliateCommission))).scalar_one()
    assert row.status == "available"


async def test_void_on_an_order_with_no_commission_is_a_no_op(db_session: AsyncSession) -> None:
    """Cancelling an order nobody earned on must not raise."""
    from yupay.modules.affiliate import api as affiliate_api

    order_id, _, _ = await _seed_delivered_order(
        db_session, total_charged=Decimal("100000"), with_attribution=False
    )
    assert await affiliate_api.void_commission(db_session, order_id=order_id) is False


async def test_accrual_skips_an_order_too_small_to_earn_anything(
    db_session: AsyncSession,
) -> None:
    """A commission that rounds to zero is skipped, not posted.

    Not merely tidiness: ``wallet_postings`` carries
    ``ck_wallet_postings_amount_positive``, so a zero-amount posting is a crash,
    not a harmless no-op. At the 1% floor that means any order under 50 UZS.
    """
    from sqlalchemy import select
    from yupay.modules.affiliate.accrual import accrue_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    await _seed_delivered_order(
        db_session, total_charged=Decimal("40"), commission_percent=Decimal("1")
    )

    assert await accrue_commissions(db_session, hold_days=14) == 0
    assert (await db_session.execute(select(AffiliateCommission))).first() is None
