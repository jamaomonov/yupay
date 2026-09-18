"""Integration tests for ``/api/v1/admin/catalog/*`` write endpoints.

Covers:
- 401 without a token, 403 with a non-admin token, 200 with admin
- CRUD round-trip for category → brand → product → SKU
- Validation: slug pattern, duplicate slug → 409
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
from sqlalchemy import update
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


async def _login(client: AsyncClient, tg_id: int = 100500) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    body: dict[str, str] = r.json()
    token: str = body["access_token"]
    return token


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    """Promote the just-logged-in user to admin via direct DB update."""
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


# ---------- auth guard ----------


async def test_admin_endpoint_401_without_token(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/catalog/brands")
    assert r.status_code == 401


async def test_admin_endpoint_403_for_non_admin(integration_client: AsyncClient) -> None:
    token = await _login(integration_client, tg_id=200)
    r = await integration_client.get(
        "/api/v1/admin/catalog/brands",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- CRUD round-trip ----------


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    # Mint a fresh token so the user's role is re-read on next request (it is — current_user
    # always hits the DB). One token is enough.
    return {"Authorization": f"Bearer {token}"}


async def test_full_crud_flow(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    # 1) Category
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={
            "slug": "test-cat",
            "icon": "gamepad",
            "sort_order": 100,
            "active": True,
            "translations": [
                {"locale": "ru", "name": "Тест"},
                {"locale": "en", "name": "Test"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    category = r.json()
    category_id = category["id"]
    assert category["slug"] == "test-cat"

    # 2) Brand
    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=_admin_headers,
        json={
            "slug": "test-brand",
            "category_id": category_id,
            "accent_color": "#FF0000",
            "translations": [{"locale": "ru", "name": "Тестбренд"}],
        },
    )
    assert r.status_code == 201, r.text
    brand_id = r.json()["id"]

    # 3) Product (with required_fields)
    r = await integration_client.post(
        "/api/v1/admin/catalog/products",
        headers=_admin_headers,
        json={
            "slug": "test-product",
            "brand_id": brand_id,
            "kind": "top_up",
            "supplier_hint": "codashop",
            "required_fields": [
                {
                    "key": "player_id",
                    "label": {"ru": "ID", "en": "ID"},
                    "type": "text",
                    "required": True,
                },
            ],
            "translations": [{"locale": "ru", "name": "Продукт"}],
        },
    )
    assert r.status_code == 201, r.text
    product = r.json()
    product_id = product["id"]
    assert product["required_fields"][0]["key"] == "player_id"

    # 4) SKU with an override
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "test-sku-1",
            "denomination": "1 unit",
            "region": "TR",
            "price_usd": "1.50",
            "price_overrides": [{"currency": "rub", "price": "150.00"}],
        },
    )
    assert r.status_code == 201, r.text
    sku = r.json()
    sku_id = sku["id"]
    assert sku["price_overrides"][0]["currency"] == "RUB"  # uppercased by validator

    # 5) PATCH product
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/products/{product_id}",
        headers=_admin_headers,
        json={"active": False, "sort_order": 999},
    )
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["sort_order"] == 999

    # 6) Listing returns the inactive product (admin sees everything)
    r = await integration_client.get("/api/v1/admin/catalog/products", headers=_admin_headers)
    assert r.status_code == 200
    assert any(p["id"] == product_id for p in r.json())

    # 7) Delete cascade: deleting the product removes its SKUs
    r = await integration_client.delete(
        f"/api/v1/admin/catalog/products/{product_id}", headers=_admin_headers
    )
    assert r.status_code == 204
    r = await integration_client.get(f"/api/v1/admin/catalog/skus/{sku_id}", headers=_admin_headers)
    # The SKU endpoint isn't defined for GET-by-id — but the product DELETE cascade
    # should have removed it. Verify via the list endpoint.
    r = await integration_client.get("/api/v1/admin/catalog/skus", headers=_admin_headers)
    assert all(s["id"] != sku_id for s in r.json())


async def test_bulk_set_uzs_prices_recomputes_overrides(
    integration_client: AsyncClient,
    _admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator clicks "recompute UZS" and overrides are written for every
    SKU with a known cost_usdt, using the same FX service that the
    storefront uses at checkout."""
    from decimal import Decimal as _Dec

    import fakeredis.aioredis
    from yupay.core.clock import now as _now
    from yupay.modules.fx.providers.base import FxProvider, Quote
    from yupay.modules.fx.service import FxService

    class _StubFx(FxProvider):
        name = "stub"

        def supports(self, base: str, quote: str) -> bool:
            return base.upper() == "USDT" and quote.upper() == "UZS"

        async def get_rate(self, base: str, quote: str) -> Quote:
            return Quote(
                base="USDT",
                quote="UZS",
                rate=_Dec("12700.0"),
                fetched_at=_now(),
                source=self.name,
            )

    def _build(*, settings=None, redis=None):
        return FxService(
            providers=[_StubFx()],
            redis=fakeredis.aioredis.FakeRedis(decode_responses=True),
        )

    monkeypatch.setattr("yupay.modules.catalog.admin_routes.build_default_service", _build)

    # Seed category/brand/product/two SKUs (one with cost_usdt, one without).
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={"slug": "fx-cat", "translations": [{"locale": "ru", "name": "fx"}]},
    )
    assert r.status_code == 201
    cid = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=_admin_headers,
        json={
            "slug": "fx-brand",
            "category_id": cid,
            "translations": [{"locale": "ru", "name": "b"}],
        },
    )
    bid = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/products",
        headers=_admin_headers,
        json={
            "slug": "fx-prod",
            "brand_id": bid,
            "kind": "top_up",
            "translations": [{"locale": "ru", "name": "p"}],
        },
    )
    pid = r.json()["id"]

    # SKU A — has cost_usdt, should get a UZS override.
    r_a = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": pid,
            "sku_code": "fx-a",
            "price_usd": "5.00",
            "cost_usdt": "4.00",
        },
    )
    assert r_a.status_code == 201
    sku_a = r_a.json()
    assert _Dec(sku_a["cost_usdt"]) == _Dec("4")

    # SKU B — no cost_usdt, should be skipped.
    r_b = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={"product_id": pid, "sku_code": "fx-b", "price_usd": "10.00"},
    )
    assert r_b.status_code == 201

    # Trigger the bulk operation.
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus/bulk-set-uzs-prices",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_total"] == 1
    assert body["skipped_without_cost"] == 1
    assert _Dec(body["rate"]) == _Dec("12700.0")

    # Confirm the override on SKU A is exactly cost × rate, and that
    # listing it back includes the new override row.
    r = await integration_client.get("/api/v1/admin/catalog/skus", headers=_admin_headers)
    skus = {s["sku_code"]: s for s in r.json()}
    overrides_a = {o["currency"]: o for o in skus["fx-a"]["price_overrides"]}
    assert "UZS" in overrides_a
    assert _Dec(overrides_a["UZS"]["price"]) == _Dec("50800")  # 4 × 12700
    overrides_b = {o["currency"]: o for o in skus["fx-b"]["price_overrides"]}
    assert "UZS" not in overrides_b


