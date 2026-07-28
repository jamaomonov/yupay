"""Guest reviews: nullable user_id, guest_email, one-review-per-(order,brand).

See docs/decisions/0039-reviews-and-ratings.md (guest-reviews amendment).

Note: downgrade() re-adds NOT NULL on user_id, so it will fail if any guest
reviews exist (rows with user_id IS NULL) — those rows must be deleted or
backfilled with a user_id first.

Revision ID: 0035_guest_reviews
Revises: 0034_reviews
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT, UUID

revision: str = "0035_guest_reviews"
down_revision: str | None = "0034_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("reviews", "user_id", existing_type=UUID(), nullable=True)
    op.add_column("reviews", sa.Column("guest_email", CITEXT(), nullable=True))
    op.create_check_constraint(
        "ck_reviews_user_xor_guest", "reviews", "(user_id IS NULL) <> (guest_email IS NULL)"
    )
    op.drop_constraint("uq_reviews_user_order_brand", "reviews", type_="unique")
    op.create_unique_constraint("uq_reviews_order_brand", "reviews", ["order_id", "brand_id"])


def downgrade() -> None:
    op.drop_constraint("uq_reviews_order_brand", "reviews", type_="unique")
    op.create_unique_constraint(
        "uq_reviews_user_order_brand", "reviews", ["user_id", "order_id", "brand_id"]
    )
    op.drop_constraint("ck_reviews_user_xor_guest", "reviews", type_="check")
    op.drop_column("reviews", "guest_email")
    op.alter_column("reviews", "user_id", existing_type=UUID(), nullable=False)
