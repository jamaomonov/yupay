"""HTTP routes for ``promo``: customer redemption + admin issuance."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.promo import service as svc
from yupay.modules.promo.schemas import (
    PromoAdminListOut,
    PromoAdminOut,
    PromoCreateIn,
    PromoRedeemIn,
    PromoRedeemOut,
)
from yupay.modules.users.models import User

router = APIRouter(prefix="/promo", tags=["promo"])
admin_router = APIRouter(
    prefix="/admin/promo",
    tags=["admin:promo"],
    dependencies=[Depends(require_admin)],
)


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


# ---------- customer ----------


@router.post("/redeem", response_model=PromoRedeemOut, summary="Redeem a promo code")
async def redeem_route(
    body: PromoRedeemIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> PromoRedeemOut:
    key = _require_idempotency_key(idempotency_key)
    promo, _redemption = await svc.redeem(db, user_id=user.id, code=body.code, idempotency_key=key)
    return PromoRedeemOut(code=promo.code, amount=promo.amount, currency=promo.currency)


# ---------- admin ----------


@admin_router.post(
    "",
    response_model=PromoAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a promo code",
)
async def admin_create_promo(
    body: PromoCreateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> PromoAdminOut:
    _require_idempotency_key(idempotency_key)
    promo = await svc.create_code(db, body=body, admin_id=admin.id)
    return PromoAdminOut.model_validate({**promo.__dict__, "redemptions": 0})


@admin_router.get("", response_model=PromoAdminListOut, summary="List promo codes with usage")
async def admin_list_promos(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    limit: int = 100,
) -> PromoAdminListOut:
    rows = await svc.list_codes(db, limit=max(1, min(limit, 500)))
    return PromoAdminListOut(
        items=[
            PromoAdminOut.model_validate({**promo.__dict__, "redemptions": count})
            for promo, count in rows
        ]
    )


@admin_router.post(
    "/{promo_id}/deactivate",
    response_model=PromoAdminOut,
    summary="Deactivate a promo code",
)
async def admin_deactivate_promo(
    promo_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PromoAdminOut:
    promo = await svc.deactivate(db, promo_id=promo_id)
    rows = await svc.list_codes(db, limit=500)
    count = next((c for p, c in rows if p.id == promo.id), 0)
    return PromoAdminOut.model_validate({**promo.__dict__, "redemptions": count})
