"""HTTP surface for the merchant cabinet (spec §11).

A **BFF**, not a second machine API. The browser never holds a merchant's HMAC
secret — that credential belongs to their server — so the cabinet signs in with
a password, carries a short-lived ``merchant_access`` JWT, and this router does
the work on their behalf.

Every route takes the merchant from ``current_merchant_user``'s result and
never from a parameter: that is the single rule keeping one reseller out of
another's catalog, deposit and orders.

**Ordering here walks the machine API's path exactly** — ``quote``, the margin
floor, the deposit charge, the fulfilment enqueue — with a minted
``manual-<uuid>`` standing in for the ``merchant_order_id`` a person should not
have to invent (spec §11). A cabinet order and an API order are therefore the
same kind of thing in history, in the ledger and in a dispute, which is what
lets the catalog page double as the no-code first purchase.

Unlike ``/merchant/v1`` this is **not** exempt from the coarse rate limit: that
exemption exists because a 429 to a signing acquirer costs money and buys
nothing (AGENTS.md §9). A password form is the opposite case, and the two
credential routes carry the two-axis ``ip_guard`` besides.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.merchants import cabinet_auth, deposit, orders, price_list
from yupay.modules.merchants.cabinet_deps import current_merchant_user
from yupay.modules.merchants.cabinet_schemas import (
    CabinetConfirmIn,
    CabinetLoginIn,
    CabinetOrderIn,
    CabinetProfileOut,
    CabinetRegisterIn,
    CabinetTokenIn,
    CabinetTokensOut,
)
from yupay.modules.merchants.machine_schemas import (
    MerchantCatalogOut,
    MerchantOrderCreateIn,
    MerchantOrderOut,
)
from yupay.modules.merchants.models import Merchant, MerchantUser
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import merchant_confirm_email

log = get_logger("yupay.merchants.cabinet_routes")

router = APIRouter(prefix="/merchant/cabinet", tags=["merchant-cabinet"])

Db = Annotated[AsyncSession, Depends(db_session)]
CurrentUser = Annotated[MerchantUser, Depends(current_merchant_user)]


def _tokens_out(tokens: cabinet_auth.CabinetTokens) -> CabinetTokensOut:
    return CabinetTokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


async def _merchant_of(db: AsyncSession, user: MerchantUser) -> Merchant:
    """The company behind the signed-in operator.

    ``current_merchant_user`` has already proved it exists and is active, so
    this is a load and not a check — but it is loaded fresh on every request
    rather than carried in the token, so a freeze takes effect on the next
    call instead of when a JWT happens to expire.
    """
    merchant = await db.get(Merchant, user.merchant_id)
    assert merchant is not None, "resolve_user proved this row exists"
    return merchant


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
    s = get_settings()
    base = s.merchant_cabinet_url.rstrip("/")
    if not base:
        # Rather than register an account whose confirmation can never arrive.
        raise ValidationError(
            "the cabinet is not configured to send mail yet",
            code="cabinet_mail_unconfigured",
        )
    user, token = await cabinet_auth.register(
        db, email=body.email, password=body.password, title=body.title
    )
    try:
        content = merchant_confirm_email(link=f"{base}/confirm?token={token}")
        await send_email(
            to=user.email,
            subject=content.subject,
            html=content.html,
            text=content.text,
        )
    except EmailSendError:
        # The account exists and the address is unconfirmed, which is a state
        # the resend endpoint can repair. Failing the request would roll the
        # registration back and lose the password they just chose.
        log.exception("merchant.cabinet.confirm_mail_failed", user_id=user.id)
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


@router.get("/me", response_model=CabinetProfileOut, summary="The operator and their company")
async def me(user: CurrentUser, db: Db) -> CabinetProfileOut:
    merchant = await _merchant_of(db, user)
    return CabinetProfileOut(
        user_id=user.id,
        email=user.email,
        timezone=user.timezone,
        merchant_id=merchant.id,
        title=merchant.title,
        status=merchant.status,
        balance_usd=await deposit.deposit_balance(db, merchant_id=merchant.id),
        offer_version=user.offer_version,
        offer_accepted_at=user.offer_accepted_at,
    )


@router.get("/catalog", response_model=MerchantCatalogOut, summary="The wholesale price list")
async def catalog(user: CurrentUser, db: Db) -> MerchantCatalogOut:
    """The same tree the machine API serves, priced for this merchant.

    One builder, so the storefront a person browses and the JSON their server
    polls can never disagree about what is sellable or what it costs.
    """
    return await price_list.build(db, merchant=await _merchant_of(db, user))


@router.post(
    "/orders",
    response_model=MerchantOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Order from the catalog page",
)
async def place_order(body: CabinetOrderIn, user: CurrentUser, db: Db) -> MerchantOrderOut:
    """Buy one SKU, minting the idempotency key on the merchant's behalf.

    ``manual-<uuid>`` (spec §11): unique per click, and visibly not a
    reseller's own id, so a support conversation about "order acme-417" is
    never about one of these.

    The trade this makes, deliberately: a double-click is two orders, where an
    API caller re-sending one id gets one. A person can see both in the list
    and ask for a refund; an invented key that collapsed two intentional
    purchases into one would be the worse failure, and the browser prevents the
    common case by disabling the button.
    """
    merchant = await _merchant_of(db, user)
    return await orders.place(
        db,
        merchant=merchant,
        body=MerchantOrderCreateIn(
            merchant_order_id=f"manual-{new_id()}",
            sku_id=body.sku_id,
            quantity=body.quantity,
            amount_usd=body.amount_usd,
            expected_price=body.expected_price,
            fulfillment_data=dict(body.fulfillment_data),
        ),
    )


__all__ = ["router"]
