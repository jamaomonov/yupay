"""Visits to partner links are counted: one row per visitor per link per day."""

from __future__ import annotations

import secrets
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.affiliate.clicks import clean_path, record_click, visitor_hash
from yupay.modules.affiliate.models import AffiliateClick, AffiliateCode, AffiliatePartner
from yupay.modules.affiliate.panel import stats

pytestmark = pytest.mark.asyncio

VISITOR = "3f6c2a1e-9b8d-4c7a-a1b2-0c9d8e7f6a5b"


async def _code(
    db: AsyncSession, *, status: str = "active", active: bool = True
) -> tuple[str, str]:
    """``(partner_id, code)`` for a fresh partner with one code."""
    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status=status)
    db.add(partner)
    await db.flush()
    code = f"C{secrets.token_hex(4).upper()}"
    db.add(
        AffiliateCode(
            id=new_id(),
            partner_id=partner.id,
            code=code,
            discount_percent=Decimal("5"),
            commission_percent=Decimal("2"),
            active=active,
        )
    )
    await db.commit()
    return partner.id, code


async def _clicks(db: AsyncSession, partner_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count(AffiliateClick.id)).where(AffiliateClick.partner_id == partner_id)
        )
        or 0
    )


async def test_a_visit_is_counted_once_a_day_per_visitor(db_session: AsyncSession) -> None:
    partner_id, code = await _code(db_session)
    assert await record_click(db_session, code=code.lower(), visitor_id=VISITOR, path="/?ref=x")
    assert not await record_click(db_session, code=code, visitor_id=VISITOR, path="/store")
    assert await record_click(db_session, code=code, visitor_id=VISITOR[::-1], path="/")
    await db_session.commit()
    assert await _clicks(db_session, partner_id) == 2

    row = (
        await db_session.execute(
            select(AffiliateClick).where(AffiliateClick.visitor_hash == visitor_hash(VISITOR))
        )
    ).scalar_one()
    assert row.landing_path == "/"  # the query string never reaches the table
    assert len(row.visitor_hash) == 64
    assert VISITOR not in row.visitor_hash


async def test_codes_that_do_not_count_record_nothing(db_session: AsyncSession) -> None:
    off_partner, off_code = await _code(db_session, active=False)
    away_partner, away_code = await _code(db_session, status="suspended")
    assert not await record_click(db_session, code=off_code, visitor_id=VISITOR)
    assert not await record_click(db_session, code=away_code, visitor_id=VISITOR)
    assert not await record_click(db_session, code="NO-SUCH-CODE", visitor_id=VISITOR)
    await db_session.commit()
    assert await _clicks(db_session, off_partner) == 0
    assert await _clicks(db_session, away_partner) == 0


async def test_stats_report_clicks_and_distinct_visitors(db_session: AsyncSession) -> None:
    partner_id, code = await _code(db_session)
    await record_click(db_session, code=code, visitor_id=VISITOR)
    await record_click(db_session, code=code, visitor_id=VISITOR[::-1])
    await db_session.commit()
    # The same visitor yesterday too: a second click, not a second visitor.
    await db_session.execute(
        update(AffiliateClick)
        .where(AffiliateClick.visitor_hash == visitor_hash(VISITOR[::-1]))
        .values(visitor_hash=visitor_hash(VISITOR), day=func.current_date() - 1)
    )
    await db_session.commit()

    month = await stats(db_session, partner_id=partner_id, period="month")
    assert (month["clicks"], month["visitors"]) == (2, 1)
    day = await stats(db_session, partner_id=partner_id, period="day")
    assert day["clicks"] >= 1


async def test_the_endpoint_always_answers_204(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    partner_id, code = await _code(db_session)
    for sent in (code, "NO-SUCH-CODE"):
        r = await integration_client.post(
            "/api/v1/affiliate/clicks",
            json={"code": sent, "visitor_id": VISITOR, "path": "/"},
        )
        assert r.status_code == 204, r.text
    again = await integration_client.post(
        "/api/v1/affiliate/clicks", json={"code": code, "visitor_id": VISITOR}
    )
    assert again.status_code == 204
    assert await _clicks(db_session, partner_id) == 1


async def test_a_malformed_visitor_id_is_refused(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/affiliate/clicks", json={"code": "MOKI", "visitor_id": "short"}
    )
    assert r.status_code == 422


async def test_clean_path() -> None:
    assert clean_path(None) == "/"
    assert clean_path("store/likee?ref=MOKI#x") == "/store/likee"
    assert len(clean_path("/" + "a" * 600)) == 255
