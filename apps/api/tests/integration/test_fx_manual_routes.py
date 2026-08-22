"""Admin toggle: typed FX rate becomes the system-wide rate."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.modules.fx.providers.base import FxProvider, Quote
from yupay.modules.fx.service import FxService
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


class _StubProvider(FxProvider):
    name = "stub"

    def __init__(self, rates: dict[str, Decimal]) -> None:
        self._rates = rates

    def supports(self, base: str, quote: str) -> bool:
        return base.upper() == "USD" and quote.upper() in self._rates

    async def get_rate(self, base: str, quote: str) -> Quote:
        return Quote(
            base=base.upper(),
            quote=quote.upper(),
            rate=self._rates[quote.upper()],
            fetched_at=now(),
            source=self.name,
        )


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


@pytest.fixture
def _stub_service(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _StubProvider(
        {"RUB": Decimal("90.5"), "UZS": Decimal("12700.25"), "USDT": Decimal("1.0001")}
    )

    shared_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _build(*, settings=None, redis=None) -> FxService:
        return FxService(
            providers=[provider],
            redis=shared_redis,
            session_factory=get_session_factory(),
        )

    monkeypatch.setattr("yupay.modules.fx.routes.build_default_service", _build)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=8801)
    await _grant_admin(db_session, tg_id=8801)
    return {"Authorization": f"Bearer {token}"}


async def test_manual_rate_is_what_the_public_endpoint_returns(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    _stub_service: None,
) -> None:
    patch = await integration_client.patch(
        "/api/v1/admin/fx/rates/UZS",
        headers=admin_headers,
        json={"use_manual": True, "manual_rate": "12500"},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["rate"] == "12500"
    assert body["source"] == "manual"
    assert body["use_manual"] is True
    assert body["fx_rate"] == "12700.25"

    public = await integration_client.get("/api/v1/fx/rates")
    assert public.status_code == 200, public.text
    uzs = next(r for r in public.json()["rates"] if r["quote"] == "UZS")
    assert uzs["rate"] == "12500"
    assert uzs["source"] == "manual"

    off = await integration_client.patch(
        "/api/v1/admin/fx/rates/UZS",
        headers=admin_headers,
        json={"use_manual": False},
    )
    assert off.status_code == 200, off.text
    public_off = await integration_client.get("/api/v1/fx/rates")
    uzs_off = next(r for r in public_off.json()["rates"] if r["quote"] == "UZS")
    assert uzs_off["rate"] == "12700.25"
    assert uzs_off["source"] == "stub"


async def test_manual_toggle_requires_a_positive_rate(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    _stub_service: None,
) -> None:
    r = await integration_client.patch(
        "/api/v1/admin/fx/rates/RUB",
        headers=admin_headers,
        json={"use_manual": True},
    )
    assert r.status_code == 422


async def test_unknown_quote_is_404(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    _stub_service: None,
) -> None:
    r = await integration_client.patch(
        "/api/v1/admin/fx/rates/EUR",
        headers=admin_headers,
        json={"use_manual": True, "manual_rate": "1"},
    )
    assert r.status_code == 404
