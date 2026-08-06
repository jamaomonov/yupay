"""Allow ``settle`` as a payment-attempt kind.

Manual settlement (``POST /admin/payments/{id}/settle``) records an attempt row
so the money trail shows who declared a lost webhook received, and on what
evidence. Reusing ``webhook`` for it would tell a future investigator a provider
called us when none did, so the constraint gains its own value instead.

Revision ID: 0038_payment_attempt_settle_kind
Revises: 0037_payment_provider_states
"""

from __future__ import annotations

from alembic import op

revision: str = "0038_payment_attempt_settle_kind"
down_revision: str | None = "0037_payment_provider_states"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = "kind IN ('create_intent', 'webhook', 'refund', 'cancel', 'status_check')"
_NEW = "kind IN ('create_intent', 'webhook', 'refund', 'cancel', 'status_check', 'settle')"


def upgrade() -> None:
    op.drop_constraint("ck_payment_attempts_kind", "payment_attempts", type_="check")
    op.create_check_constraint("ck_payment_attempts_kind", "payment_attempts", _NEW)


def downgrade() -> None:
    # Rows written by the manual-settle path would violate the narrower rule;
    # drop them so the constraint can be re-applied.
    op.execute("DELETE FROM payment_attempts WHERE kind = 'settle'")
    op.drop_constraint("ck_payment_attempts_kind", "payment_attempts", type_="check")
    op.create_check_constraint("ck_payment_attempts_kind", "payment_attempts", _OLD)
