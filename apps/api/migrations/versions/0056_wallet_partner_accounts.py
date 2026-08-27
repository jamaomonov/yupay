"""Ledger: partner account kinds and the ``partner`` owner type.

The affiliate program needs somewhere to put a partner's money. Three accounts
per partner rather than one, so that "available to withdraw" is a ledger
balance instead of a sum computed over the commissions table:

``partner_pending``      commission accrued, still inside the hold period
``partner_balance``      matured, withdrawable
``partner_payout_hold``  reserved by an open payout request

That split is what makes a payout request safe to race: it reserves its money
by moving it, so two concurrent requests cannot both pass a balance check.

The house side mirrors the existing promo pair — ``house_affiliate_expense`` is
credited when commission is earned, ``house_affiliate_paid`` is debited when it
actually leaves for a partner's card. Two accounts because "what we owe
partners" and "what we have paid partners" answer different questions and are
read by different reports.

No backfill: nothing has ever written these kinds. Contrast 0018, which added
``house_payments_received`` to a schema that already held misfiled postings.

Three places have to agree on the set of kinds, and only one of them raises a
readable error. ``wallet.service.NORMAL_SIDE`` is checked in Python and says
"unknown account kind"; ``wallet.schemas.AccountKind`` is the published literal
type; this CHECK is the one that actually stops the INSERT, with a constraint
name and nothing else. Adding a kind means editing all three.

Revision ID: 0056_wallet_partner_accounts
Revises: 0055_admin_list_sort_indexes
"""

from __future__ import annotations

from alembic import op

revision: str = "0056_wallet_partner_accounts"
down_revision: str | None = "0055_admin_list_sort_indexes"
branch_labels: str | None = None
depends_on: str | None = None

_OLD_OWNER_TYPES = ("user", "house", "provider")
_NEW_OWNER_TYPES = (*_OLD_OWNER_TYPES, "partner")

_OLD_KINDS = (
    "user_wallet",
    "user_cashback",
    "user_promo_credit",
    "house_revenue",
    "house_cogs",
    "house_promo_expense",
    "house_refunds",
    "house_fx_pnl",
    "provider_clearing",
    "house_payments_received",
)
_NEW_KINDS = (
    *_OLD_KINDS,
    "partner_pending",
    "partner_balance",
    "partner_payout_hold",
    "house_affiliate_expense",
    "house_affiliate_paid",
)


def _replace(constraint: str, column_check: str) -> None:
    op.drop_constraint(constraint, "wallet_accounts", type_="check")
    op.create_check_constraint(constraint, "wallet_accounts", column_check)


def upgrade() -> None:
    _replace("ck_wallet_accounts_owner_type", "owner_type IN " + repr(_NEW_OWNER_TYPES))
    _replace("ck_wallet_accounts_kind", "kind IN " + repr(_NEW_KINDS))


def downgrade() -> None:
    # Partner accounts must go before the CHECK can be narrowed again. They are
    # deleted rather than preserved because the affiliate tables are dropped by
    # the migration above this one anyway, so there would be nothing left to
    # explain what the balances meant.
    op.execute(
        "DELETE FROM wallet_postings WHERE account_id IN ("
        "  SELECT id FROM wallet_accounts WHERE owner_type = 'partner'"
        "     OR kind IN ('house_affiliate_expense', 'house_affiliate_paid')"
        ")"
    )
    op.execute(
        "DELETE FROM wallet_accounts WHERE owner_type = 'partner'"
        "   OR kind IN ('house_affiliate_expense', 'house_affiliate_paid')"
    )
    _replace("ck_wallet_accounts_kind", "kind IN " + repr(_OLD_KINDS))
    _replace("ck_wallet_accounts_owner_type", "owner_type IN " + repr(_OLD_OWNER_TYPES))
