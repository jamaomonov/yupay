"""HTTP routes for ``affiliate``: the buyer-facing code preview.

Deliberately **not** re-exported from ``affiliate.api``. That facade is
imported by ``payments.service`` and ``orders.service``, and a router imported
from either of those closes a cycle back through the v1 route stack — the same
cycle that broke the first test written against this module. ``api/v1`` imports
this file directly instead.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.affiliate import panel, partners, payouts
from yupay.modules.affiliate.deps import current_partner
from yupay.modules.affiliate.discount import (
    ResolvedDiscount,
    discount_amount,
    resolve_code,
)
from yupay.modules.affiliate.models import AffiliatePartner
from yupay.modules.affiliate.schemas import (
    ApplicationIn,
    ApplicationOut,
    BalanceOut,
    CodeOut,
    CommissionListOut,
    CommissionOut,
    LoginIn,
    PayoutListOut,
    PayoutOut,
    PayoutRequestIn,
    PreviewIn,
    PreviewOut,
    ProfileOut,
    RefreshIn,
    SetPasswordIn,
    StatsOut,
    TokensOut,
)
from yupay.modules.auth.deps import current_user
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.orders.schemas import OrderCreate
from yupay.modules.orders.service import quote_cart
from yupay.modules.users.models import User

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


@router.post(
    "/preview",
    response_model=PreviewOut,
    summary="What a partner code would do to this cart",
)
async def preview(
    body: PreviewIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> PreviewOut:
    """Price the cart, then say whether the code applies to it.

    Signed-in only, because a partner code binds a buyer to a partner and a
    guest has nothing durable to bind. That also gives the throttle a subject:
    the two-axis guard keys on the buyer, so one account cannot grind through
    the code space from a rotating address.

    The amounts are for display only. ``create_order`` resolves the code again
    and prices the order itself, so nothing here can be spent.
    """
    # This endpoint answers "is this string a usable promo code", which is a
    # guessing surface by construction. The codes are short and advertised, so
    # they cannot be made unguessable — the throttle is the whole defence.
    await guard_ip(request, bucket="affiliate-preview", subject=user.id)

    quote = await quote_cart(db, OrderCreate(currency=body.currency, items=body.items))

    resolved = await resolve_code(db, code=body.code, user_id=user.id, purpose="catalog")
    if not isinstance(resolved, ResolvedDiscount):
        return PreviewOut(
            applicable=False,
            reason=resolved,
            currency=quote.currency,
            total_before=quote.total_charged,
            total_after=quote.total_charged,
            discount=Decimal("0"),
        )

    discount = discount_amount(quote.total_charged, resolved.percent, quote.currency)
    return PreviewOut(
        applicable=True,
        code=resolved.code,
        percent=resolved.percent,
        currency=quote.currency,
        total_before=quote.total_charged,
        total_after=quote.total_charged - discount,
        discount=discount,
    )


__all__ = ["router"]


@router.post(
    "/applications",
    response_model=ApplicationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Apply to join the partner program",
)
async def apply(
    body: ApplicationIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ApplicationOut:
    """Record an application.

    Answers the same whether the address is new or has already applied. The
    alternative leaks the partner list to anyone with a list of addresses.

    Guarded on both axes — a public write endpoint that creates rows keyed by
    an attacker-chosen address needs the email axis as much as the IP one.
    """
    await guard_ip(request, bucket="affiliate-apply", subject=body.email)
    await partners.submit_application(
        db,
        email=body.email,
        display_name=body.display_name,
        contact=body.contact,
        channel=body.channel,
    )
    return ApplicationOut()


@router.post(
    "/auth/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a password using the approval link",
)
async def set_password(
    body: SetPasswordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    """Consume the one-time link from the approval email."""
    await guard_ip(request, bucket="affiliate-setpw")
    await partners.set_password(db, token=body.token, password=body.password)


@router.post("/auth/login", response_model=TokensOut, summary="Sign in as a partner")
async def login(
    body: LoginIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Open a partner session.

    Guarded on the email axis as well as the IP one: without it, one address
    can be attacked from many.
    """
    await guard_ip(request, bucket="affiliate-login", subject=body.email)
    tokens = await partners.login(db, email=body.email, password=body.password)
    return TokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/auth/refresh", response_model=TokensOut, summary="Rotate a partner session")
