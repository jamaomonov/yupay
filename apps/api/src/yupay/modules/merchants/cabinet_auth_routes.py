"""Getting in and out of the cabinet: register, confirm, sign in, reset.

The credential half of `/merchant/cabinet`, split from `cabinet_routes` when
that file passed AGENTS.md §6's 500-line line. The seam is the useful one:
everything here runs **before** there is a session, which is why every route
in this file carries `guard_ip` and none of them takes `CurrentUser`.

One rule runs through all of it. **Registration is open** (spec §11), so no
answer on this surface may distinguish a registered address from an
unregistered one: `register` answers 201 with no body either way, `login` has
a single error text for four different refusals, and the two "mail me a link"
endpoints answer 204 whatever the address was. An endpoint that behaved
differently would be reporting on somebody else's mailbox.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.logging import get_logger
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.merchants import cabinet_auth
from yupay.modules.merchants.cabinet_deps import Db
from yupay.modules.merchants.cabinet_schemas import (
    CabinetConfirmIn,
    CabinetEmailIn,
    CabinetLoginIn,
    CabinetRegisterIn,
    CabinetSetPasswordIn,
    CabinetTokenIn,
    CabinetTokensOut,
)
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import (
    EmailContent,
    merchant_confirm_email,
    merchant_password_reset_email,
)

log = get_logger("yupay.merchants.cabinet_auth_routes")

router = APIRouter(prefix="/merchant/cabinet", tags=["merchant-cabinet"])


def _tokens_out(tokens: cabinet_auth.CabinetTokens) -> CabinetTokensOut:
    return CabinetTokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


def _cabinet_base() -> str:
    """The cabinet's own origin, or a refusal.

    Every link we mail is built from it, so an unset value is not a degraded
    feature — it is an email nobody can act on. Refusing at the form is the
    only honest failure.
    """
    base = get_settings().merchant_cabinet_url.rstrip("/")
    if not base:
        raise ValidationError(
            "the cabinet is not configured to send mail yet",
            code="cabinet_mail_unconfigured",
        )
    return base


async def _mail_link(*, to: str, content: EmailContent, event: str, user_id: str) -> None:
    """Send one link, and let a failed send be a log line rather than a 500.

    The state these mails repair already exists — an account that cannot sign
    in, an address that is not confirmed — and failing the request would not
    undo it. What it would do is tell the caller that *this* address is real,
    since a send can only fail for an address we actually tried.
    """
    try:
        await send_email(to=to, subject=content.subject, html=content.html, text=content.text)
    except EmailSendError:
        log.exception(event, user_id=user_id)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Open a merchant account and its first operator",
)
async def register(body: CabinetRegisterIn, db: Db, request: Request) -> Response:
    """Create the account and mail a confirmation link.

    Answers ``201`` with no body. The address is not echoed and no token is
    issued: registration is open, so the response must look the same to
    somebody probing addresses as to the person who owns one — and the only
    thing that proves ownership is the link.
    """
    await guard_ip(request, bucket="merchant_register", subject=body.email.lower())
    # Before the insert: rather than register an account whose confirmation
    # can never arrive.
    base = _cabinet_base()
    user, token = await cabinet_auth.register(
        db, email=body.email, password=body.password, title=body.title
    )
    # A failed send leaves an account that exists with an unconfirmed address,
    # which `/confirm/resend` repairs. Failing the request would roll the
    # registration back and lose the password they just chose.
    await _mail_link(
        to=user.email,
        content=merchant_confirm_email(link=f"{base}/confirm?token={token}"),
        event="merchant.cabinet.confirm_mail_failed",
        user_id=user.id,
    )
    return Response(status_code=status.HTTP_201_CREATED)


@router.post("/confirm", response_model=CabinetTokensOut, summary="Confirm an address")
async def confirm(body: CabinetConfirmIn, db: Db) -> CabinetTokensOut:
    """Consume the link and sign the operator in.

    Signing them in here rather than redirecting to a login form is safe for
    the reason the link exists: holding it *is* proof of the mailbox, which is
    the same proof the password form is trying to establish.
    """
    user = await cabinet_auth.confirm_email(db, token=body.token)
    return _tokens_out(await cabinet_auth.open_session(db, user=user, settings=get_settings()))


@router.post(
    "/password/forgot",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mail a password-reset link",
)
async def forgot_password(body: CabinetEmailIn, db: Db, request: Request) -> Response:
    """``204`` whatever the address was.

    Registration is open, so an answer that distinguished a registered address
    from an unregistered one would report on somebody else's mailbox — the
    same rule ``register`` and ``login`` follow. An **unconfirmed** account is
    sent nothing here either: the link it needs is the confirmation, which
    ``/confirm/resend`` is for.
    """
    await guard_ip(request, bucket="merchant_forgot", subject=body.email.lower())
    base = _cabinet_base()
    found = await cabinet_auth.request_password_reset(db, email=body.email)
    if found is not None:
        user, token = found
        await _mail_link(
            to=user.email,
            content=merchant_password_reset_email(link=f"{base}/reset?token={token}"),
            event="merchant.cabinet.reset_mail_failed",
            user_id=user.id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password/reset",
    response_model=CabinetTokensOut,
    summary="Set a new password and sign in",
)
async def reset_password(body: CabinetSetPasswordIn, db: Db) -> CabinetTokensOut:
    """Consume the link, set the password, end every other session, sign in.

    Signing them in is safe for the reason ``/confirm`` gives — holding the
    link proves the mailbox — and ending the other sessions is the point: a
    reset whose premise is "somebody else may have my account" that left the
    attacker's refresh token alive would accomplish nothing.
    """
    user = await cabinet_auth.set_password(db, token=body.token, password=body.password)
    return _tokens_out(await cabinet_auth.open_session(db, user=user, settings=get_settings()))


@router.post(
    "/confirm/resend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mail the confirmation link again",
)
async def resend_confirmation(body: CabinetEmailIn, db: Db, request: Request) -> Response:
    """``204`` whatever the address was, including one already confirmed.

    That last case is not an oversight: re-sending a confirmation to a live
    account would let anybody who knows the address fill that mailbox on
    demand, and its owner has nothing to do with the link anyway.
    """
    await guard_ip(request, bucket="merchant_confirm_resend", subject=body.email.lower())
    base = _cabinet_base()
    found = await cabinet_auth.resend_confirmation(db, email=body.email)
    if found is not None:
        user, token = found
        await _mail_link(
            to=user.email,
            content=merchant_confirm_email(link=f"{base}/confirm?token={token}"),
            event="merchant.cabinet.confirm_mail_failed",
            user_id=user.id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/login", response_model=CabinetTokensOut, summary="Sign in")
async def login(body: CabinetLoginIn, db: Db, request: Request) -> CabinetTokensOut:
    await guard_ip(request, bucket="merchant_login", subject=body.email.lower())
    return _tokens_out(await cabinet_auth.login(db, email=body.email, password=body.password))


@router.post("/refresh", response_model=CabinetTokensOut, summary="Rotate a session")
async def refresh(body: CabinetTokenIn, db: Db) -> CabinetTokensOut:
    return _tokens_out(await cabinet_auth.refresh(db, refresh_token=body.refresh_token))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one session",
)
async def logout(body: CabinetTokenIn, db: Db) -> Response:
    await cabinet_auth.logout(db, refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
