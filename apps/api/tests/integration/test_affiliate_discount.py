"""Affiliate discount: admission, arithmetic, attribution, and the margin reports.

The reason this module exists at all is the last one. Revenue and margin are
computed from order lines, not from ``total_charged``, so a discount that only
reduced the payable total would be invisible to every report — full margin
shown on precisely the orders that have the least of it.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _unique_code(prefix: str) -> str:
    """A collision-free test code.

    Not derived from ``new_id()``: it is a UUIDv7, so its leading characters
    are a timestamp and codes minted inside one test share them.
    """
    return f"{prefix}{secrets.token_hex(5).upper()}"


async def test_order_carries_discount_columns(db_session: AsyncSession) -> None:
    """The new columns exist and default to "no discount"."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.orders.models import Order

    moment = now()
    order = Order(
        id=new_id(),
        guest_email=f"g-{new_id()}@example.test",
        status="pending_payment",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)

    assert order.affiliate_code_id is None
    assert order.discount_charged == Decimal("0")


async def _seed_partner_and_code(
    db: AsyncSession,
    *,
    discount_percent: Decimal = Decimal("5"),
    active: bool = True,
    partner_status: str = "active",
    linked_user_id: str | None = None,
) -> tuple[str, str]:
    """Create a partner and one code.

    Returns:
        ``(code_id, code)``.
    """
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliateCode, AffiliatePartner

    partner = AffiliatePartner(
        id=new_id(),
        email=f"p-{new_id()}@example.test",
        status=partner_status,
        user_id=linked_user_id,
    )
    db.add(partner)
    await db.flush()

    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=_unique_code("C"),
        discount_percent=discount_percent,
        commission_percent=Decimal("2"),
        active=active,
    )
    db.add(code)
    await db.flush()
    return code.id, code.code


async def _new_user(db: AsyncSession) -> str:
    from yupay.core.ids import new_id
    from yupay.modules.users.models import User

    user = User(id=new_id())
    db.add(user)
    await db.flush()
    return user.id


async def _order(
    db: AsyncSession,
    *,
    user_id: str,
    status: str,
    affiliate_code_id: str | None = None,
    paid: bool = False,
) -> str:
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.orders.models import Order

    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status=status,
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment if paid else None,
        affiliate_code_id=affiliate_code_id,
    )
    db.add(order)
    await db.flush()
    return order.id


async def test_resolve_accepts_a_valid_code_for_a_fresh_buyer(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session, discount_percent=Decimal("7"))
    user_id = await _new_user(db_session)

    result = await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
    assert isinstance(result, ResolvedDiscount)
    assert result.percent == Decimal("7")


async def test_resolve_normalises_case_and_whitespace(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    result = await resolve_code(
        db_session, code=f"  {code.lower()} ", user_id=user_id, purpose="catalog"
    )
    assert isinstance(result, ResolvedDiscount)


async def test_resolve_rejects_a_guest(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import resolve_code

    _, code = await _seed_partner_and_code(db_session)
    assert await resolve_code(db_session, code=code, user_id=None, purpose="catalog") == "guest"


async def test_resolve_rejects_a_wallet_topup(db_session: AsyncSession) -> None:
    """A top-up is a 1:1 deposit. Discounting one prints money."""
    from yupay.modules.affiliate.discount import resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)
    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="wallet_topup")
        == "not_catalog"
    )


async def test_resolve_hides_whether_an_unusable_code_exists(db_session: AsyncSession) -> None:
    """Nonexistent, inactive, and suspended-partner codes are indistinguishable.

    Otherwise the preview endpoint is a directory of other people's codes.
    """
    from yupay.modules.affiliate.discount import resolve_code

    user_id = await _new_user(db_session)
    _, inactive = await _seed_partner_and_code(db_session, active=False)
    _, suspended = await _seed_partner_and_code(db_session, partner_status="suspended")

    for candidate in (_unique_code("Z"), inactive, suspended):
        assert (
            await resolve_code(db_session, code=candidate, user_id=user_id, purpose="catalog")
            == "unknown"
        )


async def test_resolve_rejects_a_buyer_who_already_belongs_to_a_partner(
    db_session: AsyncSession,
) -> None:
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.discount import resolve_code
    from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode

    _, code = await _seed_partner_and_code(db_session)
    other_code_id, _ = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    existing = await db_session.get(AffiliateCode, other_code_id)
    assert existing is not None
    db_session.add(
        AffiliateAttribution(
            id=new_id(),
            user_id=user_id,
            partner_id=existing.partner_id,
            code_id=other_code_id,
        )
    )
    await db_session.flush()

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "already_used"
    )


async def test_resolve_rejects_a_buyer_with_a_prior_paid_order(db_session: AsyncSession) -> None:
    """Deliberately "no prior *paid* order", not "no prior order": an abandoned
    unpaid cart must not disqualify someone forever."""
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    await _order(db_session, user_id=user_id, status="expired")
    assert isinstance(
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog"),
        ResolvedDiscount,
    )

    await _order(db_session, user_id=user_id, status="paid", paid=True)
    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "not_first_order"
    )


async def test_resolve_rejects_a_partner_using_their_own_code(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import resolve_code

    user_id = await _new_user(db_session)
    _, code = await _seed_partner_and_code(db_session, linked_user_id=user_id)

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog") == "own_code"
    )


async def test_resolve_rejects_while_an_unpaid_coded_order_is_open(
    db_session: AsyncSession,
) -> None:
    """Narrows the spec's known gap: without this a buyer could open two orders
    with two codes and pay both, taking two discounts for one attribution."""
    from yupay.modules.affiliate.discount import resolve_code

    code_id, _ = await _seed_partner_and_code(db_session)
    _, second = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    await _order(db_session, user_id=user_id, status="pending_payment", affiliate_code_id=code_id)

    assert (
        await resolve_code(db_session, code=second, user_id=user_id, purpose="catalog")
        == "pending_coded_order"
    )


class TestDistribution:
    """Synchronous arithmetic, kept out of the module-level asyncio mark."""

    def test_splits_proportionally_and_loses_nothing(self) -> None:
        """The parts must sum to the whole — a dropped remainder is money that
        silently reappears as margin."""
        from yupay.modules.affiliate.discount import distribute_discount_usd

        shares = distribute_discount_usd(
            [Decimal("10"), Decimal("20"), Decimal("30")], Decimal("6")
        )
        assert sum(shares) == Decimal("6")
        assert shares[2] > shares[0]

    def test_awkward_thirds_still_sum_exactly(self) -> None:
        """Three equal lines and a discount that does not divide evenly."""
        from yupay.modules.affiliate.discount import distribute_discount_usd

        shares = distribute_discount_usd(
            [Decimal("1"), Decimal("1"), Decimal("1")], Decimal("0.0000010")
        )
        assert sum(shares) == Decimal("0.0000010")

    def test_handles_one_line_and_no_lines(self) -> None:
        from yupay.modules.affiliate.discount import distribute_discount_usd

        assert distribute_discount_usd([Decimal("10")], Decimal("1")) == [Decimal("1")]
        assert distribute_discount_usd([], Decimal("1")) == []
        assert distribute_discount_usd([Decimal("0")], Decimal("1")) == [Decimal("0")]
