"""Seed the ``uzqr`` payment provider as ``disabled`` (ADR-0106).

Revision ID: 0112_uzqr_provider
Revises: 0111_usdt_deposit
Create Date: 2026-11-23

A missing state row reads as ``active``, so without this seed the method would
reach checkout the moment ``UZQR_INN`` and ``UZQR_API_KEY`` are set — before
anyone has paid a test QR. The owner switches it on in the admin.
"""

from __future__ import annotations

from alembic import op

revision: str = "0112_uzqr_provider"
down_revision: str | None = "0111_usdt_deposit"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO payment_provider_states (provider, state, changed_by, changed_at) "
        "VALUES ('uzqr', 'disabled', NULL, CURRENT_TIMESTAMP) "
        "ON CONFLICT (provider) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM payment_provider_states WHERE provider = 'uzqr'")
