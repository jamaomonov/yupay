"""``GET /reviews/featured``: the home page's review wall (owner, 2026-09-29)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.reviews.models import Review
from yupay.modules.reviews.service import recompute_all_stats

from tests.integration.test_reviews_service import _make_order, _make_user, _seed_brand

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:
    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        holder["n"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _before)


async def _review(
    db: AsyncSession,
    *,
    slug: str,
    rating: int = 5,
    body: str | None = "Быстро пришло",
    status: str = "published",
    name: str | None = "Aziz",
    age_min: int = 0,
) -> Review:
    user = await _make_user(db, display_name=name)
    brand, sku = await _seed_brand(db, f"{slug}-{new_id()[-8:]}")
    brand.logo_url = f"https://cdn.yupay.uz/{slug}.webp"
    order = await _make_order(db, user_id=user.id, sku_id=sku.id)
    review = Review(
        id=new_id(),
        brand_id=brand.id,
        user_id=user.id,
        order_id=order.id,
        rating=rating,
        body=body,
        status=status,
        locale="ru",
        created_at=now() - timedelta(minutes=age_min),
    )
    db.add(review)
    await db.flush()
    return review


async def test_newest_written_reviews_with_their_brand_and_overall_stats(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _review(db_session, slug="steam", body="Old one", age_min=10)
    await _review(db_session, slug="mlbb", body="Newest", name="<b>Kamila</b>")
    await _review(db_session, slug="ff", body=None, rating=4)  # stars only: not on the wall
    await _review(db_session, slug="ff", body="   ", rating=4)  # blank: not on the wall
    await _review(db_session, slug="pubg", body="Hidden", status="hidden")
    await recompute_all_stats(db_session)
    await db_session.commit()

    r = await integration_client.get("/api/v1/reviews/featured")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["body"] for i in body["items"]] == ["Newest", "Old one"]
    first = body["items"][0]
    assert first["author_name"] == "Kamila"  # markup stripped on the way out
    assert first["brand_slug"].startswith("mlbb-")
    assert first["brand_name"].startswith("Mlbb-")
    assert first["brand_logo_url"] == "https://cdn.yupay.uz/mlbb.webp"
    # Stats count every published review, star-only ones included.
    assert body["stats"]["count"] == 4
    assert body["stats"]["avg"] == pytest.approx(4.5)


async def test_the_limit_is_bounded(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/reviews/featured?limit=500")
    assert r.status_code == 422


async def test_query_count_does_not_grow_with_rows(
    integration_client: AsyncClient, db_session: AsyncSession, sql_counter: dict[str, int]
) -> None:
    await _review(db_session, slug="a")
    await db_session.commit()
    await integration_client.get("/api/v1/reviews/featured")  # warm-up
    sql_counter["n"] = 0
    assert (await integration_client.get("/api/v1/reviews/featured")).status_code == 200
    one = sql_counter["n"]
    assert one > 0

    for i in range(4):
        await _review(db_session, slug=f"b{i}")
    await db_session.commit()
    sql_counter["n"] = 0
    assert (await integration_client.get("/api/v1/reviews/featured")).status_code == 200
    assert sql_counter["n"] == one
