"""Generic idempotency-replay store for admin write endpoints.

Payments / orders / wallet / promo already persist ``Idempotency-Key`` on their own
domain row. Admin write endpoints that mutate an existing row instead of creating one
(retry/cancel/complete a fulfillment task, upsert/delete a sourcing rule or supplier
mapping, bulk-upload inventory codes, ...) have no such column, so they share this
generic ``(scope, idempotency_key)`` -> response-snapshot table instead. See
``yupay.core.idempotency``.

Revision ID: 0033_idempotent_responses
Revises: 0032_brand_highlights
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_idempotent_responses"
down_revision: str | None = "0032_brand_highlights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotent_responses",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("scope", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("response_body", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotent_responses_scope_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotent_responses")
