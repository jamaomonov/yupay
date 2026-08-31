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

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, UnauthorizedError, ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.admin.api import require_admin
from yupay.modules.affiliate import admin as affiliate_admin
from yupay.modules.affiliate import panel, partners, payouts
from yupay.modules.affiliate.deps import current_partner
from yupay.modules.affiliate.discount import (
    ResolvedDiscount,
    discount_amount,
    resolve_code,
)
from yupay.modules.affiliate.models import AffiliatePartner, AffiliatePayout
from yupay.modules.affiliate.partners import send_partner_invite
from yupay.modules.affiliate.schemas import (
    AdminPartnerDetailOut,
    AdminPartnerListOut,
    AdminPartnerOut,
    AdminPartnerStatsOut,
    AdminPartnerUpdateIn,
    AdminPayoutDetailOut,
    AdminPayoutListOut,
    AdminPayoutOut,
    ApplicationIn,
    ApplicationOut,
    BalanceOut,
    CodeOut,
    CommissionListOut,
    CommissionOut,
    IssueCodeIn,
    LoginIn,
    PayoutListOut,
    PayoutOut,
    PayoutRequestIn,
    PreviewIn,
    PreviewOut,
    ProfileOut,
    ReinviteOut,
    RejectIn,
    SetPasswordIn,
    StatsOut,
    TokensOut,
    UpdateCodeIn,
)
from yupay.modules.auth.cookies import (
    PARTNER_REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    set_refresh_cookie,
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


def _tokens_response(response: Response, tokens: partners.PartnerTokens) -> TokensOut:
    """Put the access token in the body and the refresh token in a cookie.

    The refresh token never appears in the JSON, the same as the buyer flow
    (ADR-0007): it lives 30 days and grants a session that can move money out,
    so a single XSS regression must not be able to read it. The panel used to
    keep it in `sessionStorage` because this did not exist yet.
    """
    set_refresh_cookie(
        response,
        token=tokens.refresh_token,
        max_age=get_settings().affiliate_refresh_ttl_seconds,
        settings=get_settings(),
        name=PARTNER_REFRESH_COOKIE_NAME,
    )
    return TokensOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


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
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Open a partner session.

    Guarded on the email axis as well as the IP one: without it, one address
    can be attacked from many.
    """
    await guard_ip(request, bucket="affiliate-login", subject=body.email)
    tokens = await partners.login(db, email=body.email, password=body.password)
    return _tokens_response(response, tokens)


@router.post("/auth/refresh", response_model=TokensOut, summary="Rotate a partner session")
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    partner_refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokensOut:
    """Exchange the refresh cookie for a new pair. The old one stops working.

    The token comes from the cookie, never from a body: a body field would
    mean JavaScript had to hold it, which is the thing the cookie exists to
    prevent.
    """
    if not partner_refresh_token:
        raise UnauthorizedError("missing refresh token")
    tokens = await partners.rotate(db, refresh_token=partner_refresh_token)
    return _tokens_response(response, tokens)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a partner session",
)
async def logout(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    partner_refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    """Revoke one session and clear the cookie. Silent if already unusable."""
    if partner_refresh_token:
        await partners.logout(db, refresh_token=partner_refresh_token)
    clear_refresh_cookie(response, settings=get_settings(), name=PARTNER_REFRESH_COOKIE_NAME)


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


admin_router = APIRouter(
    prefix="/admin/affiliate",
    tags=["admin:affiliate"],
    dependencies=[Depends(require_admin)],
)


def _partner_out(row: AffiliatePartner) -> AdminPartnerOut:
    return AdminPartnerOut.model_validate(row)


@admin_router.get(
    "/applications",
    response_model=AdminPartnerListOut,
    summary="The application queue",
)
async def admin_applications(
    db: Annotated[AsyncSession, Depends(db_session)],
    status_filter: str = "pending",
) -> AdminPartnerListOut:
    rows = await affiliate_admin.list_applications(db, status=status_filter)
    return AdminPartnerListOut(items=[_partner_out(r) for r in rows])


@admin_router.post(
    "/applications/{partner_id}/approve",
    response_model=AdminPartnerOut,
    summary="Approve an application and email the set-password link",
)
async def admin_approve(
    partner_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerOut:
    """Approve, then send the link.

    The send is deliberately **after** the approval and its failure is
    swallowed: an approved partner with an undelivered email is recoverable by
    re-sending, while an approval rolled back because the mail provider was
    down is not, and leaves an applicant waiting on silence.
    """
    token = await partners.approve(db, partner_id=partner_id)
    row = await db.get(AffiliatePartner, partner_id)
    if row is None:  # pragma: no cover -- approve() would have raised
        raise NotFoundError("partner not found")
    await send_partner_invite(email=row.email, token=token)
    return _partner_out(row)


@admin_router.post(
    "/applications/{partner_id}/reject",
    response_model=AdminPartnerOut,
    summary="Turn an application down",
)
async def admin_reject(
    partner_id: str,
    body: RejectIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerOut:
    await partners.reject(db, partner_id=partner_id, note=body.note)
    row = await db.get(AffiliatePartner, partner_id)
    if row is None:  # pragma: no cover -- reject() would have raised
        raise NotFoundError("partner not found")
    return _partner_out(row)


@admin_router.post(
    "/partners/{partner_id}/reinvite",
    response_model=ReinviteOut,
    summary="Re-issue a partner's set-password link",
)
async def admin_reinvite(
    partner_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ReinviteOut:
    """For "they never got the email".

    The link comes back in the response as well as going out by mail, so an
    admin can deliver it by hand. Not an escalation: this admin can already
    suspend the partner and send their balance to any card.
    """
    token = await partners.reinvite(db, partner_id=partner_id)
    row = await db.get(AffiliatePartner, partner_id)
    if row is None:  # pragma: no cover -- reinvite() would have raised
        raise NotFoundError("partner not found")
    emailed = await send_partner_invite(email=row.email, token=token)
    base = get_settings().partners_base_url.rstrip("/")
    return ReinviteOut(link=f"{base}/set-password?token={token}", emailed=emailed)


@admin_router.get(
    "/partners", response_model=AdminPartnerListOut, summary="Everyone in the programme"
)
async def admin_partners(
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerListOut:
    rows = await affiliate_admin.list_partners(db)
    return AdminPartnerListOut(items=[_partner_out(r) for r in rows])


@admin_router.get(
    "/partners/{partner_id}",
    response_model=AdminPartnerDetailOut,
    summary="One partner: profile, codes, stats and balance",
)
async def admin_partner_detail(
    partner_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerDetailOut:
    detail = await affiliate_admin.partner_detail(db, partner_id=partner_id)
    return AdminPartnerDetailOut(
        partner=_partner_out(detail.partner),
        codes=[CodeOut.model_validate(c) for c in detail.codes],
        stats_month=AdminPartnerStatsOut(**detail.stats_month),
        stats_year=AdminPartnerStatsOut(**detail.stats_year),
        balance=detail.balance,
    )


@admin_router.patch(
    "/partners/{partner_id}",
    response_model=AdminPartnerOut,
    summary="Edit a partner's descriptive fields",
)
async def admin_update_partner(
    partner_id: str,
    body: AdminPartnerUpdateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerOut:
    """Fields absent from the body stay untouched; "" clears to NULL."""
    fields = body.model_dump(exclude_unset=True)
    row = await affiliate_admin.update_partner(db, partner_id=partner_id, **fields)
    return _partner_out(row)


@admin_router.post(
    "/partners/{partner_id}/unsuspend",
    response_model=AdminPartnerOut,
    summary="Switch a suspended partner back on",
)
async def admin_unsuspend(
    partner_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerOut:
    """Their code applies at checkout again and they can sign in afresh;
    sessions revoked by the suspension stay revoked."""
    await affiliate_admin.unsuspend_partner(db, partner_id=partner_id)
    row = await db.get(AffiliatePartner, partner_id)
    if row is None:  # pragma: no cover -- unsuspend_partner() would have raised
        raise NotFoundError("partner not found")
    return _partner_out(row)


@admin_router.post(
    "/partners/{partner_id}/codes",
    response_model=CodeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a code",
)
async def admin_issue_code(
    partner_id: str,
    body: IssueCodeIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> CodeOut:
    code = await affiliate_admin.issue_code(
        db,
        partner_id=partner_id,
        code=body.code,
        discount_percent=body.discount_percent,
        commission_percent=body.commission_percent,
    )
    return CodeOut.model_validate(code)


@admin_router.patch("/codes/{code_id}", response_model=CodeOut, summary="Retune or disable a code")
async def admin_update_code(
    code_id: str,
    body: UpdateCodeIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> CodeOut:
    code = await affiliate_admin.update_code(
        db,
        code_id=code_id,
        discount_percent=body.discount_percent,
        commission_percent=body.commission_percent,
        active=body.active,
    )
    return CodeOut.model_validate(code)


@admin_router.post(
    "/partners/{partner_id}/suspend",
    response_model=AdminPartnerOut,
    summary="Switch a partner off",
)
async def admin_suspend(
    partner_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPartnerOut:
    """Stops their code working and signs them out. Their accrued commission
    is untouched — suspension is not confiscation."""
    await affiliate_admin.suspend_partner(db, partner_id=partner_id)
    row = await db.get(AffiliatePartner, partner_id)
    if row is None:  # pragma: no cover -- suspend_partner() would have raised
        raise NotFoundError("partner not found")
    return _partner_out(row)


async def _payout_out(db: AsyncSession, row: AffiliatePayout) -> AdminPayoutOut:
    partner = await db.get(AffiliatePartner, row.partner_id)
    base = PayoutOut.from_row(row)
    return AdminPayoutOut(
        **base.model_dump(),
        partner_id=row.partner_id,
        partner_email=partner.email if partner else "",
    )


@admin_router.get(
    "/payouts", response_model=AdminPayoutListOut, summary="The withdrawal queue (card masked)"
)
async def admin_payouts(
    db: Annotated[AsyncSession, Depends(db_session)],
    status_filter: str | None = None,
) -> AdminPayoutListOut:
    """Masked on purpose. This is the screen an admin has open all day; the
    full number lives behind the detail endpoint below."""
    rows = await affiliate_admin.list_payouts(db, status=status_filter)
    return AdminPayoutListOut(items=[await _payout_out(db, r) for r in rows])


@admin_router.get(
    "/payouts/{payout_id}",
    response_model=AdminPayoutDetailOut,
    summary="One withdrawal, card unmasked",
)
async def admin_payout_detail(
    payout_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPayoutDetailOut:
    """The only response anywhere carrying a full card number.

    A single deliberate door rather than a field on the queue: the admin opens
    this when they are about to type the number into a banking app.
    """
    row = await affiliate_admin.get_payout(db, payout_id=payout_id)
    masked = await _payout_out(db, row)
    return AdminPayoutDetailOut(**masked.model_dump(), card_number=row.card_number)


@admin_router.post(
    "/payouts/{payout_id}/paid",
    response_model=AdminPayoutOut,
    summary="Record that the transfer happened",
)
async def admin_mark_paid(
    payout_id: str,
    body: RejectIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPayoutOut:
    """The only irreversible action in the programme — rejecting returns the
    money, but 'paid' asserts a transfer happened and has no undo."""
    await payouts.mark_paid(db, payout_id=payout_id, note=body.note)
    return await _payout_out(db, await affiliate_admin.get_payout(db, payout_id=payout_id))


@admin_router.post(
    "/payouts/{payout_id}/reject",
    response_model=AdminPayoutOut,
    summary="Refuse a request and return the money",
)
async def admin_reject_payout(
    payout_id: str,
    body: RejectIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> AdminPayoutOut:
    await payouts.reject_payout(db, payout_id=payout_id, note=body.note)
    return await _payout_out(db, await affiliate_admin.get_payout(db, payout_id=payout_id))


__all__ = ["admin_router", "router"]
