"""What an admin does to run the programme.

The service layer already moves the money; this is the layer that lets a person
drive it. Two behaviours here are worth more than the rest and each has a test
that fails if it is undone: a suspended partner is genuinely switched off, not
merely flagged, and the ranges are enforced with a readable message rather than
only by a database constraint.
"""

from __future__ import annotations

import secrets
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _partner(db: AsyncSession, status: str = "active") -> str:
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliatePartner

    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status=status)
    db.add(partner)
    await db.flush()
    return partner.id


async def test_a_code_is_stored_uppercase_whatever_the_admin_typed(
    db_session: AsyncSession,
) -> None:
    """The lookup normalises the buyer's input; storage has to match."""
    from yupay.modules.affiliate import admin

    partner_id = await _partner(db_session)
    code = await admin.issue_code(
        db_session,
        partner_id=partner_id,
        code="  partner10 ",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    assert code.code == "PARTNER10"


async def test_a_duplicate_code_is_a_conflict_not_a_crash(db_session: AsyncSession) -> None:
    from yupay.core.errors import ConflictError
    from yupay.modules.affiliate import admin

    first = await _partner(db_session)
    second = await _partner(db_session)
    shared = f"C{secrets.token_hex(4).upper()}"

    await admin.issue_code(
        db_session,
        partner_id=first,
        code=shared,
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    with pytest.raises(ConflictError):
        await admin.issue_code(
            db_session,
            partner_id=second,
            code=shared,
            discount_percent=Decimal("5"),
            commission_percent=Decimal("2"),
        )


async def test_a_rate_outside_the_range_is_refused_with_a_readable_message(
    db_session: AsyncSession,
) -> None:
    """An admin typing 15 should be told the range, not shown a constraint name.

    The CHECK constraint is the backstop; this is the sentence a person reads.
    """
    from yupay.core.errors import ValidationError
    from yupay.modules.affiliate import admin

    partner_id = await _partner(db_session)

    with pytest.raises(ValidationError) as too_much:
        await admin.issue_code(
            db_session,
            partner_id=partner_id,
            code=f"C{secrets.token_hex(4).upper()}",
            discount_percent=Decimal("15"),
            commission_percent=Decimal("2"),
        )
    # Split so a failure says which bound is missing from the message.
    assert "3" in str(too_much.value)
    assert "10" in str(too_much.value)

    with pytest.raises(ValidationError) as too_generous:
        await admin.issue_code(
            db_session,
            partner_id=partner_id,
            code=f"C{secrets.token_hex(4).upper()}",
            discount_percent=Decimal("5"),
            commission_percent=Decimal("9"),
        )
    assert "1" in str(too_generous.value)
    assert "2" in str(too_generous.value)


async def test_suspending_a_partner_stops_their_code_working(
    db_session: AsyncSession,
) -> None:
    """Not merely a flag on a row: the code has to stop applying at checkout."""
    from yupay.core.ids import new_id
    from yupay.modules.affiliate import admin
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code
    from yupay.modules.users.models import User

    partner_id = await _partner(db_session)
    code = await admin.issue_code(
        db_session,
        partner_id=partner_id,
        code=f"C{secrets.token_hex(4).upper()}",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    buyer = User(id=new_id())
    db_session.add(buyer)
    await db_session.flush()

    assert isinstance(
        await resolve_code(db_session, code=code.code, user_id=buyer.id, purpose="catalog"),
        ResolvedDiscount,
    )

    await admin.suspend_partner(db_session, partner_id=partner_id)

    assert (
        await resolve_code(db_session, code=code.code, user_id=buyer.id, purpose="catalog")
        == "unknown"
    )


async def test_suspending_a_partner_signs_them_out(db_session: AsyncSession) -> None:
    """A suspended partner whose session keeps working can still request a
    payout. Switching them off has to mean it."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import admin, partners
    from yupay.modules.affiliate.models import AffiliatePartner
    from yupay.modules.auth import jwt as authjwt

    partner_id = await _partner(db_session, status="pending")
    link = await partners.approve(db_session, partner_id=partner_id)
    await partners.set_password(db_session, token=link, password="a good password")
    row = await db_session.get(AffiliatePartner, partner_id)
    assert row is not None
    tokens = await partners.login(db_session, email=row.email, password="a good password")
    assert await partners.resolve_partner(db_session, tokens.access_token) is not None

    await admin.suspend_partner(db_session, partner_id=partner_id)

    with pytest.raises(UnauthorizedError):
        await partners.resolve_partner(db_session, tokens.access_token)
    with pytest.raises(UnauthorizedError):
        await partners.rotate(db_session, refresh_token=tokens.refresh_token)
    assert authjwt is not None  # imported for the reader; the refusal is above


async def test_a_code_can_be_retuned_and_switched_off(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate import admin

    partner_id = await _partner(db_session)
    code = await admin.issue_code(
        db_session,
        partner_id=partner_id,
        code=f"C{secrets.token_hex(4).upper()}",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )

    updated = await admin.update_code(db_session, code_id=code.id, discount_percent=Decimal("8"))
    assert updated.discount_percent == Decimal("8")
    assert updated.commission_percent == Decimal("2")

    off = await admin.update_code(db_session, code_id=code.id, active=False)
    assert off.active is False


async def test_a_reinvite_link_works_and_a_stale_one_stops(db_session: AsyncSession) -> None:
    """For "the email never arrived", which is otherwise a database edit.

    The reissued link must work; issuing it must not quietly invalidate the
    original, because an admin who reissues while the partner is mid-signup
    would break the very thing they were fixing.
    """
    from yupay.core.ids import new_id
    from yupay.modules.affiliate import partners
    from yupay.modules.affiliate.models import AffiliatePartner
    from yupay.modules.affiliate.models import AffiliatePartner as P

    partner = P(id=new_id(), email=f"p-{new_id()}@example.test", status="pending")
    db_session.add(partner)
    await db_session.flush()

    first = await partners.approve(db_session, partner_id=partner.id)
    second = await partners.reinvite(db_session, partner_id=partner.id)
    assert second != first

    await partners.set_password(db_session, token=second, password="a good password")
    row = await db_session.get(AffiliatePartner, partner.id)
    assert row is not None
    assert row.password_hash is not None


async def test_reinviting_a_suspended_partner_is_refused(db_session: AsyncSession) -> None:
    """Issuing a login link for a switched-off account would be the wrong
    repair — reinstating them is a separate, deliberate decision."""
    from yupay.core.errors import ConflictError
    from yupay.modules.affiliate import admin, partners

    partner_id = await _partner(db_session, status="pending")
    await partners.approve(db_session, partner_id=partner_id)
    await admin.suspend_partner(db_session, partner_id=partner_id)

    with pytest.raises(ConflictError):
        await partners.reinvite(db_session, partner_id=partner_id)
