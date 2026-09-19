"""Avatar URL columns: varchar(1024) -> text.

A URL has no natural length bound; 1024 was a guess reality exceeded. Sentry,
2026-09-18: ``POST /api/v1/auth/google`` 500'd with
``asyncpg.exceptions.StringDataRightTruncationError`` on ``INSERT INTO
users`` — a real Google avatar URL (``https://lh3.googleusercontent.com/a-/
ALV-...``) ran past 1024 characters. Production data: 893 users have a
``photo_url``, longest on record is 100 characters — this is a rare shape,
not the common one, but it failed closed at the worst possible moment, a
first registration.

``varchar(n) -> text`` (or widening ``n``) is a metadata-only ``ALTER
COLUMN ... TYPE`` in Postgres: both types share the same on-disk
representation, so relaxing/removing the length constraint requires no table
rewrite and no revalidation of existing rows (every existing value already
satisfies a looser or absent bound). Verified empirically against this
repo's Postgres 16 image before writing this migration: a scratch table's
``pg_class.relfilenode`` and ``pg_relation_size`` were byte-identical before
and after the same ``ALTER COLUMN ... TYPE text`` run here. This is safe to
run against the production ``users`` table without a maintenance window.

``steam_links.avatar_url`` is widened in the same breath, and not for
symmetry: ``upsert_user_by_steam`` writes the *same* value into both columns
in the *same* flush, so leaving one at 1024 would keep the identical 500
reachable through the sibling column. The guard's ceiling (2048) is wider
than that column was, so the gap was real rather than theoretical — a Steam
avatar between 1025 and 2048 characters would have passed the guard and then
failed the insert. Steam's URLs are short fixed-format CDN links today, which
is exactly what was true of Google's until it wasn't.

An application-level guard (``yupay.modules.users.identity_guard``) still
refuses an absurd value before it ever reaches these columns — this migration
removes the *arbitrary* 1024 cap, not the idea of a cap at all.

Revision ID: 0083_widen_photo_url
Revises: 0082_catalog_cache_denoms
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0083_widen_photo_url"
down_revision: str | None = "0082_catalog_cache_denoms"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table, column in (("users", "photo_url"), ("steam_links", "avatar_url")):
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=1024),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Values written while this column was `text` may exceed 1024 chars —
    # the guard in `identity_guard.MAX_AVATAR_URL_LENGTH` (2048) is wider
    # than the old column, so a downgrade after this ships can fail on real
    # data. That's the expected cost of reverting a deliberate widening, not
    # a bug in the downgrade.
    for table, column in (("users", "photo_url"), ("steam_links", "avatar_url")):
        op.alter_column(
            table,
            column,
            existing_type=sa.Text(),
            type_=sa.String(length=1024),
            existing_nullable=True,
        )
