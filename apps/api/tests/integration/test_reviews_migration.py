"""Migration 0034 creates the reviews module's three tables + key constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_reviews_tables_exist(db_session: AsyncSession) -> None:
    for table in ("reviews", "review_reports", "brand_rating_stats"):
        r = await db_session.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"})
        assert r.scalar() is not None, f"{table} missing"


async def test_reviews_unique_constraint_present(db_session: AsyncSession) -> None:
    r = await db_session.execute(
        text(
            "SELECT 1 FROM pg_constraint WHERE conname = 'uq_reviews_user_order_brand'"
        )
    )
    assert r.scalar() == 1


async def test_reviews_rating_check_present(db_session: AsyncSession) -> None:
    # Verify the CHECK constraint by its definition (not a brittle name string):
    # some check on ``reviews`` must constrain ``rating``.
    r = await db_session.execute(
        text(
            "SELECT pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid "
            "WHERE rel.relname = 'reviews' AND con.contype = 'c'"
        )
    )
    defs = [row[0] for row in r.all()]
    assert any("rating" in d for d in defs), f"no rating CHECK on reviews: {defs}"
