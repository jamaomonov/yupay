"""Integration tests for the ``integrations`` module skeleton.

Covers:
- CRUD over ``sku_supplier_mapping`` via admin endpoints.
- Upsert is idempotent — second PUT updates, doesn't duplicate.
- ``game`` kind without ``external_variant_id`` → 422.
- Unknown SKU → 404.
- Non-admin → 403.
- ``sku_sourcing_rules`` still works untouched (no regression in decision).
- ``/admin/integrations/g2b/health`` reports the unconfigured state correctly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return user_id


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="pubg",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG")],
    )
    product = Product(
        id=new_id(),
        slug="pubg-uc",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="PUBG UC")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-60uc",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


# ---------- mapping CRUD ----------


async def test_upsert_mapping_creates_row(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=401)
    await _grant_admin(db_session, tg_id=401)
    headers = {"Authorization": f"Bearer {admin}"}

    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
            "quantity": 1,
            "extra": {},
            "is_active": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    mapping = body["mapping"]
    assert mapping["sku_id"] == _seed_sku
    assert mapping["supplier_slug"] == "g2b"
    assert mapping["kind"] == "voucher"
    assert mapping["external_product_id"] == "42"
    assert mapping["quantity"] == 1
    assert mapping["is_active"] is True
    # cost_sync reports out — no cache row for "42", so the refresh
    # gracefully reports the cache miss instead of updating.
    assert body["cost_sync"]["updated"] is False
    assert body["cost_sync"]["reason"]


async def test_upsert_is_idempotent(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=402)
    await _grant_admin(db_session, tg_id=402)
    headers = {"Authorization": f"Bearer {admin}"}
    url = f"/api/v1/admin/integrations/mappings/{_seed_sku}"
    payload = {
        "supplier_slug": "g2b",
        "kind": "voucher",
        "external_product_id": "42",
    }

    first = await integration_client.put(url, headers=headers, json=payload)
    assert first.status_code == 200

    payload2 = {**payload, "external_product_id": "99", "quantity": 5}
    second = await integration_client.put(url, headers=headers, json=payload2)
    assert second.status_code == 200
    assert second.json()["mapping"]["external_product_id"] == "99"
    assert second.json()["mapping"]["quantity"] == 5

    rows = list(
        (
            await db_session.execute(
                select(SkuSupplierMapping).where(SkuSupplierMapping.sku_id == _seed_sku)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_game_kind_requires_variant(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=403)
    await _grant_admin(db_session, tg_id=403)
    headers = {"Authorization": f"Bearer {admin}"}
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "game",
            "external_product_id": "pubg_mobile",
        },
    )
    assert r.status_code == 422, r.text


async def test_an_amount_priced_service_needs_no_variant(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """G-Engine's `unfixed` services (Telegram Stars) have no denominations at
    all — what to buy is a quantity. Demanding a variant id there would demand
    an id that does not exist upstream, making the SKU unmappable from both the
    seed and this form."""
    admin = await _login_user(integration_client, tg_id=413)
    await _grant_admin(db_session, tg_id=413)
    headers = {"Authorization": f"Bearer {admin}"}
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "gengine",
            "kind": "game",
            "external_product_id": "72",
            "quantity": 250,
        },
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["mapping"]["external_variant_id"] is None
    assert body["mapping"]["quantity"] == 250


async def test_list_filters_by_supplier(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=404)
    await _grant_admin(db_session, tg_id=404)
    headers = {"Authorization": f"Bearer {admin}"}
    await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    r = await integration_client.get(
        "/api/v1/admin/integrations/mappings?supplier_slug=g2b",
        headers=headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(m["sku_id"] == _seed_sku for m in items)

    empty = await integration_client.get(
        "/api/v1/admin/integrations/mappings?supplier_slug=steam",
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []


async def test_delete_mapping(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=405)
    await _grant_admin(db_session, tg_id=405)
    headers = {"Authorization": f"Bearer {admin}"}
    await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    r = await integration_client.delete(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}/g2b",
        headers=headers,
    )
    assert r.status_code == 204

    again = await integration_client.delete(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}/g2b",
        headers=headers,
    )
    assert again.status_code == 404


async def test_upsert_unknown_sku_returns_404(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    admin = await _login_user(integration_client, tg_id=406)
    await _grant_admin(db_session, tg_id=406)
    fake_sku = new_id()
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{fake_sku}",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    assert r.status_code == 404, r.text


async def test_non_admin_forbidden(
    integration_client: AsyncClient,
    _seed_sku: str,
) -> None:
    user = await _login_user(integration_client, tg_id=407)
    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers={"Authorization": f"Bearer {user}"},
        json={
            "supplier_slug": "g2b",
            "kind": "voucher",
            "external_product_id": "42",
        },
    )
    assert r.status_code == 403


# ---------- health probe ----------


async def test_g2b_health_reports_unconfigured(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``G2B_API_KEY``, the probe short-circuits with a clear
    reason — no outbound call to G2B."""
    from yupay.core import config as cfg

    # Explicitly mask any value from a local .env so the test is
    # deterministic even on a developer machine that has a real key.
    monkeypatch.setenv("G2B_API_KEY", "")
    cfg.get_settings.cache_clear()

    admin = await _login_user(integration_client, tg_id=408)
    await _grant_admin(db_session, tg_id=408)
    r = await integration_client.get(
        "/api/v1/admin/integrations/g2b/health",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supplier"] == "g2b"
    assert body["available"] is False
    assert "not configured" in (body.get("reason") or "").lower()


async def test_unknown_supplier_health(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    admin = await _login_user(integration_client, tg_id=409)
    await _grant_admin(db_session, tg_id=409)
    r = await integration_client.get(
        "/api/v1/admin/integrations/wat/health",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert "unknown" in r.json()["reason"]


# ---------- sourcing regression ----------


async def test_catalog_list_returns_cached_entries(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Catalog is populated by the sync endpoint or test fixtures; the
    listing supports search + kind filter."""
    from yupay.modules.integrations.service import upsert_catalog_entry

    await upsert_catalog_entry(
        db_session,
        supplier_slug="g2b",
        kind="voucher",
        external_id="42",
        title="PUBG Mobile Voucher",
        raw={"id": 42},
    )
    await upsert_catalog_entry(
        db_session,
        supplier_slug="g2b",
        kind="game",
        external_id="pubg_mobile",
        title="PUBG Mobile",
        raw={"code": "pubg_mobile"},
    )
    await db_session.commit()

    admin = await _login_user(integration_client, tg_id=420)
    await _grant_admin(db_session, tg_id=420)
    headers = {"Authorization": f"Bearer {admin}"}

    r = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=g2b",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2

    voucher_only = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=g2b&kind=voucher",
        headers=headers,
    )
    items = voucher_only.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "voucher"

    search = await integration_client.get(
        "/api/v1/admin/integrations/catalog?supplier_slug=g2b&search=Mobile",
        headers=headers,
    )
    assert len(search.json()["items"]) == 2


async def test_g2b_sync_catalog_handles_unconfigured(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``G2B_API_KEY`` the sync route reports the misconfig
    instead of attempting any HTTP calls."""
    from yupay.core import config as cfg

    monkeypatch.setenv("G2B_API_KEY", "")
    cfg.get_settings.cache_clear()

    admin = await _login_user(integration_client, tg_id=421)
    await _grant_admin(db_session, tg_id=421)
    r = await integration_client.post(
        "/api/v1/admin/integrations/g2b/sync-catalog",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["vouchers_synced"] == 0
    assert body["games_synced"] == 0
    assert "not configured" in (body["error"] or "").lower()


async def test_topup_routes_to_supplier_once_mapped(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """A ``top_up`` SKU with an active g2b mapping auto-routes to the
    supplier (with a manual fallback) — no inventory step, no mock.

    ``_seed_sku`` is ``kind='top_up'``. Before a mapping exists the
    default is the manual queue; once mapped, sourcing picks the
    supplier. This is the behaviour that replaced the old
    "everything tries inventory then mock" default.
    """
    admin = await _login_user(integration_client, tg_id=410)
    await _grant_admin(db_session, tg_id=410)
    headers = {"Authorization": f"Bearer {admin}"}

    # Before mapping: top_up with no supplier → manual queue.
    before = await integration_client.get(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}", headers=headers
    )
    assert before.status_code == 200
    assert before.json()["primary"] == "supplier:manual"

    await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers=headers,
        json={
            "supplier_slug": "g2b",
            "kind": "game",
            "external_product_id": "pubg_mobile",
            "external_variant_id": "60 UC",
        },
    )

    after = await integration_client.get(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}", headers=headers
    )
    assert after.status_code == 200
    assert after.json()["primary"] == "supplier:g2b"
    assert after.json()["fallback"] == "supplier:manual"
    assert after.json()["rule_present"] is False


async def test_upsert_mapping_replays_pre_sku_code_body(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """A replay body cached before ``mapping.sku_code`` was added (the deploy
    window) must still replay with 200 — sku_code falls back to sku_id — not 500."""
    from yupay.core.idempotency import save_replay

    admin = await _login_user(integration_client, tg_id=450)
    await _grant_admin(db_session, tg_id=450)
    headers = {"Authorization": f"Bearer {admin}"}
    payload = {
        "supplier_slug": "g2b",
        "kind": "voucher",
        "external_product_id": "42",
        "quantity": 1,
        "extra": {},
        "is_active": True,
    }
    # A real upsert yields a valid current-shape response body.
    first = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers={**headers, "Idempotency-Key": "idem-mapping-seed-000001"},
        json=payload,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    body["mapping"].pop("sku_code", None)  # mimic a pre-deploy cached body

    key = "idem-pre-skucode-map-0001"
    await save_replay(
        db_session, scope="integrations.upsert_mapping", idempotency_key=key, body=body
    )
    await db_session.commit()

    r = await integration_client.put(
        f"/api/v1/admin/integrations/mappings/{_seed_sku}",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    assert r.status_code == 200, r.text
    assert r.json()["mapping"]["sku_code"] == _seed_sku


async def test_waxpeer_health_is_reachable(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waxpeer had a balance probe all along and no way to reach it.

    The route used to branch per supplier and knew only G2B, so the admin
    answered "no health probe defined" for a supplier that was live and
    fulfilling Steam top-ups. It resolves through the fulfiller registry now,
    so any supplier that can describe itself shows up.
    """
    from yupay.core import config as cfg

    monkeypatch.setenv("WAXPEER_API_KEY", "")
    cfg.get_settings.cache_clear()

    admin = await _login_user(integration_client, tg_id=410)
    await _grant_admin(db_session, tg_id=410)
    r = await integration_client.get(
        "/api/v1/admin/integrations/waxpeer/health",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supplier"] == "waxpeer"
    # Unconfigured here, but answered by the adapter rather than dismissed as
    # an unknown supplier — that distinction is the whole fix.
    assert body["available"] is False
    assert "not configured" in (body.get("reason") or "").lower()
    assert body.get("reason") != "no health probe defined"


async def test_nova_health_answers_from_the_adapter(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOVA is a reserve, so nothing routes to it on an ordinary day.

    That is exactly why the probe has to work: the key being dead or the
    balance being empty would otherwise be discovered at the moment somebody
    needs to switch a SKU to it.
    """
    from yupay.core import config as cfg

    monkeypatch.setenv("NOVA_API_KEY", "")
    cfg.get_settings.cache_clear()

    admin = await _login_user(integration_client, tg_id=411)
    await _grant_admin(db_session, tg_id=411)
    r = await integration_client.get(
        "/api/v1/admin/integrations/nova/health",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supplier"] == "nova"
    assert body["available"] is False
    assert "not configured" in (body.get("reason") or "").lower()
    # Not "unknown supplier" and not "no health probe defined": both would mean
    # the page cannot answer for NOVA at all.
    assert body.get("reason") != "no health probe defined"
