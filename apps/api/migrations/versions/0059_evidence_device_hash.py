"""Device fingerprint on order evidence, plus the indexes antifraud queries need.

``device_hash`` is ``sha256(user_agent | timezone | locale | screen)`` — a
pseudonym for the requesting device, not an identity. It lets the risk gate's
shared-identity rule ask "how many other orders came from this same device"
without ever storing anything that identifies a person on its own. Nullable,
because a device with no UA and no hints must not collapse into one shared
"empty" fingerprint that links every unknown device together.

The backfill below computes the hash for every pre-existing row so the column
is usable immediately rather than only for orders placed after this migration.
It must produce byte-identical hashes to ``evidence.service.device_hash`` — a
mismatch would silently split one real device into two different
fingerprints depending on when its order was placed. ``pgcrypto`` ships in
``infra/postgres/init``, but the ``CREATE EXTENSION IF NOT EXISTS`` guard
keeps this migration self-sufficient against a fresh test database that
doesn't run that init script.

``ix_order_evidence_ip`` and ``ix_order_evidence_device_hash`` back the
velocity queries that will group recent orders by address and by device.
``ix_orders_paid_at`` backs the window those queries scope to ("orders paid in
the last N minutes") — added ``if_not_exists`` because a later antifraud
migration on a different branch may have already created it.

Revision ID: 0059_evidence_device_hash
Revises: 0058_order_affiliate_discount
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0059_evidence_device_hash"
down_revision: str | None = "0058_order_affiliate_discount"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("order_evidence", sa.Column("device_hash", sa.String(64), nullable=True))
    # Backfill must produce byte-identical hashes to the Python helper:
    # sha256 over "ua|tz|locale|screen". pgcrypto ships in infra/postgres/init
    # but the guard keeps the migration self-sufficient on fresh test DBs.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        UPDATE order_evidence SET device_hash = encode(digest(
            coalesce(user_agent, '') || '|' ||
            coalesce(client_hints->>'timezone', '') || '|' ||
            coalesce(client_hints->>'locale', '') || '|' ||
            coalesce(client_hints->>'screen', ''), 'sha256'), 'hex')
        WHERE coalesce(user_agent, '') || coalesce(client_hints->>'timezone', '')
              || coalesce(client_hints->>'locale', '') || coalesce(client_hints->>'screen', '') <> ''
        """
    )
    op.create_index("ix_order_evidence_ip", "order_evidence", ["ip"])
    op.create_index("ix_order_evidence_device_hash", "order_evidence", ["device_hash"])
    op.create_index("ix_orders_paid_at", "orders", ["paid_at"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_orders_paid_at", "orders", if_exists=True)
    op.drop_index("ix_order_evidence_device_hash", "order_evidence")
    op.drop_index("ix_order_evidence_ip", "order_evidence")
    op.drop_column("order_evidence", "device_hash")
