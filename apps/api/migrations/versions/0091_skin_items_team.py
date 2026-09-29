"""skin_items.team: an agent's side, for the catalogue's Team filter.

``ct`` or ``t`` from ByMykel's ``team.id``; ``NULL`` for everything that is not an agent.
Filled by the next catalogue import. No index: 63 agents, always read inside the category.

Revision ID: 0091_skin_items_team
Revises: 0090_skin_trades_created_idx
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0091_skin_items_team"
down_revision: str | None = "0090_skin_trades_created_idx"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skin_items", sa.Column("team", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("skin_items", "team")
