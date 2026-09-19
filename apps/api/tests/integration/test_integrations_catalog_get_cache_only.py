"""``GET /admin/integrations/catalog`` reads the cache only — never a supplier.

AGENTS.md §10 forbids a synchronous supplier call inside a request handler on
the money path; this admin picker isn't on that path either way, but the
contract for it is explicit: the picker polls the cache, and only the two
POST sync endpoints (hourly job or on-demand) ever reach a supplier client.

Every supplier's API key is configured here (so a wrongly-wired GET handler
would actually have somewhere to call), and the whole test runs inside a bare
``@respx.mock`` block with **no routes registered** — respx blocks all real
outbound HTTP in that scope, so a stray supplier call would fail the request
outright rather than passing unnoticed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.integrations import service as svc
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


@pytest.fixture(autouse=True)
def _all_suppliers_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", "https://g2b.getcache.test/v1")
    monkeypatch.setenv("NOVA_API_KEY", "test-key")
    monkeypatch.setenv("NOVA_BASE_URL", "https://nova.getcache.test")
    monkeypatch.setenv("GENGINE_API_KEY", "test-key")
    monkeypatch.setenv("GENGINE_BASE_URL", "https://gengine.getcache.test/v2.1")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_admin(client: AsyncClient, db: AsyncSession, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return token


@respx.mock
async def test_get_catalog_never_calls_a_supplier(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Seed rows directly — the point is that the GET handler must not need to
    # go fetch them itself.
    await svc.upsert_catalog_entry(
        db_session,
        supplier_slug="nova",
        kind="game",
        external_id="mobile_legends_ru",
        title="Mobile Legends (RU)",
        raw={"category_id": "mobile_legends_ru"},
    )
    await svc.upsert_catalog_entry(
        db_session,
        supplier_slug="nova",
        kind="game_denom",
        external_id="275_diamonds",
        title="275 Diamonds",
        raw={"offer_id": "275_diamonds"},
        parent_external_id="mobile_legends_ru",
    )
    await db_session.commit()

    admin = await _login_admin(integration_client, db_session, tg_id=901)
    headers = {"Authorization": f"Bearer {admin}"}

    listing = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=nova", headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["items"]) == 2

    denoms = await integration_client.get(
        "/api/v1/admin/integrations/catalog"
        "?supplier_slug=nova&kind=game_denom&parent_external_id=mobile_legends_ru",
        headers=headers,
    )
    assert denoms.status_code == 200, denoms.text
    assert len(denoms.json()["items"]) == 1


@respx.mock
async def test_two_games_keep_their_own_copy_of_a_shared_denomination_id(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A denomination id is unique per game, not per supplier.

    NOVA calls the 55-diamond pack ``55_diamonds`` in Magic Chess Go Go (RU)
    and in Mobile Legends (RU) alike. While the cache key was
    ``(supplier_slug, kind, external_id)`` the two games shared one row and
    whichever synced last took it: on production, eight of Magic Chess RU's
    seventeen denominations were missing from the picker because Mobile
    Legends RU had synced after it. 0084 put ``parent_external_id`` in the
    key; this asserts the picker now shows each game its own.
    """
    for game in ("magic_chess_gogo_ru", "mobile_legends_ru"):
        await svc.upsert_catalog_entry(
            db_session,
            supplier_slug="nova",
            kind="game_denom",
            external_id="55_diamonds",
            title=f"55 Diamonds ({game})",
            raw={"offer_id": "55_diamonds"},
            parent_external_id=game,
        )
    await db_session.commit()

    admin = await _login_admin(integration_client, db_session, tg_id=931)
    headers = {"Authorization": f"Bearer {admin}"}

    for game in ("magic_chess_gogo_ru", "mobile_legends_ru"):
        resp = await integration_client.get(
            "/api/v1/admin/integrations/catalog"
            f"?supplier_slug=nova&kind=game_denom&parent_external_id={game}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert [i["external_id"] for i in items] == ["55_diamonds"]
        # Its own title, not the other game's — proving these are two rows
        # and not one row whose parent flips on every sync.
        assert items[0]["title"] == f"55 Diamonds ({game})"


@respx.mock
async def test_a_flat_row_still_has_exactly_one_copy(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Widening the key must not let a voucher exist twice.

    Flat ``voucher``/``game`` rows pass no parent, which 0084 stores as
    ``''``; two upserts of the same id are still one row, so
    ``cost_lookup``'s ``scalar_one_or_none`` on a voucher cannot start
    raising.
    """
    for title in ("Steam 10 USD", "Steam 10 USD (renamed)"):
        await svc.upsert_catalog_entry(
            db_session,
            supplier_slug="g2b",
            kind="voucher",
            external_id="107",
            title=title,
            raw={"id": "107"},
        )
    await db_session.commit()

    rows = await svc.list_catalog(db_session, supplier_slug="g2b", kind="voucher")
    assert [r.external_id for r in rows] == ["107"]
    assert rows[0].title == "Steam 10 USD (renamed)"
    assert rows[0].parent_external_id == ""
