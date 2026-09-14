"""HTTP routes for ``reviews``: public browse/submit/report + admin moderation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user, resolve_request_actor
from yupay.modules.reviews import service as svc
from yupay.modules.reviews.amend import amend_review_body, can_amend
from yupay.modules.reviews.models import BrandRatingStats, Review
from yupay.modules.reviews.pending import pending_ask
from yupay.modules.reviews.schemas import (
    AdminBrandReviewStatsListOut,
    AdminBrandReviewStatsOut,
    AdminReviewListOut,
    AdminReviewOut,
    OwnReviewListOut,
    OwnReviewOut,
    ReviewAmendIn,
    ReviewCreateIn,
    ReviewEligibilityOut,
    ReviewListOut,
    ReviewOut,
    ReviewPendingAskOut,
    ReviewReportIn,
    ReviewStatsOut,
)
from yupay.modules.users.models import User

router = APIRouter(prefix="/reviews", tags=["reviews"])
admin_router = APIRouter(
    prefix="/admin/reviews",
    tags=["admin:reviews"],
    dependencies=[Depends(require_admin)],
)


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


def _stats_out(stats: BrandRatingStats | None) -> ReviewStatsOut:
    if stats is None:
        return ReviewStatsOut(avg=0.0, count=0, dist={1: 0, 2: 0, 3: 0, 4: 0, 5: 0})
    return ReviewStatsOut(
        avg=float(stats.avg),
        count=stats.count,
        dist={
            1: stats.count_1,
            2: stats.count_2,
            3: stats.count_3,
            4: stats.count_4,
            5: stats.count_5,
        },
    )


def _admin_out(review: Review, report_count: int) -> AdminReviewOut:
    return AdminReviewOut.model_validate({**review.__dict__, "report_count": report_count})


# ---------- public ----------


@router.get(
    "/brands/{slug}",
    response_model=ReviewListOut,
    summary="List published reviews for a brand + aggregate",
)
async def list_brand_reviews(
    slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> ReviewListOut:
    brand_id = await svc.resolve_brand_id(db, slug)
    items, next_cursor = await svc.list_published(db, brand_id=brand_id, limit=limit, cursor=cursor)
    stats = (await svc.get_stats(db, [brand_id])).get(brand_id)
    return ReviewListOut(items=items, next_cursor=next_cursor, stats=_stats_out(stats))


@router.post(
    "",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a review for a delivered order (user or guest)",
)
async def create_review_route(
    body: ReviewCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> ReviewOut:
    _require_idempotency_key(idempotency_key)
    actor = await resolve_request_actor(request, db)
    locale = actor.user.locale if actor.user else (request.headers.get("Accept-Language") or "ru")
    review = await svc.create_review(
        db,
        user_id=actor.user_id,
        guest_email=actor.guest_email,
        order_id=body.order_id,
        brand_slug=body.brand_slug,
        rating=body.rating,
        body=body.body,
        locale=locale,
    )
    return ReviewOut(
        id=review.id,
        rating=review.rating,
        body=review.body,
        author_name=actor.user.display_name if actor.user else None,
        created_at=review.created_at,
    )


@router.get(
    "/eligibility",
    response_model=ReviewEligibilityOut,
    summary="Whether the actor's order can be reviewed / already was",
)
async def review_eligibility_route(
    order_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ReviewEligibilityOut:
    actor = await resolve_request_actor(request, db)
    brand_slug, delivered, already = await svc.review_eligibility(
        db, order_id=order_id, user_id=actor.user_id, guest_email=actor.guest_email
    )
    return ReviewEligibilityOut(
        brand_slug=brand_slug, delivered=delivered, already_reviewed=already
    )


@router.get("/mine", response_model=OwnReviewListOut, summary="The caller's own reviews")
async def list_own_reviews(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> OwnReviewListOut:
    reviews = await svc.list_own(db, user_id=user.id)
    at = now()
    return OwnReviewListOut(
        items=[
            OwnReviewOut(
                id=r.id,
                order_id=r.order_id,
                brand_id=r.brand_id,
                rating=r.rating,
                body=r.body,
                can_add_text=can_amend(r, at=at),
            )
            for r in reviews
        ]
    )


@router.get(
    "/pending-ask",
    response_model=ReviewPendingAskOut | None,
    summary="Unreviewed delivered order old enough to ask about on next session",
)
async def pending_ask_route(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> ReviewPendingAskOut | None:
    """The catch-up prompt's input: one catalog order, or null.

    User-only (Mini App has no guests). A 2-hour floor keeps this off the
    same session as delivery — the buyer left to check the game.
    """
    row = await pending_ask(db, user_id=user.id, locale=user.locale)
    if row is None:
        return None
    return ReviewPendingAskOut(
        order_id=row.order_id,
        brand_slug=row.brand_slug,
        brand_name=row.brand_name,
        delivered_at=row.delivered_at,
    )


@router.patch(
    "/{review_id}",
    response_model=ReviewOut,
    summary="Add or replace the comment on a review just submitted (15-minute window)",
)
async def amend_review_route(
    review_id: str,
    body: ReviewAmendIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> ReviewOut:
    """Body-only follow-up after a one-tap rating. Rating cannot change.

    The same actor resolution as ``POST /reviews`` (Bearer or Guest). The
    window is 15 minutes from ``created_at``; after that the review is frozen
    again. Idempotency-Key required like every other write.
    """
    _require_idempotency_key(idempotency_key)
    actor = await resolve_request_actor(request, db)
    review = await amend_review_body(
        db,
        review_id=review_id,
        user_id=actor.user_id,
        guest_email=actor.guest_email,
        body=body.body,
    )
    return ReviewOut(
        id=review.id,
        rating=review.rating,
        body=review.body,
        author_name=actor.user.display_name if actor.user else None,
        created_at=review.created_at,
    )


@router.post(
    "/{review_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Report a review for abuse",
)
async def report_review_route(
    review_id: str,
    body: ReviewReportIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> None:
    _require_idempotency_key(idempotency_key)
    await svc.report_review(db, review_id=review_id, reporter_user_id=user.id, reason=body.reason)


# ---------- admin ----------


@admin_router.get("", response_model=AdminReviewListOut, summary="Moderation queue")
async def admin_list_reviews(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    review_status: Annotated[str | None, Query(alias="status")] = None,
    reported: bool = False,
    brand: Annotated[str | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminReviewListOut:
    rows, total = await svc.admin_list(
        db,
        status=review_status,
        reported_only=reported,
        limit=limit,
        offset=offset,
        brand_slug=brand,
    )
    return AdminReviewListOut(
        items=[
            AdminReviewOut.model_validate(
                {
                    **row.review.__dict__,
                    "report_count": row.report_count,
                    "brand_slug": row.brand_slug,
                    "brand_name": row.brand_name,
                    "brand_logo_url": row.brand_logo_url,
                    "user_name": row.user_name,
                }
            )
            for row in rows
        ],
        total=total,
    )


@admin_router.get(
    "/by-brand",
    response_model=AdminBrandReviewStatsListOut,
    summary="Reviews grouped by brand",
)
async def admin_reviews_by_brand(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> AdminBrandReviewStatsListOut:
    """Counts, average rating and complaint count per brand.

    Aggregated server-side because the queue itself is capped: counting on the
    client would describe the first 200 reviews as if they were all of them.
    """
    rows = await svc.admin_brand_stats(db)
    return AdminBrandReviewStatsListOut(
        items=[AdminBrandReviewStatsOut(**row._asdict()) for row in rows]
    )


async def _moderate(
    db: AsyncSession, review_id: str, new_status: str, idempotency_key: str | None
) -> AdminReviewOut:
    # Every moderation action is naturally idempotent: setting a review to a
    # status it already holds is a no-op (no double stats adjustment), so we
    # require the header for consistency but need no separate replay store.
    _require_idempotency_key(idempotency_key)
    review = await svc.admin_set_status(db, review_id=review_id, status=new_status)
    return _admin_out(review, await svc.count_reports(db, review_id))


@admin_router.post("/{review_id}/hide", response_model=AdminReviewOut, summary="Hide a review")
async def admin_hide_review(
    review_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminReviewOut:
    return await _moderate(db, review_id, "hidden", idempotency_key)


@admin_router.post(
    "/{review_id}/unhide", response_model=AdminReviewOut, summary="Republish a review"
)
async def admin_unhide_review(
    review_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminReviewOut:
    return await _moderate(db, review_id, "published", idempotency_key)


@admin_router.post("/{review_id}/remove", response_model=AdminReviewOut, summary="Remove a review")
async def admin_remove_review(
    review_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminReviewOut:
    return await _moderate(db, review_id, "removed", idempotency_key)