async def test_patch_brand_highlights_persist_and_round_trip(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Admin can set ``highlights`` per-translation via PATCH and read them
    back on GET — closing the gap where the field could only be set via
    direct SQL. Also asserts the trim/empty-drop cleanup in
    ``TranslationIn._clean_highlights``."""
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={"slug": "hl-cat", "translations": [{"locale": "ru", "name": "Кат"}]},
    )
    assert r.status_code == 201, r.text
    category_id = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=_admin_headers,
        json={
            "slug": "hl-brand",
            "category_id": category_id,
            "translations": [{"locale": "ru", "name": "Бренд"}],
        },
    )
    assert r.status_code == 201, r.text
    brand_id = r.json()["id"]
    # Created without highlights -> defaults to an empty list, not null.
    assert r.json()["translations"][0]["highlights"] == []

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/brands/{brand_id}",
        headers=_admin_headers,
        json={
            "translations": [
                {
                    "locale": "ru",
                    "name": "Бренд",
                    "highlights": ["Оплата в сумах", "  По ID игрока  ", "", "Без пароля"],
                },
                {"locale": "en", "name": "Brand", "highlights": ["No password"]},
            ],
        },
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    by_locale = {t["locale"]: t for t in patched["translations"]}
    # Trimmed, and the blank entry dropped.
    assert by_locale["ru"]["highlights"] == ["Оплата в сумах", "По ID игрока", "Без пароля"]
    assert by_locale["en"]["highlights"] == ["No password"]

    # GET (admin list) reflects the persisted values.
    r = await integration_client.get("/api/v1/admin/catalog/brands", headers=_admin_headers)
    assert r.status_code == 200, r.text
    brand = next(b for b in r.json() if b["id"] == brand_id)
    by_locale = {t["locale"]: t for t in brand["translations"]}
    assert by_locale["ru"]["highlights"] == ["Оплата в сумах", "По ID игрока", "Без пароля"]
    assert by_locale["en"]["highlights"] == ["No password"]


async def test_brand_highlight_over_40_chars_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={"slug": "hl-len-cat", "translations": [{"locale": "ru", "name": "Кат"}]},
    )
    assert r.status_code == 201, r.text
    category_id = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=_admin_headers,
        json={
            "slug": "hl-len-brand",
            "category_id": category_id,
            "translations": [
                {"locale": "ru", "name": "Бренд", "highlights": ["x" * 41]},
            ],
        },
    )
    assert r.status_code == 422, r.text
    assert "at most 40 characters" in r.text


async def test_duplicate_slug_returns_409(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    payload = {
        "slug": "dup-cat",
        "translations": [{"locale": "ru", "name": "X"}],
    }
    r1 = await integration_client.post(
        "/api/v1/admin/catalog/categories", headers=_admin_headers, json=payload
    )
    assert r1.status_code == 201
    r2 = await integration_client.post(
        "/api/v1/admin/catalog/categories", headers=_admin_headers, json=payload
    )
    assert r2.status_code == 409


async def test_invalid_slug_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=_admin_headers,
        json={
            "slug": "Bad Slug With Spaces!",  # fails the pattern
            "translations": [{"locale": "ru", "name": "X"}],
        },
    )
    assert r.status_code == 422


# ---------- variable-amount SKUs ----------


async def _create_product_for_sku(
    integration_client: AsyncClient, admin_headers: dict[str, str], *, suffix: str
) -> str:
    """Category → brand → product boilerplate, returning the product id."""
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=admin_headers,
        json={
            "slug": f"var-cat-{suffix}",
            "translations": [{"locale": "ru", "name": "Категория"}],
        },
    )
    assert r.status_code == 201, r.text
    category_id = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=admin_headers,
        json={
            "slug": f"var-brand-{suffix}",
            "category_id": category_id,
            "translations": [{"locale": "ru", "name": "Бренд"}],
        },
    )
    assert r.status_code == 201, r.text
    brand_id = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/products",
        headers=admin_headers,
        json={
            "slug": f"var-product-{suffix}",
            "brand_id": brand_id,
            "kind": "top_up",
            "translations": [{"locale": "ru", "name": "Продукт"}],
        },
    )
    assert r.status_code == 201, r.text
    product_id: str = r.json()["id"]
    return product_id


async def test_create_variable_amount_sku_missing_bounds_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Turning variable_amount on without min/max/multiplier must fail
    validation before it ever reaches the DB CHECK — a readable 422, not
    an IntegrityError."""
    product_id = await _create_product_for_sku(integration_client, _admin_headers, suffix="missing")
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "steam-wallet-missing",
            "price_usd": "1",
            "variable_amount": True,
            # min_amount_usd, max_amount_usd, rate_multiplier all omitted.
        },
    )
    assert r.status_code == 422, r.text
    assert "variable_amount SKUs require" in r.text


