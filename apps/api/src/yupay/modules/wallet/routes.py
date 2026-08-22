"""HTTP routes for ``wallet``: customer views, top-up, admin adjustment."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import IDEMPOTENCY_HEADER, MIN_IDEMPOTENCY_KEY_LENGTH
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.deps import current_user
from yupay.modules.orders.service import normalise_source
from yupay.modules.payments.schemas import PaymentOut
from yupay.modules.users.models import User
from yupay.modules.wallet import service as svc
from yupay.modules.wallet.funding import create_topup
from yupay.modules.wallet.schemas import (
    USER_VISIBLE_KINDS,
    AdminAccountWithBalanceOut,
    AdminAdjustIn,
    AdminUserLedgerOut,
    BalanceOut,
    CustomerTransactionListOut,
    CustomerTransactionOut,
    TransactionListOut,
    TransactionOut,
    WalletOverviewOut,
    WalletTopUpIn,
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
    accounts = [a for a in await svc.user_accounts(db, user.id) if a.kind in USER_VISIBLE_KINDS]
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
    response_model=CustomerTransactionListOut,
    summary="My wallet — recent transactions",
)
async def my_transactions(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
    limit: int = 50,
) -> CustomerTransactionListOut:
    """The customer's own movements, without the operator's notes.

    ``CustomerTransactionOut`` rather than ``TransactionOut``: the latter
    carries ``actor`` and the whole of ``extra_metadata``, which is where a
    manual adjustment's reason lives — written on a form that calls it an
    audit entry, and read by the customer in their history.
    """
    capped = max(1, min(limit, 200))
    txns = await svc.transactions_for_user(db, user.id, limit=capped)
    return CustomerTransactionListOut(
        items=[CustomerTransactionOut.from_transaction(t) for t in txns]
    )


@router.post(
    "/topup",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Fund the wallet via an acquirer (idempotent)",
)
async def topup_wallet(
    body: WalletTopUpIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
    surface: Annotated[str | None, Header(alias="X-Yupay-Surface")] = None,
) -> PaymentOut:
    """Create a 1:1 deposit intent. Credit happens on acquirer settlement."""
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    payment = await create_topup(
        db,
        user_id=user.id,
        amount=body.amount,
        provider=body.provider,
        idempotency_key=idempotency_key,
        source=normalise_source(surface),
        return_url=body.return_url,
    )
    return PaymentOut.model_validate(payment)


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
