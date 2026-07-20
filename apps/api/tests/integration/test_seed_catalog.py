"""Integration tests for ``yupay.scripts.seed_catalog``.

Covers the Steam wallet top-up SKU specifically: it is the seed's first
variable-amount, non-G2B entry, so it exercises two branches the G2B-only
seed never touched before — the ``SkuSourcingRule`` upsert (instead of a
``SkuSupplierMapping``) and the four new ``Sku`` columns.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.modules.catalog.models import Brand, Sku
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.scripts import seed_catalog

pytestmark = pytest.mark.asyncio


async def _run_seed(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """Run ``seed_catalog.seed()`` against the test container.

    ``seed()`` resolves its own session factory via ``get_session_factory()``,
    which is bound to the app's real (non-test) engine — swap the name the
    script actually calls, mirroring how ``integration_client`` in conftest
    redirects ``yupay.core.db``'s module-level engine for the app itself.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(seed_catalog, "get_session_factory", lambda: factory)
    await seed_catalog.seed()


async def test_steam_sku_is_variable_amount_and_routed_to_waxpeer(
    db_engine, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_seed(monkeypatch, db_engine)

    sku = (
        await db_session.execute(select(Sku).where(Sku.sku_code == "steam-wallet-usd"))
    ).scalar_one()
    assert sku.variable_amount is True
    assert sku.min_amount_usd == Decimal("1.000000")
    assert sku.max_amount_usd == Decimal("300.000000")
    assert sku.rate_multiplier == Decimal("1.0800")
    assert sku.price_usd == Decimal("1.000000")

    rule = (
        await db_session.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku.id))
    ).scalar_one()
    assert rule.mode == "force_supplier"
    assert rule.supplier_slug == "waxpeer"

    # Waxpeer is never routed through a SkuSupplierMapping (its Fulfiller reads
    # steam_login straight off fulfillment_data) — the seed must not write one.
    mapping_count = (
        await db_session.execute(
            select(func.count())
            .select_from(SkuSupplierMapping)
            .where(SkuSupplierMapping.sku_id == sku.id)
        )
    ).scalar_one()
    assert mapping_count == 0


async def test_seed_is_idempotent_for_steam(
    db_engine, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_seed(monkeypatch, db_engine)
    await _run_seed(monkeypatch, db_engine)

    steam_sku_count = (
        await db_session.execute(
            select(func.count()).select_from(Sku).where(Sku.sku_code == "steam-wallet-usd")
        )
    ).scalar_one()
    assert steam_sku_count == 1

    steam_brand_count = (
        await db_session.execute(
            select(func.count()).select_from(Brand).where(Brand.slug == "steam")
        )
    ).scalar_one()
    assert steam_brand_count == 1

    rule_count = (
        await db_session.execute(select(func.count()).select_from(SkuSourcingRule))
    ).scalar_one()
    assert rule_count == 1


async def test_g2b_mapping_count_matches_g2b_sku_count(
    db_engine, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Steam skip-branch must not affect the pre-existing G2B mapping upsert."""
    await _run_seed(monkeypatch, db_engine)

    g2b_sku_count = (
        await db_session.execute(
            select(func.count()).select_from(Sku).where(Sku.variable_amount.is_(False))
        )
    ).scalar_one()
    g2b_mapping_count = (
        await db_session.execute(
            select(func.count())
            .select_from(SkuSupplierMapping)
            .where(SkuSupplierMapping.supplier_slug == "g2b")
        )
    ).scalar_one()
    assert g2b_mapping_count == g2b_sku_count
    assert g2b_sku_count > 0
