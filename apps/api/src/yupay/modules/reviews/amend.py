"""Body-only amend within a window after create.

The rating stays frozen (aggregates and the SEO snapshot do not move). The
window exists so a one-tap star can POST immediately and the optional comment
or chip can follow without a second review row. See ADR-0039.

**Two windows, because filling an empty body and replacing a written one are
different acts.** Replacing text that is already on the public page is the
thing a short window protects against: a reviewer who liked something on
Monday should not be able to rewrite an indexed page on Friday. Adding text to
a star-only review takes nothing back — there was no sentence to contradict,
and the rating it sits under does not move either way.

Measured on production 2026-09-14, this is not a hypothetical: of 45 reviews,
27 carried no text at all, and exactly one published review showed any
post-creation edit. A 15-minute window on "come back and write something" is a
window almost nobody was awake for.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ForbiddenError, NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.modules.reviews.models import Review
from yupay.modules.reviews.service import _strip_html

log = get_logger("yupay.reviews.amend")

#: Replacing a body that is already public: long enough to fix a typo or a
#: chip tapped by accident, short enough that a later change of mind cannot
#: rewrite an indexed page.
AMEND_WINDOW = timedelta(minutes=15)

#: Filling a body that is still empty. Matched to ``PENDING_ASK_MAX_AGE``, the
#: age at which we stop asking about an order at all: for exactly as long as we
#: are willing to prompt someone to write something, they are able to.
AMEND_FILL_WINDOW = timedelta(days=14)


def amend_deadline(review: Review) -> datetime:
    """When ``review`` stops accepting a body.

    One rule, so the endpoint's refusal and the "can this still be written on"
    flag the clients render from can never disagree — the flag is what decides
    whether a comment box is offered at all, and offering one that the next
    request refuses is worse than not offering it.
    """
    written = bool((review.body or "").strip())
    return review.created_at + (AMEND_WINDOW if written else AMEND_FILL_WINDOW)


def can_amend(review: Review, *, at: datetime) -> bool:
    """Whether ``amend_review_body`` would accept a write at ``at``."""
    return at <= amend_deadline(review)


async def amend_review_body(
    db: AsyncSession,
    *,
    review_id: str,
    user_id: str | None,
    guest_email: str | None,
    body: str,
) -> Review:
    """Replace ``body`` on a review the actor owns, if still inside the window.

    Rating is not accepted and not touched. Raises ``NotFoundError``,
    ``ForbiddenError`` (not the author, or the window has closed), or
    ``ValidationError`` (empty body after sanitising).
    """
    if (user_id is None) == (guest_email is None):
        raise ValidationError("exactly one of user_id / guest_email is required")
    cleaned = (_strip_html(body) or "").strip()
    if not cleaned:
        raise ValidationError("body is required")

    review = (await db.execute(select(Review).where(Review.id == review_id))).scalar_one_or_none()
    if review is None:
        raise NotFoundError("review not found")
    if user_id is not None:
        if review.user_id != user_id:
            raise ForbiddenError("not your review")
    elif review.guest_email is None or review.guest_email.lower() != guest_email:
        raise ForbiddenError("not your review")
    if not can_amend(review, at=now()):
        raise ForbiddenError("amend window closed", code="amend_window_closed")

    review.body = cleaned
    review.updated_at = now()
    await db.flush()
    log.info("review.body_amended", review_id=review.id)
    return review


__all__ = [
    "AMEND_FILL_WINDOW",
    "AMEND_WINDOW",
    "amend_deadline",
    "amend_review_body",
    "can_amend",
]
