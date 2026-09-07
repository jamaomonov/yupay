"""Outgoing merchant webhooks: the endpoint config and the delivery outbox.

Two new tables, no changes to existing ones (spec §10).

``merchant_webhooks`` is the one endpoint a merchant may register — unique on
``merchant_id``, because v1 is deliberately one hook per merchant and several
would be a different shape (per-endpoint secrets and per-endpoint failure
state), not a nullable column bolted on here. The signing secret is stored
**encrypted at rest** (``secret_enc``/``secret_nonce``, XSalsa20-Poly1305 via
``core.crypto`` under its own HKDF purpose label), the same decision migration
0070 made for ``merchant_api_keys`` and for the same structural reason: we
compute the HMAC on every delivery, and a one-way digest cannot key an HMAC.

``merchant_webhook_deliveries`` is the outbox in ADR-0064's shape — a
claimable ``status``, inserted in the transaction that causes it, drained by
``apps/worker`` with ``FOR UPDATE SKIP LOCKED``. It is also the cabinet's
delivery log from M4, so it keeps the response code, the first 2 KiB of the
merchant's response body and our own error text.

Two indices, each with a query behind it (AGENTS.md §10):

- ``ix_merchant_webhook_deliveries_pending`` — partial, the claim query
  ("pending rows whose backoff has elapsed, oldest first"). Partial so it
  stays the size of the backlog rather than of the log, which is the part
  that grows without bound.
- ``ix_merchant_webhook_deliveries_merchant_id`` — the child side of
  ``ON DELETE CASCADE`` (unindexed, deleting one merchant seq-scans the whole
  log) and M4's per-merchant list, newest first.

``response_body`` is bounded in the **column** at 2048 characters rather than
only by whatever writes it. It is text a third-party server chose, rendered
later in our own cabinet, and "the writer truncates" is a promise a future
writer can forget.

The downgrade is an ordinary pair of drops and needs no guard of the kind
0070's carries: nothing here is unreconstructible — deliveries are a log and
a webhook is re-registered by setting the URL again — and the merchant simply
goes back to polling, which is what M2 shipped.

Revision ID: 0071_merchant_webhooks
Revises: 0070_merchant_key_secret_enc
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0071_merchant_webhooks"
down_revision: str | None = "0070_merchant_key_secret_enc"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")

#: Mirrors ``merchants.models.WEBHOOK_URL_MAX`` / ``WEBHOOK_RESPONSE_BODY_MAX``.
#: Spelled out here rather than imported: a migration is a historical record
#: and must keep describing the schema it created even after the model moves.
_URL_MAX = 512
_RESPONSE_BODY_MAX = 2048


def upgrade() -> None:
    op.create_table(
        "merchant_webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=_URL_MAX), nullable=False),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("secret_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("disabled_at", _TS, nullable=True),
        sa.Column("failure_streak", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_success_at", _TS, nullable=True),
        sa.Column("last_failure_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("merchant_id", name="uq_merchant_webhooks_merchant"),
        # Bare suffix, not the full name: the metadata's naming convention
        # prepends ``ck_merchant_webhooks_`` itself, and CheckConstraint is
        # the one constraint type where that fires even when a name is given
        # — the full name here would land doubled (see 0065's note).
        sa.CheckConstraint("failure_streak >= 0", name="streak_nonneg"),
    )

    op.create_table(
        "merchant_webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", _TS, nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.String(length=_RESPONSE_BODY_MAX), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "status IN ('pending','in_progress','delivered','failed')", name="status"
        ),
        sa.CheckConstraint("attempts_count >= 0", name="attempts_nonneg"),
    )
    # ``if_not_exists`` for the reason 0062 gives: a migration interrupted
    # partway must be re-runnable rather than wedge the upgrade chain.
    op.create_index(
        "ix_merchant_webhook_deliveries_pending",
        "merchant_webhook_deliveries",
        ["next_attempt_at", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_merchant_webhook_deliveries_merchant_id",
        "merchant_webhook_deliveries",
        ["merchant_id", sa.text("created_at DESC")],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_merchant_webhook_deliveries_merchant_id",
        "merchant_webhook_deliveries",
        if_exists=True,
    )
    op.drop_index(
        "ix_merchant_webhook_deliveries_pending", "merchant_webhook_deliveries", if_exists=True
    )
    op.drop_table("merchant_webhook_deliveries")
    op.drop_table("merchant_webhooks")
