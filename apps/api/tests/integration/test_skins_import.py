"""``upsert_items`` is idempotent, updates metadata, and never touches prices."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.skins.bymykel import CatalogRow, dedupe, rows_from_skins, upsert_items
from yupay.modules.skins.models import SkinItem

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"


def _rows() -> list[CatalogRow]:
    return dedupe(rows_from_skins(json.loads((FIXTURES / "bymykel_skins.json").read_text())))


async def test_second_import_writes_nothing(db_session: AsyncSession) -> None:
    assert await upsert_items(db_session, _rows()) == 3
    await db_session.commit()
    assert await upsert_items(db_session, _rows()) == 0


async def test_changed_image_is_written_and_prices_survive(db_session: AsyncSession) -> None:
    await upsert_items(db_session, _rows())
    await db_session.commit()
    row = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.slug == "ak-47-redline-field-tested")
        )
    ).scalar_one()
    row.min_auto_units = 27867
    row.count_auto = 49
    row.active = True
    await db_session.commit()

    from dataclasses import replace

    changed = [
        replace(r, image_url="https://community.akamai.steamstatic.com/economy/image/new")
        if r.slug == "ak-47-redline-field-tested"
        else r
        for r in _rows()
    ]
    assert await upsert_items(db_session, changed) == 1
    await db_session.commit()
    db_session.expire_all()
    row = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.slug == "ak-47-redline-field-tested")
        )
    ).scalar_one()
    assert row.image_url is not None
    assert row.image_url.endswith("/new")
    assert (row.min_auto_units, row.count_auto, row.active) == (27867, 49, True)
