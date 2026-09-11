"""Read-side aggregations over ``user_wallet`` accounts.

The write path stays in :mod:`yupay.modules.wallet.service`. These helpers exist
so the admin user directory can show liability totals and sort by balance
without N+1 calls to :func:`yupay.modules.wallet.service.balance`.

Imported from here rather than ``wallet.api``: that facade pulls in
``wallet.routes`` → ``api.v1`` → ``admin``, and a cycle through the route stack
is how those imports fail in unit tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from yupay.modules.fx.models import FxRate
from yupay.modules.wallet.models import WalletAccount, WalletPosting

USER_WALLET_KIND = "user_wallet"
USER_OWNER = "user"


def _signed_amount() -> ColumnElement[Decimal]:
    """``user_wallet`` is debit-normal: D minus C is the spendable balance."""
    return case(
        (WalletPosting.direction == "D", WalletPosting.amount),
        else_=-WalletPosting.amount,
    )


def user_wallet_usd_sort_subquery() -> Subquery:
    """One row per user: USD-equivalent of their ``user_wallet`` balances.

    USD and USDT count 1:1. Other currencies convert via the latest ``USD→quote``
    row in ``fx_rates`` (``amount / rate``). A missing rate contributes 0 so a
    UZS-only wallet without FX data does not leapfrog USD wallets; the cell
    still shows the native balance.
    """
    latest_fx = (
        select(FxRate.quote.label("quote"), FxRate.rate.label("rate"))
        .distinct(FxRate.quote)
        .where(FxRate.base == "USD")
        .order_by(FxRate.quote, FxRate.fetched_at.desc())
        .subquery("latest_fx")
    )
    signed = _signed_amount()
    usd_eq = case(
        (WalletAccount.currency.in_(("USD", "USDT")), signed),
        else_=signed / func.nullif(latest_fx.c.rate, 0),
    )
    return (
        select(
            WalletAccount.owner_id.label("owner_id"),
            func.coalesce(func.sum(usd_eq), Decimal("0")).label("usd_eq"),
        )
        .select_from(WalletAccount)
        .outerjoin(WalletPosting, WalletPosting.account_id == WalletAccount.id)
        .outerjoin(latest_fx, latest_fx.c.quote == WalletAccount.currency)
        .where(
            WalletAccount.kind == USER_WALLET_KIND,
            WalletAccount.owner_type == USER_OWNER,
        )
        .group_by(WalletAccount.owner_id)
        .subquery("user_wallet_usd")
    )


async def balances_for_users(
    db: AsyncSession, user_ids: Sequence[str]
) -> dict[str, list[tuple[str, Decimal]]]:
    """``user_wallet`` balances keyed by user id, one query for the whole page.

    Zero balances are omitted so a clawed-back account does not occupy the
    cell. Users with no account are present as an empty list.
    """
    empty: dict[str, list[tuple[str, Decimal]]] = {uid: [] for uid in user_ids}
    if not user_ids:
        return empty
    signed = _signed_amount()
    stmt = (
        select(
            WalletAccount.owner_id,
            WalletAccount.currency,
            func.coalesce(func.sum(signed), Decimal("0")).label("balance"),
        )
        .select_from(WalletAccount)
        .outerjoin(WalletPosting, WalletPosting.account_id == WalletAccount.id)
        .where(
            WalletAccount.kind == USER_WALLET_KIND,
            WalletAccount.owner_type == USER_OWNER,
            WalletAccount.owner_id.in_(list(user_ids)),
        )
        .group_by(WalletAccount.owner_id, WalletAccount.currency)
        .order_by(WalletAccount.owner_id, WalletAccount.currency)
    )
    for owner_id, currency, balance in (await db.execute(stmt)).all():
        amount = Decimal(balance or 0)
        if amount == 0:
            continue
        empty[str(owner_id)].append((str(currency), amount))
    return empty


async def user_wallet_totals(db: AsyncSession) -> list[tuple[str, Decimal]]:
    """Global ``user_wallet`` liability, one bucket per currency.

    This is "how much customer money we hold", not a filtered view of the
    current search. Zero buckets are omitted.
    """
    signed = _signed_amount()
    stmt = (
        select(
            WalletAccount.currency,
            func.coalesce(func.sum(signed), Decimal("0")).label("balance"),
        )
        .select_from(WalletAccount)
        .outerjoin(WalletPosting, WalletPosting.account_id == WalletAccount.id)
        .where(
            WalletAccount.kind == USER_WALLET_KIND,
            WalletAccount.owner_type == USER_OWNER,
        )
        .group_by(WalletAccount.currency)
        .order_by(WalletAccount.currency)
    )
    out: list[tuple[str, Decimal]] = []
    for currency, balance in (await db.execute(stmt)).all():
        amount = Decimal(balance or 0)
        if amount == 0:
            continue
        out.append((str(currency), amount))
    return out


__all__ = [
    "balances_for_users",
    "user_wallet_totals",
    "user_wallet_usd_sort_subquery",
]
