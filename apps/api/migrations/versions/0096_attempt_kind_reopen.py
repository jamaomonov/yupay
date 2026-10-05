"""fulfillment_attempts.kind admits ``reopen`` — the audit line of «Переоткрыть».

Revision ID: 0096_attempt_kind_reopen
Revises: 0095_sku_cost_synced_at
Create Date: 2026-10-05

A cancelled task can now be reopened as ``failed`` (``service.reopen_task``),
and the attempt log says who did it. The kind check from ``0008`` listed the
three kinds that existed then; this widens it by one. Raw SQL on purpose:
``0008`` created the constraint through ``create_table`` under the metadata
naming convention, so its stored name is the doubled
``ck_fulfillment_attempts_ck_fulfillment_attempts_kind`` — ``DROP IF EXISTS``
on both spellings keeps this runnable whichever one a database carries.
"""

from __future__ import annotations

from alembic import op

revision: str = "0096_attempt_kind_reopen"
down_revision: str | None = "0095_sku_cost_synced_at"
branch_labels: str | None = None
depends_on: str | None = None

_NAME = "ck_fulfillment_attempts_ck_fulfillment_attempts_kind"
_OLD_NAME = "ck_fulfillment_attempts_kind"


def _swap(kinds: tuple[str, ...]) -> None:
    for name in (_NAME, _OLD_NAME):
        op.execute(f"ALTER TABLE fulfillment_attempts DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE fulfillment_attempts ADD CONSTRAINT {_NAME} CHECK (kind IN {kinds!r})")


def upgrade() -> None:
    _swap(("fulfill", "status_check", "cancel", "reopen"))


def downgrade() -> None:
    op.execute("DELETE FROM fulfillment_attempts WHERE kind = 'reopen'")
    _swap(("fulfill", "status_check", "cancel"))
