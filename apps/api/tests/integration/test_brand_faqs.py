"""Integration tests for per-brand FAQ.

Covers the admin CRUD round-trip and the public embedding on the brand detail:
- only ``active`` FAQs are returned, ordered by ``sort_order``
- the question/answer are localised by ``Accept-Language`` with ru fallback
- admin sees inactive rows; delete cascades the translations
- the admin endpoints require an admin token
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _admin_headers(
    client: AsyncClient, db_session: AsyncSession, tg_id: int = 7700
) -> dict[str, str]:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _make_brand(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    r = await client.post(
        "/api/v1/admin/catalog/categories",
        headers=headers,
        json={"slug": "faq-cat", "translations": [{"locale": "ru", "name": "Кат"}]},
    )
    assert r.status_code == 201, r.text
    cat_id = r.json()["id"]
    r = await client.post(
        "/api/v1/admin/catalog/brands",
        headers=headers,
        json={
            "slug": "faq-brand",
            "category_id": cat_id,
            "translations": [{"locale": "ru", "name": "Бренд"}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], "faq-brand"


async def test_faq_admin_crud_and_public_embedding(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _admin_headers(integration_client, db_session)
    brand_id, brand_slug = await _make_brand(integration_client, headers)

    # FAQ 1 (sort 1) — ru + en
    r = await integration_client.post(
        f"/api/v1/admin/catalog/brands/{brand_id}/faqs",
        headers=headers,
        json={
            "sort_order": 1,
            "active": True,
            "translations": [
                {"locale": "ru", "question": "Нужен ли пароль?", "answer": "Нет, только UID."},
                {"locale": "en", "question": "Password needed?", "answer": "No, UID only."},
            ],
        },
    )
    assert r.status_code == 201, r.text
    faq1 = r.json()
    assert faq1["brand_id"] == brand_id
    assert len(faq1["translations"]) == 2

    # FAQ 2 (sort 0) — ru only
    r = await integration_client.post(
        f"/api/v1/admin/catalog/brands/{brand_id}/faqs",
        headers=headers,
        json={
            "sort_order": 0,
            "active": True,
            "translations": [{"locale": "ru", "question": "Как быстро?", "answer": "1–3 минуты."}],
        },
    )
    assert r.status_code == 201
    faq2 = r.json()

    # FAQ 3 — inactive (hidden on the public side)
    r = await integration_client.post(
        f"/api/v1/admin/catalog/brands/{brand_id}/faqs",
        headers=headers,
        json={
            "sort_order": 5,
            "active": False,
            "translations": [{"locale": "ru", "question": "Скрытый?", "answer": "Да."}],
        },
    )
    assert r.status_code == 201

    # Admin list sees all three (incl. inactive), ordered by sort_order.
    r = await integration_client.get(
        f"/api/v1/admin/catalog/brands/{brand_id}/faqs", headers=headers
    )
    assert r.status_code == 200
    assert len(r.json()) == 3

    # Public (ru): only the two active FAQs, ordered by sort_order, flat strings.
    r = await integration_client.get(
        f"/api/v1/catalog/brands/{brand_slug}", headers={"Accept-Language": "ru"}
    )
    assert r.status_code == 200
    faqs = r.json()["faqs"]
    assert len(faqs) == 2
    assert faqs[0]["question"] == "Как быстро?"  # sort_order 0 first
    assert faqs[1]["question"] == "Нужен ли пароль?"
    assert all(set(f.keys()) == {"id", "question", "answer"} for f in faqs)

    # Public (en): FAQ1 uses its en text; the ru-only FAQ2 falls back to ru.
    r = await integration_client.get(
        f"/api/v1/catalog/brands/{brand_slug}", headers={"Accept-Language": "en"}
    )
    faqs_en = r.json()["faqs"]
    assert faqs_en[0]["question"] == "Как быстро?"  # ru fallback
    assert faqs_en[1]["question"] == "Password needed?"  # en translation

    # PATCH: deactivating FAQ1 drops it from the public payload.
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/faqs/{faq1['id']}", headers=headers, json={"active": False}
    )
    assert r.status_code == 200
    r = await integration_client.get(
        f"/api/v1/catalog/brands/{brand_slug}", headers={"Accept-Language": "ru"}
    )
    assert len(r.json()["faqs"]) == 1

    # DELETE removes the row.
    r = await integration_client.delete(f"/api/v1/admin/catalog/faqs/{faq2['id']}", headers=headers)
    assert r.status_code == 204
    r = await integration_client.get(
        f"/api/v1/admin/catalog/brands/{brand_id}/faqs", headers=headers
    )
    assert all(f["id"] != faq2["id"] for f in r.json())


async def test_faq_endpoints_require_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/catalog/brands/whatever/faqs")
    assert r.status_code == 401
