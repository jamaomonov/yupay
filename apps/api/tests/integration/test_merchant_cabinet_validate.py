"""``POST /merchant/cabinet/validate/player`` — the catalog page's player check.

The machine route's twin for a signed-in person; the verdict logic is pinned
by ``test_merchant_validate.py`` and is not repeated here. What this file pins
is the wiring that is this route's own: a cabinet session is what admits a
caller, a brand with no checker answers ``unsupported`` rather than 404 or
``valid``, and the body is validated the same way (``extra="forbid"``).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.cabinet_signup import auth, signed_up
from tests.integration.test_merchant_api_read import _seed_brand

pytestmark = pytest.mark.asyncio

PATH = "/merchant/cabinet/validate/player"


@pytest.fixture
async def session(
    integration_client: AsyncClient,
    cabinet_mails: list[dict[str, str]],
    db_session: AsyncSession,
) -> dict[str, str]:
    """A confirmed cabinet session and one B2B-visible brand to check against."""
    _seed_brand(db_session, n=1, skus=[{"sku_code": "chk-1", "denomination": "60 UC"}])
    await db_session.commit()
    access, _merchant_id = await signed_up(integration_client, cabinet_mails, "chk@example.com")
    return auth(access)


async def test_a_brand_without_a_checker_is_unsupported(
    integration_client: AsyncClient, session: dict[str, str]
) -> None:
    r = await integration_client.post(
        PATH, headers=session, json={"brand": "brand-1", "player_id": "123456789"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "unsupported", "name": None}


async def test_the_cabinet_session_is_the_only_way_in(integration_client: AsyncClient) -> None:
    r = await integration_client.post(PATH, json={"brand": "brand-1", "player_id": "123456789"})
    assert r.status_code == 401


async def test_an_unknown_key_in_the_body_is_refused(
    integration_client: AsyncClient, session: dict[str, str]
) -> None:
    r = await integration_client.post(
        PATH, headers=session, json={"brand": "brand-1", "player": "123456789"}
    )
    assert r.status_code == 422
