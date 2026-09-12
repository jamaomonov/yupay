"""Integration tests for public and admin blog routes (spec §9–10)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, BrandTranslation, Category, CategoryTranslation
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
_IDEM = "blog-idempotency-01"


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int = 100500) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    from sqlalchemy import select

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": _IDEM}


async def _seed_brand(db_session: AsyncSession, slug: str = "mlbb") -> Brand:
    category = Category(
        id=new_id(),
        slug=f"{slug}-cat",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=slug,
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Mobile Legends")],
    )
    db_session.add_all([category, brand])
    await db_session.commit()
    return brand


def _draft_payload(
    brand_id: str, *, slug: str = "kak-popolnit-mlbb", body: str = "<p>ok</p>"
) -> dict[str, Any]:
    return {
        "kind": "guide",
        "primary_brand_id": brand_id,
        "translations": [
            {
                "locale": "ru",
                "slug": slug,
                "title": "Как пополнить MLBB",
                "excerpt": "Коротко про player id.",
                "body_html": body,
            }
        ],
    }


async def test_admin_posts_401_without_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/blog/posts")
    assert r.status_code == 401


async def test_create_publish_and_public_get(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    created = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers=admin_headers,
        json=_draft_payload(brand.id),
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    published = await integration_client.post(
        f"/api/v1/admin/blog/posts/{post_id}/publish",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-02"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    public = await integration_client.get("/api/v1/blog/kak-popolnit-mlbb?locale=ru")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["title"] == "Как пополнить MLBB"
    assert body["body_html"] == "<p>ok</p>"
    assert body["primary_brand"]["slug"] == "mlbb"
    assert body["id"] == post_id
    assert body["locale_slugs"] == {"ru": "kak-popolnit-mlbb"}
    assert "draft" not in body


async def test_public_get_404_for_draft(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers=admin_headers,
        json=_draft_payload(brand.id),
    )
    r = await integration_client.get("/api/v1/blog/kak-popolnit-mlbb?locale=ru")
    assert r.status_code == 404


async def test_public_get_404_when_locale_row_missing(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    created = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers=admin_headers,
        json=_draft_payload(brand.id),
    )
    await integration_client.post(
        f"/api/v1/admin/blog/posts/{created.json()['id']}/publish",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-02"},
    )
    r = await integration_client.get("/api/v1/blog/kak-popolnit-mlbb?locale=uz")
    assert r.status_code == 404


async def test_duplicate_slug_returns_409(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    first = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers=admin_headers,
        json=_draft_payload(brand.id),
    )
    assert first.status_code == 201, first.text
    second = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-02"},
        json=_draft_payload(brand.id),
    )
    assert second.status_code == 409


async def test_publish_rejects_empty_body(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    created = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers=admin_headers,
        json=_draft_payload(brand.id, body=""),
    )
    assert created.status_code == 201, created.text
    published = await integration_client.post(
        f"/api/v1/admin/blog/posts/{created.json()['id']}/publish",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-02"},
    )
    assert published.status_code == 422


async def test_event_dates_required_together(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    payload = _draft_payload(brand.id, slug="x2-uc")
    payload["kind"] = "event"
    payload["event_starts_at"] = datetime.now(UTC).isoformat()
    r = await integration_client.post(
        "/api/v1/admin/blog/posts", headers=admin_headers, json=payload
    )
    assert r.status_code == 422


async def test_archive_keeps_published_at_and_hides_publicly(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    created = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers=admin_headers,
        json=_draft_payload(brand.id),
    )
    post_id = created.json()["id"]
    published = await integration_client.post(
        f"/api/v1/admin/blog/posts/{post_id}/publish",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-02"},
    )
    published_at = published.json()["published_at"]
    archived = await integration_client.post(
        f"/api/v1/admin/blog/posts/{post_id}/archive",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-03"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert archived.json()["published_at"] == published_at
    r = await integration_client.get("/api/v1/blog/kak-popolnit-mlbb?locale=ru")
    assert r.status_code == 404


async def test_pin_cap_is_two_published_per_brand(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    ids: list[str] = []
    for i in range(3):
        payload = _draft_payload(brand.id, slug=f"pin-post-{i}")
        payload["pin_on_brand"] = True
        created = await integration_client.post(
            "/api/v1/admin/blog/posts",
            headers={**admin_headers, "Idempotency-Key": f"blog-idempotency-c{i}"},
            json=payload,
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    for i, post_id in enumerate(ids[:2]):
        r = await integration_client.post(
            f"/api/v1/admin/blog/posts/{post_id}/publish",
            headers={**admin_headers, "Idempotency-Key": f"blog-idempotency-p{i}"},
        )
        assert r.status_code == 200, r.text
    third = await integration_client.post(
        f"/api/v1/admin/blog/posts/{ids[2]}/publish",
        headers={**admin_headers, "Idempotency-Key": "blog-idempotency-p2"},
    )
    assert third.status_code == 422


async def test_create_without_idempotency_key_422(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    r = await integration_client.post(
        "/api/v1/admin/blog/posts",
        headers={"Authorization": admin_headers["Authorization"]},
        json=_draft_payload(brand.id),
    )
    assert r.status_code == 422


async def test_admin_list_translations_are_not_n_plus_1(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: dict[str, str]
) -> None:
    brand = await _seed_brand(db_session)
    for i in range(3):
        r = await integration_client.post(
            "/api/v1/admin/blog/posts",
            headers={**admin_headers, "Idempotency-Key": f"blog-idempotency-l{i}"},
            json=_draft_payload(brand.id, slug=f"list-post-{i}"),
        )
        assert r.status_code == 201, r.text

    translation_queries = 0

    @event.listens_for(db_session.bind.sync_engine, "before_cursor_execute")
    def _count(
        conn: object,
        cursor: object,
        statement: str,
        params: object,
        context: object,
        executemany: bool,
    ) -> None:
        nonlocal translation_queries
        if "blog_post_translations" in statement:
            translation_queries += 1

    listed = await integration_client.get("/api/v1/admin/blog/posts", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 3
    assert translation_queries == 1
