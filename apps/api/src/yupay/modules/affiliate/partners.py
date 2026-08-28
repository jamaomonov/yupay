"""Becoming a partner, and signing in as one.

None of the cryptography here is new. Passwords go through
``auth.security.hash_password`` — argon2id, already tuned for this box and
already behind a ``CapacityLimiter(4)`` so a login burst cannot eat 2.5 GB of
RAM — and tokens through ``auth.jwt``. A second hand-rolled authentication is
where holes live, so this module is plumbing around the existing one.

What *is* new is the subject. A partner is not a user: separate table, separate
sessions, and a separate token kind that :func:`auth.jwt.verify` will refuse on
a buyer endpoint.

Two behaviours are deliberate and easy to undo by accident:

Signing in answers identically for a wrong password and an unknown address, and
runs argon2 either way against a dummy hash. Anything else turns this endpoint
into an oracle for who is a partner.

Approving mints a single-use link. It is consumed through a Redis ``SET NX`` on
the token's ``jti``, the same mechanism ``auth.reset_password`` uses. An
approval email that stays valid forever is a permanent way into an account that
can move money out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.affiliate.models import AffiliatePartner, AffiliateSession
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import (
    hash_password,
    hash_password_sync,
    hash_token,
    new_refresh_token,
    verify_password,
)
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import partner_invite_email

log = get_logger("yupay.affiliate.partners")

#: Verified against when the address is unknown, so response time does not
#: answer the question the response itself refuses to.
_DUMMY_HASH = hash_password_sync("x")

#: Only an active partner may hold a session. `pending` has not been approved,
#: `suspended` has been switched off, `rejected` never got in.
_LOGIN_ALLOWED = "active"


@dataclass(frozen=True)
class PartnerTokens:
    """An access token and the opaque refresh token that can renew it."""

    access_token: str
    refresh_token: str
    expires_in: int


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


async def submit_application(
    db: AsyncSession,
    *,
    email: str,
    display_name: str | None = None,
    contact: str | None = None,
    channel: str | None = None,
) -> AffiliatePartner | None:
    """Record an application to join the program.

    Args:
        db: Session. The caller owns the transaction.
        email: Contact address; also the future login.
        display_name: What to call them.
        contact: Telegram, phone — whatever they gave.
        channel: Where they intend to promote.

    Returns:
        The new row, or ``None`` when this address has already applied. The
        caller answers the same either way: telling an applicant that an
        address is already registered would enumerate the partner list.
    """
    partner = AffiliatePartner(
        id=new_id(),
        email=email.strip().lower(),
        display_name=display_name,
        contact=contact,
        channel=channel,
        status="pending",
    )
    try:
        # Inside the SAVEPOINT: added before it, a UNIQUE(email) failure would
        # leave the doomed row in ``session.new`` and poison the session.
        async with db.begin_nested():
            db.add(partner)
            await db.flush()
    except IntegrityError:
        return None
    log.info("affiliate.application.submitted", partner_id=partner.id)
    return partner


async def approve(
    db: AsyncSession,
    *,
    partner_id: str,
    settings: Settings | None = None,
) -> str:
    """Approve an application and mint its one-time set-password link.

    Args:
        db: Session.
        partner_id: The application to approve.
        settings: Overrides the process settings; for tests.

    Returns:
        The signed token to embed in the approval email.

    Raises:
        NotFoundError: No such partner.
        ConflictError: The partner is not awaiting approval.
    """
    s = _settings(settings)
    partner = await db.get(AffiliatePartner, partner_id)
    if partner is None:
        raise NotFoundError("partner not found")
    if partner.status != "pending":
        raise ConflictError(f"partner is {partner.status}, not pending")

    partner.status = "active"
    partner.approved_at = now()
    await db.flush()
    log.info("affiliate.partner.approved", partner_id=partner.id)
    # Annotated rather than returned bare: mypy skips analysing the auth
    # package here, so the call reads as Any and returning it from a
    # `-> str` function is an error. The annotation is the assertion.
    token: str = authjwt.mint_password_reset(sub=partner.id, settings=s)
    return token


async def reject(
    db: AsyncSession,
    *,
    partner_id: str,
    note: str | None = None,
) -> None:
    """Turn an application down.

    Raises:
        NotFoundError: No such partner.
        ConflictError: The partner is not awaiting approval.
    """
    partner = await db.get(AffiliatePartner, partner_id)
    if partner is None:
        raise NotFoundError("partner not found")
    if partner.status != "pending":
        raise ConflictError(f"partner is {partner.status}, not pending")
    partner.status = "rejected"
    partner.admin_note = note
    await db.flush()
    log.info("affiliate.partner.rejected", partner_id=partner.id)


async def set_password(
    db: AsyncSession,
    *,
    token: str,
    password: str,
    settings: Settings | None = None,
) -> None:
    """Consume the approval link and set the partner's first password.

    Single-use through a Redis ``SET NX`` on the token's ``jti`` — the same
    mechanism ``auth.reset_password`` uses. Presented twice, the second attempt
    finds the marker already set and is refused.

    The partner's status is re-checked here rather than trusted from approval
    time: an account approved and then suspended must not still be openable by
    an email sent in between.

    Raises:
        UnauthorizedError: Invalid, expired or already-used token, or a partner
            who is no longer allowed in.
        ValidationError: Password too short.
    """
    s = _settings(settings)
    if len(password) < 8:
        raise ValidationError("password must be at least 8 characters")

    claims = authjwt.verify(token, expected_kind="password_reset", settings=s)

    redis = get_redis()
    marker = f"affiliate:setpw:{claims.jti}"
    # redis-py returns True on a successful SET NX and None when the key exists.
    was_set = await redis.set(marker, "1", ex=s.jwt_email_token_ttl_seconds, nx=True)
    if not was_set:
        raise UnauthorizedError("link already used")

    partner = await db.get(AffiliatePartner, claims.sub)
    if partner is None or partner.status != _LOGIN_ALLOWED:
        raise UnauthorizedError("link is no longer valid")

    partner.password_hash = await hash_password(password)
    await db.flush()
    await _revoke_all(db, partner_id=partner.id)
    log.info("affiliate.partner.password_set", partner_id=partner.id)


async def _open_session(
    db: AsyncSession, *, partner: AffiliatePartner, settings: Settings
) -> PartnerTokens:
    """Write a session row and mint the pair that references it."""
    refresh = new_refresh_token()
    session_id = new_id()
    db.add(
        AffiliateSession(
            id=session_id,
            partner_id=partner.id,
            token_hash=hash_token(refresh),
            expires_at=now() + timedelta(seconds=settings.affiliate_refresh_ttl_seconds),
        )
    )
    await db.flush()
    return PartnerTokens(
        access_token=authjwt.mint_partner_access(sub=partner.id, sid=session_id, settings=settings),
        refresh_token=refresh,
        expires_in=settings.affiliate_access_ttl_seconds,
    )


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings | None = None,
) -> PartnerTokens:
    """Authenticate a partner and open a session.

    Raises:
        UnauthorizedError: Unknown address, no password set yet, wrong password,
            or a partner who is not active — all surfaced identically, and all
            after an argon2 verification, so neither the wording nor the timing
            says which.
    """
    s = _settings(settings)
    normalised = email.strip().lower()
    partner = (
        await db.execute(select(AffiliatePartner).where(AffiliatePartner.email == normalised))
    ).scalar_one_or_none()

    stored = partner.password_hash if (partner and partner.password_hash) else _DUMMY_HASH
    password_ok = await verify_password(password, stored)

    if partner is None or not partner.password_hash or not password_ok:
        raise UnauthorizedError("invalid email or password")
    if partner.status != _LOGIN_ALLOWED:
        # Same message on purpose: "your account is suspended" tells an
        # attacker that the address is a partner's.
        raise UnauthorizedError("invalid email or password")

    return await _open_session(db, partner=partner, settings=s)


async def rotate(
    db: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings | None = None,
) -> PartnerTokens:
    """Exchange a refresh token for a new pair, revoking the old row.

    Rotation is the point: a refresh token presented twice is either a bug or a
    stolen token, and either way the second presentation must fail.

    Raises:
        UnauthorizedError: Unknown, expired or already-revoked token, or a
            partner who is no longer active.
    """
    s = _settings(settings)
    session = (
        await db.execute(
            select(AffiliateSession)
            .where(AffiliateSession.token_hash == hash_token(refresh_token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    moment = now()
    if session is None or session.revoked_at is not None or session.expires_at <= moment:
        raise UnauthorizedError("invalid refresh token")

    partner = await db.get(AffiliatePartner, session.partner_id)
    if partner is None or partner.status != _LOGIN_ALLOWED:
        raise UnauthorizedError("invalid refresh token")

    session.revoked_at = moment
    await db.flush()
    return await _open_session(db, partner=partner, settings=s)


async def logout(db: AsyncSession, *, refresh_token: str) -> None:
    """Revoke one session. Silent when the token is already unusable —
    logging out twice is not an error worth reporting."""
    session = (
        await db.execute(
            select(AffiliateSession).where(AffiliateSession.token_hash == hash_token(refresh_token))
        )
    ).scalar_one_or_none()
    if session is not None and session.revoked_at is None:
        session.revoked_at = now()
        await db.flush()


async def _revoke_all(db: AsyncSession, *, partner_id: str) -> None:
    """Revoke every live session for a partner. Called when a password is set,
    so an old session cannot outlive the credential it was opened with."""
    moment = now()
    rows = (
        await db.execute(
            select(AffiliateSession).where(
                AffiliateSession.partner_id == partner_id,
                AffiliateSession.revoked_at.is_(None),
            )
        )
    ).scalars()
    for row in rows:
        row.revoked_at = moment
    await db.flush()


async def resolve_partner(
    db: AsyncSession, token: str, *, settings: Settings | None = None
) -> AffiliatePartner:
    """The partner behind an access token, or an error.

    Checks the session row as well as the signature: a token whose session was
    revoked — by a logout, a rotation, or a password change — must stop working
    before it expires.

    Raises:
        UnauthorizedError: Bad token, revoked session, or an inactive partner.
    """
    s = _settings(settings)
    claims = authjwt.verify(token, expected_kind="partner_access", settings=s)
    if claims.sid is None:
        raise UnauthorizedError("invalid token")

    session = await db.get(AffiliateSession, claims.sid)
    if session is None or session.revoked_at is not None or session.expires_at <= now():
        raise UnauthorizedError("session is no longer valid")

    partner = await db.get(AffiliatePartner, claims.sub)
    if partner is None or partner.status != _LOGIN_ALLOWED:
        raise UnauthorizedError("partner is not active")
    return partner


__all__ = [
    "PartnerTokens",
    "approve",
    "login",
    "logout",
    "reject",
    "resolve_partner",
    "rotate",
    "send_partner_invite",
    "set_password",
    "submit_application",
]


async def send_partner_invite(*, email: str, token: str, settings: Settings | None = None) -> bool:
    """Email an approved partner their set-password link.

    Returns ``False`` rather than raising when the send fails. The caller has
    already approved the partner, and an approval rolled back because a mail
    provider was down leaves an applicant waiting on silence — while an
    approved partner with an undelivered email is fixed by re-sending.

    Args:
        email: Where to send it. Not logged.
        token: The one-time link's token.
        settings: Overrides the process settings; for tests.

    Returns:
        Whether the message was accepted for delivery.
    """
    s = _settings(settings)
    base = s.partners_base_url.rstrip("/")
    content = partner_invite_email(link=f"{base}/set-password?token={token}")
    try:
        await send_email(to=email, subject=content.subject, html=content.html, text=content.text)
    except EmailSendError:
        log.warning("affiliate.invite.send_failed")
        return False
    return True
