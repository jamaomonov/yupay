"""Integration tests for import_game — atomic brand+product+sku+mapping."""

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
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, CategoryTranslation, Product, Sku
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.schemas import (
    DenomImportIn,
    GameImportIn,
    NewBrandIn,
    ProductImportIn,
)
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio


async def _seed_category(db: AsyncSession) -> str:
    cat = Category(id=new_id(), slug="games", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()
    return cat.id


def _payload_new_brand(category_id: str) -> GameImportIn:
    return GameImportIn(
        game_code="pubgmobile",
        target="new_brand",
        new_brand=NewBrandIn(slug="pubg-mobile", category_id=category_id, name="PUBG Mobile"),
        product=ProductImportIn(slug="pubg-uc", name="PUBG UC"),
        margin_percent=Decimal("20"),
        denominations=[
            DenomImportIn(
                catalogue_name="60 UC",
                denomination="60 UC",
                sku_code="g2b-pubg-60",
                cost_usdt=Decimal("0.85"),
            ),
            DenomImportIn(
                catalogue_name="300 UC",
                denomination="300 UC",
                sku_code="g2b-pubg-300",
                cost_usdt=Decimal("4.00"),
                price_usd_override=Decimal("5.99"),
            ),
        ],
    )


async def test_import_new_brand_creates_everything(db_session: AsyncSession) -> None:
    cat = await _seed_category(db_session)
    result = await svc.import_game(db_session, _payload_new_brand(cat), admin_id="admin-1")

    assert result.created_skus == 2
    assert result.created_mappings == 2
    assert result.skipped == []

    brand = (
        await db_session.execute(select(Brand).where(Brand.id == result.brand_id))
    ).scalar_one()
    assert brand.slug == "pubg-mobile"
    assert {t.locale for t in brand.translations} == {"ru", "en", "uz"}

    product = (
        await db_session.execute(select(Product).where(Product.id == result.product_id))
    ).scalar_one()
    assert product.kind == "top_up"
    assert product.supplier_hint == "g2b"

    skus = (
        (
            await db_session.execute(
                select(Sku).where(Sku.product_id == result.product_id).order_by(Sku.sku_code)
            )
        )
        .scalars()
        .all()
    )
    by_code = {s.sku_code: s for s in skus}
    assert by_code["g2b-pubg-60"].price_usd == Decimal("1.02")
    assert by_code["g2b-pubg-60"].cost_usdt == Decimal("0.85")
    assert by_code["g2b-pubg-300"].price_usd == Decimal("5.99")

    mappings = (
        (
            await db_session.execute(
                select(SkuSupplierMapping).where(SkuSupplierMapping.supplier_slug == "g2b")
            )
        )
        .scalars()
        .all()
    )
    assert len(mappings) == 2
    m = next(x for x in mappings if x.external_variant_id == "60 UC")
    assert m.kind == "game"
    assert m.external_product_id == "pubgmobile"


async def test_import_existing_brand_adds_product(db_session: AsyncSession) -> None:
    cat = await _seed_category(db_session)
    first = await svc.import_game(db_session, _payload_new_brand(cat), admin_id="a")
    payload = GameImportIn(
        game_code="pubgmobile",
        target="existing_brand",
        brand_id=first.brand_id,
        product=ProductImportIn(slug="pubg-royal", name="PUBG Royal Pass"),
        margin_percent=Decimal("10"),
        denominations=[
            DenomImportIn(
                catalogue_name="Elite",
                denomination="Elite",
                sku_code="g2b-pubg-elite",
                cost_usdt=Decimal("9.00"),
            )
        ],
    )
    result = await svc.import_game(db_session, payload, admin_id="a")
    assert result.brand_id == first.brand_id
    brands = (await db_session.execute(select(Brand))).scalars().all()
    assert len(brands) == 1


async def test_reimport_skips_existing_sku(db_session: AsyncSession) -> None:
    cat = await _seed_category(db_session)
    await svc.import_game(db_session, _payload_new_brand(cat), admin_id="a")
    payload = GameImportIn(
        game_code="pubgmobile",
        target="existing_brand",
        brand_id=(await db_session.execute(select(Brand.id))).scalar_one(),
        product=ProductImportIn(slug="pubg-uc-2", name="PUBG UC v2"),
        margin_percent=Decimal("20"),
        denominations=[
            DenomImportIn(
                catalogue_name="60 UC",
                denomination="60 UC",
                sku_code="g2b-pubg-60",
                cost_usdt=Decimal("0.85"),
            ),
            DenomImportIn(
                catalogue_name="1800 UC",
                denomination="1800 UC",
                sku_code="g2b-pubg-1800",
                cost_usdt=Decimal("20.00"),
            ),
        ],
    )
    result = await svc.import_game(db_session, payload, admin_id="a")
    assert result.skipped == ["g2b-pubg-60"]
    assert result.created_skus == 1


async def test_duplicate_brand_slug_raises_conflict(db_session: AsyncSession) -> None:
    cat = await _seed_category(db_session)
    await svc.import_game(db_session, _payload_new_brand(cat), admin_id="a")
    with pytest.raises(ConflictError):
        await svc.import_game(
            db_session,
            GameImportIn(
                game_code="pubgmobile",
                target="new_brand",
                new_brand=NewBrandIn(slug="pubg-mobile", category_id=cat, name="PUBG Mobile"),
                product=ProductImportIn(slug="pubg-uc-other", name="PUBG UC"),
                margin_percent=Decimal("20"),
                denominations=[
                    DenomImportIn(
                        catalogue_name="60 UC",
                        denomination="60 UC",
                        sku_code="x-60",
                        cost_usdt=Decimal("0.85"),
                    )
                ],
            ),
            admin_id="a",
        )


# ---------- HTTP endpoint ----------

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    signed = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(signed)


async def _login_admin(client: AsyncClient, db: AsyncSession, tg_id: int = 555) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "A"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return r.json()["access_token"]


async def test_import_endpoint_creates_brand(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    cat = await _seed_category(db_session)
    await db_session.commit()
    token = await _login_admin(integration_client, db_session)
    body = {
        "game_code": "pubgmobile",
        "target": "new_brand",
        "new_brand": {"slug": "pubg-mobile", "category_id": cat, "name": "PUBG Mobile"},
        "product": {"slug": "pubg-uc", "name": "PUBG UC"},
        "margin_percent": "20",
        "denominations": [
            {
                "catalogue_name": "60 UC",
                "denomination": "60 UC",
                "sku_code": "g2b-pubg-60",
                "cost_usdt": "0.85",
            }
        ],
    }
    r = await integration_client.post(
        "/api/v1/admin/integrations/g2b/import",
        json=body,
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "imp-1"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["created_skus"] == 1
    assert data["created_mappings"] == 1


async def test_import_endpoint_requires_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.post("/api/v1/admin/integrations/g2b/import", json={})
    assert r.status_code in (401, 403)
