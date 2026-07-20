"""Promo service: admin issuance + customer redemption.

Redemption is the only money-moving path: it books
``D user_wallet / C house_promo_expense`` through ``wallet.api.post`` (see
ADR-0029), so the gift is immediately visible in the balance and spendable
through the wallet gateway. ``UNIQUE(promo_code_id, user_id)`` is the
once-per-user guarantee; the per-code ``FOR UPDATE`` serialises concurrent
redemptions so the global cap can't be raced past.
"""

from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.promo.models import PromoCode, PromoRedemption
from yupay.modules.promo.schemas import PromoCreateIn
from yupay.modules.wallet import api as wallet_api

log = get_logger("yupay.promo.service")


def _normalise(code: str) -> str:
    return code.strip().upper()


async def redeem(
    db: AsyncSession,
    *,
    user_id: str,
    code: str,
    idempotency_key: str | None = None,
) -> tuple[PromoCode, PromoRedemption]:
    """Redeem ``code`` for ``user_id``; credits the user's wallet.

    A repeated call with the same ``idempotency_key`` replays the original
    success; any other repeat is refused with a conflict.
    """
    normalised = _normalise(code)
    promo = (
        await db.execute(select(PromoCode).where(PromoCode.code == normalised).with_for_update())
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("promo code not found")

    existing = (
        await db.execute(
            select(PromoRedemption).where(
                PromoRedemption.promo_code_id == promo.id,
                PromoRedemption.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if idempotency_key is not None and existing.idempotency_key == idempotency_key:
            return promo, existing  # timeout-retry replay
        raise ConflictError("promo code already redeemed", code="already_redeemed")

    if not promo.active:
        raise ConflictError("promo code is no longer active", code="inactive")
    if promo.expires_at is not None and now() > promo.expires_at:
        raise ConflictError("promo code has expired", code="expired")
    if promo.max_redemptions is not None:
        used = (
            await db.execute(
                select(func.count())
                .select_from(PromoRedemption)
                .where(PromoRedemption.promo_code_id == promo.id)
            )
        ).scalar_one()
        if used >= promo.max_redemptions:
            raise ConflictError("promo code is fully redeemed", code="exhausted")

    user_wallet = await wallet_api.ensure_account(
        db, owner_type="user", owner_id=user_id, kind="user_wallet", currency=promo.currency
    )
    house = await wallet_api.ensure_account(
        db,
        owner_type="house",
        owner_id="house",
        kind="house_promo_expense",
        currency=promo.currency,
    )
    txn = await wallet_api.post(
        db,
        kind="promo.redeem",
        legs=[
            wallet_api.Leg(
                account_id=user_wallet.id,
                direction="D",
                amount=promo.amount,
                currency=promo.currency,
            ),
            wallet_api.Leg(
                account_id=house.id, direction="C", amount=promo.amount, currency=promo.currency
            ),
        ],
        # Natural key: one posting per (code, user), whatever the client sends.
        idempotency_key=f"promo:{promo.id}:{user_id}",
        reference=wallet_api.Reference(type="promo", id=promo.id),
        actor=f"user:{user_id}",
        metadata={"code": promo.code},
    )

    redemption = PromoRedemption(
        id=new_id(),
        promo_code_id=promo.id,
        user_id=user_id,
        transaction_id=txn.id,
        idempotency_key=idempotency_key,
    )
    try:
        # SAVEPOINT: a concurrent same-user race rolls back only this insert.
        async with db.begin_nested():
            db.add(redemption)
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError("promo code already redeemed", code="already_redeemed") from exc

    log.info("promo.redeemed", code=promo.code, amount=str(promo.amount))
    return promo, redemption


async def create_code(db: AsyncSession, *, body: PromoCreateIn, admin_id: str) -> PromoCode:
    code = _normalise(body.code) if body.code else f"YP-{secrets.token_hex(4).upper()}"
    promo = PromoCode(
        id=new_id(),
        code=code,
        amount=body.amount,
        currency=body.currency.upper(),
        max_redemptions=body.max_redemptions,
        expires_at=body.expires_at,
        created_by=admin_id,
    )
    try:
        async with db.begin_nested():
            db.add(promo)
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "a promo code with this value already exists", code="duplicate_code"
        ) from exc
    log.info("promo.created", code=promo.code, amount=str(promo.amount))
    return promo


async def list_codes(db: AsyncSession, *, limit: int = 100) -> list[tuple[PromoCode, int]]:
    """All codes, newest first, each with its redemption count."""
    redemption_count = (
        select(func.count())
        .select_from(PromoRedemption)
        .where(PromoRedemption.promo_code_id == PromoCode.id)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(PromoCode, redemption_count).order_by(PromoCode.created_at.desc()).limit(limit)
    )
    return [(promo, int(count)) for promo, count in rows.all()]


async def deactivate(db: AsyncSession, *, promo_id: str) -> PromoCode:
    promo = (
        await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("promo code not found")
    promo.active = False
    await db.flush()
    return promo


__all__ = ["create_code", "deactivate", "list_codes", "redeem"]
