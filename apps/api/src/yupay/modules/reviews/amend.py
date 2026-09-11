"""Body-only amend within a short window after create.

The rating stays frozen (aggregates and the SEO snapshot do not move). The
window exists so a one-tap star can POST immediately and the optional comment
or chip can follow without a second review row. See ADR-0039.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ForbiddenError, NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.modules.reviews.models import Review
from yupay.modules.reviews.service import _strip_html

log = get_logger("yupay.reviews.amend")

#: Long enough to tap a chip or type a sentence; short enough that a later
#: change of mind cannot rewrite the public page after it has been indexed.
AMEND_WINDOW = timedelta(minutes=15)


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
    if now() - review.created_at > AMEND_WINDOW:
        raise ForbiddenError("amend window closed", code="amend_window_closed")

    review.body = cleaned
    review.updated_at = now()
    await db.flush()
    log.info("review.body_amended", review_id=review.id)
    return review


__all__ = ["AMEND_WINDOW", "amend_review_body"]