async def test_create_and_update_variable_amount_sku_round_trip(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A complete variable-amount SKU round-trips through create, is visible
    on the admin response including rate_multiplier, is absent from the
    public SkuOut, and can have its variable-amount block toggled off via
    PATCH (which must actually clear the three companion fields)."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="roundtrip"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "steam-wallet-roundtrip",
            "price_usd": "1",
            "variable_amount": True,
            "min_amount_usd": "1",
            "max_amount_usd": "500",
            "rate_multiplier": "1.08",
        },
    )
    assert r.status_code == 201, r.text
    sku = r.json()
    sku_id = sku["id"]
    assert sku["variable_amount"] is True
    assert sku["min_amount_usd"] == "1"
    assert sku["max_amount_usd"] == "500"
    assert sku["rate_multiplier"] == "1.08"

    # The public SkuOut must never expose rate_multiplier — that's the margin.
    r = await integration_client.get(f"/api/v1/catalog/skus/{sku_id}")
    assert r.status_code == 200, r.text
    public_sku = r.json()
    assert "rate_multiplier" not in public_sku
    assert public_sku["variable_amount"] is True
    # Fetched fresh from the DB this time, so Numeric(20, 6) round-trips
    # with trailing zeros — compare numerically, not as literal strings.
    assert Decimal(public_sku["min_amount_usd"]) == Decimal("1")
    assert Decimal(public_sku["max_amount_usd"]) == Decimal("500")

    # Toggling variable_amount off must actually null the three fields, not
    # just leave them stale (the admin form always sends the full block).
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={
            "variable_amount": False,
            "min_amount_usd": None,
            "max_amount_usd": None,
            "rate_multiplier": None,
        },
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["variable_amount"] is False
    assert patched["min_amount_usd"] is None
    assert patched["max_amount_usd"] is None
    assert patched["rate_multiplier"] is None


