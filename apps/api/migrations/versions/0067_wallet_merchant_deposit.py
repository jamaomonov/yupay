"""Ledger: the ``merchant_deposit`` kind and the ``merchant`` owner type.

The B2B program (spec ``docs/superpowers/specs/2026-09-06-merchant-b2b-design.md``
§7) prepays: a merchant wires USD, support credits it, orders draw it down in
M2. The deposit is a ledger balance, not a column — one debit-normal account
per merchant, owned by ``owner_type='merchant', owner_id=<merchant_id>,
currency='USD'``. A support credit posts ``D merchant_deposit /
C house_payments_received``; the full posting table lives in
``modules/merchants/README.md``.

No backfill: nothing has ever written this kind.

Three places have to agree on the set of kinds, and only one of them raises a
readable error. ``wallet.service.NORMAL_SIDE`` is checked in Python and says
"unknown account kind"; ``wallet.schemas.AccountKind`` is the published literal
type; this CHECK is the one that actually stops the INSERT, with a constraint
name and nothing else. Same for owner types (``wallet.schemas.OwnerType``).

Names below follow 0056, not 0066: these CHECKs live on ``core.db.metadata``
with the ``ck_%(table_name)s_%(constraint_name)s`` convention, so the bare
``ck_wallet_accounts_kind`` passed here ships (and drops) as the live
double-prefixed ``ck_wallet_accounts_ck_wallet_accounts_kind`` — passing a
``conv()``-wrapped literal would instead look for a single-prefixed name that
does not exist.

Revision ID: 0067_wallet_merchant_deposit
Revises: 0066_orders_merchant_actor
"""

from __future__ import annotations

from alembic import op

revision: str = "0067_wallet_merchant_deposit"
down_revision: str | None = "0066_orders_merchant_actor"
branch_labels: str | None = None
depends_on: str | None = None

_OLD_OWNER_TYPES = ("user", "house", "provider", "partner")
_NEW_OWNER_TYPES = (*_OLD_OWNER_TYPES, "merchant")

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
    "partner_pending",
    "partner_balance",
    "partner_payout_hold",
    "house_affiliate_expense",
    "house_affiliate_paid",
)
_NEW_KINDS = (*_OLD_KINDS, "merchant_deposit")


def _replace(constraint: str, column_check: str) -> None:
    op.drop_constraint(constraint, "wallet_accounts", type_="check")
    op.create_check_constraint(constraint, "wallet_accounts", column_check)


def upgrade() -> None:
    _replace("ck_wallet_accounts_owner_type", "owner_type IN " + repr(_NEW_OWNER_TYPES))
    _replace("ck_wallet_accounts_kind", "kind IN " + repr(_NEW_KINDS))


def downgrade() -> None:
    # Merchant deposit accounts must go before the CHECK can be narrowed
    # again. Whole transactions are removed, not just the merchant-side legs:
    # the counter-leg sits on ``house_payments_received`` (which survives), and
    # a one-legged transaction would break the SUM(D) == SUM(C) invariant every
    # report assumes. The merchant tables themselves survive (0065).
    op.execute(
        "DELETE FROM wallet_transactions WHERE id IN ("
        "  SELECT DISTINCT p.transaction_id"
        "    FROM wallet_postings p"
        "    JOIN wallet_accounts a ON a.id = p.account_id"
        "   WHERE a.owner_type = 'merchant'"
        ")"
    )
    op.execute("DELETE FROM wallet_accounts WHERE owner_type = 'merchant'")
    _replace("ck_wallet_accounts_kind", "kind IN " + repr(_OLD_KINDS))
    _replace("ck_wallet_accounts_owner_type", "owner_type IN " + repr(_OLD_OWNER_TYPES))
