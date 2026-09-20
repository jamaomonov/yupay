"""A brandless post may be archived, not only left as a draft.

``ck_blog_posts_brand_unless_draft`` was written as::

    primary_brand_id IS NOT NULL OR status = 'draft'

but the invariant both its migration (0079) and the ORM say it enforces is
narrower than that: "A draft may have no brand yet — an imported article
arrives before anyone has decided what it sells. **Everything a reader can
reach must have one**: every public query inner-joins ``brands`` through this
column, and they all filter to ``published``."

``archived`` is not something a reader can reach — ``blog.service``'s three
public queries filter ``status == 'published'`` and nothing else. So the
constraint was stopping a transition it had no reason to care about, and the
symptom was a **500 on the way to the one state that hides a post**: an
imported brandless draft could be published (refused cleanly, with a brand
required) or left in the drafts list forever, but never archived. The
operator's only ways out were deleting the post or inventing a brand for it.

Sentry, 2026-09-19 14:34 UTC: ``POST /admin/blog/posts/{id}/archive`` → 500,
``CheckViolationError``, on a ``guide`` imported that morning.

Widening to ``('draft', 'archived')`` keeps the whole safety property. The two
states a reader can reach are still covered — and they are covered twice over,
because ``admin_service.publish_post`` and ``schedule_post`` each refuse a
brandless post with a ``ValidationError`` before the constraint is ever
consulted. Only ``archive_post`` had no such guard, and now it needs none.

``ALTER TABLE ... DROP CONSTRAINT`` + ``ADD CONSTRAINT`` takes ACCESS
EXCLUSIVE on ``blog_posts`` and the ADD scans the table to validate. This is a
small, low-traffic table read only by the storefront's blog, so the scan is
milliseconds; ``lock_timeout`` is set for the same reason 0069, 0072, 0073 and
0083 set it — a contended run should fail and be retried, not queue behind one
slow transaction and hold every later reader behind it.

Revision ID: 0085_archive_a_brandless_post
Revises: 0084_catalog_cache_key_per_game
"""

from __future__ import annotations

from alembic import op

revision: str = "0085_archive_a_brandless_post"
down_revision: str | None = "0084_catalog_cache_key_per_game"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "blog_posts"
#: The BARE suffix, and it must be — on ``drop_constraint`` as much as on
#: ``create_check_constraint``.
#:
#: ``core/db.py``'s naming convention is ``ck_%(table_name)s_%(constraint_name)s``
#: and, because it contains ``%(constraint_name)s``, SQLAlchemy re-templates it
#: even for a constraint that already carries an explicit name. Alembic builds
#: one internally for the drop, so passing the qualified
#: ``ck_blog_posts_brand_unless_draft`` here asks Postgres for
#: ``ck_blog_posts_ck_blog_posts_brand_unless_draft`` — which is exactly how CI
#: failed this migration's first run.
#:
#: **Neighbouring migrations pass the FULL name to ``drop_constraint`` and are
#: not wrong**, which is the part worth knowing before "fixing" one of them:
#: their constraints were themselves created double-prefixed, so the qualified
#: string re-templates into the name that is really in the database.
#: ``core/db.py`` says the same ("``ck_orders_ck_orders_actor_exclusive`` is
#: live in production"). What decides it is the name Postgres actually holds,
#: not a convention — verified here against production, where 0079's bare-suffix
#: create left ``ck_blog_posts_brand_unless_draft``.
_NAME = "brand_unless_draft"

_OLD = "primary_brand_id IS NOT NULL OR status = 'draft'"
_NEW = "primary_brand_id IS NOT NULL OR status IN ('draft', 'archived')"


def upgrade() -> None:
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)
    # Scoped: a plain SET lives for the rest of the session, so without this
    # every later revision in the same `upgrade head` inherits a patience it
    # never asked for.
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    # This direction can fail on real data, and that is correct rather than a
    # bug in the downgrade: any post archived while brandless — the exact rows
    # this migration exists to allow — violates the narrower constraint. An
    # operator reverting this must first give those posts a brand or delete
    # them. Failing loudly beats silently dropping the constraint.
    op.execute("SET lock_timeout = '3s'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
    op.execute("RESET lock_timeout")
