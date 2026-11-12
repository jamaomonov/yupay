"""Signing in to the merchant cabinet with Google (2026-11-12).

The storefront's Google sign-in (``auth.google``) verifies the access token
the browser's OAuth popup returns; this reuses that verifier, against the
same OAuth client, and keeps the cabinet's own accounts and sessions.

Linking is by **verified** email, as on the storefront: ``merchant_users``
already identifies an operator by address, and Google asserting
``email_verified`` proves the mailbox at least as well as our confirmation
link does. So a Google sign-in may:

* **open a session** for the operator with that address. One who never
  confirmed it is confirmed now, and the password on file is replaced with
  an unusable one: password login refuses unconfirmed accounts, so that hash
  can only have been set by somebody who never proved the address —
  confirming without clearing it would arm their password, the hole
  ``cabinet_auth.reclaim_unconfirmed`` closes for the form;
* **register** a merchant, but only when the caller sends ``accept_offer`` —
  the offer record is the point of registration and Google cannot tick it.

An unknown address without the offer answers ``merchant_not_registered``.
That says nothing about somebody else's mailbox: the caller has just proven
this one is theirs.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import AccountSuspendedError, NotFoundError, UnauthorizedError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.auth import google
from yupay.modules.auth.security import hash_password
from yupay.modules.merchants.cabinet_auth import OFFER_VERSION, CabinetTokens, open_session
from yupay.modules.merchants.models import Merchant, MerchantUser

log = get_logger("yupay.merchants.cabinet_google")

Verifier = Callable[[str], Awaitable[google.GoogleUser]]

_TITLE_MAX = 128


async def _unusable_password() -> str:
    """A hash nobody knows the input of: the column is NOT NULL, the password
    form must not work, and a reset link is how one is set later."""
    return await hash_password(secrets.token_urlsafe(32))


def _title_for(title: str | None, identity: google.GoogleUser) -> str:
    """The shop name: what they typed, else their Google name, else the mailbox."""
    for candidate in (title, identity.name, identity.email.split("@", 1)[0]):
        cleaned = (candidate or "").strip()
        if len(cleaned) >= 2:  # the form's own minimum
            return cleaned[:_TITLE_MAX]
    return identity.email[:_TITLE_MAX]


async def _find(db: AsyncSession, email: str) -> MerchantUser | None:
    return (
        await db.execute(select(MerchantUser).where(MerchantUser.email == email).with_for_update())
    ).scalar_one_or_none()


async def _create(db: AsyncSession, *, email: str, title: str) -> MerchantUser | None:
    """Merchant + operator, confirmed. ``None`` when a concurrent sign-up won."""
    merchant = Merchant(id=new_id(), title=title)
    user = MerchantUser(
        id=new_id(),
        merchant_id=merchant.id,
        email=email,
        password_hash=await _unusable_password(),
        email_confirmed_at=now(),
        offer_version=OFFER_VERSION,
        offer_accepted_at=now(),
    )
    try:
        async with db.begin_nested():
            db.add(merchant)
            db.add(user)
            await db.flush()
    except IntegrityError:
        return None
    log.info("merchant.cabinet.registered", merchant_id=merchant.id, user_id=user.id, via="google")
    return user


async def google_sign_in(
    db: AsyncSession,
    *,
    access_token: str,
    accept_offer: bool,
    title: str | None = None,
    settings: Settings | None = None,
    verifier: Verifier | None = None,
) -> CabinetTokens:
    """Verify a Google access token and open a cabinet session.

    Args:
        db: Session; the route owns the transaction.
        access_token: From the browser's Google OAuth popup.
        accept_offer: The registration checkbox. Only read when the address
            has no account yet.
        title: The shop name from the registration form, if they typed one.
        settings: Overrides for tests.
        verifier: Injected verification for tests.

    Raises:
        UnauthorizedError: Google refused the token, or the email is unverified.
        NotFoundError: No account for this address and no offer accepted
            (``merchant_not_registered``).
        AccountSuspendedError: The merchant is frozen.
    """
    s = settings or get_settings()
    verify = verifier or google.verify_credential
    try:
        identity = await verify(access_token)
    except google.GoogleAuthError as exc:
        log.info("merchant.cabinet.google_rejected", reason=str(exc))
        raise UnauthorizedError("google verification failed") from exc
    if not identity.email_verified:
        log.info("merchant.cabinet.google_rejected", reason="email not verified")
        raise UnauthorizedError("google verification failed")

    email = identity.email.strip().lower()
    user = await _find(db, email)
    if user is None:
        if not accept_offer:
            raise NotFoundError("no merchant account", code="merchant_not_registered")
        user = await _create(db, email=email, title=_title_for(title, identity))
        if user is None:  # lost the race to a sign-up for the same address
            user = await _find(db, email)
            if user is None:  # pragma: no cover -- the winner's row is committed
                raise UnauthorizedError("google verification failed")

    if user.email_confirmed_at is None:
        user.password_hash = await _unusable_password()
        user.email_confirmed_at = now()
        await db.flush()
        log.info("merchant.cabinet.confirmed_by_google", user_id=user.id)

    merchant = await db.get(Merchant, user.merchant_id)
    if merchant is None or merchant.status != "active":
        raise AccountSuspendedError("merchant account is suspended")
    return await open_session(db, user=user, settings=s)


__all__ = ["google_sign_in"]
