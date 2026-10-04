"""Admin P2P guards: owner change unpins the connection; the journal's amount filter."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.p2p.settings import load_settings

pytestmark = pytest.mark.asyncio

A = "/api/v1/admin/p2p"
OWNER, OTHER = 555000222, 555000333


class _Log:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append((event, fields))


async def _pinned(db: AsyncSession) -> None:
    s = await load_settings(db)
    s.owner_telegram_user_id, s.business_connection_id = OWNER, "bc-owner"
    await db.commit()


async def _patch(client: AsyncClient, h: dict[str, str], body: dict[str, Any]) -> Any:
    r = await client.patch(
        f"{A}/settings", headers={**h, "Idempotency-Key": f"k-{new_id()}"}, json=body
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_changing_the_owner_unpins_the_connection(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pinned(db_session)
    rec = _Log()
    monkeypatch.setattr("yupay.modules.p2p.admin_routes.log", rec)

    out = await _patch(integration_client, admin_headers, {"owner_telegram_user_id": OTHER})

    assert out["owner_telegram_user_id"] == OTHER
    assert out["business_connection_id"] is None
    await db_session.refresh(await load_settings(db_session))
    assert (await load_settings(db_session)).business_connection_id is None
    unpinned = [fields for event, fields in rec.calls if event == "p2p.connection_unpinned"]
    assert len(unpinned) == 1
    dumped = repr(rec.calls)
    assert str(OWNER) not in dumped
    assert str(OTHER) not in dumped
    assert "bc-owner" not in dumped


async def test_clearing_the_owner_unpins_too(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    await _pinned(db_session)
    out = await _patch(integration_client, admin_headers, {"owner_telegram_user_id": None})
    assert out["business_connection_id"] is None


async def test_resaving_the_same_owner_keeps_the_pin(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pinned(db_session)
    rec = _Log()
    monkeypatch.setattr("yupay.modules.p2p.admin_routes.log", rec)
    out = await _patch(
        integration_client, admin_headers, {"owner_telegram_user_id": OWNER, "mode": "all"}
    )
    assert out["business_connection_id"] == "bc-owner"
    assert not [e for e, _ in rec.calls if e == "p2p.connection_unpinned"]


@pytest.mark.parametrize(
    "amount",
    ["NaN", "nan", "Infinity", "-Infinity", "-5", "1.234", "abc", "1e400"],
    ids=["nan", "nan-lower", "inf", "neg-inf", "negative", "three-decimals", "text", "huge-exp"],
)
async def test_a_bad_amount_filter_is_422(
    integration_client: AsyncClient, admin_headers: dict[str, str], amount: str
) -> None:
    r = await integration_client.get(
        f"{A}/incoming", params={"amount": amount}, headers=admin_headers
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "p2p_amount_invalid"


@pytest.mark.parametrize("amount", ["50000", "50000.5", "50000.50", "0"])
async def test_a_good_amount_filter_is_accepted(
    integration_client: AsyncClient, admin_headers: dict[str, str], amount: str
) -> None:
    r = await integration_client.get(
        f"{A}/incoming", params={"amount": amount}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
