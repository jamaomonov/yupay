"""Integration tests for ``GET /api/v1/admin/sourcing/brands/{brand_slug}``.

Covers:
- one row per active SKU of the brand; an inactive SKU is excluded
- the reported route matches ``sourcing.resolve_for_sku`` for every SKU
- a reserve supplier (nova) never appears as the live route, even with an
  older active mapping than the incumbent (ADR-0081)
- a candidate supplier with no mapping at all reports
  ``has_active_mapping=False`` and no cost
- the latest ``supplier_price_history`` row wins when several exist
- 404 for an unknown brand slug
- 403 for a non-admin caller
- bounded SQL query count — adding SKUs must not grow it (no N+1)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import event
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
from yupay.modules.integrations.models import SkuSupplierMapping, SupplierPriceHistory
from yupay.modules.sourcing import service as sourcing_svc
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
    body: dict[str, str] = r.json()
    return body["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    from sqlalchemy import select, update

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
    token = await _login_user(integration_client, tg_id=9001)
    await _grant_admin(db_session, tg_id=9001)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:
    """Counts every cursor execution on the engine the app is wired to.

    Copied from ``test_orders_routes.py`` (AGENTS.md §10: every list endpoint
    must have an integration test asserting query count) — duplicated
    locally rather than imported, matching this suite's existing convention
    of per-file test helpers.
    """
    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def _measure_get(
    client: AsyncClient, counter: dict[str, int], url: str, headers: dict[str, str]
) -> int:
    counter["n"] = 0
    r = await client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    assert counter["n"] > 0, "sql_counter saw no queries — listener not wired to the app engine"
    return counter["n"]


async def _seed_category_and_brand(db: AsyncSession, *, brand_slug: str) -> tuple[str, str]:
    category = Category(
        id=new_id(),
        slug=f"cat-{brand_slug}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=brand_slug,
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name=brand_slug)],
    )
    db.add_all([category, brand])
    await db.flush()
    return category.id, brand.id


async def _make_product(db: AsyncSession, *, brand_id: str, slug: str, kind: str) -> str:
    product = Product(
        id=new_id(),
        slug=slug,
        brand_id=brand_id,
        kind=kind,
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug)],
    )
    db.add(product)
    await db.flush()
    return product.id


async def _make_sku(
    db: AsyncSession,
    *,
    product_id: str,
    sku_code: str,
    active: bool = True,
    price_usd: Decimal = Decimal("1.00"),
    cost_usdt: Decimal | None = None,
) -> str:
    sku = Sku(
        id=new_id(),
        product_id=product_id,
        sku_code=sku_code,
        denomination="100",
        region="WW",
        price_usd=price_usd,
        cost_usdt=cost_usdt,
        sort_order=10,
        active=active,
    )
    db.add(sku)
    await db.flush()
    return sku.id


async def _make_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    supplier_slug: str,
    kind: str = "game",
    is_active: bool = True,
    created_at: datetime | None = None,
) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug=supplier_slug,
            kind=kind,
            external_product_id="ext-1",
            external_variant_id="100",
            quantity=1,
            extra={},
            is_active=is_active,
            created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await db.flush()


async def _make_history(
    db: AsyncSession,
    *,
    sku_id: str,
    supplier_slug: str,
    cost_usdt: Decimal,
    captured_at: datetime,
) -> None:
    db.add(
        SupplierPriceHistory(
            id=new_id(),
            sku_id=sku_id,
            supplier_slug=supplier_slug,
            kind="game",
            external_product_id="ext-1",
            external_variant_id="100",
            cost_usdt=cost_usdt,
            captured_at=captured_at,
        )
    )
    await db.flush()


@pytest.fixture
async def _seed_brand(db_session: AsyncSession) -> dict[str, str]:
    """A brand with two products, several SKUs, mixed mappings and one
    explicit rule — matches the task-3-brief scenario verbatim.

    - sku1 (top_up): active g2b mapping (incumbent) + an *older* active nova
      mapping — nova is a reserve (ADR-0081) and must never win despite
      being older. Two g2b price-history rows so the latest one must win.
      gengine has no mapping at all for this SKU.
    - sku2 (top_up): explicit ``force_supplier`` rule onto gengine (needs an
      active gengine mapping to pass ``set_rule``'s validation guard).
    - sku3 (voucher): no mapping at all — auto-routes to inventory.
    - sku4 (top_up, INACTIVE): must not appear in the response at all.
    """
    brand_slug = "mlbb-overview-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_a = await _make_product(
        db_session, brand_id=brand_id, slug="mlbb-diamonds-test", kind="top_up"
    )
    product_b = await _make_product(
        db_session, brand_id=brand_id, slug="mlbb-gift-test", kind="voucher"
    )

    sku1 = await _make_sku(db_session, product_id=product_a, sku_code="mlbb-sku1-test")
    sku2 = await _make_sku(db_session, product_id=product_a, sku_code="mlbb-sku2-test")
    sku3 = await _make_sku(db_session, product_id=product_b, sku_code="mlbb-sku3-test")
    sku4 = await _make_sku(
        db_session, product_id=product_a, sku_code="mlbb-sku4-test", active=False
    )

    await _make_mapping(
        db_session,
        sku_id=sku1,
        supplier_slug="g2b",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await _make_mapping(
        db_session,
        sku_id=sku1,
        supplier_slug="nova",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),  # older, but a reserve
    )
    await _make_history(
        db_session,
        sku_id=sku1,
        supplier_slug="g2b",
        cost_usdt=Decimal("1.000000"),
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    await _make_history(
        db_session,
        sku_id=sku1,
        supplier_slug="g2b",
        cost_usdt=Decimal("1.500000"),
        captured_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    await _make_history(
        db_session,
        sku_id=sku1,
        supplier_slug="nova",
        cost_usdt=Decimal("2.000000"),
        captured_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    await _make_mapping(db_session, sku_id=sku2, supplier_slug="gengine")
    await db_session.commit()

    await sourcing_svc.set_rule(
        db_session,
        sku_id=sku2,
        mode="force_supplier",
        supplier_slug="gengine",
        admin_id="test-admin",
    )
    await db_session.commit()

    return {
        "brand_slug": brand_slug,
        "sku1": sku1,
        "sku2": sku2,
        "sku3": sku3,
        "sku4": sku4,
    }


async def test_overview_reports_one_row_per_active_sku(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    sku_ids = {item["sku_id"] for item in items}

    # sku4 is inactive — excluded.
    assert sku_ids == {_seed_brand["sku1"], _seed_brand["sku2"], _seed_brand["sku3"]}


async def test_overview_route_matches_resolve_for_sku(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    for key in ("sku1", "sku2", "sku3"):
        sku_id = _seed_brand[key]
        decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
        assert by_sku[sku_id]["primary"] == decision.primary, key
        assert by_sku[sku_id]["rule_present"] == decision.rule_present, key

    # Concrete expectations, not just "matches the service": sku1 must route
    # to g2b (the incumbent), never nova (reserve, older mapping or not).
    assert by_sku[_seed_brand["sku1"]]["primary"] == "supplier:g2b"
    assert by_sku[_seed_brand["sku1"]]["rule_present"] is False
    # sku2 carries an explicit force_supplier rule onto gengine.
    assert by_sku[_seed_brand["sku2"]]["primary"] == "supplier:gengine"
    assert by_sku[_seed_brand["sku2"]]["rule_present"] is True
    # sku3 (voucher, no mapping) is inventory-first by kind default.
    assert by_sku[_seed_brand["sku3"]]["primary"] == "inventory"
    assert by_sku[_seed_brand["sku3"]]["rule_present"] is False


async def test_overview_supplier_comparison_list(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    sku1_suppliers = {s["supplier_slug"]: s for s in by_sku[_seed_brand["sku1"]]["suppliers"]}
    assert set(sku1_suppliers) == {"g2b", "gengine", "nova"}

    # g2b: active mapping, latest of two history rows (1.5, not 1.0) wins.
    assert sku1_suppliers["g2b"]["has_active_mapping"] is True
    assert Decimal(sku1_suppliers["g2b"]["latest_cost_usdt"]) == Decimal("1.5")
    assert sku1_suppliers["g2b"]["captured_at"].startswith("2026-06-01")

    # nova: active mapping (a reserve — reported, just never routed to).
    assert sku1_suppliers["nova"]["has_active_mapping"] is True
    assert Decimal(sku1_suppliers["nova"]["latest_cost_usdt"]) == Decimal("2.0")

    # gengine: no mapping at all on this SKU — the exact case the brief
    # calls out: has_active_mapping=false and no cost.
    assert sku1_suppliers["gengine"]["has_active_mapping"] is False
    assert sku1_suppliers["gengine"]["latest_cost_usdt"] is None
    assert sku1_suppliers["gengine"]["captured_at"] is None

    # sku2: only gengine is mapped (and it's the forced route).
    sku2_suppliers = {s["supplier_slug"]: s for s in by_sku[_seed_brand["sku2"]]["suppliers"]}
    assert sku2_suppliers["gengine"]["has_active_mapping"] is True
    assert sku2_suppliers["g2b"]["has_active_mapping"] is False
    assert sku2_suppliers["g2b"]["latest_cost_usdt"] is None
    assert sku2_suppliers["nova"]["has_active_mapping"] is False


async def test_overview_sku_fields(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}
    row = by_sku[_seed_brand["sku1"]]
    assert row["sku_code"] == "mlbb-sku1-test"
    assert row["denomination"] == "100"
    assert row["product_slug"] == "mlbb-diamonds-test"
    assert Decimal(row["price_usd"]) == Decimal("1.00")


async def test_overview_unknown_brand_404s(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/sourcing/brands/does-not-exist",
        headers=_admin_headers,
    )
    assert r.status_code == 404


async def test_overview_non_admin_forbidden(
    integration_client: AsyncClient,
    _seed_brand: dict[str, str],
) -> None:
    token = await _login_user(integration_client, tg_id=9002)
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


async def test_overview_sql_query_count_is_bounded(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    db_engine,
    _admin_headers: dict[str, str],
    sql_counter: dict[str, int],
) -> None:
    """Adding more SKUs (each with its own mapping + history row) must not
    grow the query count — the three N+1s the brief calls out: resolving
    the route, reading mappings, and reading price history per row."""
    brand_slug = "query-count-brand-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="query-count-product-test", kind="top_up"
    )

    async def _add_sku(n: int) -> None:
        sku_id = await _make_sku(db_session, product_id=product_id, sku_code=f"qc-sku-{n}-test")
        await _make_mapping(db_session, sku_id=sku_id, supplier_slug="g2b")
        await _make_history(
            db_session,
            sku_id=sku_id,
            supplier_slug="g2b",
            cost_usdt=Decimal("1.000000"),
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    for n in range(2):
        await _add_sku(n)
    await db_session.commit()

    url = f"/api/v1/admin/sourcing/brands/{brand_slug}"
    small_count = await _measure_get(integration_client, sql_counter, url, _admin_headers)

    for n in range(2, 6):
        await _add_sku(n)
    await db_session.commit()

    large_count = await _measure_get(integration_client, sql_counter, url, _admin_headers)

    assert large_count == small_count, (
        f"query count grew from {small_count} to {large_count} as SKUs were added — N+1"
    )
