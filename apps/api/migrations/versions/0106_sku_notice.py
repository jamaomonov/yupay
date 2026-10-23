"""``skus.notice``: a short condition the buyer must see before paying for a pack.

Some packs do not deliver what their name suggests to everyone: MLBB's «First Top-Up»
250 + 25 adds its bonus once per account, a Free Fire Level Up Package only works below
its level, a Weekly Membership arrives over seven days. The notice is a tile label and
a line or two of text, both per locale::

    {
        "badge": {"ru": "1-я покупка", "en": "…", "uz": "…"},
        "text": {"ru": "Бонус дают только при первой покупке…", "en": "…", "uz": "…"},
    }

``badge`` may be absent. NULL means no notice. Filled by operators on the SKU form or by
``scripts/seed/2026-10-23_sku_notices.sql``.

Revision ID: 0106_sku_notice
Revises: 0105_push_notifications
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0106_sku_notice"
down_revision: str | None = "0105_push_notifications"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("notice", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("skus", "notice")