async def test_create_and_update_sku_persists_margin_percent(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """margin_percent round-trips through create and PATCH — this is what
    the supplier price-refresh job reads back to re-derive price_usd when
    cost_usdt moves on its own (integrations.price_refresh)."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="margin-roundtrip"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "margin-roundtrip-sku",
            "price_usd": "12",
            "cost_usdt": "10",
            "margin_percent": "20",
        },
    )
    assert r.status_code == 201, r.text
    sku = r.json()
    sku_id = sku["id"]
    assert sku["margin_percent"] == "20"

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"margin_percent": "25"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["margin_percent"] == "25"

    # Never exposed on the public read side — same as cost_usdt/rate_multiplier.
    r = await integration_client.get(f"/api/v1/catalog/skus/{sku_id}")
    assert r.status_code == 200, r.text
    assert "margin_percent" not in r.json()


async def test_margin_percent_at_or_below_minus_100_is_rejected(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A margin that would zero out or invert price_usd is a 422 at the
    schema layer, before it ever reaches the DB's own check constraint."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="margin-floor"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "margin-floor-sku",
            "price_usd": "12",
            "margin_percent": "-100",
        },
    )
    assert r.status_code == 422, r.text


async def test_update_variable_amount_sku_missing_bounds_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """PATCHing variable_amount=true without the companion fields must be
    rejected exactly like create — the same DB CHECK applies either way."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="patch-missing"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "steam-wallet-patch-missing",
            "price_usd": "1",
        },
    )
    assert r.status_code == 201, r.text
    sku_id = r.json()["id"]

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"variable_amount": True},
    )
    assert r.status_code == 422, r.text
    assert "variable_amount SKUs require" in r.text


async def test_update_partial_max_amount_alone_persists_on_variable_sku(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A PATCH that only sends max_amount_usd against an already-variable SKU
    must actually persist the new ceiling, not silently no-op. Regression
    test: min/max/multiplier used to be written only inside the
    ``variable_amount is not None`` branch, so a partial edit that never
    touched ``variable_amount`` was dropped without an error."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="partial-max"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "steam-wallet-partial-max",
            "price_usd": "1",
            "variable_amount": True,
            "min_amount_usd": "1",
            "max_amount_usd": "500",
            "rate_multiplier": "1.08",
        },
    )
    assert r.status_code == 201, r.text
    sku_id = r.json()["id"]

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"max_amount_usd": "1000"},
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["max_amount_usd"] == "1000"
    # The fields this request didn't touch must survive untouched.
    assert Decimal(patched["min_amount_usd"]) == Decimal("1")
    assert Decimal(patched["rate_multiplier"]) == Decimal("1.08")
    assert patched["variable_amount"] is True


