"""Cabinet routes for P2P top-ups (spec §5.3, §6)."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.p2p import cabinet_routes, reservations
from yupay.modules.p2p.models import P2PReservation

from tests.integration.cabinet_signup import BASE
from tests.integration.cabinet_signup import auth as _auth
from tests.integration.cabinet_signup import signed_up as _signed_up
from tests.integration.p2p_fixtures import RATE, _card, _fixed_rate, _open  # noqa: F401

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
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    access, merchant_id = await _signed_up(integration_client, cabinet_mails, "st@acme.example.com")
    off = await integration_client.get(f"{P2P}/status", headers=_auth(access))
    assert off.status_code == 200, off.text
    assert off.json() == {"enabled": False, "fx_rate": None}

    await _open(db_session, [merchant_id])
    await db_session.commit()
    on = await integration_client.get(f"{P2P}/status", headers=_auth(access))
    assert on.json()["enabled"] is True
    assert Decimal(on.json()["fx_rate"]) == RATE


async def test_create_returns_the_card_and_exact_amount(
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c1@acme.example.com"
    )
    r = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_uzs"] == 50000
    assert body["status"] == "pending"
    assert re.fullmatch(r"\d{4} \d{4} \d{4} \d{4}", body["card"]["pan"])
    assert body["card"]["pan"] == "9860 3501 4602 3311"


async def test_same_idempotency_key_returns_the_same_number(
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c2@acme.example.com"
    )
    hh = {**h, "Idempotency-Key": "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34"}
    a = await integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
    b = await integration_client.post(f"{P2P}/deposits", headers=hh, json={"amount_uzs": 50000})
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["number"] == b.json()["number"]


async def test_concurrent_same_key_gives_one_number(
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c3@acme.example.com"
    )
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
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c4@acme.example.com"
    )
    first = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    r = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 60000})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "p2p_reservation_open"
    assert r.json()["number"] == first.json()["number"]


async def test_disabled_merchant_gets_404(
    integration_client: AsyncClient, cabinet_mails: list[dict[str, str]]
) -> None:
    access, _ = await _signed_up(integration_client, cabinet_mails, "c5@acme.example.com")
    r = await integration_client.post(
        f"{P2P}/deposits", headers=_auth(access), json={"amount_uzs": 50000}
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "p2p_disabled"


async def test_cancel_then_list_without_card(
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c6@acme.example.com"
    )
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
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c7@acme.example.com"
    )
    made = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    other, _ = await _signed_up(integration_client, cabinet_mails, "c8@acme.example.com")
    r = await integration_client.get(
        f"{P2P}/deposits/{made.json()['number']}", headers=_auth(other)
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "p2p_not_found"


async def test_replay_after_expiry_is_expired_without_card(
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "c9@acme.example.com"
    )
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
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "d1@acme.example.com"
    )
    made = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    other, _ = await _signed_up(integration_client, cabinet_mails, "d2@acme.example.com")
    c = await integration_client.post(
        f"{P2P}/deposits/{made.json()['number']}/cancel", headers=_auth(other)
    )
    assert c.status_code == 404, c.text
    listed = await integration_client.get(f"{P2P}/deposits", headers=_auth(other))
    assert listed.json()["items"] == []
    still = await integration_client.get(f"{P2P}/deposits/{made.json()['number']}", headers=h)
    assert still.json()["status"] == "pending"


@pytest.mark.parametrize("amount", [0, 1_000_000_001], ids=["zero", "over-a-billion"])
async def test_an_amount_out_of_range_is_422(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    cabinet_mails: list[dict[str, str]],
    amount: int,
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "e1@acme.example.com"
    )
    r = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": amount})
    assert r.status_code == 422, r.text


async def test_list_limit_is_validated(
    integration_client: AsyncClient, db_session: AsyncSession, cabinet_mails: list[dict[str, str]]
) -> None:
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "e2@acme.example.com"
    )
    for bad in (0, 101):
        r = await integration_client.get(f"{P2P}/deposits?limit={bad}", headers=h)
        assert r.status_code == 422, r.text
    ok = await integration_client.get(f"{P2P}/deposits?limit=100", headers=h)
    assert ok.status_code == 200, ok.text


async def test_rates_never_print_in_exponent_form(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    cabinet_mails: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``str(Decimal("1.23E+4"))`` is ``"1.23E+4"``; the wire wants ``"12300"``."""
    exponent = Decimal("1.23E+4")

    async def _rate(db: AsyncSession, *, quote: str, override_cache: object = None) -> Decimal:
        return exponent

    monkeypatch.setattr(cabinet_routes, "guarded_usd_rate", _rate)
    monkeypatch.setattr(reservations, "guarded_usd_rate", _rate)
    h, _ = await _enabled_cabinet(
        integration_client, db_session, cabinet_mails, "e3@acme.example.com"
    )
    st = await integration_client.get(f"{P2P}/status", headers=h)
    assert st.json()["fx_rate"] == "12300"
    made = await integration_client.post(f"{P2P}/deposits", headers=h, json={"amount_uzs": 50000})
    assert made.status_code == 201, made.text
    assert "E" not in made.json()["fx_rate"]
    assert Decimal(made.json()["fx_rate"]) == RATE
    listed = await integration_client.get(f"{P2P}/deposits", headers=h)
    assert "E" not in listed.json()["items"][0]["fx_rate"]
