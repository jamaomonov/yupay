"""Integration tests for catalog B2B visibility flags (migration 0068).

``visible_b2b`` on :class:`Brand` and :class:`Sku`, plus ``b2b_markup_pct`` on
:class:`Sku`, gate the merchant catalog independently of ``active`` (retail
visibility) — see the comments on both models for the exact pairing rule:
``active`` stays retail-only, ``visible_b2b`` is the merchant-catalog gate,
and effective B2B visibility is ``brand.visible_b2b AND sku.visible_b2b``.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from yupay.core import config as cfg
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

pytestmark = pytest.mark.asyncio


def _alembic_config() -> Config:
    """Build an ``alembic.config.Config`` pointed at the running test database.

    Mirrors ``tests/integration/conftest.py::_apply_migrations`` — Alembic's
    ``env.py`` actually resolves the URL from ``yupay.core.config.get_settings()``
    (already pinned to the testcontainer by the session fixture), so setting
    ``sqlalchemy.url`` here is belt-and-suspenders, not load-bearing.
    """
    api_dir = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(api_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(api_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", cfg.get_settings().database_url)
    return alembic_cfg


async def test_new_brand_defaults_to_b2b_hidden(db_session: AsyncSession) -> None:
    """A freshly created brand starts outside the merchant catalog."""
    category = Category(
        id=new_id(),
        slug="b2b-default-cat",
        sort_order=0,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Тест")],
    )
    brand = Brand(
        id=new_id(),
        slug="b2b-default-brand",
        category_id=category.id,
        sort_order=0,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Тест")],
    )
    db_session.add(category)
    db_session.add(brand)
    await db_session.commit()

    row = (await db_session.execute(select(Brand).where(Brand.id == brand.id))).scalar_one()
    assert row.visible_b2b is False


async def test_markup_default_is_seven_percent(db_session: AsyncSession) -> None:
    """A freshly created SKU carries the spec's 7% default wholesale markup."""
    category = Category(
        id=new_id(),
        slug="b2b-markup-cat",
        sort_order=0,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Тест")],
    )
    brand = Brand(
        id=new_id(),
        slug="b2b-markup-brand",
        category_id=category.id,
        sort_order=0,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Тест")],
    )
    product = Product(
        id=new_id(),
        slug="b2b-markup-product",
        brand_id=brand.id,
        kind="top_up",
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Тест")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="b2b-markup-sku",
        price_usd=Decimal("1.00"),
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()

    row = (await db_session.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    assert row.b2b_markup_pct == Decimal("7")
    assert row.visible_b2b is False


async def test_migration_flipped_existing_topup_brands(db_engine) -> None:
    """0068's launch backfill flips ``visible_b2b`` for pre-existing data.

    Seeds catalog rows against the schema as it stood at 0067 (before 0068's
    columns exist), upgrades to head, then checks the backfill: active
    top-up/voucher brands and their active SKUs flip to ``visible_b2b=True``,
    while the ``gift-cards`` category, the ``steam-gifts`` brand, an inactive
    brand, and a brand whose only SKU is inactive all stay ``False``.

    Seeding uses raw SQL rather than the ORM: ``yupay.modules.catalog.models``
    already declares ``visible_b2b``/``b2b_markup_pct`` in the shared
    metadata, so an ORM insert always asks Postgres to ``RETURNING`` them —
    which fails while the columns don't physically exist yet, pre-0068.
    """
    alembic_cfg = _alembic_config()
    settings = cfg.get_settings()

    await asyncio.to_thread(command.downgrade, alembic_cfg, "0067_wallet_merchant_deposit")
    try:
        seed_engine = create_async_engine(settings.database_url, future=True)
        try:
            async with seed_engine.begin() as conn:
                games_id = new_id()
                gift_cards_id = new_id()
                await conn.execute(
                    text(
                        "INSERT INTO categories (id, slug, sort_order, active) "
                        "VALUES (:id, :slug, 0, true)"
                    ),
                    [
                        {"id": games_id, "slug": "b2b-mig-games"},
                        {"id": gift_cards_id, "slug": "gift-cards"},
                    ],
                )

                def _brand(slug: str, category_id: str, active: bool) -> dict[str, Any]:
                    return {
                        "id": new_id(),
                        "slug": slug,
                        "category_id": category_id,
                        "active": active,
                    }

                brands = {
                    "eligible": _brand("b2b-mig-eligible", games_id, True),
                    "gift": _brand("b2b-mig-giftcard", gift_cards_id, True),
                    "steam_gift": _brand("steam-gifts", games_id, True),
                    "inactive": _brand("b2b-mig-inactive", games_id, False),
                    "dead_skus": _brand("b2b-mig-dead-skus", games_id, True),
                }
                await conn.execute(
                    text(
                        "INSERT INTO brands (id, slug, category_id, sort_order, active) "
                        "VALUES (:id, :slug, :category_id, 0, :active)"
                    ),
                    list(brands.values()),
                )

                def _product(slug: str, brand_id: str, kind: str) -> dict[str, Any]:
                    return {"id": new_id(), "slug": slug, "brand_id": brand_id, "kind": kind}

                products = {
                    "eligible": _product("b2b-mig-eligible-p", brands["eligible"]["id"], "top_up"),
                    "gift": _product("b2b-mig-gift-p", brands["gift"]["id"], "voucher"),
                    "steam_gift": _product(
                        "b2b-mig-steam-gift-p", brands["steam_gift"]["id"], "top_up"
                    ),
                    "inactive": _product("b2b-mig-inactive-p", brands["inactive"]["id"], "top_up"),
                    "dead_skus": _product(
                        "b2b-mig-dead-skus-p", brands["dead_skus"]["id"], "top_up"
                    ),
                }
                await conn.execute(
                    text(
                        "INSERT INTO products (id, slug, brand_id, kind, active, required_fields) "
                        "VALUES (:id, :slug, :brand_id, :kind, true, '[]'::jsonb)"
                    ),
                    list(products.values()),
                )

                def _sku(code: str, product_id: str, active: bool) -> dict[str, Any]:
                    return {
                        "id": new_id(),
                        "sku_code": code,
                        "product_id": product_id,
                        "active": active,
                    }

                skus = {
                    "eligible": _sku("b2b-mig-eligible-sku", products["eligible"]["id"], True),
                    "gift": _sku("b2b-mig-gift-sku", products["gift"]["id"], True),
                    "steam_gift": _sku(
                        "b2b-mig-steam-gift-sku", products["steam_gift"]["id"], True
                    ),
                    "inactive": _sku("b2b-mig-inactive-sku", products["inactive"]["id"], True),
                    "dead": _sku("b2b-mig-dead-sku", products["dead_skus"]["id"], False),
                }
                await conn.execute(
                    text(
                        "INSERT INTO skus (id, product_id, sku_code, price_usd, active) "
                        "VALUES (:id, :product_id, :sku_code, 1.00, :active)"
                    ),
                    list(skus.values()),
                )
        finally:
            await seed_engine.dispose()
    finally:
        # Always restore head — even if seeding above raised — so a failure here
        # never leaves the shared testcontainer mid-migration for later tests.
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    check_engine = create_async_engine(settings.database_url, future=True)
    try:
        async with check_engine.connect() as conn:
            brand_result = await conn.execute(
                text(
                    "SELECT slug, visible_b2b FROM brands "
                    "WHERE slug LIKE 'b2b-mig-%' OR slug = 'steam-gifts'"
                )
            )
            brand_rows: dict[str, bool] = {row.slug: row.visible_b2b for row in brand_result}
            sku_result = await conn.execute(
                text("SELECT sku_code, visible_b2b FROM skus WHERE sku_code LIKE 'b2b-mig-%'")
            )
            sku_rows: dict[str, bool] = {row.sku_code: row.visible_b2b for row in sku_result}
    finally:
        await check_engine.dispose()

    assert brand_rows == {
        "b2b-mig-eligible": True,
        "b2b-mig-giftcard": False,
        "steam-gifts": False,
        "b2b-mig-inactive": False,
        "b2b-mig-dead-skus": False,
    }
    assert sku_rows == {
        "b2b-mig-eligible-sku": True,
        "b2b-mig-gift-sku": False,
        "b2b-mig-steam-gift-sku": False,
        "b2b-mig-inactive-sku": False,
        "b2b-mig-dead-sku": False,
    }