# ---------- unit-SKU (Telegram Stars) quantity bounds ----------


async def test_create_sku_with_qty_bounds_only_missing_max_returns_422(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Sending min_qty without max_qty (or vice versa) must fail validation
    before it ever reaches the DB CHECK — a readable 422, not an
    IntegrityError. Mirrors the variable_amount "missing bounds" case."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="qty-missing"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "stars-qty-missing",
            "price_usd": "0.02",
            "amount_unit": "Stars",
            "min_qty": 50,
            # max_qty omitted.
        },
    )
    assert r.status_code == 422, r.text
    assert "min_qty and max_qty must be set together" in r.text


async def test_create_and_update_unit_sku_qty_bounds_round_trip(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A complete unit SKU (Telegram Stars: amount_unit + min_qty/max_qty,
    NOT variable_amount) round-trips through create, is visible on the admin
    response, reaches the public SkuOut, and can have its bounds edited via a
    partial PATCH."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="qty-roundtrip"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "stars-qty-roundtrip",
            "price_usd": "0.02",
            "amount_unit": "Stars",
            "min_qty": 50,
            "max_qty": 2500,
        },
    )
    assert r.status_code == 201, r.text
    sku = r.json()
    sku_id = sku["id"]
    assert sku["min_qty"] == 50
    assert sku["max_qty"] == 2500
    assert sku["variable_amount"] is False

    # The public SkuOut must expose the bounds too, so the storefront can
    # clamp the customer's typed quantity.
    r = await integration_client.get(f"/api/v1/catalog/skus/{sku_id}")
    assert r.status_code == 200, r.text
    public_sku = r.json()
    assert public_sku["min_qty"] == 50
    assert public_sku["max_qty"] == 2500
    assert public_sku["amount_unit"] == "Stars"

    # Partial PATCH of max_qty alone must persist, leaving min_qty untouched
    # (same "sent, not None" convention as the variable-amount block).
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"max_qty": 5000},
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["max_qty"] == 5000
    assert patched["min_qty"] == 50


async def test_update_partial_min_qty_above_max_rejected(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A partial PATCH of min_qty alone that would push min above the SKU's
    existing max must be rejected 422 — proves the merged-row invariant is
    (re-)validated on partial edits, not just full ones."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="qty-partial-min"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "stars-qty-partial-min",
            "price_usd": "0.02",
            "amount_unit": "Stars",
            "min_qty": 50,
            "max_qty": 2500,
        },
    )
    assert r.status_code == 201, r.text
    sku_id = r.json()["id"]

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"min_qty": 3000},
    )
    assert r.status_code == 422, r.text
    assert "max_qty must be >= min_qty" in r.text


async def test_amount_unit_alone_with_qty_bounds_survives_variable_amount_false(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Regression guard: `update_sku`'s "clear amount fields when not
    variable_amount" branch must not wipe `amount_unit` off a unit SKU —
    unit SKUs are deliberately not variable_amount (see
    `unit_sku.is_unit_sku`). A PATCH that only edits an unrelated field
    (`active`) must leave `amount_unit`/`min_qty`/`max_qty` untouched."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="qty-survives"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "stars-qty-survives",
            "price_usd": "0.02",
            "amount_unit": "Stars",
            "min_qty": 50,
            "max_qty": 2500,
        },
    )
    assert r.status_code == 201, r.text
    sku_id = r.json()["id"]

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"active": False},
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["min_qty"] == 50
    assert patched["max_qty"] == 2500
    assert patched["active"] is False

    r = await integration_client.get(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        params={"product_id": product_id},
    )
    assert r.status_code == 200, r.text
    sku = next(s for s in r.json() if s["id"] == sku_id)
    assert sku["min_qty"] == 50
    assert sku["max_qty"] == 2500


