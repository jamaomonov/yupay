"""Cabinet routes for P2P top-ups (spec §5.3, §6)."""

# ruff: noqa: F811

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.p2p import cabinet_routes
from yupay.modules.p2p.models import P2PReservation

from tests.integration.p2p_fixtures import RATE, _card, _fixed_rate, _open  # noqa: F401
from tests.integration.test_merchant_cabinet_sections import (
    BASE,
    _auth,
    _signed_up,
    sent,  # noqa: F401 - fixture
)

pytestmark = pytest.mark.asyncio

P2P = f"{BASE}/p2p"


@pytest.fixture(autouse=True)
def _route_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _rate(db: AsyncSession, *, quote: str, override_cache: object = None) -> Decimal:
        return RATE

    monkeypatch.setattr(cabinet_routes, "guarded_usd_rate", _rate)


async def _enabled_cabinet(
    client: AsyncClient, db: AsyncSession, mails: list[dict[str, str]], email: str
) -> tuple[dict[str, str], str]:
    access, merchant_id = await _signed_up(client, mails, email)
    await _card(db)
    await _open(db, [merchant_id])
    await db.commit()
    return _auth(access), merchant_id


async def test_status_is_off_by_default_then_on_with_a_rate(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    access, merchant_id = await _signed_up(integration_client, sent, "st@acme.example.com")
    off = await integration_client.get(f"{P2P}/status", headers=_auth(access))
    assert off.status_code == 200, off.text
    assert off.json() == {"enabled": False, "fx_rate": None}

    await _open(db_session, [merchant_id])
    await db_session.commit()
    on = await integration_client.get(f"{P2P}/status", headers=_auth(access))
    assert on.json()["enabled"] is True
    assert Decimal(on.json()["fx_rate"]) == RATE


async def test_create_returns_the_card_and_exact_amount(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c1@acme.example.com")
    r = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_uzs"] == 50000
    assert body["status"] == "pending"
    assert re.fullmatch(r"\d{4} \d{4} \d{4} \d{4}", body["card"]["pan"])
    assert body["card"]["pan"] == "9860 3501 4602 3311"


async def test_same_idempotency_key_returns_the_same_number(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c2@acme.example.com")
    hh = {**h, "Idempotency-Key": "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34"}
    a = await integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
    b = await integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["number"] == b.json()["number"]


async def test_concurrent_same_key_gives_one_number(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c3@acme.example.com")
    hh = {**h, "Idempotency-Key": "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b35"}
    rs = await asyncio.gather(
        *[
            integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
            for _ in range(2)
        ]
    )
    assert [r.status_code for r in rs] == [201, 201], [r.text for r in rs]
    assert rs[0].json()["number"] == rs[1].json()["number"]


async def test_second_open_is_a_conflict(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c4@acme.example.com")
    first = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    r = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 60000})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "p2p_reservation_open"
    assert r.json()["number"] == first.json()["number"]


async def test_disabled_merchant_gets_404(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    access, _ = await _signed_up(integration_client, sent, "c5@acme.example.com")
    r = await integration_client.post(
        f"{P2P}/deposits", headers=_auth(access), json={"amount_uzs": 50000}
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "p2p_disabled"


async def test_cancel_then_list_without_card(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c6@acme.example.com")
    made = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    n = made.json()["number"]
    polled = await integration_client.get(f"{P2P}/deposits/{n}", headers=h)
    assert polled.json()["card"] is not None
    c = await integration_client.post(f"{P2P}/deposits/{n}/cancel", headers=h)
    assert c.status_code == 200, c.text
    assert c.json()["status"] == "cancelled"
    assert c.json()["card"] is None
    listed = await integration_client.get(f"{P2P}/deposits", headers=h)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [i["number"] for i in items] == [n]
    assert items[0]["card"] is None
    assert listed.json()["next_cursor"] is None


async def test_another_merchants_deposit_is_404(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c7@acme.example.com")
    made = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    other, _ = await _signed_up(integration_client, sent, "c8@acme.example.com")
    r = await integration_client.get(
        f"{P2P}/deposits/{made.json()['number']}", headers=_auth(other)
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "p2p_not_found"


async def test_replay_after_expiry_is_expired_without_card(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "c9@acme.example.com")
    hh = {**h, "Idempotency-Key": "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b36"}
    a = await integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
    assert a.status_code == 201, a.text
    await db_session.execute(
        update(P2PReservation)
        .where(P2PReservation.number == a.json()["number"])
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()
    b = await integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
    assert b.status_code == 201, b.text
    assert b.json()["number"] == a.json()["number"]
    assert b.json()["status"] == "expired"
    assert b.json()["card"] is None


async def test_another_merchant_cannot_cancel_or_list_it(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(integration_client, db_session, sent, "d1@acme.example.com")
    made = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    other, _ = await _signed_up(integration_client, sent, "d2@acme.example.com")
    c = await integration_client.post(
        f"{P2P}/deposits/{made.json()['number']}/cancel", headers=_auth(other)
    )
    assert c.status_code == 404, c.text
    listed = await integration_client.get(f"{P2P}/deposits", headers=_auth(other))
    assert listed.json()["items"] == []
    still = await integration_client.get(f"{P2P}/deposits/{made.json()['number']}", headers=h)
    assert still.json()["status"] == "pending"
