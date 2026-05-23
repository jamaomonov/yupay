"""HTTP routes for ``wallet``: customer read-only views + admin adjustment."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.users.models import User
from yupay.modules.wallet import service as svc
from yupay.modules.wallet.schemas import (
    USER_VISIBLE_KINDS,
    AdminAccountWithBalanceOut,
    AdminAdjustIn,
    AdminUserLedgerOut,
    BalanceOut,
    TransactionListOut,
    TransactionOut,
    WalletOverviewOut,
)

router = APIRouter(prefix="/wallet", tags=["wallet"])
admin_router = APIRouter(
    prefix="/admin/wallet",
    tags=["admin:wallet"],
    dependencies=[Depends(require_admin)],
)


# ---------- customer ----------


@router.get("", response_model=WalletOverviewOut, summary="My wallet — balances")
async def my_wallet(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> WalletOverviewOut:
    accounts = [
        a for a in await svc.user_accounts(db, user.id) if a.kind in USER_VISIBLE_KINDS
    ]
    balances = [
        BalanceOut(
            account_id=a.id,
            kind=a.kind,  # type: ignore[arg-type]
            currency=a.currency,
            balance=await svc.balance(db, a.id),
        )
        for a in accounts
    ]
    return WalletOverviewOut(balances=balances)


@router.get(
    "/transactions",
    response_model=TransactionListOut,
    summary="My wallet — recent transactions",
)
async def my_transactions(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
    limit: int = 50,
) -> TransactionListOut:
    capped = max(1, min(limit, 200))
    txns = await svc.transactions_for_user(db, user.id, limit=capped)
    return TransactionListOut(items=[TransactionOut.model_validate(t) for t in txns])


# ---------- admin ----------


@admin_router.post(
    "/adjust",
    response_model=TransactionOut,
    summary="Manual ledger adjustment (idempotent via key)",
)
async def admin_adjust(
    body: AdminAdjustIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> TransactionOut:
    txn = await svc.admin_adjust(
        db,
        user_id=body.user_id,
        kind=body.kind,
        currency=body.currency.upper(),
        amount=body.amount,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        admin_id=admin.id,
    )
    return TransactionOut.model_validate(txn)


@admin_router.get(
    "/adjustments",
    response_model=TransactionListOut,
    summary="Recent admin ledger adjustments (mine / everyone)",
)
async def admin_recent_adjustments(
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    actor: str = "me",
    limit: int = 50,
) -> TransactionListOut:
    capped = max(1, min(limit, 200))
    admin_filter: str | None
    if actor == "me":
        admin_filter = admin.id
    elif actor == "all":
        admin_filter = None
    else:
        raise HTTPException(
            status_code=400,
            detail="actor must be 'me' or 'all'",
        )
    txns = await svc.list_admin_adjustments(db, admin_id=admin_filter, limit=capped)
    return TransactionListOut(items=[TransactionOut.model_validate(t) for t in txns])


@admin_router.get(
    "/{user_id}",
    response_model=AdminUserLedgerOut,
    summary="A user's full ledger (admin)",
)
async def admin_user_ledger(
    user_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    limit: int = 50,
) -> AdminUserLedgerOut:
    capped = max(1, min(limit, 200))
    accounts = await svc.user_accounts(db, user_id)
    if not accounts:
        # We could 404 here, but admins benefit from a stable shape.
        return AdminUserLedgerOut(user_id=user_id, accounts=[], recent_transactions=[])
    out_accounts = []
    for a in accounts:
        out_accounts.append(
            AdminAccountWithBalanceOut(
                id=a.id,
                owner_type=a.owner_type,  # type: ignore[arg-type]
                owner_id=a.owner_id,
                kind=a.kind,  # type: ignore[arg-type]
                currency=a.currency,
                status=a.status,  # type: ignore[arg-type]
                balance=await svc.balance(db, a.id),
            )
        )
    txns = await svc.transactions_for_user(db, user_id, limit=capped)
    return AdminUserLedgerOut(
        user_id=user_id,
        accounts=out_accounts,
        recent_transactions=[TransactionOut.model_validate(t) for t in txns],
    )


_ = HTTPException  # imported for future error handling; silence unused warnings
