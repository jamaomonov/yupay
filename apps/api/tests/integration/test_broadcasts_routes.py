"""Integration tests for the ``broadcasts`` admin HTTP routes.

Covers the auth gate, draft CRUD, the send/schedule/cancel FSM (including the
naive-datetime-to-UTC normalization carried over from the Task 5 review), test-send
(with and without a linked Telegram account), and the audience-count preview.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.auth import jwt as authjwt
from yupay.modules.notifications.channels.telegram import SendOutcome
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
IDEM_1 = "test-idem-key-0000001"
IDEM_2 = "test-idem-key-0000002"


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
    from sqlalchemy import select

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
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    return {"Authorization": f"Bearer {token}"}


async def _make_bare_admin_headers(db: AsyncSession) -> dict[str, str]:
    """An admin with no ``TelegramLink`` at all — for the test-send negative case."""
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=["admin"]))
    await db.flush()
    await db.commit()
    token = authjwt.mint_access(sub=user_id, sid=str(uuid.uuid4()))
    return {"Authorization": f"Bearer {token}"}


async def _seed_linked_user(db: AsyncSession, *, tg_user_id: int, locale: str = "ru") -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[], locale=locale))
    await db.flush()
    db.add(TelegramLink(id=str(uuid.uuid4()), user_id=user_id, tg_user_id=tg_user_id))
    await db.flush()
    await db.commit()
    return user_id


async def _create_broadcast(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {"title": "Promo blast", "body_html": "<b>Hello</b>"}
    payload.update(overrides)
    r = await client.post(
        "/api/v1/admin/broadcasts",
        headers={**headers, "Idempotency-Key": IDEM_1},
        json=payload,
    )
    assert r.status_code == 201, r.text
    body: dict[str, object] = r.json()
    return body


# ---------- auth gate ----------


async def test_broadcasts_requires_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/broadcasts")
    assert r.status_code == 401


# ---------- create ----------


async def test_create_broadcast_returns_201(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    body = await _create_broadcast(integration_client, _admin_headers)
    assert body["status"] == "draft"
    assert body["title"] == "Promo blast"
    assert body["body_html"] == "<b>Hello</b>"


async def test_create_broadcast_without_idempotency_key_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/broadcasts",
        headers=_admin_headers,
        json={"title": "Promo", "body_html": "<b>Hello</b>"},
    )
    assert r.status_code == 422


# ---------- get / list ----------


async def test_get_broadcast_by_id(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.get(
        f"/api/v1/admin/broadcasts/{created['id']}", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created["id"]


async def test_list_broadcasts_includes_created(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.get("/api/v1/admin/broadcasts", headers=_admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert isinstance(body["items"], list)


# ---------- update / delete ----------


async def test_update_draft_succeeds(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.patch(
        f"/api/v1/admin/broadcasts/{created['id']}",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
        json={"title": "Edited", "body_html": "<i>hi</i>"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Edited"


async def test_delete_draft_succeeds(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.delete(
        f"/api/v1/admin/broadcasts/{created['id']}",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
    )
    assert r.status_code == 204

    check = await integration_client.get(
        f"/api/v1/admin/broadcasts/{created['id']}", headers=_admin_headers
    )
    assert check.status_code == 404


# ---------- send ----------


async def test_send_without_idempotency_key_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/send",
        headers=_admin_headers,
    )
    assert r.status_code == 422


async def test_send_draft_succeeds(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/send",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sending"


async def test_send_again_conflicts(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r1 = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/send",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
    )
    assert r1.status_code == 200, r1.text

    r2 = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/send",
        headers={**_admin_headers, "Idempotency-Key": IDEM_2},
    )
    assert r2.status_code == 409


# ---------- schedule (carry-over naive-datetime fix) ----------


async def test_schedule_naive_past_datetime_returns_422_not_500(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/schedule",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
        json={"scheduled_at": "2020-01-01T00:00:00"},  # naive, clearly in the past
    )
    assert r.status_code == 422, r.text


async def test_schedule_naive_future_datetime_normalizes_to_utc_and_succeeds(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    future_naive = (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None).isoformat()
    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/schedule",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
        json={"scheduled_at": future_naive},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "scheduled"


# ---------- cancel ----------


async def test_cancel_scheduled_broadcast_succeeds(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    sched = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/schedule",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
        json={"scheduled_at": future},
    )
    assert sched.status_code == 200, sched.text

    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/cancel",
        headers={**_admin_headers, "Idempotency-Key": IDEM_2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "canceled"


# ---------- recipients ----------


async def test_list_recipients_empty_for_fresh_broadcast(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.get(
        f"/api/v1/admin/broadcasts/{created['id']}/recipients", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


# ---------- test-send ----------


async def test_test_send_without_telegram_link_422(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    bare_admin_headers = await _make_bare_admin_headers(db_session)
    created = await _create_broadcast(integration_client, _admin_headers)

    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/test",
        headers={**bare_admin_headers, "Idempotency-Key": IDEM_1},
    )
    assert r.status_code == 422, r.text


async def test_test_send_success_does_not_change_broadcast_status(
    integration_client: AsyncClient,
    _admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yupay.modules.broadcasts import routes as broadcasts_routes

    async def _fake_send(**_kwargs: object) -> SendOutcome:
        return SendOutcome(ok=True, status=200)

    monkeypatch.setattr(broadcasts_routes, "send_broadcast_message", _fake_send)

    created = await _create_broadcast(integration_client, _admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/broadcasts/{created['id']}/test",
        headers={**_admin_headers, "Idempotency-Key": IDEM_1},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    check = await integration_client.get(
        f"/api/v1/admin/broadcasts/{created['id']}", headers=_admin_headers
    )
    assert check.json()["status"] == "draft"


# ---------- audience-count ----------


async def test_audience_count_returns_seeded_count(
    integration_client: AsyncClient, db_session: AsyncSession, _admin_headers: dict[str, str]
) -> None:
    # The admin from `_admin_headers` already has a TelegramLink (tg_id=42), contributing
    # 1 to the count on top of the two seeded here.
    await _seed_linked_user(db_session, tg_user_id=910_101, locale="ru")
    await _seed_linked_user(db_session, tg_user_id=910_102, locale="en")

    r = await integration_client.get(
        "/api/v1/admin/broadcasts/audience-count", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 3
