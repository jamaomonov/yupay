"""The nightly reconcile job rebuilds brand rating stats from published reviews."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.modules.reviews.models import BrandRatingStats
from yupay_scheduler.jobs import recompute_review_stats

from tests.integration.test_reviews_service import _make_published_review, _seed_brand

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """Point the job's own ``get_session_factory`` at the truncated test DB so its
    session and the test's ``db_session`` see the same database."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(recompute_review_stats, "get_session_factory", lambda: factory)


async def test_reconcile_job_fixes_drift(db_session: AsyncSession) -> None:
    brand, sku = await _seed_brand(db_session, "steam")
    brand_id = brand.id
    await _make_published_review(db_session, brand, sku)
    await db_session.execute(
        update(BrandRatingStats).where(BrandRatingStats.brand_id == brand_id).values(count=42)
    )
    await db_session.commit()

    await recompute_review_stats.run_recompute_review_stats()

    row = (
        await db_session.execute(
            select(BrandRatingStats.count.label("cnt"), BrandRatingStats.avg).where(
                BrandRatingStats.brand_id == brand_id
            )
        )
    ).one()
    assert row.cnt == 1
    assert row.avg == Decimal("5.00")
