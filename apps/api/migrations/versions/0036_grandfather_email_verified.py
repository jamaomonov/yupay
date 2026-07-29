"""Grandfather existing users as email-verified.

``login_password`` now refuses to open a session for accounts whose
``email_verified_at`` is still ``NULL`` (see ``EmailUnverifiedError`` in
``yupay.core.errors``). Enforcement must be forward-only: every account
created before this rule shipped signed up under the old contract and never
saw a verification prompt, so retroactively blocking them would lock out the
entire existing user base. This one-time data backfill marks every live user
without a recorded verification as verified as of "now" so the new gate only
affects accounts registered from this point on.

Non-reversible: the exact verification timestamps this backfill invents are
not real events, so ``downgrade`` intentionally does not attempt to restore
``email_verified_at`` to ``NULL`` — undoing it would just re-lock out the
same grandfathered users for no benefit.

Revision ID: 0036_grandfather_email_verified
Revises: 0035_guest_reviews
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036_grandfather_email_verified"
down_revision: str | None = "0035_guest_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET email_verified_at = now() "
        "WHERE email_verified_at IS NULL AND deleted_at IS NULL"
    )


def downgrade() -> None:
    # Non-reversible data backfill; verification state is not restored on downgrade.
    pass
