"""Sign-up and sign-in for the merchant cabinet (spec §11).

``merchant_users`` has existed since M1 and nothing has ever created a row or
authenticated one — the machine API signs requests with an HMAC key, which is
a server's credential and not a person's. This is the person's half.

Modelled on ``affiliate.partners``, which solved the same shape one actor
earlier: a back-office login that is deliberately **not** the storefront's.
Three things carry over unchanged because they were right there:

* a **session table**, so signing out one device leaves the others alone, with
  the refresh token stored only as a SHA-256;
* a **distinct token kind** (``merchant_access``), so a cabinet token is
  structurally unusable on a buyer or partner endpoint;
* **one answer for every login failure**, after a real argon2 verification, so
  neither the wording nor the timing says which address exists.

What is new here is registration being **open** (owner, spec §11): anyone may
sign up and see wholesale prices, and the money step — support crediting the
first deposit — is the KYC filter. That makes the confirmation link the only
thing standing between a stranger and a mailbox that is not theirs, so it is
required before the first sign-in and single-use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ConflictError, UnauthorizedError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import (
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from yupay.modules.merchants.models import Merchant, MerchantSession, MerchantUser

log = get_logger("yupay.merchants.cabinet_auth")

#: The offer version a registration records. Bumped when the document changes;
#: an existing merchant is not migrated, because what they accepted is what
#: they accepted.
OFFER_VERSION = "2026-09-draft"

#: Argon2 runs on a password nobody registered, so the answer to "does this
#: address exist" costs the same either way. A constant rather than a literal
#: so the two sites that need it cannot drift.
_DUMMY_HASH_INPUT = "no-such-account"


@dataclass(frozen=True)
class CabinetTokens:
    """What a successful sign-in hands the browser."""

    access_token: str
    refresh_token: str
    expires_in: int


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


async def open_session(
    db: AsyncSession, *, user: MerchantUser, settings: Settings
) -> CabinetTokens:
    """Write a session row and mint the pair that references it."""
    refresh = new_refresh_token()
    session_id = new_id()
    db.add(
        MerchantSession(
            id=session_id,
            merchant_user_id=user.id,
            token_hash=hash_token(refresh),
            expires_at=now() + timedelta(seconds=settings.merchant_refresh_ttl_seconds),
        )
    )
    await db.flush()
    return CabinetTokens(
        access_token=authjwt.mint_merchant_access(sub=user.id, sid=session_id, settings=settings),
        refresh_token=refresh,
        expires_in=settings.merchant_access_ttl_seconds,
    )


async def register(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    title: str,
    settings: Settings | None = None,
) -> tuple[MerchantUser, str]:
    """Create a merchant and its first operator, unconfirmed.

    Both rows in one transaction: a ``merchant_users`` row whose ``merchant_id``
    points at nothing is not a half-registration, it is a foreign key violation
    waiting for the next request.

    The account is ``active`` from the start and sees the whole wholesale
    catalog. That is the owner's decision and it is safe for the reason the
    module docstring gives — prices are public to registered merchants by
    design (spec §8.3, they must be uniform), and nothing can be *bought* until
    support credits a deposit.

    Args:
        db: Session. The caller owns the transaction.
        email: The operator's address, lower-cased and trimmed here.
        password: Their password, already length-checked by the schema.
        title: The company name shown in admin and on their own dashboard.
        settings: Overrides the process settings; for tests.

    Returns:
        ``(user, confirmation_token)`` — the token is handed to the caller to
        mail rather than mailed here, so the route owns the transaction
        boundary and an email is never sent for a registration that rolls back.

    Raises:
        ConflictError: The address is already registered.
    """
    s = _settings(settings)
    normalised = email.strip().lower()
    merchant = Merchant(id=new_id(), title=title.strip())
    db.add(merchant)
    user = MerchantUser(
        id=new_id(),
        merchant_id=merchant.id,
        email=normalised,
        password_hash=await hash_password(password),
        offer_version=OFFER_VERSION,
        offer_accepted_at=now(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # The unique index on ``email`` is the authority, not a prior SELECT:
        # two simultaneous registrations would both pass a check-then-insert.
        raise ConflictError("this email is already registered", code="email_taken") from exc
    log.info("merchant.cabinet.registered", merchant_id=merchant.id, user_id=user.id)
    return user, authjwt.mint_email_verify(sub=user.id, settings=s)


async def confirm_email(
    db: AsyncSession, *, token: str, settings: Settings | None = None
) -> MerchantUser:
    """Mark an operator's address confirmed. Single-use.

    The single-use marker is a Redis ``SET NX`` on the token's ``jti``, the
    same device ``affiliate.partners.set_password`` uses: the JWT alone is
    replayable until it expires, and a confirmation link that works twice is a
    link that works for whoever reads the mailbox second.

    Raises:
        UnauthorizedError: Expired, wrong kind, already used, or no such user.
    """
    s = _settings(settings)
    claims = authjwt.verify(token, expected_kind="email_verify", settings=s)
    was_set = await get_redis().set(
        f"merchant:confirm:{claims.jti}", "1", ex=s.merchant_confirm_ttl_seconds, nx=True
    )
    if not was_set:
        raise UnauthorizedError("link already used")
    user = await db.get(MerchantUser, claims.sub)
    if user is None:
        raise UnauthorizedError("link is no longer valid")
    if user.email_confirmed_at is None:
        user.email_confirmed_at = now()
        await db.flush()
    log.info("merchant.cabinet.email_confirmed", user_id=user.id)
    return user


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings | None = None,
) -> CabinetTokens:
    """Authenticate an operator and open a session.

    Raises:
        UnauthorizedError: Unknown address, wrong password, an unconfirmed
            address, or a frozen merchant — all surfaced identically and all
            after an argon2 verification. "Not confirmed" is tempting to say
            and is not ours to say: registration is open, so telling a prober
            that an address is registered is telling them about someone else's
            mailbox. The resend endpoint is the actionable path, and it answers
            the same to everyone.
    """
    s = _settings(settings)
    normalised = email.strip().lower()
    user = (
        await db.execute(select(MerchantUser).where(MerchantUser.email == normalised))
    ).scalar_one_or_none()
    stored = user.password_hash if user is not None else None
    ok = await verify_password(password, stored) if stored else await _burn_time(password)
    if not ok or user is None:
        raise UnauthorizedError("invalid credentials")
    if user.email_confirmed_at is None:
        raise UnauthorizedError("invalid credentials")
    merchant = await db.get(Merchant, user.merchant_id)
    if merchant is None or merchant.status != "active":
        raise UnauthorizedError("invalid credentials")
    return await open_session(db, user=user, settings=s)


async def _burn_time(password: str) -> bool:
    """Verify against a throwaway hash so an unknown address costs the same.

    Without this the endpoint answers "no such account" in a microsecond and
    "wrong password" in a hundred milliseconds, which is the whole enumeration
    oracle the uniform error text was meant to close.
    """
    await verify_password(password, await hash_password(_DUMMY_HASH_INPUT))
    return False


async def refresh(
    db: AsyncSession, *, refresh_token: str, settings: Settings | None = None
) -> CabinetTokens:
    """Rotate a session: the presented token dies, a new pair is issued.

    Rotation rather than reuse, like every other refresh in this codebase: a
    stolen token is then usable exactly once, and the theft shows up as the
    real owner's next refresh failing.

    Raises:
        UnauthorizedError: Unknown, expired or already-rotated token.
    """
    s = _settings(settings)
    session = (
        await db.execute(
            select(MerchantSession).where(MerchantSession.token_hash == hash_token(refresh_token))
        )
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None or session.expires_at <= now():
        raise UnauthorizedError("session is no longer valid")
    user = await db.get(MerchantUser, session.merchant_user_id)
    if user is None:  # pragma: no cover -- FK cascade makes this unreachable
        raise UnauthorizedError("session is no longer valid")
    session.revoked_at = now()
    await db.flush()
    return await open_session(db, user=user, settings=s)


async def resolve_user(db: AsyncSession, token: str) -> MerchantUser:
    """The operator behind a ``Bearer`` cabinet access token.

    Checks the session is still live, not only that the JWT parses: a token
    minted before a sign-out is cryptographically perfect and must stop
    working, which is the whole reason ``sid`` is in the payload.

    Raises:
        UnauthorizedError: Bad, expired or wrong-kind token; a revoked or
            expired session; a vanished user; a frozen merchant. One wording
            for all of them — a signed-out operator and a frozen company are
            both "sign in again" from the browser's side, and the cabinet says
            which on the sign-in attempt that follows.
    """
    claims = authjwt.verify(token, expected_kind="merchant_access")
    if claims.sid is None:  # pragma: no cover -- mint always sets it
        raise UnauthorizedError("invalid session")
    session = await db.get(MerchantSession, claims.sid)
    if session is None or session.revoked_at is not None or session.expires_at <= now():
        raise UnauthorizedError("invalid session")
    user = await db.get(MerchantUser, claims.sub)
    if user is None or user.email_confirmed_at is None:
        raise UnauthorizedError("invalid session")
    merchant = await db.get(Merchant, user.merchant_id)
    if merchant is None or merchant.status != "active":
        raise UnauthorizedError("invalid session")
    return user


async def logout(db: AsyncSession, *, refresh_token: str) -> None:
    """Revoke one session. Silent on an unknown token — there is nothing to
    tell a caller who is already signed out, and answering differently would
    make this endpoint a session-existence oracle."""
    session = (
        await db.execute(
            select(MerchantSession).where(MerchantSession.token_hash == hash_token(refresh_token))
        )
    ).scalar_one_or_none()
    if session is not None and session.revoked_at is None:
        session.revoked_at = now()
        await db.flush()


__all__ = [
    "OFFER_VERSION",
    "CabinetTokens",
    "confirm_email",
    "login",
    "logout",
    "open_session",
    "refresh",
    "register",
    "resolve_user",
]
