"""Admin API for P2P cards, settings, the incoming journal and reservations."""

# ruff: noqa: F811

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.p2p import intake, reservations
from yupay.modules.p2p.models import P2PIncoming
from yupay.modules.p2p.settings import load_settings

from tests.integration.p2p_fixtures import _card, _fixed_rate, _merchant, _open  # noqa: F401
from tests.integration.test_merchant_cabinet_sections import (  # noqa: F401
    _sign_init_data,
    admin_headers,
)
from tests.integration.test_p2p_intake import HUMO_ID, _bank, _credit, _update

pytestmark = pytest.mark.asyncio

A = "/api/v1/admin/p2p"
PAN = "9860350146023311"


def _key() -> str:
    return f"p2p-admin-{new_id()}"


async def _create_card(client: AsyncClient, h: dict[str, str], **over: Any) -> dict[str, Any]:
    body = {
        "label": "Humo main",
        "pan": "9860 3501 4602 3311",
        "holder_name": "OMONOV J",
        "network": "humo",
        **over,
    }
    r = await client.post(f"{A}/cards", headers={**h, "Idempotency-Key": _key()}, json=body)
    assert r.status_code == 201, r.text
    assert PAN not in r.text
    out: dict[str, Any] = r.json()
    return out


async def test_create_card_never_echoes_the_pan(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    card = await _create_card(integration_client, admin_headers)
    assert card["pan_last4"] == "3311"
    assert card["min_amount_uzs"] == 10_000
    r = await integration_client.get(f"{A}/cards", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert PAN not in r.text
    assert [c["pan_last4"] for c in r.json()] == ["3311"]
    assert r.json()[0]["matched_today_uzs"] == 0
    assert r.json()[0]["last_incoming_at"] is None


async def test_create_card_replays_on_the_same_key(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    body = {"label": "L", "pan": PAN, "holder_name": "H", "network": "humo"}
    h = {**admin_headers, "Idempotency-Key": _key()}
    first = await integration_client.post(f"{A}/cards", headers=h, json=body)
    second = await integration_client.post(f"{A}/cards", headers=h, json=body)
    assert first.json()["id"] == second.json()["id"]
    cards = await integration_client.get(f"{A}/cards", headers=admin_headers)
    assert len(cards.json()) == 1


async def test_bad_pan_is_422(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        f"{A}/cards",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"label": "L", "pan": "1234 5678 9012 34xx", "holder_name": "H", "network": "humo"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "p2p_pan_invalid"


async def test_patch_card_limits_and_pan(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    card = await _create_card(integration_client, admin_headers)
    h = {**admin_headers, "Idempotency-Key": _key()}
    r = await integration_client.patch(
        f"{A}/cards/{card['id']}", headers=h, json={"max_amount_uzs": 5_000_000}
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_amount_uzs"] == 5_000_000
    r = await integration_client.patch(
        f"{A}/cards/{card['id']}",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"pan": "8600 1234 5678 9999", "active": False},
    )
    assert r.json()["pan_last4"] == "9999"
    assert r.json()["active"] is False
    assert "8600123456789999" not in r.text
    bad = await integration_client.patch(
        f"{A}/cards/{card['id']}",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"min_amount_uzs": 9_000_000},
    )
    assert bad.status_code == 422, bad.text
    missing = await integration_client.patch(
        f"{A}/cards/{new_id()}",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"active": True},
    )
    assert missing.status_code == 404


async def test_settings_roundtrip(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    m = await _merchant(db_session)
    await db_session.commit()
    r = await integration_client.get(f"{A}/settings", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "off"
    r = await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"mode": "allowlist", "allowlist_merchant_ids": [m], "humo_bot_user_id": HUMO_ID},
    )
    assert r.status_code == 200, r.text
    back = (await integration_client.get(f"{A}/settings", headers=admin_headers)).json()
    assert back["mode"] == "allowlist"
    assert back["allowlist_merchant_ids"] == [m]
    assert back["humo_bot_user_id"] == HUMO_ID
    assert back["owner_telegram_user_id"] is None
    assert back["business_connection_id"] is None
    r = await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"owner_telegram_user_id": 555000222, "business_connection_id": "forged"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["owner_telegram_user_id"] == 555000222
    assert r.json()["business_connection_id"] is None  # read-only: captured by the intake
    unknown = await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"allowlist_merchant_ids": [new_id()]},
    )
    assert unknown.status_code == 422, unknown.text


async def _matched(db: AsyncSession, n: int = 1) -> Any:
    await _card(db)
    m = await _merchant(db)
    await _open(db, [m])
    s = await load_settings(db)
    s.humo_bot_user_id, s.business_connection_id = HUMO_ID, "bc1"
    r = await reservations.reserve(db, merchant_id=m, amount_uzs=50_000, idempotency_key=None)
    res = await intake.ingest_update(
        db,
        _update(1, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.created_at + timedelta(minutes=1),
    )
    assert res.status == "matched"
    for i in range(2, n + 1):
        await intake.ingest_update(
            db,
            _update(i, _credit(f"{i}.000,00", _bank(r.created_at), "1.100.000,00")),
            received_at=r.created_at + timedelta(minutes=1, seconds=i),
        )
    await db.commit()
    return m, r


async def test_incoming_journal_filters_and_hides_raw_text(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    m, r = await _matched(db_session, n=3)
    page = await integration_client.get(f"{A}/incoming", headers=admin_headers)
    assert page.status_code == 200, page.text
    assert "raw_text" not in page.text
    assert PAN not in page.text
    assert len(page.json()["items"]) == 3

    hit = await integration_client.get(f"{A}/incoming?amount=50000", headers=admin_headers)
    items = hit.json()["items"]
    assert len(items) == 1
    assert items[0]["result"] == "matched"
    assert items[0]["reservation"]["number"] == r.number
    assert items[0]["reservation"]["merchant_id"] == m
    assert items[0]["reservation"]["merchant_title"].startswith("Reseller")

    unmatched = await integration_client.get(
        f"{A}/incoming?result=unmatched&card_last4=3311&kind=credit", headers=admin_headers
    )
    assert {i["result"] for i in unmatched.json()["items"]} == {"unmatched"}

    first = await integration_client.get(f"{A}/incoming?limit=2", headers=admin_headers)
    assert len(first.json()["items"]) == 2
    assert first.json()["next_cursor"]
    rest = await integration_client.get(
        f"{A}/incoming?limit=2&cursor={first.json()['next_cursor']}", headers=admin_headers
    )
    assert len(rest.json()["items"]) == 1
    assert rest.json()["next_cursor"] is None

    detail = await integration_client.get(f"{A}/incoming/{items[0]['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert "50.000,00" in detail.json()["raw_text"]
    missing = await integration_client.get(f"{A}/incoming/{new_id()}", headers=admin_headers)
    assert missing.status_code == 404


async def test_reservations_list_and_card_stats(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    m, r = await _matched(db_session)
    got = await integration_client.get(f"{A}/reservations?status=paid", headers=admin_headers)
    assert got.status_code == 200, got.text
    (item,) = got.json()["items"]
    assert item["number"] == r.number
    assert item["card_last4"] == "3311"
    assert item["merchant_title"].startswith("Reseller")
    none = await integration_client.get(
        f"{A}/reservations?status=pending&merchant_id={m}", headers=admin_headers
    )
    assert none.json()["items"] == []
    # The first notification has no predecessor, so its chain verdict is unknown.
    first = (await integration_client.get(f"{A}/cards", headers=admin_headers)).json()
    assert first[0]["chain_ok_last"] is None
    await db_session.execute(update(P2PIncoming).values(chain_ok=False))
    await db_session.commit()
    cards = (await integration_client.get(f"{A}/cards", headers=admin_headers)).json()
    assert cards[0]["chain_ok_last"] is False
    assert cards[0]["matched_today_uzs"] == 50_000
    assert cards[0]["last_incoming_at"] is not None


async def test_non_admin_is_forbidden(integration_client: AsyncClient) -> None:
    user_json = json.dumps({"id": 93, "first_name": "Plain"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    login = await integration_client.post(
        "/api/v1/auth/telegram/webapp", json={"init_data": init_data}
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await integration_client.get(f"{A}/cards", headers=h)).status_code == 403
    r = await integration_client.patch(
        f"{A}/settings", headers={**h, "Idempotency-Key": _key()}, json={"mode": "all"}
    )
    assert r.status_code == 403


async def test_malformed_ids_are_422_not_500(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.get(f"{A}/reservations?merchant_id=nope", headers=admin_headers)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "p2p_bad_id"
    r = await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"allowlist_merchant_ids": ["nope"]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "p2p_unknown_merchant"


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:  # type: ignore[no-untyped-def]  # conftest fixture is untyped
    """Counts every cursor execution on the engine the app is wired to."""
    holder = {"n": 0}

    def _before(*_a: object) -> None:
        holder["n"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _before)


async def test_incoming_list_query_count_is_constant(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    sql_counter: dict[str, int],
) -> None:
    await _matched(db_session, n=3)
    await integration_client.get(f"{A}/incoming", headers=admin_headers)
    sql_counter["n"] = 0
    r = await integration_client.get(f"{A}/incoming?limit=100", headers=admin_headers)
    assert len(r.json()["items"]) == 3
    small = sql_counter["n"]
    assert small > 0

    await _extra_rows(db_session, 27)
    sql_counter["n"] = 0
    r = await integration_client.get(f"{A}/incoming?limit=100", headers=admin_headers)
    assert len(r.json()["items"]) == 30
    assert sql_counter["n"] == small


async def _extra_rows(db: AsyncSession, count: int) -> None:
    from yupay.core.clock import now

    for i in range(count):
        db.add(
            P2PIncoming(
                id=new_id(),
                business_connection_id="bc1",
                telegram_message_id=10_000 + i,
                kind="credit",
                card_last4="3311",
                raw_text="x",
                result="unmatched",
                received_at=now(),
            )
        )
    await db.commit()


class _Log:
    """Stands in for the module logger (cache_logger_on_first_use defeats capture_logs)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append((event, fields))


async def test_settings_and_card_saves_log_who_and_which_fields_only(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Log()
    monkeypatch.setattr("yupay.modules.p2p.admin_routes.log", rec)
    await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"mode": "all", "owner_telegram_user_id": 555000222},
    )
    card = await _create_card(integration_client, admin_headers)
    await integration_client.patch(
        f"{A}/cards/{card['id']}",
        headers={**admin_headers, "Idempotency-Key": _key()},
        json={"pan": "8600 1234 5678 9999", "active": False},
    )
    saved = {event: fields for event, fields in rec.calls if event == "p2p.settings_saved"}
    assert saved["p2p.settings_saved"]["changed"] == ["mode", "owner_telegram_user_id"]
    assert saved["p2p.settings_saved"]["admin_id"]
    cards = [fields for event, fields in rec.calls if event == "p2p.card_saved"]
    assert cards[0]["admin_id"] == saved["p2p.settings_saved"]["admin_id"]
    assert cards[1]["changed"] == ["active", "pan"]
    dumped = repr(rec.calls)
    assert "8600123456789999" not in dumped
    assert PAN not in dumped
    assert "555000222" not in dumped
