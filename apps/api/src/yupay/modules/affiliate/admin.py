"""Running the programme: issuing codes, tuning rates, switching a partner off.

The percentage ranges are checked here as well as by the database. The CHECK
constraint is the backstop that guarantees no row escapes it; this layer is
what turns "violates ck_affiliate_codes_discount_range" into a sentence an
admin can act on. A person typing 15 should be told the range, not shown a
constraint name.

Suspending a partner means it. The row's status changes, which stops
``resolve_code`` accepting their code, **and** their sessions are revoked —
otherwise a suspended partner with an open panel tab can still request a
payout, which is the one action here that moves money outward.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.affiliate.models import (
    AffiliateCode,
    AffiliatePartner,
    AffiliatePayout,
    AffiliateSession,
)

log = get_logger("yupay.affiliate.admin")

#: The ranges the business runs on, mirrored from the CHECK constraints.
#: Measured margin on price is 14.0% at worst, and break-even including
#: commission is a discount of about 12.2% — see the spec.
DISCOUNT_MIN = Decimal("3")
DISCOUNT_MAX = Decimal("10")
COMMISSION_MIN = Decimal("1")
COMMISSION_MAX = Decimal("2")

#: What a code may be made of. Partners advertise these aloud and in captions,
#: so they have to be short and unambiguous to read back.
_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
_MIN_LENGTH = 4
_MAX_LENGTH = 32


def _check_rates(discount: Decimal, commission: Decimal) -> None:
    if not DISCOUNT_MIN <= discount <= DISCOUNT_MAX:
        raise ValidationError(
            f"discount must be between {DISCOUNT_MIN} and {DISCOUNT_MAX} percent",
            extra={"min": str(DISCOUNT_MIN), "max": str(DISCOUNT_MAX)},
        )
    if not COMMISSION_MIN <= commission <= COMMISSION_MAX:
        raise ValidationError(
            f"commission must be between {COMMISSION_MIN} and {COMMISSION_MAX} percent",
            extra={"min": str(COMMISSION_MIN), "max": str(COMMISSION_MAX)},
        )


def _normalise_code(raw: str) -> str:
    code = raw.strip().upper()
    if not _MIN_LENGTH <= len(code) <= _MAX_LENGTH:
        raise ValidationError(
            f"code must be between {_MIN_LENGTH} and {_MAX_LENGTH} characters",
        )
    if any(ch not in _ALLOWED for ch in code):
        raise ValidationError("code may contain only A-Z, 0-9 and a dash")
    return code


async def issue_code(
    db: AsyncSession,
    *,
    partner_id: str,
    code: str,
    discount_percent: Decimal,
    commission_percent: Decimal,
) -> AffiliateCode:
    """Give a partner a code to promote.

    Args:
        db: Session. The caller owns the transaction.
        partner_id: Who owns it.
        code: As typed; normalised to uppercase, which is how lookups compare.
        discount_percent: What the buyer saves, 3–10.
        commission_percent: What the partner keeps, 1–2.

    Returns:
        The stored code.

    Raises:
        NotFoundError: No such partner.
        ValidationError: Bad code shape, or a rate outside its range.
        ConflictError: That code already exists.
    """
    partner = await db.get(AffiliatePartner, partner_id)
    if partner is None:
        raise NotFoundError("partner not found")

    _check_rates(discount_percent, commission_percent)
    normalised = _normalise_code(code)

    row = AffiliateCode(
        id=new_id(),
        partner_id=partner_id,
        code=normalised,
        discount_percent=discount_percent,
        commission_percent=commission_percent,
    )
    try:
        # Inside the SAVEPOINT: added before it, a UNIQUE(code) failure would
        # leave the doomed row in ``session.new`` and poison the session.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError("that code already exists") from exc

    log.info("affiliate.code.issued", partner_id=partner_id, code=normalised)
    return row


async def update_code(
    db: AsyncSession,
    *,
    code_id: str,
    discount_percent: Decimal | None = None,
    commission_percent: Decimal | None = None,
    active: bool | None = None,
) -> AffiliateCode:
    """Retune a code, or switch it off.

    Changing a rate affects future orders only: past commission is frozen on
    its own row at accrual time, so nothing already earned is revalued.

    Raises:
        NotFoundError: No such code.
        ValidationError: A rate outside its range.
    """
    code = await db.get(AffiliateCode, code_id)
    if code is None:
        raise NotFoundError("code not found")

    _check_rates(
        discount_percent if discount_percent is not None else code.discount_percent,
        commission_percent if commission_percent is not None else code.commission_percent,
    )

    if discount_percent is not None:
        code.discount_percent = discount_percent
    if commission_percent is not None:
        code.commission_percent = commission_percent
    if active is not None:
        code.active = active
    await db.flush()

    log.info("affiliate.code.updated", code_id=code_id, active=code.active)
    return code


async def suspend_partner(db: AsyncSession, *, partner_id: str) -> None:
    """Switch a partner off, and mean it.

    Two effects, and both are needed. The status change stops ``resolve_code``
    accepting their code at checkout. Revoking their sessions stops the partner
    themselves — a suspended partner with an open tab could otherwise still
    request a payout, which is the one action in this programme that sends
    money out of the business.

    Their accrued commission is untouched: suspension is not confiscation, and
    what they have already earned is settled by a person deciding, not by a
    status flag.

    Raises:
        NotFoundError: No such partner.
    """
    partner = await db.get(AffiliatePartner, partner_id)
    if partner is None:
        raise NotFoundError("partner not found")

    partner.status = "suspended"
    moment = now()
    sessions = (
        await db.execute(
            select(AffiliateSession).where(
                AffiliateSession.partner_id == partner_id,
                AffiliateSession.revoked_at.is_(None),
            )
        )
    ).scalars()
    for session in sessions:
        session.revoked_at = moment
    await db.flush()
    log.info("affiliate.partner.suspended", partner_id=partner_id)


async def list_applications(
    db: AsyncSession, *, status: str = "pending", limit: int = 50
) -> list[AffiliatePartner]:
    """The application queue, newest first."""
    rows = (
        await db.execute(
            select(AffiliatePartner)
            .where(AffiliatePartner.status == status)
            .order_by(AffiliatePartner.created_at.desc(), AffiliatePartner.id.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars()
    return list(rows)


async def list_partners(db: AsyncSession, *, limit: int = 100) -> list[AffiliatePartner]:
    """Everyone in the programme, newest first."""
    rows = (
        await db.execute(
            select(AffiliatePartner)
            .order_by(AffiliatePartner.created_at.desc(), AffiliatePartner.id.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars()
    return list(rows)


async def list_payouts(
    db: AsyncSession, *, status: str | None = None, limit: int = 50
) -> list[AffiliatePayout]:
    """The withdrawal queue, newest first."""
    stmt = select(AffiliatePayout)
    if status is not None:
        stmt = stmt.where(AffiliatePayout.status == status)
    rows = (
        await db.execute(
            stmt.order_by(AffiliatePayout.created_at.desc(), AffiliatePayout.id.desc()).limit(
                max(1, min(limit, 200))
            )
        )
    ).scalars()
    return list(rows)


async def get_payout(db: AsyncSession, *, payout_id: str) -> AffiliatePayout:
    """One withdrawal request.

    The only read that yields the full card number, and it is a separate call
    on purpose — see the route that serves it.

    Raises:
        NotFoundError: No such payout.
    """
    payout = await db.get(AffiliatePayout, payout_id)
    if payout is None:
        raise NotFoundError("payout not found")
    return payout


__all__ = [
    "COMMISSION_MAX",
    "COMMISSION_MIN",
    "DISCOUNT_MAX",
    "DISCOUNT_MIN",
    "get_payout",
    "issue_code",
    "list_applications",
    "list_partners",
    "list_payouts",
    "suspend_partner",
    "update_code",
]
