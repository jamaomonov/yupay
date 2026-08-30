"""Cloudflare country on order evidence — the raw signal for the geo veto.

``ip_country`` is Cloudflare's edge-resolved two-letter code for the request
(``evidence.service.ip_country_from`` normalises the ``cf-ipcountry`` header
into it: stripped, upper-cased, and shaped like ``[A-Z0-9]{2}`` — real ISO
3166-1 alpha-2 codes and Cloudflare's own sentinels, ``T1`` for Tor exit
traffic and ``XX`` when it cannot resolve one, are the same shape and both are
kept as signal). A later task reads this column to refuse a foreign guest's
charge before it happens.

Additive only, no backfill: the ``cf-ipcountry`` header did not exist on
requests captured before this migration, so there is nothing to compute for
those rows — they stay ``NULL``, meaning "unknown", not "domestic" or
"foreign". That distinction matters for whoever writes the veto: ``NULL`` must
never satisfy an allow-rule or fire a block-rule on its own, or a gap in this
column would silently start deciding orders it has no evidence for.

Revision ID: 0060_evidence_ip_country
Revises: 0059_evidence_device_hash
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0060_evidence_ip_country"
down_revision: str | None = "0059_evidence_device_hash"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("order_evidence", sa.Column("ip_country", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("order_evidence", "ip_country")