async def refresh(
    body: RefreshIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Exchange a refresh token for a new pair. The old one stops working."""
    tokens = await partners.rotate(db, refresh_token=body.refresh_token)
    return TokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a partner session",
)
async def logout(
    body: RefreshIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    """Revoke one session. Silent if it was already unusable."""
    await partners.logout(db, refresh_token=body.refresh_token)


@router.get("/me", response_model=ProfileOut, summary="The signed-in partner and their codes")
async def me(
    db: Annotated[AsyncSession, Depends(db_session)],
    partner: Annotated[AffiliatePartner, Depends(current_partner)],
) -> ProfileOut:
    """Profile plus codes. Never includes the password hash or the admin note."""
    return ProfileOut(
        id=partner.id,
        email=partner.email,
        display_name=partner.display_name,
        contact=partner.contact,
        channel=partner.channel,
        status=partner.status,
        created_at=partner.created_at,
        codes=[CodeOut.model_validate(c) for c in await panel.codes(db, partner_id=partner.id)],
    )


@router.get("/stats", response_model=StatsOut, summary="Earnings over a rolling window")
async def stats(
    db: Annotated[AsyncSession, Depends(db_session)],
    partner: Annotated[AffiliatePartner, Depends(current_partner)],
    period: panel.StatsPeriod = "month",
) -> StatsOut:
    """`month` is the last 30 days, not the calendar month — see
    ``affiliate.panel`` for why, and label it accordingly in any UI."""
    return StatsOut(**await panel.stats(db, partner_id=partner.id, period=period))


@router.get("/balance", response_model=BalanceOut, summary="Available, held and reserved")
async def balance(
    db: Annotated[AsyncSession, Depends(db_session)],
    partner: Annotated[AffiliatePartner, Depends(current_partner)],
) -> BalanceOut:
    """Read from the ledger, never summed from the commissions table."""
    amounts = await panel.balances(db, partner_id=partner.id)
    return BalanceOut(currency=panel.DEFAULT_CURRENCY, **amounts)


@router.get(
    "/commissions",
    response_model=CommissionListOut,
    summary="This partner's commissions",
)
async def commissions(
    db: Annotated[AsyncSession, Depends(db_session)],
    partner: Annotated[AffiliatePartner, Depends(current_partner)],
    limit: int = 50,
    offset: int = 0,
) -> CommissionListOut:
    rows, total = await panel.commissions(db, partner_id=partner.id, limit=limit, offset=offset)
    return CommissionListOut(items=[CommissionOut.model_validate(r) for r in rows], total=total)


@router.get("/payouts", response_model=PayoutListOut, summary="Withdrawal history")
async def list_payouts(
    db: Annotated[AsyncSession, Depends(db_session)],
    partner: Annotated[AffiliatePartner, Depends(current_partner)],
    limit: int = 50,
    offset: int = 0,
) -> PayoutListOut:
    rows = await payouts.list_for_partner(db, partner_id=partner.id, limit=limit, offset=offset)
    return PayoutListOut(items=[PayoutOut.from_row(r) for r in rows])


@router.post(
    "/payouts",
    response_model=PayoutOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request a withdrawal",
)
async def request_payout(
    body: PayoutRequestIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    partner: Annotated[AffiliatePartner, Depends(current_partner)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> PayoutOut:
    """Reserve money for a withdrawal.

    The partner comes from the token, never from the body: a payout endpoint
    that accepted a partner id would let one partner drain another.
    """
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(f"{IDEMPOTENCY_HEADER} header is required")
    row = await payouts.request_payout(
        db,
        partner_id=partner.id,
        amount=body.amount,
        card_number=body.card_number,
        card_holder=body.card_holder,
    )
    return PayoutOut.from_row(row)
