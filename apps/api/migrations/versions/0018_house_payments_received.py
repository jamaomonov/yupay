"""Ledger: add ``house_payments_received`` as the proper counter-account
for wallet (and future direct-debit) payments.

The wallet gateway used to credit ``house_promo_expense`` as a
counterweight to the ``user_wallet`` debit — semantically wrong (that
account exists for promo spend, not customer payments). This migration
adds a dedicated kind and back-fills any rows we accidentally wrote to
the wrong place during the brief window the wallet gateway shipped
with the old wiring.

Backfill is targeted: only postings linked to ``wallet_transactions``
whose ``kind = 'wallet_payment'`` are moved. ``admin_adjust`` (which
also writes to ``house_promo_expense`` legitimately, for promo
balance grants) is left alone.

Revision ID: 0018_house_payments_received
Revises: 0017_supplier_price_history
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_house_payments_received"
down_revision: str | None = "0017_supplier_price_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
)
_NEW_KINDS = (*_OLD_KINDS, "house_payments_received")


def upgrade() -> None:
    # 1. Relax the CHECK so the new kind is accepted before any INSERT.
    op.drop_constraint("ck_wallet_accounts_kind", "wallet_accounts", type_="check")
    op.create_check_constraint(
        "ck_wallet_accounts_kind",
        "wallet_accounts",
        "kind IN " + repr(_NEW_KINDS),
    )

    # 2. Backfill — for every currency that has a wallet-payment posting
    # against ``house_promo_expense``, create the matching
    # ``house_payments_received`` account up-front. Then re-point the
    # postings at the new account.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO wallet_accounts (
                id, owner_type, owner_id, kind, currency, status,
                metadata, created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                'house',
                'house',
                'house_payments_received',
                a.currency,
                'active',
                '{}'::jsonb,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM wallet_accounts a
            WHERE a.owner_type = 'house'
              AND a.owner_id = 'house'
              AND a.kind = 'house_promo_expense'
              AND EXISTS (
                  SELECT 1 FROM wallet_postings p
                  JOIN wallet_transactions t ON t.id = p.transaction_id
                  WHERE p.account_id = a.id
                    AND t.kind = 'wallet_payment'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM wallet_accounts b
                  WHERE b.owner_type = 'house'
                    AND b.owner_id = 'house'
                    AND b.kind = 'house_payments_received'
                    AND b.currency = a.currency
              )
            """
        )
    )

    # Now re-point ALL postings whose parent ``wallet_transactions`` is
    # a wallet payment (regardless of currency) from the old account to
    # the new one of matching currency.
    bind.execute(
        sa.text(
            """
            UPDATE wallet_postings AS p
            SET account_id = new_acc.id
            FROM wallet_accounts AS old_acc,
                 wallet_accounts AS new_acc,
                 wallet_transactions AS t
            WHERE t.id = p.transaction_id
              AND t.kind = 'wallet_payment'
              AND p.account_id = old_acc.id
              AND old_acc.kind = 'house_promo_expense'
              AND new_acc.kind = 'house_payments_received'
              AND new_acc.owner_type = 'house'
              AND new_acc.owner_id = 'house'
              AND new_acc.currency = old_acc.currency
            """
        )
    )


def downgrade() -> None:
    # Reverse direction: move payments_received postings back to
    # promo_expense, then drop the new account rows + kind. This is
    # purely defensive — a real prod rollback would be a separate ops
    # decision because the names carry different semantics in
    # downstream reports.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE wallet_postings AS p
            SET account_id = old_acc.id
            FROM wallet_accounts AS new_acc,
                 wallet_accounts AS old_acc,
                 wallet_transactions AS t
            WHERE t.id = p.transaction_id
              AND t.kind = 'wallet_payment'
              AND p.account_id = new_acc.id
              AND new_acc.kind = 'house_payments_received'
              AND old_acc.kind = 'house_promo_expense'
              AND old_acc.owner_type = 'house'
              AND old_acc.owner_id = 'house'
              AND old_acc.currency = new_acc.currency
            """
        )
    )
    bind.execute(sa.text("DELETE FROM wallet_accounts WHERE kind = 'house_payments_received'"))
    op.drop_constraint("ck_wallet_accounts_kind", "wallet_accounts", type_="check")
    op.create_check_constraint(
        "ck_wallet_accounts_kind",
        "wallet_accounts",
        "kind IN " + repr(_OLD_KINDS),
    )