async def test_update_partial_min_amount_above_max_rejected(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """A partial PATCH of min_amount_usd alone that would push min above the
    SKU's existing max must be rejected 422 — proves the merged-row
    invariant is (re-)validated on partial edits, not just full ones."""
    product_id = await _create_product_for_sku(
        integration_client, _admin_headers, suffix="partial-min"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "steam-wallet-partial-min",
            "price_usd": "1",
            "variable_amount": True,
            "min_amount_usd": "1",
            "max_amount_usd": "500",
            "rate_multiplier": "1.08",
        },
    )
    assert r.status_code == 201, r.text
    sku_id = r.json()["id"]

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}",
        headers=_admin_headers,
        json={"min_amount_usd": "600"},
    )
    assert r.status_code == 422, r.text
    assert "max_amount_usd must be >= min_amount_usd" in r.text

    # And the original row must be untouched — the failed PATCH didn't
    # partially apply.
    r = await integration_client.get(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        params={"product_id": product_id},
    )
    assert r.status_code == 200, r.text
    sku = next(s for s in r.json() if s["id"] == sku_id)
    assert Decimal(sku["min_amount_usd"]) == Decimal("1")


async def test_admin_lists_expose_b2b_read_side(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """``GET /admin/catalog/{brands,skus}`` must carry ``visible_b2b`` (and
    ``b2b_markup_pct`` on SKUs) so the admin SPA's B2B controls render the
    *current* state — the merchants-module PATCH endpoints under
    ``/admin/catalog/**/b2b`` are write-only, and without a read side the
    Task-8 switches would always show the column defaults."""
    product_id = await _create_product_for_sku(integration_client, _admin_headers, suffix="b2b")
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "b2b-read-sku",
            "price_usd": "9.99",
            "cost_usdt": "8.00",
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    sku_id = created["id"]
    # Defaults straight from the columns: hidden, 7% (Task 4's server_default).
    assert created["visible_b2b"] is False
    assert Decimal(created["b2b_markup_pct"]) == Decimal("7.00")

    r = await integration_client.get("/api/v1/admin/catalog/brands", headers=_admin_headers)
    assert r.status_code == 200, r.text
    brand = next(b for b in r.json() if b["slug"] == "var-brand-b2b")
    assert brand["visible_b2b"] is False

    # Flip everything through the merchants-module write endpoints…
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}/b2b",
        headers=_admin_headers,
        json={"markup_pct": "5.50", "visible_b2b": True},
    )
    assert r.status_code == 200, r.text
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/brands/{brand['id']}/b2b",
        headers=_admin_headers,
        json={"visible_b2b": True},
    )
    assert r.status_code == 200, r.text

    # …and read the new state back from the plain admin lists.
    r = await integration_client.get(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        params={"product_id": product_id},
    )
    assert r.status_code == 200, r.text
    sku = next(s for s in r.json() if s["id"] == sku_id)
    assert sku["visible_b2b"] is True
    assert Decimal(sku["b2b_markup_pct"]) == Decimal("5.50")

    r = await integration_client.get("/api/v1/admin/catalog/brands", headers=_admin_headers)
    brand = next(b for b in r.json() if b["slug"] == "var-brand-b2b")
    assert brand["visible_b2b"] is True


# ---------- flipping a product's kind to top_up ----------


async def _create_voucher_product_and_sku(
    integration_client: AsyncClient, admin_headers: dict[str, str], *, suffix: str
) -> tuple[str, str]:
    """Category → brand → voucher product → SKU boilerplate.

    Returns ``(product_id, sku_id)``. A voucher product is the starting
    point for the ``kind`` flip guard's tests — it's the only kind that can
    legally carry inventory codes or a ``force_inventory`` rule in the
    first place.
    """
    r = await integration_client.post(
        "/api/v1/admin/catalog/categories",
        headers=admin_headers,
        json={
            "slug": f"kind-flip-cat-{suffix}",
            "translations": [{"locale": "ru", "name": "Категория"}],
        },
    )
    assert r.status_code == 201, r.text
    category_id = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/brands",
        headers=admin_headers,
        json={
            "slug": f"kind-flip-brand-{suffix}",
            "category_id": category_id,
            "translations": [{"locale": "ru", "name": "Бренд"}],
        },
    )
    assert r.status_code == 201, r.text
    brand_id = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/products",
        headers=admin_headers,
        json={
            "slug": f"kind-flip-product-{suffix}",
            "brand_id": brand_id,
            "kind": "voucher",
            "translations": [{"locale": "ru", "name": "Продукт"}],
        },
    )
    assert r.status_code == 201, r.text
    product_id: str = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=admin_headers,
        json={
            "product_id": product_id,
            "sku_code": f"kind-flip-sku-{suffix}",
            "price_usd": "1.00",
        },
    )
    assert r.status_code == 201, r.text
    sku_id: str = r.json()["id"]
    return product_id, sku_id


