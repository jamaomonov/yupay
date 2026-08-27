"""Partner authentication.

The property this file exists to hold is that a partner and a buyer cannot be
mistaken for one another. Everything else here — passwords, sessions, the
set-password link — is the project's existing machinery pointed at a second
kind of subject; this is the part that is genuinely new.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def test_a_partner_token_is_not_a_buyer_token() -> None:
    """The two token kinds must not be interchangeable.

    Reusing ``"access"`` for partners would work today only because a partner
    id is not found in ``users`` — an accident, not a boundary. It stops
    holding the moment anything resolves a subject less strictly.
    """
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.auth import jwt as authjwt

    token = authjwt.mint_partner_access(sub="p-1", sid="s-1")
    assert authjwt.verify(token, expected_kind="partner_access").sub == "p-1"
    with pytest.raises(UnauthorizedError):
        authjwt.verify(token, expected_kind="access")

    buyer = authjwt.mint_access(sub="u-1", sid="s-1")
    with pytest.raises(UnauthorizedError):
        authjwt.verify(buyer, expected_kind="partner_access")


async def _apply(db: AsyncSession, email: str | None = None) -> str:
    from yupay.core.ids import new_id
    from yupay.modules.affiliate import partners

    partner = await partners.submit_application(
        db, email=email or f"p-{new_id()}@example.test", display_name="P"
    )
    assert partner is not None
    return partner.id


async def _approved(db: AsyncSession) -> tuple[str, str, str]:
    """A partner with a password set.

    Returns:
        ``(partner_id, email, password)``.
    """
    from yupay.modules.affiliate import partners
    from yupay.modules.affiliate.models import AffiliatePartner

    partner_id = await _apply(db)
    token = await partners.approve(db, partner_id=partner_id)
    await partners.set_password(db, token=token, password="correct horse battery")
    partner = await db.get(AffiliatePartner, partner_id)
    assert partner is not None
    return partner_id, partner.email, "correct horse battery"


async def test_an_application_lands_pending(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.models import AffiliatePartner

    partner_id = await _apply(db_session)
    partner = await db_session.get(AffiliatePartner, partner_id)
    assert partner is not None
    assert partner.status == "pending"
    assert partner.password_hash is None


async def test_a_repeat_application_does_not_reveal_the_first(
    db_session: AsyncSession,
) -> None:
    """Answering "already registered" would enumerate the partner list."""
    from yupay.modules.affiliate import partners
    from yupay.modules.affiliate.models import AffiliatePartner

    email = "twice@example.test"
    first = await partners.submit_application(db_session, email=email)
    second = await partners.submit_application(db_session, email=email)

    assert first is not None
    assert second is None
    count = await db_session.scalar(
        select(func.count()).select_from(AffiliatePartner).where(AffiliatePartner.email == email)
    )
    assert count == 1


async def test_the_set_password_link_works_once(db_session: AsyncSession) -> None:
    """An approval email that stays valid forever is a permanent way in."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners

    partner_id = await _apply(db_session)
    token = await partners.approve(db_session, partner_id=partner_id)

    await partners.set_password(db_session, token=token, password="first password")
    with pytest.raises(UnauthorizedError):
        await partners.set_password(db_session, token=token, password="second password")


async def test_a_link_stops_working_once_the_partner_is_suspended(
    db_session: AsyncSession,
) -> None:
    """Approved, emailed, then switched off — the email must not still open it."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners
    from yupay.modules.affiliate.models import AffiliatePartner

    partner_id = await _apply(db_session)
    token = await partners.approve(db_session, partner_id=partner_id)

    partner = await db_session.get(AffiliatePartner, partner_id)
    assert partner is not None
    partner.status = "suspended"
    await db_session.flush()

    with pytest.raises(UnauthorizedError):
        await partners.set_password(db_session, token=token, password="a good password")


async def test_login_answers_the_same_for_a_wrong_password_and_an_unknown_address(
    db_session: AsyncSession,
) -> None:
    """Otherwise this endpoint is an oracle for who is a partner."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners

    _, email, password = await _approved(db_session)

    with pytest.raises(UnauthorizedError) as wrong:
        await partners.login(db_session, email=email, password="not the password")
    with pytest.raises(UnauthorizedError) as unknown:
        await partners.login(db_session, email="nobody@example.test", password=password)

    assert str(wrong.value) == str(unknown.value)


async def test_a_suspended_partner_cannot_log_in_with_the_right_password(
    db_session: AsyncSession,
) -> None:
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners
    from yupay.modules.affiliate.models import AffiliatePartner

    partner_id, email, password = await _approved(db_session)
    partner = await db_session.get(AffiliatePartner, partner_id)
    assert partner is not None
    partner.status = "suspended"
    await db_session.flush()

    with pytest.raises(UnauthorizedError) as suspended:
        await partners.login(db_session, email=email, password=password)
    # Same wording as a wrong password: "suspended" tells an attacker the
    # address belongs to a partner.
    assert "invalid email or password" in str(suspended.value)


async def test_a_refresh_token_works_once(db_session: AsyncSession) -> None:
    """Presented twice it is either a bug or a theft; both must fail."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners

    _, email, password = await _approved(db_session)
    first = await partners.login(db_session, email=email, password=password)

    second = await partners.rotate(db_session, refresh_token=first.refresh_token)
    assert second.refresh_token != first.refresh_token

    with pytest.raises(UnauthorizedError):
        await partners.rotate(db_session, refresh_token=first.refresh_token)


async def test_logging_out_kills_the_access_token_too(db_session: AsyncSession) -> None:
    """A revoked session must stop the access token before it expires."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners

    _, email, password = await _approved(db_session)
    tokens = await partners.login(db_session, email=email, password=password)
    assert await partners.resolve_partner(db_session, tokens.access_token) is not None

    await partners.logout(db_session, refresh_token=tokens.refresh_token)
    with pytest.raises(UnauthorizedError):
        await partners.resolve_partner(db_session, tokens.access_token)


async def test_setting_a_password_revokes_existing_sessions(
    db_session: AsyncSession,
) -> None:
    """A session must not outlive the credential it was opened with."""
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners

    partner_id, email, password = await _approved(db_session)
    tokens = await partners.login(db_session, email=email, password=password)

    from yupay.modules.auth import jwt as authjwt

    # A second link, as an admin re-issuing one would produce.
    fresh = authjwt.mint_password_reset(sub=partner_id)
    await partners.set_password(db_session, token=fresh, password="a different password")

    with pytest.raises(UnauthorizedError):
        await partners.resolve_partner(db_session, tokens.access_token)


async def test_a_buyer_token_is_refused_by_the_panel(db_session: AsyncSession) -> None:
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.affiliate import partners
    from yupay.modules.auth import jwt as authjwt

    buyer = authjwt.mint_access(sub="u-1", sid="s-1")
    with pytest.raises(UnauthorizedError):
        await partners.resolve_partner(db_session, buyer)
