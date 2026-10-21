"""Admin control over ``payment_review_limits`` — the per-kassa spend limit.

Two routes under ``/admin/payments/review-limits``: list every payment slug with its limit (a
slug without a row reads as "no limit"), and set one. The rule that reads them is
``orders.provider_limit``; this module only stores what an operator decides.

Per slug, not per logical provider: ``click`` and ``click_miniapp`` are one row on the
providers page, but two kassas with different risk — the mini-app one is where the limit was
asked for (owner, 2026-10-21).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.errors import NotFoundError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.models import PaymentReviewLimit
from yupay.modules.users.models import User

router = APIRouter(prefix="/review-limits")


class ReviewLimitOut(BaseModel):
    """One payment slug's limit. ``max_amount`` is ``None`` when none was ever set."""

    model_config = ConfigDict(frozen=True)

    provider: str
    enabled: bool
    max_amount: Decimal | None
    currency: str
    window_hours: int
    changed_by: str | None
    changed_at: datetime | None


class ReviewLimitListOut(BaseModel):
    """Every known payment slug, limited or not."""

    items: list[ReviewLimitOut]


class SetReviewLimitIn(BaseModel):
    """The limit an operator sets on one slug."""

    enabled: bool
    max_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    window_hours: int = Field(default=24, ge=1, le=720)


def _out(provider: str, row: PaymentReviewLimit | None) -> ReviewLimitOut:
    if row is None:
        return ReviewLimitOut(
            provider=provider,
            enabled=False,
            max_amount=None,
            currency="UZS",
            window_hours=24,
            changed_by=None,
            changed_at=None,
        )
    return ReviewLimitOut(
        provider=row.provider,
        enabled=row.enabled,
        max_amount=row.max_amount,
        currency=row.currency,
        window_hours=row.window_hours,
        changed_by=row.changed_by,
        changed_at=row.changed_at,
    )


async def list_limits(db: AsyncSession) -> list[ReviewLimitOut]:
    """Every registered payment slug with its limit, in registry order."""
    rows = {row.provider: row for row in (await db.scalars(select(PaymentReviewLimit))).all()}
    return [_out(slug, rows.get(slug)) for slug in REGISTRY]


async def set_limit(
    db: AsyncSession, *, provider: str, body: SetReviewLimitIn, changed_by: str
) -> ReviewLimitOut:
    """Create or replace one slug's limit.

    Raises:
        NotFoundError: ``provider`` is not a registered payment slug.
    """
    if provider not in REGISTRY:
        raise NotFoundError("unknown payment provider", provider=provider)
    row = await db.get(PaymentReviewLimit, provider)
    if row is None:
        row = PaymentReviewLimit(provider=provider, currency="UZS")
        db.add(row)
    row.enabled = body.enabled
    row.max_amount = body.max_amount
    row.window_hours = body.window_hours
    row.changed_by = changed_by
    row.changed_at = now()
    await db.flush()
    return _out(provider, row)


@router.get(
    "",
    response_model=ReviewLimitListOut,
    summary="Per-kassa spend limits: past them a buyer's order waits for review",
)
async def admin_list_review_limits(
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ReviewLimitListOut:
    return ReviewLimitListOut(items=await list_limits(db))


@router.put(
    "/{provider}",
    response_model=ReviewLimitOut,
    summary="Set one kassa's spend limit (summed per buyer over the window)",
)
async def admin_set_review_limit(
    provider: str,
    body: SetReviewLimitIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> ReviewLimitOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = f"payments.review_limit:{provider}"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return ReviewLimitOut.model_validate(cached.body)
    out = await set_limit(db, provider=provider, body=body, changed_by=admin.id)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["ReviewLimitListOut", "ReviewLimitOut", "SetReviewLimitIn", "list_limits", "router"]