async def test_update_product_flip_to_top_up_blocked_by_inventory_codes(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Flipping a voucher product to ``top_up`` while its SKU still has
    stocked inventory codes must be refused — those codes would fulfil
    nothing once the SKU is credited by a live supplier call instead."""
    product_id, sku_id = await _create_voucher_product_and_sku(
        integration_client, _admin_headers, suffix="stock"
    )
    r = await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers=_admin_headers,
        json={"sku_id": sku_id, "codes": ["KIND-FLIP-001", "KIND-FLIP-002"]},
    )
    assert r.status_code == 200, r.text

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/products/{product_id}",
        headers=_admin_headers,
        json={"kind": "top_up"},
    )
    assert r.status_code == 422, r.text
    assert "inventory codes" in r.text
    assert "1 SKU" in r.text

    # Refused, not silently ignored — the product's kind is unchanged.
    r = await integration_client.get("/api/v1/admin/catalog/products", headers=_admin_headers)
    product = next(p for p in r.json() if p["id"] == product_id)
    assert product["kind"] == "voucher"


async def test_update_product_flip_to_top_up_blocked_by_force_inventory_rule(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Flipping to ``top_up`` while a SKU carries an explicit
    ``force_inventory`` sourcing rule must be refused — that rule would
    become a guaranteed ``NoStockError`` with no fallback the moment the
    product becomes top_up."""
    product_id, sku_id = await _create_voucher_product_and_sku(
        integration_client, _admin_headers, suffix="rule"
    )
    r = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{sku_id}",
        headers=_admin_headers,
        json={"mode": "force_inventory"},
    )
    assert r.status_code == 200, r.text

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/products/{product_id}",
        headers=_admin_headers,
        json={"kind": "top_up"},
    )
    assert r.status_code == 422, r.text
    assert "force_inventory" in r.text
    assert "1 SKU" in r.text


async def test_update_product_flip_to_top_up_allowed_when_clear(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Control case: a voucher product with no inventory codes and no
    ``force_inventory`` rule on any of its SKUs may still be flipped to
    ``top_up`` — the guard is specific to the two states it exists to
    prevent, not a blanket refusal of the flip."""
    product_id, _sku_id = await _create_voucher_product_and_sku(
        integration_client, _admin_headers, suffix="clear"
    )
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/products/{product_id}",
        headers=_admin_headers,
        json={"kind": "top_up"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "top_up"


async def test_update_product_flip_to_top_up_reports_both_blockers(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    """Both blockers can fire together, on different SKUs of the same
    product — the error must name both, not just whichever the guard
    happened to check first, so an operator sees the full clean-up list in
    one round trip."""
    product_id, sku_with_stock = await _create_voucher_product_and_sku(
        integration_client, _admin_headers, suffix="both"
    )
    r = await integration_client.post(
        "/api/v1/admin/catalog/skus",
        headers=_admin_headers,
        json={
            "product_id": product_id,
            "sku_code": "kind-flip-sku-both-2",
            "price_usd": "1.00",
        },
    )
    assert r.status_code == 201, r.text
    sku_with_rule = r.json()["id"]

    r = await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers=_admin_headers,
        json={"sku_id": sku_with_stock, "codes": ["KIND-FLIP-BOTH-001"]},
    )
    assert r.status_code == 200, r.text
    r = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{sku_with_rule}",
        headers=_admin_headers,
        json={"mode": "force_inventory"},
    )
    assert r.status_code == 200, r.text

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/products/{product_id}",
        headers=_admin_headers,
        json={"kind": "top_up"},
    )
    assert r.status_code == 422, r.text
    assert "inventory codes" in r.text
    assert "force_inventory" in r.text
